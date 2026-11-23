"""Entering a lab: once, resumable, and never at the cost of the participant's edits.

Aurora and the API are the boundaries here: the applied-state read, the apply
and the saved request are substituted; the seam files, the start record and
the prerequisite logic run as shipped, on a copy of the checkout.
"""

from __future__ import annotations

import io
import json
import re
import sys
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
    lab_source_is_repaired,
    set_lab_state,
)
from service.participant_commands import advance_command, start_command

#: The shipped apply step, kept before the `aurora` fixture substitutes it.
REAL_APPLY = lab_entry._apply

PARTICIPANT_LAB_2 = "SELECT 1.0 / (rrf_k + source_rank)"


class Boundaries:
    """What the start asked of Aurora and the API, and what they answer."""

    def __init__(self) -> None:
        self.applied: dict[int, str] = {1: "applied", 2: "stale"}
        self.applies = 0
        self.captures = 0
        self.phases: list[tuple[int, str]] = []
        self.fail_apply = False
        self.fail_capture = False
        # When set, an apply makes Aurora run the saved files: a SQL lab then
        # reads as applied only if its saved block is repaired.
        self.applies_saved_files = False


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

    def read_applied_sql_state(lab, _connection, **_kwargs):
        return LabDatabaseState(
            state=state.applied.get(lab, "not_applicable"), detail=""
        )

    def apply(_dsn, repo, say):
        if state.fail_apply:
            raise RuntimeError("Aurora connection dropped")
        state.applies += 1
        if state.applies_saved_files:
            for lab in (1, 2):
                solved = lab_source_is_repaired(lab, repo=repo)
                state.applied[lab] = "applied" if solved else "stale"
        say("Applied it to Aurora.")
        return "sha"

    def prepare(lab, phase, _api_url, output, *, handoff=False):
        if state.fail_capture:
            raise RuntimeError("API restarting")
        state.captures += 1
        state.phases.append((lab, phase))
        output.mkdir(parents=True, exist_ok=True)
        (output / f"{phase}-state.json").write_text(
            json.dumps({"run_id": f"run-{lab}"})
        )
        # Every saved search writes the context the guide's psql step loads.
        (output / "context.psql").write_text(f"-- {phase} run-{lab}\n")
        return output / "context.psql"

    monkeypatch.setattr(lab_entry, "assert_workshop_database", lambda _dsn: None)
    monkeypatch.setattr(lab_entry, "_connect", connect)
    monkeypatch.setattr(lab_entry, "read_applied_sql_state", read_applied_sql_state)
    monkeypatch.setattr(lab_entry, "_apply", apply)
    monkeypatch.setattr("scripts.lab_request.prepare", prepare)
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

    assert not lab_source_is_repaired(2, repo=repo)
    assert lab_source_is_repaired(1, repo=repo)
    assert lab_source_is_repaired(3, repo=repo)
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

    assert not lab_source_is_repaired(2, repo=repo)
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

    record = _start(2, repo)

    assert record["steps"]["evidence"]["note"].startswith("repair already applied")
    assert aurora.phases == [(2, "after")], "the search as it is now, never a Before"
    assert (repo / ".local/lab-2/context.psql").exists()


@pytest.mark.parametrize("applied", ["applied", "stale"])
def test_lab_1_start_always_leaves_the_psql_context(repo, aurora, applied) -> None:
    # psql skips a missing PSQLRC file silently, so Lab 1's first psql step would
    # open without Alex's request. A repair applied before the start saves no
    # failing run; the context then comes from the search as it is now.
    set_lab_state(1, solved=applied == "applied", repo=repo)
    aurora.applied[1] = applied

    record = _start(1, repo)

    phase = "after" if applied == "applied" else "before"
    assert aurora.phases == [(1, phase)]
    assert record.get("completed_at")
    assert (repo / ".local/lab-1/context.psql").read_text() == f"-- {phase} run-1\n"


def test_a_repeated_start_saves_a_missing_context_and_keeps_an_existing_one(
    repo, aurora
) -> None:
    aurora.applied[1] = "applied"
    lab_entry._save(
        1,
        repo,
        {
            "version": 1,
            "lab": 1,
            "steps": {
                "evidence": {
                    "state": "done",
                    "note": "repair already applied; no failing run saved",
                }
            },
            "completed_at": "2026-11-09T05:00:00+00:00",
        },
    )
    said: list[str] = []

    _start(1, repo, said)
    _start(1, repo, said)

    assert aurora.phases == [(1, "after")], "saved once, then left alone"
    assert (repo / ".local/lab-1/context.psql").exists()
    assert all("your edits are unchanged" in line for line in said)


def test_a_failed_context_save_keeps_the_start_recorded_for_a_retry(
    repo, aurora
) -> None:
    aurora.applied[1] = "applied"
    aurora.fail_capture = True

    with pytest.raises(RuntimeError, match="API restarting"):
        _start(1, repo)

    assert lab_entry.load_record(1, repo)["completed_at"]
    aurora.fail_capture = False
    _start(1, repo)
    assert aurora.phases == [(1, "after")]


@pytest.mark.parametrize(
    ("lab", "unmet", "applied", "fix"),
    [
        (2, 1, {1: "applied"}, "Lab 1 is not repaired: in labs/lab1_retrieve"),
        (2, None, {1: "stale"}, "Lab 1's saved repair is not in Aurora"),
        (
            3,
            2,
            {1: "applied", 2: "applied"},
            "Lab 2 is not repaired: in labs/lab2_rank",
        ),
        (3, None, {1: "applied", 2: "stale"}, "Lab 2's saved repair is not in Aurora"),
    ],
)
def test_an_unmet_prerequisite_explains_the_fix_and_changes_nothing(
    repo, aurora, lab, unmet, applied, fix
) -> None:
    if unmet:
        set_lab_state(unmet, solved=False, repo=repo)
    aurora.applied = applied
    before = {path: (repo / path).read_bytes() for path, _ in LABS.values()}

    with pytest.raises(lab_entry.LabEntryError, match=fix) as refused:
        _start(lab, repo)

    assert str(refused.value).endswith(
        f"\n\nNext: after the fixes above, run\n{start_command(lab)}"
    )

    assert {path: (repo / path).read_bytes() for path, _ in LABS.values()} == before
    assert lab_entry.load_record(lab, repo) is None
    assert (aurora.applies, aurora.captures) == (0, 0)
    if unmet:
        assert not lab_source_is_repaired(unmet, repo=repo), (
            "a start never installs a solution"
        )


def test_restart_discards_only_the_selected_labs_edits(repo, aurora) -> None:
    _start(2, repo)
    completion = lab_entry.completion_path(2, repo)
    completion.write_text("{}")
    _participant_edit(repo)
    lab_3 = _seam_file(3, repo).read_bytes()

    record = lab_entry.restart(
        2, api_url="http://api", dsn="aurora", repo=repo, say=print
    )

    assert not lab_source_is_repaired(2, repo=repo)
    assert lab_source_is_repaired(1, repo=repo)
    assert _seam_file(3, repo).read_bytes() == lab_3
    assert not completion.exists()
    assert record["completed_at"]
    assert (aurora.applies, aurora.captures) == (2, 2)


