"""Replace an expired idle connection before beginning the next request."""

import psycopg
import pytest

from service import db
from service.config import get_settings


@pytest.mark.aurora
def test_pool_replaces_a_server_closed_idle_connection():
    db.close_pool()
    try:
        with db.connect() as connection:
            old_pid = connection.execute("SELECT pg_backend_pid() AS pid").fetchone()[
                "pid"
            ]
        # Terminate only the session just opened by this test. The client still
        # appears idle until it tries to use the socket again.
        with psycopg.connect(
            get_settings().database_url, connect_timeout=10
        ) as control:
            assert control.execute(
                "SELECT pg_terminate_backend(%s,5000)", (old_pid,)
            ).fetchone()[0]
        with db.connect() as replacement:
            row = replacement.execute(
                "SELECT pg_backend_pid() AS pid, 42 AS answer"
            ).fetchone()
            assert row["pid"] != old_pid
            assert row["answer"] == 42
            replacement.execute(
                "CREATE TEMP TABLE pool_recovery_witness (value int) ON COMMIT DROP"
            )
            replacement.execute("INSERT INTO pool_recovery_witness VALUES (42)")
            assert (
                replacement.execute(
                    "SELECT value FROM pool_recovery_witness"
                ).fetchone()["value"]
                == 42
            )
    finally:
        db.close_pool()


@pytest.mark.aurora
def test_statement_deadline_rolls_back_and_reused_connection_restores_settings():
    db.close_pool()
    try:
        with db.get_pool().connection() as connection:
            baseline = connection.execute(
                "SELECT pg_backend_pid() AS pid, current_setting('statement_timeout') AS statement, "
                "current_setting('lock_timeout') AS lock"
            ).fetchone()
        with (
            pytest.raises(psycopg.errors.QueryCanceled),
            db.connect(statement_timeout_ms=50, lock_timeout_ms=40) as connection,
        ):
            assert (
                connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
                == baseline["pid"]
            )
            connection.execute("SELECT pg_sleep(0.2)")
        with db.get_pool().connection() as connection:
            restored = connection.execute(
                "SELECT pg_backend_pid() AS pid, current_setting('statement_timeout') AS statement, "
                "current_setting('lock_timeout') AS lock"
            ).fetchone()
            assert restored == baseline
            assert connection.execute("SELECT 42 AS value").fetchone()["value"] == 42
    finally:
        db.close_pool()
