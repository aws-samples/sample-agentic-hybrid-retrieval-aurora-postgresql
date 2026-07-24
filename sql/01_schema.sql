CREATE TABLE IF NOT EXISTS casework.database_clusters (
  cluster_id text PRIMARY KEY,
  engine text NOT NULL CHECK (engine = 'aurora-postgresql'),
  engine_version text NOT NULL,
  aws_region text NOT NULL,
  environment text NOT NULL CHECK (environment IN ('production', 'staging', 'development')),
  service_name text NOT NULL,
  writer_endpoint_alias text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS casework.evidence_items (
  evidence_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evidence_kind text NOT NULL CHECK (
    evidence_kind IN ('incident', 'change', 'support_case', 'runbook', 'lock_evidence')
  ),
  external_key text NOT NULL,
  title text NOT NULL,
  source_system text NOT NULL,
  source_uri text NOT NULL,
  source_revision text NOT NULL,
  source_updated_at timestamptz NOT NULL,
  acl jsonb NOT NULL DEFAULT '{"visibility":"workshop"}'::jsonb,
  is_deleted boolean NOT NULL DEFAULT false,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (evidence_kind, external_key),
  CHECK ((NOT is_deleted AND deleted_at IS NULL) OR is_deleted)
);

CREATE TABLE IF NOT EXISTS casework.incidents (
  evidence_id uuid PRIMARY KEY REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  incident_id text NOT NULL UNIQUE,
  cluster_id text NOT NULL REFERENCES casework.database_clusters(cluster_id) ON DELETE RESTRICT,
  severity text NOT NULL CHECK (severity IN ('SEV-1', 'SEV-2', 'SEV-3')),
  status text NOT NULL CHECK (status IN ('open', 'mitigated', 'resolved')),
  started_at timestamptz NOT NULL,
  mitigated_at timestamptz,
  resolved_at timestamptz,
  summary text NOT NULL,
  customer_impact text NOT NULL,
  resolution text,
  CHECK (mitigated_at IS NULL OR mitigated_at >= started_at),
  CHECK (resolved_at IS NULL OR resolved_at >= started_at)
);

CREATE TABLE IF NOT EXISTS casework.changes (
  evidence_id uuid PRIMARY KEY REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  change_id text NOT NULL UNIQUE,
  cluster_id text NOT NULL REFERENCES casework.database_clusters(cluster_id) ON DELETE RESTRICT,
  change_type text NOT NULL CHECK (change_type IN ('ddl', 'configuration', 'application_release')),
  status text NOT NULL CHECK (status IN ('scheduled', 'running', 'completed', 'cancelled', 'rolled_back')),
  started_at timestamptz NOT NULL,
  completed_at timestamptz,
  owner_team text NOT NULL,
  execution_sql text,
  description text NOT NULL,
  rollback_plan text NOT NULL,
  CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE TABLE IF NOT EXISTS casework.support_cases (
  evidence_id uuid PRIMARY KEY REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  case_id text NOT NULL UNIQUE,
  account_name text NOT NULL,
  support_tier text NOT NULL CHECK (support_tier IN ('Enterprise', 'Business', 'Developer')),
  severity text NOT NULL CHECK (severity IN ('urgent', 'high', 'normal')),
  status text NOT NULL CHECK (status IN ('open', 'pending_customer', 'resolved')),
  opened_at timestamptz NOT NULL,
  sla_due_at timestamptz,
  subject text NOT NULL,
  description text NOT NULL,
  customer_commitment text,
  CHECK (sla_due_at IS NULL OR sla_due_at >= opened_at)
);

CREATE TABLE IF NOT EXISTS casework.runbooks (
  evidence_id uuid PRIMARY KEY REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  runbook_id text NOT NULL UNIQUE,
  version integer NOT NULL CHECK (version > 0),
  status text NOT NULL CHECK (status IN ('current', 'superseded', 'draft')),
  owner_team text NOT NULL,
  applies_to_engine text NOT NULL,
  applies_to_major_versions int4range NOT NULL,
  procedure_text text NOT NULL,
  caveats text NOT NULL,
  UNIQUE (runbook_id, version)
);

CREATE TABLE IF NOT EXISTS casework.lock_evidence (
  evidence_id uuid PRIMARY KEY REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  observation_id text NOT NULL UNIQUE,
  incident_evidence_id uuid NOT NULL REFERENCES casework.incidents(evidence_id) ON DELETE RESTRICT,
  captured_at timestamptz NOT NULL,
  relation_name text NOT NULL,
  blocked_pid integer NOT NULL,
  blocking_pid integer NOT NULL,
  wait_event_type text NOT NULL,
  wait_event text NOT NULL,
  blocked_statement text NOT NULL,
  blocking_statement text NOT NULL,
  database_insights_slice jsonb NOT NULL,
  CHECK (blocked_pid <> blocking_pid)
);

CREATE TABLE IF NOT EXISTS casework.incident_changes (
  incident_evidence_id uuid NOT NULL REFERENCES casework.incidents(evidence_id) ON DELETE RESTRICT,
  change_evidence_id uuid NOT NULL REFERENCES casework.changes(evidence_id) ON DELETE RESTRICT,
  relationship text NOT NULL CHECK (relationship IN ('suspected', 'confirmed', 'ruled_out')),
  rationale text NOT NULL,
  confirmed_by text,
  PRIMARY KEY (incident_evidence_id, change_evidence_id)
);

CREATE TABLE IF NOT EXISTS casework.incident_support_cases (
  incident_evidence_id uuid NOT NULL REFERENCES casework.incidents(evidence_id) ON DELETE RESTRICT,
  case_evidence_id uuid NOT NULL REFERENCES casework.support_cases(evidence_id) ON DELETE RESTRICT,
  impact text NOT NULL CHECK (impact IN ('affected', 'potentially_affected', 'not_affected')),
  rationale text NOT NULL,
  PRIMARY KEY (incident_evidence_id, case_evidence_id)
);

CREATE TABLE IF NOT EXISTS casework.incident_runbooks (
  incident_evidence_id uuid NOT NULL REFERENCES casework.incidents(evidence_id) ON DELETE RESTRICT,
  runbook_evidence_id uuid NOT NULL REFERENCES casework.runbooks(evidence_id) ON DELETE RESTRICT,
  applicability text NOT NULL CHECK (applicability IN ('used', 'recommended', 'rejected')),
  rationale text NOT NULL,
  PRIMARY KEY (incident_evidence_id, runbook_evidence_id)
);

CREATE OR REPLACE FUNCTION casework.sha256_text(value text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT encode(sha256(convert_to(coalesce(value, ''), 'UTF8')), 'hex')
$$;

CREATE OR REPLACE VIEW casework.v_evidence_documents AS
WITH rendered AS (
  SELECT
    e.evidence_id,
    e.evidence_kind,
    e.external_key,
    e.title,
    e.source_system,
    e.source_uri,
    e.source_revision,
    e.source_updated_at,
    e.acl,
    i.cluster_id,
    i.incident_id,
    NULL::text AS account_name,
    i.severity,
    c.environment,
    i.started_at AS occurred_at,
    concat_ws(
      E'\n\n',
      i.summary,
      'Customer impact: ' || i.customer_impact,
      CASE WHEN i.resolution IS NOT NULL THEN 'Resolution: ' || i.resolution END
    ) AS body,
    jsonb_build_object(
      'status', i.status,
      'started_at', i.started_at,
      'mitigated_at', i.mitigated_at,
      'resolved_at', i.resolved_at,
      'service_name', c.service_name,
      'engine_version', c.engine_version
    ) AS metadata
  FROM casework.evidence_items e
  JOIN casework.incidents i ON i.evidence_id = e.evidence_id
  JOIN casework.database_clusters c ON c.cluster_id = i.cluster_id
  WHERE NOT e.is_deleted

  UNION ALL

  SELECT
    e.evidence_id,
    e.evidence_kind,
    e.external_key,
    e.title,
    e.source_system,
    e.source_uri,
    e.source_revision,
    e.source_updated_at,
    e.acl,
    ch.cluster_id,
    NULL::text AS incident_id,
    NULL::text AS account_name,
    NULL::text AS severity,
    c.environment,
    ch.started_at AS occurred_at,
    concat_ws(
      E'\n\n',
      ch.description,
      CASE WHEN ch.execution_sql IS NOT NULL THEN 'Executed SQL:' || E'\n' || ch.execution_sql END,
      'Rollback plan: ' || ch.rollback_plan
    ) AS body,
    jsonb_build_object(
      'status', ch.status,
      'change_type', ch.change_type,
      'owner_team', ch.owner_team,
      'completed_at', ch.completed_at,
      'service_name', c.service_name,
      'engine_version', c.engine_version
    ) AS metadata
  FROM casework.evidence_items e
  JOIN casework.changes ch ON ch.evidence_id = e.evidence_id
  JOIN casework.database_clusters c ON c.cluster_id = ch.cluster_id
  WHERE NOT e.is_deleted

  UNION ALL

  SELECT
    e.evidence_id,
    e.evidence_kind,
    e.external_key,
    e.title,
    e.source_system,
    e.source_uri,
    e.source_revision,
    e.source_updated_at,
    e.acl,
    NULL::text AS cluster_id,
    NULL::text AS incident_id,
    sc.account_name,
    sc.severity,
    NULL::text AS environment,
    sc.opened_at AS occurred_at,
    concat_ws(
      E'\n\n',
      sc.subject,
      sc.description,
      CASE
        WHEN sc.customer_commitment IS NOT NULL
        THEN 'Customer commitment: ' || sc.customer_commitment
      END
    ) AS body,
    jsonb_build_object(
      'status', sc.status,
      'support_tier', sc.support_tier,
      'sla_due_at', sc.sla_due_at
    ) AS metadata
  FROM casework.evidence_items e
  JOIN casework.support_cases sc ON sc.evidence_id = e.evidence_id
  WHERE NOT e.is_deleted

  UNION ALL

  SELECT
    e.evidence_id,
    e.evidence_kind,
    e.external_key,
    e.title,
    e.source_system,
    e.source_uri,
    e.source_revision,
    e.source_updated_at,
    e.acl,
    NULL::text AS cluster_id,
    NULL::text AS incident_id,
    NULL::text AS account_name,
    NULL::text AS severity,
    NULL::text AS environment,
    e.source_updated_at AS occurred_at,
    concat_ws(
      E'\n\n',
      r.procedure_text,
      'Caveats: ' || r.caveats
    ) AS body,
    jsonb_build_object(
      'version', r.version,
      'status', r.status,
      'owner_team', r.owner_team,
      'applies_to_engine', r.applies_to_engine,
      'applies_to_major_versions', r.applies_to_major_versions::text
    ) AS metadata
  FROM casework.evidence_items e
  JOIN casework.runbooks r ON r.evidence_id = e.evidence_id
  WHERE NOT e.is_deleted

  UNION ALL

  SELECT
    e.evidence_id,
    e.evidence_kind,
    e.external_key,
    e.title,
    e.source_system,
    e.source_uri,
    e.source_revision,
    e.source_updated_at,
    e.acl,
    i.cluster_id,
    i.incident_id,
    NULL::text AS account_name,
    i.severity,
    c.environment,
    le.captured_at AS occurred_at,
    concat_ws(
      E'\n\n',
      format(
        'Blocked PID %s waited on %s:%s for relation %s while PID %s held the conflicting lock.',
        le.blocked_pid,
        le.wait_event_type,
        le.wait_event,
        le.relation_name,
        le.blocking_pid
      ),
      'Blocked statement:' || E'\n' || le.blocked_statement,
      'Blocking statement:' || E'\n' || le.blocking_statement,
      'Database Insights slice: ' || le.database_insights_slice::text
    ) AS body,
    jsonb_build_object(
      'observation_id', le.observation_id,
      'captured_at', le.captured_at,
      'relation_name', le.relation_name,
      'blocked_pid', le.blocked_pid,
      'blocking_pid', le.blocking_pid,
      'wait_event_type', le.wait_event_type,
      'wait_event', le.wait_event,
      'service_name', c.service_name,
      'engine_version', c.engine_version
    ) AS metadata
  FROM casework.evidence_items e
  JOIN casework.lock_evidence le ON le.evidence_id = e.evidence_id
  JOIN casework.incidents i ON i.evidence_id = le.incident_evidence_id
  JOIN casework.database_clusters c ON c.cluster_id = i.cluster_id
  WHERE NOT e.is_deleted
)
SELECT
  rendered.*,
  casework.sha256_text(
    concat_ws(
      E'\n',
      source_revision,
      evidence_kind,
      external_key,
      title,
      body,
      acl::text,
      metadata::text
    )
  ) AS projection_hash
FROM rendered;

CREATE TABLE IF NOT EXISTS retrieval.projection_outbox (
  outbox_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  evidence_id uuid NOT NULL REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  source_revision text NOT NULL,
  requested_at timestamptz NOT NULL DEFAULT now(),
  claimed_at timestamptz,
  completed_at timestamptz,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'claimed', 'complete', 'failed')),
  error text,
  UNIQUE (evidence_id, source_revision)
);

CREATE TABLE IF NOT EXISTS retrieval.projection_builds (
  build_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  projection_version text NOT NULL,
  embedding_model text NOT NULL,
  embedding_dimensions integer NOT NULL CHECK (embedding_dimensions > 0),
  renderer_version text NOT NULL,
  chunker_version text NOT NULL,
  status text NOT NULL CHECK (status IN ('running', 'complete', 'failed')),
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  document_count integer NOT NULL DEFAULT 0,
  chunk_count integer NOT NULL DEFAULT 0,
  cache_hit_count integer NOT NULL DEFAULT 0,
  embedded_count integer NOT NULL DEFAULT 0,
  error text
);

CREATE TABLE IF NOT EXISTS retrieval.documents (
  document_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evidence_id uuid NOT NULL REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  build_id uuid NOT NULL REFERENCES retrieval.projection_builds(build_id) ON DELETE RESTRICT,
  projection_version text NOT NULL,
  projection_hash text NOT NULL,
  source_revision text NOT NULL,
  evidence_kind text NOT NULL,
  external_key text NOT NULL,
  title text NOT NULL,
  source_system text NOT NULL,
  source_uri text NOT NULL,
  source_updated_at timestamptz NOT NULL,
  acl jsonb NOT NULL,
  cluster_id text,
  incident_id text,
  account_name text,
  severity text,
  environment text,
  occurred_at timestamptz NOT NULL,
  metadata jsonb NOT NULL,
  index_state text NOT NULL CHECK (index_state IN ('building', 'ready', 'failed', 'superseded')),
  is_current boolean NOT NULL DEFAULT false,
  indexed_at timestamptz,
  superseded_at timestamptz,
  search_tsv tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(external_key, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(title, '')), 'A')
  ) STORED,
  UNIQUE (evidence_id, projection_version, projection_hash),
  CHECK (NOT is_current OR index_state = 'ready')
);

