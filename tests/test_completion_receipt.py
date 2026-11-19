"""A SQL lab reads SOLVED only while its receipt matches this attempt and this saved SQL.

Aurora is the one boundary substituted: the applied-state read. The receipt, the start
records, the lab files and the status text run as shipped, on a copy of the checkout.
"""

from __future__ import annotations

import json
from pathlib import Path
from shutil import copy2

import pytest

from scripts import lab_entry, lab_state
from scripts.lab_entry import completion_path, read_completion, record_path
from scripts.lab_state import (
    LABS,
    REPO,
    LabDatabaseState,
    _replace_block,
    status_line,
)
from scripts.prove_lab import record_completion

LAB_1_OWN_WORDING = (
    "SELECT product_id, 'fuzzy'::text AS channel, fuzzy_rank AS source_rank,"
)
LAB_2_OTHER_EXPRESSION = "SELECT 1.0 / (rrf_k + source_rank)"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for relative_path in {definition[0] for definition in LABS.values()}:
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy2(REPO / relative_path, destination)
    monkeypatch.setattr(
        lab_state,
        "applied_sql_state_for_status",
        lambda lab, repo: LabDatabaseState(state="applied", detail="runs"),
    )
    return tmp_path


def _start(repo: Path, lab: int, at: str = "2026-11-19T10:00:00+00:00") -> None:
    path = record_path(lab, repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "lab": lab, "steps": {}, "completed_at": at})
    )


def _prove(repo: Path, lab: int) -> Path:
    return record_completion(lab, ["target found"], [f"event-{lab}"], repo)


def _edit_lab_1(repo: Path, wording: str = LAB_1_OWN_WORDING) -> None:
    path = repo / LABS[1][0]
    path.write_text(
        path.read_text().replace("SELECT product_id, 'fuzzy', fuzzy_rank,", wording)
    )
    assert lab_state.lab_source_is_repaired(1, repo=repo)


def _edit_lab_2(repo: Path, expression: str = LAB_2_OTHER_EXPRESSION) -> None:
    path = repo / LABS[2][0]
    start, end, _, _ = LABS[2][1][0]
    path.write_text(_replace_block(path.read_text(), start, end, expression))
    assert lab_state.lab_source_is_repaired(2, repo=repo)


def test_a_receipt_from_a_passing_proof_reads_solved(repo: Path) -> None:
    _prove(repo, 1)

    assert read_completion(1, repo).state == "valid"
    assert status_line(1, repo=repo) == "Lab 1: SOLVED"


def _receipt_text(**changes: object) -> str:
    receipt: dict[str, object] = {
        "lab": 1,
        "passed_at": "2026-11-19T10:00:00+00:00",
        "checks": ["a"],
        "search_event_ids": ["e"],
    }
    receipt.update(changes)
    return json.dumps(receipt)


@pytest.mark.parametrize(
    "damage",
    [
        "",
        "{",
        _receipt_text()[:-12],
        "[]",
        "{}",
        _receipt_text(passed_at="later"),
        _receipt_text(checks=[]),
        _receipt_text(lab=2),
        _receipt_text(sql_sha256="abc"),
    ],
    ids=[
        "empty",
        "truncated-object",
        "truncated-mid-list",
        "list",
        "no-fields",
        "bad-time",
        "no-checks",
        "other-lab",
        "half-identity",
    ],
)
def test_an_empty_or_damaged_receipt_does_not_read_solved_and_is_kept(
    repo: Path, damage: str
) -> None:
    path = completion_path(1, repo)
    path.parent.mkdir(parents=True)
    path.write_text(damage)

    assert read_completion(1, repo).state == "unreadable"
    assert status_line(1, repo=repo) == "Lab 1: APPLIED, NOT YET PROVED"
    assert path.read_text() == damage


