#!/usr/bin/env python3
"""G-25 - Admission determinism (D21).

Asserts the four contract properties against a DISPOSABLE database:
  1. Idempotent: the same payload admitted twice -> identical rows, one receipt.
  2. Rejection: a contract-invalid payload writes nothing (one transaction).
  3. Temporal gate: as-of t < available_at excludes; >= includes.
  4. Zero model calls: admit_evidence issues no Bedrock call (structural - the
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
        "INSERT INTO casework.database_clusters"
        " (cluster_id, engine, engine_version, aws_region, environment,"
        "  service_name, writer_endpoint_alias)"
        " VALUES ('orion-prod','aurora-postgresql','18.3','us-east-1',"
        "'production','orion','orion-writer') ON CONFLICT DO NOTHING"
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


def _clean_lock_live(conn) -> None:
    """Remove all LOCK-LIVE-* admission rows in FK-safe order.

    Every FK into casework.evidence_items is ON DELETE RESTRICT, so the two
    derived tables admit_evidence writes (retrieval.search_index_queue and
    retrieval.inferred_edges) plus lock_evidence and ingest_receipts must be
    cleared before the evidence header. Used at both the pre-seed and the
    post-run sites so they cannot diverge.
    """
    ids = [r[0] for r in conn.execute(
        "SELECT evidence_id FROM casework.evidence_items WHERE external_key LIKE 'LOCK-LIVE-%'").fetchall()]
    if ids:
        conn.execute("DELETE FROM retrieval.search_index_queue WHERE evidence_id = ANY(%s)", (ids,))
        conn.execute(
            "DELETE FROM retrieval.inferred_edges WHERE from_evidence_id = ANY(%s) OR to_evidence_id = ANY(%s)",
            (ids, ids))
    conn.execute("DELETE FROM casework.ingest_receipts WHERE external_key LIKE 'LOCK-LIVE-%'")
    conn.execute("DELETE FROM casework.lock_evidence WHERE observation_id LIKE 'LOCK-LIVE-%'")
    conn.execute("DELETE FROM casework.evidence_items WHERE external_key LIKE 'LOCK-LIVE-%'")


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
            _clean_lock_live(conn)
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

            # cleanup (FK-safe; same helper as pre-seed)
            _clean_lock_live(conn)
    except psycopg.OperationalError as exc:
        return finish(GATE_ID, BLOCKED, f"cannot reach the disposable engine: {exc}")

    return finish(GATE_ID, PASS,
                  "idempotent (1 receipt), invalid rejected (0 rows), temporal gate holds")


if __name__ == "__main__":
    main_guard(run)
