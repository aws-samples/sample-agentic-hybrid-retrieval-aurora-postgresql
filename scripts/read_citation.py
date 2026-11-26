"""Read the whole record behind one citation of a saved Retrieval agent run.

    uv run python scripts/read_citation.py NUMBER
    uv run python scripts/read_citation.py NUMBER --run-id RUN_ID

It prints the answer's sentences that cite [NUMBER], then the record that citation names, in
full. `»` marks the answer check's saved supporting passage when the run saved one for this
citation that sits in one place of the record, and otherwise a suggested line to inspect,
picked by shared figures and words. It ends with the sentences and the marked passage again,
above `Next:`, so a long record never pushes them out of view. Without --run-id it reads
Alex's setup run that Lab 3 completion grades, chosen by `grade_setup_run.py`'s own rule, so
a later question from Ask Mosaic or Playground cannot take its place; before Lab 3 starts no
run is graded, so an earlier answer is read by its Run ID. It reads what the run saved in Aurora:
the answer, and the records its successful `synthesize_cited_answer` step cited. Nothing is
asked again, so the record is the one the answer was checked against.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ask_agent import LINE_CHARS as WIDTH
from scripts.cited_lines import (
    cited_excerpt,
    locate_quotes,
    saved_support_quotes,
    without_review_markup,
)
from scripts.terminal_text import (
    BOLD,
    REOPEN_TERMINAL,
    aurora_cause,
    next_step,
    separate_next,
    tidy,
    tint,
    wrap_words,
)
from service.db import DatabaseNotConfigured
from service.participant_commands import ASK_SETUP_IN_MOSAIC, read_citation_command

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_LABEL = re.compile(r"^(?:title|description)\s*:\s*", re.IGNORECASE)
_CITED = """
    (SELECT event.output_payload -> 'citations'
     FROM mosaic.agent_tool_event AS event
     WHERE event.agent_turn_id = turn.agent_turn_id
       AND event.tool_name = 'synthesize_cited_answer'
       AND event.outcome = 'success'
     ORDER BY event.occurred_at DESC
     LIMIT 1)
"""


def saved_run(connection: Any, run_id: UUID) -> dict[str, Any] | None:
    """The run's answer, outcome and the citations its answer was checked with."""
    return connection.execute(
        f"""
        SELECT turn.agent_turn_id, turn.user_message, turn.assistant_message,
               turn.created_at, turn.extracted_intent ->> 'outcome' AS outcome,
               {_CITED} AS citations,
               turn.extracted_intent #> ARRAY['usage', 'synthesis', 'claim_review'] AS claim_review
        FROM mosaic.agent_turn AS turn
        WHERE turn.agent_turn_id = %(run_id)s
        """,
        {"run_id": run_id},
    ).fetchone()


def graded_setup_run_id(connection: Any, started_at: datetime) -> UUID | None:
    """The setup run Lab 3 completion grades, by `grade_setup_run.py`'s own rule."""
    from scripts.grade_setup_run import pick_setup_run
    from service.lab_checks import mission_for_lab

    mission = mission_for_lab(3)
    pick = pick_setup_run(
        connection,
        mission["query"],
        started_at,
        follow_up=mission["changed_requirement"]["query"],
    )
    return pick.run["agent_turn_id"] if pick.run else None


def lab_3_start() -> tuple[datetime | None, str | None]:
    """When Lab 3 started, which the default run needs, or why it has no default run."""
    from scripts import grade_setup_run
    from scripts.lab_entry import StartRecordError
    from service.agent_deploys import lab_3_started_at

    try:
        started = lab_3_started_at(grade_setup_run.ROOT)
    except StartRecordError:
        # The record's own fix is a reset, which discards the participant's agent.py.
        # Reading a citation needs only the run, which its Run ID names without the record.
        return None, (
            "Citation rule: the saved start of Lab 3 cannot be read, so the setup run "
            "completion grades cannot be picked for you; fix: name the run yourself with "
            "--run-id and the Run ID that ask_agent.py printed for the answer"
        )
    if started is None:
        # Before the start, the run the grader would pick is one it then refuses.
        return None, (
            "Citation rule: Lab 3 has not started, so completion grades no setup run "
            "yet; fix: name the run yourself with --run-id and the Run ID that "
            "ask_agent.py printed for the answer"
        )
    return started, None


def citing_sentences(answer: str, number: int) -> list[str]:
    """The answer's sentences and bullets that cite [number], whole."""
    marker = f"[{number}]"
    return [s.strip() for s in _SENTENCE.split(answer) if marker in s]


def record_lines(quote: str) -> list[str]:
    """Every line of the record, its categories included, as the site shows the text.

    Only the Title and Description labels go: the name and the text read without them.
    """
    lines = re.split(r"<br\s*/?>|\n", without_review_markup(quote), flags=re.IGNORECASE)
    kept = [_LABEL.sub("", line.strip()) for line in lines]
    return [line for line in kept if line]