@pytest.mark.parametrize("lab", [1, 2])
def test_restart_puts_back_a_deleted_lab_file(repo, aurora, lab: int) -> None:
    if lab == 2:
        _start(2, repo)
    _seam_file(lab, repo).unlink()

    record = lab_entry.restart(
        lab, api_url="http://api", dsn="aurora", repo=repo, say=print
    )

    assert _seam_file(lab, repo).exists()
    assert not lab_source_is_repaired(lab, repo=repo)
    assert record["completed_at"]


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

    assert not lab_source_is_repaired(1, repo=repo)
    assert lab_source_is_repaired(2, repo=repo)
    assert aurora.applies == 1
    for start, end, _, _ in LABS[2][1]:
        assert (
            _seam_file(2, repo).read_text().split(start, 1)[1].split(end, 1)[0]
            == lab_2.split(start, 1)[1].split(end, 1)[0]
        )


def test_lab_3_start_installs_the_starter_and_records_the_refusal(repo, aurora) -> None:
    aurora.applied[2] = "applied"

    record = _start(3, repo)

    assert not lab_source_is_repaired(3, repo=repo)
    assert lab_source_is_repaired(2, repo=repo)
    assert aurora.applies == 0
    assert "agent_refusal" in record["steps"]["evidence"]


def test_lab_3_start_prints_the_deploy_command_on_its_own_line(repo, aurora) -> None:
    """The handoff's last lines fit a laptop terminal, so none wraps mid-word."""
    from service.participant_commands import DEPLOY_AGENT

    aurora.applied[2] = "applied"
    said: list[str] = []

    _start(3, repo, said)

    lines = [line for message in said for line in message.splitlines()]
    assert max(len(line) for line in lines) <= 100
    assert f"      {DEPLOY_AGENT}" in lines


@pytest.fixture
def handoff_checks(monkeypatch):
    calls = []

    def validate(_url, events, *, rerun):
        from service.participant_commands import ADVANCE_TO_LAB_2

        assert rerun == ADVANCE_TO_LAB_2
        calls.append("validate")
        events.append("verified-lab-1")
        return ["target_recovered", "filter_controls"]

    monkeypatch.setattr("scripts.prove_lab.prove_lab_1", validate)
    return calls


def test_handoff_saves_passing_evidence_before_installing_fault(
    repo, aurora, handoff_checks
):
    lines = []
    lab_entry.advance(
        1, api_url="http://api", dsn="aurora", repo=repo, say=lines.append
    )
    assert handoff_checks == ["validate"]
    assert not lab_source_is_repaired(2, repo=repo)
    assert aurora.applies == 1 and aurora.captures == 1
    saved = json.loads(lab_entry.completion_path(1, repo).read_text())
    assert saved["search_event_ids"] == ["verified-lab-1"]
    passed = next(
        i
        for i, line in enumerate(lines)
        if re.fullmatch(
            r"\nLab 1: all \d+ checks passed\. Passing evidence saved\.", line
        )
    )
    assert passed < next(
        i for i, line in enumerate(lines) if line.startswith("Installed")
    )


def test_failed_lab1_validation_never_starts_lab2(repo, aurora, monkeypatch):
    from scripts.prove_lab import LabValidationError

    def fail(*_args, **_options):
        raise LabValidationError("target missing")

    monkeypatch.setattr("scripts.prove_lab.prove_lab_1", fail)
    with pytest.raises(LabValidationError, match="target missing"):
        lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)
    assert lab_source_is_repaired(2, repo=repo)
    assert lab_entry.load_record(2, repo) is None
    assert not lab_entry.completion_path(1, repo).exists()
    assert aurora.applies == 0


def test_interrupted_handoff_resumes_and_keeps_lab2_edits(repo, aurora, handoff_checks):
    aurora.fail_capture = True
    with pytest.raises(RuntimeError, match="API restarting"):
        lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)
    evidence = lab_entry.completion_path(1, repo).read_bytes()
    edited = _participant_edit(repo)
    aurora.fail_capture = False
    lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)
    lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)
    assert handoff_checks == ["validate"]
    assert _seam_file(2, repo).read_bytes() == edited
    assert lab_entry.completion_path(1, repo).read_bytes() == evidence
    assert aurora.applies == 1 and aurora.captures == 1


def test_handoff_refuses_changed_database_or_lab1(repo, aurora, handoff_checks):
    lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)
    with pytest.raises(lab_entry.LabEntryError, match="selects a different database"):
        lab_entry.advance(1, api_url="http://api", dsn="different-aurora", repo=repo)
    assert handoff_checks == ["validate"]
    assert aurora.applies == 1


@pytest.mark.parametrize("aurora_state", ["applied", "stale"])
def test_a_refused_handoff_names_the_problem_and_advance_as_the_rerun(
    repo, aurora, handoff_checks, aurora_state
) -> None:
    from service.participant_commands import ADVANCE_TO_LAB_2

    set_lab_state(1, solved=False, repo=repo)
    aurora.applied = {1: aurora_state}

    with pytest.raises(lab_entry.LabEntryError) as refused:
        lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)

    lines = str(refused.value).splitlines()
    assert lines[0] == "Lab 1 cannot hand off yet."
    assert lines[1].startswith("- Lab 1 is not repaired: in labs/lab1_retrieve")
    assert lines[2].startswith("  Fix: ")
    assert lines[-3:] == ["", "Next: after the fixes above, run", ADVANCE_TO_LAB_2]
    assert "start this lab again" not in str(refused.value)
    assert handoff_checks == [] and aurora.applies == 0


def _own_wording(repo: Path) -> None:
    """Save a repair that passes the contract but words the branch differently."""
    path = _seam_file(1, repo)
    path.write_text(
        path.read_text().replace(
            "SELECT product_id, 'fuzzy', fuzzy_rank,",
            "SELECT product_id, 'fuzzy'::text AS channel, fuzzy_rank AS source_rank,",
        )
    )
    assert lab_source_is_repaired(1, repo=repo)


def test_a_handoff_applies_a_saved_repair_aurora_does_not_run_yet(
    repo, aurora, handoff_checks
) -> None:
    """One correct repair applied, then another saved: the handoff applies the saved one."""
    _own_wording(repo)
    aurora.applied = {1: "stale"}
    aurora.applies_saved_files = True
    lines: list[str] = []

    lab_entry.advance(
        1, api_url="http://api", dsn="aurora", repo=repo, say=lines.append
    )

    applying = [line for line in lines if "applying the saved SQL first" in line]
    assert applying == [
        (
            "Your saved hybrid_search.sql is repaired, but Aurora runs an earlier version of "
            "it; applying the saved SQL first."
        )
    ]
    assert lines.index(applying[0]) < lines.index("Applied it to Aurora.")
    assert handoff_checks == ["validate"]
    assert lines[-1].startswith("\nLab 2: prepared.")


def test_a_handoff_that_cannot_apply_the_saved_repair_says_why(
    repo, aurora, handoff_checks, monkeypatch
) -> None:
    from service.participant_commands import ADVANCE_TO_LAB_2

    def rejected(_dsn, _repo, _say):
        raise ValueError("Lab catalog rule: prepared dataset 'old' differs from 'new'")

    monkeypatch.setattr(lab_entry, "_apply", rejected)
    aurora.applied = {1: "stale"}

    with pytest.raises(lab_entry.LabEntryError) as refused:
        lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)

    message = str(refused.value)
    assert message.startswith(
        "Lab 1 cannot hand off yet: applying your saved SQL failed."
    )
    assert "Lab catalog rule: prepared dataset 'old' differs from 'new'" in message
    assert message.endswith(f"\n\nNext: after fixing that, run\n{ADVANCE_TO_LAB_2}")
    assert handoff_checks == []


