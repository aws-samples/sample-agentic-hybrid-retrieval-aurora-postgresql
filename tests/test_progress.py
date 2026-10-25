"""The progress shown while a participant waits: honest bars on a terminal, plain lines off it.

Nothing the deploy or `finish` waits on reports a percentage, so a bar may claim only what is
known: the steps finished, how long the running step has run and how long each step usually
takes. A fake clock and a fake terminal drive the module; nothing sleeps.
"""

from __future__ import annotations

import io
import sys

import pytest

from scripts import progress as progress_module
from scripts.progress import CLEAR_LINE, Progress, bar, clock, fit, status, toward


class Clock:
    def __init__(self) -> None:
        self.seconds = 1000.0

    def __call__(self) -> float:
        return self.seconds


class Terminal(io.StringIO):
    """A stream that says it is a terminal, as Code Editor's is."""

    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _a_capable_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(progress_module, "columns", lambda: 100)


def _last_frame(text: str) -> str:
    return text.split(CLEAR_LINE)[-1]


def test_a_step_bar_fills_toward_its_usual_time_and_never_completes_early() -> None:
    assert toward(0, 60) == "░" * 20
    assert toward(30, 60).count("█") == 10
    assert toward(60, 60).count("█") == 19
    assert toward(600, 60).count("█") == 19, "an overrun step must not look finished"
    assert toward(5, 0) == "░" * 20


def test_the_share_bar_counts_finished_work_and_caps_at_full() -> None:
    assert bar(0, 5) == "[░░░░░░░░░░░░░░░░░░░░]   0%"
    assert bar(2, 5) == "[████████░░░░░░░░░░░░]  40%"
    assert bar(7, 5) == "[████████████████████] 100%"


def test_an_overrun_says_it_is_still_working() -> None:
    assert clock(71) == "1:11"
    assert status(41, 60) == "0:41, usually about 1:00"
    assert status(84, 60) == "1:24, still working"


def test_off_a_terminal_a_planned_run_prints_its_total_each_start_and_what_is_left() -> (
    None
):
    now, out = Clock(), io.StringIO()
    progress = Progress(
        "Deploying your Retrieval agent", stream=out, now=now, interval=None
    )
    progress.plan([10, 30])
    progress.begin("Build the image", typical=10, done="Built the image")
    now.seconds += 4
    progress.begin("Update the runtime", typical=30, done="Updated the runtime")
    now.seconds += 33
    progress.finish()

    assert out.getvalue().splitlines() == [
        "Deploying your Retrieval agent: 2 steps, usually about 0:40 in all.",
        f"{bar(0, 40)}  1/2  Build the image (usually about 0:10)",
        "  + 0:04  1/2  Built the image, about 0:30 left",
        f"{bar(10, 40)}  2/2  Update the runtime (usually about 0:30)",
        "  + 0:33  2/2  Updated the runtime",
        "  Done in 0:37.",
    ]
    assert CLEAR_LINE not in out.getvalue()


def test_a_named_run_says_whose_steps_it_counts_and_marks_a_failure() -> None:
    now, out = Clock(), io.StringIO()
    progress = Progress(stream=out, now=now, interval=None, name="step")
    progress.begin(
        "uv run python scripts/apply_search_functions.py", typical=1, animate=False
    )
    now.seconds += 3
    progress.fail()

    assert out.getvalue().splitlines() == [
        "  - step 1  uv run python scripts/apply_search_functions.py (usually about 0:01)",
        "  x 0:03  step 1  uv run python scripts/apply_search_functions.py: failed",
    ]


def test_a_step_can_start_at_its_place_in_the_plan() -> None:
    now, out = Clock(), io.StringIO()
    progress = Progress(stream=out, now=now, interval=None)
    progress.plan([5, 16, 16])
    progress.begin("Update the tools runtime", typical=16, number=2)
    progress.end()

    assert out.getvalue().splitlines()[-1] == (
        "  + 0:00  2/3  Update the tools runtime, about 0:16 left"
    )


def test_on_a_terminal_the_running_step_is_a_bar_that_its_end_line_replaces() -> None:
    now, out = Clock(), Terminal()
    progress = Progress(stream=out, now=now, interval=None)
    progress.plan([30, 20])
    progress.begin("Update the runtime", typical=30, done="Updated the runtime")
    now.seconds += 15
    progress._live.draw()
    assert _last_frame(out.getvalue()) == (
        "  [1/2] Update the runtime  "
        + "█" * 10
        + "░" * 10
        + "  0:15, usually about 0:30"
    )

    now.seconds += 14
    progress.end()
    assert out.getvalue().endswith(
        CLEAR_LINE + "  + 0:29  1/2  Updated the runtime, about 0:20 left\n"
    )


def test_output_printed_while_the_bar_runs_lands_above_it_and_stdout_comes_back(
    capsys: pytest.CaptureFixture[str],
) -> None:
    now, out = Clock(), Terminal()
    progress = Progress(stream=out, now=now, interval=None)
    before = sys.stdout
    progress.begin("Synchronize the Gateway tools", typical=21)
    print("Synchronizing Gateway tools from the tools runtime.")
    progress.end()

    assert sys.stdout is before, "the guard must hand stdout back when the step ends"
    assert "Synchronizing Gateway tools" in capsys.readouterr().out
    assert out.getvalue().count(CLEAR_LINE) >= 2


def test_a_failed_step_on_a_terminal_restores_both_streams() -> None:
    now, out = Clock(), Terminal()
    before = (sys.stdout, sys.stderr)
    progress = Progress(stream=out, now=now, interval=None)
    progress.begin("Verify the deployment", typical=13)
    now.seconds += 20
    progress.fail()

    assert (sys.stdout, sys.stderr) == before
    assert out.getvalue().endswith("  x 0:20  1  Verify the deployment: failed\n")


@pytest.mark.parametrize("width", [40, 60, 68, 100])
def test_a_running_line_never_wraps_and_keeps_its_time_whole(width: int) -> None:
    state = status(9, 16)
    line = fit(
        "  [3/5] Update the Retrieval agent runtime", 9, 16, state, columns=width
    )
    assert len(line) < width
    assert line.endswith(state)
