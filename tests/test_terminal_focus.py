"""Bold marks the lines a participant reads first in a long output, on a terminal only."""

from __future__ import annotations

import io
import re
import sys

import pytest

from scripts import ask_agent, lab_exercise, read_citation
from scripts.terminal_text import BOLD, next_step
from tests.test_ask_agent import grounded
from tests.test_read_citation import run
from tests.test_rerank_off_on import OFF, ON, TARGET, off_on

ON_BOLD = f"\033[{BOLD}m"
OFF_ALL = "\033[0m"
ESCAPES = re.compile(r"\033\[[0-9;]*m")


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _a_colour_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)


def _on_a_terminal(monkeypatch: pytest.MonkeyPatch) -> Terminal:
    """Point stdout at a terminal inside the test: pytest swaps stdout after fixtures run."""
    screen = Terminal()
    monkeypatch.setattr(sys, "stdout", screen)
    return screen


def _bold(text: str) -> str:
    return f"{ON_BOLD}{text}{OFF_ALL}"


def test_next_is_bold_on_a_terminal_and_plain_in_a_pipe():
    screen, pipe = Terminal(), io.StringIO()

    next_step(
        "apply your SQL:",
        "uv run python scripts/apply_search_functions.py",
        stream=screen,
    )
    next_step(
        "apply your SQL:",
        "uv run python scripts/apply_search_functions.py",
        stream=pipe,
    )

    assert screen.getvalue().startswith(f"\n{_bold('Next:')} apply your SQL:\n")
    assert pipe.getvalue().startswith("\nNext: apply your SQL:\n")
    assert ESCAPES.sub("", screen.getvalue()) == pipe.getvalue()


def test_an_answer_bolds_its_headings_run_id_and_each_citation_kind(monkeypatch):
    _on_a_terminal(monkeypatch)
    text = ask_agent.render(grounded())

    for heading in ("ANSWER", "PLAN", "TOOL TRACE", "PRODUCTS", "CITATIONS"):
        assert f"\n{_bold(heading)}\n" in f"\n{text}"
    assert _bold(f"Run ID: {grounded()['agent_run_id']}") in text
    assert f"[1] {_bold('product_spec')}" in text
    assert f"[2] {_bold('customer_review')}" in text


def test_an_answer_reads_the_same_without_colour(monkeypatch):
    piped = ask_agent.render(grounded())
    monkeypatch.setattr(sys, "stdout", Terminal())

    assert ESCAPES.sub("", ask_agent.render(grounded())) == piped
    assert "[1] product_spec     1492978" in piped


def test_the_starred_monitor_is_bold_and_the_columns_still_line_up(monkeypatch):
    piped = off_on.render(OFF, ON, TARGET)
    monkeypatch.setattr(sys, "stdout", Terminal())

    painted = off_on.render(OFF, ON, TARGET)

    assert _bold("* ViewSonic VG2756-4K 27 inch 4K UHD mo…") in painted
    assert ESCAPES.sub("", painted) == piped


def test_the_served_profile_is_bold_and_the_k_rows_keep_their_plain_signs(monkeypatch):
    terminal = _on_a_terminal(monkeypatch)
    lab_exercise.print_comparison(
        {
            "baseline": {"exact_in_cutoff": 128, "billed_search_units_per_query": 1},
            "rows": [
                {
                    "label": "k = 120",
                    "exact_gain": -1,
                    "queries_better": 2,
                    "queries_worse": 3,
                    "sign_test_p": 1.0,
                    "billed_search_units_per_query": 1,
                    "chair_controls_moved": [],
                }
            ],
            "scope": "scope line",
        }
    )

    out = terminal.getvalue()
    assert out.startswith(_bold("Served profile: 128 exact matches reach reranking"))
    k_row = next(line for line in out.splitlines() if line.startswith("k = 120"))
    assert not ESCAPES.search(k_row)


def test_a_citation_reading_bolds_its_two_headings_and_the_marked_line(monkeypatch):
    citation = run()["citations"][0]
    piped = read_citation.render(run(), citation)
    _on_a_terminal(monkeypatch)

    painted = read_citation.render(run(), citation)

    assert _bold("THE ANSWER'S SENTENCES THAT CITE [1]") in painted
    assert any(line.startswith(_bold("THE WHOLE RECORD")) for line in painted)
    assert (
        _bold("TO JUDGE: THE SENTENCE CITING [1] AND A SUGGESTED LINE TO INSPECT")
        in painted
    )
    assert [ESCAPES.sub("", line) for line in painted] == piped


def test_an_error_paths_next_is_bold_on_a_terminal_and_plain_in_a_pipe():
    from scripts.terminal_text import lay_out_next, separate_next

    message = "Lab rule: something is missing."
    for helper in (
        lambda stream: separate_next(message, "uv run python x.py", stream=stream),
        lambda stream: lay_out_next(
            f"{message} Next: run uv run python x.py", stream=stream
        ),
    ):
        painted, piped, unset = helper(Terminal()), helper(io.StringIO()), helper(None)
        assert _bold("Next:") in painted
        assert "\033" not in piped and piped == unset
        assert ESCAPES.sub("", painted) == piped


def test_read_citations_failure_prints_a_bold_next_to_a_terminals_stderr(monkeypatch):
    from tests.test_read_citation import RUN_ID, use

    use(monkeypatch, None)
    screen = Terminal()
    monkeypatch.setattr(sys, "stderr", screen)

    assert read_citation.main(["1", "--run-id", str(RUN_ID)]) == 2

    assert f"\n\n{_bold('Next:')} " in screen.getvalue()