CREATE TABLE IF NOT EXISTS retrieval.chunks (
  chunk_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_version_id uuid NOT NULL REFERENCES retrieval.documents(document_version_id) ON DELETE RESTRICT,
  chunk_ordinal integer NOT NULL CHECK (chunk_ordinal > 0),
  section_title text,
  chunk_text text NOT NULL,
  chunk_hash text NOT NULL,
  embedding vector(1024),
  embedding_model text,
  embedding_input_type text,
  embedding_state text NOT NULL CHECK (embedding_state IN ('pending', 'ready', 'failed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  search_tsv tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(section_title, '')), 'B') ||
    setweight(to_tsvector('english', chunk_text), 'C')
  ) STORED,
  UNIQUE (document_version_id, chunk_ordinal),
  CHECK (
    (embedding_state = 'ready' AND embedding IS NOT NULL AND embedding_model IS NOT NULL)
    OR embedding_state <> 'ready'
  )
);

CREATE TABLE IF NOT EXISTS retrieval.inferred_edges (
  edge_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  from_evidence_id uuid NOT NULL REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  to_evidence_id uuid NOT NULL REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  relation text NOT NULL,
  confidence numeric NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  method text NOT NULL,
  source_revision text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (from_evidence_id <> to_evidence_id),
  UNIQUE (from_evidence_id, to_evidence_id, relation, source_revision)
);

CREATE OR REPLACE VIEW retrieval.evidence_edges AS
SELECT
  'incident-change:' || ic.incident_evidence_id || ':' || ic.change_evidence_id AS edge_key,
  ic.incident_evidence_id AS from_evidence_id,
  ic.change_evidence_id AS to_evidence_id,
  'change_' || ic.relationship AS relation,
  'canonical_relation'::text AS origin,
  1.0::numeric AS confidence,
  jsonb_build_object('rationale', ic.rationale, 'confirmed_by', ic.confirmed_by) AS metadata
FROM casework.incident_changes ic

UNION ALL

SELECT
  'incident-case:' || isc.incident_evidence_id || ':' || isc.case_evidence_id,
  isc.incident_evidence_id,
  isc.case_evidence_id,
  'support_case_' || isc.impact,
  'canonical_relation'::text,
  1.0::numeric,
  jsonb_build_object('rationale', isc.rationale)
FROM casework.incident_support_cases isc

UNION ALL

SELECT
  'incident-runbook:' || ir.incident_evidence_id || ':' || ir.runbook_evidence_id,
  ir.incident_evidence_id,
  ir.runbook_evidence_id,
  'runbook_' || ir.applicability,
  'canonical_relation'::text,
  1.0::numeric,
  jsonb_build_object('rationale', ir.rationale)
FROM casework.incident_runbooks ir

UNION ALL

SELECT
  'lock-evidence:' || le.evidence_id || ':' || le.incident_evidence_id,
  le.evidence_id,
  le.incident_evidence_id,
  'observed_during',
  'canonical_relation'::text,
  1.0::numeric,
  jsonb_build_object('captured_at', le.captured_at, 'observation_id', le.observation_id)
FROM casework.lock_evidence le

UNION ALL

SELECT
  'inferred:' || ie.edge_id,
  ie.from_evidence_id,
  ie.to_evidence_id,
  ie.relation,
  'inferred'::text,
  ie.confidence,
  ie.metadata || jsonb_build_object('method', ie.method, 'source_revision', ie.source_revision)
FROM retrieval.inferred_edges ie;

CREATE OR REPLACE FUNCTION casework.queue_evidence(p_evidence_id uuid)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
  v_revision text;
  v_outbox_id bigint;
BEGIN
  SELECT source_revision
  INTO STRICT v_revision
  FROM casework.evidence_items
  WHERE evidence_id = p_evidence_id;

  INSERT INTO retrieval.projection_outbox(evidence_id, source_revision)
  VALUES (p_evidence_id, v_revision)
  ON CONFLICT (evidence_id, source_revision)
  DO UPDATE SET
    requested_at = now(),
    claimed_at = NULL,
    completed_at = NULL,
    status = 'pending',
    error = NULL
  RETURNING outbox_id INTO v_outbox_id;

  RETURN v_outbox_id;
END
$$;

CREATE TABLE IF NOT EXISTS proof.retrieval_runs (
  run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  query_text text NOT NULL,
  query_embedding vector(1024),
  embedding_model text,
  retrieval_mode text NOT NULL CHECK (retrieval_mode IN ('hybrid', 'lexical', 'semantic', 'fuzzy')),
  filters jsonb NOT NULL DEFAULT '{}'::jsonb,
  principal jsonb NOT NULL DEFAULT '{}'::jsonb,
  rrf_k integer NOT NULL CHECK (rrf_k > 0),
  text_weight numeric NOT NULL CHECK (text_weight >= 0),
  vector_weight numeric NOT NULL CHECK (vector_weight >= 0),
  fuzzy_weight numeric NOT NULL CHECK (fuzzy_weight >= 0),
  hnsw_ef_search integer,
  hnsw_iterative_scan text,
  rerank_model text,
  rerank_applied boolean NOT NULL DEFAULT false,
  status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'complete', 'failed')),
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  latency_ms integer,
  error text
);

