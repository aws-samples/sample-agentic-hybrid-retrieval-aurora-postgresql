"""Optional OpenTelemetry projection of Mosaic's Aurora evidence ledger.

Aurora remains canonical. This module emits a deliberately smaller aggregate
view when an OpenTelemetry SDK is present and the operator opts in; it never
configures an exporter and never exports candidate identities or content.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID

from opentelemetry import baggage, context, trace
from opentelemetry.trace import Span, Status, StatusCode

from service.config import get_settings
from service.db import connect
from service.models import SearchRequest, SearchResponse
from service.retrieval_fingerprint import compute_retrieval_fingerprint

INSTRUMENTATION_SCOPE = "opentelemetry.instrumentation.mosaic"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TraceCorrelation:
    """W3C trace identifiers, absent when the active provider is a no-op."""

    trace_id: str | None = None
    span_id: str | None = None


def correlation_from_span_context(
    *,
    trace_id: int,
    span_id: int,
    is_valid: bool,
) -> TraceCorrelation:
    """Format an OpenTelemetry span context without conflating Mosaic IDs."""
    if not is_valid:
        return TraceCorrelation()
    return TraceCorrelation(
        trace_id=f"{trace_id:032x}",
        span_id=f"{span_id:016x}",
    )


def _span_correlation(span: Span) -> TraceCorrelation:
    span_context = span.get_span_context()
    return correlation_from_span_context(
        trace_id=span_context.trace_id,
        span_id=span_context.span_id,
        is_valid=span_context.is_valid,
    )


def _set_attributes(span: Span, attributes: dict[str, Any]) -> None:
    for name, value in attributes.items():
        if value is not None:
            span.set_attribute(name, value)


def _numeric(value: Any) -> int | float | None:
    return (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


def retrieval_span_attributes(
    *,
    search_event_id: UUID,
    candidate_counts: dict[str, int],
    result_limit: int,
    authorized_limit: int,
    stage_timings_ms: dict[str, float],
    total_latency_ms: int,
    rerank_status: str,
    retrieval_fingerprint: str,
    source_revision: str,
    dataset_manifest_sha256: str,
    status: str,
) -> dict[str, Any]:
    """Return the export-safe retrieval projection.

    The function accepts no candidate rows, which makes candidate identity or
    content impossible to add accidentally at this boundary.
    """
    attributes: dict[str, Any] = {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": "search_products",
        "mosaic.search_event.id": str(search_event_id),
        "mosaic.retrieval.status": status,
        "mosaic.retrieval.rerank_status": rerank_status,
        "mosaic.retrieval.fingerprint": retrieval_fingerprint,
        "mosaic.source.revision": source_revision,
        "mosaic.dataset.manifest_sha256": dataset_manifest_sha256,
        "mosaic.latency.total_ms": total_latency_ms,
        "mosaic.candidates.served_limit": result_limit,
        "mosaic.candidates.authorized_limit": authorized_limit,
    }
    attributes.update(
        {f"mosaic.candidates.{name}": count for name, count in candidate_counts.items()}
    )
    attributes.update(
        {
            f"mosaic.latency.{name}_ms": timing
            for name, timing in stage_timings_ms.items()
        }
    )
    return attributes


def agent_outcome_attributes(state: dict[str, Any]) -> dict[str, Any]:
    """Return grounding and authorization aggregates without their identities."""
    record = state.get("answer_of_record") or {}
    citations = record.get("citations") or []
    selected = record.get("recommendations") or []
    trace_steps = state.get("trace") or []
    return {
        "mosaic.tools.count": len(trace_steps),
        "mosaic.grounding.selected_products": len(selected),
        "mosaic.grounding.products_with_evidence": len(
            state.get("evidence_by_product") or {}
        ),
        "mosaic.grounding.citations": len(citations),
        "mosaic.grounding.citation_validation": (
            "passed" if record and citations else "not_completed"
        ),
        "mosaic.authorization.denied_count": sum(
            step.get("outcome") == "denied" for step in trace_steps
        ),
    }


@lru_cache(maxsize=1)
def _current_retrieval_fingerprint() -> str:
    """Hash the measured retrieval closure without adding telemetry to it."""
    return compute_retrieval_fingerprint()


def persist_retrieval_telemetry(
    *,
    response: SearchResponse,
    query: str,
    start_time_ns: int,
) -> None:
    """Append correlation metadata to an existing search receipt.

    This runs outside `service.retrieval`, whose file hash gates the canonical
    scorecard. A telemetry-only change therefore cannot invalidate measured
    ranking quality.
    """
    diagnostics = response.diagnostics
    if diagnostics is None:
        return
    try:
        settings = get_settings()
        profile = diagnostics.retrieval_profile
        fingerprint = _current_retrieval_fingerprint()
        correlation = record_retrieval_span(
            search_event_id=response.search_event_id,
            query=query,
            candidate_counts=diagnostics.candidate_counts,
            result_limit=profile.result_limit,
            authorized_limit=profile.authorized_limit or profile.result_limit,
            stage_timings_ms=diagnostics.stage_timings_ms,
            total_latency_ms=diagnostics.total_latency_ms,
            rerank_status=diagnostics.rerank_status,
            retrieval_fingerprint=fingerprint,
            source_revision=settings.source_revision,
            dataset_manifest_sha256=settings.dataset_manifest_sha256,
            status="completed",
            start_time_ns=start_time_ns,
        )
    except Exception as error:  # noqa: BLE001
        logger.warning(
            "Telemetry metadata degraded to no-op for search event %s: %s",
            response.search_event_id,
            type(error).__name__,
        )
        return
    payload = {
        "trace_id": correlation.trace_id,
        "span_id": correlation.span_id,
        "retrieval_fingerprint": fingerprint,
    }
    try:
        with connect() as connection:
            connection.execute(
                """
                UPDATE mosaic.search_event
                SET diagnostics = jsonb_set(
                    diagnostics,
                    '{telemetry}',
                    %s::jsonb,
                    true
                )
                WHERE search_event_id = %s
                """,
                (json.dumps(payload), response.search_event_id),
            )
            connection.commit()
    except Exception as error:  # noqa: BLE001
        logger.warning(
            "Telemetry correlation was not appended to search event %s: %s",
            response.search_event_id,
            type(error).__name__,
        )


def search_with_telemetry(
    request: SearchRequest,
    *,
    search: Callable[[SearchRequest], SearchResponse] | None = None,
) -> SearchResponse:
    """Run the canonical search, then append its optional telemetry projection."""
    if search is None:
        from service.retrieval import get_retrieval_service

        search = get_retrieval_service().search
    started_wall_ns = time.time_ns()
    response = search(request)
    persist_retrieval_telemetry(
        response=response,
        query=request.query,
        start_time_ns=started_wall_ns,
    )
    return response


@dataclass
class AgentTurnObservation:
    """Mutable handle used to finish one optional turn span."""

    span: Span | None = None
    correlation: TraceCorrelation = TraceCorrelation()
    capture_content: bool = False
    finished: bool = False

    def finish(
        self,
        *,
        answer: str | None,
        usage: dict[str, Any],
        error_type: str | None,
        status: str,
        outcome_attributes: dict[str, Any],
    ) -> None:
        """Attach final model and outcome attributes before the span closes."""
        if self.span is None or self.finished:
            return
        self.finished = True
        try:
            strands = usage.get("strands") or {}
            synthesis = usage.get("synthesis") or {}
            input_tokens = sum(
                value
                for value in (
                    _numeric(strands.get("input_tokens")),
                    _numeric(synthesis.get("inputTokens")),
                )
                if value is not None
            )
            output_tokens = sum(
                value
                for value in (
                    _numeric(strands.get("output_tokens")),
                    _numeric(synthesis.get("outputTokens")),
                )
                if value is not None
            )
            total_tokens = sum(
                value
                for value in (
                    _numeric(strands.get("total_tokens")),
                    _numeric(synthesis.get("totalTokens")),
                )
                if value is not None
            )
            _set_attributes(
                self.span,
                {
                    "gen_ai.usage.input_tokens": input_tokens or None,
                    "gen_ai.usage.output_tokens": output_tokens or None,
                    "gen_ai.usage.total_tokens": total_tokens or None,
                    "gen_ai.response.finish_reasons": (
                        [synthesis["stopReason"]]
                        if synthesis.get("stopReason")
                        else None
                    ),
                    "mosaic.model.synthesis_latency_ms": synthesis.get("latencyMs"),
                    "mosaic.agent.status": status,
                    "mosaic.agent.error_type": error_type,
                    **outcome_attributes,
                },
            )
            if self.capture_content and answer is not None:
                self.span.set_attribute("gen_ai.task.output", answer)
                self.span.set_attribute("agentcore.invocation.agent_response", answer)
            if status == "failed":
                self.span.set_status(Status(StatusCode.ERROR, error_type))
            else:
                self.span.set_status(Status(StatusCode.OK))
        except Exception as error:  # noqa: BLE001
            logger.warning(
                "Agent telemetry finalization degraded to no-op: %s",
                type(error).__name__,
            )


@contextmanager
def observe_agent_turn(
    state: dict[str, Any],
    question: str,
) -> Iterator[AgentTurnObservation]:
    """Create the AgentCore-compatible parent span only when opted in."""
    state.setdefault("_started_monotonic", time.perf_counter())
    state.setdefault("trace_id", None)
    state.setdefault("span_id", None)
    settings = get_settings()
    if not settings.agentcore_observability_enabled:
        yield AgentTurnObservation()
        return

    attached = None
    span_manager = None
    try:
        attached = context.attach(
            baggage.set_baggage("session.id", str(state["agent_session_id"]))
        )
        attributes: dict[str, Any] = {
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.name": "mosaic",
            "gen_ai.request.model": settings.agent_model_id,
            "session.id": str(state["agent_session_id"]),
            "mosaic.agent_turn.id": str(state["agent_turn_id"]),
            "mosaic.source.revision": settings.source_revision,
            "mosaic.dataset.manifest_sha256": settings.dataset_manifest_sha256,
        }
        if settings.agentcore_capture_content:
            attributes["gen_ai.task.input"] = question
            attributes["agentcore.invocation.user_prompt"] = question
        tracer = trace.get_tracer(INSTRUMENTATION_SCOPE)
        span_manager = tracer.start_as_current_span(
            "mosaic.agent.invoke",
            attributes=attributes,
        )
        span = span_manager.__enter__()
    except Exception as error:  # noqa: BLE001
        if attached is not None:
            context.detach(attached)
        logger.warning(
            "Agent telemetry setup degraded to no-op: %s",
            type(error).__name__,
        )
        yield AgentTurnObservation()
        return

    observation = AgentTurnObservation(
        span=span,
        correlation=_span_correlation(span),
        capture_content=settings.agentcore_capture_content,
    )
    exception: BaseException | None = None
    try:
        yield observation
    except BaseException as error:
        exception = error
        if not observation.finished:
            observation.finish(
                answer=None,
                usage={},
                error_type=type(error).__name__,
                status="failed",
                outcome_attributes={},
            )
        raise
    finally:
        try:
            span_manager.__exit__(
                type(exception) if exception is not None else None,
                exception,
                exception.__traceback__ if exception is not None else None,
            )
        except Exception as error:  # noqa: BLE001
            logger.warning(
                "Agent telemetry shutdown degraded to no-op: %s",
                type(error).__name__,
            )
        if attached is not None:
            context.detach(attached)


def record_retrieval_span(
    *,
    search_event_id: UUID,
    query: str,
    candidate_counts: dict[str, int],
    result_limit: int,
    authorized_limit: int,
    stage_timings_ms: dict[str, float],
    total_latency_ms: int,
    rerank_status: str,
    retrieval_fingerprint: str,
    source_revision: str,
    dataset_manifest_sha256: str,
    status: str,
    start_time_ns: int,
    error_type: str | None = None,
) -> TraceCorrelation:
    """Emit one bounded retrieval span and return its durable correlation IDs."""
    settings = get_settings()
    if not settings.agentcore_observability_enabled:
        return TraceCorrelation()
    try:
        attributes = retrieval_span_attributes(
            search_event_id=search_event_id,
            candidate_counts=candidate_counts,
            result_limit=result_limit,
            authorized_limit=authorized_limit,
            stage_timings_ms=stage_timings_ms,
            total_latency_ms=total_latency_ms,
            rerank_status=rerank_status,
            retrieval_fingerprint=retrieval_fingerprint,
            source_revision=source_revision,
            dataset_manifest_sha256=dataset_manifest_sha256,
            status=status,
        )
        attributes["gen_ai.tool.call.result"] = json.dumps(
            {
                "candidate_counts": candidate_counts,
                "rerank_status": rerank_status,
                "status": status,
            },
            sort_keys=True,
        )
        if settings.agentcore_capture_content:
            attributes["gen_ai.tool.call.arguments"] = json.dumps(
                {"query": query},
                sort_keys=True,
            )
        if error_type:
            attributes["mosaic.retrieval.error_type"] = error_type
        span = trace.get_tracer(INSTRUMENTATION_SCOPE).start_span(
            "mosaic.retrieval.search_products",
            attributes=attributes,
            start_time=start_time_ns,
        )
        correlation = _span_correlation(span)
        if error_type:
            span.set_status(Status(StatusCode.ERROR, error_type))
        else:
            span.set_status(Status(StatusCode.OK))
        span.end(end_time=time.time_ns())
        return correlation
    except Exception as error:  # noqa: BLE001
        logger.warning(
            "Retrieval telemetry degraded to no-op: %s",
            type(error).__name__,
        )
        return TraceCorrelation()
