\set ON_ERROR_STOP on
\pset pager off
\timing on

-- `make live-workshop` renders these values from the current Investigation Evidence receipt.
\set incident_key '{{INCIDENT_KEY}}'
\set backfill_change_key '{{UNSAFE_CHANGE_KEY}}'
\set analyze_change_key '{{ANALYZE_CHANGE_KEY}}'
\set fuzzy_change_key '{{FUZZY_CHANGE_KEY}}'

\if :{?run_id}
\else
  \echo 'REMEDY: pass -v run_id=<retrieval-run-uuid> from one hybrid API request'
  \quit 1
\endif

BEGIN;

CREATE TEMP TABLE lab2_scope ON COMMIT DROP AS
SELECT
  :'incident_key'::text AS incident_key,
  :'backfill_change_key'::text AS backfill_change_key,
  :'analyze_change_key'::text AS analyze_change_key,
  :'fuzzy_change_key'::text AS fuzzy_change_key;

\echo ''
\echo '1. Inspect the physical retrieval indexes'
SELECT
  indexname,
  CASE
    WHEN indexdef ILIKE '%USING hnsw%' THEN 'semantic / HNSW'
    WHEN indexdef ILIKE '%gin_trgm_ops%' THEN 'fuzzy / GIN trigram'
    WHEN indexdef ILIKE '%USING gin%search_tsv%' THEN 'lexical / GIN tsvector'
    WHEN indexname = 'idx_documents_external_key_exact'
      THEN 'exact / B-tree expression'
    ELSE 'supporting'
  END AS retrieval_job
FROM retrieval.v_index_definitions
WHERE indexname IN (
  'idx_documents_external_key_exact',
  'idx_documents_search_tsv',
  'idx_chunks_search_tsv',
  'idx_documents_external_key_trgm',
  'idx_chunks_embedding_hnsw'
)
ORDER BY indexname;

\echo ''
\echo '2. Resolve the current backfill change through exact retrieval'
CREATE TEMP TABLE lab2_exact ON COMMIT DROP AS
SELECT
  document.external_key,
  document.evidence_kind,
  document.title
FROM retrieval.documents document
CROSS JOIN lab2_scope scope
WHERE document.is_current
  AND document.index_state = 'ready'
  AND document.source_system = 'pg_incident_capture'
  AND document.incident_id = scope.incident_key
  AND retrieval.acl_visible(document.acl)
  AND lower(document.external_key) = lower(scope.backfill_change_key);

TABLE lab2_exact;

DO $checkpoint$
BEGIN
  IF (SELECT count(*) FROM lab2_exact) <> 1 THEN
    RAISE EXCEPTION
      'REMEDY: exact lookup must return the current-run backfill change once';
  END IF;
END
$checkpoint$;

\echo ''
\echo '3. Rank mixed Investigation Evidence records with PostgreSQL full-text search'
-- Pool-boundary callers fail with psycopg_pool.PoolTimeout before PostgreSQL
-- can assign them a backend.
CREATE TEMP TABLE lab2_fts ON COMMIT DROP AS
WITH query AS (
  SELECT retrieval.to_or_tsquery(
    'priority tier migration backfill transaction pool timeout analyze '
    'sequential scan'
  ) AS value
),
ranked AS (
  SELECT
    document.evidence_id,
    document.external_key,
    document.evidence_kind,
    document.title,
    (
      ts_rank_cd(document.search_tsv, query.value)
      + ts_rank_cd(chunk.search_tsv, query.value)
    )::numeric AS text_score,
    row_number() OVER (
      PARTITION BY document.evidence_id
      ORDER BY
        (
          ts_rank_cd(document.search_tsv, query.value)
          + ts_rank_cd(chunk.search_tsv, query.value)
        ) DESC,
        chunk.chunk_ordinal
    ) AS passage_rank
  FROM retrieval.documents document
  JOIN retrieval.chunks chunk
    ON chunk.document_version_id = document.document_version_id
  CROSS JOIN query
  CROSS JOIN lab2_scope scope
  WHERE document.is_current
    AND document.index_state = 'ready'
    AND chunk.is_current
    AND chunk.embedding_state = 'ready'
    AND document.source_system = 'pg_incident_capture'
    AND chunk.source_system = 'pg_incident_capture'
    AND document.incident_id = scope.incident_key
    AND chunk.incident_id = scope.incident_key
    AND retrieval.acl_visible(document.acl)
    AND retrieval.acl_visible(chunk.acl)
    AND (
      document.search_tsv @@ query.value
      OR chunk.search_tsv @@ query.value
    )
)
SELECT
  external_key,
  evidence_kind,
  title,
  text_score
