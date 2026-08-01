-- sql/10_admission.sql — admission contract (D21). Applied after sql/09.
-- Section (a): temporal + idempotency columns on the canonical evidence header.
ALTER TABLE casework.evidence_items
  ADD COLUMN IF NOT EXISTS content_hash text;

ALTER TABLE casework.evidence_items
  ADD COLUMN IF NOT EXISTS available_at timestamptz;

-- Idempotency key for admitted content. Partial: preloaded rows have no
-- content_hash and are exempt (they are not admitted through this contract).
CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_items_admission
  ON casework.evidence_items (source_uri, content_hash)
  WHERE content_hash IS NOT NULL;

-- Section (b): the ingest receipt — one per admitted (source_uri, content_hash).
CREATE TABLE IF NOT EXISTS casework.ingest_receipts (
  ingest_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_uri text NOT NULL,
  content_hash text NOT NULL,
  evidence_id uuid NOT NULL REFERENCES casework.evidence_items(evidence_id) ON DELETE RESTRICT,
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

-- Section (c): the admission contract. One transaction (the function body):
-- validate -> upsert typed rows -> inferred edge -> queue projection -> receipt.
-- Idempotent by (source_uri, content_hash). Raises on any contract violation,
-- which rolls back every write. Zero model calls.
CREATE OR REPLACE FUNCTION casework.admit_evidence(payload jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, casework, retrieval
AS $$
DECLARE
  v_source_uri   text := payload #>> '{source,uri}';
  v_source_system text := payload #>> '{source,system}';
  v_kind         text := payload ->> 'kind';
  v_external_key text := payload ->> 'external_key';
  v_title        text := payload ->> 'title';
  v_body         text := payload ->> 'body';
  v_occurred_at  timestamptz := (payload ->> 'occurred_at')::timestamptz;
  v_available_at timestamptz := coalesce((payload ->> 'available_at')::timestamptz, now());
  v_acl          jsonb := coalesce(payload -> 'acl', '{"visibility":"workshop"}'::jsonb);
  v_revision_payload jsonb;
  v_content_hash text;
  v_payload_hash text;
  v_evidence_id  uuid;
  v_incident_id  uuid;
  v_existing_kind text;
  v_existing_source_system text;
  v_existing_source_uri text;
  v_existing     casework.ingest_receipts%ROWTYPE;
  v_rows         integer := 0;
  v_edges        integer := 0;
  v_queued       integer := 0;
  v_link         jsonb;
  v_link_target  uuid;
BEGIN
  -- 1. Validate the contract. Each raise names the violation; nothing is written.
  IF payload ->> 'schema' IS DISTINCT FROM 'admission payload v1' THEN
    RAISE EXCEPTION 'admission: schema must be "admission payload v1", got %',
      coalesce(payload ->> 'schema', '<null>') USING ERRCODE = '22023';
  END IF;
  IF v_source_uri IS NULL OR v_source_system IS NULL
     OR v_kind IS NULL OR v_external_key IS NULL
     OR v_title IS NULL OR v_body IS NULL OR v_occurred_at IS NULL THEN
    RAISE EXCEPTION 'admission: missing required field (source.system/source.uri/kind/external_key/title/body/occurred_at)'
      USING ERRCODE = '22023';
  END IF;
  IF v_kind <> 'lock_evidence' THEN
    RAISE EXCEPTION 'admission: this contract path handles kind lock_evidence, got %', v_kind
      USING ERRCODE = '22023';
  END IF;

  -- The revision fingerprint covers the complete authoritative payload. Normalize
  -- optional defaults so omitting ACL/links/available_at and supplying their
  -- effective defaults are the same revision.
  v_revision_payload :=
    payload
    || jsonb_build_object('acl', v_acl)
    || jsonb_build_object(
         'links', coalesce(payload -> 'links', '[]'::jsonb),
         'available_at', coalesce(payload -> 'available_at', 'null'::jsonb)
       );
  v_payload_hash := casework.sha256_text(v_revision_payload::text);
  v_content_hash := v_payload_hash;

  -- Serialize all revisions of one logical key. This closes the race where two
  -- identical first admissions both pass the receipt lookup and one later loses
  -- to a unique constraint instead of returning the first receipt.
  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('casework.evidence:' || v_external_key, 0)
  );

  -- An external key belongs to exactly one evidence kind even though the base
  -- schema's historical unique constraint is (evidence_kind, external_key).
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
      'admission: external key % already belongs to evidence kind %, not %',
      v_external_key, v_existing_kind, v_kind
      USING ERRCODE = '23505';
  END IF;

  -- A revision may replace the facts for an existing key, but it may not claim
  -- that key from a different authoritative source.
  SELECT evidence_id, source_system, source_uri
    INTO v_evidence_id, v_existing_source_system, v_existing_source_uri
    FROM casework.evidence_items
   WHERE evidence_kind = v_kind
     AND external_key = v_external_key
   FOR UPDATE;
  IF FOUND AND (
    v_existing_source_system IS DISTINCT FROM v_source_system
    OR v_existing_source_uri IS DISTINCT FROM v_source_uri
  ) THEN
    RAISE EXCEPTION
      'admission: external key % is owned by source % at %, not source % at %',
      v_external_key, v_existing_source_system, v_existing_source_uri,
      v_source_system, v_source_uri
      USING ERRCODE = '23505';
  END IF;

  -- 2. Idempotency: same normalized revision -> return the prior receipt.
  SELECT * INTO v_existing FROM casework.ingest_receipts
   WHERE source_uri = v_source_uri AND content_hash = v_content_hash
   FOR UPDATE;
  IF FOUND THEN
    IF v_existing.external_key IS DISTINCT FROM v_external_key
       OR v_existing.evidence_kind IS DISTINCT FROM v_kind THEN
      RAISE EXCEPTION
        'admission: revision fingerprint collision for source %, existing key % kind %, incoming key % kind %',
        v_source_uri, v_existing.external_key, v_existing.evidence_kind,
        v_external_key, v_kind
        USING ERRCODE = '23505';
    END IF;
    RETURN to_jsonb(v_existing) || jsonb_build_object('idempotent_replay', true);
  END IF;

  -- 3. Resolve the incident FK (lock_evidence.incident_evidence_id is NOT NULL).
  SELECT evidence_id INTO v_incident_id FROM casework.evidence_items
   WHERE evidence_kind = 'incident'
     AND external_key = (payload #>> '{structured,incident_external_key}');
  IF v_incident_id IS NULL THEN
    RAISE EXCEPTION 'admission: referenced incident % not found',
      coalesce(payload #>> '{structured,incident_external_key}', '<null>')
      USING ERRCODE = '23503';
  END IF;

  -- 4. Upsert the canonical evidence header (idempotent on the admission key).
  INSERT INTO casework.evidence_items
    (evidence_kind, external_key, title, source_system, source_uri,
     source_revision, source_updated_at, acl, content_hash, available_at)
  VALUES
    (v_kind, v_external_key, v_title, v_source_system, v_source_uri,
     v_payload_hash, v_occurred_at, v_acl, v_content_hash, v_available_at)
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
  -- rows_written counts upsert statements executed, not net-new rows. An exact
  -- replay returns its original receipt before reaching either upsert.
  v_rows := v_rows + 1;

  -- 5. Upsert the lock_evidence detail row.
  INSERT INTO casework.lock_evidence
    (evidence_id, observation_id, incident_evidence_id, captured_at, relation_name,
     relation_oid, blocked_pid, blocking_pid, blocked_state, blocked_query_start,
     wait_event_type, wait_event, blocked_lock_mode, blocked_lock_granted,
     blocking_lock_mode, blocking_lock_granted, blocking_pids,
     blocking_pids_sql, blocking_pids_output, blocked_statement,
     blocking_statement, raw_capture)
  VALUES
    (v_evidence_id, v_external_key, v_incident_id,
     (payload #>> '{structured,captured_at}')::timestamptz,
     payload #>> '{structured,relation_name}',
     (payload #>> '{structured,relation_oid}')::oid,
     (payload #>> '{structured,blocked_pid}')::integer,
     (payload #>> '{structured,blocking_pid}')::integer,
     payload #>> '{structured,blocked_state}',
     (payload #>> '{structured,blocked_query_start}')::timestamptz,
     payload #>> '{structured,wait_event_type}',
     payload #>> '{structured,wait_event}',
     payload #>> '{structured,blocked_lock_mode}',
     (payload #>> '{structured,blocked_lock_granted}')::boolean,
     payload #>> '{structured,blocking_lock_mode}',
     (payload #>> '{structured,blocking_lock_granted}')::boolean,
     CASE
       WHEN payload #> '{structured,blocking_pids}' IS NULL THEN NULL
       ELSE ARRAY(
         SELECT value::integer
         FROM jsonb_array_elements_text(
           payload #> '{structured,blocking_pids}'
         ) AS value
       )
     END,
     payload #>> '{structured,blocking_pids_sql}',
     payload #>> '{structured,blocking_pids_output}',
     payload #>> '{structured,blocked_statement}',
     payload #>> '{structured,blocking_statement}',
     coalesce(payload #> '{structured,raw_capture}', '{}'::jsonb))
  ON CONFLICT (evidence_id) DO UPDATE
    SET observation_id = EXCLUDED.observation_id,
        incident_evidence_id = EXCLUDED.incident_evidence_id,
        change_evidence_id = NULL,
        capture_id = NULL,
        captured_at = EXCLUDED.captured_at,
        relation_name = EXCLUDED.relation_name,
        relation_oid = EXCLUDED.relation_oid,
        blocked_pid = EXCLUDED.blocked_pid,
        blocking_pid = EXCLUDED.blocking_pid,
        blocked_state = EXCLUDED.blocked_state,
        blocked_query_start = EXCLUDED.blocked_query_start,
        wait_event_type = EXCLUDED.wait_event_type,
        wait_event = EXCLUDED.wait_event,
        blocked_lock_mode = EXCLUDED.blocked_lock_mode,
        blocked_lock_granted = EXCLUDED.blocked_lock_granted,
        blocking_lock_mode = EXCLUDED.blocking_lock_mode,
        blocking_lock_granted = EXCLUDED.blocking_lock_granted,
        blocking_pids = EXCLUDED.blocking_pids,
        blocking_pids_sql = EXCLUDED.blocking_pids_sql,
        blocking_pids_output = EXCLUDED.blocking_pids_output,
        blocked_statement = EXCLUDED.blocked_statement,
        blocking_statement = EXCLUDED.blocking_statement,
        database_insights_slice = NULL,
        raw_capture = EXCLUDED.raw_capture;
  v_rows := v_rows + 1;

  -- 6. Inferred edges (never canonical): store in retrieval.inferred_edges.
  FOR v_link IN SELECT * FROM jsonb_array_elements(coalesce(payload -> 'links', '[]'::jsonb))
  LOOP
    SELECT evidence_id INTO v_link_target FROM casework.evidence_items
     WHERE evidence_kind = (v_link ->> 'to_kind')
       AND external_key = (v_link ->> 'to_external_key');
    IF v_link_target IS NOT NULL AND v_link_target <> v_evidence_id THEN
      INSERT INTO retrieval.inferred_edges
        (from_evidence_id, to_evidence_id, relation, confidence, method, source_revision, metadata)
      VALUES
        (v_evidence_id, v_link_target, v_link ->> 'relation',
         coalesce((v_link ->> 'confidence')::numeric, 0.5),
         'live_session_capture', v_payload_hash,
         jsonb_build_object('admitted', true))
      ON CONFLICT (from_evidence_id, to_evidence_id, relation, source_revision) DO NOTHING;
      v_edges := v_edges + 1;
    END IF;
  END LOOP;

  -- 7. Queue the search-index projection (async; nothing waits on it).
  INSERT INTO retrieval.search_index_queue (evidence_id, source_revision)
  VALUES (v_evidence_id, v_payload_hash)
  ON CONFLICT (evidence_id, source_revision) DO NOTHING;
  v_queued := 1;

  -- 8. Write the ingest receipt and return it.
  INSERT INTO casework.ingest_receipts
    (source_uri, content_hash, evidence_id, external_key, evidence_kind,
     payload_hash, rows_written, edges_written, queued, available_at)
  VALUES
    (v_source_uri, v_content_hash, v_evidence_id, v_external_key, v_kind,
     v_payload_hash, v_rows, v_edges, v_queued, v_available_at)
  RETURNING * INTO v_existing;

  RETURN to_jsonb(v_existing) || jsonb_build_object('idempotent_replay', false);
END;
$$;

-- CREATE OR REPLACE must preserve the security boundary on every re-run. PUBLIC
-- receives EXECUTE on new functions by default; sql/11 grants it back only to the
-- participant and app identities after those roles exist.
REVOKE ALL ON FUNCTION casework.admit_evidence(jsonb) FROM PUBLIC;
