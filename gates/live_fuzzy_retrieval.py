#!/usr/bin/env python3
"""G-21 - Fuzzy recovery against the participant-generated live corpus."""
from __future__ import annotations

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
    read_env_value,
    redact_dsn,
)

GATE_ID = "G-21"
TITLE = "Run-derived fuzzy retrieval on the target engine"


def run() -> int:
    print_header(GATE_ID, TITLE)
    dsn = read_env_value("DATABASE_URL")
    expected_capture = os.environ.get("LIVE_CAPTURE_RUN_ID")
    if not dsn or not expected_capture:
        return finish(
            GATE_ID,
            BLOCKED,
            "needs DATABASE_URL + LIVE_CAPTURE_RUN_ID from this live run",
        )

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        return finish(GATE_ID, BLOCKED, "psycopg is not importable")

    print(f"  engine: {redact_dsn(dsn)}")
    try:
        with psycopg.connect(
            dsn,
            autocommit=True,
            row_factory=dict_row,
            options="-c default_transaction_read_only=on",
        ) as connection:
            capture = connection.execute(
                """
                SELECT
                  capture_id::text AS capture_id,
                  upper(right(replace(capture_id::text, '-', ''), 8))
                    AS run_suffix
                FROM casework.incident_capture_runs
                WHERE capture_origin = 'participant_induced'
                ORDER BY capture_started_at DESC
                LIMIT 1
                """
            ).fetchone()
            if not capture:
                return finish(
                    GATE_ID,
                    BLOCKED,
                    "no participant-induced live capture is loaded",
                )
            if capture["capture_id"] != expected_capture:
                return finish(
                    GATE_ID,
                    FAIL,
                    (
                        f"latest capture {capture['capture_id']} does not match "
                        f"LIVE_CAPTURE_RUN_ID {expected_capture}"
                    ),
                )
            target = f"CHG-{capture['run_suffix']}-01"
            probe = f"CGH-{capture['run_suffix']}-01"
            rows = connection.execute(
                """
                SELECT external_key, source_system, score
                FROM retrieval.fuzzy_search(
                  ARRAY[%s],
                  p_source_systems => ARRAY['pg_incident_capture'],
                  p_limit => 5
                )
                """,
                (probe,),
            ).fetchall()
    except psycopg.OperationalError as error:
        return finish(GATE_ID, BLOCKED, f"cannot reach the engine: {error}")

    if not rows:
        return finish(GATE_ID, FAIL, f"{probe} returned no fuzzy candidates")
    if rows[0]["external_key"] != target:
        return finish(
            GATE_ID,
            FAIL,
            f"{probe} ranked {rows[0]['external_key']} ahead of {target}",
        )
    if any(row["source_system"] != "pg_incident_capture" for row in rows):
        return finish(
            GATE_ID,
            FAIL,
            "fuzzy retrieval returned evidence outside the participant run",
        )
    return finish(
        GATE_ID,
        PASS,
        f"{probe} recovered {target} at rank 1 from the current live corpus",
    )


if __name__ == "__main__":
    main_guard(run)