FROM ranked
WHERE passage_rank = 1;

SELECT
  external_key,
  evidence_kind,
  round(text_score, 4) AS text_score
FROM lab2_fts
ORDER BY text_score DESC, external_key
LIMIT 8;

DO $checkpoint$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM lab2_fts WHERE evidence_kind = 'change'
  ) OR NOT EXISTS (
    SELECT 1 FROM lab2_fts WHERE evidence_kind <> 'change'
  ) THEN
    RAISE EXCEPTION
      'REMEDY: the lexical query must return mixed current-run evidence kinds';
  END IF;
END
$checkpoint$;

\echo ''
\echo '4. Add the change filter before candidates enter fusion'
CREATE TEMP TABLE lab2_filtered_fts ON COMMIT DROP AS
SELECT *
FROM lab2_fts
-- TODO: uncomment the next line so only measured changes enter fusion.
-- WHERE evidence_kind = 'change'
;

SELECT
  external_key,
  evidence_kind,
  round(text_score, 4) AS text_score
FROM lab2_filtered_fts
ORDER BY text_score DESC, external_key
LIMIT 8;

DO $checkpoint$
DECLARE
  expected_change_keys text[];
  actual_change_keys text[];
BEGIN
  SELECT ARRAY[
    scope.backfill_change_key,
    scope.analyze_change_key
  ]::text[]
  INTO expected_change_keys
  FROM lab2_scope scope;

  SELECT array_agg(result.external_key ORDER BY result.external_key)
  INTO actual_change_keys
  FROM lab2_filtered_fts result;

  IF EXISTS (
    SELECT 1
    FROM lab2_filtered_fts
    WHERE evidence_kind <> 'change'
  ) OR actual_change_keys IS DISTINCT FROM expected_change_keys THEN
    RAISE EXCEPTION
      'REMEDY: add the change filter; both measured Investigation Evidence changes must remain';
  END IF;
END
$checkpoint$;

\echo ''
\echo '5. Use the persisted Bedrock query embedding for pgvector retrieval'
CREATE TEMP TABLE lab2_query_vector ON COMMIT DROP AS
SELECT
  run.query_embedding,
  run.embedding_model
FROM proof.retrieval_runs run
WHERE run.run_id = :'run_id'::uuid
  AND run.status = 'complete'
  AND run.query_embedding IS NOT NULL
  AND run.embedding_model IS NOT NULL;

DO $checkpoint$
BEGIN
  IF (SELECT count(*) FROM lab2_query_vector) <> 1 THEN
    RAISE EXCEPTION
      'REMEDY: run one hybrid API request first to persist its query embedding';
  END IF;
END
$checkpoint$;

CREATE TEMP TABLE lab2_semantic ON COMMIT DROP AS
SELECT
  document.external_key,
  document.evidence_kind,
  chunk.chunk_ordinal,
  (chunk.embedding <=> query_vector.query_embedding)::numeric AS distance
FROM retrieval.chunks chunk
JOIN retrieval.documents document
  ON document.document_version_id = chunk.document_version_id