@pytest.fixture
def lab_2_repaired(repo, aurora) -> Path:
    """Lab 2 entered through its start, then repaired and applied by the participant."""
    _start(2, repo)
    set_lab_state(2, solved=True, repo=repo)
    aurora.applied[2] = "applied"
    return repo


@pytest.fixture
def lab_2_checks(monkeypatch):
    calls = []

    def validate(_url, events, *, rerun):
        calls.append(rerun)
        events.extend(["first-lab-2", "second-lab-2"])
        return ["contribution correct", "G-007: right product in the top 10"]

    monkeypatch.setattr("scripts.prove_lab.prove_lab_2", validate)
    return calls


def test_lab_2_handoff_saves_passing_evidence_then_installs_the_lab_3_starter(
    lab_2_repaired, aurora, lab_2_checks
):
    from service.participant_commands import ADVANCE_TO_LAB_3

    lines = []
    lab_entry.advance(
        2, api_url="http://api", dsn="aurora", repo=lab_2_repaired, say=lines.append
    )

    assert lab_2_checks == [ADVANCE_TO_LAB_3]
    assert not lab_source_is_repaired(3, repo=lab_2_repaired)
    assert lab_source_is_repaired(2, repo=lab_2_repaired)
    saved = json.loads(lab_entry.completion_path(2, lab_2_repaired).read_text())
    assert saved["search_event_ids"] == ["first-lab-2", "second-lab-2"]
    passed = next(
        i
        for i, line in enumerate(lines)
        if re.fullmatch(
            r"\nLab 2: all \d+ checks passed\. Passing evidence saved\.", line
        )
    )
    assert passed < next(
        i for i, line in enumerate(lines) if line.startswith("Installed")
    )
    assert any("Your Retrieval agent is not built yet" in line for line in lines)
    assert lines[-1].startswith("\nLab 3: prepared.")


def test_the_lab_3_prepared_line_is_bold_on_a_terminal(
    lab_2_repaired, aurora, lab_2_checks, monkeypatch
):
    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys, "stdout", Terminal())
    lines = []

    lab_entry.advance(
        2, api_url="http://api", dsn="aurora", repo=lab_2_repaired, say=lines.append
    )

    assert lines[-1].startswith(
        "\n\033[1mLab 3: prepared.\033[0m Continue in the Lab 3 guide."
    )


def test_lab_2_handoff_refuses_before_lab_2_has_started(repo, aurora, lab_2_checks):
    with pytest.raises(lab_entry.LabEntryError) as refused:
        lab_entry.advance(2, api_url="http://api", dsn="aurora", repo=repo)

    message = str(refused.value)
    assert message.startswith("Lab 2 cannot hand off yet.")
    assert f"Next: run {advance_command(1)}" in message
    assert lab_2_checks == []
    assert lab_entry.load_record(3, repo) is None


def test_failed_lab_2_validation_never_starts_lab_3(lab_2_repaired, monkeypatch):
    from scripts.prove_lab import LabValidationError

    def fail(*_args, **_options):
        raise LabValidationError("target missing")

    monkeypatch.setattr("scripts.prove_lab.prove_lab_2", fail)
    with pytest.raises(LabValidationError, match="target missing"):
        lab_entry.advance(2, api_url="http://api", dsn="aurora", repo=lab_2_repaired)
    assert lab_entry.load_record(3, lab_2_repaired) is None
    assert lab_source_is_repaired(3, repo=lab_2_repaired)
    assert not lab_entry.completion_path(2, lab_2_repaired).exists()


def test_a_rerun_lab_2_handoff_proves_lab_2_again_and_keeps_lab_3_edits(
    lab_2_repaired, lab_2_checks
):
    lab_entry.advance(2, api_url="http://api", dsn="aurora", repo=lab_2_repaired)
    agent = _seam_file(3, lab_2_repaired)
    agent.write_text(agent.read_text() + "\n# participant note\n")
    edited = agent.read_bytes()

    lines = []
    lab_entry.advance(
        2, api_url="http://api", dsn="aurora", repo=lab_2_repaired, say=lines.append
    )

    assert len(lab_2_checks) == 2
    assert agent.read_bytes() == edited
    assert any(line.startswith("Lab 3 was started at") for line in lines)


def test_a_refused_lab_2_handoff_names_the_problem_and_advance_as_the_rerun(
    lab_2_repaired, aurora, lab_2_checks
) -> None:
    from service.participant_commands import ADVANCE_TO_LAB_3

    set_lab_state(2, solved=False, repo=lab_2_repaired)
    aurora.applied[2] = "stale"
    applies = aurora.applies

    with pytest.raises(lab_entry.LabEntryError) as refused:
        lab_entry.advance(2, api_url="http://api", dsn="aurora", repo=lab_2_repaired)

    lines = str(refused.value).splitlines()
    assert lines[0] == "Lab 2 cannot hand off yet."
    assert lines[1].startswith("- Lab 2 is not repaired: in labs/lab2_rank")
    assert lines[-3:] == ["", "Next: after the fixes above, run", ADVANCE_TO_LAB_3]
    assert lab_2_checks == [] and aurora.applies == applies
    assert lab_entry.load_record(3, lab_2_repaired) is None


def test_a_lab_2_handoff_applies_a_saved_repair_aurora_does_not_run_yet(
    lab_2_repaired, aurora, lab_2_checks
) -> None:
    aurora.applied[2] = "stale"
    aurora.applies_saved_files = True
    applies = aurora.applies
    lines: list[str] = []

    lab_entry.advance(
        2, api_url="http://api", dsn="aurora", repo=lab_2_repaired, say=lines.append
    )

    assert (
        "Your saved rrf_contribution.sql is repaired, but Aurora runs an earlier version "
        "of it; applying the saved SQL first."
    ) in lines
    assert aurora.applies == applies + 1
    assert len(lab_2_checks) == 1
    assert lab_entry.load_record(3, lab_2_repaired) is not None


def test_lab_3_has_no_handoff_and_says_how_it_ends(repo, aurora) -> None:
    from service.participant_commands import grade_setup_run_command

    with pytest.raises(lab_entry.LabEntryError) as refused:
        lab_entry.advance(3, api_url="http://api", dsn="aurora", repo=repo)

    assert "advance --lab 1 or advance --lab 2" in str(refused.value)
    assert grade_setup_run_command() in str(refused.value)


def test_a_lab_1_reset_after_a_repaired_lab_2_validates_lab_1_again(
    lab_2_repaired, aurora, handoff_checks
):
    edited = _participant_edit(lab_2_repaired)
    lines: list[str] = []
    lab_entry.advance(
        1, api_url="http://api", dsn="aurora", repo=lab_2_repaired, say=lines.append
    )
    assert handoff_checks == ["validate"]
    assert _seam_file(2, lab_2_repaired).read_bytes() == edited
    assert lines[-1].startswith(
        "\nLab 2: already prepared; continue where you left off"
    )
    assert not any("saved failure" in line for line in lines)


def test_lab_1_is_not_validated_under_an_unrepaired_lab_2(repo, aurora, handoff_checks):
    _start(2, repo)
    with pytest.raises(lab_entry.LabEntryError, match="ranking fault can hide"):
        lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)
    assert handoff_checks == []


