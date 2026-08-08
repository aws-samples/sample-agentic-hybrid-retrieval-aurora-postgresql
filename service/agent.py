"""Strands agent harness over read-only Aurora PostgreSQL product tools."""
from __future__ import annotations

import logging
from typing import Any

from strands import Agent
from strands.hooks import BeforeToolCallEvent, HookRegistry
from strands.models import BedrockModel

from service import agent_tools
from service.config import get_settings
from service.models import (
    AgentPlanStep,
    AgentRequest,
    AgentResponse,
    ToolTraceStep,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a read-only product-discovery agent using Amazon
Aurora PostgreSQL as the search and context engine.

Every product claim must come from a tool result. Never invent a product,
price, specification, availability state, source, score, or citation.
PostgreSQL owns full-text search, pg_trgm typo recovery, pgvector HNSW search,
hard filters, and weighted reciprocal-rank fusion. Cohere Rerank orders only
the bounded fused candidate set. Scores from different stages are not
probabilities and must not be compared as though they share a scale.

For a complex question:
1. Call search_products for each distinct product need or constraint set.
2. Use get_product_evidence when reviews or complete specifications matter.
3. Use compare_products when two or more retrieved options compete.
4. Use explain_retrieval when the user asks why something ranked.
5. Call synthesize_cited_answer exactly once, last, with only product IDs that
   search_products returned.

synthesize_cited_answer creates the citation-validated answer of record. Do
not rewrite it after the tool succeeds. Close with one short sentence saying
the cited answer is ready. If a tool returns ok=false, follow its recovery
instruction or state the evidence gap."""


class ToolCallBudgetExceeded(RuntimeError):
    pass


class _ToolCallBudget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def register_hooks(self, registry: HookRegistry, **_: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before_tool_call)

    def _before_tool_call(self, event: BeforeToolCallEvent) -> None:
        self.used += 1
        if self.used <= self.limit:
            return
        if self.used > self.limit + 2:
            raise ToolCallBudgetExceeded(
                f"The Strands agent exceeded its {self.limit}-tool budget."
            )
        event.cancel_tool = (
            f"Tool budget of {self.limit} calls is exhausted. Use the evidence "
            "already retrieved or state what is missing."
        )


def build_agent(*, max_tool_calls: int = 10) -> Agent:
    settings = get_settings()
    if not settings.chat_model_id:
        raise RuntimeError("BEDROCK_CHAT_MODEL_ID is not configured")
    model = BedrockModel(
        model_id=settings.chat_model_id,
        region_name=settings.aws_region,
        max_tokens=3_200,
    )
    return Agent(
        model=model,
        tools=list(agent_tools.TOOL_FUNCTIONS),
        system_prompt=SYSTEM_PROMPT,
        hooks=[_ToolCallBudget(max_tool_calls)],
        callback_handler=None,
    )


def _usage(result: Any) -> dict[str, Any]:
    try:
        summary = result.metrics.get_summary()
    except Exception:
        return {}
    accumulated = summary.get("accumulated_usage") or {}
    return {
        "cycles": summary.get("total_cycles"),
        "input_tokens": accumulated.get("inputTokens"),
        "output_tokens": accumulated.get("outputTokens"),
        "total_tokens": accumulated.get("totalTokens"),
    }


class ProductDiscoveryAgent:
    def answer(self, request: AgentRequest) -> AgentResponse:
        state = agent_tools.start_run(
            request.question,
            request.filters,
            request.result_limit,
        )
        result: Any | None = None
        error: Exception | None = None
        try:
            result = build_agent()(request.question)
        except Exception as caught:
            error = caught
            logger.warning("Strands agent loop failed: %s", caught, exc_info=True)

        usage = _usage(result) if result is not None else {}
        agent_tools.persist_completed_run(
            state,
            usage=usage,
            error_type=type(error).__name__ if error else None,
        )
        record = state["answer_of_record"]
        if record is None:
            reason = (
                f"Strands stopped before a citation-validated answer "
                f"({type(error).__name__})."
                if error
                else "Strands stopped before a citation-validated answer."
            )
            raise RuntimeError(reason)

        plans = [
            AgentPlanStep(
                query=item["query"],
                filters=item["filters"],
                purpose=item["purpose"],
            )
            for item in state["searches"]
        ]
        trace = [
            ToolTraceStep(
                sequence=item["sequence"],
                tool=item["tool"],
                detail=item["detail"],
                retrieval_run_id=item.get("retrieval_run_id"),
                result_count=item.get("result_count"),
            )
            for item in state["trace"]
        ]
        return AgentResponse(
            agent_run_id=state["agent_run_id"],
            question=request.question,
            answer=record["answer"],
            plan=plans,
            recommendations=record["recommendations"],
            citations=record["citations"],
            trace=trace,
        )


_agent: ProductDiscoveryAgent | None = None


def get_product_discovery_agent() -> ProductDiscoveryAgent:
    global _agent
    if _agent is None:
        _agent = ProductDiscoveryAgent()
    return _agent
