"""Every Lab 3 recovery names both runs completion checks, then the check, in that order.

Completion grades the newest setup run and the newest 100W answer since Lab 3 started,
and both must come from the same deployed code. A message that names only the setup
request sends a participant who follows it into a failed check.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts import lab_exercise, lab_state, prove_lab
from service.participant_commands import (
    DEPLOY_AGENT,
    ask_100w_command,
    ask_setup_command,
    grade_setup_run_command,
)


def assert_in_order(text: str, *commands: str) -> None:
    """Each command appears whole, after the one before it; wrapping is ignored."""
    flat = " ".join(text.split())
    position = -1
    for command in commands:
        found = flat.find(" ".join(command.split()), position + 1)
        assert found > position, f"{command!r} missing or out of order in {text!r}"
        position = found


def assert_names_both_runs(text: str) -> None:
    assert_in_order(
        text, ask_setup_command(), ask_100w_command(), grade_setup_run_command()
    )


def test_finish_lab_3_names_both_runs_then_the_check(monkeypatch, capsys) -> None:
    monkeypatch.setattr(lab_state, "_run_steps", lambda *_a, **_k: 0)
    monkeypatch.setattr(lab_state, "_earlier_labs_to_finish", lambda _lab: [])

    assert lab_state.finish_lab(3) == 0

    assert_names_both_runs(capsys.readouterr().out)


def test_status_of_a_deployed_unproved_lab_3_names_both_runs(capsys) -> None:
    lab_state._status_next(
        [
            "Lab 1: SOLVED",
            "Lab 2: SOLVED",
            "Lab 3: DEPLOYED, NOT YET PROVED. Next: ask Alex's setup request",
        ]
    )

    assert_names_both_runs(capsys.readouterr().out)


def test_applying_lab_3s_answer_names_the_deploy_then_both_runs() -> None:
    summary = lab_state.solution_summary(3, Path("labs/lab3_reason/agent.py"))

    assert_in_order(
        summary,
        DEPLOY_AGENT,
        ask_setup_command(),
        ask_100w_command(),
        grade_setup_run_command(),
    )


def test_lab_3s_diff_footer_names_the_deploy_then_both_runs() -> None:
    footer = "\n".join(
        lab_state._diff_footer(
            3, block_differs=True, outside_differs=False, answer=True
        )
    )

    assert_in_order(
        footer,
        DEPLOY_AGENT,
        ask_setup_command(),
        ask_100w_command(),
        grade_setup_run_command(),
    )
    # The guide asks for no instruction of the participant's own; one they add is allowed.
    assert "asks for your own instruction" not in footer


def test_validating_lab_3_names_the_deploy_then_both_runs(monkeypatch, capsys) -> None:
    monkeypatch.setattr(lab_state, "missing_file_problem", lambda *_a: None)
    monkeypatch.setattr(lab_state, "lab_source_is_repaired", lambda *_a, **_k: True)

    assert lab_state._validate_command(3, None) == 0

    assert_in_order(
        capsys.readouterr().out,
        DEPLOY_AGENT,
        ask_setup_command(),
        ask_100w_command(),
        grade_setup_run_command(),
    )


def test_a_failed_setup_run_retries_both_runs_after_any_deploy(capsys) -> None:
    lab_exercise._grade_next(3, False, retry="setup")

    assert_in_order(
        capsys.readouterr().out,
        DEPLOY_AGENT,
        ask_setup_command(),
        ask_100w_command(),
        grade_setup_run_command(),
    )


def test_grading_lab_3_before_any_run_names_both_runs(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(lab_exercise, "REPO", tmp_path)

    with pytest.raises(lab_exercise.ExerciseError) as error:
        lab_exercise.load_context(3)

    assert_names_both_runs(str(error.value))


def test_prove_lab_3_without_a_receipt_names_both_runs(monkeypatch) -> None:
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_a, **_k: None)
    monkeypatch.setattr(sys, "argv", ["prove_lab.py", "--lab", "3"])

    with pytest.raises(SystemExit) as stopped:
        prove_lab.main()

    assert_names_both_runs(str(stopped.value.code))
