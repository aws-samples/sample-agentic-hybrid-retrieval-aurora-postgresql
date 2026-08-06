#!/usr/bin/env python3
"""G-25 - Replay one participant-generated live bundle on a disposable database."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    BLOCKED,
    FAIL,
    PASS,
    finish,
    main_guard,
    print_header,
    redact_dsn,
    require,
)

GATE_ID = "G-25"
TITLE = "Participant bundle admission determinism"
REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILES = [
    "sql/00_extensions.sql",
    "sql/01_schema.sql",
    "sql/02_indexes.sql",
    "sql/03_search_functions.sql",
    "sql/09_traverse_evidence.sql",
    "sql/10_admission.sql",
]


def run() -> int:
    print_header(GATE_ID, TITLE)
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn or os.environ.get("ALLOW_TEST_DATABASE_RESET") != "1":
        return finish(
            GATE_ID,
            BLOCKED,
            "needs TEST_DATABASE_URL + ALLOW_TEST_DATABASE_RESET=1",
        )
    payload_value = os.environ.get("LIVE_CAPTURE_PAYLOAD")
    capture_id = os.environ.get("LIVE_CAPTURE_RUN_ID")
    if not payload_value or not capture_id:
        return finish(
            GATE_ID,
            BLOCKED,
            "needs LIVE_CAPTURE_PAYLOAD + LIVE_CAPTURE_RUN_ID from this live run",
        )
    payload_path = Path(payload_value)
    if not payload_path.is_file():
        return finish(
            GATE_ID,
            BLOCKED,
            f"live payload does not exist: {payload_path}",
        )

    try:
        import psycopg
    except ImportError:
        return finish(GATE_ID, BLOCKED, "psycopg not importable")

    print(f"  engine: {redact_dsn(dsn)}")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    bundle_uri = payload.get("source", {}).get("uri")
    if not bundle_uri:
        return finish(GATE_ID, FAIL, "live payload has no source.uri")
    if payload.get("capture", {}).get("capture_id") != capture_id:
        return finish(
            GATE_ID,
            FAIL,
            "LIVE_CAPTURE_PAYLOAD does not match LIVE_CAPTURE_RUN_ID",
        )
    try:
        with psycopg.connect(dsn, autocommit=True) as connection:
            target_identity = connection.execute(
                """
                SELECT current_database(),
                       inet_server_addr()::text,
                       inet_server_port()
                """
            ).fetchone()
            database_name = target_identity[0]
            if isinstance(database_name, bytes):
                database_name = database_name.decode()
            if not database_name.endswith("_test"):
                return finish(
                    GATE_ID,
                    FAIL,
                    f"refusing writes to {database_name!r}; name must end in _test",
                )

            live_dsn = os.environ.get("DATABASE_URL")
            if live_dsn:
                with psycopg.connect(live_dsn, autocommit=True) as live_connection:
                    live_identity = live_connection.execute(
                        """
                        SELECT current_database(),
                               inet_server_addr()::text,
                               inet_server_port()
                        """
                    ).fetchone()
                if target_identity == live_identity:
                    return finish(
                        GATE_ID,
                        FAIL,
                        (
                            "TEST_DATABASE_URL resolves to DATABASE_URL; G-25 "
                            "would erase the rehearsal corpus"
                        ),
                    )

            connection.execute(
                (REPO_ROOT / "sql/99_reset.sql").read_text(encoding="utf-8")
            )
            for relative_path in SCHEMA_FILES:
                connection.execute(
                    (REPO_ROOT / relative_path).read_text(encoding="utf-8")
                )

            def admit(value: dict) -> dict:
                return connection.execute(
                    "SELECT casework.admit_evidence(%s::jsonb)",
                    (json.dumps(value),),
                ).fetchone()[0]

            first = admit(payload)
            second = admit(payload)
            require(not first["idempotent_replay"], "first admission is new")
            require(second["idempotent_replay"], "second admission is replay")
            require(
                first["ingest_id"] == second["ingest_id"],
                "replay returns the same receipt",
            )
            records = payload["records"]
            queued = (
                int(isinstance(records.get("incident"), dict))
                + len(records.get("changes", []))
                + int(isinstance(records.get("lock_evidence"), dict))
                + len(records.get("telemetry_documents", []))
            )
            require(
                first["queued"] == queued,
                "every live searchable document is queued",
            )
            require(
                connection.execute(
                    """
                    SELECT count(*)
                    FROM casework.evidence_items
                    WHERE source_uri LIKE %s || '/%%'
                    """,
                    (bundle_uri,),
                ).fetchone()[0]
                == queued,
                "only this wave's live evidence records are admitted",
            )
            receipts = connection.execute(
                """
                SELECT count(*)
                FROM casework.ingest_receipts
                WHERE source_uri = %s
                """,
                (bundle_uri,),
            ).fetchone()[0]
            require(
                receipts == 1,
                f"expected one receipt for {bundle_uri}, found {receipts}",
            )

            invalid = json.loads(json.dumps(payload))
            if payload.get("wave", "A") == "A":
                invalid["records"]["lock_evidence"]["structured"][
                    "blocking_lock_mode"
                ] = "AccessExclusiveLock"
                invalid_description = "invalid measured lock mode"
            else:
                invalid["records"]["changes"][0]["structured"][
                    "relationship"
                ] = "confirmed"
                invalid_description = "invalid Wave B validation relationship"
            try:
                admit(invalid)
                require(False, f"{invalid_description} must raise")
            except psycopg.errors.Error:
                pass
            require(
                connection.execute(
                    """
                    SELECT count(*)
                    FROM casework.evidence_items
                    WHERE source_uri LIKE %s || '/%%'
                    """,
                    (bundle_uri,),
                ).fetchone()[0]
                == queued,
                "rejected revision writes no partial rows",
            )
    except psycopg.OperationalError as error:
        return finish(
            GATE_ID,
            BLOCKED,
            f"cannot reach disposable engine: {error}",
        )

    return finish(
        GATE_ID,
        PASS,
        (
            f"{queued} live-run records atomic, replay idempotent, "
            "invalid bundle rolled back"
        ),
    )


if __name__ == "__main__":
    main_guard(run)
