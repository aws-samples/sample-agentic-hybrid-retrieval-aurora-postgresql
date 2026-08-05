#!/usr/bin/env python3
"""Run, capture, admit, and index one participant-induced Aurora incident."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from labs.incident.capture_observability import (  # noqa: E402
    preflight_aws_observability,
    _write_atomic,
)


OBSERVATION_COUNT = 30
WRITER_COUNT = 6
READER_COUNT = 2
LAB_CUSTOMER_ROWS = 5_000
LAB_ROWS = 3_000_000
SOURCE_SYSTEM = "pg_incident_capture"
RELATION_NAME = "workbench_lab.orders"
INDEX_NAME = "workbench_lab.idx_orders_customer_created"


class LiveWorkshopError(RuntimeError):
    """Raised when a live checkpoint does not prove the workshop contract."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _checkpoint(number: int, title: str, detail: str) -> None:
    print(f"\n[{number}/8] {title}")
    print(detail)


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


# Performance Insights substitutes this for query text it cannot resolve. The
# row is a real observation, but it carries no statement to protect.
_PI_UNRESOLVED_STATEMENT = "unknown"


def _measured_visibility(structured: dict[str, Any]) -> str:
    """Classify one captured observation by what the capture actually contains.

    Performance Insights returns the normalized query text for its top-SQL
    dimension and withholds it for top-wait. Query text is the one thing in this
    capture that a real operator would restrict, so the classification reads the
    captured payload instead of labelling rows by hand.

    Args:
        structured: The measured payload for one evidence record.

    Returns:
        ``restricted`` when the capture carries resolved query text, otherwise
        ``workshop``.
    """
    statement = structured.get("statement")
    if not isinstance(statement, str):
        return "workshop"
    normalized = statement.strip()
    if not normalized or normalized.lower() == _PI_UNRESOLVED_STATEMENT:
        return "workshop"
    return "restricted"


def _record(
    *,
    external_key: str,
    title: str,
    source_uri: str,
    occurred_at: Any,
    available_at: Any,
    body: str,
    structured: dict[str, Any],
) -> dict[str, Any]:
    return {
        "external_key": external_key,
        "title": title,
        "source_uri": source_uri,
        "occurred_at": occurred_at,
        "available_at": available_at,
        "acl": {"visibility": _measured_visibility(structured)},
        "body": body,
        "structured": structured,
    }