@pytest.mark.parametrize("interrupted", [False, True])
@pytest.mark.parametrize("lab", [2, 3])
def test_start_puts_back_a_deleted_exercise_before_installing_the_fault(
    repo, aurora, lab: int, interrupted: bool
) -> None:
    aurora.applied[2] = "applied"
    if lab == 2 and interrupted:
        _interrupt_before_the_file_changed(repo)
    _seam_file(lab, repo).unlink()
    said: list[str] = []

    record = _start(lab, repo, said)

    assert _seam_file(lab, repo).exists()
    assert not lab_source_is_repaired(lab, repo=repo)
    assert record["completed_at"]
    assert any("Put back" in line and "deleted" in line for line in said)


def test_lab_1_start_refuses_a_deleted_exercise_with_the_way_back(repo, aurora) -> None:
    _seam_file(1, repo).unlink()

    with pytest.raises(lab_entry.LabEntryError) as refused:
        _start(1, repo)

    assert str(refused.value) == lab_entry.missing_file_problem(1, repo).line
    assert (aurora.applies, aurora.captures) == (0, 0)


@pytest.mark.parametrize("interrupted", [False, True])
@pytest.mark.parametrize("lab", [1, 2])
def test_advance_refuses_a_deleted_exercise_with_the_way_back(
    repo, aurora, lab: int, interrupted: bool
) -> None:
    if lab == 2 and interrupted:
        _interrupt_before_the_file_changed(repo)
    _seam_file(lab, repo).unlink()

    with pytest.raises(lab_entry.LabEntryError) as refused:
        lab_entry.advance(lab, api_url="http://api", dsn="aurora", repo=repo)

    assert str(refused.value) == lab_entry.missing_file_problem(lab, repo).line
    assert (aurora.applies, aurora.captures) == (0, 0)


def test_a_start_with_an_earlier_lab_file_deleted_names_it(repo, aurora) -> None:
    _seam_file(1, repo).unlink()

    with pytest.raises(lab_entry.LabEntryError) as refused:
        _start(2, repo)

    assert "Lab 1: FILE MISSING" in str(refused.value)


def test_restart_with_the_lab_1_folder_deleted_names_it_and_changes_nothing(
    shipped_labs: Path, aurora
) -> None:
    from shutil import rmtree

    lab_2 = _seam_file(2, shipped_labs).read_bytes()
    rmtree(shipped_labs / "labs/lab1_retrieve")

    with pytest.raises(lab_entry.LabEntryError) as refused:
        lab_entry.restart(
            2, api_url="http://api", dsn="aurora", repo=shipped_labs, say=print
        )

    assert "Lab 2 cannot restart yet." in str(refused.value)
    assert "Lab 1: FILE MISSING" in str(refused.value)
    assert _seam_file(2, shipped_labs).read_bytes() == lab_2
    assert not lab_entry.record_path(2, shipped_labs).exists()


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("{", "it is cut off or is not JSON"),
        (b"\xff\xfe", "it is cut off or is not JSON"),
        ('"started"', "it holds a JSON string, not a record"),
        ("[]", "it holds a JSON list, not a record"),
        ("3", "it holds a JSON number, not a record"),
        ("null", "it holds JSON null, not a record"),
    ],
    ids=["cut-off", "not-text", "string", "list", "number", "null"],
)
def test_a_damaged_start_record_says_what_is_wrong_in_words(
    tmp_path: Path, text: str | bytes, problem: str
) -> None:
    """The reason reads as a sentence, never a Python exception or type name."""
    path = lab_entry.record_path(1, tmp_path)
    path.parent.mkdir(parents=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")

    with pytest.raises(lab_entry.StartRecordError) as raised:
        lab_entry.load_record(1, tmp_path)

    assert raised.value.problem == problem
    assert not re.search(
        r"Error|Exception|\b(str|dict|NoneType|int)\b", str(raised.value)
    )


def test_entry_command_names_the_hand_off_that_prepares_a_lab(tmp_path):
    assert lab_entry.entry_command(1, tmp_path) == start_command(1)
    assert lab_entry.entry_command(2, tmp_path) == advance_command(1)
    assert lab_entry.entry_command(3, tmp_path) == advance_command(1)

    lab_entry._save(
        2,
        tmp_path,
        {
            "lab": 2,
            "version": 1,
            "steps": {},
            "completed_at": "2026-11-15T10:00:00+00:00",
        },
    )
    assert lab_entry.entry_command(3, tmp_path) == advance_command(2)

    lab_entry._save(3, tmp_path, {"lab": 3, "version": 1, "steps": {}})
    assert lab_entry.entry_command(3, tmp_path) == start_command(3)


def test_the_start_record_recovery_puts_each_command_on_its_own_line():
    error = lab_entry.StartRecordError(3, "it is cut off or is not JSON")

    lines = str(error).splitlines()

    assert lines[0] == (
        "Lab 3 start record rule: .local/lab-3/start.json cannot be read "
        "(it is cut off or is not JSON)."
    )
    commands = [line for line in lines if line.startswith(("cp ", "uv run "))]
    assert commands == [
        "cp labs/lab3_reason/agent.py ~/my-agent.py",
        "uv run python scripts/lab_state.py reset --lab 3",
        "cp ~/my-agent.py labs/lab3_reason/agent.py",
        "uv run python scripts/deploy_agentcore.py deploy",
    ]
    assert max(len(line) for line in lines) <= 100
    assert str(error).count("Next:") == 1


@pytest.mark.parametrize(
    ("record", "problem"),
    [
        ("{}", "it has no lab number"),
        ('{"lab": 1}', "it has no version number"),
        ('{"lab": 1, "version": 1}', "it has no steps"),
        (
            '{"lab": 1, "version": 1, "steps": []}',
            "its steps are a JSON list, not an object",
        ),
        (
            '{"lab": 1, "version": 1, "steps": 3}',
            "its steps are a JSON number, not an object",
        ),
        (
            '{"lab": 1, "version": 1, "steps": {}, "completed_at": true}',
            "its start time true is not a time",
        ),
        (
            '{"lab": 1, "version": 1, "steps": {}, "completed_at": "soon"}',
            'its start time "soon" is not a time',
        ),
        (
            '{"lab": 1, "version": 1, "steps": {}, "completed_at": "2026-11-15T10:00:00"}',
            'its start time "2026-11-15T10:00:00" has no time zone',
        ),
        ('{"lab": "x", "version": 2, "steps": {}}', 'it is marked lab "x"'),
        (
            '{"lab": true, "version": 1, "steps": {}}',
            "it is marked lab true, version 1",
        ),
    ],
)
def test_a_start_record_that_would_crash_later_is_refused_now_in_words(
    tmp_path: Path, record: str, problem: str
) -> None:
    path = lab_entry.record_path(1, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(record)

    with pytest.raises(lab_entry.StartRecordError) as raised:
        lab_entry.load_record(1, tmp_path)

    assert problem in raised.value.problem
    assert not re.search(
        r"\bNone\b|\bTrue\b|\bFalse\b|\{\}|\[\]|'", raised.value.problem
    )


def test_a_cannot_be_opened_start_record_names_the_reason(tmp_path: Path, monkeypatch):
    path = lab_entry.record_path(1, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{}")

    def refuse(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(Path, "read_text", refuse)

    with pytest.raises(lab_entry.StartRecordError) as raised:
        lab_entry.load_record(1, tmp_path)

    assert raised.value.problem == "it cannot be opened: permission denied"


def _own_lab_1_wording_again(repo: Path) -> None:
    """A second valid Lab 1 repair, worded differently from the first."""
    path = _seam_file(1, repo)
    path.write_text(
        path.read_text().replace(
            "SELECT product_id, 'fuzzy', fuzzy_rank,",
            "SELECT product_id, 'fuzzy'::text AS label, fuzzy_rank AS position,",
        )
    )
    assert lab_source_is_repaired(1, repo=repo)


def test_a_handoff_receipt_names_the_attempt_and_the_proved_sql(
    repo, aurora, handoff_checks
) -> None:
    lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)

    reading = lab_entry.read_completion(1, repo)
    assert reading.state == "valid"
    assert reading.receipt["sql_sha256"] == lab_entry.sql_identity(1, repo)


@pytest.mark.parametrize("damage", ["", "{"])
def test_a_repeated_handoff_rebuilds_a_damaged_receipt_from_its_own_evidence(
    repo, aurora, handoff_checks, damage
) -> None:
    """The saved handoff is bound to this attempt and block, so no new search is needed."""
    lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)
    lab_entry.completion_path(1, repo).write_text(damage)
    edited = _participant_edit(repo)

    lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)

    assert handoff_checks == ["validate"]
    reading = lab_entry.read_completion(1, repo)
    assert reading.state == "valid"
    assert reading.receipt["search_event_ids"] == ["verified-lab-1"]
    assert _seam_file(2, repo).read_bytes() == edited


def test_a_lab_1_repair_edited_after_handoff_is_proved_again_once_lab_2_cannot_hide_it(
    repo, aurora, handoff_checks
) -> None:
    lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)
    set_lab_state(2, solved=True, repo=repo)
    aurora.applied = {1: "applied", 2: "applied"}
    _own_lab_1_wording_again(repo)
    assert lab_entry.read_completion(1, repo).state == "other_sql"
    agent = _seam_file(3, repo).read_bytes()

    lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)

    assert handoff_checks == ["validate", "validate"]
    assert lab_entry.read_completion(1, repo).state == "valid"
    assert _seam_file(3, repo).read_bytes() == agent


