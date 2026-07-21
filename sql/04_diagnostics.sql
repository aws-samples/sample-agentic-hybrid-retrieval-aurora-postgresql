CREATE OR REPLACE VIEW ops.v_corpus_profile AS
SELECT
  count(DISTINCT o.object_id) AS objects,
  count(c.chunk_id) AS chunks,
  count(DISTINCT o.source_system) AS source_systems,
  count(*) FILTER (WHERE c.embedding IS NOT NULL) AS embedded_chunks
FROM ops.source_objects o
LEFT JOIN ops.object_chunks c ON c.object_id = o.object_id
WHERE o.is_active;

CREATE OR REPLACE VIEW ops.v_source_distribution AS
SELECT source_system, source_type, count(*) AS object_count
FROM ops.source_objects
WHERE is_active
GROUP BY 1,2
ORDER BY object_count DESC;

CREATE OR REPLACE VIEW ops.v_embedding_progress AS
SELECT
  count(*) AS total_chunks,
  count(*) FILTER (WHERE embedding IS NOT NULL) AS embedded_chunks,
  round(100.0 * count(*) FILTER (WHERE embedding IS NOT NULL) / nullif(count(*),0), 2) AS pct_embedded
FROM ops.object_chunks c
JOIN ops.source_objects o ON o.object_id = c.object_id
WHERE o.is_active;

CREATE OR REPLACE VIEW ops.v_latest_retrieval_candidates AS
SELECT rc.*, rr.query_text, rr.created_at
FROM ops.retrieval_candidates rc
JOIN ops.retrieval_runs rr ON rr.run_id = rc.run_id
WHERE rr.created_at >= now() - interval '24 hours'
ORDER BY rr.created_at DESC, rc.final_score DESC;
