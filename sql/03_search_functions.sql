-- STABLE, not IMMUTABLE: identity-dependent predicates (pg_has_role) are STABLE,
-- and an IMMUTABLE label would license the planner to constant-fold a result that
-- is only valid for the role that was current when it was folded.
CREATE OR REPLACE FUNCTION retrieval.acl_visible(p_acl jsonb, p_principal jsonb)
RETURNS boolean
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
  SELECT coalesce(p_acl ->> 'visibility', 'restricted') = 'public'
    OR (
      coalesce(p_acl ->> 'visibility', 'restricted') = ANY (
        ARRAY(
          SELECT jsonb_array_elements_text(
            coalesce(p_principal -> 'scopes', '[]'::jsonb)
          )
        )
      )
      AND (
        jsonb_array_length(coalesce(p_acl -> 'principals', '[]'::jsonb)) = 0
        OR ARRAY(
          SELECT jsonb_array_elements_text(
            coalesce(p_acl -> 'principals', '[]'::jsonb)
          )
        ) && ARRAY(
          SELECT jsonb_array_elements_text(
            coalesce(p_principal -> 'principals', '[]'::jsonb)
          )
        )
      )
    )
$$;

CREATE OR REPLACE FUNCTION retrieval.acl_scalars_visible(
  p_visibility text,
  p_required_principals text[],
  p_principal jsonb
)
RETURNS boolean
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
  SELECT coalesce(p_visibility, 'restricted') = 'public'
    OR (
      coalesce(p_visibility, 'restricted') = ANY (
        ARRAY(
          SELECT jsonb_array_elements_text(
            coalesce(p_principal -> 'scopes', '[]'::jsonb)
          )
        )
      )
      AND (
        cardinality(coalesce(p_required_principals, '{}'::text[])) = 0
        OR coalesce(p_required_principals, '{}'::text[]) && ARRAY(
          SELECT jsonb_array_elements_text(
            coalesce(p_principal -> 'principals', '[]'::jsonb)
          )
        )
      )
    )
$$;

-- Natural-language questions name more terms than any one document contains, so
-- websearch_to_tsquery's AND semantics return nothing for "why did checkout
-- writes block". The lexical arm therefore ORs the terms and lets rank decide,
-- which is what makes it a ranking signal rather than a filter.
--
-- The terms are separated before parsing rather than after. Rewriting the
-- rendered tsquery text turned 'lock' & !'stage' into 'lock' | !'stage', which
-- matches every document that merely lacks "staging" -- an exclusion that
-- becomes a near-universal match. Negation is a filter even when the positive
-- terms are not, so it stays ANDed.
CREATE OR REPLACE FUNCTION retrieval.to_or_tsquery(p_query text)
RETURNS tsquery
LANGUAGE plpgsql
IMMUTABLE
PARALLEL SAFE
AS $$
DECLARE
  -- A leading hyphen is websearch_to_tsquery's exclusion marker. Requiring
  -- whitespace or start-of-string before it leaves hyphens inside a token
  -- alone, so CHG-1842 and read-only are not read as exclusions.
  negation_pattern constant text := '(?:^|\s)-("[^"]*"|\S+)';
  positive_text text;
  negative_text text;
  positive_query tsquery;
  negative_query tsquery;
BEGIN
  IF p_query IS NULL OR btrim(p_query) = '' THEN
    RETURN NULL;
  END IF;

  positive_text := regexp_replace(p_query, negation_pattern, ' ', 'g');
  SELECT string_agg(match[1], ' ')
    INTO negative_text
    FROM regexp_matches(p_query, negation_pattern, 'g') AS match;

  positive_query := websearch_to_tsquery('english', coalesce(positive_text, ''));
  IF numnode(positive_query) = 0 THEN
    RETURN NULL;
  END IF;
  -- OR the positive terms so a document matching any one of them can rank.
  positive_query := to_tsquery(
    'english',
    replace(positive_query::text, ' & ', ' | ')
  );

  IF negative_text IS NULL THEN
    RETURN positive_query;
  END IF;

  negative_query := websearch_to_tsquery('english', negative_text);
  IF numnode(negative_query) = 0 THEN
    RETURN positive_query;
  END IF;
  -- Excluding any one of the named terms excludes the document, so the
  -- exclusion set is ORed and the whole set is negated.
  RETURN positive_query
    && !!to_tsquery('english', replace(negative_query::text, ' & ', ' | '));
END
$$;

