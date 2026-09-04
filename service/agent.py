"""Strands agent harness over read-only Aurora PostgreSQL product tools."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from strands import Agent
from strands.hooks import BeforeToolCallEvent, HookRegistry
from strands.models import BedrockModel

from service import agent_tools
from service.config import get_settings
from service.model_runtime import ModelRuntimeError, model_runtime_error
from service.models import (
    AgentPartial,
    AgentPlanStep,
    AgentRequest,
    AgentResponse,
    ToolTraceStep,
)
from service.telemetry import agent_outcome_attributes, observe_agent_turn

logger = logging.getLogger(__name__)


def _plan_steps(state: dict[str, Any]) -> list[AgentPlanStep]:
    return [
        AgentPlanStep(
            query=item["query"],
            filters=item["filters"],
            purpose=item["purpose"],
        )
        for item in state["searches"]
    ]


def _trace_steps(state: dict[str, Any]) -> list[ToolTraceStep]:
    return [
        ToolTraceStep(
            sequence=item["sequence"],
            tool=item["tool"],
            detail=item["detail"],
            retrieval_run_id=item.get("search_event_id"),
            result_count=item.get("result_count"),
            arguments=item.get("arguments") or {},
            outcome=item.get("outcome", "success"),
            origin=item.get("origin", "model"),
            latency_ms=item.get("latency_ms"),
        )
        for item in state["trace"]
    ]


def _partial(state: dict[str, Any]) -> AgentPartial:
    """The run state so far, in the shape the finished response uses.

    Candidates are ordered newest search first, then by that search's ranked
    order, so the shortlist matches what the agent is currently working from.
    `state["products"]` is keyed by id, and iterating it would order the panel by
    whichever product happened to be inserted first.
    """
    ordered_ids: list[int] = []
    if state["searches"]:
        for search in reversed(state["searches"]):
            for product_id in search["product_ids"]:
                if product_id not in ordered_ids:
                    ordered_ids.append(product_id)
    else:
        ordered_ids.extend(state.get("context_product_ids", []))
    return AgentPartial(
        plan=_plan_steps(state),
        candidates=[
            state["products"][product_id]
            for product_id in ordered_ids
            if product_id in state["products"]
        ],
        trace=_trace_steps(state),
    )


SYSTEM_PROMPT = f"""You are a read-only product-discovery agent using Amazon
Aurora PostgreSQL as the search and context engine.

Every product claim must come from a tool result. Never invent a product,
price, specification, availability state, source, score, or citation.
PostgreSQL owns full-text search, pg_trgm typo recovery, pgvector HNSW search,
hard filters, and reciprocal-rank fusion. Cohere Rerank orders only the bounded
fused candidate set. Scores from different stages are not
probabilities and must not be compared as though they share a scale.

Choose the minimum sufficient tool path for each request.

For a first request, or a follow-up that asks for alternatives, changes catalog
filters, or needs any product outside the authorized prior shortlist:
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
5. Call explain_retrieval exactly once for the strongest search event so the
   final recommendation always retains a replayable ranking receipt.
6. Call synthesize_cited_answer exactly once, last, with only product IDs that
   search_products returned and for which evidence was retrieved.

For a closed-world follow-up over an authorized prior shortlist, do not repeat
retrieval:
- A product-fact question uses get_product_evidence for the referenced product,
  then synthesize_cited_answer.
- A comparison uses compare_products, fresh get_product_evidence calls for the
  selected products, then synthesize_cited_answer.
- A ranking question uses explain_retrieval for an authorized prior search event,
  fresh get_product_evidence calls, then synthesize_cited_answer.

Prior answer prose is never evidence. Every answer still requires fresh evidence
and deterministic citation validation. Never use an inherited product after
search_products starts a new candidate pool.

