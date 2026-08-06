#!/usr/bin/env python3
"""Run, capture, admit, and index one participant-induced Aurora incident."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from threading import Barrier, BrokenBarrierError
import time
from typing import Any, Callable, Sequence
import uuid

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import requests
from botocore.exceptions import BotoCoreError, ClientError

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.lab_routes import HotWriteResult  # noqa: E402
from labs.incident.capture_observability import (  # noqa: E402
    collect_aws_observability,
    preflight_aws_observability,
    _write_atomic,
)
from labs.incident.evidence_builder import (  # noqa: E402
    EvidenceDocument,
    build_wave_a_documents,
    build_wave_b_documents,
)
from labs.incident.hold_controller import (  # noqa: E402
    HoldProof,
    LiveWorkshopError,
    prove_hold,
)
from labs.incident.migration import (  # noqa: E402
    add_priority_tier_column,
    open_backfill,
)
from labs.incident.recovery_verifier import (  # noqa: E402
    RecoveryProof,
    verify_recovery,
)
from labs.incident.query_regression import (  # noqa: E402
    PlanCheckpoint,
    RECOMMENDED_INDEX_NAME,
    capture_plan_checkpoints,
)


LAB_CUSTOMER_ROWS = 5_000
LAB_ROWS = 3_000_000
SOURCE_SYSTEM = "pg_incident_capture"
RELATION_NAME = "workbench_lab.orders"
INDEX_NAME = RECOMMENDED_INDEX_NAME
HOT_WRITE_APPLICATION_NAME = "workbench-lab-api-hot-write"
BACKFILL_APPLICATION_NAME = "workbench-lab-backfill"
LAB_SCHEMA_OWNER = "workbench_lab_owner"
LAB_WRITER_ROLE = "workshop_app"
LAB_CATALOG_REVALIDATION_ROLES = (
    "persona_app_engineer",
    "persona_dba",
    "persona_auditor",
)
EXERCISE_TEMPLATE_DIR = REPO_ROOT / "labs" / "exercises"
WAVE_A_EXERCISE_TEMPLATES = (
    "lab2-sql-retrieval.sql",
    "lab2-filter-request.json",
    "lab2-fusion-request.json",
    "lab3-plan-request.json",
    "lab3-traverse-request.json",
    "lab3-compare-request.json",
)
UNRESOLVED_EXERCISE_PLACEHOLDER = re.compile(
    r"\{\{[A-Z_]+\}\}|REPLACE_WITH_[A-Z_]+"
)


def _connect(
    database_url: str,
    application_name: str,
    *,
    autocommit: bool,
) -> psycopg.Connection:
    return psycopg.connect(
        database_url,
        autocommit=autocommit,
        row_factory=dict_row,
        application_name=application_name,
    )


def _statement_stats(connection: psycopg.Connection, phase: str) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT
          %s::text AS phase,
          clock_timestamp() AS captured_at,
          coalesce(sum(statement.calls), 0)::bigint AS calls,
          coalesce(sum(statement.total_exec_time), 0)::double precision
            AS total_exec_time,
          coalesce(sum(statement.rows), 0)::bigint AS rows,
          coalesce(
            jsonb_agg(statement.queryid ORDER BY statement.queryid)
              FILTER (WHERE statement.queryid IS NOT NULL),
            '[]'::jsonb
          ) AS queryids,
          coalesce(
            jsonb_agg(statement.query ORDER BY statement.queryid)
              FILTER (WHERE statement.query IS NOT NULL),
            '[]'::jsonb
          ) AS queries
        FROM pg_stat_statements statement
        WHERE statement.dbid = (
          SELECT oid
          FROM pg_database
          WHERE datname = current_database()
        )
          AND statement.query ~*
            '^[[:space:]]*UPDATE[[:space:]]+workbench_lab[.]orders'
        """,
        (phase,),
    ).fetchone()
    if row is None:
        raise LiveWorkshopError(f"could not capture pg_stat_statements {phase}")
    sample = dict(row)
    captured_at = sample.get("captured_at")
    if isinstance(captured_at, datetime):
        sample["captured_at"] = captured_at.isoformat()
    elif captured_at is not None:
        sample["captured_at"] = str(captured_at)
    return sample


def _assert_no_live_lab_sessions(connection: psycopg.Connection) -> None:
    stale = connection.execute(
        """
        SELECT array_agg(application_name ORDER BY application_name) AS names
        FROM pg_stat_activity
        WHERE pid <> pg_backend_pid()
          AND datname = current_database()
          AND application_name LIKE 'workbench-live-%'
        """
    ).fetchone()["names"]
    if stale:
        raise LiveWorkshopError(
            "close stale workbench-live-* sessions before starting: "
            + ", ".join(stale)
        )


def _assert_empty_evidence_store(connection: psycopg.Connection) -> None:
    existing = connection.execute(
        """
        SELECT count(*) AS records
        FROM evidence.evidence_items
        WHERE NOT is_deleted
        """
    ).fetchone()["records"]
    if existing:
        raise LiveWorkshopError(
            "the participant corpus is not empty; use a fresh workshop "
            "database so this run cannot mix with prior evidence"
        )


def _create_lab_tables(connection: psycopg.Connection) -> None:
    """Create the disposable lab tables as the current effective owner."""
    connection.execute(
        """
        CREATE TABLE workbench_lab.customers (
          customer_id bigint PRIMARY KEY,
          customer_ref text NOT NULL UNIQUE,
          created_at timestamptz NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO workbench_lab.customers(
          customer_id,
          customer_ref,
          created_at
        )
        SELECT
          value,
          'CUST-' || lpad(value::text, 5, '0'),
          clock_timestamp() - ((value %% 86400) * interval '1 second')
        FROM generate_series(1, %s) value
        """,
        (LAB_CUSTOMER_ROWS,),
    )
    connection.execute(
        """
        CREATE TABLE workbench_lab.orders (
          order_id bigint PRIMARY KEY,
          customer_id bigint NOT NULL
            REFERENCES workbench_lab.customers(customer_id),
          status text NOT NULL,
          created_at timestamptz NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO workbench_lab.orders(
          order_id,
          customer_id,
          status,
          created_at
        )
        SELECT
          value,
          1 + ((value - 1) %% %s),
          'created',
          clock_timestamp() - ((value %% 86400) * interval '1 second')
        FROM generate_series(1, %s) value
        """,
        (LAB_CUSTOMER_ROWS, LAB_ROWS),
    )
    connection.execute("ANALYZE workbench_lab.customers")
    connection.execute("ANALYZE workbench_lab.orders")


def _grant_lab_writes(connection: psycopg.Connection) -> None:
    """Grant the pool DML and personas catalog visibility after each rebuild.

    This runs after the tables are recreated because DROP SCHEMA ... CASCADE
    removes object grants. The pool deliberately receives no membership in
    workbench_lab_owner: hot writes need DML, while Lab 4 reserves DDL for the
    participant. Persona-scoped agent requests only receive schema USAGE so
    they can revalidate a proposal against PostgreSQL's catalog; they receive
    neither workload-row DML nor DDL.
    """
    writer = sql.Identifier(LAB_WRITER_ROLE)
    connection.execute(
        sql.SQL("GRANT USAGE ON SCHEMA workbench_lab TO {}").format(writer)
    )
    catalog_roles = sql.SQL(", ").join(
        sql.Identifier(role) for role in LAB_CATALOG_REVALIDATION_ROLES
    )
    connection.execute(
        sql.SQL("GRANT USAGE ON SCHEMA workbench_lab TO {}").format(catalog_roles)
    )
    connection.execute(
        sql.SQL(
            "GRANT SELECT, INSERT, UPDATE, DELETE "
            "ON ALL TABLES IN SCHEMA workbench_lab TO {}"
        ).format(writer)
    )
    connection.execute(
        sql.SQL(
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA workbench_lab TO {}"
        ).format(writer)
    )


def _create_lab_workload(connection: psycopg.Connection) -> None:
    """Rebuild the operational substrate without adding participant evidence."""
    connection.execute("DROP SCHEMA IF EXISTS workbench_lab CASCADE")
    owner_present = bool(
        connection.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s) AS present",
            (LAB_SCHEMA_OWNER,),
        ).fetchone()["present"]
    )
    if not owner_present:
        connection.execute("CREATE SCHEMA workbench_lab")
        _create_lab_tables(connection)
        return

    connection.execute(
        sql.SQL("CREATE SCHEMA workbench_lab AUTHORIZATION {}").format(
            sql.Identifier(LAB_SCHEMA_OWNER)
        )
    )
    connection.execute(
        sql.SQL("SET ROLE {}").format(sql.Identifier(LAB_SCHEMA_OWNER))
    )
    try:
        _create_lab_tables(connection)
        _grant_lab_writes(connection)
    finally:
        connection.execute("RESET ROLE")


def _lab_workload_state(
    connection: psycopg.Connection,
) -> dict[str, Any] | None:
    relations = connection.execute(
        """
        SELECT
          to_regclass('workbench_lab.customers') IS NOT NULL AS customers_exist,
          to_regclass(%s) IS NOT NULL AS orders_exist
        """,
        (RELATION_NAME,),
    ).fetchone()
    if not relations["customers_exist"] or not relations["orders_exist"]:
        return None
    return dict(
        connection.execute(
            """
            SELECT
              %s::regclass::oid::bigint AS relation_oid,
              count(*)::bigint AS observed_row_count,
              count(*) FILTER (WHERE status = 'created')::bigint
                AS canonical_rows,
              count(*) FILTER (WHERE status = 'touched')::bigint
                AS touched_rows,
              count(*) FILTER (
                WHERE status NOT IN ('created', 'touched')
              )::bigint AS unexpected_status_rows,
              (SELECT count(*)::bigint FROM workbench_lab.customers)
                AS observed_customer_count,
              (SELECT min(customer_id)::bigint FROM workbench_lab.customers)
                AS minimum_customer_id,
              (SELECT max(customer_id)::bigint FROM workbench_lab.customers)
                AS maximum_customer_id,
              count(DISTINCT customer_id)::bigint AS referenced_customers,
              count(*) FILTER (
                WHERE NOT EXISTS (
                  SELECT 1
                  FROM workbench_lab.customers customer
                  WHERE customer.customer_id = orders.customer_id
                )
              )::bigint AS orphan_order_count,
              min(order_id)::bigint AS minimum_order_id,
              max(order_id)::bigint AS maximum_order_id,
              pg_total_relation_size(%s::regclass)::bigint AS table_size_bytes,
              to_regclass(%s) IS NOT NULL AS target_index_exists
            FROM workbench_lab.orders orders
            """,
            (RELATION_NAME, RELATION_NAME, INDEX_NAME),
        ).fetchone()
    )


