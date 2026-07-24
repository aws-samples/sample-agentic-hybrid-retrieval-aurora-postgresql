CREATE INDEX IF NOT EXISTS idx_incidents_cluster_started
  ON casework.incidents(cluster_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_changes_cluster_started
  ON casework.changes(cluster_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_support_cases_account_opened
  ON casework.support_cases(account_name, opened_at DESC);

CREATE INDEX IF NOT EXISTS idx_lock_evidence_incident_captured
  ON casework.lock_evidence(incident_evidence_id, captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_projection_outbox_pending
  ON retrieval.projection_outbox(status, requested_at)
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

CREATE INDEX IF NOT EXISTS idx_documents_search_tsv
  ON retrieval.documents USING GIN(search_tsv)
  WHERE is_current AND index_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_documents_title_trgm
  ON retrieval.documents USING GIN(title gin_trgm_ops)
  WHERE is_current AND index_state = 'ready';

CREATE INDEX IF NOT EXISTS idx_chunks_document
  ON retrieval.chunks(document_version_id, chunk_ordinal);

CREATE INDEX IF NOT EXISTS idx_chunks_search_tsv
  ON retrieval.chunks USING GIN(search_tsv);

CREATE INDEX IF NOT EXISTS idx_chunks_text_trgm
  ON retrieval.chunks USING GIN(chunk_text gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
  ON retrieval.chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64)
  WHERE embedding_state = 'ready' AND embedding IS NOT NULL;

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

CREATE INDEX IF NOT EXISTS idx_citations_evidence
  ON proof.answer_citations(evidence_id, run_id);
