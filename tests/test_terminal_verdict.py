"""A verdict word is coloured on a terminal and plain everywhere else."""

from __future__ import annotations

import io
import sys

import pytest

from scripts.terminal_text import (
    CONTRIBUTION_COLORS,
    GREEN,
    OUTCOME_COLORS,
    RED,
    RUN_BY,
    STATE_COLORS,
    STEP_COLORS,
    TIER_COLORS,
    YELLOW,
    next_step,
    paint,
    separate_next,
    tidy,
    tint,
    use_color,
    verdict,
)


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


@pytest.mark.parametrize(
    ("line", "words", "phrase", "code"),
    [
        ("Runtime code: passed", STEP_COLORS, "passed", GREEN),
        ("Gateway sync: failed", STEP_COLORS, "failed", RED),
        (
            "k=60   contribution correct; target",
            CONTRIBUTION_COLORS,
            "contribution correct",
            GREEN,
        ),
        (
            "k=5    contribution WRONG; target",
            CONTRIBUTION_COLORS,
            "contribution WRONG",
            RED,
        ),
        ("OUTCOME: grounded", OUTCOME_COLORS, "OUTCOME: grounded", GREEN),
        ("OUTCOME: declined", OUTCOME_COLORS, "OUTCOME: declined", YELLOW),
        ("Shrink it: FAST AND SMALL", TIER_COLORS, "FAST AND SMALL", GREEN),
        ("Shrink it: FAST", TIER_COLORS, "FAST", GREEN),
        ("Shrink it: NOT YET", TIER_COLORS, "NOT YET", YELLOW),
        ("Lab 1: SOLVED", STATE_COLORS, "SOLVED", GREEN),
        ("Lab 1: BROKEN", STATE_COLORS, "BROKEN", RED),
        (
            "Lab 3: REPAIRED, NOT DEPLOYED. Next",
            STATE_COLORS,
            "REPAIRED, NOT DEPLOYED",
            YELLOW,
        ),
    ],
)
def test_the_other_words_are_coloured_on_a_terminal_and_plain_when_piped(
    line, words, phrase, code
):
    assert verdict(line, Terminal(), words=words) == line.replace(
        phrase, f"\033[{code}m{phrase}\033[0m", 1
    )
    assert verdict(line, io.StringIO(), words=words) == line


def test_a_longer_phrase_wins_over_the_shorter_one_it_starts_with():
    painted = verdict("FAST AND SMALL", Terminal(), words=TIER_COLORS)

    assert painted == f"\033[{GREEN}mFAST AND SMALL\033[0m"


def test_every_occurrence_is_coloured_when_asked():
    painted = verdict("a passed, b passed", Terminal(), words=STEP_COLORS, every=True)

    assert painted.count(f"\033[{GREEN}mpassed") == 2


def test_tint_follows_the_stream():
    assert tint("Applied", GREEN, Terminal()) == f"\033[{GREEN}mApplied\033[0m"
    assert tint("Applied", GREEN, io.StringIO()) == "Applied"


def test_next_step_ends_with_a_blank_line_then_the_step(capsys):
    next_step("apply your SQL:", "uv run python scripts/apply_search_functions.py")

    assert capsys.readouterr().out == (
        "\nNext: apply your SQL:\nuv run python scripts/apply_search_functions.py\n"
    )


def test_next_step_waits_for_the_command_that_runs_this_one(capsys, monkeypatch):
    monkeypatch.setenv(RUN_BY, "Finish Lab 1")

    next_step("never printed")

    assert capsys.readouterr().out == ""


def test_next_step_wraps_prose_but_never_a_command(capsys):
    command = 'uv run python scripts/lab_state.py validate --lab 1 --database-url "$DATABASE_URL"'
    next_step("word " * 40, command)

    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == command
    assert all(len(line) <= 100 for line in lines[:-1])


@tidy
def _messy_main() -> int:
    print()
    print("first")
    print()
    print()
    print()
    print("second\n\n\nthird")
    print("fourth", end="")
    print("\n\n\n", end="")
    print("fifth")
    print("\nNext: go")
    return 0


def test_tidy_drops_a_leading_blank_and_never_prints_two_blanks_in_a_row(capsys):
    assert _messy_main() == 0

    out = capsys.readouterr().out
    assert out == "first\n\nsecond\n\nthird\nfourth\n\nfifth\n\nNext: go\n"
    assert not out.startswith("\n") and "\n\n\n" not in out


def test_tidy_restores_stdout_even_when_main_fails(capsys):
    before = sys.stdout

    @tidy
    def failing() -> int:
        raise SystemExit("boom")

    with pytest.raises(SystemExit):
        failing()
    assert sys.stdout is before


def test_tidy_passes_isatty_through_so_colour_still_follows_the_terminal(monkeypatch):
    seen = []

    @tidy
    def main() -> None:
        seen.append(use_color(sys.stdout))

    monkeypatch.setattr(sys, "stdout", Terminal())
    main()
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    main()

    assert seen == [True, False]


def test_a_nested_tidy_joins_the_outer_one(capsys):
    @tidy
    def inner() -> None:
        print("\ninner")

    @tidy
    def outer() -> None:
        print("outer")
        inner()
        print()
        print()

    outer()

    assert capsys.readouterr().out == "outer\n\ninner\n\n"


def test_separate_next_moves_an_inline_next_to_its_own_paragraph():
    assert (
        separate_next("Lab 1 failed. Next: do this.")
        == "Lab 1 failed.\n\nNext: do this."
    )
    assert (
        separate_next("Lab 1 failed.\nNext: do this.")
        == "Lab 1 failed.\n\nNext: do this."
    )


def test_separate_next_leaves_a_message_that_is_already_laid_out_alone():
    laid_out = "Lab 1 failed.\n\nNext: do this."
    several = "- a\n  Next: one\n- b\n  Next: two\nThen: x"

    assert separate_next(laid_out) == laid_out
    assert separate_next(several) == several


def test_separate_next_adds_the_rerun_when_the_message_names_none():
    assert separate_next("It broke.", "uv run python x.py") == (
        "It broke.\n\nNext: fix what it names above, then run\nuv run python x.py"
    )
    assert separate_next("It broke.") == "It broke."
