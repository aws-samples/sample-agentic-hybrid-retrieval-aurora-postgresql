"""Wrap and colour participant terminal output.

Code Editor's terminal breaks a line that is wider than its window mid-word, so every
participant command wraps its prose itself. `textwrap` alone still breaks at hyphens,
which splits "noise-cancelling" or "USB-C" across lines.

A check's verdict is the one word a participant looks for in a screen of output, so on a
terminal it is coloured: green for good, red for bad, yellow for needs attention. The word
itself always prints: colour is never the only signal, and a log, a pipe or a saved receipt
gets the plain line.

A long output also marks the lines a participant reads first in bold: a section heading, the
Run ID, the row of the product a lab checks, a `prepared` line and `Next:`. Bold means "look
here", never good or bad, so it does not compete with the verdict colours.

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
from pathlib import Path
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
    "START RECORD UNREADABLE": RED,
    "START INTERRUPTED": YELLOW,
    "UNEXPECTED FILE": RED,
    "SHIPPED FILE DELETED": RED,
    "SHIPPED FILES CHANGED": RED,
    "REPAIRED, NOT DEPLOYED": YELLOW,
    "DEPLOYED, NOT YET PROVED": YELLOW,
}
#: The step after Aurora does not answer a participant command: a new terminal reloads the
#: workshop settings, and a repeat is the facilitator's to diagnose.
REOPEN_TERMINAL = (
    "open a new terminal from the Terminal menu, which loads the workshop settings, and "
    "run this command again; if it repeats, tell your facilitator:"
)
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


_NEXT_AT_LINE_START = re.compile(r"(?m)^Next:")


def bold_next(text: str, stream: TextIO | None) -> str:
    """Bold each `Next:` that starts a line, when stream is a terminal; the words never change."""
    if stream is None or not use_color(stream):
        return text
    return _NEXT_AT_LINE_START.sub(paint("Next:", BOLD, True), text)


def next_text(prose: str, *lines: str) -> str:
    """The text of a `Next:` paragraph: wrapped prose, then each command on its own line."""
    wrapped = wrap_words(f"Next: {prose}", NEXT_WIDTH, subsequent_indent="      ")
    return "\n".join([*wrapped, *lines])


_COMMAND_IN_PROSE = re.compile(
    r"uv run python [^,;]*?(?=[,;]|\.(?:\s|$)|\s+(?:then|and|or)\s|$)"
)


def lay_out_next(message: str, *, stream: TextIO | None = None) -> str:
    """A message whose `Next:` sits inline, as wrapped paragraphs with commands alone.

    The finding comes first, then a blank line, then the `Next:` prose wrapped to the
    width of `next_step`, with each `uv run python` command on a line of its own.
    A message with no `Next:` is only wrapped. With stream, `Next:` is bold on a terminal.
    """
    return bold_next(_lay_out_next(message), stream)


def _lay_out_next(message: str) -> str:
    finding, marker, after = message.partition("Next: ")
    if not marker:
        return fill_words(message, NEXT_WIDTH)
    lines: list[str] = []
    cursor = 0
    prose = after
    pieces: list[tuple[str, str]] = []
    for found in _COMMAND_IN_PROSE.finditer(prose):
        pieces.append((prose[cursor : found.start()], found.group()))
        cursor = found.end()
    tail = prose[cursor:]
    if pieces:
        tail = tail.lstrip(",;. ")
        tail = tail[:1].upper() + tail[1:]
    first = True
    for words, command in pieces:
        text = f"Next: {words}".rstrip() if first else words.strip()
        if text.strip() and text.strip() != "Next:" or first:
            lines += wrap_words(
                text, NEXT_WIDTH, subsequent_indent="      " if first else ""
            )
        lines.append(command)
        first = False
    if tail.strip() or (first and not pieces):
        text = f"Next: {tail}" if first else tail.strip()
        lines += wrap_words(
            text, NEXT_WIDTH, subsequent_indent="      " if first else ""
        )
    return fill_words(finding.strip(), NEXT_WIDTH) + "\n\n" + "\n".join(lines)


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
    out = stream or sys.stdout
    print("\n" + bold_next(next_text(prose, *lines), out), file=out, flush=True)


_INLINE_NEXT = re.compile(r"(?:(?<=\S) |\n)(?=Next: )")


def separate_next(
    message: str, rerun: str | None = None, *, stream: TextIO | None = None
) -> str:
    """A failure message with its `Next:` in a paragraph of its own, last.

    A message with no `Next:` gets one telling the participant to fix what it names and run
    `rerun` again, when given. A message that lists several (one per problem) is unchanged.
    With stream, each line-starting `Next:` is bold when that stream is a terminal.
    """
    return bold_next(_separate_next(message, rerun), stream)


def _separate_next(message: str, rerun: str | None) -> str:
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
            raise SystemExit(
                separate_next(error.code, rerun, stream=sys.stderr)
            ) from error
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


def _sqlstate(error: BaseException) -> str | None:
    return getattr(error, "sqlstate", None) or getattr(
        getattr(error, "diag", None), "sqlstate", None
    )


def _server_message(error: BaseException) -> str:
    """The server's own one-line reason for rejecting a statement."""
    primary = getattr(getattr(error, "diag", None), "message_primary", None)
    return (primary or (str(error).strip().splitlines() or [""])[0]).strip()