CREATE OR REPLACE FUNCTION retrieval.exact_identifier_match(
  p_external_key text,
  p_query text
)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
WITH normalized AS (
  SELECT
    lower(coalesce(p_external_key, '')) AS key,
    lower(coalesce(p_query, '')) AS query
),
located AS (
  SELECT
    key,
    query,
    strpos(query, key) AS position
  FROM normalized
)
SELECT
  length(key) >= 3
  AND position > 0
  AND (
    position = 1
    OR substring(query FROM position - 1 FOR 1) !~ '[[:alnum:]_]'
  )
  AND (
    position + length(key) > length(query)
    OR substring(query FROM position + length(key) FOR 1) !~ '[[:alnum:]_]'
  )
FROM located
$$;

CREATE OR REPLACE VIEW retrieval.v_current_chunks AS
SELECT
  d.document_version_id,
  d.evidence_id,
  d.evidence_kind,
  d.external_key,
  d.title,
  d.source_system,
  d.source_uri,
  d.source_revision,
  d.source_updated_at,
  d.acl,
  d.cluster_id,
  d.incident_id,
  d.account_name,
  d.severity,
  d.environment,
  d.occurred_at,
  d.metadata,
  d.search_tsv AS document_tsv,
  c.chunk_version_id,
  c.chunk_ordinal,
  c.section_title,
  c.chunk_text,
  c.chunk_hash,
  c.embedding,
  c.embedding_model,
  c.embedding_state,
  c.search_tsv AS chunk_tsv,
  d.service_name,
  d.engine_version,
  d.aws_region,
  c.embedding_input_type,
  c.acl_visibility,
  c.acl_principals
FROM retrieval.documents d
JOIN retrieval.chunks c ON c.document_version_id = d.document_version_id
WHERE d.is_current
  AND d.index_state = 'ready'
  AND c.is_current
  AND c.embedding_state = 'ready';

-- Every canonical arm is dropped before it is recreated. CREATE OR REPLACE
-- cannot change a function's RETURNS TABLE shape, and these signatures are
-- listed exactly so that re-running this file over an existing cluster picks up
-- output-column changes instead of failing with "cannot change return type".
DROP FUNCTION IF EXISTS retrieval.hybrid_search(
  text, vector, text[], text[], text, text, text, text[], text, text, text,
  text, timestamptz, timestamptz, jsonb, integer, integer, integer,
  numeric, numeric, numeric, real
);
DROP FUNCTION IF EXISTS retrieval.fuzzy_search(
  text[], real, text[], text, text, text, text[], text, text, text, text,
  timestamptz, timestamptz, jsonb, integer
);
DROP FUNCTION IF EXISTS retrieval.vector_search(
  vector, text[], text, text, text, text[], text, text, text, text,
  timestamptz, timestamptz, jsonb, integer, integer
);
DROP FUNCTION IF EXISTS retrieval.full_text_search(
  text, text[], text, text, text, text[], text, text, text, text,
  timestamptz, timestamptz, jsonb, integer
);

