"""Wrap and colour participant terminal output.

Code Editor's terminal breaks a line that is wider than its window mid-word, so every
participant command wraps its prose itself. `textwrap` alone still breaks at hyphens,
which splits "noise-cancelling" or "USB-C" across lines.

A check's verdict is the one word a participant looks for in a screen of output, so on a
terminal it is coloured: green for good, red for bad, yellow for needs attention. The word
itself always prints: colour is never the only signal, and a log, a pipe or a saved receipt
gets the plain line.

Every command also ends the same way, so a participant never has to go back to the guide: a
blank line, then `Next:` and the step that follows. `tidy` keeps the blank lines between a
command's parts to one each, and none before its first line.
"""

from __future__ import annotations

import functools
import os
import re
import sys
import textwrap
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TextIO

GREEN, RED, YELLOW = "1;32", "1;31", "1;33"
BOLD = "1"
VERDICT_COLORS = {
    "PASS": GREEN,
    "FAIL": RED,
    "BLOCKED": RED,
    "CANNOT GRADE": YELLOW,
}
# Words other commands colour the same way: a step's outcome in a deploy, a grade's
# per-value check, an answer's outcome, an index's result and a lab's state.
STEP_COLORS = {"passed": GREEN, "failed": RED}
CONTRIBUTION_COLORS = {"contribution correct": GREEN, "contribution WRONG": RED}
OUTCOME_COLORS = {"OUTCOME: grounded": GREEN, "OUTCOME: declined": YELLOW}
TIER_COLORS = {"FAST AND SMALL": GREEN, "FAST": GREEN, "NOT YET": YELLOW}
STATE_COLORS = {
    "SOLVED": GREEN,
    "BROKEN": RED,
    "FILE MISSING": RED,
    "START INTERRUPTED": YELLOW,
    "REPAIRED, NOT DEPLOYED": YELLOW,
    "DEPLOYED, NOT YET PROVED": YELLOW,
}
#: Set while `finish` or `skip-to` runs a command, which then leaves the next step to them.
RUN_BY = "MOSAIC_RUN_BY"
NEXT_WIDTH = 100


def use_color(stream: TextIO) -> bool:
    """Whether `stream` is a terminal that should get colour (https://no-color.org)."""
    isatty = getattr(stream, "isatty", None)
    return (
        bool(isatty and isatty())
        and "NO_COLOR" not in os.environ
        and os.environ.get("TERM", "") != "dumb"
    )


def paint(text: str, code: str, color: bool) -> str:
    """`text` in the ANSI colour `code` when `color` is true, unchanged otherwise."""
    return f"\033[{code}m{text}\033[0m" if color else text


def tint(text: str, code: str, stream: TextIO | None = None) -> str:
    """`text` in the colour `code` when `stream` (stdout when omitted) is a terminal."""
    return paint(text, code, use_color(stream or sys.stdout))


def verdict(
    line: str,
    stream: TextIO | None = None,
    *,
    words: dict[str, str] = VERDICT_COLORS,
    every: bool = False,
) -> str:
    """`line` with its first verdict word coloured when `stream` is a terminal.

    Args:
        line: Output that names a verdict, such as `Lab 2 exercise: PASS (receipt)`.
        stream: Where the line will be printed; stdout when omitted.
        words: The words to colour and the colour of each; the check verdicts by default.
            A longer phrase wins over a shorter one that starts the same way.
        every: Colour every occurrence rather than only the first.
    """
    if not use_color(stream or sys.stdout):
        return line
    ordered = sorted(words, key=len, reverse=True)
    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(word) for word in ordered) + r")\b"
    )
    return pattern.sub(
        lambda found: paint(found.group(), words[found.group()], True),
        line,
        count=0 if every else 1,
    )


