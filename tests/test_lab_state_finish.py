"""One command finishes a lab: the steps of the guide's Running behind? paste, in order."""

import subprocess
import sys

import pytest

from scripts import lab_state
from scripts.progress import bar, clock
from service.participant_commands import (
    ADVANCE_TO_LAB_2,
    ADVANCE_TO_LAB_3,
    APPLY_SQL,
    DEPLOY_AGENT,
    LIST_TOOLS,
    USUAL_SECONDS,
    exercise_check,
    finish,
    finish_steps,
    repeat_request,
    skip_to,
    solution,
    start,
)


def test_each_lab_finishes_through_its_guide_steps():
    assert finish_steps(1) == (
        start(1),
        solution(1),
        APPLY_SQL,
        repeat_request(1),
        ADVANCE_TO_LAB_2,
    )
    assert finish_steps(2) == (
        start(2),
        solution(2),
        APPLY_SQL,
        repeat_request(2),
        exercise_check(2),
        ADVANCE_TO_LAB_3,
    )
    # Lab 3 stops at deployment: completion needs a setup run the participant asks.
    assert finish_steps(3) == (start(3), solution(3), LIST_TOOLS, DEPLOY_AGENT)


def run_finish(
    monkeypatch, capsys, lab, failing_step=None, entered=(1, 2, 3), action="finish"
):
    ran = []
    monkeypatch.setattr(lab_state, "_entered", lambda number: number in entered)

    def fake_run(command, cwd, check):
        ran.append(command)
        failed = failing_step is not None and len(ran) == failing_step
        return subprocess.CompletedProcess(command, 3 if failed else 0)

    monkeypatch.setattr(lab_state.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["lab_state.py", action, "--lab", str(lab)])
    code = lab_state.main()
    return code, ran, capsys.readouterr().out


@pytest.mark.parametrize("lab", [1, 2, 3])
def test_finish_runs_every_step_in_order_and_names_each(monkeypatch, capsys, lab):
    code, ran, out = run_finish(monkeypatch, capsys, lab)

    assert code == 0
    steps = finish_steps(lab)
    assert [command[1:] for command in ran] == [
        step.removeprefix("uv run python ").split() for step in steps
    ]
    assert all(command[0] == sys.executable for command in ran)
    total = len(steps)
    usual = sum(USUAL_SECONDS[step] for step in steps)
    assert (
        f"Finish Lab {lab}: {total} steps, usually about {clock(usual)} in all." in out
    )
    for index, step in enumerate(steps):
        number = f"step {index + 1}/{total}"
        assert f"{number}  {step} (usually about {clock(USUAL_SECONDS[step])})" in out
        assert f"{number}  done" in out
    assert "  Done in " in out


def test_every_step_finish_or_skip_to_runs_has_a_measured_usual_time():
    steps = {step for lab in (1, 2, 3) for step in finish_steps(lab)}
    steps |= {start(lab) for lab in (1, 2, 3)}
    assert steps <= set(USUAL_SECONDS), sorted(steps - set(USUAL_SECONDS))


def test_finish_stops_at_the_first_failure_and_says_how_to_resume(monkeypatch, capsys):
    code, ran, out = run_finish(monkeypatch, capsys, 2, failing_step=3)

    assert code == 3
    assert len(ran) == 3
    assert f"stopped at: {APPLY_SQL}" in out
    assert finish(2) in out


@pytest.mark.parametrize(
    "lab,entered,labs_run",
    [
        (2, (1,), (1, 2)),
        (3, (1,), (1, 2, 3)),
        (3, (1, 2), (2, 3)),
        (3, (1, 2, 3), (3,)),
    ],
)
def test_finish_skips_ahead_through_every_lab_not_handed_off(
    monkeypatch, capsys, lab, entered, labs_run
):
    code, ran, out = run_finish(monkeypatch, capsys, lab, entered=entered)

    assert code == 0
    expected = [step for number in labs_run for step in finish_steps(number)]
    assert [command[1:] for command in ran] == [
        step.removeprefix("uv run python ").split() for step in expected
    ]
    for number in labs_run[:-1]:
        assert f"Lab {number} has not handed off yet" in out


def as_commands(steps):
    return [step.removeprefix("uv run python ").split() for step in steps]


@pytest.mark.parametrize(
    "lab,entered,earlier",
    [
        (3, (1,), (1, 2)),
        (3, (1, 2), (2,)),
        (2, (1,), (1,)),
    ],
)
def test_skip_to_finishes_earlier_labs_and_stops_at_the_chosen_lab_start(
    monkeypatch, capsys, lab, entered, earlier
):
    code, ran, out = run_finish(
        monkeypatch, capsys, lab, entered=entered, action="skip-to"
    )

    assert code == 0
    expected = [step for number in earlier for step in finish_steps(number)]
    assert [command[1:] for command in ran] == as_commands(expected)
    # The chosen lab itself is only started, by the last hand-off: never solved.
    assert solution(lab) not in out
    assert f"Lab {lab}: ready." in out


@pytest.mark.parametrize("lab,entered", [(1, ()), (1, (1,)), (3, (1, 2, 3))])
def test_skip_to_a_lab_already_reachable_only_starts_it(
    monkeypatch, capsys, lab, entered
):
    code, ran, _out = run_finish(
        monkeypatch, capsys, lab, entered=entered, action="skip-to"
    )

    assert code == 0
    assert [command[1:] for command in ran] == as_commands([start(lab)])


def test_skip_to_stops_at_a_failure_and_names_its_own_command(monkeypatch, capsys):
    code, ran, out = run_finish(
        monkeypatch, capsys, 3, failing_step=2, entered=(1,), action="skip-to"
    )

    assert code == 3
    assert len(ran) == 2
    assert f"stopped at: {solution(1)}" in out
    assert skip_to(3) in out


def test_the_bar_counts_finished_steps():
    assert bar(0, 5) == "[░░░░░░░░░░░░░░░░░░░░]   0%"
    assert bar(2, 5) == "[████████░░░░░░░░░░░░]  40%"
    assert bar(5, 5) == "[████████████████████] 100%"