def _telemetry_documents(
    *,
    run_suffix: str,
    bundle_uri: str,
    incident_key: str,
    unsafe_change_key: str,
    safe_change_key: str,
    samples: list[dict[str, Any]],
    statements: list[dict[str, Any]],
    aws_capture: dict[str, Any],
    repair: dict[str, Any],
    available_at: datetime,
) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for index, sample in enumerate(samples):
        number = sample["observation_number"]
        observed_at = sample["captured_at"]
        observed_until = (
            samples[index + 1]["captured_at"]
            if index + 1 < len(samples)
            else observed_at
        )
        waiting = [
            row for row in sample["activity"]
            if row["application_name"].startswith("workbench-live-writer-")
        ]
        readers = [
            row for row in sample["activity"]
            if row["application_name"].startswith("workbench-live-reader-")
        ]
        blocker = next(
            row for row in sample["activity"]
            if row["application_name"] == "workbench-live-unsafe-index"
        )
        base = {
            "incident_external_key": incident_key,
            "change_external_key": unsafe_change_key,
            "observation_number": number,
            "observed_until": observed_until,
        }
        documents.append(
            _record(
                external_key=f"TEL-{run_suffix}-A{number:03d}",
                title=f"Activity window {number:02d}: six writers and two readers",
                source_uri=f"{bundle_uri}/telemetry/activity/{number:02d}",
                occurred_at=observed_at,
                available_at=available_at,
                body=(
                    f"Observation {number} measured {len(waiting)} active writers "
                    "waiting on Lock:relation, "
                    f"{len(readers)} active readers, and blocker PID "
                    f"{blocker['pid']} holding the ordinary index transaction."
                ),
                structured={
                    **base,
                    "telemetry_type": "activity_window",
                    "blocked_writer_pids": [row["pid"] for row in waiting],
                    "reader_pids": [row["pid"] for row in readers],
                    "blocking_pid": blocker["pid"],
                    "activity_rows": len(sample["activity"]),
                },
            )
        )
        lock_counts: dict[str, int] = {}
        for row in sample["locks"]:
            key = f"{row['mode']}:{'granted' if row['granted'] else 'waiting'}"
            lock_counts[key] = lock_counts.get(key, 0) + 1
        documents.append(
            _record(
                external_key=f"TEL-{run_suffix}-L{number:03d}",
                title=f"Lock topology {number:02d}: ShareLock blocked writers",
                source_uri=f"{bundle_uri}/telemetry/locks/{number:02d}",
                occurred_at=observed_at,
                available_at=available_at,
                body=(
                    f"Observation {number} measured one granted ShareLock, "
                    f"{WRITER_COUNT} waiting RowExclusiveLock rows, and "
                    f"{READER_COUNT} granted AccessShareLock rows on "
                    f"{RELATION_NAME}."
                ),
                structured={
                    **base,
                    "telemetry_type": "lock_topology",
                    "lock_counts": lock_counts,
                    "relation_name": RELATION_NAME,
                    "lock_rows": len(sample["locks"]),
                },
            )
        )
        blocking_pid = sample["blocking"][0]["blocking_pids"][0]
        documents.append(
            _record(
                external_key=f"TEL-{run_suffix}-B{number:03d}",
                title=f"Blocking chain {number:02d}: six writers to one DDL backend",
                source_uri=f"{bundle_uri}/telemetry/blocking/{number:02d}",
                occurred_at=observed_at,
                available_at=available_at,
                body=(
                    f"Observation {number} measured {WRITER_COUNT} writer "
                    f"backends blocked by PID {blocking_pid}; every "
                    "pg_blocking_pids result named the same ordinary-index backend."
                ),
                structured={
                    **base,
                    "telemetry_type": "blocking_chain",
                    "blocking_pid": blocking_pid,
                    "blocked_pids": [
                        row["blocked_pid"] for row in sample["blocking"]
                    ],
                    "blocking_rows": len(sample["blocking"]),
                },
            )
        )

    for number, statement in enumerate(statements, start=1):
        documents.append(
            _record(
                external_key=f"TEL-{run_suffix}-S{number:02d}",
                title=f"Statement phase {statement['phase']}: measured UPDATE totals",
                source_uri=f"{bundle_uri}/telemetry/statements/{statement['phase']}",
                occurred_at=statement["captured_at"],
                available_at=available_at,
                body=(
                    f"pg_stat_statements phase {statement['phase']} measured "
                    f"{statement['calls']} calls, {statement['rows']} rows, and "
                    f"{float(statement['total_exec_time']):.3f} ms total "
                    "execution time for live updates to workbench_lab.orders."
                ),
                structured={
                    "incident_external_key": incident_key,
                    "change_external_key": unsafe_change_key,
                    "telemetry_type": "statement_phase",
                    "observation_number": number,
                    "observed_until": statement["captured_at"],
                    "phase": statement["phase"],
                    "calls": statement["calls"],
                    "rows": statement["rows"],
                    "total_exec_time": statement["total_exec_time"],
                    "delta_from_before": statement.get("delta_from_before"),
                },
            )
        )

    for number, metric in enumerate(
        aws_capture["cloudwatch_metrics"],
        start=1,
    ):
        documents.append(
            _record(
                external_key=f"TEL-{run_suffix}-C{number:02d}",
                title=f"CloudWatch {metric['metric_name']} incident window",
                source_uri=(
                    f"{bundle_uri}/telemetry/cloudwatch/"
                    f"{metric['metric_name'].lower()}"
                ),
                occurred_at=metric["observed_at"],
                available_at=available_at,
                body=(
                    f"CloudWatch measured {metric['metric_name']} "
                    f"{metric['value']} {metric['unit']} for Aurora cluster "
                    f"{metric['dimension_value']} in the participant incident window."
                ),
                structured={
                    "incident_external_key": incident_key,
                    "change_external_key": unsafe_change_key,
                    "telemetry_type": "cloudwatch_metric",
                    "observation_number": number,
                    "observed_until": metric["observed_at"],
                    **{
                        key: metric[key]
                        for key in (
                            "metric_name",
                            "namespace",
                            "dimension_name",
                            "dimension_value",
                            "statistic",
                            "period_seconds",
                            "value",
                            "unit",
                        )
                    },
                },
            )
        )

    for number, observation in enumerate(
        aws_capture["database_insights"],
        start=1,
    ):
        if observation["evidence_type"] == "top_wait":
            description = (
                f"Performance Insights measured {observation['dimension_value']} "
                f"with DB load {float(observation['db_load'] or 0):.4f}."
            )
        else:
            description = (
                "Performance Insights measured live SQL with DB load "
                f"{float(observation['db_load'] or 0):.4f}: "
                f"{observation['statement']}"
            )
        documents.append(
            _record(
                external_key=f"TEL-{run_suffix}-P{number:02d}",
                title=(
                    "Performance Insights "
                    f"{observation['evidence_type'].replace('_', ' ')}"
                ),
                source_uri=f"{bundle_uri}/telemetry/pi/{number:02d}",
                occurred_at=observation["captured_at"],
                available_at=available_at,
                body=description,
                structured={
                    "incident_external_key": incident_key,
                    "change_external_key": unsafe_change_key,
                    "telemetry_type": "database_insights",
                    "observation_number": number,
                    "observed_until": observation["captured_at"],
                    **{
                        key: observation.get(key)
                        for key in (
                            "evidence_type",
                            "dimension",
                            "dimension_value",
                            "db_load",
                            "statement",
                            "query_id",
                            "source_api",
                        )
                    },
                },
            )
        )

    verification = repair["verification"]
    documents.append(
        _record(
            external_key=f"TEL-{run_suffix}-R01",
            title="Concurrent-index repair verification",
            source_uri=f"{bundle_uri}/telemetry/remediation/final",
            occurred_at=verification["verified_at"],
            available_at=available_at,
            body=(
                "CREATE INDEX CONCURRENTLY held ShareUpdateExclusiveLock while "
                "a RowExclusiveLock remained granted and fresh DML completed. "
                "The resulting index was ready, valid, and live with no waiting "
                "relation locks."
            ),
            structured={
                "incident_external_key": incident_key,
                "change_external_key": safe_change_key,
                "telemetry_type": "remediation_observation",
                "observation_number": 1,
                "observed_until": verification["verified_at"],
                "fresh_write": repair["fresh_write"],
                "verification": verification,
                "compatible_locks": repair["locks"],
            },
        )
    )
    if not 100 <= len(documents) <= 120:
        raise LiveWorkshopError(
            f"searchable evidence build created {len(documents)} telemetry documents; "
            "expected 100 to 120"
        )
    return documents


