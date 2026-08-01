CREATE TABLE IF NOT EXISTS casework.database_clusters (
  cluster_id text PRIMARY KEY,
  engine text NOT NULL CHECK (engine = 'aurora-postgresql'),
  engine_version text NOT NULL,
  aws_region text NOT NULL,
  environment text NOT NULL CHECK (environment IN ('production', 'staging', 'development')),
  service_name text NOT NULL,
  writer_endpoint_alias text NOT NULL,
  instance_class text NOT NULL DEFAULT 'db.r8g.xlarge',
  database_insights_mode text NOT NULL DEFAULT 'advanced'
    CHECK (database_insights_mode IN ('standard', 'advanced')),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE casework.database_clusters
  ADD COLUMN IF NOT EXISTS instance_class text NOT NULL DEFAULT 'db.r8g.xlarge';

ALTER TABLE casework.database_clusters
  ADD COLUMN IF NOT EXISTS database_insights_mode text NOT NULL DEFAULT 'advanced';

CREATE TABLE IF NOT EXISTS casework.evidence_items (
  evidence_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evidence_kind text NOT NULL CHECK (
    evidence_kind IN (
      'incident',
      'change',
      'support_case',
      'runbook',
      'lock_evidence',
      'commitment',
      'postmortem'
    )
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

ALTER TABLE casework.evidence_items
  DROP CONSTRAINT IF EXISTS evidence_items_evidence_kind_check;

ALTER TABLE casework.evidence_items
  ADD CONSTRAINT evidence_items_evidence_kind_check
  CHECK (
    evidence_kind IN (
      'incident',
      'change',
      'support_case',
      'runbook',
      'lock_evidence',
      'commitment',
      'postmortem'
    )
  );

-- Older corpora encoded restrictedness as a named entry in acl.principals while
-- leaving visibility='workshop'. The current contract has one classification
-- axis, so normalize that retired stamp before any retrieval projection is read.
UPDATE casework.evidence_items
SET acl = jsonb_set(
  jsonb_set(acl, '{visibility}', '"restricted"'::jsonb, true),
  '{principals}',
  '[]'::jsonb,
  true
)
WHERE coalesce(acl ->> 'visibility', 'restricted') = 'workshop'
  AND acl -> 'principals' ? 'support-lead';

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

CREATE TABLE IF NOT EXISTS casework.fixture_captures (
  capture_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  capture_key text NOT NULL UNIQUE,
  incident_evidence_id uuid NOT NULL
    REFERENCES casework.incidents(evidence_id) ON DELETE RESTRICT,
  cluster_id text NOT NULL
    REFERENCES casework.database_clusters(cluster_id) ON DELETE RESTRICT,
  capture_mode text NOT NULL
    CHECK (capture_mode IN ('offline_test', 'release_aurora')),
  engine_version text NOT NULL,
  instance_class text NOT NULL,
  database_name text NOT NULL,
  table_schema text NOT NULL,
  table_name text NOT NULL,
  relation_oid oid,
  configured_row_count bigint NOT NULL CHECK (configured_row_count > 0),
  observed_row_count bigint CHECK (observed_row_count > 0),
  table_size_bytes bigint CHECK (table_size_bytes > 0),
  steady_state_connections integer NOT NULL CHECK (steady_state_connections > 0),
  capture_started_at timestamptz NOT NULL,
  capture_ended_at timestamptz,
  capture_tool_version text NOT NULL,
  source_bundle_sha256 text,
  source_bundle_uri text,
  release_verified_at timestamptz,
  manifest jsonb NOT NULL DEFAULT '{}'::jsonb,
  CHECK (capture_ended_at IS NULL OR capture_ended_at >= capture_started_at),
  CHECK (
    capture_mode <> 'release_aurora'
    OR (
      relation_oid IS NOT NULL
      AND observed_row_count IS NOT NULL
      AND table_size_bytes IS NOT NULL
      AND source_bundle_sha256 IS NOT NULL
      AND release_verified_at IS NOT NULL
    )
  )
);

CREATE TABLE IF NOT EXISTS casework.lock_evidence (
  evidence_id uuid PRIMARY KEY REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  observation_id text NOT NULL UNIQUE,
  incident_evidence_id uuid NOT NULL REFERENCES casework.incidents(evidence_id) ON DELETE RESTRICT,
  change_evidence_id uuid REFERENCES casework.changes(evidence_id) ON DELETE RESTRICT,
  capture_id uuid REFERENCES casework.fixture_captures(capture_id) ON DELETE RESTRICT,
  captured_at timestamptz NOT NULL,
  relation_name text NOT NULL,
  relation_oid oid,
  blocked_pid integer NOT NULL,
  blocking_pid integer NOT NULL,
  blocked_state text,
  blocked_query_start timestamptz,
  wait_event_type text NOT NULL,
  wait_event text NOT NULL,
  blocked_lock_mode text,
  blocked_lock_granted boolean,
  blocking_lock_mode text,
  blocking_lock_granted boolean,
  blocking_pids integer[],
  blocking_pids_sql text,
  blocking_pids_output text,
  blocked_statement text NOT NULL,
  blocking_statement text NOT NULL,
  database_insights_slice jsonb,
  raw_capture jsonb NOT NULL DEFAULT '{}'::jsonb,
  CHECK (blocked_pid <> blocking_pid),
  CHECK (wait_event_type = 'Lock'),
  CHECK (wait_event = 'relation')
);

ALTER TABLE casework.lock_evidence
  ADD COLUMN IF NOT EXISTS change_evidence_id uuid
    REFERENCES casework.changes(evidence_id) ON DELETE RESTRICT;

ALTER TABLE casework.lock_evidence
  ADD COLUMN IF NOT EXISTS capture_id uuid
    REFERENCES casework.fixture_captures(capture_id) ON DELETE RESTRICT;

ALTER TABLE casework.lock_evidence
  ADD COLUMN IF NOT EXISTS relation_oid oid;

ALTER TABLE casework.lock_evidence
  ADD COLUMN IF NOT EXISTS blocked_state text;

ALTER TABLE casework.lock_evidence
  ADD COLUMN IF NOT EXISTS blocked_query_start timestamptz;

ALTER TABLE casework.lock_evidence
  ADD COLUMN IF NOT EXISTS blocked_lock_mode text;

ALTER TABLE casework.lock_evidence
  ADD COLUMN IF NOT EXISTS blocked_lock_granted boolean;

ALTER TABLE casework.lock_evidence
  ADD COLUMN IF NOT EXISTS blocking_lock_mode text;

ALTER TABLE casework.lock_evidence
  ADD COLUMN IF NOT EXISTS blocking_lock_granted boolean;

ALTER TABLE casework.lock_evidence
  ADD COLUMN IF NOT EXISTS blocking_pids integer[];

ALTER TABLE casework.lock_evidence
  ADD COLUMN IF NOT EXISTS blocking_pids_sql text;

ALTER TABLE casework.lock_evidence
  ADD COLUMN IF NOT EXISTS blocking_pids_output text;

ALTER TABLE casework.lock_evidence
  ADD COLUMN IF NOT EXISTS raw_capture jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE casework.lock_evidence
  ALTER COLUMN database_insights_slice DROP NOT NULL;

CREATE TABLE IF NOT EXISTS casework.pg_stat_activity_samples (
  sample_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  capture_id uuid NOT NULL REFERENCES casework.fixture_captures(capture_id) ON DELETE RESTRICT,
  observation_evidence_id uuid
    REFERENCES casework.lock_evidence(evidence_id) ON DELETE RESTRICT,
  captured_at timestamptz NOT NULL,
  pid integer NOT NULL,
  backend_type text,
  application_name text,
  state text NOT NULL,
  wait_event_type text,
  wait_event text,
  query_start timestamptz,
  xact_start timestamptz,
  query text NOT NULL,
  raw_row jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS casework.pg_lock_samples (
  sample_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  capture_id uuid NOT NULL REFERENCES casework.fixture_captures(capture_id) ON DELETE RESTRICT,
  observation_evidence_id uuid
    REFERENCES casework.lock_evidence(evidence_id) ON DELETE RESTRICT,
  captured_at timestamptz NOT NULL,
  pid integer NOT NULL,
  locktype text NOT NULL,
  database_oid oid,
  relation_oid oid NOT NULL,
  relation_name text NOT NULL,
  mode text NOT NULL,
  granted boolean NOT NULL,
  fastpath boolean,
  waitstart timestamptz,
  raw_row jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS casework.pg_blocking_pids_samples (
  sample_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  capture_id uuid NOT NULL REFERENCES casework.fixture_captures(capture_id) ON DELETE RESTRICT,
  observation_evidence_id uuid
    REFERENCES casework.lock_evidence(evidence_id) ON DELETE RESTRICT,
  captured_at timestamptz NOT NULL,
  blocked_pid integer NOT NULL,
  blocking_pids integer[] NOT NULL,
  literal_sql text NOT NULL,
  literal_output text NOT NULL,
  raw_row jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS casework.pg_stat_statements_samples (
  sample_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  capture_id uuid NOT NULL REFERENCES casework.fixture_captures(capture_id) ON DELETE RESTRICT,
  phase text NOT NULL CHECK (phase IN ('before', 'during', 'after')),
  captured_at timestamptz NOT NULL,
  queryid bigint,
  query text NOT NULL,
  calls bigint NOT NULL CHECK (calls >= 0),
  total_exec_time double precision NOT NULL CHECK (total_exec_time >= 0),
  mean_exec_time double precision NOT NULL CHECK (mean_exec_time >= 0),
  rows bigint NOT NULL DEFAULT 0 CHECK (rows >= 0),
  raw_row jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS casework.cloudwatch_metric_samples (
  sample_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  capture_id uuid NOT NULL REFERENCES casework.fixture_captures(capture_id) ON DELETE RESTRICT,
  metric_name text NOT NULL CHECK (
    metric_name IN (
      'WriteLatency',
      'WriteIOPS',
      'WriteThroughput',
      'CommitThroughput',
      'DatabaseConnections'
    )
  ),
  namespace text NOT NULL DEFAULT 'AWS/RDS',
  dimension_name text NOT NULL,
  dimension_value text NOT NULL,
  statistic text NOT NULL,
  period_seconds integer NOT NULL CHECK (period_seconds > 0),
  observed_at timestamptz NOT NULL,
  value double precision NOT NULL,
  unit text NOT NULL,
  raw_datapoint jsonb NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE casework.cloudwatch_metric_samples
  DROP CONSTRAINT IF EXISTS cloudwatch_metric_samples_metric_name_check;

-- Earlier fixture generations used names that are not AWS/RDS metrics.
-- They cannot be truthfully remapped, so remove them before tightening the
-- release-evidence contract.
DELETE FROM casework.cloudwatch_metric_samples
WHERE metric_name IN ('DMLThroughput', 'DDLThroughput');

ALTER TABLE casework.cloudwatch_metric_samples
  ADD CONSTRAINT cloudwatch_metric_samples_metric_name_check
  CHECK (
    metric_name IN (
      'WriteLatency',
      'WriteIOPS',
      'WriteThroughput',
      'CommitThroughput',
      'DatabaseConnections'
    )
  );

CREATE TABLE IF NOT EXISTS casework.database_insights_samples (
  sample_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  capture_id uuid NOT NULL REFERENCES casework.fixture_captures(capture_id) ON DELETE RESTRICT,
  evidence_type text NOT NULL CHECK (
    evidence_type IN ('top_wait', 'top_sql', 'lock_tree')
  ),
  captured_at timestamptz NOT NULL,
  dimension text NOT NULL,
  dimension_value text NOT NULL,
  db_load double precision,
  statement text,
  query_id text,
  source_api text NOT NULL,
  raw_payload jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS casework.customer_commitments (
  evidence_id uuid PRIMARY KEY
    REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  commitment_id text NOT NULL UNIQUE,
  account_name text NOT NULL,
  priority text NOT NULL CHECK (priority IN ('P1', 'P2', 'P3')),
  commitment_text text NOT NULL,
  due_at timestamptz NOT NULL,
  status text NOT NULL CHECK (status IN ('open', 'met', 'missed')),
  revalidate_live boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS casework.postmortems (
  evidence_id uuid PRIMARY KEY
    REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  postmortem_id text NOT NULL UNIQUE,
  incident_evidence_id uuid NOT NULL
    REFERENCES casework.incidents(evidence_id) ON DELETE RESTRICT,
  published_at timestamptz NOT NULL,
  root_cause text NOT NULL,
  contributing_factors text NOT NULL,
  remediation text NOT NULL,
  prevention text NOT NULL
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

CREATE TABLE IF NOT EXISTS casework.change_runbooks (
  change_evidence_id uuid NOT NULL
    REFERENCES casework.changes(evidence_id) ON DELETE RESTRICT,
  runbook_evidence_id uuid NOT NULL
    REFERENCES casework.runbooks(evidence_id) ON DELETE RESTRICT,
  relationship text NOT NULL
    CHECK (relationship IN ('remediated_by', 'implements', 'superseded_guidance')),
  rationale text NOT NULL,
  PRIMARY KEY (change_evidence_id, runbook_evidence_id)
);

CREATE TABLE IF NOT EXISTS casework.support_case_commitments (
  case_evidence_id uuid NOT NULL
    REFERENCES casework.support_cases(evidence_id) ON DELETE RESTRICT,
  commitment_evidence_id uuid NOT NULL
    REFERENCES casework.customer_commitments(evidence_id) ON DELETE RESTRICT,
  PRIMARY KEY (case_evidence_id, commitment_evidence_id)
);

CREATE OR REPLACE FUNCTION casework.sha256_text(value text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT encode(sha256(convert_to(coalesce(value, ''), 'UTF8')), 'hex')
$$;

CREATE OR REPLACE VIEW casework.v_evidence_documents
WITH (security_invoker = true) AS
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
    c.service_name,
    c.engine_version,
    c.aws_region,
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
    related.incident_id,
    NULL::text AS account_name,
    NULL::text AS severity,
    c.environment,
    c.service_name,
    c.engine_version,
    c.aws_region,
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
  LEFT JOIN LATERAL (
    SELECT incident.incident_id
    FROM casework.incident_changes relation
    JOIN casework.incidents incident
      ON incident.evidence_id = relation.incident_evidence_id
    WHERE relation.change_evidence_id = ch.evidence_id
    ORDER BY
      CASE relation.relationship
        WHEN 'confirmed' THEN 0
        WHEN 'suspected' THEN 1
        ELSE 2
      END,
      incident.started_at DESC
    LIMIT 1
  ) related ON true
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
    related.cluster_id,
    related.incident_id,
    sc.account_name,
    sc.severity,
    related.environment,
    related.service_name,
    related.engine_version,
    related.aws_region,
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
  LEFT JOIN LATERAL (
    SELECT
      incident.cluster_id,
      incident.incident_id,
      cluster.environment,
      cluster.service_name,
      cluster.engine_version,
      cluster.aws_region
    FROM casework.incident_support_cases relation
    JOIN casework.incidents incident
      ON incident.evidence_id = relation.incident_evidence_id
    JOIN casework.database_clusters cluster
      ON cluster.cluster_id = incident.cluster_id
    WHERE relation.case_evidence_id = sc.evidence_id
    ORDER BY incident.started_at DESC
    LIMIT 1
  ) related ON true
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
    related.environment,
    related.service_name,
    related.engine_version,
    related.aws_region,
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
  LEFT JOIN LATERAL (
    SELECT
      incident.cluster_id,
      incident.incident_id,
      cluster.environment,
      cluster.service_name,
      cluster.engine_version,
      cluster.aws_region
    FROM casework.incident_runbooks relation
    JOIN casework.incidents incident
      ON incident.evidence_id = relation.incident_evidence_id
    JOIN casework.database_clusters cluster
      ON cluster.cluster_id = incident.cluster_id
    WHERE relation.runbook_evidence_id = r.evidence_id
    ORDER BY
      CASE relation.applicability
        WHEN 'used' THEN 0
        WHEN 'recommended' THEN 1
        ELSE 2
      END,
      incident.started_at DESC
    LIMIT 1
  ) related ON true
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
    c.service_name,
    c.engine_version,
    c.aws_region,
    le.captured_at AS occurred_at,
    concat_ws(
      E'\n\n',
      format(
        'Blocked PID %s was %s and waited on %s:%s for relation %s (OID %s) while PID %s ran the index build.',
        le.blocked_pid,
        coalesce(le.blocked_state, 'active'),
        le.wait_event_type,
        le.wait_event,
        le.relation_name,
        coalesce(le.relation_oid::text, 'not loaded'),
        le.blocking_pid
      ),
      format(
        'pg_locks: blocker mode=%s granted=%s; writer mode=%s granted=%s.',
        coalesce(le.blocking_lock_mode, 'not loaded'),
        coalesce(le.blocking_lock_granted::text, 'not loaded'),
        coalesce(le.blocked_lock_mode, 'not loaded'),
        coalesce(le.blocked_lock_granted::text, 'not loaded')
      ),
      CASE
        WHEN le.blocking_pids_output IS NOT NULL
        THEN coalesce(le.blocking_pids_sql, 'SELECT pg_blocking_pids(...)') ||
             E'\n' || le.blocking_pids_output
      END,
      'Blocked statement:' || E'\n' || le.blocked_statement,
      'Blocking statement:' || E'\n' || le.blocking_statement
    ) AS body,
    jsonb_build_object(
      'observation_id', le.observation_id,
      'captured_at', le.captured_at,
      'relation_name', le.relation_name,
      'relation_oid', le.relation_oid,
      'blocked_pid', le.blocked_pid,
      'blocking_pid', le.blocking_pid,
      'blocked_state', le.blocked_state,
      'blocked_query_start', le.blocked_query_start,
      'wait_event_type', le.wait_event_type,
      'wait_event', le.wait_event,
      'blocked_lock_mode', le.blocked_lock_mode,
      'blocked_lock_granted', le.blocked_lock_granted,
      'blocking_lock_mode', le.blocking_lock_mode,
      'blocking_lock_granted', le.blocking_lock_granted,
      'blocking_pids', le.blocking_pids,
      'capture_mode', capture.capture_mode,
      'capture_key', capture.capture_key,
      'release_verified_at', capture.release_verified_at,
      'service_name', c.service_name,
      'engine_version', c.engine_version
    ) AS metadata
  FROM casework.evidence_items e
  JOIN casework.lock_evidence le ON le.evidence_id = e.evidence_id
  JOIN casework.incidents i ON i.evidence_id = le.incident_evidence_id
  JOIN casework.database_clusters c ON c.cluster_id = i.cluster_id
  LEFT JOIN casework.fixture_captures capture
    ON capture.capture_id = le.capture_id
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
    related.cluster_id,
    related.incident_id,
    commitment.account_name,
    commitment.priority,
    related.environment,
    related.service_name,
    related.engine_version,
    related.aws_region,
    e.source_updated_at AS occurred_at,
    concat_ws(
      E'\n\n',
      commitment.commitment_text,
      'Priority: ' || commitment.priority,
      'Due at: ' || commitment.due_at,
      'Search index status: ' || commitment.status,
      CASE
        WHEN commitment.revalidate_live
        THEN 'Mutable status must be revalidated in the support system before action.'
      END
    ) AS body,
    jsonb_build_object(
      'commitment_id', commitment.commitment_id,
      'priority', commitment.priority,
      'due_at', commitment.due_at,
      'status', commitment.status,
      'revalidate_live', commitment.revalidate_live,
      'service_name', related.service_name,
      'engine_version', related.engine_version
    ) AS metadata
  FROM casework.evidence_items e
  JOIN casework.customer_commitments commitment
    ON commitment.evidence_id = e.evidence_id
  LEFT JOIN LATERAL (
    SELECT
      incident.cluster_id,
      incident.incident_id,
      cluster.environment,
      cluster.service_name,
      cluster.engine_version,
      cluster.aws_region
    FROM casework.support_case_commitments case_commitment
    JOIN casework.incident_support_cases incident_case
      ON incident_case.case_evidence_id = case_commitment.case_evidence_id
    JOIN casework.incidents incident
      ON incident.evidence_id = incident_case.incident_evidence_id
    JOIN casework.database_clusters cluster
      ON cluster.cluster_id = incident.cluster_id
    WHERE case_commitment.commitment_evidence_id = commitment.evidence_id
    ORDER BY incident.started_at DESC
    LIMIT 1
  ) related ON true
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
    incident.cluster_id,
    incident.incident_id,
    NULL::text AS account_name,
    incident.severity,
    cluster.environment,
    cluster.service_name,
    cluster.engine_version,
    cluster.aws_region,
    postmortem.published_at AS occurred_at,
    concat_ws(
      E'\n\n',
      'Root cause: ' || postmortem.root_cause,
      'Contributing factors: ' || postmortem.contributing_factors,
      'Remediation: ' || postmortem.remediation,
      'Prevention: ' || postmortem.prevention
    ) AS body,
    jsonb_build_object(
      'postmortem_id', postmortem.postmortem_id,
      'published_at', postmortem.published_at,
      'service_name', cluster.service_name,
      'engine_version', cluster.engine_version
    ) AS metadata
  FROM casework.evidence_items e
  JOIN casework.postmortems postmortem
    ON postmortem.evidence_id = e.evidence_id
  JOIN casework.incidents incident
    ON incident.evidence_id = postmortem.incident_evidence_id
  JOIN casework.database_clusters cluster
    ON cluster.cluster_id = incident.cluster_id
  WHERE NOT e.is_deleted
)
SELECT
  rendered.evidence_id,
  rendered.evidence_kind,
  rendered.external_key,
  rendered.title,
  rendered.source_system,
  rendered.source_uri,
  rendered.source_revision,
  rendered.source_updated_at,
  rendered.acl,
  rendered.cluster_id,
  rendered.incident_id,
  rendered.account_name,
  rendered.severity,
  rendered.environment,
  rendered.occurred_at,
  rendered.body,
  rendered.metadata,
  casework.sha256_text(
    concat_ws(
      E'\n',
      source_revision,
      evidence_kind,
      external_key,
      title,
      body,
      acl::text,
      coalesce(cluster_id, ''),
      coalesce(incident_id, ''),
      coalesce(account_name, ''),
      coalesce(severity, ''),
      coalesce(environment, ''),
      coalesce(service_name, ''),
      coalesce(engine_version, ''),
      coalesce(aws_region, ''),
      metadata::text
    )
  ) AS search_document_hash,
  rendered.service_name,
  rendered.engine_version,
  rendered.aws_region
FROM rendered;

CREATE TABLE IF NOT EXISTS retrieval.search_index_queue (
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

CREATE TABLE IF NOT EXISTS retrieval.search_index_builds (
  build_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  search_index_version text NOT NULL,
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
  build_id uuid NOT NULL REFERENCES retrieval.search_index_builds(build_id) ON DELETE RESTRICT,
  search_index_version text NOT NULL,
  search_document_hash text NOT NULL,
  source_revision text NOT NULL,
  evidence_kind text NOT NULL,
  external_key text NOT NULL,
  title text NOT NULL,
  source_system text NOT NULL,
  source_uri text NOT NULL,
  source_updated_at timestamptz NOT NULL,
  acl jsonb NOT NULL,
  acl_visibility text NOT NULL,
  acl_principals text[] NOT NULL DEFAULT '{}',
  cluster_id text,
  incident_id text,
  account_name text,
  severity text,
  environment text,
  service_name text,
  engine_version text,
  aws_region text,
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
  UNIQUE (evidence_id, search_index_version, search_document_hash),
  CHECK (NOT is_current OR index_state = 'ready')
);

ALTER TABLE retrieval.documents
  ADD COLUMN IF NOT EXISTS acl_visibility text NOT NULL DEFAULT 'restricted';

ALTER TABLE retrieval.documents
  ADD COLUMN IF NOT EXISTS acl_principals text[] NOT NULL DEFAULT '{}';

ALTER TABLE retrieval.documents
  ADD COLUMN IF NOT EXISTS service_name text;

ALTER TABLE retrieval.documents
  ADD COLUMN IF NOT EXISTS engine_version text;

ALTER TABLE retrieval.documents
  ADD COLUMN IF NOT EXISTS aws_region text;

UPDATE retrieval.documents AS document
SET
  acl = source.acl,
  acl_visibility = coalesce(source.acl ->> 'visibility', 'restricted'),
  acl_principals = ARRAY(
    SELECT jsonb_array_elements_text(
      coalesce(source.acl -> 'principals', '[]'::jsonb)
    )
  )
FROM casework.evidence_items AS source
WHERE source.evidence_id = document.evidence_id
  AND (
    document.acl IS DISTINCT FROM source.acl
    OR document.acl_visibility IS DISTINCT FROM
      coalesce(source.acl ->> 'visibility', 'restricted')
    OR document.acl_principals IS DISTINCT FROM ARRAY(
      SELECT jsonb_array_elements_text(
        coalesce(source.acl -> 'principals', '[]'::jsonb)
      )
    )
  );

CREATE TABLE IF NOT EXISTS retrieval.chunks (
  chunk_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_version_id uuid NOT NULL REFERENCES retrieval.documents(document_version_id) ON DELETE RESTRICT,
  evidence_id uuid NOT NULL REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  chunk_ordinal integer NOT NULL CHECK (chunk_ordinal > 0),
  section_title text,
  chunk_text text NOT NULL,
  chunk_hash text NOT NULL,
  embedding vector(1024),
  embedding_model text,
  embedding_input_type text,
  embedding_state text NOT NULL CHECK (embedding_state IN ('pending', 'ready', 'failed')),
  is_current boolean NOT NULL DEFAULT false,
  evidence_kind text NOT NULL,
  source_updated_at timestamptz NOT NULL,
  occurred_at timestamptz NOT NULL,
  acl jsonb NOT NULL,
  acl_visibility text NOT NULL,
  acl_principals text[] NOT NULL DEFAULT '{}',
  cluster_id text,
  incident_id text,
  account_name text,
  severity text,
  environment text,
  service_name text,
  engine_version text,
  aws_region text,
  created_at timestamptz NOT NULL DEFAULT now(),
  search_tsv tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(section_title, '')), 'B') ||
    setweight(to_tsvector('english', chunk_text), 'C')
  ) STORED,
  UNIQUE (document_version_id, chunk_ordinal),
  CHECK (
    (embedding_state = 'ready' AND embedding IS NOT NULL AND embedding_model IS NOT NULL)
    OR embedding_state <> 'ready'
  ),
  CHECK (NOT is_current OR embedding_state = 'ready')
);

ALTER TABLE retrieval.chunks
  ADD COLUMN IF NOT EXISTS evidence_id uuid;

ALTER TABLE retrieval.chunks
  ADD COLUMN IF NOT EXISTS is_current boolean NOT NULL DEFAULT false;

ALTER TABLE retrieval.chunks
  ADD COLUMN IF NOT EXISTS evidence_kind text;

ALTER TABLE retrieval.chunks
  ADD COLUMN IF NOT EXISTS source_updated_at timestamptz;

ALTER TABLE retrieval.chunks
  ADD COLUMN IF NOT EXISTS occurred_at timestamptz;

ALTER TABLE retrieval.chunks
  ADD COLUMN IF NOT EXISTS acl jsonb;

ALTER TABLE retrieval.chunks
  ADD COLUMN IF NOT EXISTS acl_visibility text NOT NULL DEFAULT 'restricted';

ALTER TABLE retrieval.chunks
  ADD COLUMN IF NOT EXISTS acl_principals text[] NOT NULL DEFAULT '{}';

ALTER TABLE retrieval.chunks
  ADD COLUMN IF NOT EXISTS cluster_id text;

ALTER TABLE retrieval.chunks
  ADD COLUMN IF NOT EXISTS incident_id text;

ALTER TABLE retrieval.chunks
  ADD COLUMN IF NOT EXISTS account_name text;

ALTER TABLE retrieval.chunks
  ADD COLUMN IF NOT EXISTS severity text;

ALTER TABLE retrieval.chunks
  ADD COLUMN IF NOT EXISTS environment text;

ALTER TABLE retrieval.chunks
  ADD COLUMN IF NOT EXISTS service_name text;

ALTER TABLE retrieval.chunks
  ADD COLUMN IF NOT EXISTS engine_version text;

ALTER TABLE retrieval.chunks
  ADD COLUMN IF NOT EXISTS aws_region text;

UPDATE retrieval.chunks AS chunk
SET
  evidence_id = document.evidence_id,
  is_current = document.is_current,
  evidence_kind = document.evidence_kind,
  source_updated_at = document.source_updated_at,
  occurred_at = document.occurred_at,
  acl = document.acl,
  acl_visibility = document.acl_visibility,
  acl_principals = document.acl_principals,
  cluster_id = document.cluster_id,
  incident_id = document.incident_id,
  account_name = document.account_name,
  severity = document.severity,
  environment = document.environment,
  service_name = document.service_name,
  engine_version = document.engine_version,
  aws_region = document.aws_region
FROM retrieval.documents AS document
-- Repairs any chunk row that disagrees with its document. The ADD COLUMN
-- defaults above ('restricted', '{}') are deliberately closed, so re-running
-- this file over an existing cluster must correct the denormalised ACL scalars
-- too. Gating the backfill on acl IS NULL would leave every chunk restricted
-- and silently starve the vector and fuzzy arms, which read the scalars.
WHERE document.document_version_id = chunk.document_version_id
  AND (
    chunk.evidence_id IS DISTINCT FROM document.evidence_id
    OR chunk.is_current IS DISTINCT FROM document.is_current
    OR chunk.evidence_kind IS DISTINCT FROM document.evidence_kind
    OR chunk.source_updated_at IS DISTINCT FROM document.source_updated_at
    OR chunk.occurred_at IS DISTINCT FROM document.occurred_at
    OR chunk.acl IS DISTINCT FROM document.acl
    OR chunk.acl_visibility IS DISTINCT FROM document.acl_visibility
    OR chunk.acl_principals IS DISTINCT FROM document.acl_principals
    OR chunk.cluster_id IS DISTINCT FROM document.cluster_id
    OR chunk.incident_id IS DISTINCT FROM document.incident_id
    OR chunk.account_name IS DISTINCT FROM document.account_name
    OR chunk.severity IS DISTINCT FROM document.severity
    OR chunk.environment IS DISTINCT FROM document.environment
    OR chunk.service_name IS DISTINCT FROM document.service_name
    OR chunk.engine_version IS DISTINCT FROM document.engine_version
    OR chunk.aws_region IS DISTINCT FROM document.aws_region
  );

ALTER TABLE retrieval.chunks
  ALTER COLUMN evidence_id SET NOT NULL,
  ALTER COLUMN evidence_kind SET NOT NULL,
  ALTER COLUMN source_updated_at SET NOT NULL,
  ALTER COLUMN occurred_at SET NOT NULL,
  ALTER COLUMN acl SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'retrieval.chunks'::regclass
      AND conname = 'chunks_evidence_id_fkey'
  ) THEN
    ALTER TABLE retrieval.chunks
      ADD CONSTRAINT chunks_evidence_id_fkey
      FOREIGN KEY (evidence_id)
      REFERENCES casework.evidence_items(evidence_id)
      ON DELETE RESTRICT;
  END IF;
END
$$;

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

CREATE OR REPLACE VIEW retrieval.evidence_edges
WITH (security_invoker = true) AS
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
  'change-runbook:' || cr.change_evidence_id || ':' || cr.runbook_evidence_id,
  cr.change_evidence_id,
  cr.runbook_evidence_id,
  'runbook_' || cr.relationship,
  'canonical_relation'::text,
  1.0::numeric,
  jsonb_build_object('rationale', cr.rationale)
FROM casework.change_runbooks cr

UNION ALL

SELECT
  'case-commitment:' || scc.case_evidence_id || ':' || scc.commitment_evidence_id,
  scc.case_evidence_id,
  scc.commitment_evidence_id,
  'has_commitment',
  'canonical_relation'::text,
  1.0::numeric,
  '{}'::jsonb
FROM casework.support_case_commitments scc

UNION ALL

SELECT
  'incident-postmortem:' || postmortem.incident_evidence_id || ':' || postmortem.evidence_id,
  postmortem.incident_evidence_id,
  postmortem.evidence_id,
  'closed_by_postmortem',
  'canonical_relation'::text,
  1.0::numeric,
  jsonb_build_object('published_at', postmortem.published_at)
FROM casework.postmortems postmortem

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
  'lock-change:' || le.evidence_id || ':' || le.change_evidence_id,
  le.evidence_id,
  le.change_evidence_id,
  'blocked_by_change',
  'canonical_relation'::text,
  1.0::numeric,
  jsonb_build_object(
    'captured_at', le.captured_at,
    'relation_oid', le.relation_oid,
    'blocking_pid', le.blocking_pid
  )
FROM casework.lock_evidence le
WHERE le.change_evidence_id IS NOT NULL

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

  INSERT INTO retrieval.search_index_queue(evidence_id, source_revision)
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
  role text NOT NULL DEFAULT 'app_engineer'
    CHECK (role IN ('app_engineer', 'dba', 'auditor')),
  rrf_k integer NOT NULL CHECK (rrf_k > 0),
  text_weight numeric NOT NULL CHECK (text_weight >= 0),
  vector_weight numeric NOT NULL CHECK (vector_weight >= 0),
  fuzzy_weight numeric NOT NULL CHECK (fuzzy_weight >= 0),
  fuzzy_threshold real NOT NULL DEFAULT 0.3
    CHECK (fuzzy_threshold >= 0 AND fuzzy_threshold <= 1),
  identifier_tokens text[] NOT NULL DEFAULT '{}',
  fuzzy_probe_tokens text[] NOT NULL DEFAULT '{}',
  candidate_pool integer NOT NULL DEFAULT 24 CHECK (candidate_pool > 0),
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

ALTER TABLE proof.retrieval_runs
  ADD COLUMN IF NOT EXISTS fuzzy_threshold real NOT NULL DEFAULT 0.3
  CHECK (fuzzy_threshold >= 0 AND fuzzy_threshold <= 1);

ALTER TABLE proof.retrieval_runs
  ADD COLUMN IF NOT EXISTS identifier_tokens text[] NOT NULL DEFAULT '{}';

ALTER TABLE proof.retrieval_runs
  ADD COLUMN IF NOT EXISTS fuzzy_probe_tokens text[] NOT NULL DEFAULT '{}';

ALTER TABLE proof.retrieval_runs
  ADD COLUMN IF NOT EXISTS candidate_pool integer NOT NULL DEFAULT 24
  CHECK (candidate_pool > 0);

-- Database Insights hand-off (SPEC-session 6.3). Each row records the Aurora
-- resource and the execution window a run occupied, so the Proof surface can
-- deep-link into the same window in CloudWatch Database Insights (Law 4: jumping
-- surfaces is following a citation). The retrieval path writes one row per run
-- from the run's own started_at/completed_at window; wait_event and sql_digest
-- stay NULL there and are reserved for the incident-capture path (6.4), which
-- populates them with a currently blocking session's wait and statement digest.
-- db_resource_id is the Aurora DbiResourceId, sourced from deployment config
-- (env), and is NULL when the deployment has not set WORKBENCH_DB_RESOURCE_ID.
CREATE TABLE IF NOT EXISTS proof.observability_refs (
  run_id uuid PRIMARY KEY REFERENCES proof.retrieval_runs(run_id) ON DELETE CASCADE,
  db_resource_id text,
  window_start timestamptz NOT NULL,
  window_end timestamptz,
  wait_event text,
  sql_digest text,
  captured_at timestamptz NOT NULL DEFAULT now()
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

-- Replay must reproduce the ordering without re-running retrieval, and the
-- ordering is (match_tier, exact_identifier_position, final_score). Persisting
-- only final_score would make an exact-tier receipt unexplainable: the top row
-- can legitimately carry a lower RRF score than the row beneath it.
ALTER TABLE proof.retrieval_candidates
  ADD COLUMN IF NOT EXISTS match_tier integer NOT NULL DEFAULT 2
  CHECK (match_tier IN (1, 2));

ALTER TABLE proof.retrieval_candidates
  ADD COLUMN IF NOT EXISTS exact_identifier_position integer
  CHECK (exact_identifier_position IS NULL OR exact_identifier_position > 0);

CREATE TABLE IF NOT EXISTS proof.run_stages (
  run_id uuid NOT NULL REFERENCES proof.retrieval_runs(run_id) ON DELETE RESTRICT,
  stage_ordinal integer NOT NULL CHECK (stage_ordinal > 0),
  stage_name text NOT NULL,
  duration_ms integer NOT NULL CHECK (duration_ms >= 0),
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (run_id, stage_ordinal)
);

CREATE TABLE IF NOT EXISTS proof.agent_runs (
  agent_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  question text NOT NULL,
  role text NOT NULL DEFAULT 'app_engineer'
    CHECK (role IN ('app_engineer', 'dba', 'auditor')),
  filters_initial jsonb NOT NULL DEFAULT '{}'::jsonb,
  controls_initial jsonb NOT NULL,
  max_tool_calls integer NOT NULL DEFAULT 12 CHECK (max_tool_calls > 0),
  max_escalations integer NOT NULL DEFAULT 2 CHECK (max_escalations >= 0),
  tool_calls_spent integer NOT NULL DEFAULT 0,
  escalations_spent integer NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'running'
    CHECK (
      status IN (
        'running',
        'complete',
        'partial',
        'budget_exhausted',
        'no_evidence',
        'failed'
      )
    ),
  contract_version text NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  ended_at timestamptz,
  error text,
  CHECK (
    tool_calls_spent <= max_tool_calls
    AND escalations_spent <= max_escalations
  )
);

ALTER TABLE proof.retrieval_runs
  ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'app_engineer';

ALTER TABLE proof.agent_runs
  ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'app_engineer';

ALTER TABLE proof.retrieval_runs
  ALTER COLUMN role SET DEFAULT 'app_engineer';
ALTER TABLE proof.agent_runs
  ALTER COLUMN role SET DEFAULT 'app_engineer';

-- Drop the old enum constraints before rewriting existing receipt values. On an
-- upgraded database they still accept only analyst/admin/auditor, so updating a
-- row first would fail before the new constraints could be installed.
ALTER TABLE proof.retrieval_runs
  DROP CONSTRAINT IF EXISTS retrieval_runs_role_check;
ALTER TABLE proof.agent_runs
  DROP CONSTRAINT IF EXISTS agent_runs_role_check;

-- Pre-collapse receipts carried a jsonb identity bag. The only two values ever
-- written were the workshop default and the support-lead pair, which map onto the
-- App Engineer and DBA personas respectively (DBA, not Auditor: the old
-- support-lead saw the restricted row unmasked).
DO $$
DECLARE
  v_retrieval_has_principal boolean;
  v_agent_has_principal boolean;
BEGIN
  SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_schema = 'proof' AND table_name = 'retrieval_runs'
       AND column_name = 'principal'
  ) INTO v_retrieval_has_principal;

  SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_schema = 'proof' AND table_name = 'agent_runs'
       AND column_name = 'principal'
  ) INTO v_agent_has_principal;

  -- Only the legacy principal-column migration needs to remove the dependent
  -- view. An ordinary schema reapply must not delete a live API dependency when
  -- the caller intentionally applies only the admission-owned SQL subset.
  IF v_retrieval_has_principal OR v_agent_has_principal THEN
    DROP VIEW IF EXISTS proof.v_run_receipts;
  END IF;

  IF v_retrieval_has_principal THEN
    UPDATE proof.retrieval_runs
    SET role = CASE
      WHEN principal -> 'principals' ? 'support-lead' THEN 'dba'
      ELSE 'app_engineer'
    END;
    ALTER TABLE proof.retrieval_runs DROP COLUMN principal;
  END IF;

  IF v_agent_has_principal THEN
    UPDATE proof.agent_runs
    SET role = CASE
      WHEN principal -> 'principals' ? 'support-lead' THEN 'dba'
      ELSE 'app_engineer'
    END;
    ALTER TABLE proof.agent_runs DROP COLUMN principal;
  END IF;

  UPDATE proof.retrieval_runs
     SET role = CASE role
       WHEN 'analyst' THEN 'app_engineer'
       WHEN 'admin' THEN 'dba'
       ELSE role
     END
   WHERE role IN ('analyst', 'admin');

  UPDATE proof.agent_runs
     SET role = CASE role
       WHEN 'analyst' THEN 'app_engineer'
       WHEN 'admin' THEN 'dba'
       ELSE role
     END
   WHERE role IN ('analyst', 'admin');
END
$$;

ALTER TABLE proof.retrieval_runs
  ADD CONSTRAINT retrieval_runs_role_check
  CHECK (role IN ('app_engineer', 'dba', 'auditor'));

ALTER TABLE proof.agent_runs
  ADD CONSTRAINT agent_runs_role_check
  CHECK (role IN ('app_engineer', 'dba', 'auditor'));

CREATE TABLE IF NOT EXISTS proof.agent_subquestions (
  agent_run_id uuid NOT NULL
    REFERENCES proof.agent_runs(agent_run_id) ON DELETE RESTRICT,
  subquestion_id text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal > 0),
  subquestion_text text NOT NULL,
  required_kinds text[] NOT NULL,
  coverage_top_n integer NOT NULL DEFAULT 8 CHECK (coverage_top_n > 0),
  covered boolean NOT NULL DEFAULT false,
  covering_evidence_ids jsonb NOT NULL DEFAULT '{}'::jsonb,
  missing_kinds text[] NOT NULL DEFAULT '{}',
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  PRIMARY KEY (agent_run_id, subquestion_id),
  UNIQUE (agent_run_id, ordinal),
  CHECK (NOT covered OR cardinality(missing_kinds) = 0)
);

CREATE TABLE IF NOT EXISTS proof.agent_retrievals (
  agent_run_id uuid NOT NULL,
  subquestion_id text NOT NULL,
  attempt integer NOT NULL CHECK (attempt > 0),
  run_id uuid NOT NULL
    REFERENCES proof.retrieval_runs(run_id) ON DELETE RESTRICT,
  superseded_by integer,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (agent_run_id, subquestion_id, attempt),
  FOREIGN KEY (agent_run_id, subquestion_id)
    REFERENCES proof.agent_subquestions(agent_run_id, subquestion_id)
    ON DELETE RESTRICT,
  UNIQUE (run_id),
  CHECK (superseded_by IS NULL OR superseded_by > attempt)
);

CREATE TABLE IF NOT EXISTS proof.agent_escalations (
  agent_run_id uuid NOT NULL,
  subquestion_id text NOT NULL,
  attempt integer NOT NULL CHECK (attempt > 1),
  reason text NOT NULL
    CHECK (reason IN ('missing_required_kind', 'zero_candidates')),
  missing_kinds text[] NOT NULL DEFAULT '{}',
  changed jsonb NOT NULL,
  rationale text NOT NULL,
  outcome text NOT NULL
    CHECK (outcome IN ('covered', 'still_uncovered', 'budget_exhausted')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (agent_run_id, subquestion_id, attempt),
  FOREIGN KEY (agent_run_id, subquestion_id)
    REFERENCES proof.agent_subquestions(agent_run_id, subquestion_id)
    ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS proof.agent_answers (
  run_id uuid PRIMARY KEY REFERENCES proof.retrieval_runs(run_id) ON DELETE RESTRICT,
  agent_run_id uuid UNIQUE
    REFERENCES proof.agent_runs(agent_run_id) ON DELETE RESTRICT,
  question text NOT NULL,
  answer_text text NOT NULL,
  synthesis_mode text NOT NULL CHECK (synthesis_mode IN ('bedrock', 'extractive_fallback', 'checkpoint')),
  validation_status text NOT NULL DEFAULT 'pending'
    CHECK (validation_status IN ('pending', 'valid', 'failed')),
  model_id text,
  model_transport text,
  input_tokens integer,
  output_tokens integer,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE proof.agent_answers
  ADD COLUMN IF NOT EXISTS agent_run_id uuid UNIQUE
  REFERENCES proof.agent_runs(agent_run_id) ON DELETE RESTRICT;

ALTER TABLE proof.agent_answers
  ADD COLUMN IF NOT EXISTS validation_status text NOT NULL DEFAULT 'pending';

ALTER TABLE proof.agent_answers
  DROP CONSTRAINT IF EXISTS agent_answers_validation_status_check;

ALTER TABLE proof.agent_answers
  ADD CONSTRAINT agent_answers_validation_status_check
  CHECK (validation_status IN ('pending', 'valid', 'failed'));

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
  evaluation_type text NOT NULL DEFAULT 'retrieval'
    CHECK (evaluation_type IN ('retrieval', 'traversal')),
  filters jsonb NOT NULL DEFAULT '{}'::jsonb,
  notes text
);

ALTER TABLE proof.evaluation_queries
  ADD COLUMN IF NOT EXISTS evaluation_type text NOT NULL DEFAULT 'retrieval';

ALTER TABLE proof.evaluation_queries
  DROP CONSTRAINT IF EXISTS evaluation_queries_evaluation_type_check;

ALTER TABLE proof.evaluation_queries
  ADD CONSTRAINT evaluation_queries_evaluation_type_check
  CHECK (evaluation_type IN ('retrieval', 'traversal'));

CREATE TABLE IF NOT EXISTS proof.relevance_judgments (
  query_id text NOT NULL REFERENCES proof.evaluation_queries(query_id) ON DELETE RESTRICT,
  evidence_id uuid NOT NULL REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  relevance integer NOT NULL CHECK (relevance BETWEEN 0 AND 3),
  rationale text NOT NULL,
  PRIMARY KEY (query_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS proof.traversal_results (
  run_id uuid NOT NULL REFERENCES proof.retrieval_runs(run_id) ON DELETE RESTRICT,
  query_id text NOT NULL REFERENCES proof.evaluation_queries(query_id) ON DELETE RESTRICT,
  evidence_id uuid NOT NULL REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  depth integer NOT NULL CHECK (depth >= 0),
  path uuid[] NOT NULL,
  via_edge_key text,
  via_relation text,
  via_origin text,
  via_confidence numeric,
  PRIMARY KEY (run_id, query_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS proof.transport_invocations (
  invocation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES proof.retrieval_runs(run_id) ON DELETE RESTRICT,
  role text NOT NULL DEFAULT 'app_engineer'
    CHECK (role IN ('app_engineer', 'auditor', 'dba')),
  transport text NOT NULL CHECK (transport IN ('http', 'stdio_mcp', 'agentcore_gateway')),
  tool_name text NOT NULL,
  contract_version text NOT NULL,
  request_hash text NOT NULL,
  normalized_response_hash text,
  transport_trace_id text,
  status text NOT NULL CHECK (status IN ('succeeded', 'failed', 'replayed')),
  invoked_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE proof.transport_invocations
  ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'app_engineer';

ALTER TABLE proof.transport_invocations
  DROP CONSTRAINT IF EXISTS transport_invocations_role_check;

UPDATE proof.transport_invocations invocation
   SET role = run.role
  FROM proof.retrieval_runs run
 WHERE invocation.run_id = run.run_id
   AND invocation.role IS DISTINCT FROM run.role;

UPDATE proof.transport_invocations
   SET role = CASE role
     WHEN 'analyst' THEN 'app_engineer'
     WHEN 'admin' THEN 'dba'
     ELSE role
   END
 WHERE role IN ('analyst', 'admin');

ALTER TABLE proof.transport_invocations
  ALTER COLUMN role SET DEFAULT 'app_engineer',
  ALTER COLUMN role SET NOT NULL;

ALTER TABLE proof.transport_invocations
  ADD CONSTRAINT transport_invocations_role_check
  CHECK (role IN ('app_engineer', 'auditor', 'dba'));