def shown_record(citation: dict[str, Any]) -> str:
    """The record as the site shows it: a review's title, then its text.

    The answer check may quote a record's title as well as its text. A listing's text
    already opens with its own `Title:` line, so it is shown as saved. A review gets its
    saved title added as `Review title:`, which stays on screen where a listing's
    `Title:` label goes, unless its text already opens with that same title. A review
    body that opens with `Description:` or `Title:` is still a body.
    """
    text = citation["quote"]
    title = " ".join((citation.get("title") or "").split())
    first = next((line for line in text.splitlines() if line.strip()), "")
    opening = " ".join(_LABEL.sub("", first.strip()).split())
    if not title or opening == title:
        return text
    if citation.get("evidence_type") != "customer_review" and _LABEL.match(first):
        return text
    return f"{REVIEW_TITLE} {title}\n\n{text}"


def _marked(text: str) -> list[str]:
    """The quoted line, wrapped under `  » `, in bold on a terminal."""
    wrapped = wrap_words(text, WIDTH, initial_indent="  » ", subsequent_indent="    ")
    # Bold after wrapping: its escape codes would otherwise count as width.
    return [w[:4].replace("»", tint("»", BOLD)) + tint(w[4:], BOLD) for w in wrapped]


def _sentences(sentences: list[str]) -> list[str]:
    out = []
    for sentence in sentences:
        out += wrap_words(sentence, WIDTH, initial_indent="  ", subsequent_indent="  ")
    return out


REVIEW_TITLE = "Review title:"
SAVED_LABEL = "The answer check's saved supporting passage"
SUGGESTED_LABEL = "Suggested line to inspect"
SAVED_NOTE = (
    "The answer check saved this quote for the claim. Other lines may support it too."
)
SUGGESTED_NOTE = (
    "Picked by shared figures and words, not by the answer check. The claim may rest on "
    "other lines."
)


def _marks(
    quote: str, body: str, answer: str, number: int, saved: dict[str, Any] | None
) -> tuple[dict[int, list[tuple[int, int]]], list[str], bool, list[str]]:
    """Where `»` goes: line index to spans, the marked texts, whether they are saved, and
    the figures no line states.

    The answer check's saved quotes win when each sits in one place of the record; otherwise
    the figure and shared-word heuristic suggests a line.
    """
    lines = record_lines(quote)
    excerpt = cited_excerpt(body, answer, number)
    unstated = cited_excerpt(quote, answer, number).unstated
    quotes = saved_support_quotes(saved, answer, number)
    located = locate_quotes(lines, quotes) if quotes else None
    if located:
        squashed = {i: " ".join(lines[i].split()) for i in located}
        texts = [squashed[i][a:b] for i in sorted(located) for a, b in located[i]]
        return located, texts, True, unstated
    marks = {
        i: [(line.index(excerpt.line), line.index(excerpt.line) + len(excerpt.line))]
        for i, line in enumerate(lines)
        if excerpt.line and excerpt.line in line
    }
    return marks, [excerpt.line] if excerpt.line else [], False, unstated


def render(
    run: dict[str, Any], citation: dict[str, Any], graded: bool = False
) -> list[str]:
    """The cited sentences, the citation's header, the whole record with its marked
    passage, then the sentences and the marked passage again.

    The marked passage is the answer check's saved supporting quote when the run kept one
    for this citation, and a suggested line otherwise.
    """
    answer = run["assistant_message"] or ""
    number = citation["number"]
    shown = shown_record(citation)
    lines = record_lines(shown)
    marks, marked, saved, unstated = _marks(
        shown, citation["quote"], answer, number, run.get("claim_review")
    )
    asked = (
        f"{run['created_at']:%H:%M:%S} UTC" if run["created_at"] else "an unknown time"
    )
    out = [f"Run {run['agent_turn_id']}, asked at {asked}, OUTCOME: {run['outcome']}"]
    if graded:
        out.append(
            "Alex's setup run, the one completion grades. --run-id reads another run."
        )
    out.append("")
    out.append(tint(f"THE ANSWER'S SENTENCES THAT CITE [{number}]", BOLD))
    sentences = citing_sentences(answer, number)
    out += _sentences(sentences)
    source = citation["source_uri"].rstrip("/").rsplit("/", 1)[-1]
    header = (
        f"[{number}] {citation['evidence_type']}  {citation['product_id']}  "
        f"{source} @ {citation['revision'][:12]}"
    )
    label = SAVED_LABEL if saved else SUGGESTED_LABEL
    legend = f"{tint('THE WHOLE RECORD', BOLD)} ({tint('»', BOLD)} {label})"
    out += ["", header, legend]
    out += wrap_words(
        SAVED_NOTE if saved else SUGGESTED_NOTE,
        WIDTH,
        initial_indent="  ",
        subsequent_indent="  ",
    )
    for index, line in enumerate(lines):
        out += _record_line(line, marks.get(index, []), saved)
    if unstated:
        out.append(f"  No line in this record states {', '.join(unstated)}.")
    heading = (
        "THE ANSWER CHECK'S SAVED SUPPORTING PASSAGE"
        if saved
        else "A SUGGESTED LINE TO INSPECT"
    )
    out += ["", tint(f"TO JUDGE: THE SENTENCE CITING [{number}] AND {heading}", BOLD)]
    out += _sentences(sentences)
    for text in marked:
        out += _marked(text)
    return out


