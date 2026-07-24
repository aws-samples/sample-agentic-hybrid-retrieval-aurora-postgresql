CREATE OR REPLACE FUNCTION retrieval.acl_visible(p_acl jsonb, p_principal jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT
    coalesce(p_acl ->> 'visibility', 'restricted') = 'public'
    OR (
      p_principal IS NOT NULL
      AND EXISTS (
        SELECT 1
        FROM jsonb_array_elements_text(coalesce(p_principal -> 'scopes', '[]'::jsonb)) AS scope(value)
        WHERE scope.value = coalesce(p_acl ->> 'visibility', 'restricted')
      )
    )
    OR (
      p_principal IS NOT NULL
      AND EXISTS (
        SELECT 1
        FROM jsonb_array_elements_text(coalesce(p_principal -> 'principals', '[]'::jsonb)) AS principal(value)
        JOIN jsonb_array_elements_text(coalesce(p_acl -> 'principals', '[]'::jsonb)) AS allowed(value)
          ON allowed.value = principal.value
      )
    )
$$;

CREATE OR REPLACE FUNCTION retrieval.to_or_tsquery(p_query text)
RETURNS tsquery
LANGUAGE plpgsql
IMMUTABLE
PARALLEL SAFE
AS $$
DECLARE
  parsed tsquery;
  rendered text;
BEGIN
  IF p_query IS NULL OR btrim(p_query) = '' THEN
    RETURN NULL;
  END IF;

  parsed := websearch_to_tsquery('english', p_query);
  IF numnode(parsed) = 0 THEN
    RETURN NULL;
  END IF;

  rendered := replace(parsed::text, ' & ', ' | ');
  RETURN to_tsquery('english', rendered);
END
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
  c.search_tsv AS chunk_tsv
FROM retrieval.documents d
JOIN retrieval.chunks c ON c.document_version_id = d.document_version_id
WHERE d.is_current
  AND d.index_state = 'ready';

CREATE OR REPLACE FUNCTION retrieval.full_text_search(
  p_query text,
  p_kinds text[] DEFAULT NULL,
  p_cluster_id text DEFAULT NULL,
  p_incident_id text DEFAULT NULL,
  p_account_name text DEFAULT NULL,
  p_severities text[] DEFAULT NULL,
  p_environment text DEFAULT NULL,
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
ranked AS (
  SELECT
    c.*,
    (
      coalesce(ts_rank_cd(c.document_tsv, query.value), 0)
      + coalesce(ts_rank_cd(c.chunk_tsv, query.value), 0)
    )::numeric AS raw_score
  FROM retrieval.v_current_chunks c
  CROSS JOIN query
  WHERE query.value IS NOT NULL
    AND retrieval.acl_visible(c.acl, p_principal)
    AND (p_kinds IS NULL OR c.evidence_kind = ANY(p_kinds))
    AND (p_cluster_id IS NULL OR c.cluster_id = p_cluster_id)
    AND (p_incident_id IS NULL OR c.incident_id = p_incident_id)
    AND (p_account_name IS NULL OR c.account_name = p_account_name)
    AND (p_severities IS NULL OR c.severity = ANY(p_severities))
    AND (p_environment IS NULL OR c.environment = p_environment)
    AND (p_start_date IS NULL OR c.occurred_at >= p_start_date)
    AND (p_end_date IS NULL OR c.occurred_at <= p_end_date)
    AND (c.document_tsv @@ query.value OR c.chunk_tsv @@ query.value)
),
best AS (
  SELECT DISTINCT ON (ranked.evidence_id)
    ranked.*
  FROM ranked
  ORDER BY ranked.evidence_id, ranked.raw_score DESC, ranked.chunk_ordinal
)
SELECT
  best.chunk_version_id,
  best.document_version_id,
  best.evidence_id,
  best.evidence_kind,
  best.external_key,
  best.title,
  best.source_system,
  best.source_uri,
  best.source_revision,
  best.cluster_id,
  best.incident_id,
  best.account_name,
  best.severity,
  best.environment,
  best.occurred_at,
  left(regexp_replace(best.chunk_text, '\s+', ' ', 'g'), 700) AS snippet,
  best.raw_score AS score,
  jsonb_build_object(
    'arm', 'full_text',
    'raw_score', best.raw_score,
    'query', p_query
  ) AS explanation
FROM best
ORDER BY best.raw_score DESC, best.occurred_at DESC
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
  p_start_date timestamptz DEFAULT NULL,
  p_end_date timestamptz DEFAULT NULL,
  p_principal jsonb DEFAULT NULL,
  p_limit integer DEFAULT 10,
  p_candidate_pool integer DEFAULT 200
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
  occurred_at timestamptz,
  snippet text,
  score numeric,
  explanation jsonb
)
LANGUAGE sql
STABLE
AS $$
WITH candidates AS (
  SELECT
    c.*,
    (c.embedding <=> p_query_embedding) AS distance
  FROM retrieval.v_current_chunks c
  WHERE p_query_embedding IS NOT NULL
    AND c.embedding_state = 'ready'
    AND c.embedding IS NOT NULL
    AND retrieval.acl_visible(c.acl, p_principal)
    AND (p_kinds IS NULL OR c.evidence_kind = ANY(p_kinds))
    AND (p_cluster_id IS NULL OR c.cluster_id = p_cluster_id)
    AND (p_incident_id IS NULL OR c.incident_id = p_incident_id)
    AND (p_account_name IS NULL OR c.account_name = p_account_name)
    AND (p_severities IS NULL OR c.severity = ANY(p_severities))
    AND (p_environment IS NULL OR c.environment = p_environment)
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
  best.evidence_kind,
  best.external_key,
  best.title,
  best.source_system,
  best.source_uri,
  best.source_revision,
  best.cluster_id,
  best.incident_id,
  best.account_name,
  best.severity,
  best.environment,
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
ORDER BY best.distance, best.occurred_at DESC
LIMIT greatest(1, p_limit)
$$;

CREATE OR REPLACE FUNCTION retrieval.fuzzy_search(
  p_query text,
  p_threshold real DEFAULT 0.12,
  p_kinds text[] DEFAULT NULL,
  p_cluster_id text DEFAULT NULL,
  p_incident_id text DEFAULT NULL,
  p_account_name text DEFAULT NULL,
  p_severities text[] DEFAULT NULL,
  p_environment text DEFAULT NULL,
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
  occurred_at timestamptz,
  snippet text,
  score numeric,
  explanation jsonb
)
LANGUAGE sql
STABLE
AS $$
WITH ranked AS (
  SELECT
    c.*,
    greatest(
      similarity(c.title, p_query),
      similarity(left(c.chunk_text, 1000), p_query)
    )::numeric AS raw_score
  FROM retrieval.v_current_chunks c
  WHERE p_query IS NOT NULL
    AND btrim(p_query) <> ''
    AND retrieval.acl_visible(c.acl, p_principal)
    AND (p_kinds IS NULL OR c.evidence_kind = ANY(p_kinds))
    AND (p_cluster_id IS NULL OR c.cluster_id = p_cluster_id)
    AND (p_incident_id IS NULL OR c.incident_id = p_incident_id)
    AND (p_account_name IS NULL OR c.account_name = p_account_name)
    AND (p_severities IS NULL OR c.severity = ANY(p_severities))
    AND (p_environment IS NULL OR c.environment = p_environment)
    AND (p_start_date IS NULL OR c.occurred_at >= p_start_date)
    AND (p_end_date IS NULL OR c.occurred_at <= p_end_date)
    AND (
      c.title % p_query
      OR left(c.chunk_text, 1000) % p_query
      OR greatest(
        similarity(c.title, p_query),
        similarity(left(c.chunk_text, 1000), p_query)
      ) >= p_threshold
    )
),
best AS (
  SELECT DISTINCT ON (ranked.evidence_id)
    ranked.*
  FROM ranked
  WHERE ranked.raw_score >= p_threshold
  ORDER BY ranked.evidence_id, ranked.raw_score DESC, ranked.chunk_ordinal
)
SELECT
  best.chunk_version_id,
  best.document_version_id,
  best.evidence_id,
  best.evidence_kind,
  best.external_key,
  best.title,
  best.source_system,
  best.source_uri,
  best.source_revision,
  best.cluster_id,
  best.incident_id,
  best.account_name,
  best.severity,
  best.environment,
  best.occurred_at,
  left(regexp_replace(best.chunk_text, '\s+', ' ', 'g'), 700) AS snippet,
  best.raw_score AS score,
  jsonb_build_object(
    'arm', 'fuzzy',
    'raw_score', best.raw_score,
    'threshold', p_threshold
  ) AS explanation
FROM best
ORDER BY best.raw_score DESC, best.occurred_at DESC
LIMIT greatest(1, p_limit)
$$;

CREATE OR REPLACE FUNCTION retrieval.hybrid_search(
  p_query text,
  p_query_embedding vector(1024),
  p_kinds text[] DEFAULT NULL,
  p_cluster_id text DEFAULT NULL,
  p_incident_id text DEFAULT NULL,
  p_account_name text DEFAULT NULL,
  p_severities text[] DEFAULT NULL,
  p_environment text DEFAULT NULL,
  p_start_date timestamptz DEFAULT NULL,
  p_end_date timestamptz DEFAULT NULL,
  p_principal jsonb DEFAULT NULL,
  p_limit integer DEFAULT 10,
  p_candidate_pool integer DEFAULT 200,
  p_rrf_k integer DEFAULT 60,
  p_w_text numeric DEFAULT 1.0,
  p_w_vector numeric DEFAULT 1.0,
  p_w_trgm numeric DEFAULT 0.5,
  p_fuzzy_threshold real DEFAULT 0.12
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
  occurred_at timestamptz,
  snippet text,
  text_rank numeric,
  vector_score numeric,
  trigram_score numeric,
  text_position integer,
  vector_position integer,
  trigram_position integer,
  rrf_score numeric,
  final_score numeric,
  explanation jsonb
)
LANGUAGE sql
STABLE
AS $$
WITH eligible_documents AS MATERIALIZED (
  SELECT d.*
  FROM retrieval.documents d
  WHERE d.is_current
    AND d.index_state = 'ready'
    AND retrieval.acl_visible(d.acl, p_principal)
    AND (p_kinds IS NULL OR d.evidence_kind = ANY(p_kinds))
    AND (p_cluster_id IS NULL OR d.cluster_id = p_cluster_id)
    AND (p_incident_id IS NULL OR d.incident_id = p_incident_id)
    AND (p_account_name IS NULL OR d.account_name = p_account_name)
    AND (p_severities IS NULL OR d.severity = ANY(p_severities))
    AND (p_environment IS NULL OR d.environment = p_environment)
    AND (p_start_date IS NULL OR d.occurred_at >= p_start_date)
    AND (p_end_date IS NULL OR d.occurred_at <= p_end_date)
),
query AS (
  SELECT retrieval.to_or_tsquery(p_query) AS value
),
text_raw AS (
  SELECT
    d.evidence_id,
    d.document_version_id,
    c.chunk_version_id,
    (
      coalesce(ts_rank_cd(d.search_tsv, query.value), 0)
      + coalesce(ts_rank_cd(c.search_tsv, query.value), 0)
    )::numeric AS score,
    c.chunk_ordinal
  FROM eligible_documents d
  JOIN retrieval.chunks c ON c.document_version_id = d.document_version_id
  CROSS JOIN query
  WHERE query.value IS NOT NULL
    AND (d.search_tsv @@ query.value OR c.search_tsv @@ query.value)
  ORDER BY score DESC
  LIMIT greatest(p_limit, p_candidate_pool)
),
text_best AS (
  SELECT DISTINCT ON (text_raw.evidence_id)
    text_raw.*
  FROM text_raw
  ORDER BY text_raw.evidence_id, text_raw.score DESC, text_raw.chunk_ordinal
),
text_ranked AS (
  SELECT
    text_best.*,
    row_number() OVER (ORDER BY text_best.score DESC, text_best.evidence_id)::integer AS position
  FROM text_best
),
vector_raw AS (
  SELECT
    d.evidence_id,
    d.document_version_id,
    c.chunk_version_id,
    (c.embedding <=> p_query_embedding) AS distance,
    c.chunk_ordinal
  FROM retrieval.chunks c
  JOIN eligible_documents d ON d.document_version_id = c.document_version_id
  WHERE p_query_embedding IS NOT NULL
    AND c.embedding_state = 'ready'
    AND c.embedding IS NOT NULL
  ORDER BY c.embedding <=> p_query_embedding
  LIMIT greatest(p_limit, p_candidate_pool)
),
vector_best AS (
  SELECT DISTINCT ON (vector_raw.evidence_id)
    vector_raw.*
  FROM vector_raw
  ORDER BY vector_raw.evidence_id, vector_raw.distance, vector_raw.chunk_ordinal
),
vector_ranked AS (
  SELECT
    vector_best.*,
    (1 - vector_best.distance)::numeric AS score,
    row_number() OVER (ORDER BY vector_best.distance, vector_best.evidence_id)::integer AS position
  FROM vector_best
),
trgm_raw AS (
  SELECT
    d.evidence_id,
    d.document_version_id,
    c.chunk_version_id,
    greatest(
      similarity(d.title, p_query),
      similarity(left(c.chunk_text, 1000), p_query)
    )::numeric AS score,
    c.chunk_ordinal
  FROM eligible_documents d
  JOIN retrieval.chunks c ON c.document_version_id = d.document_version_id
  WHERE p_query IS NOT NULL
    AND btrim(p_query) <> ''
    AND greatest(
      similarity(d.title, p_query),
      similarity(left(c.chunk_text, 1000), p_query)
    ) >= p_fuzzy_threshold
  ORDER BY score DESC
  LIMIT greatest(p_limit, p_candidate_pool)
),
trgm_best AS (
  SELECT DISTINCT ON (trgm_raw.evidence_id)
    trgm_raw.*
  FROM trgm_raw
  ORDER BY trgm_raw.evidence_id, trgm_raw.score DESC, trgm_raw.chunk_ordinal
),
trgm_ranked AS (
  SELECT
    trgm_best.*,
    row_number() OVER (ORDER BY trgm_best.score DESC, trgm_best.evidence_id)::integer AS position
  FROM trgm_best
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
    (
      CASE WHEN t.position IS NULL THEN 0 ELSE p_w_text / (p_rrf_k + t.position) END
      + CASE WHEN v.position IS NULL THEN 0 ELSE p_w_vector / (p_rrf_k + v.position) END
      + CASE WHEN g.position IS NULL THEN 0 ELSE p_w_trgm / (p_rrf_k + g.position) END
    )::numeric AS rrf_score
  FROM all_evidence ids
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
  d.occurred_at,
  left(regexp_replace(c.chunk_text, '\s+', ' ', 'g'), 700) AS snippet,
  s.text_rank,
  s.vector_score,
  s.trigram_score,
  s.text_position,
  s.vector_position,
  s.trigram_position,
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
      'full_text', s.text_position,
      'semantic', s.vector_position,
      'fuzzy', s.trigram_position
    ),
    'weights', jsonb_build_object(
      'full_text', p_w_text,
      'semantic', p_w_vector,
      'fuzzy', p_w_trgm
    ),
    'rrf_k', p_rrf_k,
    'note', 'Raw scores are diagnostic only; final_score is weighted RRF.'
  ) AS explanation
FROM scored s
JOIN eligible_documents d
  ON d.evidence_id = s.evidence_id
 AND d.document_version_id = s.document_version_id
JOIN retrieval.chunks c ON c.chunk_version_id = s.chunk_version_id
ORDER BY s.final_score DESC, d.occurred_at DESC, d.external_key
LIMIT greatest(1, p_limit)
$$;