CREATE OR REPLACE FUNCTION retrieval.full_text_search(
  p_query text,
  p_kinds text[] DEFAULT NULL,
  p_cluster_id text DEFAULT NULL,
  p_incident_id text DEFAULT NULL,
  p_account_name text DEFAULT NULL,
  p_severities text[] DEFAULT NULL,
  p_environment text DEFAULT NULL,
  p_service_name text DEFAULT NULL,
  p_engine_version text DEFAULT NULL,
  p_aws_region text DEFAULT NULL,
  p_start_date timestamptz DEFAULT NULL,
  p_end_date timestamptz DEFAULT NULL,
  p_principal jsonb DEFAULT NULL,
  p_limit integer DEFAULT 10
)
RETURNS TABLE (
  chunk_version_id uuid,
  document_version_id uuid,
  evidence_id uuid,
  evidence_kind text,
  external_key text,
  title text,
  source_system text,
  source_uri text,
  source_revision text,
  cluster_id text,
  incident_id text,
  account_name text,
  severity text,
  environment text,
  service_name text,
  engine_version text,
  aws_region text,
  occurred_at timestamptz,
  snippet text,
  score numeric,
  explanation jsonb
)
LANGUAGE sql
STABLE
AS $$
WITH query AS (
  SELECT retrieval.to_or_tsquery(p_query) AS value
),
tokens AS MATERIALIZED (
  SELECT DISTINCT lower(token) AS value
  FROM regexp_split_to_table(
    coalesce(p_query, ''),
    '[^[:alnum:]_-]+'
  ) AS token
  WHERE length(token) >= 3
    AND token ~ '[0-9]'
    AND token ~ '[-_]'
),
exact_raw AS (
  SELECT
    d.evidence_id,
    d.document_version_id,
    c.chunk_version_id,
    c.chunk_ordinal,
    true AS exact_identifier,
    (
      coalesce(ts_rank_cd(d.search_tsv, query.value), 0)
      + coalesce(ts_rank_cd(c.search_tsv, query.value), 0)
    )::numeric AS raw_score
  FROM tokens
  JOIN retrieval.documents d ON lower(d.external_key) = tokens.value
  CROSS JOIN query
  JOIN LATERAL (
    SELECT chunk.*
    FROM retrieval.chunks chunk
    WHERE chunk.document_version_id = d.document_version_id
    ORDER BY
      coalesce(ts_rank_cd(chunk.search_tsv, query.value), 0) DESC,
      chunk.chunk_ordinal
    LIMIT 1
  ) c ON true
  WHERE d.is_current
    AND d.index_state = 'ready'
    AND retrieval.acl_visible(d.acl, p_principal)
    AND (p_kinds IS NULL OR d.evidence_kind = ANY(p_kinds))
    AND (p_cluster_id IS NULL OR d.cluster_id = p_cluster_id)
    AND (p_incident_id IS NULL OR d.incident_id = p_incident_id)
    AND (p_account_name IS NULL OR d.account_name = p_account_name)
    AND (p_severities IS NULL OR d.severity = ANY(p_severities))
    AND (p_environment IS NULL OR d.environment = p_environment)
    AND (p_service_name IS NULL OR d.service_name = p_service_name)
    AND (p_engine_version IS NULL OR d.engine_version = p_engine_version)
    AND (p_aws_region IS NULL OR d.aws_region = p_aws_region)
    AND (p_start_date IS NULL OR d.occurred_at >= p_start_date)
    AND (p_end_date IS NULL OR d.occurred_at <= p_end_date)
),
document_raw AS (
  SELECT
    d.evidence_id,
    d.document_version_id,
    c.chunk_version_id,
    c.chunk_ordinal,
    false AS exact_identifier,
    (
      ts_rank_cd(d.search_tsv, query.value)
      + coalesce(ts_rank_cd(c.search_tsv, query.value), 0)
    )::numeric AS raw_score
  FROM retrieval.documents d
  CROSS JOIN query
  JOIN LATERAL (
    SELECT chunk.*
    FROM retrieval.chunks chunk
    WHERE chunk.document_version_id = d.document_version_id
    ORDER BY
      coalesce(ts_rank_cd(chunk.search_tsv, query.value), 0) DESC,
      chunk.chunk_ordinal
    LIMIT 1
  ) c ON true
  WHERE query.value IS NOT NULL
    AND d.is_current
    AND d.index_state = 'ready'
    AND d.search_tsv @@ query.value
    AND retrieval.acl_visible(d.acl, p_principal)
    AND (p_kinds IS NULL OR d.evidence_kind = ANY(p_kinds))
    AND (p_cluster_id IS NULL OR d.cluster_id = p_cluster_id)
    AND (p_incident_id IS NULL OR d.incident_id = p_incident_id)
    AND (p_account_name IS NULL OR d.account_name = p_account_name)
    AND (p_severities IS NULL OR d.severity = ANY(p_severities))
    AND (p_environment IS NULL OR d.environment = p_environment)
    AND (p_service_name IS NULL OR d.service_name = p_service_name)
    AND (p_engine_version IS NULL OR d.engine_version = p_engine_version)
    AND (p_aws_region IS NULL OR d.aws_region = p_aws_region)
    AND (p_start_date IS NULL OR d.occurred_at >= p_start_date)
    AND (p_end_date IS NULL OR d.occurred_at <= p_end_date)
  ORDER BY raw_score DESC
  LIMIT greatest(p_limit, 24)
),
chunk_raw AS (
  SELECT
    d.evidence_id,
    d.document_version_id,
    c.chunk_version_id,
    c.chunk_ordinal,
    false AS exact_identifier,
    (
      coalesce(ts_rank_cd(d.search_tsv, query.value), 0)
      + ts_rank_cd(c.search_tsv, query.value)
    )::numeric AS raw_score
  FROM retrieval.chunks c
  JOIN retrieval.documents d ON d.document_version_id = c.document_version_id
  CROSS JOIN query
  WHERE query.value IS NOT NULL
    AND c.search_tsv @@ query.value
    AND d.is_current
    AND d.index_state = 'ready'
    AND retrieval.acl_visible(d.acl, p_principal)
    AND (p_kinds IS NULL OR d.evidence_kind = ANY(p_kinds))
    AND (p_cluster_id IS NULL OR d.cluster_id = p_cluster_id)
    AND (p_incident_id IS NULL OR d.incident_id = p_incident_id)
    AND (p_account_name IS NULL OR d.account_name = p_account_name)
    AND (p_severities IS NULL OR d.severity = ANY(p_severities))
    AND (p_environment IS NULL OR d.environment = p_environment)
    AND (p_service_name IS NULL OR d.service_name = p_service_name)
    AND (p_engine_version IS NULL OR d.engine_version = p_engine_version)
    AND (p_aws_region IS NULL OR d.aws_region = p_aws_region)
    AND (p_start_date IS NULL OR d.occurred_at >= p_start_date)
    AND (p_end_date IS NULL OR d.occurred_at <= p_end_date)
  ORDER BY raw_score DESC
  LIMIT greatest(p_limit, 24)
),
ranked AS (
  SELECT * FROM exact_raw
  UNION ALL
  SELECT * FROM document_raw
  UNION ALL
  SELECT * FROM chunk_raw
),
best AS (
  SELECT DISTINCT ON (ranked.evidence_id)
    ranked.*
  FROM ranked
  ORDER BY
    ranked.evidence_id,
    ranked.exact_identifier DESC,
    ranked.raw_score DESC,
    ranked.chunk_ordinal
)
SELECT
  best.chunk_version_id,
  best.document_version_id,
  d.evidence_id,
  d.evidence_kind,
  d.external_key,
  d.title,
  d.source_system,
  d.source_uri,
  d.source_revision,
  d.cluster_id,
  d.incident_id,
  d.account_name,
  d.severity,
  d.environment,
  d.service_name,
  d.engine_version,
  d.aws_region,
  d.occurred_at,
  left(regexp_replace(c.chunk_text, '\s+', ' ', 'g'), 700) AS snippet,
  best.raw_score AS score,
  jsonb_build_object(
    'arm', 'full_text',
    'raw_score', best.raw_score,
    'exact_identifier', best.exact_identifier,
    'query', p_query
  ) AS explanation
