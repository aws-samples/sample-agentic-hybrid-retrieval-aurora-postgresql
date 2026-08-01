# Admission Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `casework.admit_evidence(payload jsonb)` — a single-transaction, idempotent evidence-admission contract with an ingest receipt and a temporal `available_at` gate — as the first-class D21 takeaway artifact and the origin of the Lab 1 → 4 thread.

**Architecture:** One new SQL file (`sql/10_admission.sql`, applied after `09` and before any lab reset) adds two columns to `casework.evidence_items` (`content_hash`, `available_at`), a new `casework.ingest_receipts` table, and the `casework.admit_evidence(jsonb)` function. The function validates the payload against `admission payload v1`, upserts the typed rows (evidence header + `lock_evidence` detail) in one transaction, writes an inferred edge to the incident, queues the search-index projection, and writes one ingest receipt — idempotent by `(source_uri, content_hash)`. A thin Python promoter (`admission/promote_pg_incident.py`) turns incident-capture artifacts into a v1 payload; `admission/admit.sh` wires it to the function and prints the receipt. A JSON Schema (`admission/payload_v1.schema.json`) is the contract's published shape. Gate `gates/admission_determinism.py` (G-25) asserts the four determinism properties against a disposable database.

**Tech Stack:** PostgreSQL 18.3 + pgvector 0.8.x (Aurora), PL/pgSQL, Python 3 (psycopg 3, stdlib `json`/`hashlib` only — **no new dependency**; the SQL function is the authoritative validator), Bash, `unittest` (the repo's runner), the existing `gates/` harness (`_common.py`, exit codes PASS/FAIL/BLOCKED).

## Global Constraints

- **`casework.*` is authoritative; `retrieval.*` is derived and never hand-edited.** Admission writes only `casework.*` header/detail rows, `retrieval.inferred_edges`, and `retrieval.search_index_queue` (the projection outbox). It never writes `retrieval.documents`/`retrieval.chunks`.
- **Inferred edges are stored separately from canonical edges.** Live-capture edges go to `retrieval.inferred_edges` (method `live_session_capture`, confidence < 1.0), never to the canonical junction tables that back the read-only `retrieval.evidence_edges` VIEW.
- **Idempotent by `(source_uri, content_hash)`.** The same payload admitted twice yields identical rows and exactly one ingest receipt (byte-stable modulo timestamps). (G-25)
- **Invalid payloads are rejected loudly with the named violation and write nothing.** Fail fast; the whole function is one transaction, so a raised exception rolls back every write. (G-25)
- **Temporal gate:** retrieval as-of `t < available_at` excludes admitted rows; `t >= available_at` includes them. (G-25)
- **Zero model calls in the admission path.** No Bedrock embed/synth call in `admit_evidence` or `admit.sh`; semantic projection is queued async and nothing waits on it. (D23, G-26)
- **The word "principal" is banned from every participant-facing surface** (script output, payload field names, docs). The concept is *role*; values `workshop`, `support-lead`. (D22, G-11)
- **Never simulate an unimplemented connector or mutation.** The promoter reads real capture artifacts or a checked-in fixture; it does not fabricate incident data.
- **`.env` holds a live Aurora credential.** Never commit, log, or echo it. Gates and scripts read `DATABASE_URL` via the existing `_common.read_env_value` / `scripts/aurora_database_url.sh` path and redact before printing.
- **Gates never run DDL and never mutate a shared database.** G-25 requires a disposable database (`TEST_DATABASE_URL` + `ALLOW_TEST_DATABASE_RESET=1`); absent that, it exits BLOCKED, never PASS.
- **Do not commit** until the user asks. Commits use `shayons@amazon.com`, no Claude co-author trailer. Never push to `main`; never `--no-verify`.

## Naming reconciliations (ground-truth from the live schema — bound here, flag SPEC §4.6 for a one-word fix)

- SPEC §4.6 says admission writes "kind `lock`". The live `casework.evidence_items` CHECK constraint (`sql/01_schema.sql:23-33`) admits only `lock_evidence`. **This plan uses `lock_evidence`.** Flag: SPEC §4.6 line should read `lock_evidence`.
- `casework.lock_evidence.incident_evidence_id` is **NOT NULL** (`sql/01_schema.sql:166`). A live-captured lock therefore must reference an existing incident. The payload carries the incident's `external_key` (`INC-2047`); the function resolves it to `evidence_id`, and rejects the payload if that incident is absent.
- The SPEC's "edge to CHG-1842 as `evidence_supports` (inferred, method `live_session_capture`)" targets the writable `retrieval.inferred_edges` table (`sql/01_schema.sql:1107-1119`), not the read-only `retrieval.evidence_edges` VIEW (`sql/01_schema.sql:1121`).
- `proof.observability_refs` is PK'd `run_id -> proof.retrieval_runs(run_id)` (`sql/01_schema.sql:1312-1320`). It **cannot** be written at admission time (no retrieval run exists yet). SPEC §4.6 step 3's "`observability_refs` gets the incident window" belongs to the retrieval/PR-6 path and is **out of scope for this plan** (noted in the closing exclusions).

---
## File Structure

**Create:**
- `sql/10_admission.sql` — the schema delta + the contract function. Sections, in order: (a) `ALTER TABLE casework.evidence_items ADD COLUMN IF NOT EXISTS content_hash text` and `available_at timestamptz`; (b) `CREATE TABLE IF NOT EXISTS casework.ingest_receipts`; (c) `CREATE OR REPLACE FUNCTION casework.admit_evidence(payload jsonb) RETURNS jsonb`. One file: these change together and are the contract. Applied by `make schema` after `sql/09`.
- `admission/payload_v1.schema.json` — JSON Schema (draft 2020-12) for `admission payload v1`. The published contract shape; the authoritative validator is the SQL function, this is documentation + optional promoter-side check.
- `admission/promote_pg_incident.py` — thin adapter: reads incident-capture artifacts (or the checked-in fixture), emits a `payload v1` JSON document to stdout. Produces payloads only; never touches the database. Stdlib only.
- `admission/fixture_payload.json` — a checked-in, contract-valid `payload v1` for a `lock_evidence` observation (`LOCK-LIVE-001`) linked to `INC-2047`. Deterministic (fixed timestamps/pids) so G-25 idempotency is byte-stable.
- `admission/admit.sh` — the Lab 1 finale wiring: resolve `DATABASE_URL`, run the promoter (or read the fixture), pipe the payload into `SELECT casework.admit_evidence(:payload)`, pretty-print the returned receipt, run the exact-arm checkpoint query for the admitted key, print `OK`/remedy. Zero model calls.
- `admission/README.md` — the D21 takeaway doc: the contract, the JSONB-doorway rule, how a customer writes a `promote_*` adapter against the same entry point.
- `gates/admission_determinism.py` — G-25 gate (PASS/FAIL/BLOCKED), engine-backed against a disposable DB.
- `backend/tests/test_admission.py` — `unittest` coverage of the function's behaviors against `TEST_DATABASE_URL`.

**Modify:**
- `Makefile:17-27` — add `sql/10_admission.sql` to `SQL_FILES` (so `make schema` applies it).
- `gates/checks.sh:33-40` — add `"G-25|admission_determinism.py|Admission determinism (D21)"` to the `GATES` array.
- `sql/99_reset.sql` — add truncation of `casework.ingest_receipts` alongside the other casework tables so a reset clears admitted receipts. (Read the file first; match its existing TRUNCATE idiom.)

**Read-only reference (do not modify):**
- `sql/01_schema.sql:21-46` (evidence_items), `:163-236` (lock_evidence), `:409-416` (`casework.sha256_text`), `:858-868` (search_index_queue), `:1107-1119` (inferred_edges), `:1246` (existing queue-insert idiom).
- `gates/_common.py`, `gates/fixture_arithmetic.py` (the engine-backed gate pattern).
- `backend/scripts/smoke_test.py` (the exact-arm search idiom the admit.sh checkpoint mirrors).

## Task graph

- **Task 1** — schema delta (columns + receipts table). No dependency.
- **Task 2** — `casework.admit_evidence` function. Depends on Task 1.
- **Task 3** — payload JSON Schema + fixture. Depends on Task 2 (shape must match what the function reads).
- **Task 4** — the promoter + `admit.sh`. Depends on Tasks 2, 3.
- **Task 5** — G-25 gate. Depends on Tasks 2, 3.
- **Task 6** — wiring (Makefile, checks.sh, reset, README) + full-run verification. Depends on all.

Tasks 1–2 are the load-bearing core; 3–6 harden and wire. Each ends with an independently testable deliverable.

---

### Task 1: Schema delta — `content_hash`/`available_at` columns + `casework.ingest_receipts`

**Files:**
- Create: `sql/10_admission.sql` (this task writes sections (a) and (b) only; Task 2 appends section (c))
- Test: `backend/tests/test_admission.py` (created here with the schema-shape test)

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `casework.evidence_items.content_hash text` — the admission content hash (nullable; existing seeded rows leave it NULL).
  - `casework.evidence_items.available_at timestamptz` — the temporal gate; nullable, existing rows NULL means "always available" (preloaded corpus is not gated).
  - Partial unique index `casework.evidence_items (source_uri, content_hash) WHERE content_hash IS NOT NULL` — the idempotency key that Task 2's `ON CONFLICT` targets.
  - `casework.ingest_receipts` with columns: `ingest_id uuid PK`, `source_uri text NOT NULL`, `content_hash text NOT NULL`, `evidence_id uuid NOT NULL REFERENCES casework.evidence_items`, `external_key text NOT NULL`, `evidence_kind text NOT NULL`, `payload_hash text NOT NULL`, `rows_written integer NOT NULL`, `edges_written integer NOT NULL`, `queued integer NOT NULL`, `available_at timestamptz NOT NULL`, `admitted_at timestamptz NOT NULL DEFAULT now()`, and `UNIQUE (source_uri, content_hash)` (one receipt per admitted content).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_admission.py` (new file). This test connects to `TEST_DATABASE_URL`, applies `sql/10_admission.sql`, and asserts the schema shape exists. It is guarded to skip when no disposable DB is configured (mirrors the repo's DB-test convention).

```python
"""Admission-contract tests (D21). Require a disposable TEST_DATABASE_URL."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[2]
SQL_FILES = [
    "sql/00_extensions.sql", "sql/01_schema.sql", "sql/02_indexes.sql",
    "sql/03_search_functions.sql", "sql/09_traverse_evidence.sql",
    "sql/10_admission.sql",
]

TEST_DSN = os.environ.get("TEST_DATABASE_URL")
RESET_OK = os.environ.get("ALLOW_TEST_DATABASE_RESET") == "1"


def _apply_schema(conn) -> None:
    for rel in SQL_FILES:
        conn.execute((REPO_ROOT / rel).read_text(encoding="utf-8"))


@unittest.skipUnless(TEST_DSN and RESET_OK, "needs TEST_DATABASE_URL + ALLOW_TEST_DATABASE_RESET=1")
class AdmissionSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = psycopg.connect(TEST_DSN, autocommit=True)
        _apply_schema(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_columns_and_receipts_table_exist(self) -> None:
        cols = self.conn.execute(
            """
            SELECT column_name, is_nullable FROM information_schema.columns
            WHERE table_schema = 'casework' AND table_name = 'evidence_items'
              AND column_name IN ('content_hash', 'available_at')
            ORDER BY column_name
            """
        ).fetchall()
        self.assertEqual(cols, [("available_at", "YES"), ("content_hash", "YES")])

        receipt_cols = self.conn.execute(
            """
            SELECT count(*) FROM information_schema.columns
            WHERE table_schema = 'casework' AND table_name = 'ingest_receipts'
            """
        ).fetchone()[0]
        self.assertGreaterEqual(receipt_cols, 12)

    def test_idempotency_index_exists(self) -> None:
        idx = self.conn.execute(
            """
            SELECT indexdef FROM pg_indexes
            WHERE schemaname = 'casework' AND tablename = 'evidence_items'
              AND indexdef ILIKE '%source_uri%content_hash%'
            """
        ).fetchall()
        self.assertTrue(idx, "partial unique index on (source_uri, content_hash) missing")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `TEST_DATABASE_URL="$TEST_DATABASE_URL" ALLOW_TEST_DATABASE_RESET=1 .venv/bin/python -m unittest backend.tests.test_admission -v`
Expected: FAIL — `sql/10_admission.sql` does not exist yet (`FileNotFoundError` in `_apply_schema`). (If `TEST_DATABASE_URL` is unset, the test SKIPs; that is not a pass — set up a disposable DB before continuing. Never point this at the live Aurora in `.env`.)

- [ ] **Step 3: Write `sql/10_admission.sql` sections (a) and (b)**

```sql
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/shayons/Desktop/Workshops/sample-agentic-hybrid-retrieval-aurora-postgresql && TEST_DATABASE_URL="$TEST_DATABASE_URL" ALLOW_TEST_DATABASE_RESET=1 .venv/bin/python -m unittest backend.tests.test_admission -v`
Expected: PASS (2 tests: `test_columns_and_receipts_table_exist`, `test_idempotency_index_exists`).

- [ ] **Step 5: Commit**

```bash
git add sql/10_admission.sql backend/tests/test_admission.py
git commit -m "feat(admission): add content_hash/available_at columns and ingest_receipts table"
```

---

### Task 2: `casework.admit_evidence(payload jsonb)` — the contract function

**Files:**
- Modify: `sql/10_admission.sql` (append section (c))
- Test: `backend/tests/test_admission.py` (add behavior tests)

**Interfaces:**
- Consumes: the schema from Task 1.
- Produces: `casework.admit_evidence(payload jsonb) RETURNS jsonb`. On success returns the receipt as jsonb: `{ingest_id, source_uri, content_hash, evidence_id, external_key, evidence_kind, rows_written, edges_written, queued, available_at, admitted_at, idempotent_replay: bool}`. On a contract violation raises `EXCEPTION` with a named message and a specific SQLSTATE: `'22023'` (invalid_parameter_value) for a malformed or schema-mismatched payload, `'23503'` (foreign_key_violation) when the referenced incident does not exist; the raise rolls back the whole transaction. `available_at` is taken from `payload->>'available_at'` when present, else `now()`.

**`admission payload v1` shape (the fields the function reads):**
```
{
  "schema": "admission payload v1",          -- required, exact string
  "source": {"system": text, "uri": text,    -- uri -> source_uri; required
             "observation_window": {"start": ts, "end": ts|null}},
  "kind": "lock_evidence",                    -- required; this contract path handles lock_evidence
  "external_key": "LOCK-LIVE-001",            -- required
  "title": text,                              -- required
  "occurred_at": timestamptz,                 -- required
  "available_at": timestamptz|null,           -- optional; default now()
  "acl": {"visibility": "workshop"},          -- optional; default workshop
  "body": text,                               -- required; hashed for content_hash
  "structured": {                             -- required for lock_evidence
     "incident_external_key": "INC-2047",     -- resolved to incident evidence_id (NOT NULL FK)
     "captured_at": ts, "relation_name": text,
     "blocked_pid": int, "blocking_pid": int,
     "wait_event_type": "Lock", "wait_event": "relation",
     "blocked_statement": text, "blocking_statement": text,
     "raw_capture": {...}                     -- optional jsonb
  },
  "links": [{"to_external_key": "CHG-1842", "to_kind": "change",
             "relation": "evidence_supports", "confidence": 0.5}]  -- optional
}
```

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_admission.py`. These require the preloaded corpus (INC-2047, CHG-1842) — apply the seed in `setUp` for this class, or assert-skip if absent. Use `make seed-local` semantics against the disposable DB.

```python
import json

FIXTURE = REPO_ROOT / "admission" / "fixture_payload.json"


def _seed_incident(conn) -> None:
    """Minimal INC-2047 + CHG-1842 rows so the lock FK and link resolve.

    Kept intentionally small: the admission tests need the two referenced
    evidence rows to exist, not the full corpus.
    """
    conn.execute(
        """
        INSERT INTO casework.database_clusters (cluster_id, cluster_name, engine_version, instance_class, environment, region)
        VALUES ('orion-prod', 'orion-prod', '18.3', 'db.r8g.xlarge', 'production', 'us-east-1')
        ON CONFLICT (cluster_id) DO NOTHING
        """
    )
    for kind, key, title in [("incident", "INC-2047", "checkout lock incident"),
                             ("change", "CHG-1842", "index build change")]:
        conn.execute(
            """
            INSERT INTO casework.evidence_items
              (evidence_kind, external_key, title, source_system, source_uri, source_revision, source_updated_at)
            VALUES (%s, %s, %s, 'seed', %s, 'r1', now())
            ON CONFLICT (evidence_kind, external_key) DO NOTHING
            """,
            (kind, key, title, f"seed://{key}"),
        )
    inc = conn.execute("SELECT evidence_id FROM casework.evidence_items WHERE external_key='INC-2047'").fetchone()[0]
    conn.execute(
        """
        INSERT INTO casework.incidents (evidence_id, incident_id, cluster_id, severity, status, started_at, summary, customer_impact)
        VALUES (%s, 'INC-2047', 'orion-prod', 'SEV-2', 'resolved', now(), 's', 'i')
        ON CONFLICT (evidence_id) DO NOTHING
        """,
        (inc,),
    )


@unittest.skipUnless(TEST_DSN and RESET_OK, "needs TEST_DATABASE_URL + ALLOW_TEST_DATABASE_RESET=1")
class AdmitEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = psycopg.connect(TEST_DSN, autocommit=True)
        _apply_schema(self.conn)
        self._clean_admitted()  # isolation: methods share one physical DB
        _seed_incident(self.conn)
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def _clean_admitted(self) -> None:
        """Remove LOCK-LIVE-* rows so each test starts from a clean slate.

        Order honors the FKs: receipts and lock detail reference evidence_items
        (ON DELETE RESTRICT), so they must go before the header rows.
        """
        for tbl, col in [
            ("casework.ingest_receipts", "external_key"),
            ("casework.lock_evidence", "observation_id"),
            ("casework.evidence_items", "external_key"),
        ]:
            self.conn.execute(f"DELETE FROM {tbl} WHERE {col} LIKE 'LOCK-LIVE-%'")

    def tearDown(self) -> None:
        self.conn.close()

    def _admit(self, payload: dict):
        return self.conn.execute(
            "SELECT casework.admit_evidence(%s::jsonb)", (json.dumps(payload),)
        ).fetchone()[0]

    def test_admits_lock_evidence_and_returns_receipt(self) -> None:
        receipt = self._admit(self.payload)
        self.assertEqual(receipt["external_key"], "LOCK-LIVE-001")
        self.assertEqual(receipt["evidence_kind"], "lock_evidence")
        self.assertFalse(receipt["idempotent_replay"])
        self.assertGreaterEqual(receipt["rows_written"], 2)  # header + detail
        self.assertEqual(receipt["queued"], 1)
        row = self.conn.execute(
            "SELECT evidence_kind, available_at FROM casework.evidence_items WHERE external_key='LOCK-LIVE-001'"
        ).fetchone()
        self.assertEqual(row[0], "lock_evidence")
        self.assertIsNotNone(row[1])

    def test_second_admit_is_idempotent_one_receipt(self) -> None:
        first = self._admit(self.payload)
        second = self._admit(self.payload)
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(first["ingest_id"], second["ingest_id"])
        n_receipts = self.conn.execute(
            "SELECT count(*) FROM casework.ingest_receipts WHERE external_key='LOCK-LIVE-001'"
        ).fetchone()[0]
        self.assertEqual(n_receipts, 1)
        n_items = self.conn.execute(
            "SELECT count(*) FROM casework.evidence_items WHERE external_key='LOCK-LIVE-001'"
        ).fetchone()[0]
        self.assertEqual(n_items, 1)

    def test_invalid_schema_string_rejected_and_writes_nothing(self) -> None:
        bad = dict(self.payload, schema="wrong")
        with self.assertRaises(psycopg.errors.Error):
            self._admit(bad)
        n = self.conn.execute(
            "SELECT count(*) FROM casework.evidence_items WHERE external_key='LOCK-LIVE-001'"
        ).fetchone()[0]
        self.assertEqual(n, 0, "rejected payload must write nothing")

    def test_missing_incident_rejected(self) -> None:
        self.conn.execute("DELETE FROM casework.incidents")
        self.conn.execute("DELETE FROM casework.evidence_items WHERE external_key='INC-2047'")
        with self.assertRaises(psycopg.errors.Error):
            self._admit(self.payload)

    def test_temporal_gate(self) -> None:
        receipt = self._admit(self.payload)
        avail = receipt["available_at"]
        before = self.conn.execute(
            "SELECT count(*) FROM casework.evidence_items WHERE external_key='LOCK-LIVE-001' AND available_at <= %s",
            ("2000-01-01T00:00:00+00:00",),
        ).fetchone()[0]
        self.assertEqual(before, 0, "row must be excluded as-of a time before available_at")
        after = self.conn.execute(
            "SELECT count(*) FROM casework.evidence_items WHERE external_key='LOCK-LIVE-001' AND available_at <= %s",
            (avail,),
        ).fetchone()[0]
        self.assertEqual(after, 1, "row must be included as-of available_at")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `TEST_DATABASE_URL="$TEST_DATABASE_URL" ALLOW_TEST_DATABASE_RESET=1 .venv/bin/python -m unittest backend.tests.test_admission.AdmitEvidenceTest -v`
Expected: FAIL — `function casework.admit_evidence(jsonb) does not exist` (and `FileNotFoundError` for the fixture until Task 3; to unblock this task's TDD, hand-write a minimal `admission/fixture_payload.json` now and let Task 3 finalize it — or run only after Task 3. The recommended order is 2 then 3; if a fixture is needed here, create the stub in Step 3 below).

- [ ] **Step 3: Append section (c) to `sql/10_admission.sql`**

```sql
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
    IF v_link_target IS NOT NULL THEN
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/shayons/Desktop/Workshops/sample-agentic-hybrid-retrieval-aurora-postgresql && TEST_DATABASE_URL="$TEST_DATABASE_URL" ALLOW_TEST_DATABASE_RESET=1 .venv/bin/python -m unittest backend.tests.test_admission.AdmitEvidenceTest -v`
Expected: PASS (5 tests). If `test_admits...` fails on `queued`, confirm the payload's link resolves; if `test_missing_incident...` fails, confirm the ERRCODE surfaces as `psycopg.errors.Error`.

- [ ] **Step 5: Break the code, confirm the test catches it**

Temporarily change the idempotency lookup to always miss (comment out the `IF FOUND THEN RETURN`), re-run: `test_second_admit_is_idempotent_one_receipt` must FAIL (two receipts). Restore.

- [ ] **Step 6: Commit**

```bash
git add sql/10_admission.sql backend/tests/test_admission.py
git commit -m "feat(admission): add casework.admit_evidence single-transaction contract"
```

---

### Task 3: `admission payload v1` schema + fixture

**Files:**
- Create: `admission/payload_v1.schema.json`, `admission/fixture_payload.json`
- Test: `backend/tests/test_admission.py` (add a fixture-validity test)

**Interfaces:**
- Consumes: the field shape the function reads (Task 2).
- Produces: `admission/fixture_payload.json` — the deterministic `LOCK-LIVE-001` payload used by Task 2's tests, `admit.sh`, and the G-25 gate. `admission/payload_v1.schema.json` — the published contract shape.

- [ ] **Step 1: Write `admission/fixture_payload.json`**

```json
{
  "schema": "admission payload v1",
  "source": {
    "system": "pg_incident_capture",
    "uri": "workshop://live/fixture-session/lock/1",
    "observation_window": {"start": "2026-07-28T14:00:00+00:00", "end": "2026-07-28T14:03:00+00:00"}
  },
  "kind": "lock_evidence",
  "external_key": "LOCK-LIVE-001",
  "title": "Blocked writer on shop.orders during index build",
  "occurred_at": "2026-07-28T14:01:30+00:00",
  "available_at": "2026-07-28T14:03:00+00:00",
  "acl": {"visibility": "workshop"},
  "body": "AccessExclusiveLock on shop.orders held by CREATE INDEX; writer pid 20919 blocked waiting on relation lock.",
  "structured": {
    "incident_external_key": "INC-2047",
    "captured_at": "2026-07-28T14:01:30+00:00",
    "relation_name": "shop.orders",
    "blocked_pid": 20919,
    "blocking_pid": 20044,
    "wait_event_type": "Lock",
    "wait_event": "relation",
    "blocked_statement": "INSERT INTO shop.orders (customer_id, total) VALUES ($1, $2)",
    "blocking_statement": "CREATE INDEX idx_orders_customer ON shop.orders (customer_id)",
    "raw_capture": {"blocking_pids": [20044]}
  },
  "links": [
    {"to_external_key": "CHG-1842", "to_kind": "change", "relation": "evidence_supports", "confidence": 0.5}
  ]
}
```

- [ ] **Step 2: Write `admission/payload_v1.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://verity.workshop/admission/payload_v1.schema.json",
  "title": "admission payload v1",
  "type": "object",
  "required": ["schema", "source", "kind", "external_key", "title", "occurred_at", "body", "structured"],
  "properties": {
    "schema": {"const": "admission payload v1"},
    "source": {
      "type": "object",
      "required": ["system", "uri"],
      "properties": {
        "system": {"type": "string"},
        "uri": {"type": "string"},
        "observation_window": {
          "type": "object",
          "properties": {"start": {"type": "string"}, "end": {"type": ["string", "null"]}}
        }
      }
    },
    "kind": {"const": "lock_evidence"},
    "external_key": {"type": "string"},
    "title": {"type": "string"},
    "occurred_at": {"type": "string"},
    "available_at": {"type": ["string", "null"]},
    "acl": {"type": "object"},
    "body": {"type": "string"},
    "structured": {
      "type": "object",
      "required": ["incident_external_key", "captured_at", "relation_name",
                   "blocked_pid", "blocking_pid", "wait_event_type", "wait_event",
                   "blocked_statement", "blocking_statement"],
      "properties": {
        "incident_external_key": {"type": "string"},
        "wait_event_type": {"const": "Lock"},
        "wait_event": {"const": "relation"},
        "blocked_pid": {"type": "integer"},
        "blocking_pid": {"type": "integer"}
      }
    },
    "links": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["to_external_key", "to_kind", "relation"],
        "properties": {
          "to_external_key": {"type": "string"}, "to_kind": {"type": "string"},
          "relation": {"type": "string"}, "confidence": {"type": "number"}
        }
      }
    }
  }
}
```

- [ ] **Step 3: Add the fixture-validity test**

```python
class FixtureContractTest(unittest.TestCase):
    def test_fixture_has_required_top_level_fields(self) -> None:
        p = json.loads((REPO_ROOT / "admission" / "fixture_payload.json").read_text())
        for field in ["schema", "source", "kind", "external_key", "title", "occurred_at", "body", "structured"]:
            self.assertIn(field, p)
        self.assertEqual(p["schema"], "admission payload v1")
        self.assertEqual(p["kind"], "lock_evidence")
        self.assertEqual(p["structured"]["incident_external_key"], "INC-2047")
```

This test needs no database, so it runs unconditionally.

- [ ] **Step 4: Run**

Run: `.venv/bin/python -m unittest backend.tests.test_admission.FixtureContractTest -v`
Expected: PASS. Then re-run `AdmitEvidenceTest` (Task 2) now that the real fixture exists — all 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add admission/payload_v1.schema.json admission/fixture_payload.json backend/tests/test_admission.py
git commit -m "feat(admission): add payload v1 schema and deterministic lock fixture"
```

---

### Task 4: `promote_pg_incident.py` promoter + `admit.sh`

**Files:**
- Create: `admission/promote_pg_incident.py`, `admission/admit.sh`, `admission/README.md`

**Interfaces:**
- Consumes: the fixture/schema (Task 3), the function (Task 2).
- Produces: `promote_pg_incident.py` writes a `payload v1` JSON to stdout. `admit.sh` admits it and prints the receipt + runs the exact-arm checkpoint.

- [ ] **Step 1: Write `admission/promote_pg_incident.py`**

Reads incident-capture artifacts from a directory (`--capture-dir`, default `/run/verity`) if present; otherwise falls back to the checked-in fixture (`--fixture`, default `admission/fixture_payload.json`). Emits a `payload v1` document. Stdlib only; never touches the DB; never fabricates a capture (falls back to the labeled fixture and says so on stderr).

```python
#!/usr/bin/env python3
"""Promote a captured pg incident into an `admission payload v1` document.

Thin adapter (D21/D19): reads capture artifacts and emits a payload on stdout.
Produces payloads only — it never connects to a database. When no live capture
is present it emits the checked-in fixture and says so on stderr; it never
fabricates incident data.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = REPO_ROOT / "admission" / "fixture_payload.json"


def build_payload(capture_dir: Path, fixture: Path) -> dict:
    capture = capture_dir / "lock_capture.json"
    if capture.is_file():
        raw = json.loads(capture.read_text(encoding="utf-8"))
        return _payload_from_capture(raw)
    print(f"promote_pg_incident: no capture at {capture}; using fixture {fixture}", file=sys.stderr)
    return json.loads(fixture.read_text(encoding="utf-8"))


def _payload_from_capture(raw: dict) -> dict:
    """Map a raw lock-capture record to admission payload v1."""
    s = raw["structured"] if "structured" in raw else raw
    return {
        "schema": "admission payload v1",
        "source": {"system": "pg_incident_capture", "uri": raw["source_uri"],
                   "observation_window": raw.get("observation_window", {})},
        "kind": "lock_evidence",
        "external_key": raw["external_key"],
        "title": raw["title"],
        "occurred_at": raw["occurred_at"],
        "available_at": raw.get("available_at"),
        "acl": raw.get("acl", {"visibility": "workshop"}),
        "body": raw["body"],
        "structured": s,
        "links": raw.get("links", []),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Emit an admission payload v1 on stdout.")
    ap.add_argument("--capture-dir", type=Path, default=Path("/run/verity"))
    ap.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    args = ap.parse_args()
    payload = build_payload(args.capture_dir, args.fixture)
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Write `admission/admit.sh`**

Requires `DATABASE_URL` to be set in the environment (the `: "${DATABASE_URL:?...}"` guard in the code below; `scripts/aurora_database_url.sh` is a Secrets-Manager minting helper for a different flow, not a `.env` reader, so `admit.sh` does not source it), runs the promoter, pipes the payload into the function using psql's parameterized read, prints the receipt, and runs the exact-arm checkpoint. No model calls.

```bash
#!/usr/bin/env bash
# admit.sh — Lab 1 finale: promote a captured incident into the record (D23).
# Zero model calls. Prints the ingest receipt and the exact-arm checkpoint.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${DATABASE_URL:?set DATABASE_URL or add it to .env}"

payload="$(.venv/bin/python admission/promote_pg_incident.py "$@")"

# Admit inside a single statement; the function is itself one transaction.
# Piped via stdin (not -c): psql only substitutes :'var' inside SQL read from
# a script/stdin, not inside a -c command string. ON_ERROR_STOP=1 makes a RAISE
# in admit_evidence exit nonzero so set -e aborts before the checkpoint.
receipt="$(psql "$DATABASE_URL" -X -q -t -A -v ON_ERROR_STOP=1 -v payload="$payload" <<'SQL'
SELECT jsonb_pretty(casework.admit_evidence(:'payload'::jsonb));
SQL
)"

echo "── ingest receipt ─────────────────────────────"
echo "$receipt"

key="$(printf '%s' "$payload" | .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["external_key"])')"

echo "── exact-arm checkpoint ───────────────────────"
# Parameterized :'key' (not string-interpolated) — the reference template
# adapter authors copy, so it must not interpolate an id into SQL text.
hit="$(psql "$DATABASE_URL" -X -q -t -A -v ON_ERROR_STOP=1 -v key="$key" <<'SQL'
SELECT external_key FROM casework.evidence_items
 WHERE external_key = :'key' AND available_at <= now();
SQL
)"
if [ "$hit" = "$key" ]; then
  echo "OK: ${key} is retrievable by the exact arm immediately"
else
  echo "REMEDY: ${key} not visible as-of now(); check available_at and that admit succeeded" >&2
  exit 1
fi
```

Make it executable: `chmod +x admission/admit.sh`.

- [ ] **Step 3: Write `admission/README.md`**

Document: the contract (`casework.admit_evidence(payload jsonb)`), the `payload v1` shape (link to the schema file), the JSONB-doorway rule ("anything an arm filters on or a join touches is a real column, not a jsonb field"), idempotency by `(source_uri, content_hash)`, the temporal `available_at` gate, and a "write your own `promote_*` adapter" section pointing at `promote_pg_incident.py` as the reference. State plainly: zero model calls; semantic projection is queued async.

- [ ] **Step 4: Verify end-to-end against the disposable DB**

Run (disposable DB, seeded with INC-2047/CHG-1842):
```bash
DATABASE_URL="$TEST_DATABASE_URL" ./admission/admit.sh
DATABASE_URL="$TEST_DATABASE_URL" ./admission/admit.sh   # second run: idempotent
```
Expected: first run prints a receipt with `"idempotent_replay": false` then `OK`; second prints `"idempotent_replay": true`, same `ingest_id`, then `OK`.

- [ ] **Step 5: Commit**

```bash
git add admission/promote_pg_incident.py admission/admit.sh admission/README.md
git commit -m "feat(admission): add promoter, admit.sh finale, and D21 contract README"
```

---

### Task 5: `gates/admission_determinism.py` — G-25

**Files:**
- Create: `gates/admission_determinism.py`

**Interfaces:**
- Consumes: the function + fixture (Tasks 2, 3), `gates/_common.py` helpers.
- Produces: a standalone gate script exiting PASS/FAIL/BLOCKED.

**Note — this gate writes, unlike the others.** G-25 must admit evidence twice, so it cannot run read-only against the shared/live `DATABASE_URL`. It requires `TEST_DATABASE_URL` + `ALLOW_TEST_DATABASE_RESET=1` (a disposable DB); absent either, it exits **BLOCKED** and never touches a database. It applies the schema itself and cleans up its own admitted rows.

- [ ] **Step 1: Write the gate**

```python
#!/usr/bin/env python3
"""G-25 - Admission determinism (D21).

Asserts the four contract properties against a DISPOSABLE database:
  1. Idempotent: the same payload admitted twice -> identical rows, one receipt.
  2. Rejection: a contract-invalid payload writes nothing (one transaction).
  3. Temporal gate: as-of t < available_at excludes; >= includes.
  4. Zero model calls: admit_evidence issues no Bedrock call (structural — the
     function body is pure SQL; asserted by inspection here, enforced by G-26).

Unlike other gates this one WRITES, so it refuses to run against the shared
DATABASE_URL: it requires TEST_DATABASE_URL + ALLOW_TEST_DATABASE_RESET=1 and
exits BLOCKED otherwise. It applies the schema and admits into a disposable DB.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    BLOCKED, FAIL, PASS, finish, main_guard, print_header, redact_dsn, require,
)

GATE_ID = "G-25"
TITLE = "Admission determinism (D21)"
REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "admission" / "fixture_payload.json"
SCHEMA_FILES = [
    "sql/00_extensions.sql", "sql/01_schema.sql", "sql/02_indexes.sql",
    "sql/03_search_functions.sql", "sql/09_traverse_evidence.sql",
    "sql/10_admission.sql",
]


def _seed_incident(conn) -> None:
    conn.execute(
        "INSERT INTO casework.database_clusters (cluster_id, cluster_name, engine_version, instance_class, environment, region)"
        " VALUES ('orion-prod','orion-prod','18.3','db.r8g.xlarge','production','us-east-1') ON CONFLICT DO NOTHING"
    )
    for kind, key in [("incident", "INC-2047"), ("change", "CHG-1842")]:
        conn.execute(
            "INSERT INTO casework.evidence_items (evidence_kind, external_key, title, source_system, source_uri, source_revision, source_updated_at)"
            " VALUES (%s,%s,%s,'seed',%s,'r1',now()) ON CONFLICT DO NOTHING",
            (kind, key, key, f"seed://{key}"),
        )
    inc = conn.execute("SELECT evidence_id FROM casework.evidence_items WHERE external_key='INC-2047'").fetchone()[0]
    conn.execute(
        "INSERT INTO casework.incidents (evidence_id, incident_id, cluster_id, severity, status, started_at, summary, customer_impact)"
        " VALUES (%s,'INC-2047','orion-prod','SEV-2','resolved',now(),'s','i') ON CONFLICT DO NOTHING",
        (inc,),
    )


def run() -> int:
    print_header(GATE_ID, TITLE)

    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn or os.environ.get("ALLOW_TEST_DATABASE_RESET") != "1":
        return finish(GATE_ID, BLOCKED,
                      "needs TEST_DATABASE_URL + ALLOW_TEST_DATABASE_RESET=1 (this gate writes)")
    if not FIXTURE.is_file():
        return finish(GATE_ID, BLOCKED, "admission/fixture_payload.json not built yet")

    try:
        import psycopg
    except ImportError:
        return finish(GATE_ID, BLOCKED, "psycopg not importable")

    print(f"  engine: {redact_dsn(dsn)}")
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            for rel in SCHEMA_FILES:
                conn.execute((REPO_ROOT / rel).read_text(encoding="utf-8"))
            conn.execute("DELETE FROM casework.ingest_receipts WHERE external_key='LOCK-LIVE-001'")
            conn.execute("DELETE FROM casework.lock_evidence WHERE observation_id='LOCK-LIVE-001'")
            conn.execute("DELETE FROM casework.evidence_items WHERE external_key='LOCK-LIVE-001'")
            _seed_incident(conn)

            def admit(p) -> dict:
                return conn.execute("SELECT casework.admit_evidence(%s::jsonb)", (json.dumps(p),)).fetchone()[0]

            # 1. Idempotency.
            r1 = admit(payload)
            r2 = admit(payload)
            require(r1["idempotent_replay"] is False, "first admit must not be a replay")
            require(r2["idempotent_replay"] is True, "second admit must be an idempotent replay")
            require(r1["ingest_id"] == r2["ingest_id"], "replay must return the same ingest_id")
            n = conn.execute("SELECT count(*) FROM casework.ingest_receipts WHERE external_key='LOCK-LIVE-001'").fetchone()[0]
            require(n == 1, f"exactly one receipt expected, got {n}")

            # 2. Rejection writes nothing.
            conn.execute("DELETE FROM casework.ingest_receipts WHERE external_key='LOCK-LIVE-002'")
            bad = dict(payload, schema="wrong", external_key="LOCK-LIVE-002",
                       source={**payload["source"], "uri": "workshop://live/x/lock/2"})
            try:
                admit(bad)
                require(False, "invalid payload must raise")
            except psycopg.errors.Error:
                pass
            leaked = conn.execute("SELECT count(*) FROM casework.evidence_items WHERE external_key='LOCK-LIVE-002'").fetchone()[0]
            require(leaked == 0, "rejected payload must write nothing")

            # 3. Temporal gate.
            avail = r1["available_at"]
            excluded = conn.execute(
                "SELECT count(*) FROM casework.evidence_items WHERE external_key='LOCK-LIVE-001' AND available_at <= %s",
                ("2000-01-01T00:00:00+00:00",)).fetchone()[0]
            require(excluded == 0, "row must be excluded as-of before available_at")
            included = conn.execute(
                "SELECT count(*) FROM casework.evidence_items WHERE external_key='LOCK-LIVE-001' AND available_at <= %s",
                (avail,)).fetchone()[0]
            require(included == 1, "row must be included as-of available_at")

            # cleanup
            conn.execute("DELETE FROM casework.ingest_receipts WHERE external_key IN ('LOCK-LIVE-001','LOCK-LIVE-002')")
            conn.execute("DELETE FROM casework.lock_evidence WHERE observation_id='LOCK-LIVE-001'")
            conn.execute("DELETE FROM casework.evidence_items WHERE external_key='LOCK-LIVE-001'")
    except psycopg.OperationalError as exc:
        return finish(GATE_ID, BLOCKED, f"cannot reach the disposable engine: {exc}")

    return finish(GATE_ID, PASS,
                  "idempotent (1 receipt), invalid rejected (0 rows), temporal gate holds")


if __name__ == "__main__":
    main_guard(run)
```

- [ ] **Step 2: Run the gate against the disposable DB**

Run: `TEST_DATABASE_URL="$TEST_DATABASE_URL" ALLOW_TEST_DATABASE_RESET=1 .venv/bin/python gates/admission_determinism.py`
Expected: `[PASS] G-25: idempotent (1 receipt), invalid rejected (0 rows), temporal gate holds`.

- [ ] **Step 3: Confirm the safe default (no disposable DB) is BLOCKED, not a live write**

Run: `.venv/bin/python gates/admission_determinism.py` (with no `TEST_DATABASE_URL`)
Expected: `[BLOCKED] G-25: needs TEST_DATABASE_URL + ALLOW_TEST_DATABASE_RESET=1 (this gate writes)`. Confirm nothing connected to the live `DATABASE_URL`.

- [ ] **Step 4: Commit**

```bash
git add gates/admission_determinism.py
git commit -m "feat(admission): add G-25 admission-determinism gate"
```

---

### Task 6: Wire it in (Makefile, checks.sh, reset) + full-run verification

**Files:**
- Modify: `Makefile:17-27`, `gates/checks.sh:33-40`, `sql/99_reset.sql`

**Interfaces:**
- Consumes: everything above.
- Produces: `make schema` applies `sql/10_admission.sql`; `gates/checks.sh` runs G-25; `sql/99_reset.sql` clears receipts.

- [ ] **Step 1: Add the SQL file to `SQL_FILES`**

In `Makefile`, append to the `SQL_FILES` list (after `sql/09_traverse_evidence.sql`):

```makefile
	sql/09_traverse_evidence.sql \
	sql/10_admission.sql
```

(Remove the trailing backslash from the `09` line's replacement — the last entry has no continuation.)

- [ ] **Step 2: Register G-25 in the gate orchestrator**

In `gates/checks.sh`, add to the `GATES=(...)` array (build-order: after G-23):

```bash
  "G-23|route_contract.py|Route contract (D16)"
  "G-25|admission_determinism.py|Admission determinism (D21)"
```

- [ ] **Step 3: Clear receipts on reset**

Read `sql/99_reset.sql` first. Add `casework.ingest_receipts` to its TRUNCATE list, matching the existing idiom and CASCADE/ordering (receipts reference `evidence_items`, so truncate receipts before or with `CASCADE`).

- [ ] **Step 4: Full-run verification**

```bash
# schema applies the new file cleanly against the disposable DB
DATABASE_URL="$TEST_DATABASE_URL" make schema
# the full admission test module is green
TEST_DATABASE_URL="$TEST_DATABASE_URL" ALLOW_TEST_DATABASE_RESET=1 .venv/bin/python -m unittest backend.tests.test_admission -v
# the gate harness runs G-25 (and does not regress the others)
TEST_DATABASE_URL="$TEST_DATABASE_URL" ALLOW_TEST_DATABASE_RESET=1 gates/checks.sh
# admit.sh end-to-end
DATABASE_URL="$TEST_DATABASE_URL" ./admission/admit.sh
```
Expected: `make schema` exits 0; all admission tests PASS; `gates/checks.sh` SUMMARY shows G-25 in PASS and no new FAIL; `admit.sh` prints a receipt then `OK`.

- [ ] **Step 5: Commit**

```bash
git add Makefile gates/checks.sh sql/99_reset.sql
git commit -m "chore(admission): wire sql/10 into make schema, register G-25, reset receipts"
```

---

## Out of scope for this plan (deferred, with reason)

- **`proof.observability_refs` write at admission** — its PK requires a `run_id` from `proof.retrieval_runs`, which does not exist until a retrieval run. SPEC §4.6 step 3 belongs to the retrieval/PR-6 path. (Correct the SPEC to attach the window at first retrieval, not at admit.)
- **Semantic projection execution** — admission only *queues* `retrieval.search_index_queue`. The embed/index worker (`backend/app/search_index.py`) is existing machinery; wiring the async drain and the `LIVE`-badge projection status is a separate task (touches the frontend and the index builder).
- **The flagged answer-citation half (`VERITY_LIVE_CAPTURE=1`, D7)** — Lab 4 citation of `LOCK-LIVE-*`. Depends on projection completing; deferred with the projection worker.
- **G-26 (admission-beat timing, ≤60s, zero model calls end-to-end)** — a runtime/timing gate over `admit.sh` on a clean environment; belongs with the Lab 1 incident-harness plan (plan 4 of 5) where the capture artifacts and the timer live.
- **Live capture artifacts (`/run/verity`, `capture/capture_incident.sh`)** — produced by the Lab 1 incident harness (plan 4 of 5); this plan's promoter reads them if present and falls back to the fixture otherwise.
- **The four other subsystems** — RLS backstop (G-27), the three holes + reset + golden generator (G-28), the Lab 1 incident harness (G-6/G-26), Lab 4 replay + takeaway skill (D18/G-24) — each gets its own plan.

## Spec coverage (self-review)

- D21 admission contract → Tasks 1–4 (function, receipt, idempotency, JSONB-doorway in README).
- G-25 determinism → Task 5 (all three engine-backed properties) + the four `test_admission` behaviors.
- D23 zero-model-calls / async projection → Task 2 (pure-SQL function, queue-only) + admit.sh (no Bedrock).
- D22 no "principal" → payload uses `acl.visibility`/role vocabulary only; README avoids the word.
- Temporal `available_at` gate → Task 1 column + Task 2 logic + Task 5 property 3 + `test_temporal_gate`.
- Invariants (casework authoritative, inferred edges separate, one model space) → Global Constraints + Task 2 writes only inferred_edges/queue.
