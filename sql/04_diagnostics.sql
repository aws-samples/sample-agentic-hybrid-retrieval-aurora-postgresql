-- retrieval.v_search_index_drift is a COUNT_ONLY view (backend/tests/test_db_persona.py's
-- COUNT_ONLY_VIEWS): its own reloptions are owner-rights (no security_invoker) so
-- assert_search_index_ready() reports one persona-invariant count, matching
-- v_search_index_health's independent drift computation below. Three of its five
-- arms used to select FROM casework.v_evidence_documents, and that view is one of
-- the six CONTENT_VIEWS Task 10 made `security_invoker = true` so a reader of
-- evidence TEXT gets the caller's RLS. An owner-rights outer view nesting a
-- security_invoker inner view does NOT recover owner rights over the inner one --
-- measured on PG17: the inner view still applies the invoker's policies, so this
-- view's row count silently varied by persona (2 rows as owner, 1 as
-- persona_app_engineer, identical database state) while its own reloptions looked
-- correct. assert_search_index_ready() (sql/07_search_index_verification.sql)
-- counts this view and would raise a persona-dependent WRONG count.
--
-- Fixed with a SECURITY DEFINER function rather than duplicating
-- v_evidence_documents' rendering/hash logic (option (a) in the brief) or
-- restating the policy predicate against the detail tables directly (also (a) --
-- those tables are RLS-forced too, so it would not have fixed anything). The
-- function's body is a verbatim copy of the five arms below computed as the
-- OWNER regardless of caller, with search_path pinned so it cannot be tricked into
-- resolving an unqualified name through a caller-controlled schema, EXECUTE
-- revoked from PUBLIC and granted only to the three personas, and its projection
-- held to exactly evidence_id/external_key/issue/expected/actual -- identity plus
-- hashes and revisions, never the evidence body. It cannot be used to read
-- anything beyond that projection: it takes no arguments, so there is no
-- parameter to widen the query with, and it is LANGUAGE sql (no dynamic SQL, no
-- EXECUTE of caller-influenced text).
--
-- JUDGMENT CALL: this makes a restricted row's external_key (and its hash /
-- revision) visible in the drift report to persona_app_engineer, which cannot read the
-- row's content. Before this fix persona_app_engineer already saw a (wrong, partial)
-- drift count with SOME external_keys in it -- the leak direction is not new, the
-- set App Engineer sees now grows to match owner/DBA/Auditor exactly. The
-- alternative -- keeping the view App-Engineer-scoped -- is the C2 defect itself: a
-- persona-dependent count feeding an exception message and a health check that
-- both claim to be one global operational fact. An operational-health surface
-- (row exists / hash matches / embedding ready) naming a restricted item's key
-- alongside a hash is judged an acceptable disclosure for the same reason the
-- other three COUNT_ONLY_VIEWS already are: they are diagnostics about the index,
-- not evidence content, and the six CONTENT_VIEWS remain the only surface where
-- restricted evidence TEXT is gated by persona.
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
  'Owner-rights drift computation for retrieval.v_search_index_drift (C2 fix). '
  'SECURITY DEFINER with a pinned search_path so every persona measures the same '
  'operational-drift row set that assert_search_index_ready() compares against '
  'v_search_index_health. Projection stays identity + hashes + revisions, never '
  'evidence body text.';

-- PUBLIC gets EXECUTE on every new function by default (same trap sql/11 documents
-- for casework.admit_evidence); revoke it and grant only the read personas. Guarded
-- because sql/04 runs BEFORE sql/11 creates the personas on a fresh database --
-- the same guard shape sql/03_search_functions.sql uses for its own re-grant.
REVOKE ALL ON FUNCTION retrieval.search_index_drift() FROM PUBLIC;
DO $$
BEGIN
  IF to_regrole('persona_app_engineer') IS NOT NULL
     AND to_regrole('persona_dba') IS NOT NULL
     AND to_regrole('persona_auditor') IS NOT NULL THEN
    GRANT EXECUTE ON FUNCTION retrieval.search_index_drift()
      TO persona_app_engineer, persona_dba, persona_auditor;
  END IF;
END
$$;

-- The view stays the stable name every caller (backend/app/insights.py,
-- assert_search_index_ready(), backend/tests/test_db_persona.py's
-- COUNT_ONLY_VIEWS) already queries by. Its own reloptions are still owner-rights
-- (no security_invoker), which is correct and is what the fix restores: the
-- defect was the NESTED view leaking the invoker's RLS through, not this view's
-- own setting.
CREATE OR REPLACE VIEW retrieval.v_search_index_drift AS
SELECT * FROM retrieval.search_index_drift();

CREATE OR REPLACE VIEW casework.v_release_capture_validation AS
WITH captures AS (
  SELECT *
  FROM casework.fixture_captures
  WHERE capture_mode = 'release_aurora'
),
checks AS (
  SELECT
    capture.capture_id,
    capture.capture_key,
    capture.cluster_id,
    capture.engine_version,
    capture.instance_class,
    capture.relation_oid,
    (
      capture.observed_row_count IS NOT NULL
      AND capture.table_size_bytes IS NOT NULL
      AND capture.steady_state_connections > 0
      AND capture.source_bundle_sha256 IS NOT NULL
      AND capture.release_verified_at IS NOT NULL
    ) AS fixture_profile_complete,
    EXISTS (
      SELECT 1
      FROM casework.pg_stat_activity_samples activity
      WHERE activity.capture_id = capture.capture_id
        AND activity.state = 'active'
        AND activity.wait_event_type = 'Lock'
        AND lower(activity.wait_event) = 'relation'
        AND activity.query_start IS NOT NULL
    ) AS activity_proves_wait,
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
    EXISTS (
      SELECT 1
      FROM casework.pg_blocking_pids_samples blockers
      WHERE blockers.capture_id = capture.capture_id
        AND cardinality(blockers.blocking_pids) > 0
        AND blockers.literal_sql ~ '^SELECT pg_blocking_pids\([0-9]+\);$'
    ) AS blocking_pids_captured,
    (
      SELECT count(DISTINCT stats.phase) = 3
      FROM casework.pg_stat_statements_samples stats
      WHERE stats.capture_id = capture.capture_id
        AND stats.query ~* '^(INSERT|UPDATE|DELETE)[[:space:]]'
    ) AS statement_phases_complete,
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
    fixture_profile_complete
    AND activity_proves_wait
    AND blocker_share_lock_granted
    AND writer_row_exclusive_waiting
    AND blocking_pids_captured
    AND statement_phases_complete
    AND cloudwatch_metrics_complete
    AND top_wait_lock_relation
  ) AS release_ready
FROM checks;

CREATE OR REPLACE FUNCTION casework.assert_release_capture_ready()
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
  validation casework.v_release_capture_validation%ROWTYPE;
BEGIN
  SELECT *
  INTO validation
  FROM casework.v_release_capture_validation
  ORDER BY capture_key
  LIMIT 1;

  IF validation.capture_id IS NULL THEN
    RAISE EXCEPTION 'no release_aurora capture is loaded';
  END IF;

  IF NOT validation.release_ready THEN
    RAISE EXCEPTION
      'release capture % is incomplete: %',
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