def test_a_receipt_from_an_earlier_attempt_does_not_count(repo: Path) -> None:
    _start(repo, 2, "2026-11-19T10:00:00+00:00")
    _prove(repo, 2)
    assert status_line(2, repo=repo) == "Lab 2: SOLVED"

    # reset --lab 2, then start again: a new attempt, with this receipt left behind
    _start(repo, 2, "2026-11-19T11:30:00+00:00")

    assert read_completion(2, repo).state == "other_attempt"
    assert status_line(2, repo=repo) == "Lab 2: APPLIED, NOT YET PROVED"


@pytest.mark.parametrize("lab", [1, 2])
def test_a_different_valid_edit_after_proof_reads_not_yet_proved(
    repo: Path, lab: int
) -> None:
    if lab == 2:
        _start(repo, 2)
    _prove(repo, lab)
    assert status_line(lab, repo=repo) == f"Lab {lab}: SOLVED"

    (_edit_lab_1 if lab == 1 else _edit_lab_2)(repo)

    assert read_completion(lab, repo).state == "other_sql"
    assert status_line(lab, repo=repo) == f"Lab {lab}: APPLIED, NOT YET PROVED"


def test_a_comment_or_spacing_edit_after_proof_keeps_the_proof(repo: Path) -> None:
    _prove(repo, 1)
    path = repo / LABS[1][0]
    path.write_text(
        path.read_text()
        .replace("-- LAB1_EDIT_START\n", "-- LAB1_EDIT_START\n-- a note of mine\n", 1)
        .replace(
            "    UNION ALL\n    SELECT product_id, 'fuzzy'",
            "\n    UNION ALL\n    SELECT product_id,   'fuzzy'",
            1,
        )
    )

    assert status_line(1, repo=repo) == "Lab 1: SOLVED"


def test_the_other_labs_file_does_not_change_a_labs_proof(repo: Path) -> None:
    """Starting Lab 2 and then editing or breaking it leaves Lab 1's proof alone."""
    _prove(repo, 1)
    _start(repo, 2)
    set_broken = lab_state.set_lab_state
    set_broken(2, solved=False, repo=repo)
    assert status_line(1, repo=repo) == "Lab 1: SOLVED"

    _edit_lab_2(repo)
    assert status_line(1, repo=repo) == "Lab 1: SOLVED"


def test_starting_lab_2_directly_does_not_manufacture_lab_1_proof(repo: Path) -> None:
    _start(repo, 2)

    assert not completion_path(1, repo).exists()
    assert status_line(1, repo=repo) == "Lab 1: APPLIED, NOT YET PROVED"


def _legacy_lab_1(repo: Path, events: list[str]) -> tuple[Path, bytes]:
    """The receipt f833c76a wrote: no attempt and no SQL named."""
    path = completion_path(1, repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "lab": 1,
                "passed_at": "2026-11-19T10:00:00+00:00",
                "checks": ["target found"],
                "search_event_ids": events,
            },
            indent=2,
        )
        + "\n"
    )
    return path, path.read_bytes()


def _legacy_handoff(repo: Path, events: list[str], *, edited: bool = False) -> None:
    saved_seam = lab_entry._seam_sha256(1, (repo / LABS[1][0]).read_text())
    if edited:
        saved_seam = "0" * 64
    path = repo / ".local/lab-1/handoff.json"
    path.write_text(
        json.dumps(
            {
                "binding": {
                    "database": "db",
                    "lab1_seam": saved_seam,
                    "lab1_entry": lab_entry.load_record(1, repo),
                },
                "checks": ["target found"],
                "search_event_ids": events,
            }
        )
    )


def test_a_legacy_receipt_the_handoff_vouches_for_still_reads_solved(
    repo: Path,
) -> None:
    path, saved = _legacy_lab_1(repo, ["event-1"])
    _legacy_handoff(repo, ["event-1"])

    assert read_completion(1, repo).state == "legacy_verified"
    assert status_line(1, repo=repo) == "Lab 1: SOLVED"
    assert path.read_bytes() == saved


