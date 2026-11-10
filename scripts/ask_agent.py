"""Ask your deployed Retrieval agent one question from the terminal and print its answer of record.

    uv run python scripts/ask_agent.py "QUESTION"

The question goes through the same streaming API route as Ask Mosaic, so it reaches your
Retrieval agent on AgentCore Runtime; while you wait, a bar shows each stage the run reaches
and each tool call prints as the Retrieval agent makes it. A draft the answer checks refuse
prints its reason at once, before the agent drafts again. On a terminal the bar is one line
redrawn in place with the time waited, and the answer prints as the API delivers it, after
its checks have passed.
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
import ast
import http.client
import json
import re
import sys
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, TextIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.progress import Waiting, bar, can_redraw
from scripts.prove_lab import LabValidationError, error_detail
from scripts.terminal_text import (
    GREEN,
    OUTCOME_COLORS,
    RED,
    YELLOW,
    fill_words,
    next_step,
    separate_next,
    tidy,
    tint,
    verdict,
    wrap_words,
)
from service.config import get_settings
from service.lab_validation_receipt import participant_sql_digest
from service.participant_commands import (
    APPLY_SQL,
    STATUS,
    ask_100w_command,
    ask_agent_command,
    ask_setup_command,
    grade_setup_run_command,
)

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
# What the waiting line says while a tool runs, where the tool's name says too little: this
# call is most of a run's wait, and the answer is held back until every check passes.
WAITING_ON = {
    "synthesize_cited_answer": "drafting, then checking every claim against its source",
}


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
# A tool call that worked is good, one that failed is bad, and one the application refused
# (a draft its checks denied) needs the participant's attention.
OUTCOME_WORD_COLORS = {"success": GREEN, "error": RED, "denied": YELLOW}


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
        outcome = tint(step["outcome"], OUTCOME_WORD_COLORS.get(step["outcome"], ""))
        lines.append(
            f"  {step['sequence']}  {step['tool']:<23}  {outcome}{took}{noted}"
        )
        if step["tool"] == "synthesize_cited_answer" and step["outcome"] == "error":
            lines.append(f"     {_refusal(step.get('detail') or '')}")
        if step["tool"] == "search_products" and step.get("route"):
            lines.append(
                f"     {_search_sql(step.get('search_sql_sha256'), workspace)}"
            )
    return lines


REFUSED = "draft refused"
UNSUPPORTED = "which no cited record supports"
# The application's own answer checks; any other failure of the draft step is the
# model or the service, not a refusal.
ANSWER_CHECKS = (
    "AnswerabilityError",
    "PartlySupportedSelection",
    "SynthesisOutputError",
    "SynthesisStopped",
    "SynthesisTruncated",
)


def _refusal(detail: str) -> str:
    """Say in plain words why the draft step failed.

    The trace detail names the Python exception and quotes the whole sentence; a
    participant needs only the rule the draft broke. A refused draft is not a failed
    run: the agent drafts again, and the next synthesize step shows the result.
    """
    failed = re.match(r"Synthesis failed with (\w+)", detail)
    if failed and failed.group(1) not in ANSWER_CHECKS:
        return f"draft step failed ({failed.group(1)}), not refused by a check"
    if match := re.search(
        r"unsupported numeric claim or availability claim (\[.*?\])", detail
    ):
        stated = ", ".join(str(value) for value in ast.literal_eval(match.group(1)))
        frame = f"     {REFUSED}: it stated , {UNSUPPORTED}"
        reason = f"it stated {_clip(stated, LINE_CHARS - len(frame))}, {UNSUPPORTED}"
    elif match := re.search(r"naming product (\d+) does not cite evidence", detail):
        reason = f"it named product {match.group(1)} without citing its records"
    elif match := re.search(
        r"unsupported compatibility claim (['\"])(.+?)\1 in:", detail
    ):
        frame = f"     {REFUSED}: it claimed '', {UNSUPPORTED}"
        claim = _clip(match.group(2), LINE_CHARS - len(frame))
        reason = f"it claimed '{claim}', {UNSUPPORTED}"
    elif "SynthesisTruncated" in detail:
        reason = "it was cut off before it finished"
    elif match := re.search(r"stopped with '(\w+)'", detail):
        reason = f"it stopped before it finished ({match.group(1)})"
    elif "did not cite every selected product" in detail:
        reason = "it left a selected product without a citation"
    elif "contains a link" in detail:
        reason = "it contained a link that is not a cited source"
    else:
        return f"{REFUSED} by the answer check"
    return f"{REFUSED}: {reason}"


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


def _answer_lines(text: str) -> list[str]:
    return [
        "  " + line
        for paragraph in text.splitlines()
        for line in (wrap_words(paragraph, 86) or [""])
    ]


def render(response: dict[str, Any], *, answer: bool = True) -> str:
    """The answer of record as plain text: answer, trace, products, citations, outcome.

    Args:
        response: The saved run.
        answer: `False` when the answer is already on screen, printed as it arrived.
    """
    products = []
    for item in response["recommendations"]:
        lead = f"  {item['product_id']}  "
        products.append(lead + _clip(item["title"], LINE_CHARS - len(lead)))
    closing = [verdict(f"OUTCOME: {response['outcome']}", words=OUTCOME_COLORS)]
    if response.get("decline_reason"):
        closing.append(f"DECLINE REASON: {response['decline_reason']}")
    closing.append(f"Run ID: {response['agent_run_id']}")
    parts = [
        *([_section("ANSWER", _answer_lines(response["answer"]))] if answer else []),
        _section("PLAN", _plan(response)),
        _section("TOOL TRACE", _trace(response, _workspace_digest())),
        _section("PRODUCTS", products),
        _section("CITATIONS", _citations(response)),
        closing,
    ]
    return "\n\n".join("\n".join(part) for part in parts)


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


class _Run:
    """One run's progress on screen.

    In a log every stage and tool call is a line. On a terminal the tool calls are lines
    and the stage is one line redrawn in place; the answer then prints as the API
    delivers it, which it does only after the answer's checks have passed.
    """

    def __init__(self, stream: TextIO) -> None:
        self.started, self.reached, self.title = time.monotonic(), -1, ""
        self.live = Waiting(stream) if can_redraw(stream) else None
        self.answer_shown, self._pending, self._doing = False, "", ""
        self._refused = 0

    def _elapsed(self) -> int:
        return int(time.monotonic() - self.started)

    def _waiting(self) -> None:
        if self.live:
            head = f"{bar(self.reached, len(STAGES))}  {self.title}"
            self.live.show(f"{head}: {self._doing}" if self._doing else head)

    def stage(self, data: dict[str, Any]) -> None:
        """Move to a later stage; a run that searches again never moves the bar back."""
        stage = data.get("id")
        if stage not in STAGES or STAGES.index(stage) <= self.reached:
            return
        self.reached, self.title = STAGES.index(stage), data["title"]
        if self.live:
            self._waiting()
        else:
            print(
                f"{bar(self.reached, len(STAGES))}  {self.title}, {self._elapsed()} s",
                flush=True,
            )

    def tool(self, name: str) -> None:
        # The route names a tool before the stage that tool opens, so the stage keeps it.
        print(f"      tool call  {name}, {self._elapsed()} s", flush=True)
        self._doing = WAITING_ON.get(name, name)
        self._waiting()

    def partial(self, trace: list[dict[str, Any]]) -> None:
        """Say why a draft was refused as soon as the run records it.

        The agent drafts again after a refusal, so the wait is longer; the reason is
        the same line the tool trace prints once the run ends.
        """
        refusals = [
            step.get("detail") or ""
            for step in trace
            if step.get("tool") == "synthesize_cited_answer"
            and step.get("outcome") == "error"
        ]
        for detail in refusals[self._refused :]:
            print(f"      {_refusal(detail)}; the agent drafts again", flush=True)
        self._refused = max(self._refused, len(refusals))

    def _answered(self) -> None:
        self.close()
        print(f"{bar(1, 1)}  answered in {self._elapsed()} s\n", flush=True)

    def answer_start(self) -> None:
        if self.live:
            self._answered()
            print("ANSWER", flush=True)
            self.answer_shown = True

    def answer_delta(self, delta: str) -> None:
        """Print each paragraph once it is whole, wrapped as the saved answer is."""
        if not self.answer_shown:
            return
        *whole, self._pending = (self._pending + delta).split("\n")
        for paragraph in whole:
            print("\n".join(_answer_lines(paragraph) or ["  "]), flush=True)

    def complete(self) -> None:
        if not self.answer_shown:
            self._answered()
        elif self._pending:
            print("\n".join(_answer_lines(self._pending)), flush=True)

    def close(self) -> None:
        """Take the waiting line down, whatever ended the run."""
        if self.live:
            self.live.stop()
            self.live = None


def _follow(events: Iterator[tuple[str, dict[str, Any]]], run: _Run) -> dict[str, Any]:
    """Show each event of a run and return its saved response."""
    for event, data in events:
        if event == "stage":
            run.stage(data)
        elif event == "tool":
            run.tool(data["name"])
        elif event == "partial":
            run.partial((data.get("partial") or {}).get("trace") or [])
        elif event == "notice":
            note = fill_words(
                f"NOTE  {data.get('detail', '')}",
                LINE_CHARS,
                subsequent_indent="      ",
            )
            print(f"{note}\n", flush=True)
        elif event == "answer_start":
            run.answer_start()
        elif event == "answer_delta":
            run.answer_delta(data.get("delta", ""))
        elif event == "complete":
            run.complete()
            return data["response"]
        elif event == "error":
            run_id = data.get("agent_run_id")
            raise LabValidationError(
                f"{STREAM_PATH} stopped: {data.get('detail', 'no reason given')}"
                + (f" Run ID: {run_id}" if run_id else "")
            )
    raise LabValidationError(
        f"{STREAM_PATH} closed before the answer; fix: run the command again, and if "
        "it happens twice, give this message to your facilitator"
    )


def ask(base_url: str, question: str, *, timeout: float) -> tuple[dict[str, Any], bool]:
    """Ask through Ask Mosaic's streaming route; show each stage the run reaches.

    The bar counts stages reached, not time. A run can return to retrieval after
    reading evidence, so it shows the furthest stage and never moves backward.

    Returns:
        The saved response, and whether its answer is already on screen.
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
    run = _Run(sys.stdout)
    try:
        with urlopen(request, timeout=timeout) as response:
            return _follow(_events(response), run), run.answer_shown
    except TimeoutError as error:
        raise LabValidationError(
            f"{STREAM_PATH} sent no response within {timeout:.0f} s; fix: run the command "
            "again, and if it times out twice, give this message to your facilitator"
        ) from error
    except HTTPError as error:
        detail = error_detail(error.read().decode("utf-8", errors="replace"))
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
    finally:
        run.close()


