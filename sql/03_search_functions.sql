-- Drop prior signatures first. Each search function has gained parameters over time
-- (the four RRF-tuning params, then a trailing p_principal jsonb for ACL enforcement),
-- and adding a parameter creates a NEW overload rather than replacing in place, so we
-- drop every prior signature explicitly. These IF EXISTS drops keep re-applying this
-- file idempotent on a database that already has an earlier definition.
DROP FUNCTION IF EXISTS ops.hybrid_search(text, vector, text[], text[], text[], text[], text, text, text, timestamptz, timestamptz, int);
DROP FUNCTION IF EXISTS ops.hybrid_search(text, vector, text[], text[], text[], text[], text, text, text, timestamptz, timestamptz, int, int, numeric, numeric, numeric);
DROP FUNCTION IF EXISTS ops.full_text_search(text, text[], text[], text[], text[], text, text, text, timestamptz, timestamptz, int);
DROP FUNCTION IF EXISTS ops.vector_search(vector, text[], text[], text[], text[], text, text, text, timestamptz, timestamptz, int);
DROP FUNCTION IF EXISTS ops.fuzzy_match(text, numeric, text[], text[], text[], text[], text, text, text, timestamptz, timestamptz, int);

CREATE OR REPLACE FUNCTION ops.rrf(rank_position int, k int DEFAULT 60)
RETURNS numeric
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE WHEN rank_position IS NULL THEN 0 ELSE 1.0 / (k + rank_position) END;
$$;

