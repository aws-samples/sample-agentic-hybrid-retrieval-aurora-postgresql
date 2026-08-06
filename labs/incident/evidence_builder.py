"""Build searchable evidence from one measured online schema and data migration.

Gate 5 showed why this module does not loop over polling ticks or fill a target
count with sentence templates: the first 148-document prototype had a 20.65%
near-duplicate rate. Each document here represents a distinct transition,
outcome class, lifecycle fact, or plan checkpoint. The raw polls remain available
to the admission path; they are control evidence, not a document-generation loop.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from backend.app.lab_routes import HotWriteResult
from labs.incident.hold_controller import HoldProof, PollSample, StateChange
from labs.incident.query_regression import PlanCheckpoint, REFERENCE_QUERY
from labs.incident.recovery_verifier import RecoveryProof


CLASSIFIER_VERSION = "statement-text/1"
CLASSIFICATION_REASONS = (
    "statement_text_present",
    "no_statement_text",
    "statement_text_empty",
)
SIGNAL_TYPES = ("lock", "pool", "request", "wal", "meta", "plan")


@dataclass(frozen=True)
class VisibilityDecision:
    """One replayable visibility decision from a measured payload."""

    visibility: str
    reason: str
    classifier_version: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceDocument:
    """One authoritative telemetry record ready for C2 admission."""

    key: str
    signal_type: str
    phase: str
    title: str
    body: str
    occurred_at: str
    structured: dict[str, Any]
    visibility: str
    classifier_version: str
    classification_reason: str
    classification_sources: tuple[str, ...]


def _sources(structured: Mapping[str, Any]) -> tuple[str, ...]:
    collected: set[tuple[str, int]] = set()
    for key, table in (
        ("activity_sample_ids", "pg_stat_activity_samples"),
        ("statements_sample_ids", "pg_stat_statements_samples"),
    ):
        for sample_id in structured.get(key) or ():
            if isinstance(sample_id, bool):
                raise ValueError(f"{key} cannot contain a boolean sample id")
            try:
                collected.add((table, int(sample_id)))
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"{key} must contain integer sample ids, got {sample_id!r}"
                ) from error
    return tuple(
        f"{table}:{sample_id}"
        for table, sample_id in sorted(collected)
    )


def classify_visibility(structured: Mapping[str, Any]) -> VisibilityDecision:
    """Classify one measured observation by captured PostgreSQL statement text.

    Query text from ``pg_stat_activity_samples.query`` and
    ``pg_stat_statements_samples.queries`` is the sensitive material that the
    optional masking module protects. The classifier reads that captured content
    rather than assigning visibility by document key or signal type.
    """
    sources = _sources(structured)
    statement = structured.get("statement")
    if not isinstance(statement, str):
        return VisibilityDecision(
            "workshop",
            "no_statement_text",
            CLASSIFIER_VERSION,
            sources,
        )
    if not statement.strip():
        return VisibilityDecision(
            "workshop",
            "statement_text_empty",
            CLASSIFIER_VERSION,
            sources,
        )
    if not sources:
        raise ValueError(
            "restricted classification requires at least one source sample id; "
            "got statement text with no activity_sample_ids or "
            f"statements_sample_ids: {sorted(structured)}"
        )
    return VisibilityDecision(
        "restricted",
        "statement_text_present",
        CLASSIFIER_VERSION,
        sources,
    )


def _require_timestamp(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must carry a non-empty observed timestamp")
    return value


def _require_int(record: Mapping[str, Any], key: str, context: str) -> int:
    value = record.get(key)
    if isinstance(value, bool):
        raise ValueError(f"{context}.{key} must be an integer, got {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{context}.{key} must be an integer, got {value!r}"
        ) from error


def _require_float(record: Mapping[str, Any], key: str, context: str) -> float:
    value = record.get(key)
    if isinstance(value, bool):
        raise ValueError(f"{context}.{key} must be numeric, got {value!r}")
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{context}.{key} must be numeric, got {value!r}"
        ) from error


def _first_statement(record: Mapping[str, Any]) -> str | None:
    statement = record.get("statement")
    if isinstance(statement, str):
        return statement

    queries = record.get("queries")
    if not isinstance(queries, Sequence) or isinstance(queries, (str, bytes)):
        return None
    for query in queries:
        if isinstance(query, str) and query.strip():
            return query
    return None


def _document(
    *,
    key: str,
    signal_type: str,
    phase: str,
    title: str,
    body: str,
    occurred_at: str,
    structured: Mapping[str, Any],
) -> EvidenceDocument:
    if signal_type not in SIGNAL_TYPES:
        raise ValueError(f"unsupported signal type {signal_type!r}")
    measured = {
        **dict(structured),
        "telemetry_type": signal_type,
        "phase": phase,
    }
    decision = classify_visibility(measured)
    return EvidenceDocument(
        key=key,
        signal_type=signal_type,
        phase=phase,
        title=title,
        body=body,
        occurred_at=_require_timestamp(occurred_at, f"{key}.occurred_at"),
        structured=measured,
        visibility=decision.visibility,
        classifier_version=decision.classifier_version,
        classification_reason=decision.reason,
        classification_sources=decision.sources,
    )


def _poll_at_or_after(samples: Sequence[PollSample], target_index: int) -> PollSample:
    return samples[min(target_index, len(samples) - 1)]


def _by_order_id(
    samples: Sequence[Mapping[str, Any]],
) -> dict[int, Mapping[str, Any]]:
    result: dict[int, Mapping[str, Any]] = {}
    for sample in samples:
        order_id = _require_int(sample, "order_id", "activity_sample")
        if order_id in result:
            raise ValueError(
                f"activity samples contain multiple rows for order_id={order_id}"
            )
        _require_int(sample, "sample_id", "activity_sample")
        _require_timestamp(sample.get("captured_at"), "activity_sample.captured_at")
        result[order_id] = sample
    return result


def _state_change_body(change: StateChange, ordinal: int) -> tuple[str, str]:
    if change.label == "hold_state_observed":
        return (
            "Pool state observed",
            "The controller recorded the pool and blocker state before declaring "
            f"the hold proven: {change.detail}.",
        )
    return (
        f"Pool state transition {ordinal}",
        "A controller boundary changed while observing the migration collision: "
        f"{change.detail}.",
    )


def _plan_document(
    *,
    key: str,
    checkpoint: PlanCheckpoint,
    occurred_at: str,
    wave: str,
) -> EvidenceDocument:
    phase = "plan_regression"
    label = checkpoint.label.replace("_", " ")
    reference_query = " ".join(REFERENCE_QUERY.split())
    body = (
        f"Reference query: {reference_query}. Plan checkpoint {label}: "
        f"{checkpoint.plan_type}, "
        f"{checkpoint.execution_ms:.3f} ms, {checkpoint.buffers} buffers, "
        f"{checkpoint.rows_returned} rows returned, and "
        f"{checkpoint.rows_removed_by_filter} rows removed by filter."
    )
    return _document(
        key=key,
        signal_type="plan",
        phase=phase,
        title=f"{wave} plan checkpoint: {label}",
        body=body,
        occurred_at=occurred_at,
        structured={
            "checkpoint": checkpoint.label,
            "plan_type": checkpoint.plan_type,
            "execution_ms": checkpoint.execution_ms,
            "buffers": checkpoint.buffers,
            "rows_returned": checkpoint.rows_returned,
            "rows_removed_by_filter": checkpoint.rows_removed_by_filter,
            "raw_explain": checkpoint.raw_explain,
            "reference_query": reference_query,
        },
    )


def build_wave_a_documents(
    *,
    run_suffix: str,
    backfill_pid: int,
    backfill_duration_seconds: float,
    backfill_rows_updated: int,
    hold_proof: HoldProof,
    recovery_proof: RecoveryProof,
    hot_write_results: Sequence[HotWriteResult],
    activity_samples: Sequence[Mapping[str, Any]],
    statement_samples: Sequence[Mapping[str, Any]],
    plan_checkpoints: Sequence[PlanCheckpoint],
) -> list[EvidenceDocument]:
    """Render Investigation Evidence facts without inventing documents from raw poll frequency.

    ``activity_samples`` and ``statement_samples`` are captured PostgreSQL rows
    supplied by the orchestration/admission boundary. Their capture-local sample
    IDs travel into every restricted document's provenance so C2 can persist and
    replay the classification from the original statement text.
    """
    if not run_suffix:
        raise ValueError("run_suffix is required")
    if backfill_pid <= 0:
        raise ValueError("backfill_pid must be positive")
    if backfill_duration_seconds <= 0:
        raise ValueError("backfill_duration_seconds must be positive")
    if backfill_rows_updated <= 0:
        raise ValueError("backfill_rows_updated must be positive")
    if not hold_proof.samples:
        raise ValueError("hold proof has no raw poll samples")

    expected_labels = {"before_analyze", "after_analyze"}
    if len(plan_checkpoints) != 2 or {
        checkpoint.label for checkpoint in plan_checkpoints
    } != expected_labels:
        raise ValueError(
            "Investigation Evidence requires exactly before_analyze and "
            "after_analyze plan checkpoints"
        )
    if any(checkpoint.plan_type != "Seq Scan" for checkpoint in plan_checkpoints):
        raise ValueError("Investigation Evidence plan checkpoints must remain sequential scans")

    unexpected_outcomes = {
        result.outcome
        for result in hot_write_results
        if result.outcome not in {"committed", "pool_timeout"}
    }
    if unexpected_outcomes:
        raise ValueError(
            "Investigation Evidence cannot describe unhealthy hot-write outcomes: "
            + ", ".join(sorted(unexpected_outcomes))
        )

    results_by_outcome: dict[str, list[HotWriteResult]] = defaultdict(list)
    for result in hot_write_results:
        results_by_outcome[result.outcome].append(result)
    committed = sorted(results_by_outcome["committed"], key=lambda item: item.order_id)
    pool_timeouts = sorted(
        results_by_outcome["pool_timeout"],
        key=lambda item: item.order_id,
    )
    if not committed or not pool_timeouts:
        raise ValueError(
            "Investigation Evidence needs both committed blocked writers and queued pool timeouts"
        )

    samples = hold_proof.samples
    first_poll = samples[0]
    proved_poll = next(
        (
            sample
            for sample in samples
            if sample.observed_at == hold_proof.proven_at
        ),
        samples[min(2, len(samples) - 1)],
    )
    final_poll = samples[-1]
    activity_by_order = _by_order_id(activity_samples)
    documents: list[EvidenceDocument] = []

    # One entry and one drain event per pool-held writer. Queue timeouts are not
    # lock events because they never own a PostgreSQL backend.
    for ordinal, result in enumerate(committed, start=1):
        activity = activity_by_order.get(result.order_id)
        if activity is None:
            raise ValueError(
                "missing captured pg_stat_activity sample for committed "
                f"hot write order_id={result.order_id}"
            )
        sample_id = _require_int(activity, "sample_id", "activity_sample")
        pid = _require_int(activity, "pid", "activity_sample")
        captured_at = _require_timestamp(
            activity.get("captured_at"),
            "activity_sample.captured_at",
        )
        statement = _first_statement(activity)
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError(
                "committed hot-write activity samples must carry captured statement text"
            )
        common = {
            "backfill_pid": backfill_pid,
            "writer_pid": pid,
            "order_id": result.order_id,
            "statement": statement,
            "activity_sample_ids": [sample_id],
            "request_outcome": result.outcome,
            "waited_seconds": result.waited_seconds,
        }
        documents.append(
            _document(
                key=f"TEL-{run_suffix}-LE{ordinal:02d}",
                signal_type="lock",
                phase="pool_exhaustion",
                title=f"Writer {ordinal} entered transaction-ID wait",
                body=(
                    f"Writer PID {pid} targeted order_id={result.order_id} and "
                    f"entered a Lock:transactionid wait behind backfill PID "
                    f"{backfill_pid} after acquiring a pool connection."
                ),
                occurred_at=captured_at,
                structured=common,
            )
        )
        documents.append(
            _document(
                key=f"TEL-{run_suffix}-LD{ordinal:02d}",
                signal_type="lock",
                phase="recovery",
                title=f"Writer {ordinal} drained after backfill commit",
                body=(
                    f"After the backfill released its row locks, writer PID {pid} "
                    f"acquired its update lock for order_id={result.order_id} and "
                    f"committed after waiting {result.waited_seconds:.3f} seconds."
                ),
                occurred_at=final_poll.observed_at,
                structured=common,
            )
        )

    # State-change boundaries are searchable; every raw 250ms poll is retained
    # separately and is never expanded into a template series.
    for ordinal, change in enumerate(hold_proof.state_changes, start=1):
        title, body = _state_change_body(change, ordinal)
        documents.append(
            _document(
                key=f"TEL-{run_suffix}-Q{ordinal:02d}",
                signal_type="pool",
                phase="pool_exhaustion",
                title=title,
                body=body,
                occurred_at=change.observed_at,
                structured={
                    "state_change": change.label,
                    "detail": change.detail,
                    "pool_size": first_poll.pool_size,
                    "pool_available": first_poll.pool_available,
                    "requests_waiting": first_poll.requests_waiting,
                    "blocked_session_count": first_poll.blocked_session_count,
                },
            )
        )

    documents.append(
        _document(
            key=f"TEL-{run_suffix}-Q90",
            signal_type="pool",
            phase="pool_exhaustion",
            title="Pool saturation proven",
            body=(
                "Three consecutive controller polls proved the combined condition: "
                f"pool_available={proved_poll.pool_available}, "
                f"requests_waiting={proved_poll.requests_waiting}, and "
                f"{proved_poll.blocked_session_count} tagged PostgreSQL sessions "
                "waiting on the backfill transaction."
            ),
            occurred_at=hold_proof.proven_at,
            structured={
                "pool_size": proved_poll.pool_size,
                "pool_max": proved_poll.pool_max,
                "pool_available": proved_poll.pool_available,
                "requests_waiting": proved_poll.requests_waiting,
                "blocked_session_count": proved_poll.blocked_session_count,
                "required_consecutive_samples": 3,
            },
        )
    )
    for ordinal, fraction in enumerate((0.25, 0.5, 0.75), start=1):
        marker = _poll_at_or_after(
            samples,
            int((len(samples) - 1) * fraction),
        )
        documents.append(
            _document(
                key=f"TEL-{run_suffix}-Q9{ordinal}",
                signal_type="pool",
                phase="pool_exhaustion",
                title=f"Proven hold boundary {ordinal}",
                body=(
                    f"At the {int(fraction * 100)}% boundary of the "
                    f"{hold_proof.hold_seconds:.1f}-second observation hold, the "
                    f"pool still had {marker.pool_available} available connection(s), "
                    f"{marker.requests_waiting} queued request(s), and "
                    f"{marker.blocked_session_count} transaction-ID lock waiters."
                ),
                occurred_at=marker.observed_at,
                structured={
                    "hold_boundary_fraction": fraction,
                    "hold_seconds": hold_proof.hold_seconds,
                    "pool_size": marker.pool_size,
                    "pool_max": marker.pool_max,
                    "pool_available": marker.pool_available,
                    "requests_waiting": marker.requests_waiting,
                    "blocked_session_count": marker.blocked_session_count,
                },
            )
        )
    documents.append(
        _document(
            key=f"TEL-{run_suffix}-Q99",
            signal_type="pool",
            phase="recovery",
            title="Pool capacity recovered",
            body=(
                "The recovery verifier observed the application pool fully "
                "available with no queued checkout requests after the backfill "
                "committed."
            ),
            occurred_at=final_poll.observed_at,
            structured={
                "pool_fully_available": recovery_proof.pool_fully_available,
                "no_requests_waiting": recovery_proof.no_requests_waiting,
            },
        )
    )

    documents.extend(
        (
            _document(
                key=f"TEL-{run_suffix}-R01",
                signal_type="request",
                phase="recovery",
                title="Blocked hot writes committed after release",
                body=(
                    f"{len(committed)} hot-write request(s) had obtained PostgreSQL "
                    "connections, waited behind the open backfill, and committed "
                    "after the backfill transaction released their row locks."
                ),
                occurred_at=final_poll.observed_at,
                structured={
                    "outcome": "committed",
                    "request_count": len(committed),
                    "minimum_waited_seconds": min(
                        result.waited_seconds for result in committed
                    ),
                    "maximum_waited_seconds": max(
                        result.waited_seconds for result in committed
                    ),
                },
            ),
            _document(
                key=f"TEL-{run_suffix}-R02",
                signal_type="request",
                phase="pool_exhaustion",
                title="Queued requests ended at pool checkout",
                body=(
                    f"{len(pool_timeouts)} request(s) returned pool_timeout after "
                    "waiting for a pool slot. They never obtained a PostgreSQL "
                    "connection, so they have no database lock wait and no "
                    "pg_stat_activity row."
                ),
                occurred_at=proved_poll.observed_at,
                structured={
                    "outcome": "pool_timeout",
                    "request_count": len(pool_timeouts),
                    "minimum_waited_seconds": min(
                        result.waited_seconds for result in pool_timeouts
                    ),
                    "maximum_waited_seconds": max(
                        result.waited_seconds for result in pool_timeouts
                    ),
                },
            ),
        )
    )

    if not statement_samples:
        raise ValueError("Investigation Evidence requires captured pg_stat_statements samples")
    for ordinal, statement_sample in enumerate(statement_samples, start=1):
        sample_id = _require_int(
            statement_sample,
            "sample_id",
            "statement_sample",
        )
        phase = statement_sample.get("phase")
        if not isinstance(phase, str) or not phase:
            raise ValueError("statement_sample.phase must be non-empty text")
        captured_at = _require_timestamp(
            statement_sample.get("captured_at"),
            "statement_sample.captured_at",
        )
        statement = _first_statement(statement_sample)
        structured: dict[str, Any] = {
            "statement_phase": phase,
            "calls": _require_int(statement_sample, "calls", "statement_sample"),
            "rows": _require_int(statement_sample, "rows", "statement_sample"),
            "total_exec_time": _require_float(
                statement_sample,
                "total_exec_time",
                "statement_sample",
            ),
            "statements_sample_ids": [sample_id],
        }
        if statement is not None:
            structured["statement"] = statement
        documents.append(
            _document(
                key=f"TEL-{run_suffix}-W{ordinal:02d}",
                signal_type="wal",
                phase="backfill" if phase != "after" else "recovery",
                title=f"Statement and row-churn checkpoint: {phase}",
                body=(
                    f"The {phase} statement checkpoint recorded "
                    f"{structured['calls']} call(s), {structured['rows']} affected "
                    f"row(s), and {structured['total_exec_time']:.3f} ms total "
                    "execution time for the captured workbench updates."
                ),
                occurred_at=captured_at,
                structured=structured,
            )
        )

    plans_by_label = {checkpoint.label: checkpoint for checkpoint in plan_checkpoints}
    first_plan = plans_by_label["before_analyze"]
    second_plan = plans_by_label["after_analyze"]
    meta_events = (
        (
            "M01",
            "Nullable column committed before backfill",
            "The migration added the nullable priority_tier column in a separate "
            "committed step, so the later open transaction represents the "
            "unbatched data backfill rather than an AccessExclusiveLock.",
            "backfill",
            {"backfill_pid": backfill_pid},
        ),
        (
            "M02",
            "Unbatched backfill transaction opened",
            f"Backfill PID {backfill_pid} began one unbatched UPDATE across "
            f"{backfill_rows_updated} orders.",
            "backfill",
            {"backfill_pid": backfill_pid, "rows_updated": backfill_rows_updated},
        ),
        (
            "M03",
            "Backfill update completed but transaction stayed open",
            f"The UPDATE affected {backfill_rows_updated} orders in "
            f"{backfill_duration_seconds:.3f} seconds and the transaction remained "
            "open until the measured hold completed.",
            "backfill",
            {
                "backfill_pid": backfill_pid,
                "rows_updated": backfill_rows_updated,
                "duration_seconds": backfill_duration_seconds,
            },
        ),
        (
            "M04",
            "Twelve hot writes targeted the migration window",
            f"{len(hot_write_results)} hot-write requests targeted the first "
            "orders while the backfill transaction remained open.",
            "pool_exhaustion",
            {"request_count": len(hot_write_results)},
        ),
        (
            "M05",
            "Controller required a combined proof",
            "The hold controller required pool exhaustion, at least two queued "
            "requests, and the configured tagged sessions blocked by the backfill "
            "for three consecutive polls.",
            "pool_exhaustion",
            {"required_consecutive_samples": 3},
        ),
        (
            "M06",
            "Combined condition became proven",
            "The controller began its observation hold only after the combined "
            "pool and PostgreSQL condition was proven.",
            "pool_exhaustion",
            {"proven_at": hold_proof.proven_at},
        ),
        (
            "M07",
            "Proven condition held for observation",
            f"The proven state remained under observation for "
            f"{hold_proof.hold_seconds:.1f} seconds before recovery began.",
            "pool_exhaustion",
            {"hold_seconds": hold_proof.hold_seconds},
        ),
        (
            "M08",
            "Backfill commit began recovery",
            "Committing the open backfill transaction released the row locks that "
            "the connected hot writers had been waiting to acquire.",
            "recovery",
            {"backfill_pid": backfill_pid},
        ),
        (
            "M09",
            "Backfill no longer blocked any backend",
            "Recovery verification confirmed that the released backfill PID no "
            "longer appeared in any PostgreSQL blocking chain.",
            "recovery",
            {
                "backfill_no_longer_blocking": (
                    recovery_proof.backfill_no_longer_blocking
                )
            },
        ),
        (
            "M10",
            "Tagged transaction-ID waiters disappeared",
            "Recovery verification found no tagged application sessions still "
            "waiting on a transaction-ID lock.",
            "recovery",
            {"no_sessions_blocked": recovery_proof.no_sessions_blocked},
        ),
        (
            "M11",
            "Pool wait queue drained",
            "Recovery verification observed zero waiting pool checkout requests.",
            "recovery",
            {"no_requests_waiting": recovery_proof.no_requests_waiting},
        ),
        (
            "M12",
            "Pool timeout remained a measured outcome",
            "The recovery contract retained the pool timeout as evidence that the "
            "request queue genuinely saturated during the hold.",
            "recovery",
            {"pool_timeout_observed": recovery_proof.pool_timeout_observed},
        ),
        (
            "M13",
            "All blocked writers drained",
            "The recovery verifier confirmed that the pool-held writers committed "
            "after the blocking transaction released their row locks.",
            "recovery",
            {"blocked_writers_drained": recovery_proof.blocked_writers_drained},
        ),
        (
            "M14",
            "Fresh post-recovery write committed",
            "A new hot write through the same application pool committed after the "
            "queue and transaction-ID waiters were gone.",
            "recovery",
            {"fresh_write_committed": recovery_proof.fresh_write_committed},
        ),
        (
            "M15",
            "ANALYZE did not change the access path",
            "The before- and after-ANALYZE checkpoints both remained sequential "
            "scans, so statistics refresh alone was not the evidence-backed "
            "finding for the remaining slow query.",
            "plan_regression",
            {
                "before_plan_type": first_plan.plan_type,
                "after_plan_type": second_plan.plan_type,
            },
        ),
        (
            "M16",
            "Rows removed by filter remained high",
            f"Both Investigation Evidence plans removed {first_plan.rows_removed_by_filter} and "
            f"{second_plan.rows_removed_by_filter} rows by filter respectively, "
            "showing that the query still lacked a selective access path.",
            "plan_regression",
            {
                "before_rows_removed": first_plan.rows_removed_by_filter,
                "after_rows_removed": second_plan.rows_removed_by_filter,
            },
        ),
        (
            "M17",
            "Investigation Evidence ends before index validation exists",
            "Investigation Evidence contains diagnostic observations only. No post-index plan was "
            "captured, so a later improvement cannot be claimed from this evidence.",
            "plan_regression",
            {"wave": "A"},
        ),
    )
    for code, title, body, phase, structured in meta_events:
        documents.append(
            _document(
                key=f"TEL-{run_suffix}-{code}",
                signal_type="meta",
                phase=phase,
                title=title,
                body=body,
                occurred_at=final_poll.observed_at,
                structured=structured,
            )
        )

    for ordinal, checkpoint in enumerate(
        sorted(plan_checkpoints, key=lambda item: item.label),
        start=1,
    ):
        documents.append(
            _plan_document(
                key=f"TEL-{run_suffix}-P{ordinal:02d}",
                checkpoint=checkpoint,
                occurred_at=final_poll.observed_at,
                wave="Investigation Evidence",
            )
        )

    return documents


def build_wave_b_documents(
    *,
    run_suffix: str,
    plan_checkpoints: Sequence[PlanCheckpoint],
    occurred_at: str,
) -> list[EvidenceDocument]:
    """Render only new validation facts observed after human-approved DDL."""
    if not run_suffix:
        raise ValueError("run_suffix is required")
    if len(plan_checkpoints) != 1 or plan_checkpoints[0].label != "after_index":
        raise ValueError("Validation Evidence requires exactly one after_index plan checkpoint")
    checkpoint = plan_checkpoints[0]
    if checkpoint.plan_type != "Index Scan":
        raise ValueError("Validation Evidence plan checkpoint must be an index scan")
    observed_at = _require_timestamp(occurred_at, "Validation Evidence occurred_at")
    return [
        _document(
            key=f"TEL-{run_suffix}-M01",
            signal_type="meta",
            phase="plan_regression",
            title="Validation Evidence captured post-index evidence",
            body=(
                "Validation Evidence was captured after the participant-approved change. It adds "
                "a new measured plan checkpoint without revising the earlier "
                "Investigation Evidence "
                "observations."
            ),
            occurred_at=observed_at,
            structured={"wave": "B", "checkpoint": checkpoint.label},
        ),
        _plan_document(
            key=f"TEL-{run_suffix}-P01",
            checkpoint=checkpoint,
            occurred_at=observed_at,
            wave="Validation Evidence",
        ),
    ]
