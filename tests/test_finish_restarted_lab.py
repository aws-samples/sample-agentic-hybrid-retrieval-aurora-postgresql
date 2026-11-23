"""`finish` and `skip-to` finish an earlier lab again only when its receipt no longer holds.

A later lab's start record shows that a hand-off happened once. A restart or a different
repair afterwards leaves that record behind, so the receipt for the lab's current attempt
and saved SQL decides. The files, start records and receipts run as shipped on a copy of
the checkout; only the commands `finish` and `skip-to` would spawn are recorded.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from shutil import copy2

import pytest

from scripts import lab_state
from scripts.lab_entry import record_path
from scripts.lab_state import LABS, REPO, _replace_block
from scripts.prove_lab import record_completion
from service.lab_files import solution_path
from service.participant_commands import (
    ADVANCE_TO_LAB_2,
    APPLY_SQL,
    apply_solution_command,
    finish_command,
    finish_steps,
    skip_to_command,
    start_command,
)

STARTED = "2026-11-19T10:00:00+00:00"
RESTARTED = "2026-11-20T03:00:00+00:00"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for relative_path in {definition[0] for definition in LABS.values()}:
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy2(REPO / relative_path, destination)
    monkeypatch.setattr(lab_state, "REPO", tmp_path)
    return tmp_path


def _start(repo: Path, lab: int, at: str = STARTED) -> None:
    path = record_path(lab, repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "lab": lab, "steps": {}, "completed_at": at})
    )


def _handed_off(repo: Path, lab: int) -> None:
    """The lab passed: its receipt is saved and the lab after it has started."""
    _start(repo, lab)
    record_completion(lab, ["target found"], [f"event-{lab}"], repo)
    _start(repo, lab + 1)


def _restart(repo: Path, lab: int, *, keep_receipt: bool = False) -> None:
    """What `reset --lab N` leaves: a new start record and the next lab's record.

    A reset also deletes the receipt; keeping it covers a restart by `start` alone.
    """
    _start(repo, lab, RESTARTED)
    if not keep_receipt:
        (repo / f".local/lab-{lab}/completion.json").unlink(missing_ok=True)


def _break_lab_2(repo: Path) -> None:
    """Lab 2 as the exercise ships it: started, with its ranking fault in the saved block."""
    path = repo / LABS[2][0]
    start, end, _fixed, broken = LABS[2][1][0]
    path.write_text(_replace_block(path.read_text(), start, end, broken))
    assert lab_state.source_problem(2, repo=repo) is not None


def _run(monkeypatch, capsys, action: str, lab: int):
    ran: list[list[str]] = []
    real_run = subprocess.run

    def fake_run(command, *args, **kwargs):
        if command[0] != sys.executable or not command[1].startswith("scripts/"):
            return real_run(command, *args, **kwargs)
        ran.append(command[1:])
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(lab_state.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["lab_state.py", action, "--lab", str(lab)])
    code = lab_state.main()
    return code, ran, capsys.readouterr().out


def _commands(steps) -> list[list[str]]:
    return [step.removeprefix("uv run python ").split() for step in steps]


def _in_order(steps, ran) -> bool:
    """Whether every step ran, in this order, with other steps allowed between them."""
    remaining = iter(ran)
    return all(command in remaining for command in _commands(steps))


@pytest.mark.parametrize("action", ["skip-to", "finish"])
def test_a_restarted_lab_1_is_finished_again_before_lab_2(
    repo, monkeypatch, capsys, action
):
    _handed_off(repo, 1)
    _restart(repo, 1)

    _code, ran, out = _run(monkeypatch, capsys, action, 2)

    assert _in_order(finish_steps(1), ran)
    assert "Lab 1 is not complete any more (no completion was saved)" in out


def test_a_receipt_from_an_earlier_attempt_does_not_keep_lab_1_finished(
    repo, monkeypatch, capsys
):
    _handed_off(repo, 1)
    _restart(repo, 1, keep_receipt=True)

    _code, ran, out = _run(monkeypatch, capsys, "skip-to", 2)

    assert _in_order(finish_steps(1), ran)
    assert "Lab 1 was restarted since it passed" in out


@pytest.mark.parametrize("action", ["skip-to", "finish"])
def test_a_restarted_lab_2_is_finished_again_before_lab_3(
    repo, monkeypatch, capsys, action
):
    _handed_off(repo, 1)
    _handed_off(repo, 2)
    _restart(repo, 2)

    _code, ran, out = _run(monkeypatch, capsys, action, 3)

    assert ran[: len(finish_steps(2))] == _commands(finish_steps(2))
    assert _commands([apply_solution_command(1)])[0] not in ran
    assert "Lab 2 is not complete any more" in out


@pytest.mark.parametrize("action", ["skip-to", "finish"])
def test_a_valid_lab_1_handoff_is_not_finished_again(repo, monkeypatch, capsys, action):
    _handed_off(repo, 1)
    before = (repo / LABS[1][0]).read_bytes()

    _code, ran, out = _run(monkeypatch, capsys, action, 2)

    assert _commands([apply_solution_command(1)])[0] not in ran
    assert _commands([start_command(1)])[0] not in ran
    assert (repo / LABS[1][0]).read_bytes() == before
    assert "Lab 1 has not" not in out and "Lab 1 is not" not in out


@pytest.mark.parametrize("action", ["skip-to", "finish"])
def test_a_valid_lab_2_handoff_is_not_finished_again(repo, monkeypatch, capsys, action):
    _handed_off(repo, 1)
    _handed_off(repo, 2)

    _code, ran, _out = _run(monkeypatch, capsys, action, 3)

    for lab in (1, 2):
        assert _commands([apply_solution_command(lab)])[0] not in ran
    assert _commands([start_command(3)])[0] in ran or action == "finish"
    assert "Lab 2 is not" not in _out


def test_a_lab_1_repair_changed_after_its_receipt_is_finished_again(
    repo, monkeypatch, capsys
):
    _handed_off(repo, 1)
    path = repo / LABS[1][0]
    path.write_text(
        path.read_text().replace(
            "SELECT product_id, 'fuzzy', fuzzy_rank,",
            "SELECT product_id, 'fuzzy'::text AS channel, fuzzy_rank AS source_rank,",
        )
    )

    _code, ran, out = _run(monkeypatch, capsys, "skip-to", 2)

    assert ran[0] == _commands([start_command(1)])[0]
    assert "saved SQL changed since it passed" in out


def test_finish_installs_lab_2s_answer_before_lab_1s_proof_when_lab_2_has_started(
    repo, monkeypatch, capsys
):
    """Lab 1's hand-off refuses while a started Lab 2 collapses ranks, so Lab 2 goes first."""
    _handed_off(repo, 1)
    _break_lab_2(repo)
    _restart(repo, 1)

    code, ran, _out = _run(monkeypatch, capsys, "finish", 2)

    assert code == 0
    first_apply = ran.index(_commands([APPLY_SQL])[0])
    assert ran.index(_commands([apply_solution_command(2)])[0]) < first_apply
    assert first_apply < ran.index(_commands([ADVANCE_TO_LAB_2])[0])
    assert ran.count(_commands([apply_solution_command(2)])[0]) == 1


