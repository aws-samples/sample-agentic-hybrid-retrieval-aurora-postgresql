"""Phase 1 of the incident: an unbatched backfill held open in one transaction.

The ADD COLUMN commits separately on purpose. A transaction spanning both the
DDL and backfill retains AccessExclusiveLock for the backfill's full duration,
so hot writers block on Lock:relation instead of Lock:transactionid.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import psycopg


def add_priority_tier_column(conn: psycopg.Connection) -> None:
    """Add the nullable migration column and release its DDL lock immediately."""
    conn.execute("ALTER TABLE workbench_lab.orders ADD COLUMN priority_tier int")
    conn.commit()


@dataclass
class BackfillHandle:
    """Own the intentionally open transaction until recovery commits or aborts it."""

    pid: int
    duration_seconds: float
    rows_updated: int
    _conn: psycopg.Connection = field(repr=False)

    def commit(self) -> None:
        try:
            self._conn.commit()
        finally:
            self._conn.close()

    def abort(self) -> None:
        try:
            self._conn.rollback()
        finally:
            self._conn.close()


def open_backfill(database_url: str) -> BackfillHandle:
    """Update all orders and retain the transaction so its row locks survive.

    The caller owns the returned handle and must call ``commit()`` or
    ``abort()``. The server-side idle-transaction timeout recovers an abandoned
    backfill if the orchestrator exits unexpectedly.
    """
    connection = psycopg.connect(
        database_url,
        autocommit=False,
        application_name="workbench-lab-backfill",
    )
    try:
        connection.execute("SET idle_in_transaction_session_timeout = '3min'")
        connection.execute("SET statement_timeout = '3min'")
        pid = connection.execute("SELECT pg_backend_pid()").fetchone()[0]
        started = time.monotonic()
        cursor = connection.execute(
            "UPDATE workbench_lab.orders "
            "SET priority_tier = (order_id % 5) + 1"
        )
        return BackfillHandle(
            pid=pid,
            duration_seconds=time.monotonic() - started,
            rows_updated=cursor.rowcount,
            _conn=connection,
        )
    except BaseException:
        connection.close()
        raise
