"""Live answer synthesis with a real Strands Agent over Amazon Bedrock.

For questions the seed does NOT know canonically, this composes a cited answer by
running a Strands `Agent` backed by a Bedrock `BedrockModel` (Opus 4.8 by default)
over the evidence rows Aurora already ranked. The agent is instructed to write
grounded prose that cites sources by their bracket number; we capture the model's
token usage so the Diagnostics view can show a real cost signal.

The canonical Orion demo never reaches this path — it is served verbatim from
ops.agent_answers (see agent.answer_question), so the flagship narrative stays
byte-identical and does not depend on a live text-model call. If Bedrock is
unreachable, `synthesize_live` raises and the caller falls back to the extractive
template in agent.synthesize_answer.
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from .config import get_settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are Verity, an operational analyst that answers questions strictly from "
    "the retrieved evidence you are given. Rules:\n"
    "1. Use ONLY the numbered evidence rows below. Do not invent facts, IDs, dates, "
    "or systems that are not present in the evidence.\n"
    "2. Cite every claim inline with its source's bracket number, e.g. [1], [3]. A "
    "sentence may carry more than one citation.\n"
    "3. Lead with a direct answer to the question, then give the supporting chain of "
    "evidence across the systems (Slack, Jira, Confluence, Salesforce, GitHub).\n"
    "4. Be concise and factual. Prefer 4-8 sentences. No preamble, no restating the "
    "question, no meta commentary about being an AI.\n"
    "5. If the evidence does not answer the question, say so plainly rather than "
    "guessing."
)


def _evidence_block(results: list[dict[str, Any]], limit: int = 8) -> str:
    """Render the ranked rows as a numbered evidence list for the model prompt."""
    lines: list[str] = []
    for i, r in enumerate(results[:limit], start=1):
        system = str(r.get("source_system") or "source")
        ext = r.get("external_id") or "?"
        title = " ".join(str(r.get("title") or "").split())
        snippet = " ".join(str(r.get("snippet") or "").split())[:600]
        meta = " · ".join(
            str(part)
            for part in (r.get("status"), r.get("priority"), r.get("account_name"), r.get("component"))
            if part
        )
        header = f"[{i}] {system} {ext} — {title}"
        if meta:
            header += f" ({meta})"
        lines.append(f"{header}\n    {snippet}")
    return "\n".join(lines)


def _build_prompt(question: str, results: list[dict[str, Any]]) -> str:
    return (
        f"Question: {question}\n\n"
        f"Retrieved evidence (already ranked by Aurora hybrid search):\n"
        f"{_evidence_block(results)}\n\n"
        f"Write the cited answer now."
    )


def _build_agent():
    """Construct a Strands Agent on a Bedrock model, or raise if unavailable."""
    from strands import Agent
    from strands.models import BedrockModel

    from .bedrock import bedrock_client_config

    settings = get_settings()
    # NOTE: Claude 5 family rejects `temperature` on Bedrock — do not set it here.
    # Adaptive retries via boto_client_config so synthesis backs off under the
    # throttling a full workshop room produces instead of failing fast.
    model = BedrockModel(
        model_id=settings.bedrock_chat_model,
        region_name=settings.aws_region,
        boto_client_config=bedrock_client_config(),
        max_tokens=1024,
        streaming=True,
    )
    return Agent(model=model, system_prompt=_SYSTEM_PROMPT, callback_handler=None)


def _usage_from_result(result: Any) -> dict[str, int]:
    try:
        usage = result.metrics.get_summary().get("accumulated_usage") or {}
        return {
            "input_tokens": int(usage.get("inputTokens", 0)),
            "output_tokens": int(usage.get("outputTokens", 0)),
            "total_tokens": int(usage.get("totalTokens", 0)),
        }
    except Exception:  # pragma: no cover - defensive
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def synthesize_live(question: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    """Synthesize a cited answer with a real Strands agent over Bedrock.

    Returns {answer, usage, model, harness}. Raises on any Bedrock/Strands failure
    so the caller can fall back to the deterministic extractive template.
    """
    if not results:
        raise ValueError("no evidence rows to synthesize from")
    agent = _build_agent()
    result = agent(_build_prompt(question, results))
    text = str(result).strip()
    if not text:
        raise ValueError("empty synthesis from model")
    return {
        "answer": text,
        "usage": _usage_from_result(result),
        "model": get_settings().bedrock_chat_model,
        "harness": "Strands Agents",
    }


async def stream_live(question: str, results: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
    """Yield streaming synthesis events for the SSE endpoint.

    Emits {type: 'token', text: ...} for each text delta and a terminal
    {type: 'usage', ...} carrying token counts and the model id.
    """
    agent = _build_agent()
    async for event in agent.stream_async(_build_prompt(question, results)):
        if not isinstance(event, dict):
            continue
        if event.get("data"):
            yield {"type": "token", "text": event["data"]}
        if "result" in event:
            yield {
                "type": "usage",
                "usage": _usage_from_result(event["result"]),
                "model": get_settings().bedrock_chat_model,
                "stop_reason": getattr(event["result"], "stop_reason", None),
            }