@pytest.mark.parametrize("handoff", ["missing", "other_block", "other_events"])
def test_a_legacy_receipt_that_cannot_be_verified_is_kept_and_asks_for_proof(
    repo: Path, handoff: str
) -> None:
    path, saved = _legacy_lab_1(repo, ["event-1"])
    if handoff == "other_block":
        _legacy_handoff(repo, ["event-1"], edited=True)
    elif handoff == "other_events":
        _legacy_handoff(repo, ["event-9"])

    assert read_completion(1, repo).state == "legacy_unverified"
    assert status_line(1, repo=repo) == "Lab 1: APPLIED, NOT YET PROVED"
    assert path.read_bytes() == saved


def test_a_legacy_lab_2_receipt_cannot_be_verified_offline(repo: Path) -> None:
    _start(repo, 2)
    path = completion_path(2, repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "lab": 2,
                "passed_at": "2026-11-19T10:00:00+00:00",
                "checks": ["contribution correct"],
                "search_event_ids": ["a", "b"],
            }
        )
    )

    assert status_line(2, repo=repo) == "Lab 2: APPLIED, NOT YET PROVED"
    assert read_completion(2, repo).receipt["search_event_ids"] == ["a", "b"]


def test_the_proof_message_under_lab_2s_fault_survives_an_empty_receipt(
    repo: Path,
) -> None:
    """`prove_lab` read the receipt with json.loads and indexed it: an empty file crashed it."""
    from scripts.prove_lab import _under_ranking_fault

    path = completion_path(1, repo)
    path.parent.mkdir(parents=True)
    path.write_text("")

    message = _under_ranking_fault("target missing; fix: x", repo)

    assert "No valid saved Lab 1 completion was found" in message
    assert "Next: finish Lab 2, then run this check again." in message


def test_the_proof_message_quotes_only_a_receipt_that_matches(repo: Path) -> None:
    from scripts.prove_lab import _under_ranking_fault

    _prove(repo, 1)
    assert "Lab 1 passed at" in _under_ranking_fault("target missing", repo)

    _edit_lab_1(repo)
    assert "Lab 1 passed at" not in _under_ranking_fault("target missing", repo)


def test_the_receipt_is_bound_before_the_proof_so_a_late_edit_is_not_credited(
    repo: Path,
) -> None:
    binding = lab_entry.completion_binding(1, repo)
    _edit_lab_1(repo)

    record_completion(1, ["target found"], ["event-1"], repo, binding)

    assert read_completion(1, repo).state == "other_sql"


@pytest.mark.parametrize("lab_2_state", ["stale", "applied"])
def test_status_names_the_lab_2_guide_first_when_lab_2_started_before_lab_1_was_proved(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys, lab_2_state: str
) -> None:
    """`advance --lab 1` refuses while Lab 2's fault can hide Lab 1, so status says so first."""
    from contextlib import contextmanager

    from service.participant_commands import ADVANCE_TO_LAB_2, repeat_request_command

    @contextmanager
    def connect(_dsn):
        yield object()

    def applied(lab, _connection, **_kwargs):
        return LabDatabaseState(state="applied" if lab == 1 else lab_2_state, detail="")

    monkeypatch.setattr(lab_entry, "_connect", connect)
    monkeypatch.setattr(lab_entry, "read_applied_sql_state", applied)
    monkeypatch.setenv("DATABASE_URL", "aurora")
    _start(repo, 2)
    lines = [status_line(1, repo=repo), "Lab 2: NOT YET", "Lab 3: NOT YET"]
    assert lines[0] == "Lab 1: APPLIED, NOT YET PROVED"

    lab_state._status_next(lines, repo)
    out = capsys.readouterr().out

    assert ADVANCE_TO_LAB_2 in out
    if lab_2_state == "stale":
        assert "Continue in the Lab 2 guide" in out
        assert repeat_request_command(1) not in out
    else:
        assert "Continue in the Lab 2 guide" not in out
        assert repeat_request_command(1) in out
