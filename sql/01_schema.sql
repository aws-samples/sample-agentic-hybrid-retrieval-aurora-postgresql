CREATE TABLE IF NOT EXISTS ops.source_connectors (
  source_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_system text NOT NULL,
  source_name text NOT NULL,
  auth_mode text NOT NULL DEFAULT 'api',
  status text NOT NULL DEFAULT 'configured',
  last_sync_at timestamptz,
  sync_cursor jsonb NOT NULL DEFAULT '{}'::jsonb,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(source_system, source_name)
);

CREATE TABLE IF NOT EXISTS ops.ingest_jobs (
  job_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id uuid REFERENCES ops.source_connectors(source_id) ON DELETE SET NULL,
  job_type text NOT NULL DEFAULT 'source_object_ingest',
  status text NOT NULL DEFAULT 'created',
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  object_count int NOT NULL DEFAULT 0,
  chunk_count int NOT NULL DEFAULT 0,
  embedding_count int NOT NULL DEFAULT 0,
  link_count int NOT NULL DEFAULT 0,
  citation_count int NOT NULL DEFAULT 0,
  error_count int NOT NULL DEFAULT 0,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS ops.ingest_job_events (
  event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES ops.ingest_jobs(job_id) ON DELETE CASCADE,
  step_name text NOT NULL,
  status text NOT NULL,
  message text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.source_objects (
  object_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id uuid REFERENCES ops.source_connectors(source_id) ON DELETE SET NULL,
  source_system text NOT NULL,
  source_type text NOT NULL,
  external_id text NOT NULL,
  title text NOT NULL,
  url text,
  status text,
  priority text,
  owner text,
  owner_team text,
  account_name text,
  project_key text,
  component text,
  environment text,
  created_at timestamptz,
  updated_at timestamptz,
  source_authority numeric NOT NULL DEFAULT 0.70,
  acl jsonb NOT NULL DEFAULT '{}'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  body_hash text,
  title_tsv tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(title,'')), 'A')
  ) STORED,
  UNIQUE(source_system, external_id)
);

CREATE TABLE IF NOT EXISTS ops.object_chunks (
  chunk_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  object_id uuid NOT NULL REFERENCES ops.source_objects(object_id) ON DELETE CASCADE,
  chunk_index int NOT NULL,
  section_title text,
  chunk_text text NOT NULL,
  chunk_summary text,
  embedding vector(1024),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  tsv tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(section_title,'')), 'A') ||
    setweight(to_tsvector('english', coalesce(chunk_summary,'')), 'B') ||
    setweight(to_tsvector('english', coalesce(chunk_text,'')), 'C')
  ) STORED,
  UNIQUE(object_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS ops.object_links (
  link_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  from_object_id uuid NOT NULL REFERENCES ops.source_objects(object_id) ON DELETE CASCADE,
  to_object_id uuid NOT NULL REFERENCES ops.source_objects(object_id) ON DELETE CASCADE,
  link_type text NOT NULL,
  confidence numeric NOT NULL DEFAULT 1.0,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(from_object_id, to_object_id, link_type)
);

CREATE TABLE IF NOT EXISTS ops.citations (
  citation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  chunk_id uuid NOT NULL REFERENCES ops.object_chunks(chunk_id) ON DELETE CASCADE,
  object_id uuid NOT NULL REFERENCES ops.source_objects(object_id) ON DELETE CASCADE,
  source_label text NOT NULL,
  source_url text,
  locator text,
  quote_text text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS ops.entities (
  entity_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_name text NOT NULL,
  entity_type text NOT NULL,
  aliases text[] NOT NULL DEFAULT '{}',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(entity_name, entity_type)
);

CREATE TABLE IF NOT EXISTS ops.object_entities (
  object_id uuid NOT NULL REFERENCES ops.source_objects(object_id) ON DELETE CASCADE,
  entity_id uuid NOT NULL REFERENCES ops.entities(entity_id) ON DELETE CASCADE,
  mention_count int NOT NULL DEFAULT 1,
  confidence numeric NOT NULL DEFAULT 0.75,
  PRIMARY KEY(object_id, entity_id)
);

CREATE TABLE IF NOT EXISTS ops.retrieval_runs (
  run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  query_text text NOT NULL,
  filters jsonb NOT NULL DEFAULT '{}'::jsonb,
  query_embedding vector(1024),
  created_at timestamptz NOT NULL DEFAULT now(),
  principal jsonb NOT NULL DEFAULT '{}'::jsonb,
  retrieval_mode text NOT NULL DEFAULT 'hybrid'
);

CREATE TABLE IF NOT EXISTS ops.retrieval_candidates (
  run_id uuid NOT NULL REFERENCES ops.retrieval_runs(run_id) ON DELETE CASCADE,
  chunk_id uuid NOT NULL REFERENCES ops.object_chunks(chunk_id) ON DELETE CASCADE,
  object_id uuid NOT NULL REFERENCES ops.source_objects(object_id) ON DELETE CASCADE,
  text_rank numeric,
  vector_score numeric,
  trigram_score numeric,
  metadata_score numeric,
  recency_score numeric,
  authority_score numeric,
  rrf_score numeric,
  rerank_score numeric,
  final_score numeric,
  explanation jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY(run_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS ops.evaluation_queries (
  query_id text PRIMARY KEY,
  query_text text NOT NULL,
  filters jsonb NOT NULL DEFAULT '{}'::jsonb,
  notes text
);

CREATE TABLE IF NOT EXISTS ops.relevance_judgments (
  query_id text NOT NULL REFERENCES ops.evaluation_queries(query_id) ON DELETE CASCADE,
  object_external_id text NOT NULL,
  relevance int NOT NULL CHECK (relevance BETWEEN 0 AND 3),
  rationale text,
  PRIMARY KEY(query_id, object_external_id)
);