def build_live_payload(
    *,
    capture_id: uuid.UUID,
    database_identity: dict[str, Any],
    before: dict[str, Any],
    during: dict[str, Any],
    after: dict[str, Any],
    samples: list[dict[str, Any]],
    aws_capture: dict[str, Any],
    repair: dict[str, Any],
    incident_started_at: datetime,
    incident_ended_at: datetime,
) -> dict[str, Any]:
    run_suffix = capture_id.hex[-8:].upper()
    incident_key = f"INC-{run_suffix}"
    unsafe_change_key = f"CHG-{run_suffix}-01"
    safe_change_key = f"CHG-{run_suffix}-02"
    lock_key = f"LOCK-{run_suffix}-01"
    bundle_uri = f"workshop://participant/live-run/{capture_id}"
    verified_at = repair["verification"]["verified_at"]
    delta = {
        "calls": after["calls"] - before["calls"],
        "total_exec_time": after["total_exec_time"] - before["total_exec_time"],
        "rows": after["rows"] - before["rows"],
    }
    if delta["calls"] < WRITER_COUNT + 2 or delta["total_exec_time"] <= 0:
        raise LiveWorkshopError(
            f"pg_stat_statements delta is incomplete: {delta}"
        )
    statements = [
        before,
        during,
        {**after, "delta_from_before": delta},
    ]
    telemetry_documents = _telemetry_documents(
        run_suffix=run_suffix,
        bundle_uri=bundle_uri,
        incident_key=incident_key,
        unsafe_change_key=unsafe_change_key,
        safe_change_key=safe_change_key,
        samples=samples,
        statements=statements,
        aws_capture=aws_capture,
        repair=repair,
        available_at=verified_at,
    )
    first = samples[0]
    blocker = next(
        row for row in first["activity"]
        if row["application_name"] == "workbench-live-unsafe-index"
    )
    writer = next(
        row for row in first["activity"]
        if row["application_name"] == "workbench-live-writer-1"
    )
    blocker_lock = next(
        row for row in first["locks"]
        if row["pid"] == blocker["pid"]
    )
    writer_lock = next(
        row for row in first["locks"]
        if row["pid"] == writer["pid"]
    )
    blocking = next(
        row for row in first["blocking"]
        if row["blocked_pid"] == writer["pid"]
    )
    unsafe_statement = re.sub(r"\s+", " ", blocker["query"]).strip()
    safe_statement = (
        "CREATE INDEX CONCURRENTLY idx_orders_customer_created "
        "ON workbench_lab.orders(customer_id, created_at DESC)"
    )
    unsafe_summary = (
        f"Six writers waited on Lock:relation for RowExclusiveLock while PID "
        f"{blocker['pid']} held ShareLock from the ordinary CREATE INDEX. "
        "Two readers remained active throughout all 30 observations."
    )
    repair_summary = (
        "CREATE INDEX CONCURRENTLY used ShareUpdateExclusiveLock; a normal "
        "RowExclusiveLock remained granted, fresh DML completed, and the final "
        "index was ready, valid, and live."
    )
    raw_activity = [
        row for sample in samples for row in sample["activity"]
    ]
    raw_locks = [row for sample in samples for row in sample["locks"]]
    raw_blocking = [
        row for sample in samples for row in sample["blocking"]
    ]
    return _json_safe(
        {
            "schema": "admission payload v1",
            "kind": "incident_bundle",
            "source": {
                "system": SOURCE_SYSTEM,
                "uri": bundle_uri,
                "observation_window": {
                    "start": incident_started_at,
                    "end": incident_ended_at,
                },
            },
            "database": aws_capture["database"],
            "capture": {
                "capture_id": str(capture_id),
                "capture_key": f"CAP-{run_suffix}",
                "run_suffix": run_suffix,
                "capture_origin": "participant_induced",
                "relation_name": RELATION_NAME,
                "relation_oid": database_identity["relation_oid"],
                "configured_customer_count": LAB_CUSTOMER_ROWS,
                "observed_customer_count": database_identity[
                    "observed_customer_count"
                ],
                "configured_row_count": LAB_ROWS,
                "observed_row_count": database_identity["observed_row_count"],
                "table_size_bytes": database_identity["table_size_bytes"],
                "observation_count": OBSERVATION_COUNT,
                "writer_count": WRITER_COUNT,
                "reader_count": READER_COUNT,
                "capture_started_at": incident_started_at,
                "capture_ended_at": verified_at,
                "capture_tool_version": "workbench-live-orchestrator-v1",
                "manifest": {
                    "raw_activity_rows": len(raw_activity),
                    "raw_lock_rows": len(raw_locks),
                    "raw_blocking_rows": len(raw_blocking),
                    "telemetry_documents": len(telemetry_documents),
                    "aws_source_apis": aws_capture["capture_metadata"][
                        "source_apis"
                    ],
                    "db_resource_id": aws_capture["database"]["db_resource_id"],
                },
            },
            "telemetry": {
                "pg_stat_activity": raw_activity,
                "pg_locks": raw_locks,
                "pg_blocking_pids": raw_blocking,
                "pg_stat_statements": statements,
                "cloudwatch_metrics": aws_capture["cloudwatch_metrics"],
                "database_insights": aws_capture["database_insights"],
            },
            "records": {
                "incident": _record(
                    external_key=incident_key,
                    title="Participant-induced Aurora PostgreSQL write stall",
                    source_uri=f"{bundle_uri}/incident",
                    occurred_at=incident_started_at,
                    available_at=verified_at,
                    body=f"{unsafe_summary} {repair_summary}",
                    structured={
                        "severity": "SEV-3",
                        "status": "resolved",
                        "started_at": incident_started_at,
                        "mitigated_at": repair["fresh_write"]["updated_at"],
                        "resolved_at": verified_at,
                        "summary": unsafe_summary,
                        "impact_summary": (
                            "The participant measured six blocked lab writers; "
                            "no external records were used."
                        ),
                        "resolution": repair_summary,
                    },
                ),
                "changes": [
                    _record(
                        external_key=unsafe_change_key,
                        title="Measured ordinary CREATE INDEX that blocked writes",
                        source_uri=f"{bundle_uri}/change/unsafe",
                        occurred_at=blocker["query_start"],
                        available_at=verified_at,
                        body=(
                            f"{unsafe_statement} held granted ShareLock and "
                            "blocked six RowExclusiveLock requests."
                        ),
                        structured={
                            "incident_external_key": incident_key,
                            "change_role": "unsafe",
                            "relationship": "confirmed",
                            "rationale": (
                                "All 30 lock samples and 180 blocking-pid rows "
                                "named this DDL backend as the blocker."
                            ),
                            "change_type": "ddl",
                            "status": "rolled_back",
                            "started_at": blocker["query_start"],
                            "completed_at": incident_ended_at,
                            "owner_team": "workshop-participant",
                            "execution_sql": unsafe_statement,
                            "description": unsafe_summary,
                            "rollback_plan": (
                                "ROLLBACK the lab transaction to release "
                                "waiting writers and remove the ordinary index."
                            ),
                        },
                    ),
                    _record(
                        external_key=safe_change_key,
                        title="Measured concurrent-index repair",
                        source_uri=f"{bundle_uri}/change/repair",
                        occurred_at=repair["activity"][0]["query_start"],
                        available_at=verified_at,
                        body=f"{safe_statement}. {repair_summary}",
                        structured={
                            "incident_external_key": incident_key,
                            "change_role": "repair",
                            "relationship": "remediated",
                            "rationale": (
                                "The safe-phase lock capture, fresh UPDATE, and "
                                "final pg_index state all came from this run."
                            ),
                            "change_type": "ddl",
                            "status": "completed",
                            "started_at": repair["activity"][0]["query_start"],
                            "completed_at": verified_at,
                            "owner_team": "workshop-participant",
                            "execution_sql": safe_statement,
                            "description": repair_summary,
                            "rollback_plan": (
                                "DROP INDEX CONCURRENTLY "
                                "workbench_lab.idx_orders_customer_created "
                                "if final validation fails."
                            ),
                        },
                    ),
                ],
                "lock_evidence": _record(
                    external_key=lock_key,
                    title="First measured six-writer lock observation",
                    source_uri=f"{bundle_uri}/lock/primary",
                    occurred_at=first["captured_at"],
                    available_at=verified_at,
                    body=unsafe_summary,
                    structured={
                        "incident_external_key": incident_key,
                        "change_external_key": unsafe_change_key,
                        "captured_at": first["captured_at"],
                        "relation_name": RELATION_NAME,
                        "relation_oid": database_identity["relation_oid"],
                        "blocked_pid": writer["pid"],
                        "blocking_pid": blocker["pid"],
                        "blocked_state": writer["state"],
                        "blocked_query_start": writer["query_start"],
                        "wait_event_type": writer["wait_event_type"],
                        "wait_event": str(writer["wait_event"]).lower(),
                        "blocked_lock_mode": writer_lock["mode"],
                        "blocked_lock_granted": writer_lock["granted"],
                        "blocking_lock_mode": blocker_lock["mode"],
                        "blocking_lock_granted": blocker_lock["granted"],
                        "blocking_pids": blocking["blocking_pids"],
                        "blocking_pids_sql": blocking["literal_sql"],
                        "blocking_pids_output": blocking["literal_output"],
                        "blocked_statement": writer["query"],
                        "blocking_statement": blocker["query"],
                    },
                ),
                "telemetry_documents": telemetry_documents,
            },
        }
    )


