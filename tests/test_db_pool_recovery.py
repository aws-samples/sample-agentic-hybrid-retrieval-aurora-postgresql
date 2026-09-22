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