def next_step(prose: str, *lines: str, stream: TextIO | None = None) -> None:
    """Print a command's last lines: a blank line, then `Next:` and the step that follows.

    Commands go on lines of their own, whole, so a terminal never breaks one and it can be
    copied as printed. Nothing prints while `finish` or `skip-to` runs this command, because
    they print the step after the last one themselves.

    Args:
        prose: What to do next, in words; end it with a colon when commands follow.
        lines: Commands to run, and any words between them, one per line.
        stream: Where to print; stdout when omitted.
    """
    if os.environ.get(RUN_BY):
        return
    wrapped = wrap_words(f"Next: {prose}", NEXT_WIDTH, subsequent_indent="      ")
    print("\n" + "\n".join([*wrapped, *lines]), file=stream or sys.stdout, flush=True)


_INLINE_NEXT = re.compile(r"(?:(?<=\S) |\n)(?=Next: )")


def separate_next(message: str, rerun: str | None = None) -> str:
    """A failure message with its `Next:` in a paragraph of its own, last.

    A message with no `Next:` gets one telling the participant to fix what it names and run
    `rerun` again, when given. A message that lists several (one per problem) is unchanged.
    """
    if message.count("Next: ") > 1 or "\n\nNext: " in message:
        return message
    if "Next: " in message:
        return _INLINE_NEXT.sub("\n\n", message, count=1)
    if rerun is None:
        return message
    return f"{message}\n\nNext: fix what the message above names, then run this again:\n{rerun}"


@contextmanager
def next_on_failure(rerun: str | None = None) -> Iterator[None]:
    """Give a command's text exit its `Next:` paragraph, whichever code raised it.

    Args:
        rerun: The command to name when the message has no `Next:` of its own.
    """
    try:
        yield
    except SystemExit as error:
        if isinstance(error.code, str):
            raise SystemExit(separate_next(error.code, rerun)) from error
        raise


class _Tidy:
    """Stands in for stdout so a command's blank lines come out one at a time.

    A command prints a blank line between its parts without knowing what came before, so a
    part that follows another's blank line, or opens the output, would leave two or one
    too many. This drops the extras: no blank line first, never two in a row.
    """

    def __init__(self, wrapped: TextIO) -> None:
        self._wrapped = wrapped
        # As if two newlines had just printed, so a blank line that opens the output is dropped.
        self._newlines = 2

    def write(self, text: str) -> int:
        if not text:
            return 0
        kept = re.sub(r"\n{3,}", "\n\n", text)
        lead = len(kept) - len(kept.lstrip("\n"))
        allowed = 2 - self._newlines
        if lead > allowed:
            kept = kept[lead - allowed :]
        if kept:
            trailing = len(kept) - len(kept.rstrip("\n"))
            self._newlines = (
                min(2, self._newlines + trailing) if trailing == len(kept) else trailing
            )
            self._wrapped.write(kept)
        return len(text)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


def tidy(main: Callable[..., int | None]) -> Callable[..., int | None]:
    """`main` with stdout tidied by `_Tidy`; a call nested in a tidied command joins it."""

    @functools.wraps(main)
    def tidied(*args: Any, **kwargs: Any) -> int | None:
        if isinstance(sys.stdout, _Tidy):
            return main(*args, **kwargs)
        saved = sys.stdout
        sys.stdout = _Tidy(saved)
        try:
            return main(*args, **kwargs)
        finally:
            sys.stdout = saved

    return tidied


def wrap_words(
    text: str, width: int, *, initial_indent: str = "", subsequent_indent: str = ""
) -> list[str]:
    """`text` as lines no wider than `width`, broken only at spaces."""
    return textwrap.wrap(
        text,
        width,
        initial_indent=initial_indent,
        subsequent_indent=subsequent_indent,
        break_long_words=False,
        break_on_hyphens=False,
    )


def fill_words(
    text: str, width: int, *, initial_indent: str = "", subsequent_indent: str = ""
) -> str:
    """`wrap_words` joined with newlines."""
    return "\n".join(
        wrap_words(
            text,
            width,
            initial_indent=initial_indent,
            subsequent_indent=subsequent_indent,
        )
    )
