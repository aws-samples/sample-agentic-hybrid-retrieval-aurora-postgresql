"""A verdict word is coloured on a terminal and plain everywhere else."""

from __future__ import annotations

import io

import pytest

from scripts.terminal_text import GREEN, RED, YELLOW, paint, use_color, verdict


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _a_colour_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)


@pytest.mark.parametrize(
    ("line", "word", "code"),
    [
        ("Lab 3 exercise: PASS (.local/lab-3/exercise-receipt.json)", "PASS", GREEN),
        ("PASS: G-007: right product in the top 10", "PASS", GREEN),
        ("Lab 2 exercise: FAIL (.local/lab-2/exercise-receipt.json)", "FAIL", RED),
        ("BLOCKED: the sentence cites no record", "BLOCKED", RED),
        ("Lab 3 exercise: CANNOT GRADE - no run yet", "CANNOT GRADE", YELLOW),
    ],
)
def test_on_a_terminal_only_the_verdict_word_is_coloured(line, word, code):
    painted = verdict(line, Terminal())

    assert painted == line.replace(word, f"\033[{code}m{word}\033[0m", 1)


def test_the_words_are_unchanged_so_colour_is_never_the_only_signal():
    painted = verdict("Lab 1: FAIL. The Logitech is missing.", Terminal())

    assert painted.replace(f"\033[{RED}m", "").replace("\033[0m", "") == (
        "Lab 1: FAIL. The Logitech is missing."
    )


def test_only_the_first_verdict_in_a_line_is_coloured():
    painted = verdict("FAIL: expected PASS on k=60", Terminal())

    assert painted == f"\033[{RED}mFAIL\033[0m: expected PASS on k=60"


def test_a_word_that_only_contains_a_verdict_is_left_alone():
    assert verdict("PASSING evidence saved", Terminal()) == "PASSING evidence saved"


def test_a_log_or_pipe_gets_the_plain_line():
    line = "Lab 2 exercise: PASS (.local/lab-2/exercise-receipt.json)"

    assert verdict(line, io.StringIO()) == line


def test_no_color_and_a_dumb_terminal_get_the_plain_line(monkeypatch):
    line = "PASS: RRF arithmetic correct"
    monkeypatch.setenv("NO_COLOR", "1")
    assert verdict(line, Terminal()) == line

    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("TERM", "dumb")
    assert not use_color(Terminal())
    assert verdict(line, Terminal()) == line


def test_paint_leaves_text_alone_without_colour():
    assert paint("FROM semantic", "33", False) == "FROM semantic"
    assert paint("FROM semantic", "33", True) == "\033[33mFROM semantic\033[0m"