FROM best
JOIN retrieval.documents d ON d.document_version_id = best.document_version_id
JOIN retrieval.chunks c ON c.chunk_version_id = best.chunk_version_id
-- external_key last so the ordering is total. Without it, rows tied on score
-- and occurred_at order arbitrarily, and since the caller applies LIMIT, which
-- rows reach fusion could differ between replays of the same query.
ORDER BY
  best.exact_identifier DESC,
  best.raw_score DESC,
  d.occurred_at DESC,
  d.external_key
LIMIT greatest(1, p_limit)
$$;

CREATE OR REPLACE FUNCTION retrieval.vector_search(
  p_query_embedding vector(1024),
  p_kinds text[] DEFAULT NULL,
  p_cluster_id text DEFAULT NULL,
  p_incident_id text DEFAULT NULL,
  p_account_name text DEFAULT NULL,
  p_severities text[] DEFAULT NULL,
  p_environment text DEFAULT NULL,
  p_service_name text DEFAULT NULL,
  p_engine_version text DEFAULT NULL,
  p_aws_region text DEFAULT NULL,
  p_start_date timestamptz DEFAULT NULL,
  p_end_date timestamptz DEFAULT NULL,
  p_principal jsonb DEFAULT NULL,
  p_limit integer DEFAULT 10,
  p_candidate_pool integer DEFAULT 24
)
RETURNS TABLE (
  chunk_version_id uuid,
  document_version_id uuid,
  evidence_id uuid,
  evidence_kind text,
  external_key text,
  title text,
  source_system text,
  source_uri text,
  source_revision text,
  cluster_id text,
  incident_id text,
  account_name text,
  severity text,
  environment text,
  service_name text,
  engine_version text,
  aws_region text,
  occurred_at timestamptz,
  snippet text,
  score numeric,
  explanation jsonb
)
LANGUAGE sql
STABLE
AS $$
WITH candidates AS MATERIALIZED (
  SELECT
    c.*,
    (c.embedding <=> p_query_embedding) AS distance
  FROM retrieval.chunks c
  WHERE p_query_embedding IS NOT NULL
    AND c.is_current
    AND c.embedding_state = 'ready'
    AND c.embedding IS NOT NULL
    AND retrieval.acl_scalars_visible(
      c.acl_visibility,
      c.acl_principals,
      p_principal
    )
    AND (p_kinds IS NULL OR c.evidence_kind = ANY(p_kinds))
    AND (p_cluster_id IS NULL OR c.cluster_id = p_cluster_id)
    AND (p_incident_id IS NULL OR c.incident_id = p_incident_id)
    AND (p_account_name IS NULL OR c.account_name = p_account_name)
    AND (p_severities IS NULL OR c.severity = ANY(p_severities))
    AND (p_environment IS NULL OR c.environment = p_environment)
    AND (p_service_name IS NULL OR c.service_name = p_service_name)
    AND (p_engine_version IS NULL OR c.engine_version = p_engine_version)
    AND (p_aws_region IS NULL OR c.aws_region = p_aws_region)
    AND (p_start_date IS NULL OR c.occurred_at >= p_start_date)
    AND (p_end_date IS NULL OR c.occurred_at <= p_end_date)
  ORDER BY c.embedding <=> p_query_embedding
  LIMIT greatest(p_limit, p_candidate_pool)
),
best AS (
  SELECT DISTINCT ON (candidates.evidence_id)
    candidates.*
  FROM candidates
  ORDER BY candidates.evidence_id, candidates.distance, candidates.chunk_ordinal
)
SELECT
  best.chunk_version_id,
  best.document_version_id,
  best.evidence_id,
  d.evidence_kind,
  d.external_key,
  d.title,
  d.source_system,
  d.source_uri,
  d.source_revision,
  best.cluster_id,
  best.incident_id,
  best.account_name,
  best.severity,
  best.environment,
  best.service_name,
  best.engine_version,
  best.aws_region,
  best.occurred_at,
  left(regexp_replace(best.chunk_text, '\s+', ' ', 'g'), 700) AS snippet,
  (1 - best.distance)::numeric AS score,
  jsonb_build_object(
    'arm', 'semantic',
    'cosine_distance', best.distance,
    'raw_score', 1 - best.distance,
    'embedding_model', best.embedding_model
  ) AS explanation