def test_a_lab_1_repair_edited_after_handoff_waits_while_lab_2s_fault_is_installed(
    repo, aurora, handoff_checks
) -> None:
    lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)
    aurora.applied = {1: "applied", 2: "stale"}
    _own_lab_1_wording_again(repo)

    with pytest.raises(lab_entry.LabEntryError) as refused:
        lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)

    message = str(refused.value)
    assert "your LAB1_EDIT block changed" in message
    assert "Lab 2's ranking fault can hide a correct Lab 1 repair" in message
    assert f"run {advance_command(1)} to prove Lab 1 again" in message
    assert handoff_checks == ["validate"]
    assert lab_entry.lab_1_waits_for_lab_2("aurora", repo)


def test_a_damaged_lab_1_receipt_under_lab_2s_fault_is_restored_by_its_handoff(
    repo, aurora, handoff_checks, monkeypatch, capsys
) -> None:
    """Status must name the step that works: `advance --lab 1`, not a refused request."""
    from scripts import lab_state
    from service.participant_commands import ADVANCE_TO_LAB_2, repeat_request_command

    lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)
    aurora.applied = {1: "applied", 2: "stale"}
    lab_entry.completion_path(1, repo).write_text("")

    assert lab_entry.read_completion(1, repo).state != "valid"
    assert lab_entry.lab_1_handoff_restores_proof("aurora", repo)
    assert not lab_entry.lab_1_waits_for_lab_2("aurora", repo)

    monkeypatch.setenv("DATABASE_URL", "aurora")
    lab_state._status_next(
        ["Lab 1: APPLIED, NOT YET PROVED", "Lab 2: B", "Lab 3: B"], repo
    )
    shown = capsys.readouterr().out
    assert ADVANCE_TO_LAB_2 in shown and "restores the record" in shown
    assert repeat_request_command(1) not in shown

    lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)
    assert lab_entry.read_completion(1, repo).state == "valid"
    assert handoff_checks == ["validate"], "restored from the handoff, no new search"


def test_starting_lab_2_keeps_lab_1s_handed_off_proof(repo, aurora, handoff_checks):
    lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)

    assert lab_entry.load_record(2, repo)["completed_at"]
    assert lab_entry.read_completion(1, repo).state == "valid"
    assert not lab_entry.lab_1_waits_for_lab_2("aurora", repo)


class _InstalledSql:
    """Aurora holding the function bodies it last applied, answering the real reads."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.installed = {
            1: _seam_file(1, repo).read_text(),
            2: _seam_file(2, repo).read_text(),
        }
        self.applies = 0

    def execute(self, sql: str, params=None):
        from types import SimpleNamespace

        from scripts.checks.retrieval_profile import load_profile

        rrf_k = load_profile().rrf_k
        if "pg_get_functiondef" in sql:
            lab = 2 if "reciprocal_rank_contribution" in str(params) else 1
            row = {"definition": self.installed[lab]}
        else:
            # Every correct expression gives the same values at ranks 1 and 2.
            row = {
                "first_contribution": 1 / (rrf_k + 1),
                "second_contribution": 1 / (rrf_k + 2),
            }
        return SimpleNamespace(fetchone=lambda: row)

    def apply_saved_files(self) -> None:
        self.applies += 1
        self.installed = {lab: _seam_file(lab, self.repo).read_text() for lab in (1, 2)}


@pytest.fixture
def installed_sql(repo, aurora, monkeypatch) -> _InstalledSql:
    """The real applied-state reads over an Aurora that keeps what it was given."""
    from scripts import lab_state

    _start(2, repo)
    set_lab_state(2, solved=True, repo=repo)
    aurora.applied[2] = "applied"
    sql = _InstalledSql(repo)
    order: list[str] = []

    @contextmanager
    def connect(_dsn):
        yield sql

    def apply(_dsn, _repo, say):
        order.append("apply")
        sql.apply_saved_files()
        say("Applied it to Aurora.")
        return "sha"

    monkeypatch.setattr(lab_entry, "assert_workshop_database", lambda _dsn: None)
    monkeypatch.setattr(lab_entry, "_connect", connect)
    monkeypatch.setattr(
        lab_entry, "read_applied_sql_state", lab_state.read_applied_sql_state
    )
    monkeypatch.setattr(lab_entry, "_apply", apply)
    monkeypatch.setattr(
        "scripts.prove_lab.prove_lab_2",
        lambda *_a, **_k: order.append("prove") or ["contribution correct"],
    )
    sql.order = order
    return sql


def _save_other_rrf_expression(repo: Path) -> None:
    path = _seam_file(2, repo)
    start, end, _, _ = LABS[2][1][0]
    path.write_text(_replace_block(path.read_text(), start, end, PARTICIPANT_LAB_2))
    assert lab_source_is_repaired(2, repo=repo)


def test_lab_2_handoff_applies_a_second_valid_expression_that_samples_the_same_ranks(
    repo, installed_sql
) -> None:
    """Ranks 1 and 2 cannot tell two correct expressions apart; the saved block can."""
    _save_other_rrf_expression(repo)
    agent = _seam_file(3, repo)

    lab_entry.advance(2, api_url="http://api", dsn="aurora", repo=repo)

    assert installed_sql.order[:2] == ["apply", "prove"]
    assert installed_sql.applies == 1
    assert "1.0 / (rrf_k + source_rank)" in installed_sql.installed[2]
    agent.write_text(agent.read_text() + "\n# my note\n")
    edited = agent.read_bytes()

    lab_entry.advance(2, api_url="http://api", dsn="aurora", repo=repo)

    assert installed_sql.applies == 1, "nothing changed, so nothing is applied again"
    assert agent.read_bytes() == edited


def test_the_applied_check_reads_a_different_saved_expression_as_not_applied(
    repo, installed_sql
) -> None:
    from scripts.lab_state import applied_problem, read_applied_sql_state

    assert read_applied_sql_state(2, installed_sql, repo=repo).state == "applied"
    _save_other_rrf_expression(repo)

    problem = applied_problem(2, read_applied_sql_state(2, installed_sql, repo=repo))

    assert problem is not None
    assert "different LAB2_EDIT block" in problem.finding


def _limit_one_outside_the_block(repo: Path) -> None:
    """A valid-looking edit to the function's final LIMIT, outside LAB1_EDIT."""
    path = _seam_file(1, repo)
    path.write_text(
        path.read_text().replace("LIMIT greatest(result_limit, 1)", "LIMIT 1")
    )
    assert lab_source_is_repaired(1, repo=repo)


