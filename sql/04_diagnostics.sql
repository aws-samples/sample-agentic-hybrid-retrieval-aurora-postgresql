CREATE OR REPLACE VIEW retrieval.v_projection_drift AS
SELECT
  source.evidence_id,
  source.external_key,
  'missing_current_document'::text AS issue,
  source.projection_hash AS expected,
  NULL::text AS actual
FROM casework.v_evidence_documents source
LEFT JOIN retrieval.documents document
  ON document.evidence_id = source.evidence_id
 AND document.is_current
WHERE document.document_version_id IS NULL

UNION ALL

SELECT
  source.evidence_id,
  source.external_key,
  'projection_hash_mismatch',
  source.projection_hash,
  document.projection_hash
FROM casework.v_evidence_documents source
JOIN retrieval.documents document
  ON document.evidence_id = source.evidence_id
 AND document.is_current
WHERE document.projection_hash <> source.projection_hash

UNION ALL

SELECT
  source.evidence_id,
  source.external_key,
  'source_revision_mismatch',
  source.source_revision,
  document.source_revision
FROM casework.v_evidence_documents source
JOIN retrieval.documents document
  ON document.evidence_id = source.evidence_id
 AND document.is_current
WHERE document.source_revision <> source.source_revision

UNION ALL

SELECT
  document.evidence_id,
  document.external_key,
  'current_document_not_ready',
  'ready',
  document.index_state
FROM retrieval.documents document
WHERE document.is_current
  AND document.index_state <> 'ready'

UNION ALL

SELECT
  document.evidence_id,
  document.external_key,
  'current_document_for_deleted_source',
  'not current',
  'current'
FROM retrieval.documents document
JOIN casework.evidence_items source ON source.evidence_id = document.evidence_id
WHERE document.is_current
  AND source.is_deleted

UNION ALL

SELECT
  document.evidence_id,
  document.external_key,
  'missing_ready_embedding',
  document.projection_hash,
  chunk.chunk_hash
FROM retrieval.documents document
JOIN retrieval.chunks chunk ON chunk.document_version_id = document.document_version_id
WHERE document.is_current
  AND document.index_state = 'ready'
  AND (
    chunk.embedding_state <> 'ready'
    OR chunk.embedding IS NULL
    OR chunk.embedding_model IS NULL
  );

CREATE OR REPLACE VIEW retrieval.v_projection_health AS
SELECT
  (SELECT count(*) FROM casework.v_evidence_documents) AS source_documents,
  count(DISTINCT document.evidence_id) FILTER (WHERE document.is_current) AS current_documents,
  count(chunk.chunk_version_id) FILTER (WHERE document.is_current) AS current_chunks,
  count(chunk.chunk_version_id) FILTER (
    WHERE document.is_current AND chunk.embedding_state = 'ready'
  ) AS ready_embeddings,
  count(chunk.chunk_version_id) FILTER (
    WHERE document.is_current AND chunk.embedding_state <> 'ready'
  ) AS pending_embeddings,
  (SELECT count(*) FROM retrieval.v_projection_drift) AS drift_issues,
  max(document.indexed_at) FILTER (WHERE document.is_current) AS last_indexed_at
FROM retrieval.documents document
LEFT JOIN retrieval.chunks chunk ON chunk.document_version_id = document.document_version_id;

CREATE OR REPLACE VIEW retrieval.v_corpus_distribution AS
SELECT
  document.evidence_kind,
  count(DISTINCT document.evidence_id) AS documents,
  count(chunk.chunk_version_id) AS chunks,
  min(document.occurred_at) AS oldest_evidence,
  max(document.occurred_at) AS newest_evidence
FROM retrieval.documents document
JOIN retrieval.chunks chunk ON chunk.document_version_id = document.document_version_id
WHERE document.is_current
  AND document.index_state = 'ready'
GROUP BY document.evidence_kind
ORDER BY document.evidence_kind;

CREATE OR REPLACE VIEW retrieval.v_index_usage AS
SELECT
  indexrelname AS index_name,
  idx_scan,
  idx_tup_read,
  idx_tup_fetch,
  pg_relation_size(indexrelid) AS size_bytes,
  pg_size_pretty(pg_relation_size(indexrelid)) AS size_pretty
FROM pg_stat_user_indexes
WHERE schemaname = 'retrieval'
ORDER BY indexrelname;

CREATE OR REPLACE VIEW proof.v_run_receipts AS
SELECT
  run.run_id,
  run.query_text,
  run.retrieval_mode,
  run.embedding_model,
  run.rerank_model,
  run.rerank_applied,
  run.rrf_k,
  run.text_weight,
  run.vector_weight,
  run.fuzzy_weight,
  run.hnsw_ef_search,
  run.hnsw_iterative_scan,
  run.status,
  run.started_at,
  run.completed_at,
  run.latency_ms,
  count(candidate.evidence_id) AS candidate_count,
  max(candidate.result_rank) AS final_rank_count,
  count(candidate.evidence_id) FILTER (WHERE candidate.rerank_score IS NOT NULL) AS reranked_count
FROM proof.retrieval_runs run
LEFT JOIN proof.retrieval_candidates candidate ON candidate.run_id = run.run_id
GROUP BY run.run_id;
