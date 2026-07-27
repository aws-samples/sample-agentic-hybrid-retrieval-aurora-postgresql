CREATE INDEX IF NOT EXISTS idx_incidents_cluster_started
  ON casework.incidents(cluster_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_changes_cluster_started
  ON casework.changes(cluster_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_support_cases_account_opened
  ON casework.support_cases(account_name, opened_at DESC);

CREATE INDEX IF NOT EXISTS idx_lock_evidence_incident_captured
  ON casework.lock_evidence(incident_evidence_id, captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_activity_samples_capture_pid
  ON casework.pg_stat_activity_samples(capture_id, captured_at, pid);

CREATE INDEX IF NOT EXISTS idx_lock_samples_capture_relation
  ON casework.pg_lock_samples(capture_id, captured_at, relation_oid, granted, mode);

CREATE INDEX IF NOT EXISTS idx_blocking_pids_capture
  ON casework.pg_blocking_pids_samples(capture_id, captured_at, blocked_pid);

CREATE INDEX IF NOT EXISTS idx_stat_statements_capture_phase
  ON casework.pg_stat_statements_samples(capture_id, phase, captured_at, queryid);

CREATE INDEX IF NOT EXISTS idx_cloudwatch_capture_metric
  ON casework.cloudwatch_metric_samples(capture_id, metric_name, observed_at);

CREATE INDEX IF NOT EXISTS idx_database_insights_capture_type
  ON casework.database_insights_samples(capture_id, evidence_type, captured_at);

CREATE INDEX IF NOT EXISTS idx_search_index_queue_pending
  ON retrieval.search_index_queue(status, requested_at)
  WHERE status IN ('pending', 'failed');

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_one_current
  ON retrieval.documents(evidence_id)
  WHERE is_current;

CREATE INDEX IF NOT EXISTS idx_documents_kind_time
  ON retrieval.documents(evidence_kind, occurred_at DESC)
  WHERE is_current AND index_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_documents_cluster_time
  ON retrieval.documents(cluster_id, occurred_at DESC)
  WHERE is_current AND index_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_documents_incident
  ON retrieval.documents(incident_id)
  WHERE is_current AND index_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_documents_account
  ON retrieval.documents(account_name)
  WHERE is_current AND index_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_documents_severity
  ON retrieval.documents(severity)
  WHERE is_current AND index_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_documents_acl
  ON retrieval.documents USING GIN(acl)
  WHERE is_current AND index_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_documents_acl_visibility
  ON retrieval.documents(acl_visibility)
  WHERE is_current AND index_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_documents_acl_principals
  ON retrieval.documents USING GIN(acl_principals)
  WHERE is_current AND index_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_documents_service_engine_region
  ON retrieval.documents(service_name, engine_version, aws_region)
  WHERE is_current AND index_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_documents_search_tsv
  ON retrieval.documents USING GIN(search_tsv)
  WHERE is_current AND index_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_documents_title_trgm
  ON retrieval.documents USING GIN(title gin_trgm_ops)
  WHERE is_current AND index_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_documents_external_key_trgm
  ON retrieval.documents USING GIN(external_key gin_trgm_ops)
  WHERE is_current AND index_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_documents_external_key_exact
  ON retrieval.documents(lower(external_key))
  WHERE is_current AND index_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_chunks_document
  ON retrieval.chunks(document_version_id, chunk_ordinal);

CREATE INDEX IF NOT EXISTS idx_chunks_evidence
  ON retrieval.chunks(evidence_id, chunk_ordinal)
  WHERE is_current AND embedding_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_chunks_filters
  ON retrieval.chunks(
    cluster_id,
    incident_id,
    evidence_kind,
    occurred_at
  )
  WHERE is_current AND embedding_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_chunks_account_severity
  ON retrieval.chunks(account_name, severity)
  WHERE is_current AND embedding_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_chunks_service_engine_region
  ON retrieval.chunks(service_name, engine_version, aws_region)
  WHERE is_current AND embedding_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_chunks_acl_visibility
  ON retrieval.chunks(acl_visibility)
  WHERE is_current AND embedding_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_chunks_acl_principals
  ON retrieval.chunks USING GIN(acl_principals)
  WHERE is_current AND embedding_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_chunks_search_tsv
  ON retrieval.chunks USING GIN(search_tsv);

DROP INDEX IF EXISTS retrieval.idx_chunks_text_trgm;

CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
  ON retrieval.chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64)
  WHERE is_current
    AND embedding_state = 'ready'
    AND embedding IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_inferred_edges_from
  ON retrieval.inferred_edges(from_evidence_id, relation);

CREATE INDEX IF NOT EXISTS idx_inferred_edges_to
  ON retrieval.inferred_edges(to_evidence_id, relation);

CREATE INDEX IF NOT EXISTS idx_runs_started
  ON proof.retrieval_runs(started_at DESC);

CREATE INDEX IF NOT EXISTS idx_candidates_run_final
  ON proof.retrieval_candidates(run_id, final_score DESC);

CREATE INDEX IF NOT EXISTS idx_candidates_evidence
  ON proof.retrieval_candidates(evidence_id, run_id);

CREATE INDEX IF NOT EXISTS idx_agent_runs_started
  ON proof.agent_runs(started_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_retrievals_run
  ON proof.agent_retrievals(run_id);

CREATE INDEX IF NOT EXISTS idx_citations_evidence
  ON proof.answer_citations(evidence_id, run_id);

CREATE INDEX IF NOT EXISTS idx_traversal_results_query
  ON proof.traversal_results(query_id, run_id, depth);

CREATE INDEX IF NOT EXISTS idx_transport_invocations_run
  ON proof.transport_invocations(run_id, invoked_at DESC);