def _assert_lab_workload_ready(
    state: dict[str, Any] | None,
    *,
    target_index_expected: bool | None = False,
    expected_touched_rows: int = 0,
) -> dict[str, Any]:
    if state is None:
        raise LiveWorkshopError(
            "the operational workload is missing; run `make prepare-workload`"
        )
    if expected_touched_rows < 0 or expected_touched_rows > LAB_ROWS:
        raise ValueError(
            f"expected_touched_rows must be between 0 and {LAB_ROWS}, got "
            f"{expected_touched_rows}"
        )
    if (
        state["observed_row_count"] != LAB_ROWS
        or state["canonical_rows"] != LAB_ROWS - expected_touched_rows
        or state["touched_rows"] != expected_touched_rows
        or state["unexpected_status_rows"] != 0
        or state["observed_customer_count"] != LAB_CUSTOMER_ROWS
        or state["minimum_customer_id"] != 1
        or state["maximum_customer_id"] != LAB_CUSTOMER_ROWS
        or state["referenced_customers"] != LAB_CUSTOMER_ROWS
        or state["orphan_order_count"] != 0
        or state["minimum_order_id"] != 1
        or state["maximum_order_id"] != LAB_ROWS
        or (
            target_index_expected is not None
            and state["target_index_exists"] is not target_index_expected
        )
    ):
        raise LiveWorkshopError(
            "the preloaded operational workload is not canonical: "
            f"{state}"
        )
    return state


def prepare_lab_workload(database_url: str) -> dict[str, Any]:
    """Create the disposable operational substrate without admitting evidence."""
    with _connect(
        database_url,
        "workbench-live-workload-bootstrap",
        autocommit=True,
    ) as connection:
        _assert_no_live_lab_sessions(connection)
        _assert_empty_evidence_store(connection)
        _create_lab_workload(connection)
        return _assert_lab_workload_ready(_lab_workload_state(connection))


@dataclass(frozen=True)
class MigrationCollision:
    """The measured result of the migration backfill and hot-write collision."""

    backfill_pid: int
    backfill_duration_seconds: float
    backfill_rows_updated: int
    hold_proof: HoldProof
    hot_write_results: tuple[HotWriteResult, ...]
    recovery_proof: RecoveryProof
    wave_a_plan_checkpoints: tuple[PlanCheckpoint, ...]
    activity_samples: tuple[dict[str, Any], ...]
    lock_samples: tuple[dict[str, Any], ...]
    blocking_samples: tuple[dict[str, Any], ...]
    during_statement: dict[str, Any]
    after_statement: dict[str, Any]
    started_at: str
    ended_at: str


@dataclass
class ControllerCapture:
    """Raw PostgreSQL evidence captured beside every controller poll."""

    activity_samples: list[dict[str, Any]]
    lock_samples: list[dict[str, Any]]
    blocking_samples: list[dict[str, Any]]
    observation_count: int = 0

    @classmethod
    def empty(cls) -> "ControllerCapture":
        return cls(activity_samples=[], lock_samples=[], blocking_samples=[])


def _lab_api_url() -> str:
    base_url = os.getenv("RETRIEVAL_API_URL", "http://127.0.0.1:8000").rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise LiveWorkshopError(
            "RETRIEVAL_API_URL must be an http(s) URL for the lab API"
        )
    return base_url


