"""Lab 3 completion finds the participant's setup run without a pasted Run ID."""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from scripts import grade_setup_run
from service.lab_checks import mission_for_lab

REQUEST = mission_for_lab(3)["query"]
STARTED = datetime(2026, 10, 25, 10, 0, tzinfo=UTC)


def _run(minutes: int, outcome: str | None, *, question: str = REQUEST) -> dict:
    """One saved turn, `minutes` after Lab 3 started; no outcome means it stopped."""
    return {
        "agent_turn_id": uuid4(),
        "user_message": question,
        "created_at": STARTED + timedelta(minutes=minutes),
        "answered": outcome is not None,
        "outcome": outcome,
    }


class _Connection:
    """Answers the picker's one query with turns, newest first, as Aurora orders them."""

    def __init__(self, turns: list[dict]) -> None:
        self.turns = sorted(turns, key=lambda turn: turn["created_at"], reverse=True)
        self.params: dict = {}

    def execute(self, _sql: str, params: dict):
        self.params = params
        return self

    def fetchall(self) -> list[dict]:
        return self.turns


def test_the_newest_grounded_setup_run_is_checked() -> None:
    earlier, newest = _run(5, "grounded"), _run(9, "grounded")
    connection = _Connection([earlier, newest, _run(12, "grounded", question="100W?")])

    pick = grade_setup_run.pick_setup_run(connection, REQUEST, STARTED)

    assert pick.run is newest and pick.skipped == []
    assert connection.params["started"] == STARTED
    assert grade_setup_run._choice(pick).startswith("Checking your newest setup run,")


def test_a_stopped_or_declined_retry_does_not_hide_an_earlier_grounded_run() -> None:
    """A run is saved as it starts, so a retry that hit HTTP 503 is the newest run."""
    grounded = _run(5, "grounded")
    connection = _Connection([grounded, _run(8, "declined"), _run(11, None)])

    pick = grade_setup_run.pick_setup_run(connection, REQUEST, STARTED)

    assert pick.run is grounded and len(pick.skipped) == 2
    choice = grade_setup_run._choice(pick)
    assert f"newest grounded setup run, {grounded['agent_turn_id']}" in choice
    assert (
        "asked at 10:05:00 UTC; 2 newer runs ended without a grounded answer" in choice
    )


def test_without_a_grounded_run_the_newest_answered_one_is_checked() -> None:
    """A declined run is graded, so the participant reads why it cannot pass."""
    declined = _run(6, "declined")
    connection = _Connection([_run(2, "declined"), declined, _run(9, None)])

    pick = grade_setup_run.pick_setup_run(connection, REQUEST, STARTED)

    assert pick.run is declined
    assert "with an answer" in grade_setup_run._choice(pick)
    assert "1 newer run stopped without one" in grade_setup_run._choice(pick)


def test_the_request_matches_whatever_its_case_and_spacing() -> None:
    respaced = _run(4, "grounded", question="  " + REQUEST.upper().replace(" ", "  "))
    pick = grade_setup_run.pick_setup_run(_Connection([respaced]), REQUEST, STARTED)
    assert pick.run is respaced


@pytest.fixture
def workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(grade_setup_run, "ROOT", tmp_path)
    monkeypatch.setattr(grade_setup_run, "load_dotenv", lambda _path: None)
    monkeypatch.setattr(
        "service.agent_deploys.lab_3_started_at", lambda _root=None: STARTED
    )
    graded = []
    monkeypatch.setattr(
        grade_setup_run.lab_exercise, "main", lambda: graded.append(1) or 0
    )
    return graded


def _turns(monkeypatch, turns: list[dict]) -> None:
    @contextmanager
    def connect():
        yield _Connection(turns)

    monkeypatch.setattr("service.db.connect", connect)


@pytest.mark.parametrize(
    ("turns", "said"),
    [
        ([], "found no run of Alex's setup request since Lab 3 started at 10:00 UTC"),
        (
            [_run(3, None), _run(7, None)],
            (
                "your 2 run(s) of Alex's setup request since Lab 3 started at 10:00 UTC "
                "all stopped without an answer"
            ),
        ),
    ],
)
def test_no_checkable_setup_run_says_how_to_make_one(
    monkeypatch, capsys, workspace, turns, said
) -> None:
    from service.participant_commands import ask_setup_command

    _turns(monkeypatch, turns)
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py"])

    assert grade_setup_run.main() == 2

    output = capsys.readouterr().out
    assert said in output and ask_setup_command() in output
    assert workspace == []


def test_the_picked_run_is_saved_for_the_check(monkeypatch, capsys, workspace) -> None:
    grounded = _run(5, "grounded")
    _turns(monkeypatch, [grounded, _run(8, None)])
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py"])

    assert grade_setup_run.main() == 0

    saved = json.loads((grade_setup_run.ROOT / ".local/lab-3/context.json").read_text())
    assert saved == {"lab_agent_id": str(grounded["agent_turn_id"])}
    assert "1 newer run ended without a grounded answer" in capsys.readouterr().out
    assert workspace == [1]


def test_a_named_run_is_checked_without_a_pick(monkeypatch, workspace) -> None:
    named = uuid4()
    monkeypatch.setattr(
        "service.db.connect", lambda: pytest.fail("a named run needs no pick")
    )
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py", "--run-id", str(named)])

    assert grade_setup_run.main() == 0

    saved = json.loads((grade_setup_run.ROOT / ".local/lab-3/context.json").read_text())
    assert saved == {"lab_agent_id": str(named)}