@pytest.fixture
def lab_1_proved(repo, installed_sql, monkeypatch):
    """Lab 1 handed off with the reference function; Aurora runs that function."""
    monkeypatch.setattr(
        "scripts.prove_lab.prove_lab_1",
        lambda _url, events, *, rerun: (
            installed_sql.order.append("prove-1") or events.append("e1") or ["found"]
        ),
    )
    lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)
    installed_sql.order.clear()
    assert lab_entry.read_completion(1, repo).state == "valid"
    return installed_sql


def test_a_comment_edit_outside_the_block_keeps_lab_1s_proof(repo, lab_1_proved):
    path = _seam_file(1, repo)
    path.write_text(path.read_text() + "\n-- a note of mine\n")

    assert lab_entry.read_completion(1, repo).state == "valid"


def test_an_edit_outside_the_block_ends_the_proof_and_is_not_the_installed_sql(
    repo, lab_1_proved
) -> None:
    from scripts import lab_state

    _limit_one_outside_the_block(repo)

    assert lab_entry.read_completion(1, repo).state == "other_sql"
    assert lab_state.status_line(1, repo=repo) != "Lab 1: SOLVED"
    problem = lab_state.applied_problem(
        1, lab_state.read_applied_sql_state(1, lab_1_proved, repo=repo)
    )
    assert problem is not None
    assert "a change outside the marked block counts" in problem.finding

    lab_1_proved.apply_saved_files()
    applied = lab_state.read_applied_sql_state(1, lab_1_proved, repo=repo)
    assert applied.state == "applied"
    assert lab_entry.read_completion(1, repo).state == "other_sql", (
        "applying the edit is not proving it"
    )


def test_advance_refuses_an_out_of_block_edit_and_proves_nothing(
    repo, lab_1_proved
) -> None:
    """An edit outside the block is not the exercise: nothing is applied or credited."""
    _limit_one_outside_the_block(repo)
    edited = _seam_file(1, repo).read_bytes()

    with pytest.raises(lab_entry.LabEntryError, match="changed outside the marked"):
        lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)

    assert lab_1_proved.order == []
    assert _seam_file(1, repo).read_bytes() == edited


def test_lab_2s_deliberate_fault_leaves_lab_1s_proof_alone(repo, lab_1_proved):
    set_lab_state(2, solved=False, repo=repo)

    assert lab_entry.read_completion(1, repo).state == "valid"


def _damage_handoff(repo: Path, **changes) -> None:
    path = repo / ".local/lab-1/handoff.json"
    saved = json.loads(path.read_text())
    saved.update(changes)
    path.write_text(json.dumps(saved))


@pytest.mark.parametrize(
    "damage",
    [
        {"checks": [], "search_event_ids": []},
        {"search_event_ids": [""]},
        {"checks": ["found", 3]},
    ],
    ids=["empty", "blank-event-id", "non-text-check"],
)
def test_a_damaged_handoff_is_not_reused_and_writes_no_receipt(
    repo, lab_1_proved, damage
) -> None:
    set_lab_state(2, solved=False, repo=repo)
    lab_1_proved.installed[2] = _seam_file(2, repo).read_text()
    completion = lab_entry.completion_path(1, repo)
    completion.unlink()
    _damage_handoff(repo, **damage)

    with pytest.raises(lab_entry.LabEntryError) as refused:
        lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)

    message = str(refused.value)
    assert "its saved hand-off evidence is incomplete" in message
    assert "continue in the Lab 2 guide" in message
    assert not completion.exists()
    assert lab_entry.lab_1_waits_for_lab_2("aurora", repo)
    assert not lab_entry.lab_1_handoff_restores_proof("aurora", repo)


def test_a_valid_handoff_restores_the_receipt_without_a_new_search(
    repo, lab_1_proved
) -> None:
    set_lab_state(2, solved=False, repo=repo)
    lab_1_proved.installed[2] = _seam_file(2, repo).read_text()
    lab_entry.completion_path(1, repo).write_text("")

    assert lab_entry.lab_1_handoff_restores_proof("aurora", repo)
    lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)

    assert "prove-1" not in lab_1_proved.order
    assert lab_entry.read_completion(1, repo).state == "valid"


def test_a_damaged_handoff_is_replaced_by_a_live_proof_once_lab_2_cannot_hide_lab_1(
    repo, lab_1_proved
) -> None:
    lab_entry.completion_path(1, repo).unlink()
    _damage_handoff(repo, checks=[], search_event_ids=[])

    lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)

    assert "prove-1" in lab_1_proved.order
    assert lab_entry.read_completion(1, repo).state == "valid"
    assert lab_entry._read_handoff(repo) is not None


def _default_one_in_the_header(repo: Path) -> None:
    path = _seam_file(1, repo)
    path.write_text(
        path.read_text().replace(
            "result_limit integer DEFAULT 50", "result_limit integer DEFAULT 1"
        )
    )
    assert lab_source_is_repaired(1, repo=repo)


@pytest.mark.parametrize("applied", [False, True], ids=["saved", "applied"])
def test_a_header_default_changed_outside_the_block_is_refused_with_the_diff_step(
    repo, lab_1_proved, applied
) -> None:
    """The guide's psql queries pass three arguments and take `result_limit` from the header.

    The served search and the proof pass every argument, so they cannot see DEFAULT 1,
    and the body compare cannot either; only the check outside the block does.
    """
    from scripts import lab_state
    from service.participant_commands import APPLY_SQL, DIFF

    _default_one_in_the_header(repo)
    if applied:
        lab_1_proved.apply_saved_files()

    problem = lab_state.source_problem(1, repo=repo)

    assert problem is not None
    assert "changed outside the marked block" in problem.finding
    assert "result_limit integer DEFAULT 50" in problem.finding
    assert "yours has `result_limit integer DEFAULT 1" in problem.finding
    assert "restore those lines" in problem.next_step
    assert APPLY_SQL in problem.next_step and DIFF not in problem.next_step
    with pytest.raises(lab_entry.LabEntryError) as refused:
        lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)
    assert "changed outside the marked block" in str(refused.value)
    assert "prove-1" not in lab_1_proved.order
    assert lab_entry.read_completion(1, repo).state == "other_sql"


