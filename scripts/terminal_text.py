"""Wrap participant terminal output at word boundaries.

Code Editor's terminal breaks a line that is wider than its window mid-word, so every
participant command wraps its prose itself. `textwrap` alone still breaks at hyphens,
which splits "noise-cancelling" or "USB-C" across lines.
"""

from __future__ import annotations

import textwrap


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