def cause_in_words(error: BaseException) -> str:
    """Why a call failed, in words a participant can read; empty when nothing is known.

    Decided from the exception's type and attributes, never its class name or the
    wording of its message. A database error with a SQLSTATE names it with the server's
    own reason, as `database_fault_exit` does.
    """
    import http.client
    import json
    import subprocess

    from botocore import exceptions as aws
    from psycopg import Error as DatabaseError
    from psycopg import errors as database_errors
    from psycopg_pool import PoolTimeout

    if isinstance(error, DatabaseError) and (state := _sqlstate(error)):
        return f"SQLSTATE {state}: {_server_message(error)}"
    if isinstance(
        error,
        (
            TimeoutError,
            subprocess.TimeoutExpired,
            PoolTimeout,
            database_errors.ConnectionTimeout,
            database_errors.QueryCanceled,
            aws.ConnectTimeoutError,
            aws.ReadTimeoutError,
        ),
    ):
        return "timed out"
    if isinstance(error, ConnectionRefusedError):
        return "connection refused"
    if isinstance(
        error,
        (
            ConnectionError,
            http.client.IncompleteRead,
            http.client.RemoteDisconnected,
            aws.ConnectionClosedError,
        ),
    ):
        return "connection cut off"
    if isinstance(error, json.JSONDecodeError):
        return "reply cut off or not JSON"
    if isinstance(error, aws.NoCredentialsError):
        return "no AWS credentials were found"
    if isinstance(error, aws.EndpointConnectionError):
        return "AWS could not be reached"
    if isinstance(error, DatabaseError):
        return "the connection failed"
    return ""


def cause_clause(error: BaseException) -> str:
    """` (cause)` for a message, or nothing when the cause is not known."""
    cause = cause_in_words(error)
    return f" ({cause})" if cause else ""


def aurora_cause(error: BaseException) -> str:
    """Why Aurora could not be used, in words, for a database or an unset DATABASE_URL."""
    if "DatabaseNotConfigured" in {cls.__name__ for cls in type(error).__mro__}:
        return "DATABASE_URL is empty in this terminal, so Aurora cannot be reached"
    from psycopg import Error as DatabaseError

    if isinstance(error, DatabaseError) and _sqlstate(error):
        from scripts.lab_state import is_environment_fault

        verb = (
            "did not answer" if is_environment_fault(error) else "rejected the request"
        )
        return f"Aurora {verb}{cause_clause(error)}"
    return f"Aurora did not answer{cause_clause(error)}"


_DATABASE_URL_TEXT = '"$DATABASE_URL"'
_DSN = re.compile(r"^[a-z][a-z0-9+.-]*://[^\s]*@", re.IGNORECASE)
_SAFE_WORD = re.compile(r"^[A-Za-z0-9_@%+=:,./-]+$")


def _quoted(word: str) -> str:
    """One argument as a participant types it: double quotes when it has spaces or marks."""
    if word and _SAFE_WORD.match(word):
        return word
    escaped = re.sub(r'(["\\$`])', r"\\\1", word)
    return f'"{escaped}"'


def _argument_words(arguments: list[str]) -> list[str]:
    """The arguments to show again, with a connection string never among them."""
    shown: list[str] = []
    redact_next = False
    for argument in arguments:
        if redact_next:
            shown.append(_DATABASE_URL_TEXT)
            redact_next = False
        elif argument == "--database-url":
            shown.append(argument)
            redact_next = True
        elif argument.startswith("--database-url=") or _DSN.match(argument):
            flag = "--database-url=" if argument.startswith("--database-url=") else ""
            shown.append(f"{flag}{_DATABASE_URL_TEXT}")
        else:
            shown.append(_quoted(argument))
    return shown


def _same_command() -> str:
    """The command this process was started with, as a participant types it.

    A connection string never appears: `--database-url` shows the `"$DATABASE_URL"` the
    guide types in its place.
    """
    main_module = sys.modules.get("__main__")
    spec = getattr(main_module, "__spec__", None)
    ran_as_module = (
        spec is not None
        and spec.origin
        and Path(spec.origin).resolve() == Path(sys.argv[0]).resolve()
    )
    if ran_as_module:
        target = ["-m", spec.name]
    else:
        script = Path(sys.argv[0]).resolve()
        try:
            target = [
                script.relative_to(Path(__file__).resolve().parents[1]).as_posix()
            ]
        except ValueError:
            target = [script.name]
    return " ".join(["uv run python", *target, *_argument_words(sys.argv[1:])])


def tidy(main: Callable[..., int | None]) -> Callable[..., int | None]:
    """`main` with stdout tidied by `_Tidy`; a call nested in a tidied command joins it.

    Ctrl+C in the outermost call stops the command in plain words, names the same command
    to run again and exits 130, rather than printing a traceback.
    """

    @functools.wraps(main)
    def tidied(*args: Any, **kwargs: Any) -> int | None:
        if isinstance(sys.stdout, _Tidy):
            return main(*args, **kwargs)
        saved = sys.stdout
        sys.stdout = _Tidy(saved)
        try:
            return main(*args, **kwargs)
        except KeyboardInterrupt:
            if not os.environ.get(RUN_BY):
                print("\nStopped before it finished.")
                next_step("run the same command again:", _same_command())
            return 130
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
