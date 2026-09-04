"""Map Aurora telemetry rows into the portable Retrieve -> Rank -> Reason contract."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class TelemetryCorrelationRecord(BaseModel):
    """Explicit links between Mosaic ledger IDs and optional OTel spans."""

    trace_id: str | None = None
    span_id: str | None = None
    search_event_ids: list[UUID] = Field(default_factory=list)
    retrieval_spans: list[dict[str, Any]] = Field(default_factory=list)
    source_revision: str | None = None
    dataset_manifest_sha256: str | None = None
    retrieval_fingerprint: str | None = None


class TelemetryModelRecord(BaseModel):
    """Model identity, bounded usage, finish reason, and measured latency."""

    agent_model_id: str | None = None
    synthesis_model_id: str | None = None
    input_tokens: int | float | None = None
    output_tokens: int | float | None = None
    total_tokens: int | float | None = None
    stop_reason: str | None = None
    latency_ms: int | float | None = None


class TelemetryStageRecord(BaseModel):
    """One portable stage in the Retrieve -> Rank -> Reason timeline."""

    id: Literal["retrieve", "rank", "reason"]
    status: Literal["active", "completed", "failed"]
    duration_ms: int | float | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AgentTelemetryResponse(BaseModel):
    """Canonical turn telemetry, independent of any observability backend."""

    schema_version: Literal["mosaic.telemetry.v1"] = "mosaic.telemetry.v1"
    agent_turn_id: UUID
    agent_session_id: UUID
    status: Literal["active", "completed", "failed"]
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    correlation: TelemetryCorrelationRecord
    model: TelemetryModelRecord
    stages: list[TelemetryStageRecord]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> int | float | None:
    return (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


def _sum_numbers(*values: Any) -> int | float | None:
    numbers = [value for value in values if _number(value) is not None]
    return sum(numbers) if numbers else None


def _disposition(
    result_rank: int,
    *,
    result_limit: int,
    authorized_limit: int,
) -> tuple[str, str | None]:
    if result_rank <= authorized_limit:
        return "authorized", None
    if result_rank <= result_limit:
        return "served_not_authorized", None
    return "outside_served_window", "outside_served_window"


def _ranking_receipt(
    row: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    channels = _as_dict(_as_dict(row.get("provenance")).get("channels"))

    def contribution(name: str) -> int | float | None:
        return _number(_as_dict(channels.get(name)).get("rrf_contribution"))

    result_rank = int(row["result_rank"])
    result_limit = int(profile.get("result_limit") or result_rank)
    authorized_limit = int(profile.get("authorized_limit") or result_limit)
    disposition, drop_reason = _disposition(
        result_rank,
        result_limit=result_limit,
        authorized_limit=authorized_limit,
    )
    fused_rank = row.get("fused_rank")
    rerank_rank = row.get("rerank_rank")
    movement = (
        int(rerank_rank) - int(fused_rank)
        if rerank_rank is not None and fused_rank is not None
        else None
    )
    return {
        "search_event_id": str(row["search_event_id"]),
        "product_id": row["product_id"],
        "result_rank": result_rank,
        "fused_rank": fused_rank,
        "rerank_rank": rerank_rank,
        "rerank_movement": movement,
        "rrf_score": _number(_as_dict(row.get("scores")).get("rrf")),
        "rrf_contributions": {
            "fts": contribution("fts"),
            "trigram": contribution("trigram"),
            "semantic": contribution("vector"),
        },
        "disposition": disposition,
        "drop_reason": drop_reason,
    }


def _model_record(
    turn: dict[str, Any],
    session: dict[str, Any],
) -> TelemetryModelRecord:
    intent = _as_dict(turn.get("extracted_intent"))
    usage = _as_dict(intent.get("usage"))
    strands = _as_dict(usage.get("strands"))
    synthesis = _as_dict(usage.get("synthesis"))
    metadata = _as_dict(session.get("metadata"))
    return TelemetryModelRecord(
        agent_model_id=metadata.get("agent_model_id") or metadata.get("model_id"),
        synthesis_model_id=metadata.get("synthesis_model_id"),
        input_tokens=_sum_numbers(
            strands.get("input_tokens"),
            synthesis.get("inputTokens"),
        ),
        output_tokens=_sum_numbers(
            strands.get("output_tokens"),
            synthesis.get("outputTokens"),
        ),
        total_tokens=_sum_numbers(
            strands.get("total_tokens"),
            synthesis.get("totalTokens"),
        ),
        stop_reason=synthesis.get("stopReason"),
        latency_ms=_number(synthesis.get("latencyMs")),
    )


def build_agent_telemetry_contract(
    *,
    turn: dict[str, Any],
    session: dict[str, Any],
    searches: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> AgentTelemetryResponse:
    """Build the transport-independent timeline from canonical persisted rows."""
    profiles = {
        str(search["search_event_id"]): _as_dict(search.get("retrieval_profile"))
        for search in searches
    }
    receipts = [
        _ranking_receipt(
            row,
            profiles.get(str(row["search_event_id"]), {}),
        )
        for row in candidates
    ]
    intent = _as_dict(turn.get("extracted_intent"))
    turn_telemetry = _as_dict(intent.get("telemetry"))
    selected_products = {
        item.get("product_id")
        for item in intent.get("selected_products", [])
        if isinstance(item, dict) and item.get("product_id") is not None
    }
    evidence_products = {
        _as_dict(tool.get("input_payload")).get("product_id")
        for tool in tools
        if tool.get("tool_name") == "get_product_evidence"
        and tool.get("outcome") == "success"
    }
    evidence_products.discard(None)
    synthesis = next(
        (
            tool
            for tool in reversed(tools)
            if tool.get("tool_name") == "synthesize_cited_answer"
        ),
        None,
    )
    synthesis_output = _as_dict(synthesis.get("output_payload")) if synthesis else {}
    citations = synthesis_output.get("citations")
    citation_count = len(citations) if isinstance(citations, list) else 0
    citation_status = (
        "passed"
        if synthesis and synthesis.get("outcome") == "success" and citation_count > 0
        else "failed"
        if synthesis
        else "not_run"
    )
    search_summaries = []
    for search in searches:
        diagnostics = _as_dict(search.get("diagnostics"))
        search_summaries.append(
            {
                "search_event_id": str(search["search_event_id"]),
                "status": diagnostics.get("status", "unknown"),
                "candidate_counts": _as_dict(search.get("candidate_counts")),
                "stage_timings_ms": _as_dict(diagnostics.get("stage_timings_ms")),
                "total_latency_ms": search.get("total_latency_ms"),
                "rerank_status": diagnostics.get("rerank_status"),
            }
        )
    turn_status = turn_telemetry.get("status") or (
        "completed" if turn.get("assistant_message") else "active"
    )
    stage_status = (
        "failed"
        if turn_status == "failed"
        else "active"
        if turn_status == "active"
        else "completed"
    )
    reason_tools = [
        {
            "tool": tool.get("tool_name"),
            "outcome": tool.get("outcome"),
            "duration_ms": tool.get("duration_ms"),
            "search_event_id": (
                str(tool["search_event_id"])
                if tool.get("search_event_id") is not None
                else None
            ),
        }
        for tool in tools
    ]
    authorization_counts: dict[str, int] = defaultdict(int)
    for tool in tools:
        authorization_counts[str(tool.get("outcome", "unknown"))] += 1
    first_search = searches[0] if searches else {}
    first_search_telemetry = _as_dict(
        _as_dict(first_search.get("diagnostics")).get("telemetry")
    )
    correlation = TelemetryCorrelationRecord(
        trace_id=turn_telemetry.get("trace_id"),
        span_id=turn_telemetry.get("span_id"),
        search_event_ids=[search["search_event_id"] for search in searches],
        retrieval_spans=[
            {
                "search_event_id": str(search["search_event_id"]),
                "trace_id": _as_dict(
                    _as_dict(search.get("diagnostics")).get("telemetry")
                ).get("trace_id"),
                "span_id": _as_dict(
                    _as_dict(search.get("diagnostics")).get("telemetry")
                ).get("span_id"),
            }
            for search in searches
        ],
        source_revision=first_search.get("source_revision"),
        dataset_manifest_sha256=first_search.get("dataset_manifest_sha256"),
        retrieval_fingerprint=first_search_telemetry.get("retrieval_fingerprint"),
    )
    return AgentTelemetryResponse(
        agent_turn_id=turn["agent_turn_id"],
        agent_session_id=turn["agent_session_id"],
        status=turn_status,
        started_at=turn["created_at"],
        completed_at=turn_telemetry.get("completed_at"),
        duration_ms=turn_telemetry.get("duration_ms"),
        correlation=correlation,
        model=_model_record(turn, session),
        stages=[
            TelemetryStageRecord(
                id="retrieve",
                status=stage_status,
                duration_ms=sum(
                    search.get("total_latency_ms") or 0 for search in searches
                )
                or None,
                details={
                    "mode": (
                        "new_retrieval" if searches else "reused_authorized_context"
                    ),
                    "searches": search_summaries,
                },
            ),
            TelemetryStageRecord(
                id="rank",
                status=stage_status,
                duration_ms=sum(
                    _as_dict(
                        _as_dict(search.get("diagnostics")).get("stage_timings_ms")
                    ).get("rerank", 0)
                    for search in searches
                )
                or None,
                details={"receipts": receipts},
            ),
            TelemetryStageRecord(
                id="reason",
                status=stage_status,
                duration_ms=sum(tool.get("duration_ms") or 0 for tool in tools) or None,
                details={
                    "tools": reason_tools,
                    "evidence_coverage": {
                        "selected_products": len(selected_products),
                        "products_with_evidence": len(
                            selected_products & evidence_products
                        ),
                        "complete": bool(selected_products)
                        and selected_products <= evidence_products,
                    },
                    "citation_validation": {
                        "status": citation_status,
                        "citation_count": citation_count,
                    },
                    "authorization_decisions": dict(authorization_counts),
                },
            ),
        ],
    )
