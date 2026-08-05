"""Condition-based hold controller for the induced migration incident.

The hold begins only after consecutive polls prove both sides of the failure:
the application pool has no available connections and the connections it does
hold are blocked by the open backfill transaction. The extra requests waiting
for pool checkout never appear in PostgreSQL, so the two signals must be
measured separately and in the same poll.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
from typing import Any

import psycopg

from backend.app.config import get_settings


HOT_WRITE_APPLICATION_NAME = "workbench-lab-api-hot-write"


class LiveWorkshopError(RuntimeError):
    """Raised when a live checkpoint does not prove the workshop contract."""


@dataclass(frozen=True)
class PollSample:
    """One raw controller poll, retained for later evidence admission."""

    pool_size: int
    pool_max: int
    pool_available: int
    requests_waiting: int
    blocked_session_count: int
    observed_at: str = ""


@dataclass(frozen=True)
class StateChange:
    """A meaningful change in controller state, never one entry per poll."""

    label: str
    detail: str
    observed_at: str


@dataclass
class HoldProof:
    """Raw polling history plus the proven observation hold."""

    samples: list[PollSample] = field(default_factory=list)
    state_changes: list[StateChange] = field(default_factory=list)
    proven_at: str = ""
    hold_seconds: float = 0.0


PoolStatus = Callable[[], Mapping[str, Any]]
SampleObserver = Callable[[psycopg.Connection, PollSample], None]

_BLOCKED_SESSION_COUNT_SQL = """
SELECT count(*)::int AS blocked_session_count
FROM pg_stat_activity activity
WHERE activity.datname = current_database()
  AND activity.application_name = %s
  AND activity.wait_event_type = 'Lock'
  AND %s = ANY(pg_blocking_pids(activity.pid))
  AND EXISTS (
    SELECT 1
    FROM pg_locks waiting_lock
    WHERE waiting_lock.pid = activity.pid
      AND NOT waiting_lock.granted
      AND waiting_lock.locktype = 'transactionid'
  )
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _proves(sample: PollSample, *, expected_blocked_sessions: int) -> bool:
    """Return whether one sample proves every hold condition together."""
    return (
        sample.pool_size == sample.pool_max
        and sample.pool_available == 0
        and sample.requests_waiting >= 2
        and sample.blocked_session_count == expected_blocked_sessions
    )


def evaluate_samples(
    samples: list[PollSample],
    *,
    expected_blocked_sessions: int,
    required_samples: int = 3,
) -> bool:
    """Require consecutive proving samples; a non-proving poll resets the streak."""
    if required_samples < 1:
        raise ValueError("required_samples must be at least one")
    if len(samples) < required_samples:
        return False
    return all(
        _proves(sample, expected_blocked_sessions=expected_blocked_sessions)
        for sample in samples[-required_samples:]
    )


def describe_failure(
    samples: list[PollSample], *, expected_blocked_sessions: int
) -> str:
    """Describe the unmet condition without collapsing it into a generic timeout."""
    if not samples:
        return "no pool or PostgreSQL poll sample was collected"
    if not any(
        sample.blocked_session_count == expected_blocked_sessions
        for sample in samples
    ):
        peak = max(sample.blocked_session_count for sample in samples)
        return (
            f"only {peak} of {expected_blocked_sessions} tagged sessions were "
            "ever blocked on the backfill"
        )
    if not any(sample.pool_size == sample.pool_max for sample in samples):
        peak = max(sample.pool_size for sample in samples)
        return (
            "pool never reached its configured maximum size: "
            f"peaked at {peak} of {samples[0].pool_max}"
        )
    if not any(sample.pool_available == 0 for sample in samples):
        lowest = min(sample.pool_available for sample in samples)
        return f"pool_available stayed non-zero: lowest observed was {lowest}"
    if not any(sample.requests_waiting >= 2 for sample in samples):
        peak = max(sample.requests_waiting for sample in samples)
        return f"requests_waiting never reached 2: peaked at {peak}"

    longest_streak = 0
    streak = 0
    for sample in samples:
        if _proves(sample, expected_blocked_sessions=expected_blocked_sessions):
            streak += 1
            longest_streak = max(longest_streak, streak)
        else:
            streak = 0
    return (
        "the combined pool and lock condition did not remain true for "
        f"three consecutive samples; longest proving streak was {longest_streak}"
    )


def _required_int(status: Mapping[str, Any], key: str) -> int:
    value = status.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LiveWorkshopError(
            f"pool-status response omitted numeric {key!r}: {dict(status)!r}"
        )
    return int(value)


def _blocked_session_count(
    conn: psycopg.Connection,
    *,
    backfill_pid: int,
) -> int:
    row = conn.execute(
        _BLOCKED_SESSION_COUNT_SQL,
        (HOT_WRITE_APPLICATION_NAME, backfill_pid),
    ).fetchone()
    if row is None:
        raise LiveWorkshopError(
            "blocked-session query returned no count for the current database"
        )
    if isinstance(row, Mapping):
        return int(row["blocked_session_count"])
    return int(row[0])