CREATE TABLE IF NOT EXISTS proof.retrieval_candidates (
  run_id uuid NOT NULL REFERENCES proof.retrieval_runs(run_id) ON DELETE RESTRICT,
  evidence_id uuid NOT NULL REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  document_version_id uuid NOT NULL REFERENCES retrieval.documents(document_version_id) ON DELETE RESTRICT,
  chunk_version_id uuid NOT NULL REFERENCES retrieval.chunks(chunk_version_id) ON DELETE RESTRICT,
  result_rank integer NOT NULL CHECK (result_rank > 0),
  text_rank numeric,
  vector_score numeric,
  trigram_score numeric,
  text_position integer,
  vector_position integer,
  trigram_position integer,
  rrf_score numeric NOT NULL,
  rerank_score numeric,
  final_score numeric NOT NULL,
  explanation jsonb NOT NULL,
  evidence_snapshot jsonb NOT NULL,
  PRIMARY KEY (run_id, evidence_id),
  UNIQUE (run_id, result_rank)
);

CREATE TABLE IF NOT EXISTS proof.run_stages (
  run_id uuid NOT NULL REFERENCES proof.retrieval_runs(run_id) ON DELETE RESTRICT,
  stage_ordinal integer NOT NULL CHECK (stage_ordinal > 0),
  stage_name text NOT NULL,
  duration_ms integer NOT NULL CHECK (duration_ms >= 0),
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (run_id, stage_ordinal)
);

