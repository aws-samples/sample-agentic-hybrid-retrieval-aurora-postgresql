"""Ask your deployed agent one question from the terminal and print its answer of record.

    uv run python scripts/ask_agent.py "QUESTION"

The question goes through the same API route as Ask Mosaic, so it reaches your agent on
AgentCore Runtime. The output shows the answer, the searches the agent planned with the
filters it chose, the tool trace, the products, each citation's type, product, source
and quote, the outcome, any decline reason and the run ID. A declined answer is an
answer of record, not a failure: every run is saved in mosaic.agent_turn and its tool
calls in mosaic.agent_tool_event.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validate_lab import LabValidationError, _request

QUOTE_CHARS = 120
MIN_QUESTION = 4  # AgentRequest.question's own minimum


def _section(title: str, lines: list[str]) -> list[str]:
    return [title, *(lines or ["  none"])]


def _filters(filters: dict[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in filters.items() if value)


def _plan(response: dict[str, Any]) -> list[str]:
    """The searches the agent chose, with the filters it set for each."""
    lines = []
    for number, step in enumerate(response["plan"], start=1):
        chosen = _filters(step.get("filters") or {})
        lines.append(
            f"  {number}  {step['query']}" + (f"   [{chosen}]" if chosen else "")
        )
        lines.append(f"     {step['purpose']}")
    return lines


def _trace(response: dict[str, Any]) -> list[str]:
    lines = []
    for step in response["trace"]:
        latency = step.get("latency_ms")
        took = f"   {latency:,.0f} ms" if latency is not None else ""
        lines.append(
            f"  {step['sequence']}  {step['tool']:<23}  {step['outcome']}{took}"
        )
    return lines


def _quote(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= QUOTE_CHARS else flat[: QUOTE_CHARS - 1].rstrip() + "…"


def _citations(response: dict[str, Any]) -> list[str]:
    """One line per citation (type, product, source file at a short revision), then its quote.

    The full source URI and revision are saved with the run; the file name and the first
    12 characters of the revision are enough to tell records apart on screen.
    """
    lines = []
    for c in response["citations"]:
        source = c["source_uri"].rstrip("/").rsplit("/", 1)[-1]
        lines.append(
            f"  [{c['number']}] {c['evidence_type']:<16} {c['product_id']}  "
            f"{source} @ {c['revision'][:12]}"
        )
        lines.append(f'      "{_quote(c["quote"])}"')
    return lines


def render(response: dict[str, Any]) -> str:
    """The answer of record as plain text: answer, trace, products, citations, outcome."""
    answer = [
        "  " + line
        for paragraph in response["answer"].splitlines()
        for line in (textwrap.wrap(paragraph, 86) or [""])
    ]
    products = [
        f"  {item['product_id']}  {item['title']}"
        for item in response["recommendations"]
    ]
    lines = [
        *_section("ANSWER", answer),
        *_section("PLAN", _plan(response)),
        *_section("TOOL TRACE", _trace(response)),
        *_section("PRODUCTS", products),
        *_section("CITATIONS", _citations(response)),
        f"OUTCOME: {response['outcome']}",
    ]
    if response.get("decline_reason"):
        lines.append(f"DECLINE REASON: {response['decline_reason']}")
    lines.append(f"Run ID: {response['agent_run_id']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args(argv)
    if len(args.question.strip()) < MIN_QUESTION:
        print(
            f"Question rule: ask at least {MIN_QUESTION} characters, in quotes; "
            'fix: uv run python scripts/ask_agent.py "Find headphones for calls"',
            file=sys.stderr,
        )
        return 2
    try:
        response = _request(
            args.api_url, "/api/agent/answer", {"question": args.question}
        )
    except LabValidationError as error:
        print(f"Agent request failed: {error}", file=sys.stderr)
        return 1
    print(render(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
