-- sql/10_admission.sql - atomic admission for one participant-induced capture wave.
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
  v_wave text := coalesce(payload ->> 'wave', 'A');
  v_bundle_uri text := payload #>> '{source,uri}';
  v_cluster_id text := payload #>> '{database,cluster_id}';
  v_database_name text := payload #>> '{database,database_name}';
  v_engine text := payload #>> '{database,engine}';
  v_engine_version text := payload #>> '{database,engine_version}';
  v_aws_region text := payload #>> '{database,aws_region}';
  v_capture jsonb := payload -> 'capture';
  v_request_count integer;
  v_blocked_writer_count integer;
  v_reader_count integer;
  v_cloudwatch_status text := nullif(btrim(payload ->> 'cloudwatch_status'), '');
  v_phases jsonb := v_capture -> 'phases';
  v_signal_types jsonb := v_capture -> 'signal_types';
  v_telemetry jsonb := payload -> 'telemetry';
  v_incident jsonb := payload #> '{records,incident}';
  v_changes jsonb := payload #> '{records,changes}';
  v_lock jsonb := payload #> '{records,lock_evidence}';
  v_telemetry_documents jsonb := payload #> '{records,telemetry_documents}';
  v_capture_id uuid;
  v_run_suffix text;
  v_expected_suffix text;
  v_incident_key text;
  v_lock_key text;
  v_lock_change_key text;
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
  v_acl jsonb;
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
  IF v_wave NOT IN ('A', 'B') THEN
    RAISE EXCEPTION 'admission rejected: capture stage must be A or B, got %', v_wave
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
     OR jsonb_typeof(v_changes) IS DISTINCT FROM 'array'
     OR jsonb_typeof(v_telemetry_documents) IS DISTINCT FROM 'array'
     OR (
       v_wave = 'A'
       AND (
         jsonb_typeof(v_incident) IS DISTINCT FROM 'object'
         OR jsonb_typeof(v_lock) IS DISTINCT FROM 'object'
       )
     )
     OR (
       v_wave = 'B'
       AND (v_incident IS NOT NULL OR v_lock IS NOT NULL)
     ) THEN
    RAISE EXCEPTION
      'admission rejected: Investigation Evidence requires incident, changes, '
      'lock, and telemetry documents; Validation Evidence requires only new '
      'changes and telemetry documents'
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
       IS DISTINCT FROM 'CAP-' || v_expected_suffix THEN
    RAISE EXCEPTION
      'admission: capture identity does not match the derived run suffix %',
      v_expected_suffix
      USING ERRCODE = '22023';
  END IF;

  BEGIN
    v_request_count := (v_capture ->> 'request_count')::integer;
    v_blocked_writer_count := (v_capture ->> 'blocked_writer_count')::integer;
    v_reader_count := (v_capture ->> 'reader_count')::integer;
  EXCEPTION WHEN invalid_text_representation THEN
    RAISE EXCEPTION
      'admission rejected: capture must carry integer request_count, '
      'blocked_writer_count, and reader_count plus phases and signal_types arrays'
      USING ERRCODE = '22023';
  END;

  IF v_wave = 'A' AND v_blocked_writer_count IS NULL THEN
    RAISE EXCEPTION
      'admission rejected: blocked_writer_count must equal DB_POOL_MAX_SIZE (10), got <null>'
      USING ERRCODE = '22023';
  END IF;

  IF v_request_count IS NULL
     OR v_blocked_writer_count IS NULL
     OR v_reader_count IS NULL
     OR jsonb_typeof(v_phases) IS DISTINCT FROM 'array'
     OR jsonb_typeof(v_signal_types) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION
      'admission rejected: capture must carry integer request_count, '
      'blocked_writer_count, and reader_count plus phases and signal_types arrays'
      USING ERRCODE = '22023';
  END IF;

  IF v_cloudwatch_status IS NULL
     OR v_cloudwatch_status NOT IN ('available', 'unavailable') THEN
    RAISE EXCEPTION
      'admission rejected: cloudwatch_status must be available or unavailable, got %',
      coalesce(v_cloudwatch_status, '<null>')
      USING ERRCODE = '22023';
  END IF;

  IF v_wave = 'A' THEN
    IF v_blocked_writer_count <> 10 THEN
      RAISE EXCEPTION
        'admission rejected: blocked_writer_count must equal DB_POOL_MAX_SIZE (10), got %',
        v_blocked_writer_count
        USING ERRCODE = '22023';
    END IF;

    IF v_request_count <= v_blocked_writer_count THEN
      RAISE EXCEPTION
        'admission rejected: request_count (%) must exceed blocked_writer_count (%); '
        'a run where every request obtained a connection produced no wait queue and '
        'therefore no pool exhaustion',
        v_request_count, v_blocked_writer_count
        USING ERRCODE = '22023';
    END IF;

    IF v_reader_count <> 0 THEN
      RAISE EXCEPTION
        'admission rejected: the four-phase mechanism has no reader sessions, got %',
        v_reader_count
        USING ERRCODE = '22023';
    END IF;

    IF NOT (
      v_phases @> '["backfill","pool_exhaustion","recovery","plan_regression"]'::jsonb
    ) THEN
      RAISE EXCEPTION
        'admission rejected: missing incident phases, got %', v_phases
        USING ERRCODE = '22023';
    END IF;

    IF NOT (
      v_signal_types @> '["lock","pool","request","wal","meta","plan"]'::jsonb
    ) THEN
      RAISE EXCEPTION
        'admission rejected: every signal type must be represented, got %',
        v_signal_types
        USING ERRCODE = '22023';
    END IF;
  ELSE
    IF v_request_count <> 0
       OR v_blocked_writer_count <> 0
       OR v_reader_count <> 0 THEN
      RAISE EXCEPTION
        'admission rejected: Validation Evidence validates the recommendation and must not '
        'claim incident request, blocked-writer, or reader counts; got %, %, %',
        v_request_count, v_blocked_writer_count, v_reader_count
        USING ERRCODE = '22023';
    END IF;

    IF NOT (v_phases @> '["plan_regression"]'::jsonb)
       OR NOT (v_signal_types @> '["meta","plan"]'::jsonb) THEN
      RAISE EXCEPTION
        'admission rejected: Validation Evidence must carry plan_regression plus meta and '
        'plan validation evidence; got phases %, signal types %',
        v_phases, v_signal_types
        USING ERRCODE = '22023';
    END IF;
  END IF;

  IF v_wave = 'A' THEN
    v_incident_key := v_incident ->> 'external_key';
    IF v_incident_key IS DISTINCT FROM 'INC-' || v_run_suffix THEN
      RAISE EXCEPTION
        'admission: Investigation Evidence incident identity must be derived from run suffix %',
        v_run_suffix
        USING ERRCODE = '22023';
    END IF;
  ELSE
    v_incident_key := nullif(btrim(payload ->> 'incident_key'), '');
    IF v_incident_key IS NULL THEN
      RAISE EXCEPTION
        'admission rejected: Validation Evidence must name the incident_key it attaches to'
        USING ERRCODE = '22023';
    END IF;

    SELECT item.evidence_id
    INTO v_incident_id
    FROM casework.evidence_items item
    JOIN casework.incidents incident
      ON incident.evidence_id = item.evidence_id
    JOIN casework.incident_capture_runs wave_a
      ON wave_a.incident_evidence_id = incident.evidence_id
     AND wave_a.wave = 'A'
    WHERE item.evidence_kind = 'incident'
      AND item.external_key = v_incident_key
      AND item.source_system = v_source_system
      AND incident.cluster_id = v_cluster_id
      AND wave_a.cluster_id = v_cluster_id
      AND NOT item.is_deleted;
    IF NOT FOUND THEN
      RAISE EXCEPTION
        'admission rejected: wave B names incident % which has no Investigation Evidence '
        'capture on cluster %',
        v_incident_key, v_cluster_id
        USING ERRCODE = '22023';
    END IF;
  END IF;

  IF jsonb_array_length(v_changes) = 0
     OR EXISTS (
       SELECT 1
       FROM jsonb_array_elements(v_changes) change_record
       WHERE change_record ->> 'external_key'
         !~ ('^CHG-' || v_run_suffix || '-[0-9]{2}$')
          OR change_record #>> '{structured,incident_external_key}'
            IS DISTINCT FROM v_incident_key
     ) THEN
    RAISE EXCEPTION
      'admission: change identifiers must be run-scoped and name incident %',
      v_incident_key
      USING ERRCODE = '22023';
  END IF;

  IF v_wave = 'A' THEN
    v_lock_key := v_lock ->> 'external_key';
    v_lock_change_key := v_lock #>> '{structured,change_external_key}';
    IF v_lock_key IS DISTINCT FROM 'LOCK-' || v_run_suffix || '-01'
       OR v_lock #>> '{structured,incident_external_key}'
         IS DISTINCT FROM v_incident_key
       OR NOT EXISTS (
         SELECT 1
         FROM jsonb_array_elements(v_changes) change_record
         WHERE change_record ->> 'external_key' = v_lock_change_key
       )
       OR NOT EXISTS (
         SELECT 1
         FROM jsonb_array_elements(v_changes) change_record
         WHERE change_record #>> '{structured,relationship}' = 'confirmed'
       ) THEN
      RAISE EXCEPTION
        'admission: Investigation Evidence lock and confirmed change must match run suffix %',
        v_run_suffix
        USING ERRCODE = '22023';
    END IF;

    IF v_lock #>> '{structured,wait_event_type}' IS DISTINCT FROM 'Lock'
       OR lower(v_lock #>> '{structured,wait_event}')
         IS DISTINCT FROM 'transactionid'
       OR lower(v_lock #>> '{structured,blocked_locktype}')
         IS DISTINCT FROM 'transactionid'
       OR (v_lock #>> '{structured,blocked_lock_granted}')::boolean
         IS DISTINCT FROM false
       OR NOT EXISTS (
         SELECT 1
         FROM jsonb_array_elements_text(
           coalesce(v_lock #> '{structured,blocking_pids}', '[]'::jsonb)
         ) blocker(pid)
         WHERE blocker.pid::integer
           = (v_lock #>> '{structured,blocking_pid}')::integer
       )
       OR v_lock #>> '{structured,blocking_pids_sql}'
         IS DISTINCT FROM
           'SELECT pg_blocking_pids(' ||
           (v_lock #>> '{structured,blocked_pid}') ||
           ');' THEN
      RAISE EXCEPTION
        'admission: lock evidence does not prove the live Lock:transactionid '
        'wait on the backfill transaction'
        USING ERRCODE = '22023';
    END IF;
  ELSE
    IF jsonb_array_length(v_changes) <> 1
       OR v_changes -> 0 #>> '{structured,change_role}'
         IS DISTINCT FROM 'validation'
       OR v_changes -> 0 #>> '{structured,relationship}'
         IS DISTINCT FROM 'validates'
       OR jsonb_array_length(v_telemetry_documents) = 0 THEN
      RAISE EXCEPTION
        'admission rejected: Validation Evidence requires one validation change with a '
        'validates relationship and at least one new telemetry document'
        USING ERRCODE = '22023';
    END IF;
  END IF;

  IF EXISTS (
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

  IF v_wave = 'A' THEN
    v_available_at := (v_lock ->> 'available_at')::timestamptz;
  ELSE
    v_available_at := (v_changes -> 0 ->> 'available_at')::timestamptz;
  END IF;
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
      WHERE v_wave = 'A'
      UNION ALL
      SELECT 'change', value
      FROM jsonb_array_elements(v_changes) value
      UNION ALL
      SELECT 'lock_evidence', v_lock
      WHERE v_wave = 'A'
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

    IF v_record -> 'acl' IS NULL THEN
      RAISE EXCEPTION
        'admission rejected: % record % carries no acl; visibility must be '
        'classified by the producer, never defaulted here',
        v_kind, v_external_key
        USING ERRCODE = '22023';
    END IF;

    v_acl := v_record -> 'acl';
    IF v_acl ->> 'visibility' NOT IN ('workshop', 'restricted') THEN
      RAISE EXCEPTION
        'admission rejected: % record % has acl.visibility %; the only values are '
        'workshop and restricted, and any other value reads as restricted in '
        'retrieval.acl_visible and silently removes the row from every arm',
        v_kind, v_external_key, coalesce(v_acl ->> 'visibility', '<null>')
        USING ERRCODE = '22023';
    END IF;

    IF v_acl ->> 'classifier_version' IS NULL
       OR v_acl ->> 'classification_reason' IS NULL
       OR jsonb_typeof(v_acl -> 'classification_sources') IS DISTINCT FROM 'array' THEN
      RAISE EXCEPTION
        'admission rejected: % record % is missing acl classification provenance; '
        'classifier_version, classification_reason, and a classification_sources '
        'array are all required so the label can be replayed',
        v_kind, v_external_key
        USING ERRCODE = '22023';
    END IF;

    IF v_acl ->> 'visibility' = 'restricted'
       AND jsonb_array_length(v_acl -> 'classification_sources') = 0 THEN
      RAISE EXCEPTION
        'admission rejected: % record % is restricted with an empty '
        'classification_sources array; a label nothing can re-derive is '
        'indistinguishable from a hand-written one',
        v_kind, v_external_key
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
      v_acl,
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

  IF v_wave = 'A' THEN
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
  END IF;

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
    wave,
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
    v_wave,
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
    CASE
      WHEN v_wave = 'A'
      THEN 1 + v_blocked_writer_count + v_reader_count
      ELSE 1
    END,
    (v_capture ->> 'capture_started_at')::timestamptz,
    (v_capture ->> 'capture_ended_at')::timestamptz,
    v_capture ->> 'capture_tool_version',
    v_payload_hash,
    v_bundle_uri,
    (v_capture ->> 'capture_ended_at')::timestamptz,
    coalesce(v_capture -> 'manifest', '{}'::jsonb)
      || jsonb_build_object(
        'phases', v_phases,
        'signal_types', v_signal_types,
        'request_count', v_request_count,
        'blocked_writer_count', v_blocked_writer_count,
        'reader_count', v_reader_count,
        'cloudwatch_status', v_cloudwatch_status
      )
  );
  v_rows := v_rows + 1;

  IF v_wave = 'A' THEN
    SELECT evidence_id
    INTO v_change_id
    FROM casework.evidence_items
    WHERE evidence_kind = 'change'
      AND external_key = v_lock_change_key;
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
      blocked_locktype,
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
      lower(v_lock #>> '{structured,blocked_locktype}'),
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
  END IF;

  INSERT INTO casework.pg_stat_activity_samples(
    sample_id,
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
  OVERRIDING SYSTEM VALUE
  SELECT
    coalesce(
      nullif(sample ->> 'sample_id', '')::bigint,
      nextval(
        pg_get_serial_sequence(
          'casework.pg_stat_activity_samples',
          'sample_id'
        )
      )
    ),
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
    sample_id,
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
  OVERRIDING SYSTEM VALUE
  SELECT
    coalesce(
      nullif(sample ->> 'sample_id', '')::bigint,
      nextval(
        pg_get_serial_sequence(
          'casework.pg_stat_statements_samples',
          'sample_id'
        )
      )
    ),
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
