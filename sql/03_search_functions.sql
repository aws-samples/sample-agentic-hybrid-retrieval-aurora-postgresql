CREATE OR REPLACE FUNCTION ops.rrf(rank_position int, k int DEFAULT 60)
RETURNS numeric
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE WHEN rank_position IS NULL THEN 0 ELSE 1.0 / (k + rank_position) END;
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
  p_limit int DEFAULT 20
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
  WHERE (p_source_systems IS NULL OR o.source_system = ANY(p_source_systems))
    AND (p_source_types IS NULL OR o.source_type = ANY(p_source_types))
    AND (p_statuses IS NULL OR o.status = ANY(p_statuses))
    AND (p_priorities IS NULL OR o.priority = ANY(p_priorities))
    AND (p_project_key IS NULL OR o.project_key = p_project_key)
    AND (p_account_name IS NULL OR o.account_name = p_account_name)
    AND (p_component IS NULL OR o.component = p_component)
    AND (p_start_date IS NULL OR o.updated_at >= p_start_date)
    AND (p_end_date IS NULL OR o.updated_at <= p_end_date)
),
text_hits AS (
  SELECT b.chunk_id,
         ts_rank_cd(c.tsv, websearch_to_tsquery('english', p_query))::numeric AS text_rank,
         row_number() OVER (ORDER BY ts_rank_cd(c.tsv, websearch_to_tsquery('english', p_query)) DESC) AS text_pos
  FROM base b
  JOIN ops.object_chunks c ON c.chunk_id = b.chunk_id
  WHERE c.tsv @@ websearch_to_tsquery('english', p_query)
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
    (
      ops.rrf(th.text_pos::int) +
      ops.rrf(vh.vector_pos::int) +
      ops.rrf(tg.trgm_pos::int)
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
  (
    coalesce(f.rrf_score,0) * 35 +
    coalesce(f.text_rank,0) * 1.5 +
    coalesce(f.vector_score,0) * 0.8 +
    coalesce(f.trigram_score,0) * 0.4 +
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
    'why', ARRAY[
      'Matched through hybrid retrieval across full-text, semantic, fuzzy, and metadata signals',
      'Filtered by requested source systems, status, project, account, component, or time window when provided'
    ]
  ) AS explanation
FROM fused f
ORDER BY final_score DESC
LIMIT p_limit;
$$;