def _pool_status_from_api(api_url: str) -> dict[str, Any]:
    try:
        response = requests.get(
            f"{api_url}/v1/lab/pool-status",
            timeout=2.0,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise LiveWorkshopError(
            "could not read the lab pool status endpoint; start the API with "
            "LAB_ENDPOINTS_ENABLED=1 and DB_POOL_MIN_SIZE=DB_POOL_MAX_SIZE=10"
        ) from error
    try:
        payload = response.json()
    except ValueError as error:
        raise LiveWorkshopError(
            "lab pool-status endpoint returned invalid JSON"
        ) from error
    if not isinstance(payload, dict):
        raise LiveWorkshopError(
            f"lab pool-status endpoint returned a non-object response: {payload!r}"
        )
    return payload


def _post_hot_write(api_url: str, order_id: int) -> HotWriteResult:
    """Issue one measured hot write through the lab API."""
    try:
        response = requests.post(
            f"{api_url}/v1/lab/hot-write",
            json={"order_id": order_id},
            timeout=60.0,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise LiveWorkshopError(
            f"hot-write request for order_id={order_id} did not return a measured "
            f"result: {error}"
        ) from error
    try:
        return HotWriteResult.model_validate(response.json())
    except (TypeError, ValueError) as error:
        raise LiveWorkshopError(
            f"hot-write response for order_id={order_id} violates the lab contract"
        ) from error


def _run_hot_write(api_url: str, order_id: int, barrier: Barrier) -> HotWriteResult:
    """Issue one request only after every hot writer is ready to collide."""
    try:
        barrier.wait(timeout=10)
    except BrokenBarrierError as error:
        raise LiveWorkshopError(
            f"hot-write barrier broke before order_id={order_id} could start"
        ) from error
    return _post_hot_write(api_url, order_id)


def _terminate_tagged_lab_sessions(database_url: str) -> int:
    """Terminate only this database's backfill and actively blocked hot writers."""
    with _connect(
        database_url,
        "workbench-live-lab-session-cleanup",
        autocommit=True,
    ) as connection:
        rows = connection.execute(
            """
            SELECT pg_terminate_backend(activity.pid) AS terminated
            FROM pg_stat_activity activity
            WHERE activity.pid <> pg_backend_pid()
              AND activity.datname = current_database()
              AND activity.application_name = ANY(%s)
            """,
            ([HOT_WRITE_APPLICATION_NAME, BACKFILL_APPLICATION_NAME],),
        ).fetchall()
    return sum(1 for row in rows if row["terminated"])


def _capture_controller_observation(
    connection: psycopg.Connection,
    sample: Any,
    *,
    backfill_pid: int,
    capture: ControllerCapture,
) -> None:
    """Persist raw PostgreSQL state for every 250ms controller poll.

    The pool counters in ``PollSample`` prove checkout exhaustion. These rows
    prove the separate database fact: the ten checked-out requests are waiting
    on the open backfill transaction. The searchable corpus later selects only
    distinct transitions from this raw record; it does not expand one document
    per poll.
    """
    capture.observation_count += 1
    observation_number = capture.observation_count
    captured_at = sample.observed_at
    tags = [HOT_WRITE_APPLICATION_NAME, BACKFILL_APPLICATION_NAME]
    activities = connection.execute(
        """
        SELECT
          activity.pid,
          activity.backend_type,
          activity.application_name,
          activity.state,
          activity.wait_event_type,
          activity.wait_event,
          activity.query_start,
          activity.xact_start,
          coalesce(activity.query, '') AS query
        FROM pg_stat_activity activity
        WHERE activity.datname = current_database()
          AND activity.application_name = ANY(%s)
        ORDER BY activity.application_name, activity.pid
        """,
        (tags,),
    ).fetchall()
    locks = connection.execute(
        """
        SELECT
          lock_row.pid,
          lock_row.locktype,
          lock_row.database AS database_oid,
          lock_row.relation::bigint AS relation_oid,
          CASE
            WHEN lock_row.relation IS NULL THEN NULL
            ELSE lock_row.relation::regclass::text
          END AS relation_name,
          lock_row.mode,
          lock_row.granted,
          lock_row.fastpath,
          lock_row.waitstart
        FROM pg_locks lock_row
        JOIN pg_stat_activity activity
          ON activity.pid = lock_row.pid
        WHERE activity.datname = current_database()
          AND activity.application_name = ANY(%s)
        ORDER BY activity.application_name, lock_row.pid, lock_row.locktype,
                 lock_row.mode
        """,
        (tags,),
    ).fetchall()
    blocking = connection.execute(
        """
        SELECT
          activity.pid AS blocked_pid,
          pg_blocking_pids(activity.pid) AS blocking_pids
        FROM pg_stat_activity activity
        WHERE activity.datname = current_database()
          AND activity.application_name = %s
          AND %s = ANY(pg_blocking_pids(activity.pid))
        ORDER BY activity.pid
        """,
        (HOT_WRITE_APPLICATION_NAME, backfill_pid),
    ).fetchall()
    for row in activities:
        measured = dict(row)
        capture.activity_samples.append(
            {
                "observation_number": observation_number,
                "captured_at": captured_at,
                **measured,
                "raw_row": measured,
            }
        )
    for row in locks:
        measured = dict(row)
        capture.lock_samples.append(
            {
                "observation_number": observation_number,
                "captured_at": captured_at,
                **measured,
                "raw_row": measured,
            }
        )
    for row in blocking:
        measured = dict(row)
        capture.blocking_samples.append(
            {
                "observation_number": observation_number,
                "captured_at": captured_at,
                **measured,
                "literal_sql": (
                    f"SELECT pg_blocking_pids({measured['blocked_pid']});"
                ),
                "literal_output": str(measured["blocking_pids"]),
                "raw_row": measured,
            }
        )


def run_migration_collision(
    database_url: str,
    *,
    api_url: str | None = None,
    hold_seconds: float = 12.0,
    max_attempt_seconds: float = 90.0,
) -> MigrationCollision:
    """Induce and prove the migration collision without admitting evidence.

    The later Investigation Evidence admission task consumes this measured result. Keeping this
    phase separate means a failure never publishes a corpus describing an
    incident that did not actually occur.
    """
    get_settings.cache_clear()
    settings = get_settings()
    expected_blocked_sessions = settings.db_pool_max_size
    request_count = settings.lab_hot_write_request_count

    endpoint = api_url or _lab_api_url()
    _pool_status_from_api(endpoint)

    with _connect(
        database_url,
        "workbench-live-migration-ddl",
        autocommit=False,
    ) as ddl_connection:
        add_priority_tier_column(ddl_connection)

    started_at = datetime.now(timezone.utc).isoformat()
    backfill = open_backfill(database_url)
    backfill_pid = backfill.pid
    backfill_duration_seconds = backfill.duration_seconds
    backfill_rows_updated = backfill.rows_updated
    executor = ThreadPoolExecutor(
        max_workers=request_count,
        thread_name_prefix="workbench-hot-write",
    )
    futures = []
    controller_capture = ControllerCapture.empty()
    try:
        barrier = Barrier(request_count)
        futures = [
            executor.submit(_run_hot_write, endpoint, order_id, barrier)
            for order_id in range(1, request_count + 1)
        ]
        with _connect(
            database_url,
            "workbench-live-hold-controller",
            autocommit=True,
        ) as controller_connection:
            hold_proof = prove_hold(
                controller_connection,
                backfill_pid=backfill.pid,
                pool_status=lambda: _pool_status_from_api(endpoint),
                expected_blocked_sessions=expected_blocked_sessions,
                hold_seconds=hold_seconds,
                max_attempt_seconds=max_attempt_seconds,
                sample_observer=lambda conn, sample: _capture_controller_observation(
                    conn,
                    sample,
                    backfill_pid=backfill_pid,
                    capture=controller_capture,
                ),
            )
            during_statement = _statement_stats(controller_connection, "during")

        backfill.commit()
        backfill = None
        results = tuple(future.result(timeout=60.0) for future in futures)
        with _connect(
            database_url,
            "workbench-live-recovery-verifier",
            autocommit=True,
        ) as recovery_connection:
            recovery_proof = verify_recovery(
                recovery_connection,
                backfill_pid=backfill_pid,
                pool_status=lambda: _pool_status_from_api(endpoint),
                write_outcomes=results,
                fresh_write=lambda: _post_hot_write(
                    endpoint,
                    request_count + 1,
                ),
            )
            after_statement = _statement_stats(recovery_connection, "after")
        with _connect(
            database_url,
            "workbench-live-query-regression",
            autocommit=True,
        ) as regression_connection:
            wave_a_plan_checkpoints = tuple(
                capture_plan_checkpoints(regression_connection, tier=3)
            )
        return MigrationCollision(
            backfill_pid=backfill_pid,
            backfill_duration_seconds=backfill_duration_seconds,
            backfill_rows_updated=backfill_rows_updated,
            hold_proof=hold_proof,
            hot_write_results=results,
            recovery_proof=recovery_proof,
            wave_a_plan_checkpoints=wave_a_plan_checkpoints,
            activity_samples=tuple(controller_capture.activity_samples),
            lock_samples=tuple(controller_capture.lock_samples),
            blocking_samples=tuple(controller_capture.blocking_samples),
            during_statement=during_statement,
            after_statement=after_statement,
            started_at=started_at,
            ended_at=str(after_statement["captured_at"]),
        )
    except BaseException:
        if backfill is not None:
            try:
                backfill.abort()
            finally:
                _terminate_tagged_lab_sessions(database_url)
        else:
            _terminate_tagged_lab_sessions(database_url)
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def _assert_wave_a_corpus_present(connection: psycopg.Connection) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT
          capture.capture_id,
          capture.capture_key,
          (capture.manifest ->> 'blocked_writer_count')::integer
            AS blocked_writer_count,
          incident.external_key AS incident_key
        FROM evidence.incident_capture_runs capture
        JOIN evidence.evidence_items incident
          ON incident.evidence_id = capture.incident_evidence_id
        WHERE capture.capture_origin = 'participant_induced'
          AND capture.wave = 'A'
          AND NOT incident.is_deleted
        ORDER BY capture.capture_started_at
        """
    ).fetchall()
    if not rows:
        raise LiveWorkshopError(
            "Validation Evidence requires Lab 1's admitted Investigation "
            "Evidence; run Lab 1 first"
        )
    if len(rows) != 1:
        raise LiveWorkshopError(
            "Validation Evidence requires exactly one Investigation Evidence capture in this workshop database"
        )
    return dict(rows[0])


def _prepare_lab_for_wave(
    database_url: str,
    capture_id: uuid.UUID,
    *,
    wave: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if wave not in {"A", "B"}:
        raise ValueError(f"unsupported capture stage {wave!r}")
    with _connect(
        database_url,
        f"workbench-live-setup-{wave.lower()}",
        autocommit=True,
    ) as connection:
        _assert_no_live_lab_sessions(connection)
        identity = connection.execute(
            """
            SELECT
              current_database() AS database_name,
              current_user AS database_user,
              current_setting('server_version') AS engine_version,
              aurora_version() AS aurora_version
            """
        ).fetchone()
        if identity is None:
            raise LiveWorkshopError("Aurora identity query returned no row")
        if wave == "A":
            _assert_empty_evidence_store(connection)
            expected_touched_rows = 0
        else:
            wave_a = _assert_wave_a_corpus_present(connection)
            # Investigation Evidence commits one hot write per pool slot plus its verified
            # post-recovery probe through the same application pool.
            expected_touched_rows = int(wave_a["blocked_writer_count"]) + 1
        workload = _assert_lab_workload_ready(
            _lab_workload_state(connection),
            # A Validation Evidence participant can have run no index or a differently-shaped
            # one. Both are evidence-bearing outcomes that D3 records before it
            # declines the post-index admission; preflight must not erase them.
            target_index_expected=None if wave == "B" else False,
            expected_touched_rows=expected_touched_rows,
        )
        before = _statement_stats(connection, "before")
    return (
        {
            **dict(identity),
            **workload,
            "capture_id": str(capture_id),
            "workload_preloaded": True,
        },
        before,
    )


def _reserve_sample_ids(
    connection: psycopg.Connection,
    *,
    relation: str,
    rows: Sequence[dict[str, Any]],
) -> None:
    """Reserve identity values before document construction names them."""
    if not rows:
        return
    values = connection.execute(
        """
        SELECT nextval(pg_get_serial_sequence(%s, 'sample_id')) AS sample_id
        FROM generate_series(1, %s)
        """,
        (relation, len(rows)),
    ).fetchall()
    for row, value in zip(rows, values, strict=True):
        row["sample_id"] = int(value["sample_id"])


def _reserve_classifier_sample_ids(
    database_url: str,
    *,
    activity_samples: Sequence[dict[str, Any]],
    statement_samples: Sequence[dict[str, Any]],
) -> None:
    with _connect(
        database_url,
        "workbench-live-sample-identities",
        autocommit=True,
    ) as connection:
        _reserve_sample_ids(
            connection,
            relation="evidence.pg_stat_activity_samples",
            rows=activity_samples,
        )
        _reserve_sample_ids(
            connection,
            relation="evidence.pg_stat_statements_samples",
            rows=statement_samples,
        )


def _selected_activity_samples(
    collision: MigrationCollision,
) -> list[dict[str, Any]]:
    """Match each connected hot write to one captured lock-wait row."""
    order_by_pid: dict[int, int] = {}
    for result in collision.hot_write_results:
        if result.outcome != "committed":
            continue
        if result.backend_pid is None:
            raise LiveWorkshopError(
                "a committed hot write did not return its PostgreSQL backend PID"
            )
        order_by_pid[result.backend_pid] = result.order_id

    selected: dict[int, dict[str, Any]] = {}
    for sample in sorted(
        collision.activity_samples,
        key=lambda row: (
            int(row["observation_number"]),
            int(row["pid"]),
        ),
    ):
        pid = int(sample["pid"])
        if (
            pid not in order_by_pid
            or pid in selected
            or sample["application_name"] != HOT_WRITE_APPLICATION_NAME
            or sample["wait_event_type"] != "Lock"
            or str(sample["wait_event"]).lower() != "transactionid"
        ):
            continue
        selected[pid] = {
            **sample,
            "order_id": order_by_pid[pid],
            "statement": sample["query"],
        }
    if len(selected) != len(order_by_pid):
        raise LiveWorkshopError(
            "raw controller capture did not retain one transaction-ID wait "
            f"for every connected hot writer: expected {len(order_by_pid)}, "
            f"captured {len(selected)}"
        )
    return sorted(selected.values(), key=lambda row: int(row["order_id"]))


def _base_acl() -> dict[str, Any]:
    return {
        "visibility": "workshop",
        "classifier_version": "statement-text/1",
        "classification_reason": "no_statement_text",
        "classification_sources": [],
    }


def _record(
    *,
    external_key: str,
    title: str,
    source_uri: str,
    occurred_at: str,
    available_at: str,
    body: str,
    structured: dict[str, Any],
    acl: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "external_key": external_key,
        "title": title,
        "source_uri": source_uri,
        "occurred_at": occurred_at,
        "available_at": available_at,
        "body": body,
        "structured": structured,
        "acl": acl or _base_acl(),
    }


def _telemetry_record(
    document: EvidenceDocument,
    *,
    bundle_uri: str,
    incident_key: str,
    change_key: str,
    available_at: str,
    observation_number: int,
) -> dict[str, Any]:
    structured = {
        **document.structured,
        "incident_external_key": incident_key,
        "change_external_key": change_key,
        "observation_number": observation_number,
        "observed_until": document.occurred_at,
    }
    return _record(
        external_key=document.key,
        title=document.title,
        source_uri=f"{bundle_uri}/telemetry/{document.key.lower()}",
        occurred_at=document.occurred_at,
        available_at=available_at,
        body=document.body,
        structured=structured,
        acl={
            "visibility": document.visibility,
            "classifier_version": document.classifier_version,
            "classification_reason": document.classification_reason,
            "classification_sources": list(document.classification_sources),
        },
    )


def _primary_lock_fields(collision: MigrationCollision) -> dict[str, Any]:
    writer = next(
        (
            sample
            for sample in collision.activity_samples
            if sample["application_name"] == HOT_WRITE_APPLICATION_NAME
            and sample["wait_event_type"] == "Lock"
            and str(sample["wait_event"]).lower() == "transactionid"
        ),
        None,
    )
    blocker = next(
        (
            sample
            for sample in collision.activity_samples
            if int(sample["pid"]) == collision.backfill_pid
        ),
        None,
    )
    if writer is None or blocker is None:
        raise LiveWorkshopError(
            "raw controller capture is missing the primary writer or backfill row"
        )
    waiting_lock = next(
        (
            sample
            for sample in collision.lock_samples
            if int(sample["pid"]) == int(writer["pid"])
            and str(sample["locktype"]).lower() == "transactionid"
            and not sample["granted"]
        ),
        None,
    )
    blocking = next(
        (
            sample
            for sample in collision.blocking_samples
            if int(sample["blocked_pid"]) == int(writer["pid"])
            and collision.backfill_pid in sample["blocking_pids"]
        ),
        None,
    )
    blocking_lock = next(
        (
            sample
            for sample in collision.lock_samples
            if int(sample["pid"]) == collision.backfill_pid
            and str(sample["locktype"]).lower() == "transactionid"
            and sample["granted"]
        ),
        None,
    )
    if waiting_lock is None or blocking is None or blocking_lock is None:
        raise LiveWorkshopError(
            "raw controller capture does not prove the transaction-ID blocker chain"
        )
    return {
        "captured_at": writer["captured_at"],
        "relation_name": RELATION_NAME,
        "relation_oid": next(
            (
                sample["relation_oid"]
                for sample in collision.lock_samples
                if sample["relation_name"] == RELATION_NAME
            ),
            None,
        ),
        "blocked_pid": writer["pid"],
        "blocking_pid": collision.backfill_pid,
        "blocked_state": writer["state"],
        "blocked_query_start": writer["query_start"],
        "wait_event_type": writer["wait_event_type"],
        "wait_event": str(writer["wait_event"]).lower(),
        "blocked_locktype": str(waiting_lock["locktype"]).lower(),
        "blocked_lock_mode": waiting_lock["mode"],
        "blocked_lock_granted": waiting_lock["granted"],
        "blocking_lock_mode": blocking_lock["mode"],
        "blocking_lock_granted": blocking_lock["granted"],
        "blocking_pids": blocking["blocking_pids"],
        "blocking_pids_sql": blocking["literal_sql"],
        "blocking_pids_output": blocking["literal_output"],
        "blocked_statement": writer["query"],
        "blocking_statement": blocker["query"],
    }


def _wave_a_payload(
    *,
    capture_id: uuid.UUID,
    workload: dict[str, Any],
    before_statement: dict[str, Any],
    collision: MigrationCollision,
    aws_capture: dict[str, Any],
) -> dict[str, Any]:
    run_suffix = capture_id.hex[-8:].upper()
    incident_key = f"INC-{run_suffix}"
    backfill_change_key = f"CHG-{run_suffix}-01"
    analyze_change_key = f"CHG-{run_suffix}-02"
    lock_key = f"LOCK-{run_suffix}-01"
    bundle_uri = f"workshop://participant/live-run/{capture_id}"
    statement_samples = [
        before_statement,
        collision.during_statement,
        {
            **collision.after_statement,
            "delta_from_before": {
                key: collision.after_statement[key] - before_statement[key]
                for key in ("calls", "total_exec_time", "rows")
            },
        },
    ]
    activity_samples = [dict(sample) for sample in collision.activity_samples]
    _reserve_classifier_sample_ids(
        workload["database_url"],
        activity_samples=activity_samples,
        statement_samples=statement_samples,
    )
    collision = MigrationCollision(
        **{
            **collision.__dict__,
            "activity_samples": tuple(activity_samples),
        }
    )
    documents = build_wave_a_documents(
        run_suffix=run_suffix,
        backfill_pid=collision.backfill_pid,
        backfill_duration_seconds=collision.backfill_duration_seconds,
        backfill_rows_updated=collision.backfill_rows_updated,
        hold_proof=collision.hold_proof,
        recovery_proof=collision.recovery_proof,
        hot_write_results=collision.hot_write_results,
        activity_samples=_selected_activity_samples(collision),
        statement_samples=statement_samples,
        plan_checkpoints=collision.wave_a_plan_checkpoints,
    )
    lock_fields = _primary_lock_fields(collision)
    available_at = collision.ended_at
    telemetry_documents = [
        _telemetry_record(
            document,
            bundle_uri=bundle_uri,
            incident_key=incident_key,
            change_key=(
                analyze_change_key
                if document.phase == "plan_regression"
                else backfill_change_key
            ),
            available_at=available_at,
            observation_number=ordinal,
        )
        for ordinal, document in enumerate(documents, start=1)
    ]
    return _json_safe(
        {
            "schema": "admission payload v1",
            "kind": "incident_bundle",
            "wave": "A",
            "cloudwatch_status": aws_capture["cloudwatch_status"],
            "source": {
                "system": SOURCE_SYSTEM,
                "uri": bundle_uri,
                "observation_window": {
                    "start": collision.started_at,
                    "end": collision.ended_at,
                },
            },
            "database": aws_capture["database"],
            "capture": {
                "capture_id": str(capture_id),
                "capture_key": f"CAP-{run_suffix}",
                "run_suffix": run_suffix,
                "capture_origin": "participant_induced",
                "relation_name": RELATION_NAME,
                "relation_oid": workload["relation_oid"],
                "configured_row_count": LAB_ROWS,
                "observed_row_count": workload["observed_row_count"],
                "table_size_bytes": workload["table_size_bytes"],
                "request_count": len(collision.hot_write_results),
                "blocked_writer_count": sum(
                    result.outcome == "committed"
                    for result in collision.hot_write_results
                ),
                "reader_count": 0,
                "phases": [
                    "backfill",
                    "pool_exhaustion",
                    "recovery",
                    "plan_regression",
                ],
                "signal_types": ["lock", "pool", "request", "wal", "meta", "plan"],
                "capture_started_at": collision.started_at,
                "capture_ended_at": collision.ended_at,
                "capture_tool_version": "workbench-live-orchestrator-v2",
                "manifest": {
                    "controller_poll_count": len(collision.hold_proof.samples),
                    "raw_activity_rows": len(collision.activity_samples),
                    "raw_lock_rows": len(collision.lock_samples),
                    "raw_blocking_rows": len(collision.blocking_samples),
                    "telemetry_documents": len(telemetry_documents),
                    "cloudwatch_error": aws_capture.get("cloudwatch_error"),
                },
            },
            "telemetry": {
                "pg_stat_activity": list(collision.activity_samples),
                "pg_locks": list(collision.lock_samples),
                "pg_blocking_pids": list(collision.blocking_samples),
                "pg_stat_statements": statement_samples,
                "cloudwatch_metrics": aws_capture["cloudwatch_metrics"],
            },
            "records": {
                "incident": _record(
                    external_key=incident_key,
                    title="Participant-induced Aurora PostgreSQL write stall",
                    source_uri=f"{bundle_uri}/incident",
                    occurred_at=collision.started_at,
                    available_at=available_at,
                    body=(
                        "One unbatched priority_tier backfill held row locks while "
                        "the real application pool exhausted. The lock wait "
                        "recovered after commit, but the measured query remained a "
                        "sequential scan after ANALYZE."
                    ),
                    structured={
                        "severity": "SEV-3",
                        "status": "mitigated",
                        "started_at": collision.started_at,
                        "mitigated_at": collision.ended_at,
                        "resolved_at": None,
                        "summary": (
                            "An open unbatched migration transaction blocked "
                            "concurrent hot writes."
                        ),
                        "impact_summary": (
                            "Ten requests reached PostgreSQL and waited on the "
                            "backfill; two more timed out waiting for the pool."
                        ),
                        "resolution": None,
                    },
                ),
                "changes": [
                    _record(
                        external_key=backfill_change_key,
                        title="Unbatched priority-tier migration backfill",
                        source_uri=f"{bundle_uri}/change/backfill",
                        occurred_at=collision.started_at,
                        available_at=available_at,
                        body=(
                            "The nullable priority_tier column committed first. "
                            "A separate, unbatched UPDATE then changed all "
                            f"{collision.backfill_rows_updated} orders and held "
                            "its transaction open for the measured collision."
                        ),
                        structured={
                            "incident_external_key": incident_key,
                            "change_role": "unsafe",
                            "relationship": "confirmed",
                            "rationale": (
                                "pg_blocking_pids() and the transaction-ID lock "
                                "snapshot both named the retained backfill PID."
                            ),
                            "change_type": "ddl",
                            "status": "completed",
                            "started_at": collision.started_at,
                            "completed_at": collision.ended_at,
                            "owner_team": "workshop-participant",
                            "execution_sql": (
                                "ALTER TABLE workbench_lab.orders "
                                "ADD COLUMN priority_tier int; "
                                "UPDATE workbench_lab.orders "
                                "SET priority_tier = (order_id % 5) + 1"
                            ),
                            "description": (
                                "The data backfill remained open after updating "
                                "all rows, retaining row-level locks."
                            ),
                            "rollback_plan": (
                                "ROLLBACK the open backfill before commit to "
                                "release the row locks."
                            ),
                        },
                    ),
                    _record(
                        external_key=analyze_change_key,
                        title="ANALYZE checkpoint did not change the access path",
                        source_uri=f"{bundle_uri}/change/analyze",
                        occurred_at=collision.ended_at,
                        available_at=available_at,
                        body=(
                            "ANALYZE completed, but the captured reference query "
                            "remained a sequential scan. Statistics refresh did not "
                            "create the missing selective access path."
                        ),
                        structured={
                            "incident_external_key": incident_key,
                            "change_role": "attempted_fix",
                            "relationship": "ruled_out",
                            "rationale": (
                                "The before-ANALYZE and after-ANALYZE EXPLAIN "
                                "checkpoints are both sequential scans."
                            ),
                            "change_type": "ddl",
                            "status": "completed",
                            "started_at": collision.ended_at,
                            "completed_at": collision.ended_at,
                            "owner_team": "workshop-participant",
                            "execution_sql": "ANALYZE workbench_lab.orders",
                            "description": (
                                "Statistics refresh alone did not address the "
                                "missing composite index."
                            ),
                            "rollback_plan": "No rollback is required.",
                        },
                    ),
                ],
                "lock_evidence": _record(
                    external_key=lock_key,
                    title="Measured transaction-ID lock wait",
                    source_uri=f"{bundle_uri}/lock/primary",
                    occurred_at=str(lock_fields["captured_at"]),
                    available_at=available_at,
                    body=(
                        "A hot-write backend waited on Lock:transactionid. "
                        "Its pg_blocking_pids() result named the open backfill "
                        "transaction."
                    ),
                    structured={
                        "incident_external_key": incident_key,
                        "change_external_key": backfill_change_key,
                        **lock_fields,
                    },
                ),
                "telemetry_documents": telemetry_documents,
            },
        }
    )


def _action_proposal(
    connection: psycopg.Connection,
    proposal_id: str,
    *,
    incident_key: str,
) -> dict[str, Any]:
    """Read the approved proposal only when its run retrieved this incident."""
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
              proposal_id::text AS proposal_id,
              target_schema,
              target_table,
              proposed_fingerprint,
              proposed_sql,
              EXISTS (
                SELECT 1
                FROM proof.retrieval_candidates candidate
                JOIN retrieval.documents document
                  ON document.document_version_id = candidate.document_version_id
                JOIN evidence.incidents incident
                  ON incident.incident_id = document.incident_id
                JOIN evidence.evidence_items incident_item
                  ON incident_item.evidence_id = incident.evidence_id
                WHERE candidate.run_id = proposal.run_id
                  AND incident_item.external_key = %s
                  AND NOT incident_item.is_deleted
              ) AS matches_incident
            FROM proof.action_proposals proposal
            WHERE proposal.proposal_id = %s::uuid
            """,
            (incident_key, proposal_id),
        )
        row = cursor.fetchone()
    if row is None:
        raise LiveWorkshopError(
            f"no stored action proposal exists for {proposal_id}; run Lab 3 first"
        )
    proposal = dict(row)
    if not proposal.pop("matches_incident"):
        raise LiveWorkshopError(
            f"stored action proposal {proposal_id} is not grounded in the current "
            f"Investigation Evidence incident {incident_key}; run Lab 3 for this incident first"
        )
    if (
        proposal["target_schema"],
        proposal["target_table"],
    ) != ("workbench_lab", "orders"):
        raise LiveWorkshopError(
            "the approved proposal does not target workbench_lab.orders; "
            "this Lab 4 runner will not inspect another relation"
        )
    return proposal


@dataclass(frozen=True)
class ObservedIndex:
    """One participant-created index read back from Aurora's catalog."""

    oid: int
    fingerprint: str
    definition: str


def _observed_index_by_oid(
    connection: psycopg.Connection,
    *,
    relation_name: str,
    index_oid: int,
) -> ObservedIndex | None:
    row = connection.execute(
        """
        SELECT
          index_row.indexrelid::oid::integer AS index_oid,
          observed.fingerprint,
          observed.index_definition
        FROM pg_index index_row
        CROSS JOIN LATERAL proof.observed_index_fingerprint(
          index_row.indexrelid
        ) observed
        WHERE index_row.indexrelid = %s::oid
          AND index_row.indrelid = %s::regclass
        """,
        (index_oid, relation_name),
    ).fetchone()
    if row is None:
        return None
    return ObservedIndex(
        oid=int(row["index_oid"]),
        fingerprint=str(row["fingerprint"]),
        definition=str(row["index_definition"]),
    )


def _resolve_observed_index(
    connection: psycopg.Connection,
    *,
    proposal: dict[str, Any],
    observed_index_name: str | None,
) -> ObservedIndex | None:
    """Resolve the created index by shape, then a named fallback.

    A canonical fingerprint is the equality contract. A name is used only when
    the participant built a different shape and the runner needs to preserve
    that mismatch as evidence instead of treating it as no action.
    """
    relation_name = f"{proposal['target_schema']}.{proposal['target_table']}"
    matching_rows = connection.execute(
        """
        SELECT index_row.indexrelid::oid::integer AS index_oid
        FROM pg_index index_row
        CROSS JOIN LATERAL proof.observed_index_fingerprint(
          index_row.indexrelid
        ) observed
        WHERE index_row.indrelid = %s::regclass
          AND observed.fingerprint = %s
        ORDER BY index_row.indexrelid
        """,
        (relation_name, proposal["proposed_fingerprint"]),
    ).fetchall()
    if len(matching_rows) == 1:
        return _observed_index_by_oid(
            connection,
            relation_name=relation_name,
            index_oid=int(matching_rows[0]["index_oid"]),
        )
    if len(matching_rows) > 1 and observed_index_name is None:
        raise LiveWorkshopError(
            "multiple indexes match the approved proposal; rerun Validation Evidence with "
            "--observed-index <schema.index_name> to identify the one you ran"
        )

    if observed_index_name is not None:
        oid_row = connection.execute(
            "SELECT to_regclass(%s)::oid::integer AS index_oid",
            (observed_index_name,),
        ).fetchone()
        if oid_row is None or oid_row["index_oid"] is None:
            return None
        observed = _observed_index_by_oid(
            connection,
            relation_name=relation_name,
            index_oid=int(oid_row["index_oid"]),
        )
        if observed is None:
            raise LiveWorkshopError(
                f"{observed_index_name!r} is not an index on {relation_name}"
            )
        return observed

    candidates = connection.execute(
        """
        SELECT indexrelid::oid::integer AS index_oid
        FROM pg_index
        WHERE indrelid = %s::regclass
          AND NOT indisprimary
        ORDER BY indexrelid
        """,
        (relation_name,),
    ).fetchall()
    if len(candidates) == 0:
        return None
    if len(candidates) > 1:
        raise LiveWorkshopError(
            "the approved proposal did not match and multiple non-primary "
            "indexes exist; rerun Validation Evidence with --observed-index "
            "<schema.index_name> so the mismatch can be recorded honestly"
        )
    return _observed_index_by_oid(
        connection,
        relation_name=relation_name,
        index_oid=int(candidates[0]["index_oid"]),
    )


def record_action_execution(
    connection: psycopg.Connection,
    *,
    proposal_id: str,
    approved_by: str,
    observed_index_oid: int | None,
    outcome: str,
    outcome_detail: str | None,
    started_at: datetime | None,
    completed_at: datetime | None,
    plan_before_checkpoint: str | None,
    plan_after_checkpoint: str | None,
    wave_b_capture_id: str | None,
    wave_b_ingest_id: str | None,
) -> str:
    """Persist one participant action with Aurora-derived catalog evidence.

    The definition, canonical fingerprint, and equality result are selected from
    ``proof.observed_index_fingerprint()`` inside the insert. Callers cannot
    supply those values, because that would turn the execution record into an
    assertion about what ran instead of evidence read back from Aurora.
    """
    approver = approved_by.strip()
    if not approver:
        raise LiveWorkshopError("Validation Evidence requires a non-empty --approved-by value")
    if outcome not in {"succeeded", "failed"}:
        raise LiveWorkshopError(
            "execution outcome must be 'succeeded' or 'failed', "
            f"got {outcome!r}"
        )
    if outcome == "succeeded" and observed_index_oid is None:
        raise LiveWorkshopError(
            "a succeeded execution must name the index Aurora created; record "
            "outcome='failed' when no index exists"
        )

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO proof.action_executions(
              proposal_id,
              run_id,
              approved_by,
              executed_sql,
              executed_sql_sha256,
              observed_index_definition,
              observed_fingerprint,
              fingerprint_matches,
              outcome,
              outcome_detail,
              started_at,
              completed_at,
              plan_before_checkpoint,
              plan_after_checkpoint,
              wave_b_capture_id,
              wave_b_ingest_id
            )
            SELECT
              proposal.proposal_id,
              proposal.run_id,
              %(approved_by)s,
              observed.index_definition,
                CASE
                WHEN observed.index_definition IS NULL THEN NULL
                ELSE encode(
                  sha256(convert_to(observed.index_definition, 'UTF8')),
                  'hex'
                )
              END,
              observed.index_definition,
              observed.fingerprint,
              CASE
                WHEN observed.fingerprint IS NULL THEN NULL
                ELSE observed.fingerprint = proposal.proposed_fingerprint
              END,
              %(outcome)s,
              %(outcome_detail)s,
              %(started_at)s,
              %(completed_at)s,
              %(plan_before_checkpoint)s,
              %(plan_after_checkpoint)s,
              %(wave_b_capture_id)s::uuid,
              %(wave_b_ingest_id)s::uuid
            FROM proof.action_proposals proposal
            LEFT JOIN LATERAL (
              SELECT fingerprint, index_definition
              FROM proof.observed_index_fingerprint(%(observed_index_oid)s::oid)
              WHERE %(observed_index_oid)s IS NOT NULL
            ) observed ON true
            WHERE proposal.proposal_id = %(proposal_id)s::uuid
            RETURNING execution_id
            """,
            {
                "proposal_id": proposal_id,
                "approved_by": approver,
                "observed_index_oid": observed_index_oid,
                "outcome": outcome,
                "outcome_detail": outcome_detail,
                "started_at": started_at,
                "completed_at": completed_at,
                "plan_before_checkpoint": plan_before_checkpoint,
                "plan_after_checkpoint": plan_after_checkpoint,
                "wave_b_capture_id": wave_b_capture_id,
                "wave_b_ingest_id": wave_b_ingest_id,
            },
        )
        row = cursor.fetchone()
    if row is None:
        raise LiveWorkshopError(
            f"no proposal {proposal_id} exists to record an execution against"
        )
    if isinstance(row, dict):
        return str(row["execution_id"])
    return str(row[0])


def _wave_b_payload(
    *,
    capture_id: uuid.UUID,
    workload: dict[str, Any],
    incident_key: str,
    index_definition: str,
    plan_checkpoints: Sequence[PlanCheckpoint],
    started_at: str,
    ended_at: str,
    aws_capture: dict[str, Any],
) -> dict[str, Any]:
    run_suffix = capture_id.hex[-8:].upper()
    bundle_uri = f"workshop://participant/live-run/{capture_id}"
    validation_change_key = f"CHG-{run_suffix}-01"
    documents = build_wave_b_documents(
        run_suffix=run_suffix,
        plan_checkpoints=plan_checkpoints,
        occurred_at=ended_at,
    )
    telemetry_documents = [
        _telemetry_record(
            document,
            bundle_uri=bundle_uri,
            incident_key=incident_key,
            change_key=validation_change_key,
            available_at=ended_at,
            observation_number=ordinal,
        )
        for ordinal, document in enumerate(documents, start=1)
    ]
    return _json_safe(
        {
            "schema": "admission payload v1",
            "kind": "incident_bundle",
            "wave": "B",
            "incident_key": incident_key,
            "cloudwatch_status": aws_capture["cloudwatch_status"],
            "source": {
                "system": SOURCE_SYSTEM,
                "uri": bundle_uri,
                "observation_window": {"start": started_at, "end": ended_at},
            },
            "database": aws_capture["database"],
            "capture": {
                "capture_id": str(capture_id),
                "capture_key": f"CAP-{run_suffix}",
                "run_suffix": run_suffix,
                "capture_origin": "participant_induced",
                "relation_name": RELATION_NAME,
                "relation_oid": workload["relation_oid"],
                "configured_row_count": LAB_ROWS,
                "observed_row_count": workload["observed_row_count"],
                "table_size_bytes": workload["table_size_bytes"],
                "request_count": 0,
                "blocked_writer_count": 0,
                "reader_count": 0,
                "phases": ["plan_regression"],
                "signal_types": ["meta", "plan"],
                "capture_started_at": started_at,
                "capture_ended_at": ended_at,
                "capture_tool_version": "workbench-live-orchestrator-v2",
                "manifest": {
                    "telemetry_documents": len(telemetry_documents),
                    "cloudwatch_error": aws_capture.get("cloudwatch_error"),
                },
            },
            "telemetry": {
                "pg_stat_activity": [],
                "pg_locks": [],
                "pg_blocking_pids": [],
                "pg_stat_statements": [],
                "cloudwatch_metrics": aws_capture["cloudwatch_metrics"],
            },
            "records": {
                "changes": [
                    _record(
                        external_key=validation_change_key,
                        title="Participant-approved composite index validation",
                        source_uri=f"{bundle_uri}/change/index",
                        occurred_at=ended_at,
                        available_at=ended_at,
                        body=(
                            "The participant created the recommended composite "
                            "index. Validation Evidence captured a new post-index plan without "
                            "revising the earlier Investigation Evidence diagnosis."
                        ),
                        structured={
                            "incident_external_key": incident_key,
                            "change_role": "validation",
                            "relationship": "validates",
                            "rationale": (
                                "The post-index EXPLAIN checkpoint used the "
                                "participant-created access path."
                            ),
                            "change_type": "ddl",
                            "status": "completed",
                            "started_at": started_at,
                            "completed_at": ended_at,
                            "owner_team": "workshop-participant",
                            "execution_sql": index_definition,
                            "description": (
                                "The index supplies the selective path the "
                                "Investigation Evidence sequential scans lacked."
                            ),
                            "rollback_plan": (
                                f"DROP INDEX {RECOMMENDED_INDEX_NAME}"
                            ),
                        },
                    )
                ],
                "telemetry_documents": telemetry_documents,
            },
        }
    )


def _json_safe(payload: Any) -> Any:
    return json.loads(json.dumps(payload, default=str))


def _admit_evidence(database_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _connect(
        database_url,
        "workbench-live-admission",
        autocommit=True,
    ) as connection:
        row = connection.execute(
            "SELECT evidence.admit_evidence(%s::jsonb) AS receipt",
            (json.dumps(payload),),
        ).fetchone()
    if row is None:
        raise LiveWorkshopError("admission did not return a receipt")
    return dict(row)["receipt"]


def _receipt_identifiers(payload: dict[str, Any]) -> dict[str, Any]:
    """Return only identifiers that the admitted wave actually observed."""
    capture = payload["capture"]
    records = payload["records"]
    wave = payload["wave"]
    identifiers = {
        "run_suffix": capture["run_suffix"],
        "incident_key": (
            records["incident"]["external_key"]
            if wave == "A"
            else payload["incident_key"]
        ),
    }
    if wave == "A":
        changes = records["changes"]
        identifiers.update(
            {
                "unsafe_change_key": changes[0]["external_key"],
                "analyze_change_key": changes[1]["external_key"],
                "lock_key": records["lock_evidence"]["external_key"],
            }
        )
    else:
        identifiers["validation_change_key"] = records["changes"][0]["external_key"]
    return identifiers


def _render_wave_a_exercise_template(
    template: str,
    replacements: dict[str, str],
) -> str:
    """Render one request template and reject a broken participant handoff."""
    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    unresolved = sorted(set(UNRESOLVED_EXERCISE_PLACEHOLDER.findall(rendered)))
    if unresolved:
        raise LiveWorkshopError(
            "the generated participant exercise still has unresolved placeholders: "
            + ", ".join(unresolved)
        )
    return rendered


def _materialize_wave_a_exercises(
    receipt: dict[str, Any],
    *,
    output_dir: Path,
) -> None:
    """Write Lab 2 and Lab 3 requests from the Investigation Evidence receipt alone."""
    required = {
        "wave",
        "run_suffix",
        "incident_key",
        "unsafe_change_key",
        "analyze_change_key",
        "lock_key",
    }
    missing = sorted(required - receipt.keys())
    if missing:
        raise LiveWorkshopError(
            "cannot create run-scoped exercises; the Investigation Evidence receipt is missing: "
            + ", ".join(missing)
        )
    if receipt["wave"] != "A":
        raise LiveWorkshopError(
            "run-scoped Lab 2 and Lab 3 exercises require an Investigation "
            "Evidence receipt"
        )

    suffix = str(receipt["run_suffix"])
    expected = {
        "incident_key": f"INC-{suffix}",
        "unsafe_change_key": f"CHG-{suffix}-01",
        "analyze_change_key": f"CHG-{suffix}-02",
        "lock_key": f"LOCK-{suffix}-01",
    }
    if not re.fullmatch(r"[A-F0-9]{8}", suffix) or any(
        receipt[name] != value for name, value in expected.items()
    ):
        raise LiveWorkshopError(
            "cannot create run-scoped exercises; the Investigation Evidence receipt does not "
            "contain one valid run-derived identity"
        )

    replacements = {
        "{{INCIDENT_KEY}}": expected["incident_key"],
        "{{UNSAFE_CHANGE_KEY}}": expected["unsafe_change_key"],
        "{{ANALYZE_CHANGE_KEY}}": expected["analyze_change_key"],
        "{{LOCK_KEY}}": expected["lock_key"],
        "{{FUZZY_CHANGE_KEY}}": f"CGH-{suffix}-01",
        "REPLACE_WITH_INCIDENT_ID": expected["incident_key"],
        "REPLACE_WITH_UNSAFE_CHANGE_ID": expected["unsafe_change_key"],
        "REPLACE_WITH_ANALYZE_CHANGE_ID": expected["analyze_change_key"],
        "REPLACE_WITH_LOCK_OBSERVATION_ID": expected["lock_key"],
    }
    exercise_dir = output_dir / "exercises"
    exercise_dir.mkdir(parents=True, exist_ok=True)
    for name in WAVE_A_EXERCISE_TEMPLATES:
        source = EXERCISE_TEMPLATE_DIR / name
        if not source.is_file():
            raise LiveWorkshopError(f"participant exercise template is missing: {source}")
        rendered = _render_wave_a_exercise_template(
            source.read_text(encoding="utf-8"),
            replacements,
        )
        (exercise_dir / name).write_text(rendered, encoding="utf-8")


def admit_wave_a(
    database_url: str,
    *,
    capture_id: uuid.UUID,
    workload: dict[str, Any],
    before_statement: dict[str, Any],
    collision: MigrationCollision,
    aws_capture: dict[str, Any],
    payload_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build and atomically admit Lab 1's diagnostic evidence."""
    payload = _wave_a_payload(
        capture_id=capture_id,
        workload={**workload, "database_url": database_url},
        before_statement=before_statement,
        collision=collision,
        aws_capture=aws_capture,
    )
    _write_atomic(payload_path, payload)
    return payload, _admit_evidence(database_url, payload)


def admit_wave_b(
    database_url: str,
    *,
    capture_id: uuid.UUID,
    workload: dict[str, Any],
    incident_key: str,
    index_definition: str,
    plan_checkpoints: Sequence[PlanCheckpoint],
    started_at: str,
    ended_at: str,
    aws_capture: dict[str, Any],
    payload_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build and atomically admit Lab 4's additive validation evidence."""
    payload = _wave_b_payload(
        capture_id=capture_id,
        workload=workload,
        incident_key=incident_key,
        index_definition=index_definition,
        plan_checkpoints=plan_checkpoints,
        started_at=started_at,
        ended_at=ended_at,
        aws_capture=aws_capture,
    )
    _write_atomic(payload_path, payload)
    return payload, _admit_evidence(database_url, payload)


def _attach_wave_b_receipt(
    database_url: str,
    *,
    execution_id: str,
    capture_id: uuid.UUID,
    ingest_receipt: dict[str, Any],
) -> None:
    """Attach an admitted Validation Evidence receipt to an already-recorded action once."""
    ingest_id = ingest_receipt.get("ingest_id")
    if not isinstance(ingest_id, str) or not ingest_id:
        raise LiveWorkshopError(
            "Validation Evidence admission returned no ingest_id; the execution remains "
            "recorded but cannot claim validation"
        )
    with _connect(
        database_url,
        "workbench-live-wave-b-receipt",
        autocommit=True,
    ) as connection:
        connection.execute(
            "SELECT proof.attach_wave_b_receipt(%s::uuid, %s::uuid, %s::uuid)",
            (execution_id, str(capture_id), ingest_id),
        )


def _build_search_index(
    database_url: str,
    *,
    run_suffix: str,
    output_dir: Path,
) -> dict[str, Any]:
    os.environ["DATABASE_URL"] = database_url
    from backend.app.config import get_settings
    from backend.app.db import close_pool, get_owner_conn
    from backend.app.search_index import rebuild_search_index

    get_settings.cache_clear()
    settings = get_settings()
    if settings.embed_provider != "bedrock":
        raise LiveWorkshopError(
            "EMBED_PROVIDER must be bedrock for participant indexing"
        )
    cache_path = output_dir / f"embeddings-{run_suffix}.jsonl"
    try:
        with get_owner_conn() as connection:
            search_index = rebuild_search_index(
                connection,
                model_id=settings.bedrock_embedding_model,
                cache_path=cache_path,
                embed_missing=True,
                batch_size=48,
                source_systems=[SOURCE_SYSTEM],
            )
            health = connection.execute(
                "SELECT retrieval.assert_search_index_ready()"
            ).fetchone()[0]
        return {
            "search_index": search_index,
            "health": health,
            "embedding_cache": str(cache_path),
        }
    finally:
        close_pool()


def _verify_wave(
    database_url: str,
    *,
    capture_id: uuid.UUID,
    wave: str,
    bundle_uri: str,
) -> dict[str, Any]:
    with _connect(
        database_url,
        "workbench-live-receipt",
        autocommit=True,
    ) as connection:
        counts = connection.execute(
            """
            SELECT
              (
                SELECT count(*)
                FROM evidence.evidence_items item
                WHERE item.source_system = %s
                  AND NOT item.is_deleted
              ) AS corpus_documents,
              (
                SELECT count(*)
                FROM retrieval.documents document
                WHERE document.is_current
                  AND document.index_state = 'ready'
                  AND document.source_uri LIKE %s || '/%%'
              ) AS wave_documents,
              (
                SELECT count(*)
                FROM evidence.pg_stat_activity_samples
                WHERE capture_id = %s
              ) AS activity_rows,
              (
                SELECT count(*)
                FROM evidence.pg_lock_samples
                WHERE capture_id = %s
              ) AS lock_rows,
              (
                SELECT count(*)
                FROM evidence.pg_blocking_pids_samples
                WHERE capture_id = %s
              ) AS blocking_rows,
              (
                SELECT count(*)
                FROM evidence.pg_stat_statements_samples
                WHERE capture_id = %s
              ) AS statement_rows,
              (
                SELECT count(*)
                FROM evidence.cloudwatch_metric_samples
                WHERE capture_id = %s
              ) AS cloudwatch_rows
            """,
            (
                SOURCE_SYSTEM,
                bundle_uri,
                capture_id,
                capture_id,
                capture_id,
                capture_id,
                capture_id,
            ),
        ).fetchone()
        capture = connection.execute(
            """
            SELECT capture_key, wave
            FROM evidence.incident_capture_runs
            WHERE capture_id = %s
            """,
            (capture_id,),
        ).fetchone()
        readiness = connection.execute(
            "SELECT evidence.assert_live_capture_ready() AS receipt"
        ).fetchone()["receipt"]
        health = connection.execute(
            "SELECT retrieval.assert_search_index_ready() AS health"
        ).fetchone()["health"]
    capture_label = (
        "Investigation Evidence" if wave == "A" else "Validation Evidence"
    )
    if capture is None or capture["wave"] != wave:
        raise LiveWorkshopError(
            f"admission did not persist {capture_label} capture {capture_id} "
            f"as internal stage {wave}"
        )
    if counts["wave_documents"] == 0:
        raise LiveWorkshopError(
            f"{capture_label} did not produce indexed documents"
        )
    if wave == "A" and not readiness["live_ready"]:
        raise LiveWorkshopError(
            "Investigation Evidence did not satisfy the live capture contract"
        )
    if wave == "B" and not readiness["two_wave_ready"]:
        raise LiveWorkshopError(
            "Validation Evidence did not produce the required additive "
            "validation relationship"
        )
    return {
        "status": "ready",
        "capture_id": str(capture_id),
        "capture_key": capture["capture_key"],
        "wave": wave,
        "corpus_documents": counts["corpus_documents"],
        "wave_documents": counts["wave_documents"],
        "raw_counts": {
            key: counts[key]
            for key in counts
            if key.endswith("_rows")
        },
        "capture_validation": readiness,
        "search_index_health": health,
    }


def _cleanup_lab(database_url: str) -> None:
    with _connect(
        database_url,
        "workbench-live-cleanup",
        autocommit=True,
    ) as connection:
        active = connection.execute(
            """
            SELECT count(*) AS sessions
            FROM pg_stat_activity
            WHERE pid <> pg_backend_pid()
              AND datname = current_database()
              AND application_name LIKE 'workbench-live-%'
            """
        ).fetchone()["sessions"]
        if active:
            raise LiveWorkshopError(
                f"cannot clean lab schema while {active} live sessions remain"
            )
        connection.execute("DROP SCHEMA IF EXISTS workbench_lab CASCADE")


def _preflight(
    database_url: str,
    *,
    region: str,
    cluster_id: str,
    instance_id: str,
) -> dict[str, Any]:
    with _connect(
        database_url,
        "workbench-live-schema-preflight",
        autocommit=True,
    ) as connection:
        schema = connection.execute(
            """
            SELECT
              to_regclass('evidence.incident_capture_runs') IS NOT NULL
                AS incident_capture_runs,
              to_regclass('evidence.telemetry_evidence') IS NOT NULL
                AS telemetry_evidence,
              to_regprocedure('evidence.admit_evidence(jsonb)') IS NOT NULL
                AS admit_evidence,
              to_regprocedure('evidence.assert_live_capture_ready()') IS NOT NULL
                AS live_capture_ready,
              to_regprocedure('retrieval.assert_search_index_ready()') IS NOT NULL
                AS search_index_ready,
              to_regclass('proof.action_proposals') IS NOT NULL
                AS action_proposals,
              to_regprocedure('proof.observed_index_fingerprint(oid)') IS NOT NULL
                AS observed_index_fingerprint,
              to_regprocedure(
                'proof.attach_wave_b_receipt(uuid,uuid,uuid)'
              ) IS NOT NULL AS wave_b_receipt_attachment
            """
        ).fetchone()
    missing = [name for name, present in dict(schema).items() if not present]
    if missing:
        raise LiveWorkshopError(
            "core schema is incomplete; run `make schema` before the workshop. "
            f"Missing: {', '.join(missing)}"
        )

    os.environ["DATABASE_URL"] = database_url
    os.environ["AWS_REGION"] = region
    from backend.app.config import get_settings
    from backend.app.embeddings import bedrock_embedding

    get_settings.cache_clear()
    settings = get_settings()
    if settings.embed_provider != "bedrock":
        raise LiveWorkshopError(
            "EMBED_PROVIDER must be bedrock; hash embeddings are not permitted"
        )
    aws = preflight_aws_observability(
        database_url=database_url,
        region=region,
        cluster_id=cluster_id,
        instance_id=instance_id,
    )
    vector = bedrock_embedding(
        "participant-induced Aurora PostgreSQL write stall",
        dim=settings.embed_dim,
        model_id=settings.bedrock_embedding_model,
        region=region,
        input_type="search_document",
    )
    if len(vector) != settings.embed_dim:
        raise LiveWorkshopError(
            f"Cohere preflight returned {len(vector)} dimensions; "
            f"expected {settings.embed_dim}"
        )
    return {
        **aws,
        "embedding_model": settings.bedrock_embedding_model,
        "embedding_dimensions": len(vector),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Induce one live Aurora PostgreSQL write stall, capture its evidence, "
            "build Cohere embeddings, and publish the indexing receipt."
        )
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        required=os.getenv("DATABASE_URL") is None,
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
    )
    parser.add_argument(
        "--db-cluster-identifier",
        default=os.getenv("AURORA_CLUSTER_IDENTIFIER"),
        required=os.getenv("AURORA_CLUSTER_IDENTIFIER") is None,
    )
    parser.add_argument(
        "--db-instance-identifier",
        default=os.getenv("AURORA_INSTANCE_IDENTIFIER"),
        required=os.getenv("AURORA_INSTANCE_IDENTIFIER") is None,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/generated/incident-lab"),
    )
    parser.add_argument(
        "--wave",
        choices=("A", "B"),
        default="A",
        help="admit diagnostic evidence in Lab 1 or validation evidence in Lab 4",
    )
    parser.add_argument(
        "--proposal-id",
        help=(
            "Lab 3 action proposal the participant reviewed; required for "
            "Validation Evidence so the approval and execution are tied to one recommendation"
        ),
    )
    parser.add_argument(
        "--approved-by",
        help=(
            "name or role of the human who approved the stored proposal; "
            "required for Validation Evidence"
        ),
    )
    parser.add_argument(
        "--observed-index",
        help=(
            "optional schema-qualified index name when the participant created "
            "a differently shaped index and the catalog fallback is ambiguous"
        ),
    )
    parser.add_argument(
        "--drop-lab-schema",
        action="store_true",
        help="explicitly remove workbench_lab after a completed rehearsal",
    )
    return parser


def _wave_b_payload_path(output_dir: Path, wave_a_capture_id: str) -> Path:
    return output_dir / f"wave-b-for-{wave_a_capture_id}.json"


def _load_replay_payload(path: Path, *, incident_key: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LiveWorkshopError(
            f"could not reuse Validation Evidence payload {path}: {error}"
        ) from error
    if (
        payload.get("wave") != "B"
        or payload.get("incident_key") != incident_key
        or not payload.get("capture", {}).get("capture_id")
    ):
        raise LiveWorkshopError(
            f"{path} is not the saved Validation Evidence payload for {incident_key}"
        )
    return payload


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.wave == "B" and not args.proposal_id:
            raise LiveWorkshopError(
                "Validation Evidence requires --proposal-id from the Lab 3 Hybrid Retrieval "
                "Agent proposal"
            )
        if args.wave == "B" and not args.approved_by:
            raise LiveWorkshopError(
                "Validation Evidence requires --approved-by to record the human approval"
            )

        capture_id = uuid.uuid4()

        if args.wave == "A":
            preflight = _preflight(
                args.database_url,
                region=args.region,
                cluster_id=args.db_cluster_identifier,
                instance_id=args.db_instance_identifier,
            )
            workload, before_statement = _prepare_lab_for_wave(
                args.database_url,
                capture_id,
                wave="A",
            )
            print(
                f"Investigation Evidence preflight: {preflight['cluster_id']} / "
                f"{preflight['instance_id']}; "
                f"{workload['observed_customer_count']} customers, "
                f"{workload['observed_row_count']} orders"
            )
            run_suffix = capture_id.hex[-8:].upper()
            payload_path = args.output_dir / f"wave-a-{run_suffix}.json"
            collision = run_migration_collision(args.database_url)
            aws_capture = collect_aws_observability(
                database_url=args.database_url,
                region=args.region,
                cluster_id=args.db_cluster_identifier,
                instance_id=args.db_instance_identifier,
                start_time=datetime.fromisoformat(collision.started_at),
                end_time=datetime.fromisoformat(collision.ended_at),
            )
            payload, ingest_receipt = admit_wave_a(
                args.database_url,
                capture_id=capture_id,
                workload=workload,
                before_statement=before_statement,
                collision=collision,
                aws_capture=aws_capture,
                payload_path=payload_path,
            )
        else:
            workload, _before_statement = _prepare_lab_for_wave(
                args.database_url,
                capture_id,
                wave="B",
            )
            with _connect(
                args.database_url,
                "workbench-live-wave-b-context",
                autocommit=True,
            ) as connection:
                wave_a = _assert_wave_a_corpus_present(connection)
                proposal = _action_proposal(
                    connection,
                    args.proposal_id,
                    incident_key=wave_a["incident_key"],
                )
                started_at = connection.execute(
                    "SELECT clock_timestamp() AS captured_at"
                ).fetchone()["captured_at"]
                observed = _resolve_observed_index(
                    connection,
                    proposal=proposal,
                    observed_index_name=args.observed_index,
                )
                if observed is None:
                    completed_at = connection.execute(
                        "SELECT clock_timestamp() AS captured_at"
                    ).fetchone()["captured_at"]
                    record_action_execution(
                        connection,
                        proposal_id=proposal["proposal_id"],
                        approved_by=args.approved_by,
                        observed_index_oid=None,
                        outcome="failed",
                        outcome_detail=(
                            "no non-primary index exists on workbench_lab.orders "
                            "for Aurora to validate"
                        ),
                        started_at=started_at,
                        completed_at=completed_at,
                        plan_before_checkpoint="before_analyze",
                        plan_after_checkpoint=None,
                        wave_b_capture_id=None,
                        wave_b_ingest_id=None,
                    )
                    raise LiveWorkshopError(
                        "no participant-created index was found. The failed "
                        "execution is recorded; correct the DDL and rerun Validation Evidence."
                    )
                if observed.fingerprint != proposal["proposed_fingerprint"]:
                    completed_at = connection.execute(
                        "SELECT clock_timestamp() AS captured_at"
                    ).fetchone()["captured_at"]
                    execution_id = record_action_execution(
                        connection,
                        proposal_id=proposal["proposal_id"],
                        approved_by=args.approved_by,
                        observed_index_oid=observed.oid,
                        outcome="succeeded",
                        outcome_detail=(
                            "Aurora catalog fingerprint did not match the "
                            "approved proposal"
                        ),
                        started_at=started_at,
                        completed_at=completed_at,
                        plan_before_checkpoint="before_analyze",
                        plan_after_checkpoint=None,
                        wave_b_capture_id=None,
                        wave_b_ingest_id=None,
                    )
                    raise LiveWorkshopError(
                        "the participant-created index does not match the "
                        f"approved proposal (execution {execution_id}). Compare "
                        "the proposed and observed fingerprints, correct the "
                        "index, and rerun Validation Evidence."
                    )
                plan_checkpoints = tuple(
                    capture_plan_checkpoints(
                        connection,
                        tier=3,
                        index_oid=observed.oid,
                    )
                )
                completed_at = connection.execute(
                    "SELECT clock_timestamp() AS captured_at"
                ).fetchone()["captured_at"]
                execution_id = record_action_execution(
                    connection,
                    proposal_id=proposal["proposal_id"],
                    approved_by=args.approved_by,
                    observed_index_oid=observed.oid,
                    outcome="succeeded",
                    outcome_detail=None,
                    started_at=started_at,
                    completed_at=completed_at,
                    plan_before_checkpoint="before_analyze",
                    plan_after_checkpoint="after_index",
                    wave_b_capture_id=None,
                    wave_b_ingest_id=None,
                )

            # Record the human action before any optional AWS or Bedrock operation.
            # A successful CREATE INDEX must remain visible even if admission later
            # fails because a supplemental service is unavailable.
            preflight = _preflight(
                args.database_url,
                region=args.region,
                cluster_id=args.db_cluster_identifier,
                instance_id=args.db_instance_identifier,
            )
            print(
                f"Validation Evidence preflight: {preflight['cluster_id']} / "
                f"{preflight['instance_id']}; "
                f"{workload['observed_customer_count']} customers, "
                f"{workload['observed_row_count']} orders"
            )
            payload_path = _wave_b_payload_path(
                args.output_dir,
                str(wave_a["capture_id"]),
            )
            if payload_path.exists():
                payload = _load_replay_payload(
                    payload_path,
                    incident_key=wave_a["incident_key"],
                )
                capture_id = uuid.UUID(payload["capture"]["capture_id"])
                ingest_receipt = _admit_evidence(args.database_url, payload)
            else:
                aws_capture = collect_aws_observability(
                    database_url=args.database_url,
                    region=args.region,
                    cluster_id=args.db_cluster_identifier,
                    instance_id=args.db_instance_identifier,
                    start_time=started_at,
                    end_time=completed_at,
                )
                payload, ingest_receipt = admit_wave_b(
                    args.database_url,
                    capture_id=capture_id,
                    workload=workload,
                    incident_key=wave_a["incident_key"],
                    index_definition=observed.definition,
                    plan_checkpoints=plan_checkpoints,
                    started_at=str(started_at),
                    ended_at=str(completed_at),
                    aws_capture=aws_capture,
                    payload_path=payload_path,
                )
            _attach_wave_b_receipt(
                args.database_url,
                execution_id=execution_id,
                capture_id=capture_id,
                ingest_receipt=ingest_receipt,
            )

        run_suffix = payload["capture"]["run_suffix"]
        index_result = _build_search_index(
            args.database_url,
            run_suffix=run_suffix,
            output_dir=args.output_dir,
        )
        receipt = {
            **_verify_wave(
                args.database_url,
                capture_id=capture_id,
                wave=args.wave,
                bundle_uri=payload["source"]["uri"],
            ),
            **_receipt_identifiers(payload),
            "ingest_receipt": ingest_receipt,
            "index_result": index_result,
            "payload_path": str(payload_path),
        }
        if args.wave == "B":
            receipt.update(
                {
                    "proposal_id": args.proposal_id,
                    "action_execution_id": execution_id,
                    "approved_by": args.approved_by,
                }
            )
        receipt_path = args.output_dir / f"receipt-{args.wave.lower()}-{run_suffix}.json"
        _write_atomic(receipt_path, receipt)
        if args.wave == "A":
            _materialize_wave_a_exercises(receipt, output_dir=args.output_dir)
        print(json.dumps(receipt, indent=2, default=str))
        capture_label = (
            "Investigation Evidence"
            if args.wave == "A"
            else "Validation Evidence"
        )
        print(f"\n{capture_label.upper()} READY: {receipt_path}")
        if args.wave == "B":
            print(
                "\nyou built the trusted context layer required by a "
                "fleet-scale database agent."
            )
        if args.drop_lab_schema:
            _cleanup_lab(args.database_url)
            print("workbench_lab cleanup complete")
        return 0
    except (
        BotoCoreError,
        ClientError,
        LiveWorkshopError,
        OSError,
        psycopg.Error,
        requests.RequestException,
        ValueError,
    ) as error:
        print(f"\nLIVE WORKSHOP FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