FROM best
JOIN retrieval.documents d
  ON d.document_version_id = best.document_version_id
ORDER BY best.distance, best.occurred_at DESC, d.external_key
LIMIT greatest(1, p_limit)
$$;

CREATE OR REPLACE FUNCTION retrieval.fuzzy_search(
  p_probe_tokens text[],
  p_threshold real DEFAULT 0.3,
  p_kinds text[] DEFAULT NULL,
  p_cluster_id text DEFAULT NULL,
  p_incident_id text DEFAULT NULL,
  p_account_name text DEFAULT NULL,
  p_severities text[] DEFAULT NULL,
  p_environment text DEFAULT NULL,
  p_service_name text DEFAULT NULL,
  p_engine_version text DEFAULT NULL,
  p_aws_region text DEFAULT NULL,
  p_start_date timestamptz DEFAULT NULL,
  p_end_date timestamptz DEFAULT NULL,
  p_principal jsonb DEFAULT NULL,
  p_limit integer DEFAULT 10
)
RETURNS TABLE (
  chunk_version_id uuid,
  document_version_id uuid,
  evidence_id uuid,
  evidence_kind text,
  external_key text,
  title text,
  source_system text,
  source_uri text,
  source_revision text,
  cluster_id text,
  incident_id text,
  account_name text,
  severity text,
  environment text,
  service_name text,
  engine_version text,
  aws_region text,
  occurred_at timestamptz,
  snippet text,
  score numeric,
  explanation jsonb
)
LANGUAGE sql
STABLE
AS $$
WITH probes AS MATERIALIZED (
  SELECT DISTINCT upper(btrim(token)) AS token
  FROM unnest(coalesce(p_probe_tokens, '{}'::text[])) AS token
  WHERE btrim(token) <> ''
),
matches AS MATERIALIZED (
  SELECT
    d.*,
    probes.token AS probe_token,
    similarity(d.external_key, probes.token)::numeric AS external_key_score,
    similarity(d.title, probes.token)::numeric AS title_score,
    greatest(
      similarity(d.external_key, probes.token),
      similarity(d.title, probes.token)
    )::numeric AS raw_score
  FROM retrieval.documents d
  CROSS JOIN probes
  WHERE d.is_current
    AND d.index_state = 'ready'
    AND retrieval.acl_scalars_visible(
      d.acl_visibility,
      d.acl_principals,
      p_principal
    )
    AND (p_kinds IS NULL OR d.evidence_kind = ANY(p_kinds))
    AND (p_cluster_id IS NULL OR d.cluster_id = p_cluster_id)
    AND (p_incident_id IS NULL OR d.incident_id = p_incident_id)
    AND (p_account_name IS NULL OR d.account_name = p_account_name)
    AND (p_severities IS NULL OR d.severity = ANY(p_severities))
    AND (p_environment IS NULL OR d.environment = p_environment)
    AND (p_service_name IS NULL OR d.service_name = p_service_name)
    AND (p_engine_version IS NULL OR d.engine_version = p_engine_version)
    AND (p_aws_region IS NULL OR d.aws_region = p_aws_region)
    AND (p_start_date IS NULL OR d.occurred_at >= p_start_date)
    AND (p_end_date IS NULL OR d.occurred_at <= p_end_date)
    AND (d.external_key % probes.token OR d.title % probes.token)
),
ranked_documents AS (
  SELECT DISTINCT ON (matches.evidence_id)
    matches.*
  FROM matches
  WHERE matches.raw_score >= p_threshold
  ORDER BY
    matches.evidence_id,
    matches.raw_score DESC,
    matches.probe_token
),
ranked AS (
  SELECT
    d.*,
    c.chunk_version_id,
    c.chunk_text
  FROM ranked_documents d
  JOIN LATERAL (
    SELECT chunk.chunk_version_id, chunk.chunk_text
    FROM retrieval.chunks chunk
    WHERE chunk.document_version_id = d.document_version_id
      AND chunk.is_current
    ORDER BY chunk.chunk_ordinal
    LIMIT 1
  ) c ON true
)
SELECT
  ranked.chunk_version_id,
  ranked.document_version_id,
  ranked.evidence_id,
  ranked.evidence_kind,
  ranked.external_key,
  ranked.title,
  ranked.source_system,
  ranked.source_uri,
  ranked.source_revision,
  ranked.cluster_id,
  ranked.incident_id,
  ranked.account_name,
  ranked.severity,
  ranked.environment,
  ranked.service_name,
  ranked.engine_version,
  ranked.aws_region,
  ranked.occurred_at,
  left(regexp_replace(ranked.chunk_text, '\s+', ' ', 'g'), 700) AS snippet,
  ranked.raw_score AS score,
  jsonb_build_object(
    'arm', 'fuzzy',
    'raw_score', ranked.raw_score,
    'threshold', p_threshold,
    'probe_token', ranked.probe_token,
    'field_scores', jsonb_build_object(
      'external_key', ranked.external_key_score,
      'title', ranked.title_score
    )
  ) AS explanation
