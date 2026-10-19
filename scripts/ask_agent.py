"""Ask your deployed Retrieval agent one question from the terminal and print its answer of record.

    uv run python scripts/ask_agent.py "QUESTION"

The question goes through the same API route as Ask Mosaic, so it reaches your Retrieval agent on
AgentCore Runtime. The output shows the answer, the searches the Retrieval agent planned with the
filters it chose, the tool trace, the products, each citation's type, product, source
and quote, the outcome, any decline reason and the run ID. The trace names each catalog
tool's route (through AgentCore Gateway when the Retrieval agent is deployed) and, under each
search, whether Aurora ran the search SQL in your lab files. A declined answer is an
answer of record, not a failure: every run is saved in mosaic.agent_turn and its tool
calls in mosaic.agent_tool_event.
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validate_lab import LabValidationError, _request
from service.config import get_settings
from service.lab_validation_receipt import participant_sql_digest
from service.participant_commands import APPLY_SQL

# Code Editor's terminal on a 16-inch laptop holds 124 characters a line. Every line stays
# well inside it, so a long title or quote is shortened rather than wrapped mid-word.
LINE_CHARS = 100
QUOTE_CHARS = LINE_CHARS - 8  # inside its six-space indent and quotation marks
MIN_QUESTION = 4  # AgentRequest.question's own minimum
# The API waits for Runtime up to the turn deadline plus its own 30 s transport
# margin, then saves the run; waiting longer means the Run ID always prints.
RESPONSE_MARGIN_SECONDS = 60


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


ROUTES = {"gateway": "through AgentCore Gateway", "in_process": "without Gateway"}


def _search_sql(applied: str | None, workspace: str) -> str:
    """Which search SQL Aurora ran for one search, against the lab files in Code Editor."""
    if applied is None:
        return (
            "Aurora has no record of which search SQL ran; "
            f"apply your lab files with {APPLY_SQL}"
        )
    if applied == workspace:
        return (
            f"Aurora ran your Lab 1 and Lab 2 SQL ({applied[:12]}), the same as your lab files"
        )
    return (
        f"Aurora ran search SQL {applied[:12]}, not your lab files' {workspace[:12]}; "
        f"apply them with {APPLY_SQL}"
    )


def _trace(response: dict[str, Any], workspace: str) -> list[str]:
    """One line per tool call, then the search SQL under each search.

    A step the application ran itself, after the agent stopped, says so; the agent
    is capped at a number of tool calls, and that step is not one of them.
    """
    lines = []
    for step in response["trace"]:
        latency = step.get("latency_ms")
        took = f"   {latency:,.0f} ms" if latency is not None else ""
        notes = [ROUTES[step["route"]]] if step.get("route") in ROUTES else []
        if step.get("origin") == "controller_fallback":
            notes.append("run by the application")
        noted = f"   {', '.join(notes)}" if notes else ""
        lines.append(
            f"  {step['sequence']}  {step['tool']:<23}  {step['outcome']}{took}{noted}"
        )
        if step["tool"] == "search_products" and step.get("route"):
            lines.append(
                f"     {_search_sql(step.get('search_sql_sha256'), workspace)}"
            )
    return lines


def _clip(text: str, limit: int) -> str:
    # Review text keeps the source's HTML line breaks; on screen they are just spaces.
    flat = " ".join(re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE).split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _quote(text: str) -> str:
    return _clip(text, QUOTE_CHARS)


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
    products = []
    for item in response["recommendations"]:
        lead = f"  {item['product_id']}  "
        products.append(lead + _clip(item["title"], LINE_CHARS - len(lead)))
    lines = [
        *_section("ANSWER", answer),
        *_section("PLAN", _plan(response)),
        *_section("TOOL TRACE", _trace(response, participant_sql_digest())),
        *_section("PRODUCTS", products),
        *_section("CITATIONS", _citations(response)),
        f"OUTCOME: {response['outcome']}",
    ]
    if response.get("decline_reason"):
        lines.append(f"DECLINE REASON: {response['decline_reason']}")
    lines.append(f"Run ID: {response['agent_run_id']}")
    return "\n".join(lines)


def response_timeout() -> float:
    """Seconds to wait for the answer: longer than the API can take to return one."""
    return get_settings().agent_turn_deadline_seconds + RESPONSE_MARGIN_SECONDS


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
            args.api_url,
            "/api/agent/answer",
            {"question": args.question},
            timeout=response_timeout(),
        )
    except LabValidationError as error:
        print(f"Retrieval agent request failed: {error}", file=sys.stderr)
        return 1
    print(render(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