def response_timeout() -> float:
    """Seconds to wait for the answer: longer than the API can take to return one."""
    return get_settings().agent_turn_deadline_seconds + RESPONSE_MARGIN_SECONDS


def _answered_next(question: str, response: dict[str, Any]) -> None:
    """Print the step after an answer: the guide's follow-up, or the completion check."""
    from service.lab_checks import mission_for_lab, same_request

    if not same_request(mission_for_lab(3)["query"], question):
        next_step(
            "check completion on your newest setup run:", grade_setup_run_command()
        )
    elif response["outcome"] == "declined":
        next_step(
            "read the DECLINE REASON above, then ask Alex's setup request again:",
            ask_setup_command(),
        )
    else:
        next_step(
            "ask whether the ViewSonic meets a new need for 100W charging:",
            ask_100w_command(),
            "then check completion with:",
            grade_setup_run_command(),
        )


@tidy
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args(argv)
    if len(args.question.strip()) < MIN_QUESTION:
        print(
            f"Question rule: ask at least {MIN_QUESTION} characters, in quotes.",
            file=sys.stderr,
        )
        next_step(
            "ask a question of your own, or Alex's setup request from the guide, "
            "in quotes. For example:",
            ask_agent_command("Find headphones for calls"),
            stream=sys.stderr,
        )
        return 2
    try:
        response, answer_shown = ask(
            args.api_url, args.question, timeout=response_timeout()
        )
    except LabValidationError as error:
        message = f"Retrieval agent request failed: {error}"
        print(separate_next(message, ask_agent_command(args.question)), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        # Only the wait stops: the API keeps the turn and saves its answer when it finishes.
        print(
            "\nStopped waiting for the answer. The Retrieval agent may still finish this run "
            "and save it.",
            file=sys.stderr,
        )
        next_step(
            "wait a minute for the run to finish, then ask again:",
            ask_agent_command(args.question),
            stream=sys.stderr,
        )
        return 130
    print("\n" + render(response, answer=not answer_shown))
    _answered_next(args.question, response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
