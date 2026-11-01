"""Participant output wraps only at spaces: a hyphenated word or a long ID stays whole."""

from scripts.terminal_text import fill_words, wrap_words


def test_a_hyphenated_word_at_the_margin_is_not_split():
    lines = wrap_words("a" * 93 + " noise-cancelling", 100)

    assert lines == ["a" * 93, "noise-cancelling"]


def test_a_word_wider_than_the_line_stays_whole():
    assert wrap_words("x" * 120, 100) == ["x" * 120]


def test_indents_apply_to_the_first_and_following_lines():
    text = fill_words("word " * 30, 40, initial_indent="  ", subsequent_indent="    ")

    first, *rest = text.splitlines()
    assert first.startswith("  word") and all(
        line.startswith("    word") for line in rest
    )
    assert all(len(line) <= 40 for line in text.splitlines())
