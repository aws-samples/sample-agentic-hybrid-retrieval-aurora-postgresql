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