def _sample(
    conn: psycopg.Connection,
    *,
    backfill_pid: int,
    pool_max: int,
    pool_status: PoolStatus,
) -> PollSample:
    status = pool_status()
    return PollSample(
        pool_size=_required_int(status, "pool_size"),
        pool_max=pool_max,
        pool_available=_required_int(status, "pool_available"),
        requests_waiting=_required_int(status, "requests_waiting"),
        blocked_session_count=_blocked_session_count(
            conn,
            backfill_pid=backfill_pid,
        ),
        observed_at=_utc_now(),
    )


def _state_detail(sample: PollSample, *, expected_blocked_sessions: int) -> str:
    return (
        f"pool_size={sample.pool_size}/{sample.pool_max}, "
        f"pool_available={sample.pool_available}, "
        f"requests_waiting={sample.requests_waiting}, "
        f"blocked_sessions={sample.blocked_session_count}/"
        f"{expected_blocked_sessions}"
    )


def _record_state_change(
    proof: HoldProof,
    sample: PollSample,
    *,
    expected_blocked_sessions: int,
) -> None:
    """Record the initial state and later field-boundary transitions only."""
    if not proof.samples:
        proof.state_changes.append(
            StateChange(
                label="hold_state_observed",
                detail=_state_detail(
                    sample,
                    expected_blocked_sessions=expected_blocked_sessions,
                ),
                observed_at=sample.observed_at,
            )
        )
        return

    previous = proof.samples[-1]
    before = (
        previous.pool_size == previous.pool_max,
        previous.pool_available == 0,
        previous.requests_waiting >= 2,
        previous.blocked_session_count == expected_blocked_sessions,
    )
    after = (
        sample.pool_size == sample.pool_max,
        sample.pool_available == 0,
        sample.requests_waiting >= 2,
        sample.blocked_session_count == expected_blocked_sessions,
    )
    if before != after:
        proof.state_changes.append(
            StateChange(
                label="hold_state_changed",
                detail=_state_detail(
                    sample,
                    expected_blocked_sessions=expected_blocked_sessions,
                ),
                observed_at=sample.observed_at,
            )
        )


def _append_sample(
    proof: HoldProof,
    sample: PollSample,
    *,
    expected_blocked_sessions: int,
) -> None:
    _record_state_change(
        proof,
        sample,
        expected_blocked_sessions=expected_blocked_sessions,
    )
    proof.samples.append(sample)


def prove_hold(
    conn: psycopg.Connection,
    *,
    backfill_pid: int,
    pool_status: PoolStatus,
    expected_blocked_sessions: int | None = None,
    poll_interval: float = 0.25,
    required_samples: int = 3,
    hold_seconds: float = 12.0,
    max_attempt_seconds: float = 90.0,
    sample_observer: SampleObserver | None = None,
) -> HoldProof:
    """Prove the combined pool and transaction-lock condition, then observe it.

    The default blocked-session count comes from the pool maximum, not the
    request count. The two queued requests are intentionally absent from
    ``pg_stat_activity`` because they never acquired a database connection.
    """
    if poll_interval <= 0:
        raise ValueError("poll_interval must be greater than zero")
    if hold_seconds < 0:
        raise ValueError("hold_seconds cannot be negative")
    if max_attempt_seconds <= 0:
        raise ValueError("max_attempt_seconds must be greater than zero")

    pool_max = get_settings().db_pool_max_size
    expected = (
        pool_max
        if expected_blocked_sessions is None
        else expected_blocked_sessions
    )
    if expected < 1:
        raise ValueError("expected_blocked_sessions must be at least one")

    proof = HoldProof(hold_seconds=hold_seconds)
    started = time.monotonic()
    deadline = started + max_attempt_seconds
    hold_deadline: float | None = None

    while time.monotonic() < deadline:
        sample = _sample(
            conn,
            backfill_pid=backfill_pid,
            pool_max=pool_max,
            pool_status=pool_status,
        )
        if sample_observer is not None:
            sample_observer(conn, sample)
        _append_sample(
            proof,
            sample,
            expected_blocked_sessions=expected,
        )

        if hold_deadline is None and evaluate_samples(
            proof.samples,
            expected_blocked_sessions=expected,
            required_samples=required_samples,
        ):
            proof.proven_at = sample.observed_at
            hold_deadline = time.monotonic() + hold_seconds

        if hold_deadline is not None and time.monotonic() >= hold_deadline:
            return proof

        now = time.monotonic()
        if now >= deadline:
            break
        sleep_until = deadline if hold_deadline is None else min(
            deadline,
            hold_deadline,
        )
        time.sleep(min(poll_interval, max(0.0, sleep_until - now)))

    if hold_deadline is not None:
        return proof
    raise LiveWorkshopError(
        describe_failure(proof.samples, expected_blocked_sessions=expected)
    )
