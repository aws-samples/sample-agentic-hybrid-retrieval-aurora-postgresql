from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import time
from typing import Any

import psycopg
from psycopg.rows import dict_row


CAPTURE_FORMAT_VERSION = "1.0"
CAPTURE_TOOL_VERSION = "verity-lock-capture-v1"
FIXTURE_SCHEMA = "verity_capture"
FIXTURE_TABLE = "orders"
FIXTURE_RELATION = f"{FIXTURE_SCHEMA}.{FIXTURE_TABLE}"
INDEX_NAME = "idx_orders_customer_created"
INDEX_SQL = (
    f"CREATE INDEX {INDEX_NAME} "
    f"ON {FIXTURE_RELATION} (customer_id, created_at DESC)"
)
WRITER_SQL = (
    f"UPDATE {FIXTURE_RELATION} "
    "SET status = %s, updated_at = clock_timestamp() "
    "WHERE order_id = %s"
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _server_version(version_num: int) -> str:
    major = version_num // 10_000
    minor = version_num % 100
    return f"{major}.{minor}"


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _bundle_digest(bundle: dict[str, Any]) -> str:
    unsigned = json.loads(json.dumps(bundle, default=str))
    unsigned["capture"].pop("source_bundle_sha256", None)
    unsigned["capture"].pop("release_verified_at", None)
    encoded = json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _statement_sample(cursor, phase: str) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT
          queryid,
          query,
          calls,
          total_exec_time,
          mean_exec_time,
          rows
        FROM pg_stat_statements
        WHERE dbid = (
          SELECT oid
          FROM pg_database
          WHERE datname = current_database()
        )
          AND query ILIKE 'UPDATE verity_capture.orders SET status%%'
        ORDER BY calls DESC, queryid
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(
            "pg_stat_statements did not record the controlled writer statement"
        )
    return {
        "phase": phase,
        "captured_at": _utc_now(),
        **row,
        "raw_row": row,
    }


def _run_writer(database_url: str, application_name: str, order_id: int) -> None:
    with psycopg.connect(
        database_url,
        autocommit=True,
        application_name=application_name,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = '30s'")
            cursor.execute(WRITER_SQL, ("queued", order_id))


def _wait_for_blocked_writers(
    cursor,
    writer_names: list[str],
    *,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        cursor.execute(
            """
            SELECT
              pid,
              backend_type,
              application_name,
              state,
              wait_event_type,
              wait_event,
              query_start,
              xact_start,
              query
            FROM pg_stat_activity
            WHERE application_name = ANY(%s)
              AND state = 'active'
              AND wait_event_type = 'Lock'
              AND lower(wait_event) = 'relation'
            ORDER BY application_name
            """,
            (writer_names,),
        )
        rows = cursor.fetchall()
        if len(rows) == len(writer_names):
            return rows
        time.sleep(0.05)
    raise RuntimeError("writers did not enter Lock:relation wait before timeout")


def validate_capture_bundle(
    bundle: dict[str, Any],
    *,
    require_release: bool = False,
) -> None:
    if bundle.get("format_version") != CAPTURE_FORMAT_VERSION:
        raise ValueError("unsupported capture bundle format")

    capture = bundle.get("capture")
    if not isinstance(capture, dict):
        raise ValueError("capture bundle is missing capture metadata")
    mode = capture.get("capture_mode")
    if mode not in {"offline_test", "release_aurora"}:
        raise ValueError(f"unsupported capture mode: {mode}")
    if require_release and mode != "release_aurora":
        raise ValueError("release evidence requires a release_aurora capture")

    relation_oid = capture.get("relation_oid")
    observations = bundle.get("observations") or []
    if len(observations) < 2:
        raise ValueError("capture must contain at least two blocked-writer observations")

    for observation in observations:
        if observation.get("relation_oid") != relation_oid:
            raise ValueError("observation relation OID does not match capture metadata")
        if observation.get("blocked_state") != "active":
            raise ValueError("blocked writer must be active")
        if (
            observation.get("wait_event_type") != "Lock"
            or str(observation.get("wait_event", "")).lower() != "relation"
        ):
            raise ValueError("blocked writer must wait on Lock:relation")
        if (
            observation.get("blocked_lock_mode") != "RowExclusiveLock"
            or observation.get("blocked_lock_granted") is not False
        ):
            raise ValueError("blocked writer must have an ungranted RowExclusiveLock")
        if (
            observation.get("blocking_lock_mode") != "ShareLock"
            or observation.get("blocking_lock_granted") is not True
        ):
            raise ValueError("blocker must have a granted ShareLock")
        if observation.get("blocking_pid") not in observation.get("blocking_pids", []):
            raise ValueError("pg_blocking_pids output does not identify the blocker")

    phases = {
        sample.get("phase")
        for sample in bundle.get("pg_stat_statements", [])
    }
    if phases != {"before", "during", "after"}:
        raise ValueError("pg_stat_statements must include before, during, and after")

    expected_digest = capture.get("source_bundle_sha256")
    if expected_digest and expected_digest != _bundle_digest(bundle):
        raise ValueError("capture bundle digest does not match its contents")

    if mode == "release_aurora":
        if not capture.get("release_verified_at"):
            raise ValueError("release capture is missing release_verified_at")
        if not capture.get("manifest", {}).get("signature"):
            raise ValueError("release capture is missing its detached signature metadata")
        metric_names = {
            sample.get("metric_name")
            for sample in bundle.get("cloudwatch_metrics", [])
        }
        required_metrics = {
            "WriteLatency",
            "WriteIOPS",
            "DMLThroughput",
            "DDLThroughput",
            "DatabaseConnections",
        }
        if not required_metrics.issubset(metric_names):
            raise ValueError("release capture is missing required CloudWatch metrics")
        if not any(
            sample.get("evidence_type") == "top_wait"
            and sample.get("dimension_value") == "Lock:relation"
            for sample in bundle.get("database_insights", [])
        ):
            raise ValueError("release capture does not contain Lock:relation Top Waits")


def capture_offline_lock_fixture(
    database_url: str,
    *,
    row_count: int = 25_000,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    if row_count < 1_000:
        raise ValueError("row_count must be at least 1000")

    capture_started = _utc_now()
    writer_names = ["verity-offline-writer-1", "verity-offline-writer-2"]
    blocker = None
    pool = ThreadPoolExecutor(max_workers=len(writer_names))
    futures = []

    try:
        with psycopg.connect(
            database_url,
            autocommit=True,
            row_factory=dict_row,
            application_name="verity-offline-capture",
        ) as control:
            with control.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT count(*) AS connections
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                    """
                )
                steady_state_connections = int(
                    cursor.fetchone()["connections"]
                )
                cursor.execute(
                    f"DROP SCHEMA IF EXISTS {FIXTURE_SCHEMA} CASCADE"
                )
                cursor.execute(f"CREATE SCHEMA {FIXTURE_SCHEMA}")
                cursor.execute(
                    f"""
                    CREATE TABLE {FIXTURE_RELATION} (
                      order_id bigint PRIMARY KEY,
                      customer_id bigint NOT NULL,
                      status text NOT NULL,
                      created_at timestamptz NOT NULL,
                      updated_at timestamptz NOT NULL
                    )
                    """
                )
                cursor.execute(
                    f"""
                    INSERT INTO {FIXTURE_RELATION}(
                      order_id,
                      customer_id,
                      status,
                      created_at,
                      updated_at
                    )
                    SELECT
                      value,
                      1 + (value %% 5000),
                      'created',
                      clock_timestamp() - ((value %% 86400) * interval '1 second'),
                      clock_timestamp()
                    FROM generate_series(1, %s) AS value
                    """,
                    (row_count,),
                )
                cursor.execute(
                    WRITER_SQL,
                    ("baseline", row_count),
                )
                cursor.execute(
                    """
                    SELECT
                      %s::regclass::oid AS relation_oid,
                      count(*) AS observed_row_count,
                      pg_total_relation_size(%s::regclass) AS table_size_bytes
                    FROM verity_capture.orders
                    """,
                    (FIXTURE_RELATION, FIXTURE_RELATION),
                )
                profile = cursor.fetchone()
                before_stats = _statement_sample(cursor, "before")

            blocker = psycopg.connect(
                database_url,
                row_factory=dict_row,
                application_name="verity-offline-index-build",
            )
            with blocker.cursor() as blocker_cursor:
                blocker_cursor.execute(INDEX_SQL)
                blocker_pid = blocker.info.backend_pid

            for offset, writer_name in enumerate(writer_names, start=1):
                futures.append(
                    pool.submit(
                        _run_writer,
                        database_url,
                        writer_name,
                        offset,
                    )
                )

            with control.cursor() as cursor:
                blocked = _wait_for_blocked_writers(
                    cursor,
                    writer_names,
                    timeout_seconds=timeout_seconds,
                )
                blocked_pids = [int(row["pid"]) for row in blocked]
                all_pids = [blocker_pid, *blocked_pids]

                cursor.execute(
                    """
                    SELECT
                      pid,
                      backend_type,
                      application_name,
                      state,
                      wait_event_type,
                      wait_event,
                      query_start,
                      xact_start,
                      query
                    FROM pg_stat_activity
                    WHERE pid = ANY(%s)
                    ORDER BY pid
                    """,
                    (all_pids,),
                )
                activity_rows = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT
                      lock.pid,
                      lock.locktype,
                      lock.database AS database_oid,
                      lock.relation AS relation_oid,
                      namespace.nspname || '.' || relation.relname AS relation_name,
                      lock.mode,
                      lock.granted,
                      lock.fastpath,
                      lock.waitstart
                    FROM pg_locks lock
                    JOIN pg_class relation ON relation.oid = lock.relation
                    JOIN pg_namespace namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE lock.relation = %s
                      AND lock.pid = ANY(%s)
                    ORDER BY lock.pid, lock.mode
                    """,
                    (profile["relation_oid"], all_pids),
                )
                lock_rows = cursor.fetchall()

                blocking_rows: list[dict[str, Any]] = []
                for blocked_pid in blocked_pids:
                    literal_sql = f"SELECT pg_blocking_pids({blocked_pid});"
                    cursor.execute(
                        "SELECT pg_blocking_pids(%s) AS blocking_pids",
                        (blocked_pid,),
                    )
                    pids = list(cursor.fetchone()["blocking_pids"])
                    blocking_rows.append(
                        {
                            "captured_at": _utc_now(),
                            "blocked_pid": blocked_pid,
                            "blocking_pids": pids,
                            "literal_sql": literal_sql,
                            "literal_output": "{" + ",".join(map(str, pids)) + "}",
                            "raw_row": {"pg_blocking_pids": pids},
                        }
                    )

                during_stats = _statement_sample(cursor, "during")

            blocker.commit()
            blocker.close()
            blocker = None
            for future in futures:
                future.result(timeout=timeout_seconds)

            with control.cursor() as cursor:
                after_stats = _statement_sample(cursor, "after")

            activity_by_pid = {
                int(row["pid"]): row for row in activity_rows
            }
            locks_by_pid = {
                int(row["pid"]): row
                for row in lock_rows
                if row["relation_oid"] == profile["relation_oid"]
            }
            blocker_lock = next(
                row
                for row in lock_rows
                if int(row["pid"]) == blocker_pid
                and row["mode"] == "ShareLock"
                and row["granted"]
            )
            observations: list[dict[str, Any]] = []
            blocking_by_pid = {
                row["blocked_pid"]: row for row in blocking_rows
            }
            for ordinal, blocked_pid in enumerate(blocked_pids):
                activity = activity_by_pid[blocked_pid]
                waiting_lock = next(
                    row
                    for row in lock_rows
                    if int(row["pid"]) == blocked_pid
                    and row["mode"] == "RowExclusiveLock"
                    and not row["granted"]
                )
                blockers = blocking_by_pid[blocked_pid]
                observations.append(
                    {
                        "external_key": f"LOCK-2047-{ordinal + 1:03d}",
                        "captured_at": blockers["captured_at"],
                        "relation_name": FIXTURE_RELATION,
                        "relation_oid": profile["relation_oid"],
                        "blocked_pid": blocked_pid,
                        "blocking_pid": blocker_pid,
                        "blocked_state": activity["state"],
                        "blocked_query_start": activity["query_start"],
                        "wait_event_type": activity["wait_event_type"],
                        "wait_event": str(activity["wait_event"]).lower(),
                        "blocked_lock_mode": waiting_lock["mode"],
                        "blocked_lock_granted": waiting_lock["granted"],
                        "blocking_lock_mode": blocker_lock["mode"],
                        "blocking_lock_granted": blocker_lock["granted"],
                        "blocking_pids": blockers["blocking_pids"],
                        "blocking_pids_sql": blockers["literal_sql"],
                        "blocking_pids_output": blockers["literal_output"],
                        "blocked_statement": activity["query"],
                        "blocking_statement": INDEX_SQL,
                        "raw_capture": {
                            "activity": activity,
                            "waiting_lock": waiting_lock,
                            "blocking_lock": blocker_lock,
                        },
                    }
                )

            capture_ended = _utc_now()
            bundle: dict[str, Any] = {
                "format_version": CAPTURE_FORMAT_VERSION,
                "capture": {
                    "capture_key": (
                        "CAP-OFFLINE-"
                        + capture_started.strftime("%Y%m%dT%H%M%SZ")
                    ),
                    "capture_mode": "offline_test",
                    "engine_version": _server_version(control.info.server_version),
                    "instance_class": "unverified",
                    "database_name": control.info.dbname,
                    "table_schema": FIXTURE_SCHEMA,
                    "table_name": FIXTURE_TABLE,
                    "relation_oid": profile["relation_oid"],
                    "configured_row_count": row_count,
                    "observed_row_count": profile["observed_row_count"],
                    "table_size_bytes": profile["table_size_bytes"],
                    "steady_state_connections": steady_state_connections,
                    "capture_started_at": capture_started,
                    "capture_ended_at": capture_ended,
                    "capture_tool_version": CAPTURE_TOOL_VERSION,
                    "source_bundle_uri": None,
                    "release_verified_at": None,
                    "manifest": {
                        "capture_method": "post_build_transaction_hold",
                        "release_evidence": False,
                        "note": (
                            "Genuine non-release PostgreSQL lock-catalog capture. "
                            "It does not satisfy the Aurora release gate."
                        ),
                    },
                },
                "observations": observations,
                "pg_stat_activity": [
                    {
                        "captured_at": capture_ended,
                        **row,
                        "raw_row": row,
                    }
                    for row in activity_rows
                ],
                "pg_locks": [
                    {
                        "captured_at": capture_ended,
                        **row,
                        "raw_row": row,
                    }
                    for row in lock_rows
                ],
                "pg_blocking_pids": blocking_rows,
                "pg_stat_statements": [
                    before_stats,
                    during_stats,
                    after_stats,
                ],
                "cloudwatch_metrics": [],
                "database_insights": [],
            }
            bundle = _json_safe(bundle)
            bundle["capture"]["source_bundle_sha256"] = _bundle_digest(bundle)
            validate_capture_bundle(bundle)
            return bundle
    finally:
        if blocker is not None:
            try:
                blocker.rollback()
            finally:
                blocker.close()
        pool.shutdown(wait=True, cancel_futures=True)
        try:
            with psycopg.connect(database_url, autocommit=True) as cleanup:
                cleanup.execute(
                    f"DROP SCHEMA IF EXISTS {FIXTURE_SCHEMA} CASCADE"
                )
        except Exception:
            pass
