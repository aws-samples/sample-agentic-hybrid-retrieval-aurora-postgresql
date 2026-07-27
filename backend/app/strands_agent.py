"""A Strands agent that chooses and sequences the Aurora evidence tools.

Verity exposes two answer paths over the same tools and the same Aurora SQL:

- the deterministic pipeline in :func:`backend.app.agent.answer_question`, which
  calls the tools in a fixed order. Evaluation and replay use it, because a
  graded metric and a byte-identical receipt both require the same input to
  produce the same output.
- this module, where a Bedrock model reads the tool schemas and decides what to
  call. The workshop demonstrates it, because "the agent chose to traverse
  relationships here" is only true if the model actually chose.

Both write the same ``proof.*`` receipts through the same owning
implementations, so a run from either path replays identically. Neither contains
ranking logic: Aurora ranks, and the agent only decides what to ask it.
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any, AsyncIterator

from strands import Agent
from strands.hooks import BeforeToolCallEvent, HookRegistry
from strands.models import BedrockModel

from backend.app import agent_tools
from backend.app.config import get_settings
from backend.app.models import AgentAnswerRequest

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an incident evidence analyst working over Amazon \
Aurora PostgreSQL.

Every claim you make must come from a tool result. You have no knowledge of this \
company's incidents beyond what the tools return.

Work in this order, adapting when a result tells you to:
1. decompose_question, to learn which identifiers and cluster the question names.
2. search_evidence for the incident evidence using the inferred filters. Keep \
every run_id it returns.
3. When the question asks for reusable guidance such as a runbook, make a \
separate search_evidence call for that subquestion. Keep ACLs unchanged, but set \
cluster_id and incident_id to null because reusable guidance carries neither. \
Use JSON null, never the string "null". Keep that run_id too.
4. follow_evidence_links from keys you retrieved, when the question asks what \
caused something or which record is current. Declared relationships are the only \
proof of causation; text similarity is not.
5. compare_sources when two records compete, to rule one out on scope or revision.
6. synthesize_cited_answer with all supporting run_ids, last. It will refuse to \
synthesize if any evidence kind required by the decomposed question is absent.

synthesize_cited_answer produces the answer of record. Its citations are \
validated against the stored source revision and quote, and it is delivered to \
the user directly. Do not repeat, summarize, or rewrite it: paraphrasing it \
would break the citation numbers the database validated. After it succeeds, \
close with one short sentence, either confirming the cited answer is ready or \
naming an evidence gap you noticed.

If a tool returns ok=false, read its recovery field and correct your next call. \
Never report an answer ready after synthesize_cited_answer returns ok=false. \
If evidence is genuinely absent, say so rather than filling the gap.
"""


class ToolCallBudgetExceeded(RuntimeError):
    """Raised when a model keeps calling tools after the budget was refused."""


# Cancelled calls the model may attempt before the loop is torn down. Each one
# costs a Bedrock request, so the grace is small.
_CANCELLED_CALL_GRACE = 3