def test_status_next_names_the_line_and_the_apply_step_for_an_edit_outside_the_block(
    repo, lab_1_proved, capsys
) -> None:
    from scripts import lab_state
    from service.participant_commands import APPLY_SQL

    _default_one_in_the_header(repo)
    lab_1_proved.apply_saved_files()

    lab_state._status_next(
        ["Lab 1: APPLIED, NOT YET PROVED", "Lab 2: NOT YET", "Lab 3: NOT YET"], repo
    )

    out = capsys.readouterr().out
    assert "changed outside the marked block" in out
    assert "result_limit integer DEFAULT 50" in out
    assert out.rstrip().splitlines()[-1] == APPLY_SQL
    assert "reset" not in out


def test_comments_and_spacing_outside_the_block_are_allowed(repo, lab_1_proved):
    from scripts import lab_state

    path = _seam_file(1, repo)
    path.write_text(
        path.read_text().replace(
            "    fuzzy_threshold real DEFAULT 0.20",
            "    -- my note\n    fuzzy_threshold   real   DEFAULT 0.20",
        )
    )

    assert lab_state.source_problem(1, repo=repo) is None
    assert lab_entry.read_completion(1, repo).state == "valid"


def test_a_missing_marker_is_a_problem_not_no_problem(repo):
    from scripts import lab_state

    path = _seam_file(1, repo)
    path.write_text(path.read_text().replace("-- LAB1_EDIT_END", ""))

    problem = lab_state.outside_block_problem(1, repo=repo)
    assert problem is not None and "'-- LAB1_EDIT_END' is missing" in problem.finding


def _legacy_receipt_and_handoff(repo: Path) -> None:
    """What f833c76a wrote: no identity, and a hand-off bound to the marked block only."""
    path = lab_entry.completion_path(1, repo)
    receipt = json.loads(path.read_text())
    legacy = {k: receipt[k] for k in ("lab", "passed_at", "checks", "search_event_ids")}
    path.write_text(json.dumps(legacy))
    handoff = repo / ".local/lab-1/handoff.json"
    saved = json.loads(handoff.read_text())
    saved["binding"].pop("lab1_sql", None)
    handoff.write_text(json.dumps(saved))


def test_a_legacy_receipt_still_reads_proved_while_nothing_changed_outside_the_block(
    repo, lab_1_proved
) -> None:
    _legacy_receipt_and_handoff(repo)

    assert lab_entry.read_completion(1, repo).state == "legacy_verified"


def test_a_legacy_receipt_is_not_credited_after_an_applied_edit_outside_the_block(
    repo, lab_1_proved
) -> None:
    _legacy_receipt_and_handoff(repo)
    saved = lab_entry.completion_path(1, repo).read_bytes()
    _limit_one_outside_the_block(repo)
    lab_1_proved.apply_saved_files()

    assert lab_entry.read_completion(1, repo).state == "legacy_unverified"
    assert lab_entry.completion_path(1, repo).read_bytes() == saved


def test_the_applied_body_compare_keeps_capitals_in_dollar_quoted_strings() -> None:
    """`lab_sql_tokens` is case-sensitive, so the compare is too, tagged strings included."""
    from scripts.lab_state import _body_tokens

    saved = "AS $$ SELECT $tag$Sony$tag$, 'A' $$"
    assert _body_tokens(saved) == _body_tokens(saved.replace("-- x", ""))
    assert _body_tokens(saved) != _body_tokens(saved.replace("$tag$Sony", "$tag$SONY"))
    assert _body_tokens(saved) != _body_tokens(saved.replace("'A'", "'a'"))


def test_installed_defaults_that_differ_are_not_credited_until_applied(
    repo, lab_1_proved
) -> None:
    """The edit is undone in the editor, but Aurora still runs DEFAULT 1.

    The guide's three-argument psql queries take `result_limit` from that default; the
    body is the same, so only the parameter compare sees it.
    """
    from scripts import lab_state

    lab_1_proved.installed[1] = (
        _seam_file(1, repo)
        .read_text()
        .replace("result_limit integer DEFAULT 50", "result_limit integer DEFAULT 1")
    )

    assert lab_entry.read_completion(1, repo).state == "valid"
    state = lab_state.read_applied_sql_state(1, lab_1_proved, repo=repo)
    assert state.state == "stale"
    assert "`result_limit` is `integer` default 1" in state.detail
    assert lab_state.applied_sql_state_for_status  # status reads this same state

    lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)

    assert lab_1_proved.order[:1] == ["apply"]
    assert (
        lab_state.read_applied_sql_state(1, lab_1_proved, repo=repo).state == "applied"
    )


def test_postgresql_deparsed_defaults_read_as_the_files(repo, lab_1_proved) -> None:
    """`0.20` on a `real` prints as `'0.2'::real` and `vector(1024)` as `vector`."""
    from scripts import lab_state

    lab_1_proved.installed[1] = (
        _seam_file(1, repo)
        .read_text()
        .replace("vector(1024)", "vector")
        .replace("DEFAULT 0.20", "DEFAULT '0.2'::real")
        .replace("DEFAULT 60", "DEFAULT 60")
    )

    assert (
        lab_state.read_applied_sql_state(1, lab_1_proved, repo=repo).state == "applied"
    )


def test_a_correct_in_block_repair_still_applies_and_a_header_edit_writes_nothing(
    repo, monkeypatch, capsys
) -> None:
    """The guide's apply command: zero writes for an outside edit, a normal apply otherwise."""
    from scripts import apply_search_functions as apply_module

    writes: list[str] = []

    class Recording:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, *args, **kwargs):
            writes.append("execute")

        def cursor(self, *a, **k):
            writes.append("cursor")
            return self

        def commit(self):
            writes.append("commit")

    monkeypatch.setattr(apply_module, "ROOT", repo)
    monkeypatch.setattr(apply_module, "search_sql", lambda _root: "SELECT 1;")
    monkeypatch.setattr(apply_module, "participant_sql_digest", lambda _root: "d")
    monkeypatch.setattr(apply_module, "assert_workshop_database", lambda _d: None)
    monkeypatch.setattr("psycopg.connect", lambda *a, **k: Recording())
    monkeypatch.setattr(apply_module, "apply", lambda *a, **k: writes.append("apply"))
    monkeypatch.setattr(
        "scripts.configure_retrieval_database.configure", lambda _d: None
    )

    _default_one_in_the_header(repo)
    with pytest.raises(SystemExit) as refused:
        apply_module._apply_and_configure()
    assert writes == []
    message = str(refused.value)
    assert (
        "Nothing was applied" in message
        and "result_limit integer DEFAULT 50" in message
    )

    path = _seam_file(1, repo)
    path.write_text(
        path.read_text().replace(
            "result_limit integer DEFAULT 1",
            "-- note\n    result_limit  integer DEFAULT 50",
        )
    )
    apply_module._apply_and_configure()
    assert writes == ["apply"]


class _Recording:
    """A connection that records every write the apply command would make."""

    def __init__(self, writes: list[str]) -> None:
        self.writes = writes

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, *_a, **_k):
        self.writes.append("execute")


@pytest.fixture
def apply_command(repo, monkeypatch):
    from scripts import apply_search_functions as apply_module

    writes: list[str] = []
    monkeypatch.setattr(apply_module, "ROOT", repo)
    monkeypatch.setattr(apply_module, "search_sql", lambda _root: "SELECT 1;")
    monkeypatch.setattr(apply_module, "participant_sql_digest", lambda _root: "d")
    monkeypatch.setattr(apply_module, "assert_workshop_database", lambda _d: None)
    monkeypatch.setattr("psycopg.connect", lambda *a, **k: _Recording(writes))
    monkeypatch.setattr(apply_module, "apply", lambda *a, **k: writes.append("apply"))
    monkeypatch.setattr(
        "scripts.configure_retrieval_database.configure", lambda _d: None
    )
    return apply_module._apply_and_configure, writes