def test_skip_to_lab_2_stops_rather_than_replace_an_unrepaired_lab_2(
    repo, monkeypatch, capsys
):
    _handed_off(repo, 1)
    _break_lab_2(repo)
    _restart(repo, 1)
    faulty = (repo / LABS[2][0]).read_bytes()
    monkeypatch.setattr(
        lab_state.subprocess, "run", lambda *a, **k: pytest.fail("ran a step")
    )
    monkeypatch.setattr(sys, "argv", ["lab_state.py", "skip-to", "--lab", "2"])

    with pytest.raises(SystemExit) as stopped:
        lab_state.main()

    message = str(stopped.value)
    assert "Skip rule" in message and "Lab 2 is started and not repaired" in message
    assert finish_command(2) in message and skip_to_command(2) in message
    assert message.count("Next:") == 1
    assert (repo / LABS[2][0]).read_bytes() == faulty


def test_skip_to_lab_3_finishes_both_labs_with_lab_2s_answer_first(
    repo, monkeypatch, capsys
):
    _handed_off(repo, 1)
    _break_lab_2(repo)
    _restart(repo, 1)
    _start(repo, 3)

    code, ran, _out = _run(monkeypatch, capsys, "skip-to", 3)

    assert code == 0
    first_apply = ran.index(_commands([APPLY_SQL])[0])
    assert ran.index(_commands([apply_solution_command(2)])[0]) < first_apply


def test_refinishing_lab_1_behind_a_complete_lab_2_points_past_lab_2(
    repo, monkeypatch, capsys
):
    """The event's stale Next: sent a participant back into Lab 2's psql after Lab 2 passed."""
    monkeypatch.setattr(
        lab_state,
        "applied_sql_state_for_status",
        lambda lab, repo: lab_state.LabDatabaseState(state="applied", detail="runs"),
    )
    _handed_off(repo, 1)
    _handed_off(repo, 2)
    _restart(repo, 1)

    code, ran, out = _run(monkeypatch, capsys, "finish", 1)

    assert code == 0 and _in_order(finish_steps(1), ran)
    assert "Lab 1: finished with the reference answer." in out
    assert "lab-2/context.psql" not in out


@pytest.mark.parametrize(
    ("action", "resume"), [("finish", finish_command), ("skip-to", skip_to_command)]
)
def test_an_edit_outside_the_block_stops_finishing_before_any_step_and_names_the_reset(
    repo, monkeypatch, action, resume
):
    _start(repo, 1)
    solution = solution_path(Path(LABS[1][0]))
    (repo / solution).parent.mkdir(parents=True, exist_ok=True)
    copy2(REPO / solution, repo / solution)
    path = repo / LABS[1][0]
    source = path.read_text()
    edited = source.replace(
        "fuzzy_limit integer DEFAULT 80", "fuzzy_limit integer DEFAULT 8", 1
    )
    assert edited != source
    path.write_text(edited)
    monkeypatch.setattr(
        lab_state.subprocess, "run", lambda *a, **k: pytest.fail("ran a step")
    )
    lab = 1 if action == "finish" else 2
    monkeypatch.setattr(sys, "argv", ["lab_state.py", action, "--lab", str(lab)])

    with pytest.raises(SystemExit) as stopped:
        lab_state.main()

    message = str(stopped.value)
    assert "changed outside the marked block" in message
    assert "reset --lab 1" in message and resume(lab) in message
    assert message.index("reset --lab 1") < message.index(resume(lab))
    assert message.count("Next:") == 1
    assert path.read_text() == edited


def test_finish_runs_through_a_glued_marker_because_the_answer_repairs_it(
    repo, monkeypatch, capsys
):
    _start(repo, 1)
    solution = solution_path(Path(LABS[1][0]))
    (repo / solution).parent.mkdir(parents=True, exist_ok=True)
    copy2(REPO / solution, repo / solution)
    path = repo / LABS[1][0]
    source = path.read_text()
    end = LABS[1][1][0][1]
    assert source.count(f"\n{end}") == 1
    path.write_text(source.replace(f"\n{end}", f" {end}", 1))

    code, ran, _out = _run(monkeypatch, capsys, "finish", 1)

    assert code == 0
    assert _in_order(lab_state.finish_steps(1), ran)