CROSS JOIN lab2_query_vector query_vector
CROSS JOIN lab2_scope scope
WHERE chunk.is_current
  AND chunk.embedding_state = 'ready'
  AND chunk.embedding IS NOT NULL
  AND chunk.embedding_model = query_vector.embedding_model
  AND document.is_current
  AND document.index_state = 'ready'
  AND chunk.source_system = 'pg_incident_capture'
  AND document.source_system = 'pg_incident_capture'
  AND chunk.incident_id = scope.incident_key
  AND document.incident_id = scope.incident_key
  AND retrieval.acl_visible(chunk.acl)
  AND retrieval.acl_visible(document.acl)
ORDER BY chunk.embedding <=> query_vector.query_embedding
LIMIT 5;

SELECT
  external_key,
  evidence_kind,
  chunk_ordinal,
  round((1 - distance), 4) AS cosine_similarity
FROM lab2_semantic
ORDER BY distance, external_key;

\echo ''
\echo '6. Recover the mistyped backfill change with pg_trgm'
SET LOCAL pg_trgm.similarity_threshold = 0.3;

CREATE TEMP TABLE lab2_fuzzy ON COMMIT DROP AS
SELECT
  document.external_key,
  document.evidence_kind,
  similarity(
    document.external_key,
    scope.fuzzy_change_key
  )::numeric AS trigram_score
FROM retrieval.documents document
CROSS JOIN lab2_scope scope
WHERE document.is_current
  AND document.index_state = 'ready'
  AND document.source_system = 'pg_incident_capture'
  AND document.incident_id = scope.incident_key
  AND retrieval.acl_visible(document.acl)
  AND document.external_key % scope.fuzzy_change_key
ORDER BY similarity(document.external_key, scope.fuzzy_change_key) DESC
LIMIT 5;

SELECT
  external_key,
  evidence_kind,
  round(trigram_score, 4) AS trigram_score
FROM lab2_fuzzy
ORDER BY trigram_score DESC, external_key;

DO $checkpoint$
BEGIN
  IF (
    SELECT external_key
    FROM lab2_fuzzy
    ORDER BY trigram_score DESC, external_key
    LIMIT 1
  ) IS DISTINCT FROM (
    SELECT backfill_change_key FROM lab2_scope
  ) THEN
    RAISE EXCEPTION
      'REMEDY: the mistyped key must recover the backfill change at rank 1';
  END IF;
END
$checkpoint$;

\echo ''
\echo '7. Inspect lexical and vector plans on the live corpus'
\echo 'A sequential scan can be the correct plan at workshop corpus scale.'

EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
WITH query AS (
  SELECT retrieval.to_or_tsquery(
    'priority tier backfill pool timeout sequential scan'
  ) AS value
)
SELECT
  document.external_key,
  ts_rank_cd(document.search_tsv, query.value) AS text_score
FROM retrieval.documents document
CROSS JOIN query
CROSS JOIN lab2_scope scope
WHERE document.is_current
  AND document.index_state = 'ready'
  AND document.source_system = 'pg_incident_capture'
  AND document.incident_id = scope.incident_key
  AND retrieval.acl_visible(document.acl)
  AND document.search_tsv @@ query.value
ORDER BY text_score DESC
LIMIT 5;

EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT
  document.external_key,
  chunk.embedding <=> query_vector.query_embedding AS distance
FROM retrieval.chunks chunk
JOIN retrieval.documents document
  ON document.document_version_id = chunk.document_version_id
CROSS JOIN lab2_query_vector query_vector
CROSS JOIN lab2_scope scope
WHERE chunk.is_current
  AND chunk.embedding_state = 'ready'
  AND chunk.embedding IS NOT NULL
  AND chunk.embedding_model = query_vector.embedding_model
  AND document.is_current
  AND document.index_state = 'ready'
  AND chunk.source_system = 'pg_incident_capture'
  AND document.source_system = 'pg_incident_capture'
  AND chunk.incident_id = scope.incident_key
  AND document.incident_id = scope.incident_key
  AND retrieval.acl_visible(chunk.acl)
  AND retrieval.acl_visible(document.acl)
ORDER BY chunk.embedding <=> query_vector.query_embedding
LIMIT 5;

\echo 'OK: exact, FTS, semantic, fuzzy, filter, and plan checks passed'
ROLLBACK;
