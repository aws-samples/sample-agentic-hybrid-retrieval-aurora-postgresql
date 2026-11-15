"""Read the whole record behind one citation of a saved Retrieval agent run.

    uv run python scripts/read_citation.py NUMBER
    uv run python scripts/read_citation.py NUMBER --run-id RUN_ID

It prints the answer's sentences that cite [NUMBER], then the record that citation names, in
full, with the line `ask_agent.py` quoted marked. Without --run-id it reads Alex's setup run
that Lab 3 completion grades, chosen by `grade_setup_run.py`'s own rule, so a later question
from Ask Mosaic or Playground cannot take its place. It reads what the run saved in Aurora:
the answer, and the records its successful `synthesize_cited_answer` step cited. Nothing is
asked again, so the record is the one the answer was checked against.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ask_agent import LINE_CHARS as WIDTH
from scripts.cited_lines import cited_excerpt, without_review_markup
from scripts.terminal_text import BOLD, next_step, separate_next, tidy, tint, wrap_words
from service.participant_commands import ask_setup_command, read_citation_command

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
               {_CITED} AS citations
        FROM mosaic.agent_turn AS turn
        WHERE turn.agent_turn_id = %(run_id)s
        """,
        {"run_id": run_id},
    ).fetchone()


def graded_setup_run_id(connection: Any) -> UUID | None:
    """The setup run Lab 3 completion grades, by `grade_setup_run.py`'s own rule."""
    from scripts.grade_setup_run import ROOT, pick_setup_run
    from service.agent_deploys import lab_3_started_at
    from service.lab_checks import mission_for_lab

    mission = mission_for_lab(3)
    pick = pick_setup_run(
        connection,
        mission["query"],
        lab_3_started_at(ROOT),
        follow_up=mission["changed_requirement"]["query"],
    )
    return pick.run["agent_turn_id"] if pick.run else None


def citing_sentences(answer: str, number: int) -> list[str]:
    """The answer's sentences and bullets that cite [number], whole."""
    marker = f"[{number}]"
    return [s.strip() for s in _SENTENCE.split(answer) if marker in s]


def record_lines(quote: str) -> list[str]:
    """The record as a shopper reads it: its name and lines, without ingest labels."""
    lines = re.split(r"<br\s*/?>|\n", without_review_markup(quote), flags=re.IGNORECASE)
    kept = [_LABEL.sub("", line.strip()) for line in lines]
    return [
        line for line in kept if line and not line.lower().startswith("categories:")
    ]


def render(
    run: dict[str, Any], citation: dict[str, Any], graded: bool = False
) -> list[str]:
    """The cited sentences, the citation's header and the whole record, its quote marked."""
    answer = run["assistant_message"] or ""
    number = citation["number"]
    excerpt = cited_excerpt(citation["quote"], answer, number)
    asked = (
        f"{run['created_at']:%H:%M:%S} UTC" if run["created_at"] else "an unknown time"
    )
    out = [f"Run {run['agent_turn_id']}, asked at {asked}, OUTCOME: {run['outcome']}"]
    if graded:
        out.append(
            "Alex's setup run, the one completion grades. --run-id reads another run."
        )
    out.append("")
    out.append(f"THE ANSWER'S SENTENCES THAT CITE [{number}]")
    for sentence in citing_sentences(answer, number):
        out += wrap_words(sentence, WIDTH, initial_indent="  ", subsequent_indent="  ")
    source = citation["source_uri"].rstrip("/").rsplit("/", 1)[-1]
    header = (
        f"[{number}] {citation['evidence_type']}  {citation['product_id']}  "
        f"{source} @ {citation['revision'][:12]}"
    )
    legend = f"THE WHOLE RECORD ({tint('»', BOLD)} marks the line the answer's quote comes from)"
    out += ["", header, legend]
    for line in record_lines(citation["quote"]):
        if not excerpt.line or excerpt.line not in line:
            out += wrap_words(
                line, WIDTH, initial_indent="    ", subsequent_indent="    "
            )
            continue
        # The quote can be one sentence inside a long paragraph: it starts its own line so
        # the marker points at it, with the paragraph's other words kept around it.
        before, _, after = line.partition(excerpt.line)
        for text, lead in (
            (before.strip(), "    "),
            (excerpt.line, "  » "),
            (after.strip(), "    "),
        ):
            if not text:
                continue
            wrapped = wrap_words(
                text, WIDTH, initial_indent=lead, subsequent_indent="    "
            )
            if text == excerpt.line:
                # Bold after wrapping: its escape codes would otherwise count as width.
                wrapped = [
                    w[:4].replace("»", tint("»", BOLD)) + tint(w[4:], BOLD)
                    for w in wrapped
                ]
            out += wrapped
    if excerpt.unstated:
        out.append(f"  No line in this record states {', '.join(excerpt.unstated)}.")
    return out


def problem(run: dict[str, Any] | None, run_id: UUID | None, number: int) -> str | None:
    """Why there is no citation to read, with the way out."""
    if run is None and run_id is None:
        return (
            "Citation rule: found no answer to Alex's setup request since Lab 3 started; "
            "fix: ask it first, then read one of its citations"
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


def _rerun(run: dict[str, Any] | None, run_id: UUID | None) -> str:
    if run is None and run_id is None:
        return ask_setup_command()
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

    try:
        with connect() as connection:
            run_id = args.run_id or graded_setup_run_id(connection)
            run = saved_run(connection, run_id) if run_id else None
    except ValueError as error:
        # An unreadable Lab 3 start record names its own fix.
        print(separate_next(f"Citation rule: {error}"), file=sys.stderr)
        return 2
    reason = problem(run, args.run_id, args.number)
    if reason:
        print(separate_next(reason, _rerun(run, args.run_id)), file=sys.stderr)
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
