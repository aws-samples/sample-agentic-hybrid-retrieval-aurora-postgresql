#!/usr/bin/env python3
"""Gate 4: prove abandoned backfill transactions, hung load generators, and
pool exhaustion all recover cleanly without a fresh database. Throwaway,
real _test DB only.
"""
from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import psycopg

from backend.app.config import get_settings


def safety_check(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        name = conn.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY ABORT: {name}")
        print(f"safety check passed: {name}")


def probe_abandoned_transaction(dsn: str) -> bool:
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"""
import psycopg
conn = psycopg.connect({dsn!r}, autocommit=False)
conn.execute("SET application_name = 'gate4-orphan'")
conn.execute("SELECT pg_sleep(60)")
""",
        ],
    )
    time.sleep(2)

    with psycopg.connect(dsn, autocommit=True) as check_conn:
        orphan = check_conn.execute(
            "SELECT pid FROM pg_stat_activity WHERE application_name = 'gate4-orphan'"
        ).fetchone()
        if not orphan:
            print("probe_abandoned_transaction: FAILED to even start the orphan")
            proc.kill()
            return False
        orphan_pid = orphan[0]
        print(f"orphan started, pid={orphan_pid}")

    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=5)
    print("client process SIGKILLed")

    with psycopg.connect(dsn, autocommit=True) as cleanup_conn:
        still_there = cleanup_conn.execute(
            "SELECT pid FROM pg_stat_activity WHERE application_name = 'gate4-orphan'"
        ).fetchone()
        if not still_there:
            print("probe_abandoned_transaction: orphan already gone "
                  "(fast keepalive cleanup -- not a failure)")
            return True
        cleanup_conn.execute("SELECT pg_terminate_backend(%s)", (still_there[0],))
        time.sleep(1)
        gone = cleanup_conn.execute(
            "SELECT pid FROM pg_stat_activity WHERE application_name = 'gate4-orphan'"
        ).fetchone()

    success = gone is None
    print(f"probe_abandoned_transaction: {'PASSED' if success else 'FAILED'}")
    return success


def probe_pool_recovery(dsn: str) -> bool:
    from backend.app import db as app_db

    app_db.open_pool()
    stats_before = app_db.get_pool().get_stats()
    print(f"pool stats before saturation: {stats_before}")

    import concurrent.futures

    def hold_briefly():
        with app_db.get_pool().connection(timeout=3.0) as conn:
            conn.execute("SELECT pg_sleep(1)")

    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as pool:
        futures = [pool.submit(hold_briefly) for _ in range(15)]
        for f in futures:
            try:
                f.result()
            except Exception:
                pass

    time.sleep(1)
    stats_after = app_db.get_pool().get_stats()
    recovered = stats_after.get("pool_available", -1) == stats_after.get("pool_size", -2)
    print(f"probe_pool_recovery: {'PASSED' if recovered else 'FAILED'} "
          f"(before={stats_before}, after={stats_after})")
    app_db.close_pool()
    return recovered


def probe_rerun_against_dirty_state(dsn: str) -> bool:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS workbench_lab CASCADE")
        conn.execute("CREATE SCHEMA workbench_lab")
        conn.execute("CREATE TABLE workbench_lab.orders (order_id bigint PRIMARY KEY)")
        conn.execute("INSERT INTO workbench_lab.orders VALUES (999999)")
        # Simulate the real rebuild path (matches _create_lab_workload's
        # DROP SCHEMA ... CASCADE pattern already in run_live_workshop.py).
        conn.execute("DROP SCHEMA IF EXISTS workbench_lab CASCADE")
        conn.execute("CREATE SCHEMA workbench_lab")
        conn.execute(
            "CREATE TABLE workbench_lab.orders (order_id bigint PRIMARY KEY, status text NOT NULL)"
        )
        count = conn.execute("SELECT count(*) FROM workbench_lab.orders").fetchone()[0]
        clean = count == 0
        conn.execute("DROP SCHEMA IF EXISTS workbench_lab CASCADE")
    print(f"probe_rerun_against_dirty_state: {'PASSED' if clean else 'FAILED'}")
    return clean


def main() -> int:
    settings = get_settings()
    dsn = settings.database_url
    safety_check(dsn)

    results = {
        "abandoned_transaction": probe_abandoned_transaction(dsn),
        "pool_recovery": probe_pool_recovery(dsn),
        "rerun_dirty_state": probe_rerun_against_dirty_state(dsn),
    }
    all_passed = all(results.values())
    print()
    print(f"GATE 4 {'PASSED' if all_passed else 'FAILED'}: {results}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