def _admit_payload(database_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _connect(
        database_url,
        "workbench-live-admission",
        autocommit=True,
    ) as connection:
        receipt = connection.execute(
            "SELECT casework.admit_evidence(%s::jsonb) AS receipt",
            (Jsonb(payload),),
        ).fetchone()["receipt"]
    return receipt


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
    if cache_path.exists():
        raise LiveWorkshopError(
            f"run-scoped embedding cache already exists: {cache_path}"
        )
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


def _verify_live_run(
    database_url: str,
    *,
    capture_id: uuid.UUID,
    run_suffix: str,
    bundle_uri: str,
) -> dict[str, Any]:
    with _connect(
        database_url,
        "workbench-live-receipt",
        autocommit=True,
    ) as connection:
        row = connection.execute(
            """
            SELECT
              (
                SELECT count(*)
                FROM retrieval.documents document
                WHERE document.is_current
                  AND document.index_state = 'ready'
                  AND document.source_system = 'pg_incident_capture'
                  AND document.source_uri LIKE %s || '/%%'
              ) AS documents,
              (
                SELECT count(*)
                FROM casework.evidence_items item
                WHERE NOT item.is_deleted
                  AND (
                    item.source_system <> 'pg_incident_capture'
                    OR item.source_uri NOT LIKE %s || '/%%'
                  )
              ) AS foreign_documents,
              (
                SELECT count(*)
                FROM retrieval.chunks chunk
                WHERE chunk.is_current
              ) AS chunks,
              (
                SELECT count(*)
                FROM retrieval.chunks chunk
                WHERE chunk.is_current
                  AND chunk.embedding_state = 'ready'
                  AND chunk.embedding IS NOT NULL
              ) AS ready_embeddings,
              (
                SELECT count(*)
                FROM casework.pg_stat_activity_samples
                WHERE capture_id = %s
              ) AS activity_rows,
              (
                SELECT count(*)
                FROM casework.pg_lock_samples
                WHERE capture_id = %s
              ) AS lock_rows,
              (
                SELECT count(*)
                FROM casework.pg_blocking_pids_samples
                WHERE capture_id = %s
              ) AS blocking_rows,
              (
                SELECT count(*)
                FROM casework.pg_stat_statements_samples
                WHERE capture_id = %s
              ) AS statement_rows,
              (
                SELECT count(*)
                FROM casework.cloudwatch_metric_samples
                WHERE capture_id = %s
              ) AS metric_rows
            """,
            (
                bundle_uri,
                bundle_uri,
                capture_id,
                capture_id,
                capture_id,
                capture_id,
                capture_id,
            ),
        ).fetchone()
        capture = connection.execute(
            "SELECT casework.assert_live_capture_ready() AS receipt"
        ).fetchone()["receipt"]
        build = connection.execute(
            """
            SELECT *
            FROM retrieval.search_index_builds
            WHERE status = 'complete'
            ORDER BY completed_at DESC
            LIMIT 1
            """
        ).fetchone()
    counts = dict(row)
    raw_rows = sum(
        counts[name]
        for name in (
            "activity_rows",
            "lock_rows",
            "blocking_rows",
            "statement_rows",
            "metric_rows",
        )
    )
    if not 100 <= counts["documents"] <= 120:
        raise LiveWorkshopError(
            f"indexed document count {counts['documents']} is outside 100..120"
        )
    if counts["foreign_documents"] != 0:
        raise LiveWorkshopError("participant corpus contains another source or run")
    if not 100 <= counts["chunks"] <= 250:
        raise LiveWorkshopError(
            f"chunk count {counts['chunks']} is outside 100..250"
        )
    if counts["ready_embeddings"] != counts["chunks"]:
        raise LiveWorkshopError("not every current chunk has a live embedding")
    if not 600 <= raw_rows <= 1000:
        raise LiveWorkshopError(
            f"raw telemetry count {raw_rows} is outside 600..1000"
        )
    return {
        "status": "ready",
        "capture_id": str(capture_id),
        "run_suffix": run_suffix,
        "documents": counts["documents"],
        "chunks": counts["chunks"],
        "ready_embeddings": counts["ready_embeddings"],
        "raw_telemetry_rows": raw_rows,
        "raw_counts": {
            key: counts[key]
            for key in counts
            if key.endswith("_rows")
        },
        "capture_validation": capture,
        "search_index_build": dict(build),
    }


def _write_exercise_requests(
    output_dir: Path,
    *,
    incident_key: str,
    unsafe_change_key: str,
    repair_change_key: str,
    lock_key: str,
) -> dict[str, str]:
    exercise_dir = output_dir / "exercises"
    requests = {
        "lab2-filter-request.json": {
            "query": (
                "ordinary CREATE INDEX writer wait concurrent repair relation lock"
            ),
            "source_systems": [SOURCE_SYSTEM],
            "rerank": False,
            "limit": 12,
        },
        "lab2-fusion-request.json": {
            "query": (
                "Why did the writer wait on a relation lock during the ordinary "
                "index build, and how did the concurrent repair change that behavior?"
            ),
            "source_systems": [SOURCE_SYSTEM],
            "w_text": 2.0,
            "w_vector": 1.0,
            "w_trgm": 1.0,
            "rrf_k": 60,
            "rerank": False,
            "limit": 8,
        },
        "lab3-plan-request.json": {
            "question": (
                f"What caused the measured writer wait in {incident_key}, how did "
                f"{unsafe_change_key} block writes, how did {repair_change_key} "
                f"repair the behavior, and what did {lock_key} prove?"
            )
        },
        "lab3-traverse-request.json": {
            "seed_external_keys": [incident_key],
            "max_depth": 2,
        },
        "lab3-compare-request.json": {
            "external_keys": [
                incident_key,
                unsafe_change_key,
                repair_change_key,
                lock_key,
            ]
        },
    }
    written: dict[str, str] = {}
    for filename, request in requests.items():
        path = exercise_dir / filename
        _write_atomic(path, request)
        written[filename] = str(path)
    return written


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
        "--pi-wait-seconds",
        type=int,
        default=300,
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
        "LIVE WORKSHOP UNAVAILABLE: the retired relation-lock scenario was "
        "removed. The online migration driver is complete, but the lab-only "
        "pool-collision endpoint and condition-based hold controller are not "
        "installed yet.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
