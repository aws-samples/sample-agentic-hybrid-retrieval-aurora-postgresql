"""Pooled connections: replace an expired idle connection, restore settings, and
read a function that an apply recreated."""

from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from scripts import lab_state
from service import db
from service.config import get_settings
from service.search_sql import FUSED_FUNCTION


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


@pytest.mark.aurora
def test_lab_1_state_reads_a_function_another_session_recreated(monkeypatch):
    """Every apply drops and recreates the fused function under a new OID.

    The apply runs on its own connection. The API's pooled connections prepare a
    statement after its fifth run (`prepare_threshold=0` prepares at once) and never
    see the apply's DROP, the command that makes psycopg discard its prepared
    statements. A `'...'::regprocedure` literal is an OID fixed when the statement is
    planned, so on 14 November 2026 the prepared read returned NULL after an apply and
    `GET /api/labs/state` answered 500. The stand-in function lives in a scratch
    schema that is dropped at the end.
    """
    database_url = get_settings().database_url
    schema = f"lab1_state_witness_{uuid4().hex[:8]}"
    function = f"{schema}.{FUSED_FUNCTION}"
    create = f"CREATE FUNCTION {function} RETURNS integer LANGUAGE sql AS 'SELECT 1'"
    monkeypatch.setattr(lab_state, "search_schema", lambda: schema)
    with psycopg.connect(database_url, autocommit=True, connect_timeout=10) as applier:
        applier.execute(f"CREATE SCHEMA {schema}")
        try:
            applier.execute(create)
            with psycopg.connect(
                database_url,
                row_factory=dict_row,
                prepare_threshold=0,
                autocommit=True,
                connect_timeout=10,
            ) as reader:
                before = lab_state._lab_1_database_state(reader, lab_state.REPO)
                applier.execute(f"DROP FUNCTION {function}")
                applier.execute(create)
                after = lab_state._lab_1_database_state(reader, lab_state.REPO)
        finally:
            applier.execute(f"DROP SCHEMA {schema} CASCADE")

    assert "Aurora has no" not in before.detail, before.detail
    assert after == before, (
        "the read after another session recreated the function must find the new "
        f"one, as the read before found the old; got {after.detail!r}"
    )