class _ToolCallBudget:
    """Stop the event loop from spending an unbounded number of tool calls.

    The model decides which tools to call, so nothing in the loop bounds how
    many it calls. Calls past the budget are cancelled with a message the model
    can act on, which is enough for a cooperative model.

    A model that ignores the cancellation is stopped outright. Strands continues
    a tool cycle by recursing in Python (strands/event_loop/event_loop.py), so an
    uncooperative loop exhausts the interpreter's stack rather than any budget,
    and every cycle before that is a billed model call.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def register_hooks(self, registry: HookRegistry, **_: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before_tool_call)

    def _before_tool_call(self, event: BeforeToolCallEvent) -> None:
        self.used += 1
        if self.used <= self.limit:
            return
        if self.used > self.limit + _CANCELLED_CALL_GRACE:
            raise ToolCallBudgetExceeded(
                f"The model attempted {self.used} tool calls against a budget of "
                f"{self.limit} and did not stop when the budget was refused."
            )
        event.cancel_tool = (
            f"Tool call budget of {self.limit} calls is exhausted. Answer from "
            "the evidence you already have, or say what is missing."
        )


def strands_agent_metadata() -> dict[str, Any]:
    """Describe the live agent configuration for the UI and diagnostics.

    Returns:
        The orchestration mode, model, and the tools the model may select.
    """
    settings = get_settings()
    return {
        "orchestration": "strands agent event loop",
        "framework": "strands-agents",
        "model_selected_tools": agent_tools.MODEL_TOOLS,
        "model_provider": "Amazon Bedrock",
        "synthesis_model": settings.bedrock_synthesis_model,
        "model_transport": settings.bedrock_model_transport,
        "embedding_model": settings.bedrock_embedding_model,
        "rerank_model": settings.cohere_rerank_model,
        "deterministic_path": (
            "POST /v1/agent/answer runs the fixed pipeline that evaluation and "
            "replay use. This path lets the model choose its own tool sequence, "
            "so two runs of the same question may differ."
        ),
    }


def build_agent(*, max_tool_calls: int = 12) -> Agent:
    """Construct the Strands agent over the Aurora evidence tools.

    Args:
        max_tool_calls: Tool calls allowed before the loop is asked to conclude.

    Returns:
        An Agent bound to the configured Bedrock synthesis model.
    """
    settings = get_settings()
    # No temperature: the Claude 5 family rejects the parameter. max_tokens is
    # raised over the synthesis budget because this budget covers the whole
    # multi-turn loop, not one answer.
    model = BedrockModel(
        model_id=settings.bedrock_synthesis_model,
        region_name=settings.aws_region,
        max_tokens=max(settings.bedrock_synthesis_max_tokens * 3, 2000),
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
    except Exception as error:
        logger.debug("Strands metrics unavailable: %s", error)
        return {}
    usage = summary.get("accumulated_usage") or {}
    return {
        "cycles": summary.get("total_cycles"),
        "input_tokens": usage.get("inputTokens"),
        "output_tokens": usage.get("outputTokens"),
        "total_tokens": usage.get("totalTokens"),
    }


def _finalize(
    response: dict[str, Any],
    result: Any,
    run: dict[str, Any],
    started: float,
) -> dict[str, Any]:
    """Assemble the response around the database's answer, not the model's prose.

    Args:
        response: The envelope to fill in place.
        result: The Strands AgentResult, or None if the loop did not finish.
        run: The run state returned by agent_tools.start_run.
        started: perf_counter value from the start of the run.

    Returns:
        The same response dict, populated.
    """
    trace = run["trace"]
    record = run["answer_of_record"]
    response["status"] = "complete" if record else "unsynthesized"
    # The model's closing text is narration about its own process. The answer is
    # whatever synthesize_cited_answer validated and persisted.
    response["agent_commentary"] = str(result).strip() if result is not None else None
    response["stop_reason"] = getattr(result, "stop_reason", None)
    response["run_ids"] = [call["run_id"] for call in trace if call.get("run_id")]
    if record:
        response["answer"] = record["answer"]
        response["citations"] = record["citations"]
        response["run_id"] = record["run_id"]
        response["synthesis_mode"] = record["synthesis_mode"]
    else:
        response["answer"] = None
        response["citations"] = []
        response["run_id"] = None
        response["synthesis_mode"] = None
        response["note"] = (
            "The agent stopped before synthesizing a cited answer. Its commentary "
            "is not citation-validated and is not an answer of record."
        )
    response["usage"] = _usage(result)
    response["total_latency_ms"] = round((perf_counter() - started) * 1000, 2)
    return response


def answer_question_with_strands(request: AgentAnswerRequest) -> dict[str, Any]:
    """Answer a question by letting the model drive the Aurora evidence tools.

    Args:
        request: The question, the caller's principal, and the tool-call budget.
            Retrieval knobs on the request are not forwarded: the model chooses
            its own tool arguments, and silently overriding them would make the
            reported trace a lie.

    Returns:
        The model's reply, the ordered tool-call trace with per-call Aurora
        run_ids and latencies, and the run_id of the answer of record.
    """
    started = perf_counter()
    run = agent_tools.start_run(request.principal)
    agent = build_agent(max_tool_calls=request.max_tool_calls)

    response: dict[str, Any] = {
        "question": request.question,
        "agent": strands_agent_metadata(),
        "tool_calls": run["trace"],
    }
    try:
        result = agent(request.question)
    except Exception as error:
        logger.warning("Strands agent loop failed: %s", error)
        # The loop dying does not invalidate work Aurora already validated, so
        # finalize on what the tools produced and record why the loop ended.
        _finalize(response, None, run, started)
        response["error"] = str(error)
        if not run["answer_of_record"]:
            response["status"] = "failed"
        return response

    return _finalize(response, result, run, started)


async def stream_answer_with_strands(
    request: AgentAnswerRequest,
) -> AsyncIterator[dict[str, Any]]:
    """Stream the agent's decisions as it makes them.

    Unlike the deterministic path, which streams an answer that already exists,
    this yields each tool selection and each token as the event loop produces
    them, so the UI shows the sequence the model actually chose.

    Args:
        request: The question, the caller's principal, and the tool-call budget.

    Yields:
        Envelopes with a ``type`` of meta, tool_call, answer_token, commentary,
        done, or error. Answer tokens carry the citation-validated text, not the
        model's closing message.
    """
    started = perf_counter()
    run = agent_tools.start_run(request.principal)
    trace = run["trace"]
    agent = build_agent(max_tool_calls=request.max_tool_calls)

    yield {
        "type": "meta",
        "question": request.question,
        "agent": strands_agent_metadata(),
    }
    emitted = 0
    answer_streamed = False
    result: Any = None
    failure: str | None = None
    try:
        async for event in agent.stream_async(request.question):
            while emitted < len(trace):
                yield {"type": "tool_call", **trace[emitted]}
                emitted += 1
                record = run["answer_of_record"]
                if record and not answer_streamed:
                    answer_streamed = True
                    # Citations are already validated when the answer of record
                    # is created. Publish them first so clients can reveal the
                    # source rail while the answer text streams.
                    yield {"type": "citations", "citations": record["citations"]}
                    for offset in range(0, len(record["answer"]), 48):
                        yield {
                            "type": "answer_token",
                            "text": record["answer"][offset : offset + 48],
                        }
            if "result" in event:
                result = event["result"]
    except Exception as error:
        logger.warning("Strands agent stream failed: %s", error)
        failure = str(error)

    while emitted < len(trace):
        yield {"type": "tool_call", **trace[emitted]}
        emitted += 1
    if failure and not run["answer_of_record"]:
        yield {
            "type": "error",
            "status": "failed",
            "error": failure,
            "tool_calls": trace,
            "total_latency_ms": round((perf_counter() - started) * 1000, 2),
        }
        return
    if failure and not answer_streamed:
        record = run["answer_of_record"]
        yield {"type": "citations", "citations": record["citations"]}
        for offset in range(0, len(record["answer"]), 48):
            yield {"type": "answer_token", "text": record["answer"][offset : offset + 48]}
    done: dict[str, Any] = {
        "type": "done",
        "question": request.question,
        "agent": strands_agent_metadata(),
        "tool_calls": trace,
    }
    _finalize(done, result, run, started)
    if failure:
        done["error"] = failure
    yield done