-- ACL predicate, in one place so every retrieval arm enforces it identically.
-- Returns TRUE when a principal may see an object with the given acl.
--   * p_principal IS NULL  -> unauthenticated/default context: no ACL filtering, so
--     existing callers and the canonical demo are unchanged (every object visible).
--   * otherwise the object is visible when its visibility label is in the principal's
--     clearances array: p_principal->'clearances' @> to_jsonb(visibility). Objects
--     with no explicit acl visibility default to 'workshop_lab' (the corpus baseline),
--     which every workshop principal carries, so only objects explicitly marked with a
--     restricted label are hidden from a principal lacking that clearance.
CREATE OR REPLACE FUNCTION ops.acl_visible(p_acl jsonb, p_principal jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT p_principal IS NULL
      OR coalesce(p_principal -> 'clearances', '[]'::jsonb)
           @> to_jsonb(coalesce(p_acl ->> 'visibility', 'workshop_lab'));
$$;

-- Single home for the OR-combine invariant used by every lexical arm.
-- websearch_to_tsquery defaults to AND ('orion <-> -1489' & 'page' & 'prod' &
-- 'fix'), which drops any chunk missing even one term -> every row scores
-- text_rank = 0, silently disabling full-text search inside a natural-language
-- question. Rewriting the top-level '&' to '|' keeps the exact-ID phrase intact
-- ('orion' <-> '-1489') but lets partial matches rank by ts_rank_cd, so a strong
-- lexical hit like the Jira ID ORION-1489 surfaces first. ops.hybrid_search and
-- ops.full_text_search both call this, so the rewrite lives in exactly one place.
-- Do not reintroduce AND-semantics here or the exact-ID teaching moment breaks in
-- every lexical caller at once.
CREATE OR REPLACE FUNCTION ops.to_or_tsquery(p_query text)
RETURNS tsquery
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT replace(websearch_to_tsquery('english', p_query)::text, ' & ', ' | ')::tsquery;
$$;

CREATE OR REPLACE FUNCTION ops.hybrid_search(
  p_query text,
  p_query_embedding vector(1024),
  p_source_systems text[] DEFAULT NULL,
  p_source_types text[] DEFAULT NULL,
  p_statuses text[] DEFAULT NULL,
  p_priorities text[] DEFAULT NULL,
  p_project_key text DEFAULT NULL,
  p_account_name text DEFAULT NULL,
  p_component text DEFAULT NULL,
  p_start_date timestamptz DEFAULT NULL,
  p_end_date timestamptz DEFAULT NULL,
  p_limit int DEFAULT 20,
  p_rrf_k int DEFAULT 60,
  p_w_text numeric DEFAULT 1.0,
  p_w_vector numeric DEFAULT 1.0,
  p_w_trgm numeric DEFAULT 0.5,
  p_principal jsonb DEFAULT NULL
)
RETURNS TABLE (
  chunk_id uuid,
  object_id uuid,
  source_system text,
  source_type text,
  external_id text,
  title text,
  url text,
  status text,
  priority text,
  owner text,
  account_name text,
  project_key text,
  component text,
  updated_at timestamptz,
  snippet text,
  text_rank numeric,
  vector_score numeric,
  trigram_score numeric,
  metadata_score numeric,
  recency_score numeric,
  rrf_score numeric,
  final_score numeric,
  explanation jsonb
)
LANGUAGE sql
AS $$
WITH base AS (
  SELECT c.chunk_id, o.object_id, o.source_system, o.source_type, o.external_id, o.title,
         o.url, o.status, o.priority, o.owner, o.account_name, o.project_key, o.component,
         o.updated_at, c.chunk_text, o.source_authority
  FROM ops.object_chunks c
  JOIN ops.source_objects o ON o.object_id = c.object_id
  WHERE o.is_active
    AND (p_source_systems IS NULL OR o.source_system = ANY(p_source_systems))
    AND (p_source_types IS NULL OR o.source_type = ANY(p_source_types))
    AND (p_statuses IS NULL OR o.status = ANY(p_statuses))
    AND (p_priorities IS NULL OR o.priority = ANY(p_priorities))
    AND (p_project_key IS NULL OR o.project_key = p_project_key)
    AND (p_account_name IS NULL OR o.account_name = p_account_name)
    AND (p_component IS NULL OR o.component = p_component)
    AND (p_start_date IS NULL OR o.updated_at >= p_start_date)
    AND (p_end_date IS NULL OR o.updated_at <= p_end_date)
    -- Row-level ACL. Applied once in base so every retrieval arm (text/vector/trgm)
    -- inherits it; a restricted object never enters the fused ranking for a principal
    -- lacking its clearance. p_principal IS NULL keeps the canonical demo unfiltered.
    AND ops.acl_visible(o.acl, p_principal)
),
q AS (
  -- Lexical arm shares the OR-combine invariant via ops.to_or_tsquery so the
  -- rewrite lives in exactly one place for both hybrid and lexical-only API modes.
  SELECT ops.to_or_tsquery(p_query) AS tq
),
text_hits AS (
  -- Lexical arm matches EITHER the chunk body vector (object_chunks.tsv) OR the
  -- object-level vector (source_objects.search_tsv, which carries external_id + title
  -- at weight A). The rank sums both so an exact-ID hit (matched via search_tsv) ranks
  -- strongly even when the ID never appears in the chunk body — the case a chunk-only
  -- lexical arm silently missed. coalesce keeps a body-only or title-only match valid.
  SELECT b.chunk_id,
         (coalesce(ts_rank_cd(c.tsv, q.tq), 0)
          + coalesce(ts_rank_cd(o.search_tsv, q.tq), 0))::numeric AS text_rank,
         row_number() OVER (
           ORDER BY (coalesce(ts_rank_cd(c.tsv, q.tq), 0)
                     + coalesce(ts_rank_cd(o.search_tsv, q.tq), 0)) DESC
         ) AS text_pos
  FROM base b
  JOIN ops.object_chunks c ON c.chunk_id = b.chunk_id
  JOIN ops.source_objects o ON o.object_id = b.object_id
  CROSS JOIN q
  WHERE o.is_active
    AND q.tq IS NOT NULL AND (c.tsv @@ q.tq OR o.search_tsv @@ q.tq)
  ORDER BY text_rank DESC
  LIMIT 300
),
vector_hits AS (
  SELECT b.chunk_id,
         (1 - (c.embedding <=> p_query_embedding))::numeric AS vector_score,
         row_number() OVER (ORDER BY c.embedding <=> p_query_embedding ASC) AS vector_pos
  FROM base b
  JOIN ops.object_chunks c ON c.chunk_id = b.chunk_id
  WHERE c.embedding IS NOT NULL AND p_query_embedding IS NOT NULL
  ORDER BY c.embedding <=> p_query_embedding ASC
  LIMIT 300
),
trgm_hits AS (
  SELECT b.chunk_id,
         greatest(similarity(b.title, p_query), similarity(left(b.chunk_text, 500), p_query))::numeric AS trigram_score,
         row_number() OVER (ORDER BY greatest(similarity(b.title, p_query), similarity(left(b.chunk_text, 500), p_query)) DESC) AS trgm_pos
  FROM base b
  WHERE greatest(similarity(b.title, p_query), similarity(left(b.chunk_text, 500), p_query)) > 0.08
  ORDER BY trigram_score DESC
  LIMIT 300
),
fused AS (
  SELECT
    b.*,
    th.text_rank,
    vh.vector_score,
    tg.trigram_score,
    (
      CASE WHEN b.priority IN ('P0','P1','Sev1','Sev2') THEN 0.15 ELSE 0 END +
      CASE WHEN b.status IN ('Open','In Progress','Escalated','Blocked') THEN 0.10 ELSE 0 END +
      coalesce(b.source_authority, 0.7) * 0.10
    )::numeric AS metadata_score,
    CASE
      WHEN b.updated_at IS NULL THEN 0
      WHEN b.updated_at > now() - interval '7 days' THEN 0.10
      WHEN b.updated_at > now() - interval '30 days' THEN 0.06
      ELSE 0.02
    END::numeric AS recency_score,
    -- Weighted Reciprocal Rank Fusion. Each retrieval arm contributes ONLY through
    -- its rank position (ops.rrf), scaled by its ranker weight. This is the single
    -- fused relevance signal: the raw ts_rank_cd / cosine / trigram scores are kept
    -- for display and explanation but never re-added to final_score, so a signal is
    -- counted once (by rank), not twice (by rank and by raw score on incommensurate
    -- scales). p_w_text / p_w_vector / p_w_trgm are the live ranker weights.
    (
      p_w_text   * ops.rrf(th.text_pos::int, p_rrf_k) +
      p_w_vector * ops.rrf(vh.vector_pos::int, p_rrf_k) +
      p_w_trgm   * ops.rrf(tg.trgm_pos::int, p_rrf_k)
    )::numeric AS rrf_score
  FROM base b
  LEFT JOIN text_hits th ON th.chunk_id = b.chunk_id
  LEFT JOIN vector_hits vh ON vh.chunk_id = b.chunk_id
  LEFT JOIN trgm_hits tg ON tg.chunk_id = b.chunk_id
  WHERE th.chunk_id IS NOT NULL OR vh.chunk_id IS NOT NULL OR tg.chunk_id IS NOT NULL
)
SELECT
  f.chunk_id, f.object_id, f.source_system, f.source_type, f.external_id, f.title, f.url,
  f.status, f.priority, f.owner, f.account_name, f.project_key, f.component, f.updated_at,
  left(regexp_replace(f.chunk_text, '\s+', ' ', 'g'), 460) AS snippet,
  coalesce(f.text_rank,0), coalesce(f.vector_score,0), coalesce(f.trigram_score,0), f.metadata_score,
  f.recency_score,
  f.rrf_score,
  -- final_score = weighted RRF (primary, rank-based) lifted onto the same numeric
  -- scale as the metadata/recency boosts (RRF maxes near 1/(k+1) per arm, so *35
  -- makes the fused rank signal ~O(1) and the boosts act as tie-breakers, not
  -- dominators). No raw retrieval score is added here — see the rrf_score comment.
  (
    coalesce(f.rrf_score,0) * 35 +
    coalesce(f.metadata_score,0) +
    coalesce(f.recency_score,0)
  )::numeric AS final_score,
  jsonb_build_object(
    'signals', jsonb_build_object(
      'full_text', coalesce(f.text_rank,0),
      'semantic', coalesce(f.vector_score,0),
      'fuzzy', coalesce(f.trigram_score,0),
      'metadata', f.metadata_score,
      'recency', f.recency_score,
      'rrf', f.rrf_score
    ),
    'weights', jsonb_build_object(
      'text', p_w_text, 'vector', p_w_vector, 'trgm', p_w_trgm, 'rrf_k', p_rrf_k
    ),
    'why', ARRAY[
      'Matched through hybrid retrieval across full-text, semantic, fuzzy, and metadata signals',
      'Ranked by weighted Reciprocal Rank Fusion (k=' || p_rrf_k || ') with metadata and recency boosts',
      'Filtered by requested source systems, status, project, account, component, or time window when provided'
    ]
  ) AS explanation
FROM fused f
ORDER BY final_score DESC
LIMIT p_limit;
$$;

-- ---------------------------------------------------------------------------
-- Single-signal retrieval functions.
--
-- These back the API's lexical, semantic, and fuzzy retrieval modes. The
-- agent-facing search_evidence capability selects those modes without exposing
-- these SQL functions as separate tools. They share the same filter set and a
-- compact, consistent row shape. full_text_search calls ops.to_or_tsquery, so the
-- OR-combine invariant holds here too.
-- ---------------------------------------------------------------------------

-- Lexical / full-text only. tsvector @@ tsquery ranked by ts_rank_cd.
CREATE OR REPLACE FUNCTION ops.full_text_search(
  p_query text,
  p_source_systems text[] DEFAULT NULL,
  p_source_types text[] DEFAULT NULL,
  p_statuses text[] DEFAULT NULL,
  p_priorities text[] DEFAULT NULL,
  p_project_key text DEFAULT NULL,
  p_account_name text DEFAULT NULL,
  p_component text DEFAULT NULL,
  p_start_date timestamptz DEFAULT NULL,
  p_end_date timestamptz DEFAULT NULL,
  p_limit int DEFAULT 20,
  p_principal jsonb DEFAULT NULL
)
RETURNS TABLE (
  chunk_id uuid,
  object_id uuid,
  source_system text,
  source_type text,
  external_id text,
  title text,
  url text,
  status text,
  priority text,
  owner text,
  account_name text,
  project_key text,
  component text,
  updated_at timestamptz,
  snippet text,
  score numeric
)
LANGUAGE sql
AS $$
  WITH q AS (
    SELECT ops.to_or_tsquery(p_query) AS tq
  )
  -- Matches the chunk body vector OR the object-level search_tsv (external_id + title
  -- at weight A), ranked by the sum — same exact-ID fix as ops.hybrid_search's lexical
  -- arm, so this single-signal tool and the fused ranker agree on lexical matches.
  SELECT c.chunk_id, o.object_id, o.source_system, o.source_type, o.external_id, o.title,
         o.url, o.status, o.priority, o.owner, o.account_name, o.project_key, o.component,
         o.updated_at,
         left(regexp_replace(c.chunk_text, '\s+', ' ', 'g'), 460) AS snippet,
         (coalesce(ts_rank_cd(c.tsv, q.tq), 0)
          + coalesce(ts_rank_cd(o.search_tsv, q.tq), 0))::numeric AS score
  FROM ops.object_chunks c
  JOIN ops.source_objects o ON o.object_id = c.object_id
  CROSS JOIN q
  WHERE o.is_active
    AND q.tq IS NOT NULL AND (c.tsv @@ q.tq OR o.search_tsv @@ q.tq)
    AND (p_source_systems IS NULL OR o.source_system = ANY(p_source_systems))
    AND (p_source_types IS NULL OR o.source_type = ANY(p_source_types))
    AND (p_statuses IS NULL OR o.status = ANY(p_statuses))
    AND (p_priorities IS NULL OR o.priority = ANY(p_priorities))
    AND (p_project_key IS NULL OR o.project_key = p_project_key)
    AND (p_account_name IS NULL OR o.account_name = p_account_name)
    AND (p_component IS NULL OR o.component = p_component)
    AND (p_start_date IS NULL OR o.updated_at >= p_start_date)
    AND (p_end_date IS NULL OR o.updated_at <= p_end_date)
    AND ops.acl_visible(o.acl, p_principal)
  ORDER BY score DESC
  LIMIT p_limit;
$$;

-- Semantic / vector only. Cosine similarity against the HNSW-indexed embedding.
CREATE OR REPLACE FUNCTION ops.vector_search(
  p_query_embedding vector(1024),
  p_source_systems text[] DEFAULT NULL,
  p_source_types text[] DEFAULT NULL,
  p_statuses text[] DEFAULT NULL,
  p_priorities text[] DEFAULT NULL,
  p_project_key text DEFAULT NULL,
  p_account_name text DEFAULT NULL,
  p_component text DEFAULT NULL,
  p_start_date timestamptz DEFAULT NULL,
  p_end_date timestamptz DEFAULT NULL,
  p_limit int DEFAULT 20,
  p_principal jsonb DEFAULT NULL
)
RETURNS TABLE (
  chunk_id uuid,
  object_id uuid,
  source_system text,
  source_type text,
  external_id text,
  title text,
  url text,
  status text,
  priority text,
  owner text,
  account_name text,
  project_key text,
  component text,
  updated_at timestamptz,
  snippet text,
  score numeric
)
LANGUAGE sql
AS $$
  SELECT c.chunk_id, o.object_id, o.source_system, o.source_type, o.external_id, o.title,
         o.url, o.status, o.priority, o.owner, o.account_name, o.project_key, o.component,
         o.updated_at,
         left(regexp_replace(c.chunk_text, '\s+', ' ', 'g'), 460) AS snippet,
         (1 - (c.embedding <=> p_query_embedding))::numeric AS score
  FROM ops.object_chunks c
  JOIN ops.source_objects o ON o.object_id = c.object_id
  WHERE o.is_active
    AND c.embedding IS NOT NULL AND p_query_embedding IS NOT NULL
    AND (p_source_systems IS NULL OR o.source_system = ANY(p_source_systems))
    AND (p_source_types IS NULL OR o.source_type = ANY(p_source_types))
    AND (p_statuses IS NULL OR o.status = ANY(p_statuses))
    AND (p_priorities IS NULL OR o.priority = ANY(p_priorities))
    AND (p_project_key IS NULL OR o.project_key = p_project_key)
    AND (p_account_name IS NULL OR o.account_name = p_account_name)
    AND (p_component IS NULL OR o.component = p_component)
    AND (p_start_date IS NULL OR o.updated_at >= p_start_date)
    AND (p_end_date IS NULL OR o.updated_at <= p_end_date)
    AND ops.acl_visible(o.acl, p_principal)
  ORDER BY c.embedding <=> p_query_embedding ASC
  LIMIT p_limit;
$$;

-- Fuzzy / pg_trgm only. Trigram similarity over title + leading chunk text, so
-- typos and near-miss identifiers (e.g. "OR10N-1489") still surface a hit.
CREATE OR REPLACE FUNCTION ops.fuzzy_match(
  p_query text,
  p_threshold numeric DEFAULT 0.08,
  p_source_systems text[] DEFAULT NULL,
  p_source_types text[] DEFAULT NULL,
  p_statuses text[] DEFAULT NULL,
  p_priorities text[] DEFAULT NULL,
  p_project_key text DEFAULT NULL,
  p_account_name text DEFAULT NULL,
  p_component text DEFAULT NULL,
  p_start_date timestamptz DEFAULT NULL,
  p_end_date timestamptz DEFAULT NULL,
  p_limit int DEFAULT 20,
  p_principal jsonb DEFAULT NULL
)
RETURNS TABLE (
  chunk_id uuid,
  object_id uuid,
  source_system text,
  source_type text,
  external_id text,
  title text,
  url text,
  status text,
  priority text,
  owner text,
  account_name text,
  project_key text,
  component text,
  updated_at timestamptz,
  snippet text,
  score numeric
)
LANGUAGE sql
AS $$
  SELECT c.chunk_id, o.object_id, o.source_system, o.source_type, o.external_id, o.title,
         o.url, o.status, o.priority, o.owner, o.account_name, o.project_key, o.component,
         o.updated_at,
         left(regexp_replace(c.chunk_text, '\s+', ' ', 'g'), 460) AS snippet,
         greatest(similarity(o.title, p_query), similarity(left(c.chunk_text, 500), p_query))::numeric AS score
  FROM ops.object_chunks c
  JOIN ops.source_objects o ON o.object_id = c.object_id
  WHERE o.is_active
    AND greatest(similarity(o.title, p_query), similarity(left(c.chunk_text, 500), p_query)) > p_threshold
    AND (p_source_systems IS NULL OR o.source_system = ANY(p_source_systems))
    AND (p_source_types IS NULL OR o.source_type = ANY(p_source_types))
    AND (p_statuses IS NULL OR o.status = ANY(p_statuses))
    AND (p_priorities IS NULL OR o.priority = ANY(p_priorities))
    AND (p_project_key IS NULL OR o.project_key = p_project_key)
    AND (p_account_name IS NULL OR o.account_name = p_account_name)
    AND (p_component IS NULL OR o.component = p_component)
    AND (p_start_date IS NULL OR o.updated_at >= p_start_date)
    AND (p_end_date IS NULL OR o.updated_at <= p_end_date)
    AND ops.acl_visible(o.acl, p_principal)
  ORDER BY score DESC
  LIMIT p_limit;
$$;
