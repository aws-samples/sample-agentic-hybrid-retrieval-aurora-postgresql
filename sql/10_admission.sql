-- sql/10_admission.sql - atomic admission for one participant-induced live run.
ALTER TABLE casework.evidence_items
  ADD COLUMN IF NOT EXISTS content_hash text;

ALTER TABLE casework.evidence_items
  ADD COLUMN IF NOT EXISTS available_at timestamptz;

CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_items_admission
  ON casework.evidence_items (source_uri, content_hash)
  WHERE content_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS casework.ingest_receipts (
  ingest_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_uri text NOT NULL,
  content_hash text NOT NULL,
  evidence_id uuid NOT NULL
    REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
  external_key text NOT NULL,
  evidence_kind text NOT NULL,
  payload_hash text NOT NULL,
  rows_written integer NOT NULL CHECK (rows_written >= 0),
  edges_written integer NOT NULL CHECK (edges_written >= 0),
  queued integer NOT NULL CHECK (queued >= 0),
  available_at timestamptz NOT NULL,
  admitted_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_uri, content_hash)
);

CREATE OR REPLACE FUNCTION casework.admit_evidence(payload jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, casework, retrieval
AS $$
DECLARE
  v_source_system constant text := 'pg_incident_capture';
  v_bundle_uri text := payload #>> '{source,uri}';
  v_cluster_id text := payload #>> '{database,cluster_id}';
  v_database_name text := payload #>> '{database,database_name}';
  v_engine text := payload #>> '{database,engine}';
  v_engine_version text := payload #>> '{database,engine_version}';
  v_aws_region text := payload #>> '{database,aws_region}';
  v_capture jsonb := payload -> 'capture';
  v_telemetry jsonb := payload -> 'telemetry';
  v_incident jsonb := payload #> '{records,incident}';
  v_changes jsonb := payload #> '{records,changes}';
  v_lock jsonb := payload #> '{records,lock_evidence}';
  v_telemetry_documents jsonb := payload #> '{records,telemetry_documents}';
  v_capture_id uuid;
  v_run_suffix text;
  v_expected_suffix text;
  v_incident_key text;
  v_unsafe_change_key text;
  v_safe_change_key text;
  v_lock_key text;
  v_payload_hash text;
  v_available_at timestamptz;
  v_existing casework.ingest_receipts%ROWTYPE;
  v_record jsonb;
  v_kind text;
  v_external_key text;
  v_source_uri text;
  v_record_hash text;
  v_evidence_id uuid;
  v_incident_id uuid;
  v_lock_id uuid;
  v_change_id uuid;
  v_existing_kind text;
  v_existing_source_system text;
  v_existing_source_uri text;
  v_rows integer := 0;
  v_edges integer := 0;
  v_queued integer := 0;
  v_activity_observations integer;
  v_lock_observations integer;
  v_blocking_observations integer;
  v_interval_activity_documents integer;
  v_interval_lock_documents integer;
  v_interval_blocking_documents integer;
BEGIN
  IF payload ->> 'schema' IS DISTINCT FROM 'admission payload v1' THEN
    RAISE EXCEPTION 'admission: schema must be "admission payload v1"'
      USING ERRCODE = '22023';
  END IF;
  IF payload ->> 'kind' IS DISTINCT FROM 'incident_bundle' THEN
    RAISE EXCEPTION 'admission: kind must be incident_bundle'
      USING ERRCODE = '22023';
  END IF;
  IF payload #>> '{source,system}' IS DISTINCT FROM v_source_system THEN
    RAISE EXCEPTION 'admission: source.system must be %', v_source_system
      USING ERRCODE = '22023';
  END IF;
  IF v_bundle_uri IS NULL OR btrim(v_bundle_uri) = '' THEN
    RAISE EXCEPTION 'admission: source.uri is required'
      USING ERRCODE = '22023';
  END IF;
  IF v_cluster_id IS NULL
     OR v_database_name IS NULL
     OR v_engine_version IS NULL
     OR v_aws_region IS NULL THEN
    RAISE EXCEPTION
      'admission: cluster_id, database_name, engine_version, and aws_region are required'
      USING ERRCODE = '22023';
  END IF;
  IF v_engine IS DISTINCT FROM 'aurora-postgresql' THEN
    RAISE EXCEPTION
      'admission: live participant evidence requires aurora-postgresql'
      USING ERRCODE = '22023';
  END IF;
  IF jsonb_typeof(v_capture) IS DISTINCT FROM 'object'
     OR jsonb_typeof(v_telemetry) IS DISTINCT FROM 'object'
     OR jsonb_typeof(v_incident) IS DISTINCT FROM 'object'
     OR jsonb_typeof(v_changes) IS DISTINCT FROM 'array'
     OR jsonb_typeof(v_lock) IS DISTINCT FROM 'object'
     OR jsonb_typeof(v_telemetry_documents) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION
      'admission: capture, telemetry, incident, changes, lock, and telemetry documents are required'
      USING ERRCODE = '22023';
  END IF;

  BEGIN
    v_capture_id := (v_capture ->> 'capture_id')::uuid;
  EXCEPTION WHEN invalid_text_representation THEN
    RAISE EXCEPTION 'admission: capture.capture_id must be a UUID'
      USING ERRCODE = '22023';
  END;
  v_run_suffix := upper(v_capture ->> 'run_suffix');
  v_expected_suffix := upper(right(replace(v_capture_id::text, '-', ''), 8));
  IF v_capture ->> 'capture_origin'
       IS DISTINCT FROM 'participant_induced'
     OR v_run_suffix IS DISTINCT FROM v_expected_suffix
     OR v_capture ->> 'capture_key'
       IS DISTINCT FROM 'CAP-' || v_expected_suffix
     OR (v_capture ->> 'observation_count')::integer <> 30
     OR (v_capture ->> 'writer_count')::integer <> 6
     OR (v_capture ->> 'reader_count')::integer <> 2 THEN
    RAISE EXCEPTION
      'admission: capture identity or 30-observation/6-writer/2-reader contract is invalid'
      USING ERRCODE = '22023';
  END IF;

  v_incident_key := v_incident ->> 'external_key';
  v_unsafe_change_key := v_changes -> 0 ->> 'external_key';
  v_safe_change_key := v_changes -> 1 ->> 'external_key';
  v_lock_key := v_lock ->> 'external_key';
  IF jsonb_array_length(v_changes) <> 2
     OR v_incident_key IS DISTINCT FROM 'INC-' || v_run_suffix
     OR v_unsafe_change_key IS DISTINCT FROM 'CHG-' || v_run_suffix || '-01'
     OR v_safe_change_key IS DISTINCT FROM 'CHG-' || v_run_suffix || '-02'
     OR v_lock_key IS DISTINCT FROM 'LOCK-' || v_run_suffix || '-01'
     OR v_lock #>> '{structured,incident_external_key}'
       IS DISTINCT FROM v_incident_key
     OR v_lock #>> '{structured,change_external_key}'
       IS DISTINCT FROM v_unsafe_change_key THEN
    RAISE EXCEPTION
      'admission: evidence identifiers must be derived from run suffix %',
      v_run_suffix
      USING ERRCODE = '22023';
  END IF;
  IF v_changes -> 0 #>> '{structured,change_role}' IS DISTINCT FROM 'unsafe'
     OR v_changes -> 1 #>> '{structured,change_role}' IS DISTINCT FROM 'repair'
     OR v_changes -> 0 #>> '{structured,relationship}' IS DISTINCT FROM 'confirmed'
     OR v_changes -> 1 #>> '{structured,relationship}' IS DISTINCT FROM 'remediated'
     OR v_changes -> 0 #>> '{structured,incident_external_key}'
       IS DISTINCT FROM v_incident_key
     OR v_changes -> 1 #>> '{structured,incident_external_key}'
       IS DISTINCT FROM v_incident_key THEN
    RAISE EXCEPTION
      'admission: changes must identify the measured unsafe cause and repair'
      USING ERRCODE = '22023';
  END IF;
  IF v_lock #>> '{structured,wait_event_type}' IS DISTINCT FROM 'Lock'
     OR lower(v_lock #>> '{structured,wait_event}') IS DISTINCT FROM 'relation'
     OR v_lock #>> '{structured,blocked_lock_mode}'
       IS DISTINCT FROM 'RowExclusiveLock'
     OR (v_lock #>> '{structured,blocked_lock_granted}')::boolean
       IS DISTINCT FROM false
     OR v_lock #>> '{structured,blocking_lock_mode}'
       IS DISTINCT FROM 'ShareLock'
     OR (v_lock #>> '{structured,blocking_lock_granted}')::boolean
       IS DISTINCT FROM true THEN
    RAISE EXCEPTION
      'admission: lock evidence does not prove the live Lock:relation wait'
      USING ERRCODE = '22023';
  END IF;

  SELECT count(DISTINCT (sample ->> 'observation_number')::integer)
  INTO v_activity_observations
  FROM jsonb_array_elements(
    coalesce(v_telemetry -> 'pg_stat_activity', '[]'::jsonb)
  ) sample;
  SELECT count(DISTINCT (sample ->> 'observation_number')::integer)
  INTO v_lock_observations
  FROM jsonb_array_elements(
    coalesce(v_telemetry -> 'pg_locks', '[]'::jsonb)
  ) sample;
  SELECT count(DISTINCT (sample ->> 'observation_number')::integer)
  INTO v_blocking_observations
  FROM jsonb_array_elements(
    coalesce(v_telemetry -> 'pg_blocking_pids', '[]'::jsonb)
  ) sample;
  IF jsonb_array_length(coalesce(
       v_telemetry -> 'pg_stat_activity', '[]'::jsonb
     )) < 270
     OR jsonb_array_length(coalesce(
       v_telemetry -> 'pg_locks', '[]'::jsonb
     )) < 270
     OR jsonb_array_length(coalesce(
       v_telemetry -> 'pg_blocking_pids', '[]'::jsonb
     )) < 180
     OR v_activity_observations <> 30
     OR v_lock_observations <> 30
     OR v_blocking_observations <> 30
     OR jsonb_array_length(coalesce(
       v_telemetry -> 'pg_stat_statements', '[]'::jsonb
     )) <> 3
     OR jsonb_array_length(coalesce(
       v_telemetry -> 'cloudwatch_metrics', '[]'::jsonb
     )) <> 5 THEN
    RAISE EXCEPTION
      'admission: complete live PostgreSQL and CloudWatch telemetry is required'
      USING ERRCODE = '22023';
  END IF;

  IF jsonb_array_length(v_telemetry_documents) < 100
     OR jsonb_array_length(v_telemetry_documents) > 120 THEN
    RAISE EXCEPTION
      'admission: searchable telemetry must contain 100 to 120 documents'
      USING ERRCODE = '22023';
  END IF;
  SELECT
    count(*) FILTER (
      WHERE document #>> '{structured,telemetry_type}' = 'activity_window'
    ),
    count(*) FILTER (
      WHERE document #>> '{structured,telemetry_type}' = 'lock_topology'
    ),
    count(*) FILTER (
      WHERE document #>> '{structured,telemetry_type}' = 'blocking_chain'
    )
  INTO
    v_interval_activity_documents,
    v_interval_lock_documents,
    v_interval_blocking_documents
  FROM jsonb_array_elements(v_telemetry_documents) document;
  IF v_interval_activity_documents <> 30
     OR v_interval_lock_documents <> 30
     OR v_interval_blocking_documents <> 30
     OR EXISTS (
       SELECT 1
       FROM jsonb_array_elements(v_telemetry_documents) document
       WHERE document ->> 'external_key'
         !~ ('^TEL-' || v_run_suffix || '-[A-Z]+[0-9]+$')
          OR document #>> '{structured,incident_external_key}'
            IS DISTINCT FROM v_incident_key
     ) THEN
    RAISE EXCEPTION
      'admission: telemetry documents do not match the run-scoped evidence contract'
      USING ERRCODE = '22023';
  END IF;

  v_available_at := (v_lock ->> 'available_at')::timestamptz;
  IF v_available_at IS NULL THEN
    RAISE EXCEPTION 'admission: every record requires available_at'
      USING ERRCODE = '22023';
  END IF;
  v_payload_hash := casework.sha256_text(payload::text);
  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('casework.live_run:' || v_bundle_uri, 0)
  );

  SELECT *
  INTO v_existing
  FROM casework.ingest_receipts
  WHERE source_uri = v_bundle_uri
    AND content_hash = v_payload_hash
  FOR UPDATE;
  IF FOUND THEN
    RETURN to_jsonb(v_existing) || jsonb_build_object(
      'idempotent_replay', true,
      'capture_id', v_capture_id,
      'run_suffix', v_run_suffix,
      'evidence', (
        SELECT jsonb_object_agg(
          item.external_key,
          jsonb_build_object(
            'evidence_id', item.evidence_id,
            'evidence_kind', item.evidence_kind
          )
        )
        FROM casework.evidence_items item
        WHERE item.source_system = v_source_system
          AND item.source_uri LIKE v_bundle_uri || '/%'
      )
    );
  END IF;

  INSERT INTO casework.database_clusters(
    cluster_id,
    engine,
    engine_version,
    aws_region,
    environment,
    service_name,
    writer_endpoint_alias,
    instance_class,
    database_insights_mode,
    metadata
  )
  VALUES (
    v_cluster_id,
    v_engine,
    v_engine_version,
    v_aws_region,
    'development',
    'participant-incident-lab',
    coalesce(payload #>> '{database,endpoint}', v_database_name),
    payload #>> '{database,instance_class}',
    'advanced',
    (payload -> 'database') || jsonb_build_object(
      'captured_source_uri', v_bundle_uri,
      'capture_id', v_capture_id
    )
  )
  ON CONFLICT (cluster_id) DO UPDATE
    SET engine = EXCLUDED.engine,
        engine_version = EXCLUDED.engine_version,
        aws_region = EXCLUDED.aws_region,
        environment = EXCLUDED.environment,
        service_name = EXCLUDED.service_name,
        writer_endpoint_alias = EXCLUDED.writer_endpoint_alias,
        instance_class = EXCLUDED.instance_class,
        database_insights_mode = EXCLUDED.database_insights_mode,
        metadata = EXCLUDED.metadata;
  v_rows := v_rows + 1;

  FOR v_kind, v_record IN
    SELECT record.kind, record.body
    FROM (
      SELECT 'incident'::text AS kind, v_incident AS body
      UNION ALL
      SELECT 'change', value
      FROM jsonb_array_elements(v_changes) value
      UNION ALL
      SELECT 'lock_evidence', v_lock
      UNION ALL
      SELECT 'telemetry', value
      FROM jsonb_array_elements(v_telemetry_documents) value
    ) record
  LOOP
    v_external_key := v_record ->> 'external_key';
    v_source_uri := v_record ->> 'source_uri';
    IF v_external_key IS NULL
       OR v_source_uri IS NULL
       OR v_source_uri NOT LIKE v_bundle_uri || '/%'
       OR v_record ->> 'title' IS NULL
       OR v_record ->> 'occurred_at' IS NULL
       OR v_record ->> 'available_at' IS NULL
       OR v_record ->> 'body' IS NULL
       OR jsonb_typeof(v_record -> 'structured') IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'admission: % record is missing a required field', v_kind
        USING ERRCODE = '22023';
    END IF;

    SELECT evidence_kind
    INTO v_existing_kind
    FROM casework.evidence_items
    WHERE external_key = v_external_key
      AND evidence_kind <> v_kind
    ORDER BY evidence_kind
    LIMIT 1
    FOR UPDATE;
    IF FOUND THEN
      RAISE EXCEPTION
        'admission: external key % already belongs to evidence kind %',
        v_external_key,
        v_existing_kind
        USING ERRCODE = '23505';
    END IF;

    SELECT source_system, source_uri
    INTO v_existing_source_system, v_existing_source_uri
    FROM casework.evidence_items
    WHERE evidence_kind = v_kind
      AND external_key = v_external_key
    FOR UPDATE;
    IF FOUND AND (
      v_existing_source_system IS DISTINCT FROM v_source_system
      OR v_existing_source_uri IS DISTINCT FROM v_source_uri
    ) THEN
      RAISE EXCEPTION
        'admission: external key % is owned by another source',
        v_external_key
        USING ERRCODE = '23505';
    END IF;

    v_record_hash := casework.sha256_text(v_record::text);
    INSERT INTO casework.evidence_items(
      evidence_kind,
      external_key,
      title,
      source_system,
      source_uri,
      source_revision,
      source_updated_at,
      acl,
      content_hash,
      available_at
    )
    VALUES (
      v_kind,
      v_external_key,
      v_record ->> 'title',
      v_source_system,
      v_source_uri,
      v_record_hash,
      (v_record ->> 'occurred_at')::timestamptz,
      coalesce(v_record -> 'acl', '{"visibility":"workshop"}'::jsonb),
      v_record_hash,
      (v_record ->> 'available_at')::timestamptz
    )
    ON CONFLICT (evidence_kind, external_key) DO UPDATE
      SET title = EXCLUDED.title,
          source_system = EXCLUDED.source_system,
          source_uri = EXCLUDED.source_uri,
          source_revision = EXCLUDED.source_revision,
          source_updated_at = EXCLUDED.source_updated_at,
          acl = EXCLUDED.acl,
          content_hash = EXCLUDED.content_hash,
          available_at = EXCLUDED.available_at,
          is_deleted = false,
          deleted_at = NULL
    RETURNING evidence_id INTO v_evidence_id;
    v_rows := v_rows + 1;
  END LOOP;

  SELECT evidence_id
  INTO v_incident_id
  FROM casework.evidence_items
  WHERE evidence_kind = 'incident'
    AND external_key = v_incident_key;
  SELECT evidence_id
  INTO v_lock_id
  FROM casework.evidence_items
  WHERE evidence_kind = 'lock_evidence'
    AND external_key = v_lock_key;

  INSERT INTO casework.incidents(
    evidence_id,
    incident_id,
    cluster_id,
    severity,
    status,
    started_at,
    mitigated_at,
    resolved_at,
    summary,
    impact_summary,
    resolution
  )
  VALUES (
    v_incident_id,
    v_incident_key,
    v_cluster_id,
    v_incident #>> '{structured,severity}',
    v_incident #>> '{structured,status}',
    (v_incident #>> '{structured,started_at}')::timestamptz,
    (v_incident #>> '{structured,mitigated_at}')::timestamptz,
    (v_incident #>> '{structured,resolved_at}')::timestamptz,
    v_incident #>> '{structured,summary}',
    v_incident #>> '{structured,impact_summary}',
    v_incident #>> '{structured,resolution}'
  )
  ON CONFLICT (evidence_id) DO UPDATE
    SET cluster_id = EXCLUDED.cluster_id,
        severity = EXCLUDED.severity,
        status = EXCLUDED.status,
        started_at = EXCLUDED.started_at,
        mitigated_at = EXCLUDED.mitigated_at,
        resolved_at = EXCLUDED.resolved_at,
        summary = EXCLUDED.summary,
        impact_summary = EXCLUDED.impact_summary,
        resolution = EXCLUDED.resolution;
  v_rows := v_rows + 1;

  FOR v_record IN
    SELECT value
    FROM jsonb_array_elements(v_changes) value
  LOOP
    SELECT evidence_id
    INTO v_change_id
    FROM casework.evidence_items
    WHERE evidence_kind = 'change'
      AND external_key = v_record ->> 'external_key';

    INSERT INTO casework.changes(
      evidence_id,
      change_id,
      cluster_id,
      change_type,
      status,
      started_at,
      completed_at,
      owner_team,
      execution_sql,
      description,
      rollback_plan
    )
    VALUES (
      v_change_id,
      v_record ->> 'external_key',
      v_cluster_id,
      v_record #>> '{structured,change_type}',
      v_record #>> '{structured,status}',
      (v_record #>> '{structured,started_at}')::timestamptz,
      (v_record #>> '{structured,completed_at}')::timestamptz,
      v_record #>> '{structured,owner_team}',
      v_record #>> '{structured,execution_sql}',
      v_record #>> '{structured,description}',
      v_record #>> '{structured,rollback_plan}'
    )
    ON CONFLICT (evidence_id) DO UPDATE
      SET cluster_id = EXCLUDED.cluster_id,
          change_type = EXCLUDED.change_type,
          status = EXCLUDED.status,
          started_at = EXCLUDED.started_at,
          completed_at = EXCLUDED.completed_at,
          owner_team = EXCLUDED.owner_team,
          execution_sql = EXCLUDED.execution_sql,
          description = EXCLUDED.description,
          rollback_plan = EXCLUDED.rollback_plan;

    INSERT INTO casework.incident_changes(
      incident_evidence_id,
      change_evidence_id,
      relationship,
      rationale,
      confirmed_by
    )
    VALUES (
      v_incident_id,
      v_change_id,
      v_record #>> '{structured,relationship}',
      v_record #>> '{structured,rationale}',
      v_source_system
    )
    ON CONFLICT (incident_evidence_id, change_evidence_id) DO UPDATE
      SET relationship = EXCLUDED.relationship,
          rationale = EXCLUDED.rationale,
          confirmed_by = EXCLUDED.confirmed_by;
    v_rows := v_rows + 2;
    v_edges := v_edges + 1;
  END LOOP;

  INSERT INTO casework.incident_capture_runs(
    capture_id,
    capture_key,
    incident_evidence_id,
    cluster_id,
    capture_origin,
    engine_version,
    instance_class,
    database_name,
    table_schema,
    table_name,
    relation_oid,
    configured_row_count,
    observed_row_count,
    table_size_bytes,
    steady_state_connections,
    capture_started_at,
    capture_ended_at,
    capture_tool_version,
    source_bundle_sha256,
    source_bundle_uri,
    observability_verified_at,
    manifest
  )
  VALUES (
    v_capture_id,
    v_capture ->> 'capture_key',
    v_incident_id,
    v_cluster_id,
    v_capture ->> 'capture_origin',
    v_engine_version,
    payload #>> '{database,instance_class}',
    v_database_name,
    split_part(v_capture ->> 'relation_name', '.', 1),
    split_part(v_capture ->> 'relation_name', '.', 2),
    (v_capture ->> 'relation_oid')::oid,
    (v_capture ->> 'configured_row_count')::bigint,
    (v_capture ->> 'observed_row_count')::bigint,
    (v_capture ->> 'table_size_bytes')::bigint,
    1
      + (v_capture ->> 'writer_count')::integer
      + (v_capture ->> 'reader_count')::integer,
    (v_capture ->> 'capture_started_at')::timestamptz,
    (v_capture ->> 'capture_ended_at')::timestamptz,
    v_capture ->> 'capture_tool_version',
    v_payload_hash,
    v_bundle_uri,
    (v_capture ->> 'capture_ended_at')::timestamptz,
    coalesce(v_capture -> 'manifest', '{}'::jsonb)
  );
  v_rows := v_rows + 1;

  SELECT evidence_id
  INTO v_change_id
  FROM casework.evidence_items
  WHERE evidence_kind = 'change'
    AND external_key = v_unsafe_change_key;
  INSERT INTO casework.lock_evidence(
    evidence_id,
    observation_id,
    incident_evidence_id,
    change_evidence_id,
    capture_id,
    captured_at,
    relation_name,
    relation_oid,
    blocked_pid,
    blocking_pid,
    blocked_state,
    blocked_query_start,
    wait_event_type,
    wait_event,
    blocked_lock_mode,
    blocked_lock_granted,
    blocking_lock_mode,
    blocking_lock_granted,
    blocking_pids,
    blocking_pids_sql,
    blocking_pids_output,
    blocked_statement,
    blocking_statement,
    raw_capture
  )
  VALUES (
    v_lock_id,
    v_lock_key,
    v_incident_id,
    v_change_id,
    v_capture_id,
    (v_lock #>> '{structured,captured_at}')::timestamptz,
    v_lock #>> '{structured,relation_name}',
    (v_lock #>> '{structured,relation_oid}')::oid,
    (v_lock #>> '{structured,blocked_pid}')::integer,
    (v_lock #>> '{structured,blocking_pid}')::integer,
    v_lock #>> '{structured,blocked_state}',
    (v_lock #>> '{structured,blocked_query_start}')::timestamptz,
    v_lock #>> '{structured,wait_event_type}',
    lower(v_lock #>> '{structured,wait_event}'),
    v_lock #>> '{structured,blocked_lock_mode}',
    (v_lock #>> '{structured,blocked_lock_granted}')::boolean,
    v_lock #>> '{structured,blocking_lock_mode}',
    (v_lock #>> '{structured,blocking_lock_granted}')::boolean,
    ARRAY(
      SELECT value::integer
      FROM jsonb_array_elements_text(
        coalesce(v_lock #> '{structured,blocking_pids}', '[]'::jsonb)
      ) value
    ),
    v_lock #>> '{structured,blocking_pids_sql}',
    v_lock #>> '{structured,blocking_pids_output}',
    v_lock #>> '{structured,blocked_statement}',
    v_lock #>> '{structured,blocking_statement}',
    v_lock -> 'structured'
  );
  v_rows := v_rows + 1;
  v_edges := v_edges + 2;

  INSERT INTO casework.pg_stat_activity_samples(
    capture_id,
    observation_evidence_id,
    observation_number,
    captured_at,
    pid,
    backend_type,
    application_name,
    state,
    wait_event_type,
    wait_event,
    query_start,
    xact_start,
    query,
    raw_row
  )
  SELECT
    v_capture_id,
    v_lock_id,
    (sample ->> 'observation_number')::integer,
    (sample ->> 'captured_at')::timestamptz,
    (sample ->> 'pid')::integer,
    sample ->> 'backend_type',
    sample ->> 'application_name',
    sample ->> 'state',
    sample ->> 'wait_event_type',
    sample ->> 'wait_event',
    (sample ->> 'query_start')::timestamptz,
    (sample ->> 'xact_start')::timestamptz,
    sample ->> 'query',
    coalesce(sample -> 'raw_row', sample)
  FROM jsonb_array_elements(v_telemetry -> 'pg_stat_activity') sample;

  INSERT INTO casework.pg_lock_samples(
    capture_id,
    observation_evidence_id,
    observation_number,
    captured_at,
    pid,
    locktype,
    database_oid,
    relation_oid,
    relation_name,
    mode,
    granted,
    fastpath,
    waitstart,
    raw_row
  )
  SELECT
    v_capture_id,
    v_lock_id,
    (sample ->> 'observation_number')::integer,
    (sample ->> 'captured_at')::timestamptz,
    (sample ->> 'pid')::integer,
    sample ->> 'locktype',
    (sample ->> 'database_oid')::oid,
    (sample ->> 'relation_oid')::oid,
    sample ->> 'relation_name',
    sample ->> 'mode',
    (sample ->> 'granted')::boolean,
    (sample ->> 'fastpath')::boolean,
    (sample ->> 'waitstart')::timestamptz,
    coalesce(sample -> 'raw_row', sample)
  FROM jsonb_array_elements(v_telemetry -> 'pg_locks') sample;

  INSERT INTO casework.pg_blocking_pids_samples(
    capture_id,
    observation_evidence_id,
    observation_number,
    captured_at,
    blocked_pid,
    blocking_pids,
    literal_sql,
    literal_output,
    raw_row
  )
  SELECT
    v_capture_id,
    v_lock_id,
    (sample ->> 'observation_number')::integer,
    (sample ->> 'captured_at')::timestamptz,
    (sample ->> 'blocked_pid')::integer,
    ARRAY(
      SELECT value::integer
      FROM jsonb_array_elements_text(sample -> 'blocking_pids') value
    ),
    sample ->> 'literal_sql',
    sample ->> 'literal_output',
    coalesce(sample -> 'raw_row', sample)
  FROM jsonb_array_elements(v_telemetry -> 'pg_blocking_pids') sample;

  INSERT INTO casework.pg_stat_statements_samples(
    capture_id,
    phase,
    captured_at,
    calls,
    total_exec_time,
    rows,
    queryids,
    queries,
    delta_from_before,
    raw_row
  )
  SELECT
    v_capture_id,
    sample ->> 'phase',
    (sample ->> 'captured_at')::timestamptz,
    (sample ->> 'calls')::bigint,
    (sample ->> 'total_exec_time')::double precision,
    (sample ->> 'rows')::bigint,
    coalesce(sample -> 'queryids', '[]'::jsonb),
    coalesce(sample -> 'queries', '[]'::jsonb),
    sample -> 'delta_from_before',
    sample
  FROM jsonb_array_elements(v_telemetry -> 'pg_stat_statements') sample;

  INSERT INTO casework.cloudwatch_metric_samples(
    capture_id,
    metric_name,
    namespace,
    dimension_name,
    dimension_value,
    statistic,
    period_seconds,
    observed_at,
    value,
    unit,
    raw_datapoint
  )
  SELECT
    v_capture_id,
    sample ->> 'metric_name',
    sample ->> 'namespace',
    sample ->> 'dimension_name',
    sample ->> 'dimension_value',
    sample ->> 'statistic',
    (sample ->> 'period_seconds')::integer,
    (sample ->> 'observed_at')::timestamptz,
    (sample ->> 'value')::double precision,
    sample ->> 'unit',
    coalesce(sample -> 'raw_datapoint', sample)
  FROM jsonb_array_elements(v_telemetry -> 'cloudwatch_metrics') sample;

  INSERT INTO casework.telemetry_evidence(
    evidence_id,
    telemetry_id,
    capture_id,
    incident_evidence_id,
    change_evidence_id,
    telemetry_type,
    observation_number,
    observed_at,
    observed_until,
    body,
    structured
  )
  SELECT
    item.evidence_id,
    document ->> 'external_key',
    v_capture_id,
    v_incident_id,
    change_item.evidence_id,
    document #>> '{structured,telemetry_type}',
    (document #>> '{structured,observation_number}')::integer,
    (document ->> 'occurred_at')::timestamptz,
    (document #>> '{structured,observed_until}')::timestamptz,
    document ->> 'body',
    document -> 'structured'
  FROM jsonb_array_elements(v_telemetry_documents) document
  JOIN casework.evidence_items item
    ON item.evidence_kind = 'telemetry'
   AND item.external_key = document ->> 'external_key'
  LEFT JOIN casework.evidence_items change_item
    ON change_item.evidence_kind = 'change'
   AND change_item.external_key =
     document #>> '{structured,change_external_key}';

  v_rows := v_rows
    + jsonb_array_length(v_telemetry -> 'pg_stat_activity')
    + jsonb_array_length(v_telemetry -> 'pg_locks')
    + jsonb_array_length(v_telemetry -> 'pg_blocking_pids')
    + jsonb_array_length(v_telemetry -> 'pg_stat_statements')
    + jsonb_array_length(v_telemetry -> 'cloudwatch_metrics')
    + jsonb_array_length(v_telemetry_documents);
  v_edges := v_edges
    + jsonb_array_length(v_telemetry_documents)
    + (
      SELECT count(*)
      FROM jsonb_array_elements(v_telemetry_documents) document
      WHERE document #>> '{structured,change_external_key}' IS NOT NULL
    );

  FOR v_evidence_id IN
    SELECT item.evidence_id
    FROM casework.evidence_items item
    WHERE item.source_system = v_source_system
      AND item.source_uri LIKE v_bundle_uri || '/%'
      AND NOT item.is_deleted
  LOOP
    PERFORM casework.queue_evidence(v_evidence_id);
    v_queued := v_queued + 1;
  END LOOP;

  INSERT INTO casework.ingest_receipts(
    source_uri,
    content_hash,
    evidence_id,
    external_key,
    evidence_kind,
    payload_hash,
    rows_written,
    edges_written,
    queued,
    available_at
  )
  VALUES (
    v_bundle_uri,
    v_payload_hash,
    v_incident_id,
    v_incident_key,
    'incident_bundle',
    v_payload_hash,
    v_rows,
    v_edges,
    v_queued,
    v_available_at
  )
  RETURNING * INTO v_existing;

  RETURN to_jsonb(v_existing) || jsonb_build_object(
    'idempotent_replay', false,
    'capture_id', v_capture_id,
    'run_suffix', v_run_suffix,
    'evidence', (
      SELECT jsonb_object_agg(
        item.external_key,
        jsonb_build_object(
          'evidence_id', item.evidence_id,
          'evidence_kind', item.evidence_kind
        )
      )
      FROM casework.evidence_items item
      WHERE item.source_system = v_source_system
        AND item.source_uri LIKE v_bundle_uri || '/%'
    )
  );
END;
$$;

REVOKE ALL ON FUNCTION casework.admit_evidence(jsonb) FROM PUBLIC;
