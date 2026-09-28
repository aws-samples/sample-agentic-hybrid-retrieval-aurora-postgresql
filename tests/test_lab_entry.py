"""Entering a lab: once, resumable, and never at the cost of the participant's edits.

Aurora and the API are the boundaries here: the applied-state read, the apply
and the saved request are substituted; the seam files, the start record and
the prerequisite logic run as shipped, on a copy of the checkout.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from shutil import copy2

import pytest

from scripts import lab_entry
from scripts.lab_state import (
    LABS,
    REPO,
    LabDatabaseState,
    _replace_block,
    lab_is_solved,
    set_lab_state,
)

PARTICIPANT_LAB_2 = "SELECT 1.0 / (rrf_k + source_rank)"


class Boundaries:
    """What the start asked of Aurora and the API, and what they answer."""

    def __init__(self) -> None:
        self.applied: dict[int, str] = {1: "applied", 2: "stale"}
        self.applies = 0
        self.captures = 0
        self.fail_apply = False
        self.fail_capture = False


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for relative_path in {definition[0] for definition in LABS.values()}:
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy2(REPO / relative_path, destination)
    return tmp_path


@pytest.fixture
def aurora(monkeypatch) -> Boundaries:
    state = Boundaries()

    @contextmanager
    def connect(_dsn):
        yield object()

    def validate_database(lab, _connection):
        return LabDatabaseState(
            state=state.applied.get(lab, "not_applicable"), detail=""
        )

    def apply(_dsn, _repo, say):
        if state.fail_apply:
            raise RuntimeError("Aurora connection dropped")
        state.applies += 1
        say("Applied it to Aurora.")
        return "sha"

    def prepare(lab, phase, _api_url, output):
        if state.fail_capture:
            raise RuntimeError("API restarting")
        state.captures += 1
        output.mkdir(parents=True, exist_ok=True)
        (output / f"{phase}-state.json").write_text(
            json.dumps({"run_id": f"run-{lab}"})
        )
        return output / "context.psql"

    monkeypatch.setattr(lab_entry, "assert_reset_database", lambda _dsn: None)
    monkeypatch.setattr(lab_entry, "_connect", connect)
    monkeypatch.setattr(lab_entry, "validate_database", validate_database)
    monkeypatch.setattr(lab_entry, "_apply", apply)
    monkeypatch.setattr("scripts.lab_terminal.prepare", prepare)
    return state


def _start(lab: int, repo: Path, said: list[str] | None = None) -> dict:
    lines = [] if said is None else said
    return lab_entry.start(
        lab, api_url="http://api", dsn="aurora", repo=repo, say=lines.append
    )


def _seam_file(lab: int, repo: Path) -> Path:
    return repo / LABS[lab][0]


def _participant_edit(repo: Path) -> bytes:
    path = _seam_file(2, repo)
    start, end, _, _ = LABS[2][1][0]
    path.write_text(_replace_block(path.read_text(), start, end, PARTICIPANT_LAB_2))
    return path.read_bytes()


def _interrupt_before_the_file_changed(repo: Path) -> None:
    source = _seam_file(2, repo).read_text()
    lab_entry._save(
        2,
        repo,
        {
            "version": 1,
            "lab": 2,
            "steps": {
                "fault": {
                    "state": "installing",
                    "before": lab_entry._seam_sha256(2, source),
                }
            },
        },
    )


def test_lab_2_start_installs_only_its_fault_applies_and_saves_the_failing_run(
    repo, aurora
) -> None:
    lab_1_before = [
        start + source.split(start, 1)[1].split(end, 1)[0]
        for start, end, _, _ in LABS[1][1]
        for source in [_seam_file(1, repo).read_text()]
    ]

    record = _start(2, repo)

    assert not lab_is_solved(2, repo=repo)
    assert lab_is_solved(1, repo=repo)
    assert lab_is_solved(3, repo=repo)
    after = _seam_file(1, repo).read_text()
    assert all(block in after for block in lab_1_before)
    assert (aurora.applies, aurora.captures) == (1, 1)
    assert record["completed_at"]
    assert record["steps"]["evidence"]["search_event_id"] == "run-2"


def test_a_completed_start_is_a_no_op_that_keeps_the_participants_edits(
    repo, aurora
) -> None:
    _start(2, repo)
    edited = _participant_edit(repo)
    said: list[str] = []

    _start(2, repo, said)

    assert _seam_file(2, repo).read_bytes() == edited
    assert (aurora.applies, aurora.captures) == (1, 1)
    assert "your edits are unchanged" in said[-1]


def test_an_interruption_before_the_file_changed_installs_the_fault_on_retry(
    repo, aurora
) -> None:
    _interrupt_before_the_file_changed(repo)

    record = _start(2, repo)

    assert not lab_is_solved(2, repo=repo)
    assert record["steps"]["fault"]["state"] == "done"
    assert record["completed_at"]


def test_an_interruption_after_the_file_changed_does_not_rewrite_it(
    repo, aurora
) -> None:
    _interrupt_before_the_file_changed(repo)
    set_lab_state(2, solved=False, repo=repo)
    installed = _seam_file(2, repo).read_bytes()
    said: list[str] = []

    _start(2, repo, said)

    assert _seam_file(2, repo).read_bytes() == installed
    assert not any("Installed" in line for line in said)


def test_an_interrupted_install_keeps_an_edit_made_since(repo, aurora) -> None:
    _interrupt_before_the_file_changed(repo)
    set_lab_state(2, solved=False, repo=repo)
    edited = _participant_edit(repo)
    said: list[str] = []

    _start(2, repo, said)

    assert _seam_file(2, repo).read_bytes() == edited
    assert any("Kept your edits" in line for line in said)


def test_a_failed_apply_is_retried_without_reinstalling_the_fault(repo, aurora) -> None:
    aurora.fail_apply = True
    with pytest.raises(RuntimeError, match="connection dropped"):
        _start(2, repo)
    record = lab_entry.load_record(2, repo)
    assert record["steps"]["fault"]["state"] == "done"
    assert "applied" not in record["steps"]
    assert not record.get("completed_at")
    edited = _participant_edit(repo)

    aurora.fail_apply = False
    record = _start(2, repo)

    assert _seam_file(2, repo).read_bytes() == edited
    assert aurora.applies == 1
    assert record["completed_at"]


def test_a_failed_capture_is_retried_without_repeating_earlier_steps(
    repo, aurora
) -> None:
    aurora.fail_capture = True
    with pytest.raises(RuntimeError, match="API restarting"):
        _start(2, repo)
    edited = _participant_edit(repo)

    aurora.fail_capture = False
    record = _start(2, repo)

    assert _seam_file(2, repo).read_bytes() == edited
    assert (aurora.applies, aurora.captures) == (1, 1)
    assert record["steps"]["evidence"]["search_event_id"] == "run-2"


def test_an_already_applied_lab_2_repair_saves_no_failing_run(repo, aurora) -> None:
    aurora.applied[2] = "applied"
    said: list[str] = []

    record = _start(2, repo, said)

    assert aurora.captures == 0
    assert record["steps"]["evidence"]["note"].startswith("repair already applied")
    assert any("already applied" in line for line in said)


@pytest.mark.parametrize(
    ("lab", "unmet", "applied", "fix"),
    [
        (2, 1, {1: "applied"}, "complete its LAB1_ block"),
        (2, None, {1: "stale"}, "Lab 1's repair is in"),
        (3, 2, {1: "applied", 2: "applied"}, "complete its LAB2_ block"),
        (3, None, {1: "applied", 2: "stale"}, "Lab 2's repair is in"),
    ],
)
def test_an_unmet_prerequisite_explains_the_fix_and_changes_nothing(
    repo, aurora, lab, unmet, applied, fix
) -> None:
    if unmet:
        set_lab_state(unmet, solved=False, repo=repo)
    aurora.applied = applied
    before = {path: (repo / path).read_bytes() for path, _ in LABS.values()}

    with pytest.raises(lab_entry.LabEntryError, match=fix):
        _start(lab, repo)

    assert {path: (repo / path).read_bytes() for path, _ in LABS.values()} == before
    assert lab_entry.load_record(lab, repo) is None
    assert (aurora.applies, aurora.captures) == (0, 0)
    if unmet:
        assert not lab_is_solved(unmet, repo=repo), "a start never installs a solution"


def test_restart_discards_only_the_selected_labs_edits(repo, aurora) -> None:
    _start(2, repo)
    completion = lab_entry.completion_path(2, repo)
    completion.write_text("{}")
    _participant_edit(repo)
    lab_3 = _seam_file(3, repo).read_bytes()

    record = lab_entry.restart(
        2, api_url="http://api", dsn="aurora", repo=repo, say=print
    )

    assert not lab_is_solved(2, repo=repo)
    assert lab_is_solved(1, repo=repo)
    assert _seam_file(3, repo).read_bytes() == lab_3
    assert not completion.exists()
    assert record["completed_at"]
    assert (aurora.applies, aurora.captures) == (2, 2)


def test_lab_1_start_saves_the_request_and_never_edits_or_applies(repo, aurora) -> None:
    set_lab_state(1, solved=False, repo=repo)
    aurora.applied[1] = "stale"
    before = _seam_file(1, repo).read_bytes()

    record = _start(1, repo)

    assert _seam_file(1, repo).read_bytes() == before
    assert (aurora.applies, aurora.captures) == (0, 1)
    assert "fault" not in record["steps"]


def test_lab_1_restart_restores_and_applies_its_starter(repo, aurora) -> None:
    aurora.applied[1] = "stale"
    lab_2 = _seam_file(2, repo).read_text()

    lab_entry.restart(1, api_url="http://api", dsn="aurora", repo=repo, say=print)

    assert not lab_is_solved(1, repo=repo)
    assert lab_is_solved(2, repo=repo)
    assert aurora.applies == 1
    for start, end, _, _ in LABS[2][1]:
        assert (
            _seam_file(2, repo).read_text().split(start, 1)[1].split(end, 1)[0]
            == lab_2.split(start, 1)[1].split(end, 1)[0]
        )


def test_lab_3_start_installs_the_starter_and_records_the_refusal(repo, aurora) -> None:
    aurora.applied[2] = "applied"

    record = _start(3, repo)

    assert not lab_is_solved(3, repo=repo)
    assert lab_is_solved(2, repo=repo)
    assert aurora.applies == 0
    assert "agent_refusal" in record["steps"]["evidence"]
