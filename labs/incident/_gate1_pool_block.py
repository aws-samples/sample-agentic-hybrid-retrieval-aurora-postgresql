#!/usr/bin/env python3
"""Gate 1: prove all 10 API sessions block directly on the backfill while the
pool-status endpoint remains responsive. Throwaway prototype -- not shipped.
Run against a disposable _test database only.
"""
from __future__ import annotations

import concurrent.futures
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import psycopg
import psycopg_pool

from backend.app import db as app_db
from backend.app.config import get_settings


def safety_check() -> None:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        name = conn.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY ABORT: {name} does not end in _test")
    print(f"safety check passed: {name}")


def build_3m_orders(conn: psycopg.Connection) -> None:
    conn.execute("DROP SCHEMA IF EXISTS workbench_lab CASCADE")
    conn.execute("CREATE SCHEMA workbench_lab")
    conn.execute(
        """
        CREATE TABLE workbench_lab.orders (
          order_id bigint PRIMARY KEY,
          status text NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO workbench_lab.orders(order_id, status)
        SELECT value, 'created' FROM generate_series(1, 3000000) value
        """
    )
    conn.execute("ANALYZE workbench_lab.orders")


def main() -> int:
    safety_check()
    settings = get_settings()

    with psycopg.connect(settings.database_url, autocommit=True) as setup_conn:
        t0 = time.monotonic()
        build_3m_orders(setup_conn)
        print(f"bootstrap: {time.monotonic() - t0:.2f}s")

    backfill_conn = psycopg.connect(
        settings.database_url,
        autocommit=False,
        application_name="workbench-lab-backfill",
    )
    t0 = time.monotonic()
    with backfill_conn.cursor() as cur:
        cur.execute("UPDATE workbench_lab.orders SET status = 'backfilled'")
    print(f"backfill (left open): {time.monotonic() - t0:.2f}s")
    with backfill_conn.cursor() as cur:
        cur.execute("SELECT pg_backend_pid()")
        backfill_pid = cur.fetchone()[0]
    print(f"backfill PID: {backfill_pid}")

    app_db.open_pool()
    hot_ids = list(range(1, 11))

    def hot_write(order_id: int) -> tuple[str, float]:
        t0 = time.monotonic()
        try:
            with app_db.get_pool().connection(timeout=3.0) as conn:
                # The pool's connections run autocommit=True (backend/app/db.py's
                # _configure_connection) -- each bare conn.execute() is its OWN
                # implicit transaction. SET LOCAL only lasts until the CURRENT
                # transaction ends, so a bare "SET LOCAL statement_timeout" followed
                # by a separate conn.execute() call silently resets to no timeout
                # before the UPDATE runs. Discovered live: this hung the gate script
                # indefinitely with sessions stuck on Lock:Transactionid, never
                # respecting the intended 3s bound. Fix: one explicit transaction
                # block so SET LOCAL actually scopes across both statements.
                with conn.transaction():
                    conn.execute(
                        "SET LOCAL application_name = 'workbench-lab-api-hot-write'"
                    )
                    conn.execute("SET LOCAL statement_timeout = '3s'")
                    conn.execute(
                        "UPDATE workbench_lab.orders SET status = 'touched' WHERE order_id = %s",
                        (order_id,),
                    )
            return ("ok", time.monotonic() - t0)
        except psycopg_pool.PoolTimeout:
            return ("pool_timeout", time.monotonic() - t0)
        except psycopg.errors.QueryCanceled:
            return ("statement_timeout", time.monotonic() - t0)

    status_results: list[tuple[float, dict]] = []

    def poll_status_no_checkout() -> None:
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            t0 = time.monotonic()
            stats = app_db.get_pool().get_stats()
            elapsed = time.monotonic() - t0
            status_results.append((elapsed, stats))
            time.sleep(0.25)

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        status_future = pool.submit(poll_status_no_checkout)
        write_futures = [pool.submit(hot_write, oid) for oid in hot_ids]
        outcomes = [f.result() for f in write_futures]
        status_future.result()

    backfill_conn.rollback()
    backfill_conn.close()

    print()
    print("=== Hot-write outcomes (expect pool_timeout or statement_timeout, never 'ok') ===")
    all_blocked = all(status in ("pool_timeout", "statement_timeout") for status, _ in outcomes)
    for i, (status, dur) in enumerate(outcomes, 1):
        print(f"  writer {i}: {status} after {dur:.2f}s")
    print(f"ALL 10 GENUINELY BLOCKED (checkout or statement timeout): {all_blocked}")

    print()
    print("=== Pool-status responsiveness while blocked (expect all fast, low ms) ===")
    max_status_latency = max((elapsed for elapsed, _ in status_results), default=None)
    print(f"samples collected: {len(status_results)}")
    if max_status_latency is not None:
        print(f"max status-check latency: {max_status_latency:.4f}s")
    else:
        print("NO SAMPLES")
    saturated_samples = [
        s for _, s in status_results
        if s.get("pool_available", -1) == 0 and s.get("requests_waiting", 0) >= 2
    ]
    print(f"samples showing pool_available=0 and requests_waiting>=2: {len(saturated_samples)}")

    gate_passed = (
        all_blocked
        and bool(status_results)
        and max_status_latency is not None
        and max_status_latency < 0.5
        and len(saturated_samples) >= 3
    )
    print()
    print(f"GATE 1 {'PASSED' if gate_passed else 'FAILED'}")

    with psycopg.connect(settings.database_url, autocommit=True) as cleanup_conn:
        cleanup_conn.execute("DROP SCHEMA IF EXISTS workbench_lab CASCADE")
    app_db.close_pool()

    return 0 if gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
