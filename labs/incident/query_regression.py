"""Capture the measured query-plan regression before and after a human fix.

Investigation Evidence runs while the supporting index is absent, so it records the before- and
after-ANALYZE sequential scans. Validation Evidence can only run after the participant has
created the recommended index; it records the resulting index scan without
creating, dropping, or hiding any database state.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Any

import psycopg

from labs.incident.hold_controller import LiveWorkshopError


RECOMMENDED_INDEX_NAME = (
    "workbench_lab.idx_orders_priority_tier_created_at"
)
REFERENCE_QUERY = """
SELECT order_id, customer_id, created_at
FROM workbench_lab.orders
WHERE priority_tier = %s
ORDER BY created_at DESC
LIMIT 20
"""
WAVE_A_CHECKPOINTS = ("before_analyze", "after_analyze")
WAVE_B_CHECKPOINTS = ("after_index",)
_BUFFER_KEYS = (
    "Shared Hit Blocks",
    "Shared Read Blocks",
    "Shared Dirtied Blocks",
    "Shared Written Blocks",
)


@dataclass(frozen=True)
class PlanCheckpoint:
    """One observed EXPLAIN ANALYZE checkpoint from the participant database."""

    label: str
    plan_type: str
    execution_ms: float
    rows_returned: int
    rows_removed_by_filter: int
    buffers: int
    raw_explain: str


def _record_value(
    row: Mapping[str, Any] | tuple[Any, ...],
) -> Any:
    if isinstance(row, Mapping):
        return row["QUERY PLAN"]
    return row[0]


def _as_explain_report(value: Any) -> tuple[dict[str, Any], str]:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list) or len(value) != 1:
        raise LiveWorkshopError(
            "EXPLAIN JSON must contain exactly one query report"
        )
    report = value[0]
    if not isinstance(report, dict) or not isinstance(report.get("Plan"), dict):
        raise LiveWorkshopError(
            "EXPLAIN JSON report did not contain a plan object"
        )
    return report, json.dumps(value, sort_keys=True)


def _walk_plan(plan: Mapping[str, Any]):
    yield plan
    children = plan.get("Plans", [])
    if not isinstance(children, list):
        raise LiveWorkshopError("EXPLAIN JSON plan has a non-list Plans field")
    for child in children:
        if not isinstance(child, Mapping):
            raise LiveWorkshopError("EXPLAIN JSON plan has a non-object child")
        yield from _walk_plan(child)


def _scan_node(plan: Mapping[str, Any]) -> Mapping[str, Any]:
    for node in _walk_plan(plan):
        node_type = node.get("Node Type")
        if node_type in {"Seq Scan", "Index Scan"}:
            return node
    raise LiveWorkshopError(
        "EXPLAIN JSON did not contain a Seq Scan or Index Scan node"
    )


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LiveWorkshopError(
            f"EXPLAIN JSON field {field!r} was not numeric: {value!r}"
        )
    return int(value)


def _as_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LiveWorkshopError(
            f"EXPLAIN JSON field {field!r} was not numeric: {value!r}"
        )
    return float(value)


def _capture_checkpoint(
    conn: psycopg.Connection,
    *,
    label: str,
    tier: int,
) -> PlanCheckpoint:
    row = conn.execute(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + REFERENCE_QUERY,
        (tier,),
    ).fetchone()
    if row is None:
        raise LiveWorkshopError(
            f"{label} EXPLAIN did not return a query report"
        )
    report, raw_explain = _as_explain_report(_record_value(row))
    plan = report["Plan"]
    scan = _scan_node(plan)
    plan_type = scan["Node Type"]
    if not isinstance(plan_type, str):
        raise LiveWorkshopError(
            f"{label} EXPLAIN scan node had a non-text Node Type"
        )
    return PlanCheckpoint(
        label=label,
        plan_type=plan_type,
        execution_ms=_as_float(report.get("Execution Time"), "Execution Time"),
        rows_returned=_as_int(plan.get("Actual Rows"), "Actual Rows"),
        rows_removed_by_filter=_as_int(
            scan.get("Rows Removed by Filter", 0),
            "Rows Removed by Filter",
        ),
        buffers=sum(
            _as_int(plan.get(key, 0), key)
            for key in _BUFFER_KEYS
        ),
        raw_explain=raw_explain,
    )


def _index_exists(
    conn: psycopg.Connection,
    *,
    index_oid: int | None = None,
) -> bool:
    if index_oid is not None:
        row = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_index WHERE indexrelid = %s::oid) "
            "AS index_exists",
            (index_oid,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT to_regclass(%s) IS NOT NULL AS index_exists",
            (RECOMMENDED_INDEX_NAME,),
        ).fetchone()
    if row is None:
        raise LiveWorkshopError("index-existence query returned no result")
    if isinstance(row, Mapping):
        return bool(row["index_exists"])
    return bool(row[0])


def _assert_shape(checkpoint: PlanCheckpoint, expected: str) -> None:
    if checkpoint.plan_type != expected:
        raise LiveWorkshopError(
            f"{checkpoint.label} expected {expected}, observed "
            f"{checkpoint.plan_type}"
        )


def capture_plan_checkpoints(
    conn: psycopg.Connection,
    *,
    tier: int,
    index_oid: int | None = None,
) -> list[PlanCheckpoint]:
    """Capture only the checkpoint(s) that can truthfully exist now.

    The supporting index is the time boundary. Before it exists, capture Investigation Evidence,
    run ANALYZE, and prove the scan remains sequential. Once a participant has
    created it, capture only the Validation Evidence index-scan checkpoint.
    """
    if _index_exists(conn, index_oid=index_oid):
        after_index = _capture_checkpoint(
            conn,
            label=WAVE_B_CHECKPOINTS[0],
            tier=tier,
        )
        _assert_shape(after_index, "Index Scan")
        return [after_index]

    before_analyze = _capture_checkpoint(
        conn,
        label=WAVE_A_CHECKPOINTS[0],
        tier=tier,
    )
    _assert_shape(before_analyze, "Seq Scan")
    conn.execute("ANALYZE workbench_lab.orders")
    after_analyze = _capture_checkpoint(
        conn,
        label=WAVE_A_CHECKPOINTS[1],
        tier=tier,
    )
    _assert_shape(after_analyze, "Seq Scan")
    return [before_analyze, after_analyze]
