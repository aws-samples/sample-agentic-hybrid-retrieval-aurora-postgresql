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
AS $$
DECLARE
  v_source_uri   text := payload #>> '{source,uri}';
  v_kind         text := payload ->> 'kind';
  v_external_key text := payload ->> 'external_key';
  v_title        text := payload ->> 'title';
  v_body         text := payload ->> 'body';
  v_occurred_at  timestamptz := (payload ->> 'occurred_at')::timestamptz;
  v_available_at timestamptz := coalesce((payload ->> 'available_at')::timestamptz, now());
  v_acl          jsonb := coalesce(payload -> 'acl', '{"visibility":"workshop"}'::jsonb);
  v_content_hash text;
  v_payload_hash text := casework.sha256_text(payload::text);
  v_evidence_id  uuid;
  v_incident_id  uuid;
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
  IF v_source_uri IS NULL OR v_kind IS NULL OR v_external_key IS NULL
     OR v_title IS NULL OR v_body IS NULL OR v_occurred_at IS NULL THEN
    RAISE EXCEPTION 'admission: missing required field (source.uri/kind/external_key/title/body/occurred_at)'
      USING ERRCODE = '22023';
  END IF;
  IF v_kind <> 'lock_evidence' THEN
    RAISE EXCEPTION 'admission: this contract path handles kind lock_evidence, got %', v_kind
      USING ERRCODE = '22023';
  END IF;

  v_content_hash := casework.sha256_text(v_source_uri || '|' || v_body);

  -- 2. Idempotency: same (source_uri, content_hash) -> return the prior receipt.
  SELECT * INTO v_existing FROM casework.ingest_receipts
   WHERE source_uri = v_source_uri AND content_hash = v_content_hash;
  IF FOUND THEN
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
    (v_kind, v_external_key, v_title, payload #>> '{source,system}', v_source_uri,
     v_payload_hash, v_occurred_at, v_acl, v_content_hash, v_available_at)
  ON CONFLICT (evidence_kind, external_key) DO UPDATE
    SET title = EXCLUDED.title, source_uri = EXCLUDED.source_uri,
        content_hash = EXCLUDED.content_hash, available_at = EXCLUDED.available_at
  RETURNING evidence_id INTO v_evidence_id;
  -- rows_written counts upsert statements executed, not net-new rows
  -- (an idempotent replay re-runs both upserts and still reports 2).
  v_rows := v_rows + 1;

  -- 5. Upsert the lock_evidence detail row.
  INSERT INTO casework.lock_evidence
    (evidence_id, observation_id, incident_evidence_id, captured_at, relation_name,
     blocked_pid, blocking_pid, wait_event_type, wait_event,
     blocked_statement, blocking_statement, raw_capture)
  VALUES
    (v_evidence_id, v_external_key, v_incident_id,
     (payload #>> '{structured,captured_at}')::timestamptz,
     payload #>> '{structured,relation_name}',
     (payload #>> '{structured,blocked_pid}')::integer,
     (payload #>> '{structured,blocking_pid}')::integer,
     payload #>> '{structured,wait_event_type}',
     payload #>> '{structured,wait_event}',
     payload #>> '{structured,blocked_statement}',
     payload #>> '{structured,blocking_statement}',
     coalesce(payload #> '{structured,raw_capture}', '{}'::jsonb))
  ON CONFLICT (evidence_id) DO UPDATE
    SET captured_at = EXCLUDED.captured_at, raw_capture = EXCLUDED.raw_capture;
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