synthesize_cited_answer creates the citation-bounded answer of record and applies
deterministic product, numeric, availability, and mission-claim checks. Do not
rewrite it after the tool succeeds. Close with one short sentence saying the
cited answer is ready. If a tool returns ok=false, follow its recovery instruction
or state the evidence gap."""


class ToolCallBudgetExceeded(RuntimeError):
    pass


class GroundingContractError(RuntimeError):
    """The retrieved state cannot support a citation-bounded answer."""


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


def _agent_prompt(
    request: AgentRequest,
    state: dict[str, Any] | None = None,
) -> str:
    """Add bounded prior-turn references without treating them as evidence."""
    if request.context is None:
        return request.question
    context = {
        "previous_agent_run_id": str(request.context.previous_agent_run_id),
        "previous_question": request.context.previous_question,
        "previous_recommendations": [
            recommendation.model_dump()
            for recommendation in request.context.recommendations
        ],
        "authorized_search_event_ids": [
            str(event_id)
            for event_id in (
                state.get("context_search_event_ids", []) if state is not None else []
            )
        ],
    }
    return (
        f"Current shopper message: {json.dumps(request.question)}\n\n"
        "Prior grounded turn references:\n"
        f"{json.dumps(context)}\n\n"
        "Resolve conversational references such as 'one', 'them', 'cheaper', "
        "or 'the first' against those prior recommendations. They are lookup "
        "targets only, not evidence. Use the minimum sufficient tool path. "
        "Do not call search_products when the answer is closed over this "
        "shortlist; retrieve fresh evidence and synthesize a newly validated "
        "answer. If the shopper asks for alternatives, changes constraints, "
        "or needs a new candidate, call search_products and follow the full "
        "retrieval, comparison, ranking-receipt, evidence, and synthesis path."
    )


def _usage(result: Any) -> dict[str, Any]:
    metrics = getattr(result, "metrics", None)
    get_summary = getattr(metrics, "get_summary", None)
    if not callable(get_summary):
        return {}
    try:
        summary = get_summary()
    except (AttributeError, TypeError, ValueError):
        return {}
    if not isinstance(summary, dict):
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
                f"Strands stopped before a citation-bounded answer "
                f"({type(error).__name__})."
                if error
                else "Strands stopped before a citation-bounded answer."
            )
            raise RuntimeError(reason)

        return AgentResponse(
            agent_run_id=state["agent_run_id"],
            question=request.question,
            answer=record["answer"],
            plan=_plan_steps(state),
            recommendations=record["recommendations"],
            citations=record["citations"],
            trace=_trace_steps(state),
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
            request.context,
        )
        result: Any | None = None
        error: Exception | None = None
        with observe_agent_turn(state, request.question) as observation:
            state["trace_id"] = observation.correlation.trace_id
            state["span_id"] = observation.correlation.span_id
            try:
                # Agent.__call__ delegates to a worker thread. The tool run is held
                # in a ContextVar so concurrent requests stay isolated, and moving
                # the loop to another thread discards that context before the first
                # tool executes. The FastAPI route is synchronous, so running the
                # native async invocation here preserves the request context.
                result = asyncio.run(
                    build_agent().invoke_async(_agent_prompt(request, state))
                )
            except Exception as caught:
                error = caught
                logger.warning("Strands agent loop failed: %s", caught, exc_info=True)

            fallback_error = model_runtime_error(error) if error is not None else None
            if fallback_error is None:
                fallback_error = self._finalize_if_needed(request, state)
            if fallback_error is not None:
                error = fallback_error
            strands_usage = _usage(result) if result is not None else {}
            self._persist(state, result, error)
            record = state["answer_of_record"]
            observation.finish(
                answer=record["answer"] if record else None,
                usage={
                    "strands": strands_usage,
                    "synthesis": record["usage"] if record else {},
                },
                error_type=type(error).__name__ if error else None,
                status="completed" if record else "failed",
                outcome_attributes=agent_outcome_attributes(state),
            )
            return self._response(request, state, result, error)

    async def stream(self, request: AgentRequest):
        """Yield native Strands lifecycle events for one canonical agent run."""
        state = agent_tools.start_run(
            request.question,
            request.filters,
            request.result_limit,
            request.context,
        )
        result: Any | None = None
        error: Exception | None = None
        # Emit a snapshot only when a tool has actually added something. A
        # `current_tool_use` arrives on every streamed delta, so keying off the
        # event alone would re-send the same shortlist dozens of times per tool.
        produced = (0, 0, 0)
        with observe_agent_turn(state, request.question) as observation:
            state["trace_id"] = observation.correlation.trace_id
            state["span_id"] = observation.correlation.span_id
            try:
                async for event in build_agent().stream_async(
                    _agent_prompt(request, state)
                ):
                    if "result" in event:
                        result = event["result"]
                    yield event
                    progress = (
                        len(state["searches"]),
                        len(state["products"]),
                        len(state["trace"]),
                    )
                    if progress != produced:
                        produced = progress
                        yield {"agent_partial": _partial(state)}
            except Exception as caught:
                error = caught
                logger.warning(
                    "Strands streaming agent loop failed: %s", caught, exc_info=True
                )

            fallback_error = model_runtime_error(error) if error is not None else None
            if fallback_error is None:
                fallback_error = self._finalize_if_needed(request, state)
            if fallback_error is not None:
                error = fallback_error
            strands_usage = _usage(result) if result is not None else {}
            self._persist(state, result, error)
            record = state["answer_of_record"]
            observation.finish(
                answer=record["answer"] if record else None,
                usage={
                    "strands": strands_usage,
                    "synthesis": record["usage"] if record else {},
                },
                error_type=type(error).__name__ if error else None,
                status="completed" if record else "failed",
                outcome_attributes=agent_outcome_attributes(state),
            )

            if error is not None and record is None:
                raise error
            yield {"agent_response": self._response(request, state, result, None)}


_agent: ProductDiscoveryAgent | None = None


def get_product_discovery_agent() -> ProductDiscoveryAgent:
    global _agent
    if _agent is None:
        _agent = ProductDiscoveryAgent()
    return _agent