CREATE TABLE IF NOT EXISTS proof.agent_answers (
  run_id uuid PRIMARY KEY REFERENCES proof.retrieval_runs(run_id) ON DELETE RESTRICT,
  question text NOT NULL,
  answer_text text NOT NULL,
  synthesis_mode text NOT NULL CHECK (synthesis_mode IN ('bedrock', 'extractive_fallback', 'checkpoint')),
  model_id text,
  model_transport text,
  input_tokens integer,
  output_tokens integer,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS proof.answer_citations (
  run_id uuid NOT NULL REFERENCES proof.agent_answers(run_id) ON DELETE RESTRICT,
  citation_number integer NOT NULL CHECK (citation_number > 0),
  evidence_id uuid NOT NULL REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  document_version_id uuid NOT NULL REFERENCES retrieval.documents(document_version_id) ON DELETE RESTRICT,
  chunk_version_id uuid NOT NULL REFERENCES retrieval.chunks(chunk_version_id) ON DELETE RESTRICT,
  source_uri text NOT NULL,
  source_revision text NOT NULL,
  quote_text text NOT NULL,
  claim text,
  PRIMARY KEY (run_id, citation_number),
  UNIQUE (run_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS proof.evaluation_queries (
  query_id text PRIMARY KEY,
  query_text text NOT NULL,
  filters jsonb NOT NULL DEFAULT '{}'::jsonb,
  notes text
);

CREATE TABLE IF NOT EXISTS proof.relevance_judgments (
  query_id text NOT NULL REFERENCES proof.evaluation_queries(query_id) ON DELETE RESTRICT,
  evidence_id uuid NOT NULL REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  relevance integer NOT NULL CHECK (relevance BETWEEN 0 AND 3),
  rationale text NOT NULL,
  PRIMARY KEY (query_id, evidence_id)
);
