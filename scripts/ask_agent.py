"""Ask your deployed Retrieval agent one question from the terminal and print its answer of record.

    uv run python scripts/ask_agent.py "QUESTION"

The question goes through the same streaming API route as Ask Mosaic, so it reaches your
Retrieval agent on AgentCore Runtime; while you wait, a bar shows each stage the run reaches
and each tool call prints as the Retrieval agent makes it.
The output shows the answer, the searches the Retrieval agent planned with the
filters it chose, the tool trace, the products, each citation's type, product, source
and quote, the outcome, any decline reason and the run ID. The trace names each catalog
tool's route (through AgentCore Gateway when the Retrieval agent is deployed) and, under each
search, whether Aurora ran the search SQL in your lab files. A declined answer is an
answer of record, not a failure: every run is saved in mosaic.agent_turn and its tool
calls in mosaic.agent_tool_event.
"""

from __future__ import annotations

import argparse
import http.client
import json
import re
import sys
import textwrap
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.progress import bar
from scripts.validate_lab import LabValidationError
from service.config import get_settings
from service.lab_validation_receipt import participant_sql_digest
from service.participant_commands import APPLY_SQL, STATUS
from service.participant_commands import ask_agent as ask_command

# Code Editor's terminal on a 16-inch laptop holds 124 characters a line. Every line stays
# well inside it, so a long title or quote is shortened rather than wrapped mid-word.
LINE_CHARS = 100
QUOTE_CHARS = LINE_CHARS - 8  # inside its six-space indent and quotation marks
MIN_QUESTION = 4  # AgentRequest.question's own minimum
# The API waits for Runtime up to the turn deadline plus its own 30 s transport
# margin, then saves the run; waiting longer means the Run ID always prints.
RESPONSE_MARGIN_SECONDS = 60
STREAM_PATH = "/api/agent/answer/stream"
# The stages the streaming route reports, in order; a follow-up skips retrieval.
STAGES = ("understand", "retrieve", "rank", "answer")


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


def _search_sql(applied: str | None, workspace: str | None) -> str:
    """Which search SQL Aurora ran for one search, against the lab files in Code Editor."""
    if workspace is None:
        return (
            "A lab SQL file could not be read, so the search SQL Aurora ran cannot be "
            f"compared with it; {STATUS} names the file"
        )
    if applied is None:
        return (
            "Aurora has no record of which search SQL ran; "
            f"apply your lab files with {APPLY_SQL}"
        )
    if applied == workspace:
        return f"Aurora ran your Lab 1 and Lab 2 SQL ({applied[:12]}), the same as your lab files"
    return (
        f"Aurora ran search SQL {applied[:12]}, not your lab files' {workspace[:12]}; "
        f"apply them with {APPLY_SQL}"
    )


def _trace(response: dict[str, Any], workspace: str | None) -> list[str]:
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


def _workspace_digest() -> str | None:
    """The lab SQL files' digest, or None when one was deleted: the Run ID still prints."""
    try:
        return participant_sql_digest()
    except OSError:
        return None


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
        *_section("TOOL TRACE", _trace(response, _workspace_digest())),
        *_section("PRODUCTS", products),
        *_section("CITATIONS", _citations(response)),
        f"OUTCOME: {response['outcome']}",
    ]
    if response.get("decline_reason"):
        lines.append(f"DECLINE REASON: {response['decline_reason']}")
    lines.append(f"Run ID: {response['agent_run_id']}")
    return "\n".join(lines)


def _events(lines: Iterable[bytes]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Read server-sent events as (event name, decoded data) pairs."""
    event, data = "message", []
    for raw in lines:
        line = raw.decode("utf-8").rstrip("\r\n")
        if line.startswith("event:"):
            event = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data.append(line.removeprefix("data:").strip())
        elif not line:
            if data:
                yield event, json.loads("\n".join(data))
            event, data = "message", []


def ask(base_url: str, question: str, *, timeout: float) -> dict[str, Any]:
    """Ask through Ask Mosaic's streaming route; print each stage the run reaches.

    The bar counts stages reached, not time. A run can return to retrieval after
    reading evidence, so it shows the furthest stage and never moves backward.
    """
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    # The same shared origin secret `_request` presents on this loopback call.
    origin_secret = get_settings().origin_verify_secret
    if origin_secret:
        headers["X-Mosaic-Origin-Verify"] = origin_secret
    request = Request(
        f"{base_url.rstrip('/')}{STREAM_PATH}",
        data=json.dumps({"question": question}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    started, reached = time.monotonic(), -1
    try:
        with urlopen(request, timeout=timeout) as response:
            for event, data in _events(response):
                elapsed = int(time.monotonic() - started)
                stage = data.get("id") if event == "stage" else None
                if stage in STAGES and STAGES.index(stage) > reached:
                    reached = STAGES.index(stage)
                    print(
                        f"{bar(reached, len(STAGES))}  {data['title']}, {elapsed} s",
                        flush=True,
                    )
                elif event == "tool":
                    print(f"      tool call  {data['name']}, {elapsed} s", flush=True)
                elif event == "notice":
                    note = textwrap.fill(
                        f"NOTE  {data.get('detail', '')}",
                        LINE_CHARS,
                        subsequent_indent="      ",
                    )
                    print(f"{note}\n", flush=True)
                elif event == "complete":
                    print(f"{bar(1, 1)}  answered in {elapsed} s\n", flush=True)
                    return data["response"]
                elif event == "error":
                    raise LabValidationError(
                        f"{STREAM_PATH} stopped: {data.get('detail', 'no reason given')}"
                    )
    except TimeoutError as error:
        raise LabValidationError(
            f"{STREAM_PATH} sent no response within {timeout:.0f} s; fix: run the command "
            "again, and if it times out twice, give this message to your facilitator"
        ) from error
    except HTTPError as error:
        detail = _error_detail(error.read().decode("utf-8", errors="replace"))
        raise LabValidationError(
            f"{STREAM_PATH} returned HTTP {error.code}: {detail}"
        ) from error
    except URLError as error:
        raise LabValidationError(
            f"{STREAM_PATH} is unavailable at {base_url}: {error.reason}; "
            "fix: run `systemctl status mosaic-api` in the terminal. If it is not "
            "active, tell your facilitator"
        ) from error
    except (http.client.HTTPException, ValueError) as error:
        # The connection dropped or sent a broken event after the run began, so the
        # API may still have saved it.
        raise LabValidationError(
            f"{STREAM_PATH} broke off mid-answer ({type(error).__name__}); the "
            "Retrieval agent may still have saved this run. Fix: run the command "
            "again, and if it happens twice, give this message to your facilitator"
        ) from error
    raise LabValidationError(
        f"{STREAM_PATH} closed before the answer; fix: run the command again, and if "
        "it happens twice, give this message to your facilitator"
    )


def _error_detail(body: str) -> str:
    """The API's own sentence when it sent one, so a refusal reads as its reason and Next step."""
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, AttributeError):
        return body
    return detail if isinstance(detail, str) else body


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
            f"fix: {ask_command('Find headphones for calls')}",
            file=sys.stderr,
        )
        return 2
    try:
        response = ask(args.api_url, args.question, timeout=response_timeout())
    except LabValidationError as error:
        print(f"Retrieval agent request failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        # Only the wait stops: the API keeps the turn and saves its answer when it finishes.
        print(
            "\nStopped waiting for the answer. The Retrieval agent may still finish this run "
            "and save it.",
            file=sys.stderr,
        )
        return 130
    print(render(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
