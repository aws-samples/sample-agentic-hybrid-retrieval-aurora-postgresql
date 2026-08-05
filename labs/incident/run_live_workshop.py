#!/usr/bin/env python3
"""Run, capture, admit, and index one participant-induced Aurora incident."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import os
from pathlib import Path
import sys
from threading import Barrier, BrokenBarrierError
import time
from typing import Any
import uuid

import psycopg
from psycopg.rows import dict_row
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.lab_routes import HotWriteResult  # noqa: E402
from labs.incident.capture_observability import (  # noqa: E402
    preflight_aws_observability,
    _write_atomic,
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
    return dict(row)


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
        FROM casework.evidence_items
        WHERE NOT is_deleted
        """
    ).fetchone()["records"]
    if existing:
        raise LiveWorkshopError(
            "the participant corpus is not empty; use a fresh workshop "
            "database so this run cannot mix with prior evidence"
        )


def _create_lab_workload(connection: psycopg.Connection) -> None:
    connection.execute("DROP SCHEMA IF EXISTS workbench_lab CASCADE")
    connection.execute("CREATE SCHEMA workbench_lab")
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


def _assert_lab_workload_ready(state: dict[str, Any] | None) -> dict[str, Any]:
    if state is None:
        raise LiveWorkshopError(
            "the operational workload is missing; run `make prepare-workload`"
        )
    if (
        state["observed_row_count"] != LAB_ROWS
        or state["canonical_rows"] != LAB_ROWS
        or state["observed_customer_count"] != LAB_CUSTOMER_ROWS
        or state["minimum_customer_id"] != 1
        or state["maximum_customer_id"] != LAB_CUSTOMER_ROWS
        or state["referenced_customers"] != LAB_CUSTOMER_ROWS
        or state["orphan_order_count"] != 0
        or state["minimum_order_id"] != 1
        or state["maximum_order_id"] != LAB_ROWS
        or state["target_index_exists"]
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


def run_migration_collision(
    database_url: str,
    *,
    api_url: str | None = None,
    hold_seconds: float = 12.0,
    max_attempt_seconds: float = 90.0,
) -> MigrationCollision:
    """Induce and prove the migration collision without admitting evidence.

    The later Wave A admission task consumes this measured result. Keeping this
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

    backfill = open_backfill(database_url)
    backfill_pid = backfill.pid
    backfill_duration_seconds = backfill.duration_seconds
    backfill_rows_updated = backfill.rows_updated
    executor = ThreadPoolExecutor(
        max_workers=request_count,
        thread_name_prefix="workbench-hot-write",
    )
    futures = []
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
            )

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


def _prepare_lab(
    database_url: str,
    capture_id: uuid.UUID,
) -> tuple[dict[str, Any], dict[str, Any]]:
    with _connect(
        database_url,
        "workbench-live-setup",
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
        _assert_empty_evidence_store(connection)

        workload = _assert_lab_workload_ready(_lab_workload_state(connection))
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
              to_regclass('casework.incident_capture_runs') IS NOT NULL
                AS incident_capture_runs,
              to_regclass('casework.telemetry_evidence') IS NOT NULL
                AS telemetry_evidence,
              to_regprocedure('casework.admit_evidence(jsonb)') IS NOT NULL
                AS admit_evidence,
              to_regprocedure('casework.assert_live_capture_ready()') IS NOT NULL
                AS live_capture_ready,
              to_regprocedure('retrieval.assert_search_index_ready()') IS NOT NULL
                AS search_index_ready
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
        "--keep-lab-schema",
        action="store_true",
        help="retain workbench_lab after the receipt is verified",
    )
    return parser


def main() -> int:
    _parser().parse_args()
    print(
        "LIVE WORKSHOP UNAVAILABLE: the online-migration collision and "
        "condition-based hold controller are installed, but recovery "
        "verification, evidence construction, and two-wave admission are not "
        "complete yet.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
