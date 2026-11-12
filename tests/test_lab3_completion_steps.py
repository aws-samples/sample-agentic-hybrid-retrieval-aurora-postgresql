"""Each Lab 3 next step names only the runs completion still needs, in order.

Completion checks the newest setup run and the newest answered 100W question since Lab 3
started, both made by the code deployed now. A deploy of changed code makes both needed
again. A run already saved from that code is never asked for again: each costs about a
minute of a 20-minute lab.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import lab_exercise, lab_state, prove_lab
from service import lab_followup
from service.participant_commands import (
    DEPLOY_AGENT,
    ask_100w_command,
    ask_setup_command,
    grade_setup_run_command,
    lab3_steps,
)

SETUP, FOLLOW_UP, CHECK = (
    ask_setup_command(),
    ask_100w_command(),
    grade_setup_run_command(),
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def assert_in_order(text: str, *commands: str) -> None:
    """Each command appears whole, after the one before it; wrapping is ignored."""
    flat = _flat(text)
    position = -1
    for command in commands:
        found = flat.find(_flat(command), position + 1)
        assert found > position, f"{command!r} missing or out of order in {text!r}"
        position = found


def assert_absent(text: str, *commands: str) -> None:
    for command in commands:
        assert _flat(command) not in _flat(text), (
            f"{command!r} should not be in {text!r}"
        )


@pytest.mark.parametrize(
    ("needs", "commands"),
    [
        ({"deploy": True}, (DEPLOY_AGENT, SETUP, FOLLOW_UP, CHECK)),
        ({}, (SETUP, FOLLOW_UP, CHECK)),
        ({"follow_up": False}, (SETUP, CHECK)),
        ({"setup": False}, (FOLLOW_UP, CHECK)),
        ({"setup": False, "follow_up": False}, (CHECK,)),
    ],
)
def test_the_steps_name_only_what_completion_still_needs(needs, commands) -> None:
    prose, named = lab3_steps(**needs)

    assert named == commands
    assert prose.endswith(":")


def test_a_deploy_needs_both_runs_again_whatever_was_saved() -> None:
    assert lab3_steps(deploy=True, setup=False, follow_up=False)[1] == (
        DEPLOY_AGENT,
        SETUP,
        FOLLOW_UP,
        CHECK,
    )


def test_finish_lab_3_names_both_runs_then_the_check(monkeypatch, capsys) -> None:
    monkeypatch.setattr(lab_state, "_run_steps", lambda *_a, **_k: 0)
    monkeypatch.setattr(lab_state, "_earlier_labs_to_finish", lambda _lab: [])

    assert lab_state.finish_lab(3) == 0

    out = capsys.readouterr().out
    assert_in_order(out, SETUP, FOLLOW_UP, CHECK)


def test_status_of_a_deployed_unproved_lab_3_names_only_the_check(capsys) -> None:
    """The check reads the saved runs and names any still missing, so status need not."""
    lab_state._status_next(
        ["Lab 1: SOLVED", "Lab 2: SOLVED", "Lab 3: DEPLOYED, NOT YET PROVED"]
    )

    out = capsys.readouterr().out
    assert_in_order(out, CHECK)
    assert_absent(out, SETUP, FOLLOW_UP, DEPLOY_AGENT)


def test_applying_lab_3s_answer_names_the_deploy_then_both_runs() -> None:
    summary = lab_state.solution_summary(3, Path("labs/lab3_reason/agent.py"))

    assert_in_order(summary, DEPLOY_AGENT, SETUP, FOLLOW_UP, CHECK)


def test_lab_3s_diff_footer_names_the_deploy_then_both_runs() -> None:
    footer = "\n".join(
        lab_state._diff_footer(
            3, block_differs=True, outside_differs=False, answer=True
        )
    )

    assert_in_order(footer, DEPLOY_AGENT, SETUP, FOLLOW_UP, CHECK)
    # The guide asks for no instruction of the participant's own; one they add is allowed.
    assert "asks for your own instruction" not in footer


@pytest.mark.parametrize(
    ("started", "due", "named", "absent"),
    [
        (True, True, (DEPLOY_AGENT, SETUP, FOLLOW_UP, CHECK), ()),
        (False, False, (DEPLOY_AGENT, SETUP, FOLLOW_UP, CHECK), ()),
        (True, False, (CHECK,), (DEPLOY_AGENT, SETUP, FOLLOW_UP)),
    ],
)
def test_validating_lab_3_names_a_deploy_unless_this_code_is_deployed(
    monkeypatch, capsys, started, due, named, absent
) -> None:
    monkeypatch.setattr(lab_state, "missing_file_problem", lambda *_a: None)
    monkeypatch.setattr(lab_state, "lab_source_is_repaired", lambda *_a, **_k: True)
    monkeypatch.setattr(
        "service.agent_deploys.lab_3_started_at",
        lambda *_a: object() if started else None,
    )
    monkeypatch.setattr("service.agent_deploys.deploy_due", lambda *_a, **_k: due)

    assert lab_state._validate_command(3, None) == 0

    out = capsys.readouterr().out
    assert_in_order(out, *named)
    assert_absent(out, *absent)


@pytest.mark.parametrize(
    ("needs", "named", "absent"),
    [
        (
            {"deploy": False, "setup": True, "follow_up": False},
            (SETUP, CHECK),
            (DEPLOY_AGENT, FOLLOW_UP),
        ),
        (
            {"deploy": False, "setup": False, "follow_up": True},
            (FOLLOW_UP, CHECK),
            (DEPLOY_AGENT, SETUP),
        ),
        (
            {"deploy": True, "setup": True, "follow_up": True},
            (DEPLOY_AGENT, SETUP, FOLLOW_UP, CHECK),
            (),
        ),
    ],
)
def test_a_failed_grade_names_only_the_runs_it_needs(
    capsys, needs, named, absent
) -> None:
    lab_exercise._grade_next(3, False, needs)

    out = capsys.readouterr().out
    assert_in_order(out, *named)
    assert_absent(out, *absent)


def test_grading_lab_3_before_any_run_sends_to_the_check(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(lab_exercise, "REPO", tmp_path)

    with pytest.raises(lab_exercise.ExerciseError) as error:
        lab_exercise.load_context(3)

    assert_in_order(str(error.value), CHECK)
    assert_absent(str(error.value), SETUP, FOLLOW_UP)


def test_prove_lab_3_without_a_receipt_sends_to_the_check(monkeypatch) -> None:
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_a, **_k: None)
    monkeypatch.setattr(sys, "argv", ["prove_lab.py", "--lab", "3"])

    with pytest.raises(SystemExit) as stopped:
        prove_lab.main()

    assert_in_order(str(stopped.value.code), CHECK)
    assert_absent(str(stopped.value.code), SETUP, FOLLOW_UP)


# ------------------------------------------- whether the 100W answer already counts


def _follow_up(monkeypatch, *, due: bool, run_code: str | None) -> None:
    monkeypatch.setattr("service.agent_deploys.deploy_due", lambda *_a, **_k: due)
    monkeypatch.setattr(
        "service.agent_deploys.lab_3_started_at", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "service.lab_validation_receipt.application_digest", lambda *_a: "deployed"
    )
    rows = (
        None
        if run_code is None
        else SimpleNamespace(
            turn={"extracted_intent": {"application_sha256": run_code}}
        )
    )
    monkeypatch.setattr(lab_followup, "load_changed_requirement", lambda *_a: rows)


@pytest.mark.parametrize(
    ("due", "run_code", "saved"),
    [
        (False, "deployed", True),
        (False, "earlier", False),
        (False, None, False),
        (True, "deployed", False),
    ],
)
def test_a_100w_answer_counts_only_from_the_code_deployed_now(
    monkeypatch, due, run_code, saved
) -> None:
    _follow_up(monkeypatch, due=due, run_code=run_code)

    assert lab_followup.follow_up_saved(object()) is saved
