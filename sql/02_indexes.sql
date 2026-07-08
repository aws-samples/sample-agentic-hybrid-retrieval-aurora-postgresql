CREATE INDEX IF NOT EXISTS idx_source_connectors_system ON ops.source_connectors(source_system, status);
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_status ON ops.ingest_jobs(status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingest_events_job ON ops.ingest_job_events(job_id, created_at);

CREATE INDEX IF NOT EXISTS idx_objects_source_type ON ops.source_objects(source_system, source_type);
CREATE INDEX IF NOT EXISTS idx_objects_status_priority ON ops.source_objects(status, priority);
CREATE INDEX IF NOT EXISTS idx_objects_project_component ON ops.source_objects(project_key, component);
CREATE INDEX IF NOT EXISTS idx_objects_account ON ops.source_objects(account_name);
CREATE INDEX IF NOT EXISTS idx_objects_updated_at ON ops.source_objects(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_objects_metadata_gin ON ops.source_objects USING GIN(metadata);
CREATE INDEX IF NOT EXISTS idx_objects_acl_gin ON ops.source_objects USING GIN(acl);
CREATE INDEX IF NOT EXISTS idx_objects_title_tsv ON ops.source_objects USING GIN(title_tsv);
CREATE INDEX IF NOT EXISTS idx_objects_title_trgm ON ops.source_objects USING GIN(title gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_chunks_object ON ops.object_chunks(object_id);
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON ops.object_chunks USING GIN(tsv);
CREATE INDEX IF NOT EXISTS idx_chunks_text_trgm ON ops.object_chunks USING GIN(chunk_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_chunks_metadata_gin ON ops.object_chunks USING GIN(metadata);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw ON ops.object_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64) WHERE embedding IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_links_from ON ops.object_links(from_object_id, link_type);
CREATE INDEX IF NOT EXISTS idx_links_to ON ops.object_links(to_object_id, link_type);
CREATE INDEX IF NOT EXISTS idx_citations_chunk ON ops.citations(chunk_id);
CREATE INDEX IF NOT EXISTS idx_candidates_run_final ON ops.retrieval_candidates(run_id, final_score DESC);
