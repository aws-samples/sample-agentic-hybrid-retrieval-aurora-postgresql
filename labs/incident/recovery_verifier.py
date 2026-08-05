"""Recovery verification for the condition-based migration collision.

Committing the backfill releases its row locks, but that fact alone does not
prove the application recovered. This module independently verifies the
database-side blocker, the pool's own counters, the original request outcomes,
and a new write through the same API pool.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, fields
import os
from typing import Any, Protocol

import psycopg
import requests

from backend.app.config import get_settings
from labs.incident.hold_controller import LiveWorkshopError


class WriteOutcome(Protocol):
    """The subset of B2's measured response used by recovery verification."""

    outcome: str


PoolStatus = Callable[[], Mapping[str, Any]]
FreshWrite = Callable[[], WriteOutcome | Mapping[str, Any]]


@dataclass(frozen=True)
class RecoveryProof:
    """Seven independently inspectable recovery assertions."""

    backfill_no_longer_blocking: bool = True
    pool_fully_available: bool = True
    no_requests_waiting: bool = True
    no_sessions_blocked: bool = True
    pool_timeout_observed: bool = True
    blocked_writers_drained: bool = True
    fresh_write_committed: bool = True


_BACKFILL_NO_LONGER_BLOCKING_SQL = """
SELECT NOT EXISTS (
  SELECT 1
  FROM pg_stat_activity activity
  WHERE activity.datname = current_database()
    AND %s = ANY(pg_blocking_pids(activity.pid))
) AS recovered
"""

_NO_TAGGED_LOCK_WAITERS_SQL = """
SELECT NOT EXISTS (
  SELECT 1
  FROM pg_stat_activity activity
  WHERE activity.datname = current_database()
    AND activity.application_name LIKE 'workbench-lab-%'
    AND activity.wait_event_type = 'Lock'
) AS recovered
"""


def _required_int(status: Mapping[str, Any], key: str) -> int:
    value = status.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LiveWorkshopError(
            f"pool-status response omitted numeric {key!r}: {dict(status)!r}"
        )
    return int(value)


def _no_longer_blocking(conn: psycopg.Connection, backfill_pid: int) -> bool:
    row = conn.execute(
        _BACKFILL_NO_LONGER_BLOCKING_SQL,
        (backfill_pid,),
    ).fetchone()
    if row is None:
        raise LiveWorkshopError(
            "recovery query returned no backfill-blocking result"
        )
    if isinstance(row, Mapping):
        return bool(row["recovered"])
    return bool(row[0])


def _no_sessions_blocked(conn: psycopg.Connection) -> bool:
    row = conn.execute(_NO_TAGGED_LOCK_WAITERS_SQL).fetchone()
    if row is None:
        raise LiveWorkshopError(
            "recovery query returned no tagged-session result"
        )
    if isinstance(row, Mapping):
        return bool(row["recovered"])
    return bool(row[0])


def _pool_fully_available(status: Mapping[str, Any]) -> bool:
    return _required_int(status, "pool_available") == _required_int(
        status,
        "pool_size",
    )


def _no_requests_waiting(status: Mapping[str, Any]) -> bool:
    return _required_int(status, "requests_waiting") == 0


def _outcome_name(value: WriteOutcome | Mapping[str, Any]) -> str | None:
    if isinstance(value, Mapping):
        outcome = value.get("outcome")
    else:
        outcome = getattr(value, "outcome", None)
    return outcome if isinstance(outcome, str) else None


def evaluate_drain(
    write_outcomes: Iterable[WriteOutcome | Mapping[str, Any]],
    *,
    pool_max_size: int,
) -> bool:
    """Require every pool-held writer to drain and no statement wait to expire."""
    outcomes = [_outcome_name(item) for item in write_outcomes]
    committed = outcomes.count("committed")
    statement_timeouts = outcomes.count("statement_timeout")
    return (
        committed == pool_max_size
        and statement_timeouts == 0
    )


def failed_assertions(proof: RecoveryProof) -> list[str]:
    """Return failed assertions in declaration order for an actionable error."""
    return [
        field.name
        for field in fields(proof)
        if not getattr(proof, field.name)
    ]


def _fresh_write_from_api() -> Mapping[str, Any]:
    base_url = os.getenv("RETRIEVAL_API_URL", "http://127.0.0.1:8000").rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise LiveWorkshopError(
            "RETRIEVAL_API_URL must be an http(s) URL for the lab API"
        )
    order_id = get_settings().db_pool_max_size + 1
    try:
        response = requests.post(
            f"{base_url}/v1/lab/hot-write",
            json={"order_id": order_id},
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise LiveWorkshopError(
            "fresh post-recovery hot write did not return a measured result"
        ) from error
    if not isinstance(payload, Mapping):
        raise LiveWorkshopError(
            f"fresh hot-write response was not an object: {payload!r}"
        )
    return payload


def verify_recovery(
    conn: psycopg.Connection,
    *,
    backfill_pid: int,
    pool_status: PoolStatus,
    write_outcomes: Iterable[WriteOutcome | Mapping[str, Any]],
    fresh_write: FreshWrite | None = None,
) -> RecoveryProof:
    """Verify each required recovery condition and name every failed one."""
    outcomes = tuple(write_outcomes)
    status = pool_status()
    fresh_result = (
        fresh_write()
        if fresh_write is not None
        else _fresh_write_from_api()
    )
    proof = RecoveryProof(
        backfill_no_longer_blocking=_no_longer_blocking(conn, backfill_pid),
        pool_fully_available=_pool_fully_available(status),
        no_requests_waiting=_no_requests_waiting(status),
        no_sessions_blocked=_no_sessions_blocked(conn),
        pool_timeout_observed=any(
            _outcome_name(item) == "pool_timeout"
            for item in outcomes
        ),
        blocked_writers_drained=evaluate_drain(
            outcomes,
            pool_max_size=get_settings().db_pool_max_size,
        ),
        fresh_write_committed=_outcome_name(fresh_result) == "committed",
    )
    failures = failed_assertions(proof)
    if failures:
        raise LiveWorkshopError(
            "recovery verification failed on: " + ", ".join(failures)
        )
    return proof
