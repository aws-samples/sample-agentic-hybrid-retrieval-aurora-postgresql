"""The progress participant commands show while they wait.

Nothing these commands wait on reports a percentage, so a bar claims only what is known: the
steps finished, how long the running step has taken, and how long each step usually takes,
measured on test events. Within a step the bar fills toward that usual time and never reaches
the end before the step does; past it, the line says the step is still working. Each finished
step leaves one line with how long it took and, when the steps' usual times are planned, about
how long is left.

On a terminal the running step's line redraws in place, and anything printed meanwhile lands
above it. Anywhere else (a log, a pipe, a capture) nothing redraws: a step prints one line as it
starts, with its label on a second line when the first would be too wide for the terminal, and
one as it ends. The step tracker follows the progress module of the Pellier workshop
(sample-pellier-agentic-search-apg, scripts/wait_progress.py).

    progress = Progress("Deploying your Retrieval agent")
    progress.plan([5, 16, 16, 21, 13])
    progress.begin("Update the tools runtime", typical=16, done="Updated the tools runtime")
    ...
    progress.finish()
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from collections.abc import Callable, Sequence
from typing import TextIO

WIDTH = 20
NARROWEST_BAR = 8
# A step's bar stops short of full until the step really ends.
MOST_OF_THE_BAR = 0.95
REDRAW_SECONDS = 0.5
# A step that ends sooner than this draws nothing, so an instant step does not flash a bar.
GRACE_SECONDS = 1.0
CLEAR_LINE = "\r\x1b[K"


def bar(done: float, total: float) -> str:
    """Render finished work as a bar and a percentage, such as `[██████████░░░░░░░░░░]  50%`.

    The share counts work actually finished, never elapsed time, so it cannot promise a
    finish nobody knows.
    """
    share = min(1.0, done / total) if total else 1.0
    filled = round(WIDTH * share)
    return f"[{'█' * filled}{'░' * (WIDTH - filled)}] {round(100 * share):3d}%"


def clock(seconds: float) -> str:
    """`m:ss` for a duration, as the terminal shows elapsed and usual times."""
    whole = max(0, int(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def status(elapsed: float, typical: float) -> str:
    """How a running step stands against its usual duration."""
    if elapsed <= typical:
        return f"{clock(elapsed)}, usually about {clock(typical)}"
    return f"{clock(elapsed)}, still working"


def toward(
    elapsed: float, typical: float, blocks: str = "█░", width: int = WIDTH
) -> str:
    """A bar filled toward `typical`, never full: only the step's end completes it."""
    fraction = MOST_OF_THE_BAR * min(1.0, elapsed / typical) if typical > 0 else 0.0
    filled = min(width - 1, round(width * fraction))
    return blocks[0] * filled + blocks[1] * (width - filled)


def fit(
    head: str,
    elapsed: float,
    typical: float,
    state: str,
    *,
    columns: int,
    blocks: str = "█░",
) -> str:
    """`head  bar  state` in fewer than `columns` characters, so the line never wraps.

    A wrapped line cannot be redrawn in place. The state is what the participant reads, so it
    stays whole: the bar narrows first, then the head is shortened.
    """
    room = columns - 1 - len(state) - 4
    width = max(NARROWEST_BAR, min(WIDTH, room - len(head)))
    if len(head) > room - width:
        head = head[: max(0, room - width - 1)] + "…"
    return f"{head}  {toward(elapsed, typical, blocks, width)}  {state}"[
        : max(1, columns - 1)
    ]


def columns() -> int:
    return shutil.get_terminal_size((80, 24)).columns


def can_redraw(stream: TextIO) -> bool:
    """A terminal that understands carriage returns and line clears."""
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty()) and os.environ.get("TERM", "") != "dumb"


def _blocks(stream: TextIO) -> str:
    encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
    return "█░" if encoding.startswith("utf") else "#-"


class _Guard:
    """Stands in for stdout or stderr while a bar is drawn, so other output lands above it."""

    def __init__(self, live: _Live, wrapped: TextIO) -> None:
        self._live, self._wrapped = live, wrapped

    def write(self, text: str) -> int:
        with self._live.lock:
            if can_redraw(self._wrapped):
                self._live.erase()
            written = self._wrapped.write(text)
            self._wrapped.flush()
            if text:
                self._live.at_line_start = text.endswith("\n")
            return written

    def flush(self) -> None:
        self._wrapped.flush()

    def __getattr__(self, name: str):
        return getattr(self._wrapped, name)