def _record_line(line: str, spans: list[tuple[int, int]], saved: bool) -> list[str]:
    """One record line, wrapped; each marked span starts its own `»` line.

    A quote can be one sentence inside a long paragraph: it starts its own line so the
    marker points at it, with the paragraph's other words kept around it.
    """
    plain = {"initial_indent": "    ", "subsequent_indent": "    "}
    if not spans:
        return wrap_words(line, WIDTH, **plain)
    text = " ".join(line.split()) if saved else line
    out: list[str] = []
    at = 0
    for start, end in spans:
        before, marked = text[at:start].strip(), text[start:end]
        if before == REVIEW_TITLE:
            before, marked = "", f"{before} {marked}"
        if before:
            out += wrap_words(before, WIDTH, **plain)
        out += _marked(marked)
        at = end
    if text[at:].strip():
        out += wrap_words(text[at:].strip(), WIDTH, **plain)
    return out


def problem(run: dict[str, Any] | None, run_id: UUID | None, number: int) -> str | None:
    """Why there is no citation to read, with the way out."""
    if run is None and run_id is None:
        return (
            "Citation rule: found no answer to Alex's setup request since Lab 3 started. "
            f"Next: {ASK_SETUP_IN_MOSAIC} Then read one of its citations in Code Editor:\n"
            f"{read_citation_command(str(number))}"
        )
    if run is None:
        return (
            f"Citation rule: no saved run has the ID {run_id}; fix: copy the Run ID from "
            "the last lines of your ask_agent.py output"
        )
    numbers = sorted(c["number"] for c in run["citations"] or [])
    if not numbers:
        return (
            f"Citation rule: run {run['agent_turn_id']} has no cited answer (OUTCOME: "
            f"{run['outcome'] or 'none'}); fix: read a run that ended OUTCOME: grounded"
        )
    if number not in numbers:
        listed = ", ".join(f"[{n}]" for n in numbers)
        return (
            f"Citation rule: run {run['agent_turn_id']} cites {listed}, not [{number}]; "
            "fix: use one of those numbers"
        )
    return None


def _rerun(run: dict[str, Any] | None) -> str:
    if run is not None and run["citations"]:
        return read_citation_command("NUMBER", str(run["agent_turn_id"]))
    return read_citation_command()


@tidy
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "number",
        type=int,
        metavar="NUMBER",
        help="the citation number, such as 1 for [1]",
    )
    parser.add_argument(
        "--run-id",
        type=UUID,
        metavar="RUN_ID",
        help="read this run instead of Alex's setup run that completion grades",
    )
    args = parser.parse_args(argv)
    from service.db import connect

    rerun = read_citation_command(
        str(args.number), str(args.run_id) if args.run_id else None
    )
    started = None
    if args.run_id is None:
        started, unpicked = lab_3_start()
        if unpicked:
            named = read_citation_command(str(args.number), "RUN_ID")
            print(separate_next(unpicked, named, stream=sys.stderr), file=sys.stderr)
            return 2
    try:
        with connect() as connection:
            run_id = args.run_id or graded_setup_run_id(connection, started)
            run = saved_run(connection, run_id) if run_id else None
    except (DatabaseNotConfigured, psycopg.Error) as error:
        print(
            f"Citation rule: {aurora_cause(error)}. This is an environment problem, not a mistake in "
            "your work.",
            file=sys.stderr,
        )
        next_step(REOPEN_TERMINAL, rerun, stream=sys.stderr)
        return 2
    reason = problem(run, args.run_id, args.number)
    if reason:
        print(
            separate_next(reason, _rerun(run), stream=sys.stderr),
            file=sys.stderr,
        )
        return 2
    citation = next(c for c in run["citations"] if c["number"] == args.number)
    print("\n".join(render(run, citation, graded=args.run_id is None)))
    numbers = sorted(c["number"] for c in run["citations"])
    following = numbers[(numbers.index(args.number) + 1) % len(numbers)]
    next_step(
        "judge whether this record supports the sentence, then go back to the guide. To "
        "read another citation of this run, change the number:",
        read_citation_command(str(following), str(run["agent_turn_id"])),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
