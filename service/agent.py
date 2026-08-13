"""Strands agent harness over read-only Aurora PostgreSQL product tools."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from strands import Agent
from strands.hooks import BeforeToolCallEvent, HookRegistry
from strands.models import BedrockModel

from service import agent_tools
from service.config import get_settings
from service.model_runtime import ModelRuntimeError, model_runtime_error
from service.models import (
    AgentPlanStep,
    AgentRequest,
    AgentResponse,
    ToolTraceStep,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""You are a read-only product-discovery agent using Amazon
Aurora PostgreSQL as the search and context engine.

Every product claim must come from a tool result. Never invent a product,
price, specification, availability state, source, score, or citation.
PostgreSQL owns full-text search, pg_trgm typo recovery, pgvector HNSW search,
hard filters, and reciprocal-rank fusion. Cohere Rerank orders only the bounded
fused candidate set. Scores from different stages are not
probabilities and must not be compared as though they share a scale.

For a complex question:
1. Use at most {len(agent_tools.SEARCH_SLOTS)} focused search_products calls.
   When the request has two independent product intents, issue both search calls
   together in one tool-use turn. Prefer one search for one product intent.
2. Preserve explicit hard constraints as category_key or attributes instead of
   leaving them only in query text. Mosaic home-office keys include
   category_key=quiet-keyboards with quiet_typing=true and
   category_key=ergonomic-office-chairs with seat_depth_adjustable=true.
   Keep preferences such as switch feel and lumbar style in query text when the
   user wants alternatives compared.
3. Select a shortlist of two to four products total, with no more than two
   products from any focused search.
4. In the next tool-use turn, call compare_products once and issue one
   get_product_evidence(product_id, evidence_query) call for every shortlisted
   product together. Use the shopper question or focused subquestion as
   evidence_query. These reads are independent.
5. Use explain_retrieval at most once when the user asks why something ranked.
6. Call synthesize_cited_answer exactly once, last, with only product IDs that
   search_products returned and for which evidence was retrieved.

synthesize_cited_answer creates the citation-validated answer of record. Do
not rewrite it after the tool succeeds. Close with one short sentence saying
the cited answer is ready. If a tool returns ok=false, follow its recovery
instruction or state the evidence gap."""


class ToolCallBudgetExceeded(RuntimeError):
    pass


class GroundingContractError(RuntimeError):
    """The retrieved state cannot support a citation-validated answer."""


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
    if not settings.agent_model_id:
        raise RuntimeError(
            "BEDROCK_AGENT_MODEL_ID or BEDROCK_CHAT_MODEL_ID is not configured"
        )
    model = BedrockModel(
        model_id=settings.agent_model_id,
        region_name=settings.aws_region,
        max_tokens=1_200,
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
    @staticmethod
    def _finalize_if_needed(
        request: AgentRequest,
        state: dict[str, Any],
    ) -> Exception | None:
        if state["answer_of_record"] is not None or not state["products"]:
            return None
        try:
            agent_tools.complete_grounded_answer(request.question)
        except Exception as error:
            classified = model_runtime_error(error)
            if classified is not None:
                return classified
            logger.warning(
                "Fallback cited synthesis failed: %s",
                error,
                exc_info=True,
            )
            return GroundingContractError(
                "Grounded synthesis refused to continue because the retrieved "
                "state did not satisfy the evidence and citation contract."
            )
        return None

    def _response(
        self,
        request: AgentRequest,
        state: dict[str, Any],
        result: Any | None,
        error: Exception | None,
    ) -> AgentResponse:
        record = state["answer_of_record"]
        if record is None:
            if isinstance(error, (GroundingContractError, ModelRuntimeError)):
                raise error
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
                retrieval_run_id=item.get("search_event_id"),
                result_count=item.get("result_count"),
                arguments=item.get("arguments") or {},
                outcome=item.get("outcome", "success"),
                latency_ms=item.get("latency_ms"),
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

    def _persist(
        self,
        state: dict[str, Any],
        result: Any | None,
        error: Exception | None,
    ) -> None:
        agent_tools.persist_completed_run(
            state,
            usage=_usage(result) if result is not None else {},
            error_type=type(error).__name__ if error else None,
        )

    def answer(self, request: AgentRequest) -> AgentResponse:
        state = agent_tools.start_run(
            request.question,
            request.filters,
            request.result_limit,
        )
        result: Any | None = None
        error: Exception | None = None
        try:
            # Agent.__call__ delegates to a worker thread. The tool run is held
            # in a ContextVar so concurrent requests stay isolated, and moving
            # the loop to another thread discards that context before the first
            # tool executes. The FastAPI route is synchronous, so running the
            # native async invocation here preserves the request context.
            result = asyncio.run(build_agent().invoke_async(request.question))
        except Exception as caught:
            error = caught
            logger.warning("Strands agent loop failed: %s", caught, exc_info=True)

        fallback_error = model_runtime_error(error) if error is not None else None
        if fallback_error is None:
            fallback_error = self._finalize_if_needed(request, state)
        if fallback_error is not None:
            error = fallback_error
        self._persist(state, result, error)
        return self._response(request, state, result, error)

    async def stream(self, request: AgentRequest):
        """Yield native Strands lifecycle events for one canonical agent run."""
        state = agent_tools.start_run(
            request.question,
            request.filters,
            request.result_limit,
        )
        result: Any | None = None
        error: Exception | None = None
        try:
            async for event in build_agent().stream_async(request.question):
                if "result" in event:
                    result = event["result"]
                yield event
        except Exception as caught:
            error = caught
            logger.warning("Strands streaming agent loop failed: %s", caught, exc_info=True)

        fallback_error = model_runtime_error(error) if error is not None else None
        if fallback_error is None:
            fallback_error = self._finalize_if_needed(request, state)
        if fallback_error is not None:
            error = fallback_error
        self._persist(state, result, error)

        if error is not None and state["answer_of_record"] is None:
            raise error
        yield {"agent_response": self._response(request, state, result, None)}


_agent: ProductDiscoveryAgent | None = None


def get_product_discovery_agent() -> ProductDiscoveryAgent:
    global _agent
    if _agent is None:
        _agent = ProductDiscoveryAgent()
    return _agent