class _Live:
    """One line redrawn in place on a terminal, with stdout and stderr guarded meanwhile."""

    def __init__(
        self,
        stream: TextIO,
        render: Callable[[int], str],
        interval: float | None = REDRAW_SECONDS,
    ) -> None:
        self.stream, self.render, self.interval = stream, render, interval
        self.lock = threading.RLock()
        self.drawn = False
        self.at_line_start = True
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._saved: tuple = ()

    def start(self) -> None:
        """Guard the streams; draw after the grace period, or now when redrawn by hand."""
        self._saved = (sys.stdout, sys.stderr)
        sys.stdout, sys.stderr = _Guard(self, sys.stdout), _Guard(self, sys.stderr)
        if not self.interval:
            self.draw()
            return
        self._thread = threading.Thread(target=self._redraw, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        with self.lock:
            self.erase()
            sys.stdout, sys.stderr = self._saved

    def draw(self) -> None:
        with self.lock:
            if not self.at_line_start:
                return
            self.stream.write(CLEAR_LINE + self.render(columns()))
            self.stream.flush()
            self.drawn = True

    def erase(self) -> None:
        if self.drawn:
            self.stream.write(CLEAR_LINE)
            self.stream.flush()
            self.drawn = False

    def _redraw(self) -> None:
        if self._stop.wait(GRACE_SECONDS):
            return
        self.draw()
        while not self._stop.wait(self.interval):
            self.draw()


class Progress:
    """Numbered steps, each a bar while it runs and one line when it ends.

    Args:
        title: Printed once, before the first step; with a plan it adds the step count and
            the usual time in all.
        stream: Where the bar and the step lines go; defaults to stdout at the first step.
        now: The clock, for tests.
        interval: Seconds between redraws; `None` redraws only on demand, for tests.
        name: Whose steps the counters count, as in "step 2/15", so a command that runs
            another command with its own steps never shows two counters that look alike.
    """

    def __init__(
        self,
        title: str = "",
        *,
        stream: TextIO | None = None,
        now: Callable[[], float] = time.monotonic,
        interval: float | None = REDRAW_SECONDS,
        name: str = "",
    ) -> None:
        self.title, self._stream, self.now, self.interval = title, stream, now, interval
        self.name = name
        self.total: int | None = None
        self.number = 0
        self._planned: list[float] = []
        self._began = 0.0
        self._step: dict | None = None
        self._live: _Live | None = None
        self._finished = False

    @property
    def stream(self) -> TextIO:
        """Fixed at the first step, so a guarded stdout never becomes the bar's own stream."""
        if self._stream is None:
            self._stream = sys.stdout
        return self._stream

    def plan(self, typicals: Sequence[float]) -> None:
        """Set every step's usual duration, in order, so the lines can say how long is left."""
        self._planned = list(typicals)
        self.total = len(self._planned)

    def counter(self) -> str:
        count = f"{self.number}/{self.total}" if self.total else str(self.number)
        return f"{self.name} {count}" if self.name else count

    def begin(
        self,
        label: str,
        *,
        typical: float,
        done: str | None = None,
        animate: bool = True,
        number: int | None = None,
    ) -> None:
        """End the running step, if any, and start the next.

        Args:
            label: What the step is doing, as its bar or start line shows it.
            typical: Its usual duration in seconds, from measured runs.
            done: The line it leaves when it ends; defaults to `label`.
            animate: `False` for a step whose own child process prints to the terminal,
                which a redrawn line would collide with: it prints a start line instead.
            number: The step's place in the plan, when steps can start out of order.
        """
        self.end()
        if self.number == 0:
            self._began = self.now()
            if self.title:
                self._print(self._heading())
        self.number = number if number is not None else self.number + 1
        self._step = {
            "label": label,
            "done": done or label,
            "typical": typical,
            "started": self.now(),
        }
        if animate and can_redraw(self.stream):
            self._live = _Live(self.stream, self._render, self.interval)
            self._live.start()
            return
        self._print(self._start_line(label, typical))

    def end(self, done: str | None = None) -> None:
        """End the running step: its line says what it did, how long it took and what is left."""
        step = self._close()
        if step:
            left = sum(self._planned[self.number :]) if self._planned else 0
            remains = f", about {clock(left)} left" if left else ""
            self._print(
                f"  + {clock(self.now() - step['started'])}  {self.counter()}  "
                f"{done or step['done']}{remains}"
            )

    def fail(self) -> None:
        """End the running step as failed; the caller reports why."""
        step = self._close()
        if step:
            self._print(
                f"  x {clock(self.now() - step['started'])}  {self.counter()}  "
                f"{step['label']}: failed"
            )

    def finish(self) -> None:
        """End the running step and say how long the whole run took. Safe to call twice."""
        self.end()
        if self.number and not self._finished:
            self._finished = True
            self._print(f"  Done in {clock(self.now() - self._began)}.")

    def _start_line(self, label: str, typical: float) -> str:
        """The step's counter, label and usual time; with a plan, the share finished first.

        A label too wide for the terminal, such as a whole command, moves to a line of its
        own, so neither line wraps.
        """
        head = f"  - {self.counter()}"
        if self._planned:
            finished = sum(self._planned[: self.number - 1])
            head = f"{bar(finished, sum(self._planned))}  {self.counter()}"
        usual = f"usually about {clock(typical)}"
        line = f"{head}  {label} ({usual})"
        if len(line) < columns():
            return line
        return f"{head}, {usual}\n    {label}"

    def _heading(self) -> str:
        if not self._planned:
            return self.title
        return (
            f"{self.title}: {len(self._planned)} steps, usually about "
            f"{clock(sum(self._planned))} in all."
        )

    def _close(self) -> dict | None:
        if self._live is not None:
            self._live.stop()
            self._live = None
        step, self._step = self._step, None
        return step

    def _render(self, width: int) -> str:
        step = self._step or {"label": "", "typical": 0.0, "started": self.now()}
        elapsed = self.now() - step["started"]
        return fit(
            f"  [{self.counter()}] {step['label']}",
            elapsed,
            step["typical"],
            status(elapsed, step["typical"]),
            columns=width,
            blocks=_blocks(self.stream),
        )

    def _print(self, line: str) -> None:
        print(line, file=self.stream, flush=True)