def test_the_guides_paste_between_intact_markers_applies(apply_command, repo) -> None:
    run, writes = apply_command
    set_lab_state(1, solved=True, repo=repo)

    run()

    assert writes == ["apply"]


def test_a_paste_that_crossed_the_end_marker_and_took_the_semantic_branch_writes_nothing(
    apply_command, repo
) -> None:
    """The function is still valid SQL without them, so only the markers show the damage."""
    from service.participant_commands import APPLY_SQL, reset_command

    run, writes = apply_command
    path = _seam_file(1, repo)
    source = path.read_text()
    cut = source.index("-- LAB1_EDIT_END")
    end = source.index("), fused AS (")
    path.write_text(source[:cut] + source[end:])

    with pytest.raises(SystemExit) as refused:
        run()

    message = str(refused.value)
    assert writes == []
    assert "'-- LAB1_EDIT_END' is missing" in message
    assert reset_command(1) in message and "discards your Lab 1 edits" in message
    assert "Nothing was applied" in message
    assert APPLY_SQL in message


def test_an_intact_deliberate_fault_still_applies_and_resets(
    apply_command, repo
) -> None:
    run, writes = apply_command
    set_lab_state(1, solved=False, repo=repo)

    run()

    assert writes == ["apply"]


def test_validate_and_advance_report_the_same_marker_problem(repo, aurora) -> None:
    from scripts import lab_state

    path = _seam_file(1, repo)
    source = path.read_text()
    cut = source.index("-- LAB1_EDIT_END")
    path.write_text(source[:cut] + source[source.index("), fused AS (") :])

    assert (
        "'-- LAB1_EDIT_END' is missing"
        in lab_state.source_problem(1, repo=repo).finding
    )
    with pytest.raises(lab_entry.LabEntryError, match="LAB1_EDIT_END' is missing"):
        lab_entry.advance(1, api_url="http://api", dsn="aurora", repo=repo)


@pytest.fixture
def submitted_sql(monkeypatch) -> list[str]:
    """The SQL the shipped `_apply` would send Aurora, recorded instead of sent."""
    sent: list[str] = []
    monkeypatch.setattr(lab_entry, "_apply", REAL_APPLY)
    monkeypatch.setattr(
        "service.search_sql.search_sql",
        lambda root: "\n".join((root / LABS[lab][0]).read_text() for lab in (1, 2)),
    )
    monkeypatch.setattr(
        "service.lab_validation_receipt.participant_sql_digest", lambda _root: "d"
    )
    monkeypatch.setattr("psycopg.connect", lambda *a, **k: _Recording([]))
    monkeypatch.setattr(
        "scripts.apply_search_functions.apply",
        lambda _connection, source, _digest: sent.append(source),
    )
    monkeypatch.setattr(
        "scripts.configure_retrieval_database.configure", lambda _d: None
    )
    return sent


def test_a_reset_after_a_refused_apply_restores_and_applies_the_whole_starting_file(
    repo, aurora, apply_command, submitted_sql
) -> None:
    """The guide's reset discards an outside-block default as well as the block."""
    from scripts.lab_state import outside_block_problem

    set_lab_state(1, solved=False, repo=repo)
    starting = _seam_file(1, repo).read_bytes()
    lab_2 = _seam_file(2, repo).read_bytes()
    path = _seam_file(1, repo)
    path.write_text(
        path.read_text().replace(
            "result_limit integer DEFAULT 50", "result_limit integer DEFAULT 1"
        )
    )
    run, writes = apply_command
    with pytest.raises(SystemExit):
        run()
    assert writes == []

    said: list[str] = []
    lab_entry.restart(1, api_url="http://api", dsn="aurora", repo=repo, say=said.append)

    assert _seam_file(1, repo).read_bytes() == starting
    assert outside_block_problem(1, repo=repo) is None
    assert _seam_file(2, repo).read_bytes() == lab_2
    assert len(submitted_sql) == 1
    assert "result_limit integer DEFAULT 50" in submitted_sql[0]
    assert "result_limit integer DEFAULT 1," not in submitted_sql[0]
    assert "Discarded your Lab 1 edits." in said


def test_a_lab_1_reset_refused_by_lab_2s_file_keeps_lab_1s_work(
    repo, aurora, submitted_sql
) -> None:
    """Nothing is discarded when the apply that follows the reset would be refused."""
    record = lab_entry.record_path(1, repo)
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("{}")
    lab_1 = _seam_file(1, repo).read_bytes()
    lab_2 = _seam_file(2, repo)
    lab_2.write_text(lab_2.read_text().replace("IMMUTABLE", "VOLATILE", 1))

    with pytest.raises(lab_entry.LabEntryError) as refused:
        lab_entry.restart(1, api_url="http://api", dsn="aurora", repo=repo, say=print)

    message = str(refused.value)
    assert "Lab 2" in message and "IMMUTABLE" in message
    assert "Your Lab 1 edits are unchanged" in message and "Next:" in message
    assert _seam_file(1, repo).read_bytes() == lab_1
    assert record.exists()
    assert submitted_sql == []


def test_every_entry_apply_refuses_sql_changed_outside_a_block(
    repo, submitted_sql
) -> None:
    """Lab 2's start and a hand-off's catch-up apply go through the same guard."""
    _default_one_in_the_header(repo)

    with pytest.raises(lab_entry.LabEntryError) as refused:
        lab_entry._apply("aurora", repo, print)

    message = str(refused.value)
    assert "Nothing was applied" in message and "Next:" in message
    assert submitted_sql == []


def _without(repo: Path, lab: int, marker: str) -> None:
    path = repo / lab_entry.LABS[lab][0]
    path.write_text(path.read_text().replace(marker, "", 1))


def test_a_missing_start_marker_is_a_marker_rule_not_an_index_error(repo):
    start = lab_entry.LABS[1][1][0][0]
    _without(repo, 1, start)
    with pytest.raises(ValueError, match="marker"):
        lab_entry._seam(1, (repo / lab_entry.LABS[1][0]).read_text())


def test_a_lab_1_handoff_never_matches_a_file_without_its_start_marker(
    repo, monkeypatch
):
    monkeypatch.setattr(lab_entry, "_read_handoff", lambda _repo: {"binding": {}})
    _without(repo, 1, lab_entry.LABS[1][1][0][0])
    assert lab_entry._lab_1_handoff_matches(None, repo) is False


def test_installing_a_fault_into_a_file_without_its_markers_names_the_reset(repo):
    _without(repo, 2, lab_entry.LABS[2][1][0][1])
    record = {"version": 1, "lab": 2, "steps": {}}
    with pytest.raises(lab_entry.LabEntryError) as refused:
        lab_entry._install_fault(2, repo, record, lambda _line: None)
    assert "LAB2_EDIT_END' is missing" in str(refused.value)
    assert "lab_state.py reset --lab 2" in str(refused.value)


def test_a_cut_off_saved_request_during_start_names_the_start_again(tmp_path):
    (tmp_path / "before-state.json").write_text('{"run_id": "ab')
    with pytest.raises(lab_entry.LabEntryError) as refused:
        lab_entry._captured_run_id(1, tmp_path)
    message = str(refused.value)
    assert "before-state.json was cut off" in message
    assert "lab_state.py start --lab 1" in message