FROM ranked
-- A letter-for-digit typo such as CHG-1OOO scores identically against every
-- CHG-10xx key, because the typo destroys the digits that distinguish them.
-- external_key makes that tie resolve the same way on every replay.
ORDER BY ranked.raw_score DESC, ranked.occurred_at DESC, ranked.external_key
LIMIT greatest(1, p_limit)
$$;

CREATE OR REPLACE FUNCTION retrieval.hybrid_search(
  p_query text,
  p_query_embedding vector(1024),
  p_fuzzy_probe_tokens text[] DEFAULT NULL,
  p_kinds text[] DEFAULT NULL,
  p_cluster_id text DEFAULT NULL,
  p_incident_id text DEFAULT NULL,
  p_account_name text DEFAULT NULL,
  p_severities text[] DEFAULT NULL,
  p_environment text DEFAULT NULL,
  p_service_name text DEFAULT NULL,
  p_engine_version text DEFAULT NULL,
  p_aws_region text DEFAULT NULL,
  p_start_date timestamptz DEFAULT NULL,
  p_end_date timestamptz DEFAULT NULL,
  p_principal jsonb DEFAULT NULL,
  p_limit integer DEFAULT 10,
  p_candidate_pool integer DEFAULT 24,
  p_rrf_k integer DEFAULT 60,
  p_w_text numeric DEFAULT 2.0,
  p_w_vector numeric DEFAULT 1.0,
  p_w_trgm numeric DEFAULT 1.0,
  p_fuzzy_threshold real DEFAULT 0.3
)
RETURNS TABLE (
  chunk_version_id uuid,
  document_version_id uuid,
  evidence_id uuid,
  evidence_kind text,
  external_key text,
  title text,
  source_system text,
  source_uri text,
  source_revision text,
  cluster_id text,
  incident_id text,
  account_name text,
  severity text,
  environment text,
  service_name text,
  engine_version text,
  aws_region text,
  occurred_at timestamptz,
  snippet text,
  text_rank numeric,
  vector_score numeric,
  trigram_score numeric,
  text_position integer,
  vector_position integer,
  trigram_position integer,
  exact_identifier_position integer,
  match_tier integer,
  rrf_score numeric,
  final_score numeric,
  explanation jsonb
)
LANGUAGE sql
STABLE
AS $$
WITH text_candidates AS MATERIALIZED (
  SELECT *
  FROM retrieval.full_text_search(
    p_query,
    p_kinds,
    p_cluster_id,
    p_incident_id,
    p_account_name,
    p_severities,
    p_environment,
    p_service_name,
    p_engine_version,
    p_aws_region,
    p_start_date,
    p_end_date,
    p_principal,
    greatest(p_limit, p_candidate_pool)
  )
),
text_ranked AS (
  SELECT
    candidate.evidence_id,
    candidate.document_version_id,
    candidate.chunk_version_id,
    candidate.score,
    coalesce(
      (candidate.explanation ->> 'exact_identifier')::boolean,
      false
    ) AS exact_identifier,
    row_number() OVER (
      ORDER BY
        coalesce((candidate.explanation ->> 'exact_identifier')::boolean, false) DESC,
        candidate.score DESC,
        candidate.occurred_at DESC,
        candidate.evidence_id
    )::integer AS position
  FROM text_candidates candidate
),
-- The deterministic tier. `full_text_search` resolves these rows with a B-tree
-- equality probe on lower(external_key), so membership is a fact about the
-- query, not a score. Ordering inside the tier stays stable and inspectable:
-- text_ranked already sorts exact matches by lexical score, then recency, then
-- evidence_id, so two exact matches never swap between identical runs.
exact_ranked AS (
  SELECT
    candidate.evidence_id,
    row_number() OVER (
      ORDER BY candidate.position, candidate.evidence_id
    )::integer AS position
  FROM text_ranked candidate
  WHERE candidate.exact_identifier
),
vector_candidates AS MATERIALIZED (
  SELECT *
  FROM retrieval.vector_search(
    p_query_embedding,
    p_kinds,
    p_cluster_id,
    p_incident_id,
    p_account_name,
    p_severities,
    p_environment,
    p_service_name,
    p_engine_version,
    p_aws_region,
    p_start_date,
    p_end_date,
    p_principal,
    greatest(p_limit, p_candidate_pool),
    greatest(p_limit, p_candidate_pool)
  )
),
vector_ranked AS (
  SELECT
    candidate.evidence_id,
    candidate.document_version_id,
    candidate.chunk_version_id,
    candidate.score,
    row_number() OVER (
      ORDER BY candidate.score DESC, candidate.occurred_at DESC, candidate.evidence_id
    )::integer AS position
  FROM vector_candidates candidate
),
trgm_candidates AS MATERIALIZED (
  SELECT *
  FROM retrieval.fuzzy_search(
    p_fuzzy_probe_tokens,
    p_fuzzy_threshold,
    p_kinds,
    p_cluster_id,
    p_incident_id,
    p_account_name,
    p_severities,
    p_environment,
    p_service_name,
    p_engine_version,
    p_aws_region,
    p_start_date,
    p_end_date,
    p_principal,
    greatest(p_limit, p_candidate_pool)
  )
),
trgm_ranked AS (
  SELECT
    candidate.evidence_id,
    candidate.document_version_id,
    candidate.chunk_version_id,
    candidate.score,
    row_number() OVER (
      ORDER BY candidate.score DESC, candidate.occurred_at DESC, candidate.evidence_id
    )::integer AS position
  FROM trgm_candidates candidate
),
all_evidence AS (
  SELECT evidence_id FROM text_ranked
  UNION
  SELECT evidence_id FROM vector_ranked
  UNION
  SELECT evidence_id FROM trgm_ranked
),
fused AS (
  SELECT
    ids.evidence_id,
    coalesce(t.document_version_id, v.document_version_id, g.document_version_id) AS document_version_id,
    coalesce(t.chunk_version_id, v.chunk_version_id, g.chunk_version_id) AS chunk_version_id,
    t.score AS text_rank,
    v.score AS vector_score,
    g.score AS trigram_score,
    t.position AS text_position,
    v.position AS vector_position,
    g.position AS trigram_position,
    e.position AS exact_identifier_position,
    -- Tier 1 is exact identifier resolution, tier 2 is everything fusion found.
    -- The tier is applied in ORDER BY, not folded into rrf_score, so a caller
    -- cannot demote a named identifier by reweighting an arm.
    CASE WHEN e.position IS NULL THEN 2 ELSE 1 END AS match_tier,
    -- Three weighted terms for three ranked arms. Division is numeric because
    -- p_w_* are numeric: integer 2 / (60 + 1) would truncate to 0 and flatten
    -- every score. An arm that returned no row contributes exactly zero.
    (
      CASE WHEN t.position IS NULL THEN 0 ELSE p_w_text / (p_rrf_k + t.position) END
      + CASE WHEN v.position IS NULL THEN 0 ELSE p_w_vector / (p_rrf_k + v.position) END
      + CASE WHEN g.position IS NULL THEN 0 ELSE p_w_trgm / (p_rrf_k + g.position) END
    )::numeric AS rrf_score
  FROM all_evidence ids
  LEFT JOIN exact_ranked e ON e.evidence_id = ids.evidence_id
  LEFT JOIN text_ranked t ON t.evidence_id = ids.evidence_id
  LEFT JOIN vector_ranked v ON v.evidence_id = ids.evidence_id
  LEFT JOIN trgm_ranked g ON g.evidence_id = ids.evidence_id
),
scored AS (
  SELECT
    f.*,
    f.rrf_score AS final_score
  FROM fused f
)
SELECT
  s.chunk_version_id,
  s.document_version_id,
  d.evidence_id,
  d.evidence_kind,
  d.external_key,
  d.title,
  d.source_system,
  d.source_uri,
  d.source_revision,
  d.cluster_id,
  d.incident_id,
  d.account_name,
  d.severity,
  d.environment,
  d.service_name,
  d.engine_version,
  d.aws_region,
  d.occurred_at,
  left(regexp_replace(c.chunk_text, '\s+', ' ', 'g'), 700) AS snippet,
  s.text_rank,
  s.vector_score,
  s.trigram_score,
  s.text_position,
  s.vector_position,
  s.trigram_position,
  s.exact_identifier_position,
  s.match_tier,
  s.rrf_score,
  s.final_score,
  jsonb_build_object(
    'signals', jsonb_build_object(
      'full_text', s.text_rank,
      'semantic', s.vector_score,
      'fuzzy', s.trigram_score,
      'rrf', s.rrf_score
    ),
    'positions', jsonb_build_object(
      'exact_identifier', s.exact_identifier_position,
      'full_text', s.text_position,
      'semantic', s.vector_position,
      'fuzzy', s.trigram_position
    ),
    'weights', jsonb_build_object(
      'full_text', p_w_text,
      'semantic', p_w_vector,
      'fuzzy', p_w_trgm
    ),
    'match_tier', s.match_tier,
    'match_tier_label',
      CASE WHEN s.match_tier = 1 THEN 'exact_identifier' ELSE 'fused' END,
    'exact_identifier', s.match_tier = 1,
    'fuzzy_probe_tokens', coalesce(p_fuzzy_probe_tokens, '{}'::text[]),
    'rrf_k', p_rrf_k,
    'note', 'Exact identifier matches are a deterministic tier ordered above every fused candidate; weights only reorder within a tier. Raw scores are diagnostic only.'
  ) AS explanation
FROM scored s
JOIN retrieval.documents d
  ON d.document_version_id = s.document_version_id
JOIN retrieval.chunks c ON c.chunk_version_id = s.chunk_version_id
-- match_tier leads the sort. Within the exact tier the resolved identifier
-- position decides, so the tier order is reproducible from the probe alone.
-- Within the fused tier the weighted RRF score decides. occurred_at and
-- external_key break remaining ties so the ordering is total.
ORDER BY
  s.match_tier,
  s.exact_identifier_position NULLS LAST,
  s.final_score DESC,
  d.occurred_at DESC,
  d.external_key
LIMIT greatest(1, p_limit)
$$;
