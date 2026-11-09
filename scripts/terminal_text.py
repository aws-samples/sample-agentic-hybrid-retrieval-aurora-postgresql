"""Wrap and colour participant terminal output.

Code Editor's terminal breaks a line that is wider than its window mid-word, so every
participant command wraps its prose itself. `textwrap` alone still breaks at hyphens,
which splits "noise-cancelling" or "USB-C" across lines.

A check's verdict is the one word a participant looks for in a screen of output, so on a
terminal it is coloured. The word itself always prints: colour is never the only signal,
and a log, a pipe or a saved receipt gets the plain line.
"""

from __future__ import annotations

import os
import re
import sys
import textwrap
from typing import TextIO

GREEN, RED, YELLOW = "1;32", "1;31", "1;33"
VERDICT_COLORS = {
    "PASS": GREEN,
    "FAIL": RED,
    "BLOCKED": RED,
    "CANNOT GRADE": YELLOW,
}
_VERDICT = re.compile(r"\b(?:" + "|".join(VERDICT_COLORS) + r")\b")


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


def verdict(line: str, stream: TextIO | None = None) -> str:
    """`line` with its first verdict word coloured when `stream` is a terminal.

    Args:
        line: Output that names a verdict, such as `Lab 2 exercise: PASS (receipt)`.
        stream: Where the line will be printed; stdout when omitted.
    """
    if not use_color(stream or sys.stdout):
        return line
    return _VERDICT.sub(
        lambda found: paint(found.group(), VERDICT_COLORS[found.group()], True),
        line,
        count=1,
    )


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
