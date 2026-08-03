-- Search-index drift is an owner-rights operational diagnostic. Its projection
-- is limited to evidence identity, issue, hashes, and revisions; it never returns
-- evidence body text. The pinned search_path prevents caller-controlled name
-- resolution.
CREATE OR REPLACE FUNCTION retrieval.search_index_drift()
RETURNS TABLE (
  evidence_id uuid,
  external_key text,
  issue text,
  expected text,
  actual text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, casework, retrieval
AS $$
  SELECT
    source.evidence_id,
    source.external_key,
    'missing_current_document'::text AS issue,
    source.search_document_hash AS expected,
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
    'search_document_hash_mismatch',
    source.search_document_hash,
    document.search_document_hash
  FROM casework.v_evidence_documents source
  JOIN retrieval.documents document
    ON document.evidence_id = source.evidence_id
   AND document.is_current
  WHERE document.search_document_hash <> source.search_document_hash

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
    source.evidence_id,
    source.external_key,
    'document_acl_mismatch',
    jsonb_build_object(
      'acl', source.acl,
      'visibility', coalesce(source.acl ->> 'visibility', 'restricted'),
      'principals', coalesce(source.acl -> 'principals', '[]'::jsonb)
    )::text,
    jsonb_build_object(
      'acl', document.acl,
      'visibility', document.acl_visibility,
      'principals', to_jsonb(document.acl_principals)
    )::text
  FROM casework.evidence_items source
  JOIN retrieval.documents document
    ON document.evidence_id = source.evidence_id
   AND document.is_current
  WHERE document.acl IS DISTINCT FROM source.acl
     OR document.acl_visibility IS DISTINCT FROM
       coalesce(source.acl ->> 'visibility', 'restricted')
     OR to_jsonb(document.acl_principals) IS DISTINCT FROM
       coalesce(source.acl -> 'principals', '[]'::jsonb)

  UNION ALL

  SELECT
    document.evidence_id,
    document.external_key,
    'missing_ready_embedding',
    document.search_document_hash,
    chunk.chunk_hash
  FROM retrieval.documents document
  JOIN retrieval.chunks chunk ON chunk.document_version_id = document.document_version_id
  WHERE document.is_current
    AND document.index_state = 'ready'
    AND (
      chunk.embedding_state <> 'ready'
      OR chunk.embedding IS NULL
      OR chunk.embedding_model IS NULL
    )

  UNION ALL

  SELECT
    document.evidence_id,
    document.external_key,
    'chunk_currency_mismatch',
    document.is_current::text,
    chunk.is_current::text
  FROM retrieval.documents document
  JOIN retrieval.chunks chunk
    ON chunk.document_version_id = document.document_version_id
  WHERE document.is_current IS DISTINCT FROM chunk.is_current

  UNION ALL

  SELECT
    document.evidence_id,
    document.external_key,
    'chunk_acl_mismatch',
    jsonb_build_object(
      'acl', document.acl,
      'visibility', document.acl_visibility,
      'principals', to_jsonb(document.acl_principals)
    )::text,
    jsonb_build_object(
      'acl', chunk.acl,
      'visibility', chunk.acl_visibility,
      'principals', to_jsonb(chunk.acl_principals)
    )::text
  FROM retrieval.documents document
  JOIN retrieval.chunks chunk
    ON chunk.document_version_id = document.document_version_id
  WHERE chunk.acl IS DISTINCT FROM document.acl
     OR chunk.acl_visibility IS DISTINCT FROM document.acl_visibility
     OR chunk.acl_principals IS DISTINCT FROM document.acl_principals;
$$;

COMMENT ON FUNCTION retrieval.search_index_drift() IS
  'Owner-rights drift computation with a pinned search_path. Projection stays '
  'identity + hashes + revisions, never evidence body text.';

-- The database owner invokes this through the stable diagnostic view.
REVOKE ALL ON FUNCTION retrieval.search_index_drift() FROM PUBLIC;

-- The view stays the stable name used by health checks and readiness assertions.
CREATE OR REPLACE VIEW retrieval.v_search_index_drift AS
SELECT * FROM retrieval.search_index_drift();

DROP FUNCTION IF EXISTS casework.assert_release_capture_ready();
DROP VIEW IF EXISTS casework.v_release_capture_validation;

CREATE OR REPLACE VIEW casework.v_live_capture_validation AS
WITH captures AS (
  SELECT *
  FROM casework.incident_capture_runs
  WHERE capture_origin = 'participant_induced'
),
checks AS (
  SELECT
    capture.capture_id,
    capture.capture_key,
    capture.cluster_id,
    capture.engine_version,
    capture.instance_class,
    capture.relation_oid,
    capture.capture_started_at,
    (
      capture.observed_row_count IS NOT NULL
      AND capture.table_size_bytes IS NOT NULL
      AND capture.steady_state_connections > 0
      AND capture.source_bundle_sha256 IS NOT NULL
      AND capture.observability_verified_at IS NOT NULL
    ) AS capture_profile_complete,
    EXISTS (
      SELECT 1
      FROM casework.pg_stat_activity_samples activity
      WHERE activity.capture_id = capture.capture_id
        AND activity.state = 'active'
        AND activity.wait_event_type = 'Lock'
        AND lower(activity.wait_event) = 'relation'
        AND activity.query_start IS NOT NULL
    ) AS activity_proves_wait,
    (
      SELECT
        count(*) >= 270
        AND count(DISTINCT activity.observation_number) = 30
      FROM casework.pg_stat_activity_samples activity
      WHERE activity.capture_id = capture.capture_id
    ) AS activity_scale_complete,
    EXISTS (
      SELECT 1
      FROM casework.pg_lock_samples lock_sample
      WHERE lock_sample.capture_id = capture.capture_id
        AND lock_sample.relation_oid = capture.relation_oid
        AND lock_sample.mode = 'ShareLock'
        AND lock_sample.granted
    ) AS blocker_share_lock_granted,
    EXISTS (
      SELECT 1
      FROM casework.pg_lock_samples lock_sample
      WHERE lock_sample.capture_id = capture.capture_id
        AND lock_sample.relation_oid = capture.relation_oid
        AND lock_sample.mode = 'RowExclusiveLock'
        AND NOT lock_sample.granted
    ) AS writer_row_exclusive_waiting,
    (
      SELECT
        count(*) >= 270
        AND count(DISTINCT lock_sample.observation_number) = 30
      FROM casework.pg_lock_samples lock_sample
      WHERE lock_sample.capture_id = capture.capture_id
    ) AS lock_scale_complete,
    EXISTS (
      SELECT 1
      FROM casework.pg_blocking_pids_samples blockers
      WHERE blockers.capture_id = capture.capture_id
        AND cardinality(blockers.blocking_pids) > 0
        AND blockers.literal_sql ~ '^SELECT pg_blocking_pids\([0-9]+\);$'
    ) AS blocking_pids_captured,
    (
      SELECT
        count(*) >= 180
        AND count(DISTINCT blockers.observation_number) = 30
      FROM casework.pg_blocking_pids_samples blockers
      WHERE blockers.capture_id = capture.capture_id
    ) AS blocking_scale_complete,
    (
      SELECT count(DISTINCT stats.phase) = 3
      FROM casework.pg_stat_statements_samples stats
      WHERE stats.capture_id = capture.capture_id
    ) AS statement_phases_complete,
    EXISTS (
      SELECT 1
      FROM casework.pg_stat_statements_samples stats
      WHERE stats.capture_id = capture.capture_id
        AND stats.phase = 'after'
        AND (stats.delta_from_before ->> 'calls')::bigint >= 8
        AND (stats.delta_from_before ->> 'total_exec_time')::double precision > 0
    ) AS statement_delta_measured,
    (
      SELECT count(DISTINCT metric.metric_name) = 5
      FROM casework.cloudwatch_metric_samples metric
      WHERE metric.capture_id = capture.capture_id
        AND metric.metric_name = ANY (
          ARRAY[
            'WriteLatency',
            'WriteIOPS',
            'WriteThroughput',
            'CommitThroughput',
            'DatabaseConnections'
          ]
        )
    ) AS cloudwatch_metrics_complete,
    EXISTS (
      SELECT 1
      FROM casework.database_insights_samples insight
      WHERE insight.capture_id = capture.capture_id
        AND insight.evidence_type = 'top_wait'
        AND insight.dimension_value = 'Lock:relation'
    ) AS top_wait_lock_relation,
    (
      SELECT count(*) BETWEEN 100 AND 120
      FROM casework.telemetry_evidence telemetry
      WHERE telemetry.capture_id = capture.capture_id
    ) AS telemetry_projection_complete,
    EXISTS (
      SELECT 1
      FROM casework.database_insights_samples insight
      WHERE insight.capture_id = capture.capture_id
        AND insight.evidence_type = 'top_sql'
        AND insight.statement ~* 'CREATE[[:space:]]+INDEX'
    ) AS top_sql_contains_index_build
  FROM captures capture
)
SELECT
  checks.*,
  (
    capture_profile_complete
    AND activity_proves_wait
    AND activity_scale_complete
    AND blocker_share_lock_granted
    AND writer_row_exclusive_waiting
    AND lock_scale_complete
    AND blocking_pids_captured
    AND blocking_scale_complete
    AND statement_phases_complete
    AND statement_delta_measured
    AND cloudwatch_metrics_complete
    AND top_wait_lock_relation
    AND telemetry_projection_complete
  ) AS live_ready
FROM checks;

-- Owner-rights for the same reason retrieval.search_index_drift() above is: this
-- is a readiness assertion over capture COMPLETENESS, not an evidence read, and
-- its projection is boolean checks plus capture identity -- never statement text.
--
-- SECURITY DEFINER is load-bearing when sql/12_masking.sql is applied. The view
-- predicates on casework.database_insights_samples.statement (top_sql_contains_index
-- build, above), and that column is masked for persona_app_engineer and
-- persona_auditor. pg_columnmask refuses any predicate touching a masked column:
--   ERROR: Predicates on masked columns are not allowed
-- Measured on Aurora PostgreSQL 18.3 as an invoker-rights function, both masked
-- personas got that error instead of a receipt, which broke `make doctor`
-- (backend/scripts/doctor.py checks out get_dict_conn("app_engineer")) while
-- persona_dba and the owner passed -- so the failure looked persona-specific and
-- unrelated to masking. Measured again with SECURITY DEFINER: both personas read it.
-- pg_columnmask evaluates policies against the EFFECTIVE role, so a definer
-- function owned by the unmasked owner is not subject to the caller's mask.
--
-- This grants no extra evidence visibility. The rows it counts are capture
-- telemetry that sql/11_roles_rls.sql already makes readable to every persona via
-- the capture-run gate, and the pinned search_path prevents caller-controlled
-- name resolution.
CREATE OR REPLACE FUNCTION casework.assert_live_capture_ready()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, casework, retrieval
AS $$
DECLARE
  validation casework.v_live_capture_validation%ROWTYPE;
BEGIN
  SELECT *
  INTO validation
  FROM casework.v_live_capture_validation
  ORDER BY capture_started_at DESC
  LIMIT 1;

  IF validation.capture_id IS NULL THEN
    RAISE EXCEPTION 'no participant-induced live capture is loaded';
  END IF;

  IF NOT validation.live_ready THEN
    RAISE EXCEPTION
      'live capture % is incomplete: %',
      validation.capture_key,
      to_jsonb(validation);
  END IF;

  RETURN to_jsonb(validation);
END
$$;

CREATE OR REPLACE VIEW retrieval.v_search_index_health AS
WITH source_summary AS (
  SELECT count(*) AS documents
  FROM casework.evidence_items
  WHERE NOT is_deleted
),
document_summary AS (
  SELECT
    count(*) AS documents,
    max(indexed_at) AS last_indexed_at
  FROM retrieval.documents
  WHERE is_current
    AND index_state = 'ready'
),
chunk_summary AS (
  SELECT
    count(*) AS chunks,
    count(*) FILTER (
      WHERE embedding_state = 'ready'
        AND embedding IS NOT NULL
        AND embedding_model IS NOT NULL
    ) AS ready_embeddings,
    count(*) FILTER (
      WHERE embedding_state <> 'ready'
        OR embedding IS NULL
        OR embedding_model IS NULL
    ) AS pending_embeddings
  FROM retrieval.chunks
  WHERE is_current
),
revision_drift AS (
  SELECT count(*) AS issues
  FROM casework.evidence_items source
  LEFT JOIN retrieval.documents document
    ON document.evidence_id = source.evidence_id
   AND document.is_current
  WHERE NOT source.is_deleted
    AND (
      document.document_version_id IS NULL
      OR document.index_state <> 'ready'
      OR document.source_revision <> source.source_revision
    )
),
deleted_source_drift AS (
  SELECT count(*) AS issues
  FROM retrieval.documents document
  JOIN casework.evidence_items source
    ON source.evidence_id = document.evidence_id
  WHERE document.is_current
    AND source.is_deleted
),
chunk_drift AS (
  SELECT count(DISTINCT document.evidence_id) AS issues
  FROM retrieval.documents document
  LEFT JOIN retrieval.chunks chunk
    ON chunk.document_version_id = document.document_version_id
   AND chunk.is_current
  WHERE document.is_current
    AND document.index_state = 'ready'
    AND (
      chunk.chunk_version_id IS NULL
      OR chunk.embedding_state <> 'ready'
      OR chunk.embedding IS NULL
      OR chunk.embedding_model IS NULL
    )
),
currency_drift AS (
  SELECT count(*) AS issues
  FROM retrieval.documents document
  JOIN retrieval.chunks chunk
    ON chunk.document_version_id = document.document_version_id
  WHERE document.is_current IS DISTINCT FROM chunk.is_current
),
queue_drift AS (
  SELECT count(*) AS issues
  FROM retrieval.search_index_queue
  WHERE status IN ('pending', 'claimed', 'failed')
)
SELECT
  source_summary.documents AS source_documents,
  document_summary.documents AS current_documents,
  chunk_summary.chunks AS current_chunks,
  chunk_summary.ready_embeddings,
  chunk_summary.pending_embeddings,
  (
    revision_drift.issues
    + deleted_source_drift.issues
    + chunk_drift.issues
    + currency_drift.issues
    + queue_drift.issues
  ) AS drift_issues,
  document_summary.last_indexed_at
FROM source_summary
CROSS JOIN document_summary
CROSS JOIN chunk_summary
CROSS JOIN revision_drift
CROSS JOIN deleted_source_drift
CROSS JOIN chunk_drift
CROSS JOIN currency_drift
CROSS JOIN queue_drift;

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

-- The receipt view's last column changed from principal jsonb to role text
-- (A7). CREATE OR REPLACE VIEW cannot rename or retype a column, so the view
-- is dropped first. It carries no grants of its own (sql/11 grants by schema).
DROP VIEW IF EXISTS proof.v_run_receipts;

CREATE OR REPLACE VIEW proof.v_run_receipts
WITH (security_invoker = true) AS
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
  count(candidate.evidence_id) FILTER (WHERE candidate.rerank_score IS NOT NULL) AS reranked_count,
  run.fuzzy_threshold,
  run.identifier_tokens,
  run.fuzzy_probe_tokens,
  run.candidate_pool,
  run.role
FROM proof.retrieval_runs run
LEFT JOIN proof.retrieval_candidates candidate ON candidate.run_id = run.run_id
GROUP BY run.run_id;
