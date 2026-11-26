"""Lab 3 completion finds the participant's setup run without a pasted Run ID."""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from scripts import grade_setup_run
from service.agent_deploys import lab_3_started_at as REAL_LAB_3_STARTED_AT
from service.lab_checks import mission_for_lab
from service.participant_commands import (
    ASK_100W_IN_MOSAIC,
    ASK_SETUP_IN_MOSAIC,
    grade_setup_run_command,
)

REQUEST = mission_for_lab(3)["query"]
STARTED = datetime(2026, 10, 25, 10, 0, tzinfo=UTC)


def _run(minutes: int, outcome: str | None, *, question: str = REQUEST) -> dict:
    """One saved turn, `minutes` after Lab 3 started; no outcome means it stopped."""
    return {
        "agent_turn_id": uuid4(),
        "user_message": question,
        "created_at": STARTED + timedelta(minutes=minutes),
        "answered": outcome is not None,
        "turn_number": 1,
        "awaiting_answer": False,
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
    monkeypatch.setattr("service.agent_deploys.deploy_due", lambda *_a, **_k: False)
    monkeypatch.setattr(grade_setup_run, "follow_up_saved", lambda *_a: False)
    graded = []

    def grade(argv: list[str], *, pending_answers=None, run_id=None) -> int:
        graded.append(argv)
        return 0

    monkeypatch.setattr(grade_setup_run.lab_exercise, "main", grade)
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
    _turns(monkeypatch, turns)
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py"])

    assert grade_setup_run.main() == 2

    output = capsys.readouterr().out
    assert said in output and ASK_SETUP_IN_MOSAIC in output
    assert workspace == []


def test_the_picked_run_is_saved_for_the_check(monkeypatch, capsys, workspace) -> None:
    grounded = _run(5, "grounded")
    _turns(monkeypatch, [grounded, _run(8, None)])
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py"])

    assert grade_setup_run.main() == 0

    saved = json.loads((grade_setup_run.ROOT / ".local/lab-3/context.json").read_text())
    assert saved == {"lab_agent_id": str(grounded["agent_turn_id"])}
    assert "1 newer run ended without a grounded answer" in capsys.readouterr().out
    assert len(workspace) == 1


def test_the_saved_run_is_graded_with_a_command_lab_exercise_accepts(
    monkeypatch, workspace
) -> None:
    """The stub above skips lab_exercise's parser; this runs its arguments through it.

    A renamed action (check became grade on 31 October 2026) once crashed Lab 3's last
    step on a fresh event while every test here passed.
    """
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py", "--run-id", str(uuid4())])

    assert grade_setup_run.main() == 0

    args = grade_setup_run.lab_exercise.argument_parser().parse_args(workspace[0])
    assert (args.action, args.lab) == ("grade", 3)


def test_a_named_run_is_checked_without_a_pick(monkeypatch, workspace) -> None:
    named = uuid4()
    monkeypatch.setattr(
        "service.db.connect", lambda: pytest.fail("a named run needs no pick")
    )
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py", "--run-id", str(named)])

    assert grade_setup_run.main() == 0

    saved = json.loads((grade_setup_run.ROOT / ".local/lab-3/context.json").read_text())
    assert saved == {"lab_agent_id": str(named)}


def test_in_progress_setup_waits_before_asking_again(
    monkeypatch, workspace, capsys
) -> None:
    pending = _run(7, None)
    pending.update(awaiting_answer=True)
    _turns(monkeypatch, [pending])
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py"])

    assert grade_setup_run.main() == 2
    out = capsys.readouterr().out
    assert str(pending["agent_turn_id"]) in out and "setup" in out
    assert out.rstrip().endswith("uv run python scripts/grade_setup_run.py")
    assert (
        "Ask Mosaic" not in out
        and "scripts/ask_agent.py" not in out
        and workspace == []
    )


def test_a_100w_run_in_flight_without_a_setup_run_asks_setup_now(
    monkeypatch, workspace, capsys
) -> None:
    """A 100W answer still on its way cannot supply setup, and asking it twice wastes a turn."""
    pending = _run(7, None, question=mission_for_lab(3)["changed_requirement"]["query"])
    pending.update(awaiting_answer=True, turn_number=2)
    _turns(monkeypatch, [pending])
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py"])

    assert grade_setup_run.main() == 2
    out = capsys.readouterr().out
    assert ASK_SETUP_IN_MOSAIC in out
    assert ASK_100W_IN_MOSAIC not in out and workspace == []


def test_later_conversation_turn_cannot_be_the_setup_run():
    later = _run(8, "grounded")
    later["turn_number"] = 2
    first = _run(3, "grounded")
    pick = grade_setup_run.pick_setup_run(_Connection([later, first]), REQUEST, STARTED)

    assert pick.run is first and pick.asked == 1


@pytest.mark.parametrize("pending_kind", ["setup", "100W"])
@pytest.mark.parametrize("missing", [None, "setup", "100W", "both"])
def test_an_extra_pending_attempt_does_not_hide_an_existing_pair(
    missing, pending_kind, monkeypatch, tmp_path, capsys
):
    """Grade the saved answers first. Wait only when the open turn can supply a missing one."""
    follow_up = mission_for_lab(3)["changed_requirement"]["query"]
    pending = _run(8, None, question=REQUEST if pending_kind == "setup" else follow_up)
    pending.update(
        awaiting_answer=True, turn_number=1 if pending_kind == "setup" else 2
    )
    _turns(
        monkeypatch,
        [_run(4, "grounded"), _run(5, "grounded", question=follow_up), pending],
    )
    monkeypatch.setattr(grade_setup_run, "ROOT", tmp_path)
    monkeypatch.setattr(grade_setup_run, "load_dotenv", lambda _: None)
    monkeypatch.setattr("service.agent_deploys.lab_3_started_at", lambda _: STARTED)
    monkeypatch.setattr(grade_setup_run.lab_exercise, "REPO", tmp_path)
    work = tmp_path / "agent.py"
    work.write_text("# participant agent")
    monkeypatch.setattr(grade_setup_run.lab_exercise, "default_work", lambda _: work)
    needs = {
        "deploy": False,
        "setup": missing in ("setup", "both"),
        "follow_up": missing in ("100W", "both"),
    }
    monkeypatch.setattr(
        grade_setup_run.lab_exercise,
        "grade",
        lambda *_: {
            "failures": [f"needs {missing}"] if missing else [],
            "needs": needs,
        },
    )
    monkeypatch.setattr(grade_setup_run.lab_exercise, "_print_lab3", lambda _: None)
    monkeypatch.setattr(
        grade_setup_run.lab_exercise, "record_decision", lambda *_: None
    )
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py"])

    result = grade_setup_run.main()
    output = capsys.readouterr().out
    receipt = tmp_path / ".local/lab-3/exercise-receipt.json"
    if missing in (pending_kind, "both"):
        assert result == 2 and not receipt.exists()
        assert str(pending["agent_turn_id"]) in output
        assert "Ask Mosaic" not in output and "ask_agent.py" not in output
    else:
        assert result == (1 if missing else 0) and receipt.exists()
        assert str(pending["agent_turn_id"]) not in output


def test_an_unreachable_aurora_is_reported_without_a_traceback(
    monkeypatch, capsys, workspace
) -> None:
    import psycopg

    @contextmanager
    def connect():
        raise psycopg.errors.ConnectionTimeout("connection timeout expired")
        yield

    monkeypatch.setattr("service.db.connect", connect)
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py"])

    assert grade_setup_run.main() == 2

    out = capsys.readouterr().out
    assert out.startswith("Lab 3 exercise: CANNOT GRADE - Aurora did not answer")
    assert "OperationalError" not in out and "Traceback" not in out
    assert workspace == []


def test_the_saved_context_keeps_what_lab_request_saved(tmp_path) -> None:
    """`lab_request.py` saves more keys in the same files; naming the run must keep them."""
    output = tmp_path / ".local/lab-3"
    output.mkdir(parents=True)
    earlier = str(uuid4())
    (output / "context.json").write_text(
        json.dumps({"lab_agent_id": earlier, "lab_before_agent_id": earlier}) + "\n"
    )
    chosen = str(uuid4())

    grade_setup_run.save_context(output, chosen)

    values = json.loads((output / "context.json").read_text())
    assert values == {"lab_agent_id": chosen, "lab_before_agent_id": earlier}
    psql = (output / "context.psql").read_text()
    assert "AS lab_agent_id" in psql and "AS lab_before_agent_id" in psql
    assert not list(output.glob("*.tmp"))


def test_a_cut_off_context_file_is_replaced_not_crashed_on(tmp_path) -> None:
    output = tmp_path / ".local/lab-3"
    output.mkdir(parents=True)
    (output / "context.json").write_text('{"lab_agent_id": "abc')
    chosen = str(uuid4())

    grade_setup_run.save_context(output, chosen)

    assert json.loads((output / "context.json").read_text()) == {"lab_agent_id": chosen}


@pytest.mark.parametrize("follow_up_saved", [False, True])
def test_no_checkable_run_ends_with_asking_what_is_missing_then_checking(
    monkeypatch, capsys, workspace, follow_up_saved
) -> None:
    """A 100W answer already saved from the deployed code is not asked for again."""
    _turns(monkeypatch, [])
    monkeypatch.setattr(grade_setup_run, "follow_up_saved", lambda *_a: follow_up_saved)
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py"])

    assert grade_setup_run.main() == 2

    out = capsys.readouterr().out
    assert not out.startswith("\n") and "\n\n\n" not in out
    follow_up = "" if follow_up_saved else f"Then {ASK_100W_IN_MOSAIC}\n"
    assert out.endswith(
        f"\n\nNext: {ASK_SETUP_IN_MOSAIC}\n{follow_up}"
        f"Return to Code Editor and check completion:\n{grade_setup_run_command()}\n"
    )
    assert "ask_agent.py" not in out


def test_an_unreachable_aurora_ends_with_opening_a_new_terminal(
    monkeypatch, capsys, workspace
) -> None:
    import psycopg

    from service.participant_commands import grade_setup_run_command

    @contextmanager
    def connect():
        raise psycopg.errors.ConnectionTimeout("connection timeout expired")
        yield

    monkeypatch.setattr("service.db.connect", connect)
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py"])

    grade_setup_run.main()

    out = capsys.readouterr().out
    assert "Next:" not in out.split("\n\n")[0]
    assert out.endswith(f"tell your facilitator:\n{grade_setup_run_command()}\n")


def test_the_verdict_comes_before_the_next_step(monkeypatch, capsys, tmp_path) -> None:
    """The pick, the verdict and the step after it are separate parts, in that order."""
    from scripts import lab_exercise

    monkeypatch.setattr(grade_setup_run, "ROOT", tmp_path)
    monkeypatch.setattr(grade_setup_run, "load_dotenv", lambda _path: None)
    monkeypatch.setattr(
        "service.agent_deploys.lab_3_started_at", lambda _root=None: STARTED
    )
    monkeypatch.setattr(lab_exercise, "REPO", tmp_path)
    monkeypatch.setattr(lab_exercise, "grade", lambda *_: {"failures": []})
    monkeypatch.setattr(lab_exercise, "record_decision", lambda *_: None)
    monkeypatch.setattr(
        lab_exercise, "default_work", lambda _lab: tmp_path / "agent.py"
    )
    (tmp_path / "agent.py").write_text("agent")
    _turns(monkeypatch, [_run(5, "grounded")])
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py"])

    assert grade_setup_run.main() == 0

    parts = capsys.readouterr().out.rstrip("\n").split("\n\n")
    assert parts[0].startswith("Checking your newest setup run, ")
    assert parts[1].startswith("Your Retrieval agent is live")
    assert parts[2].startswith("Lab 3 exercise: PASS")
    assert (
        parts[3]
        == "Next: start a new conversation in Ask Mosaic and try a shopping question of your own."
    )
    assert len(parts) == 4


DAMAGED_STARTS = [
    "{",
    '{"version": 1, "lab": 2, "steps": {}}',
    '{"version": 7, "lab": 3, "steps": {}}',
    '{"version": 1, "lab": 3, "steps": {}, "completed_at": "soon"}',
    "[]",
]


@pytest.mark.parametrize("named", [False, True], ids=["newest run", "--run-id"])
@pytest.mark.parametrize("record", DAMAGED_STARTS)
def test_a_damaged_lab_3_start_record_names_the_reset_that_keeps_the_agent(
    monkeypatch, capsys, workspace, tmp_path, record, named
) -> None:
    """Cut off, another lab's, another version's, an unreadable time: one fix for all."""
    started = tmp_path / ".local" / "lab-3" / "start.json"
    started.parent.mkdir(parents=True)
    started.write_text(record)
    monkeypatch.setattr("service.agent_deploys.lab_3_started_at", REAL_LAB_3_STARTED_AT)
    argv = ["grade_setup_run.py"] + (["--run-id", str(uuid4())] if named else [])
    monkeypatch.setattr(sys, "argv", argv)

    assert grade_setup_run.main() == 2

    out = capsys.readouterr().out
    assert out.startswith("Lab 3 exercise: CANNOT GRADE - Lab 3 start record rule")
    assert out.count("Next:") == 1 and max(map(len, out.splitlines())) <= 120
    assert out.rstrip().endswith(
        "uv run python scripts/deploy_agentcore.py deploy\nThen ask both Lab 3 questions again."
    )
    assert "lab_state.py reset --lab 3" in out and workspace == []
    # The reset restores the starting agent.py, so the fix saves the participant's first.
    saved, reset = (
        out.index("cp labs/lab3_reason/agent.py ~/my-agent.py"),
        out.index("reset --lab 3"),
    )
    assert saved < reset < out.index("cp ~/my-agent.py labs/lab3_reason/agent.py")


@pytest.fixture
def proof(monkeypatch, tmp_path):
    """The real grade after the pick, with the proof and decision record faked.

    Returns the Run IDs the proof was asked for, in order.
    """
    from types import SimpleNamespace

    from scripts import lab_exercise

    monkeypatch.setattr(grade_setup_run, "ROOT", tmp_path)
    monkeypatch.setattr(grade_setup_run, "load_dotenv", lambda _path: None)
    monkeypatch.setattr(
        "service.agent_deploys.lab_3_started_at", lambda _root=None: STARTED
    )
    monkeypatch.setattr("service.agent_deploys.deploy_due", lambda *_a, **_k: False)
    monkeypatch.setattr(grade_setup_run, "follow_up_saved", lambda *_a: False)
    monkeypatch.setattr(lab_exercise, "REPO", tmp_path)
    work = tmp_path / "agent.py"
    work.write_text("# participant agent")
    monkeypatch.setattr(lab_exercise, "default_work", lambda _lab: work)
    monkeypatch.setattr(lab_exercise.lab_state, "lab3_problem", lambda: None)
    monkeypatch.setattr("service.agentcore_transport.runtime_arn", lambda: "arn")
    monkeypatch.setattr(lab_exercise, "record_decision", lambda *_: None)
    asked: list[str] = []

    def completion_proof(lab, *, agent_run_id):
        asked.append(str(agent_run_id))
        return SimpleNamespace(checks=[], status="pass")

    monkeypatch.setattr("service.lab_proof.completion_proof", completion_proof)
    return asked


def test_a_second_grade_saving_its_run_meanwhile_does_not_change_this_ones(
    monkeypatch, capsys, proof
) -> None:
    """Another terminal can rewrite the saved context between this pick and its proof."""
    mine, theirs = uuid4(), uuid4()
    save = grade_setup_run.save_context

    def save_then_theirs(output, run_id):
        save(output, run_id)
        save(output, str(theirs))

    monkeypatch.setattr(grade_setup_run, "save_context", save_then_theirs)
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py", "--run-id", str(mine)])

    assert grade_setup_run.main() == 0

    assert proof == [str(mine)]
    receipt = json.loads(
        (grade_setup_run.ROOT / ".local/lab-3/exercise-receipt.json").read_text()
    )
    assert receipt["agent_run_id"] == str(mine)


@pytest.mark.parametrize("failure", ["timeout", "throttled"])
def test_a_bedrock_call_that_fails_during_the_grade_names_a_retry_without_a_traceback(
    monkeypatch, capsys, proof, failure
) -> None:
    from botocore.exceptions import ClientError

    from service.bedrock import search_timeout_message
    from service.model_runtime import BedrockTimeoutError
    from service.participant_commands import grade_setup_run_command

    picked = _run(5, "grounded")
    _turns(monkeypatch, [picked])

    def bedrock_failed(lab, *, agent_run_id):
        if failure == "timeout":
            raise BedrockTimeoutError(search_timeout_message("query embedding"))
        raise ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "slow down"}},
            "InvokeModel",
        )

    monkeypatch.setattr("service.lab_proof.completion_proof", bedrock_failed)
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py"])

    assert grade_setup_run.main() == 2

    out = capsys.readouterr().out
    assert "Traceback" not in out
    assert "Lab 3 exercise: CANNOT GRADE - Amazon Bedrock did not answer" in out
    assert ("ThrottlingException" in out) == (failure == "throttled")
    assert "Nothing is wrong with your run" in out
    assert out.endswith(grade_setup_run_command(str(picked["agent_turn_id"])) + "\n")
    assert not (grade_setup_run.ROOT / ".local/lab-3/exercise-receipt.json").exists()


@pytest.mark.parametrize("named", [True, False])
def test_aurora_timing_out_after_the_pick_names_a_retry_of_that_run(
    monkeypatch, capsys, proof, named
) -> None:
    from psycopg_pool import PoolTimeout

    from service.participant_commands import grade_setup_run_command

    picked = _run(5, "grounded")
    _turns(monkeypatch, [picked])

    def timed_out(lab, *, agent_run_id):
        raise PoolTimeout("couldn't get a connection after 30.00 sec")

    monkeypatch.setattr("service.lab_proof.completion_proof", timed_out)
    argv = ["grade_setup_run.py"]
    if named:
        argv += ["--run-id", str(picked["agent_turn_id"])]
    monkeypatch.setattr(sys, "argv", argv)

    assert grade_setup_run.main() == 2

    out = capsys.readouterr().out
    assert "Lab 3 exercise: CANNOT GRADE - Aurora did not answer (timed out)." in out
    assert "Traceback" not in out and "tell your facilitator" in out
    assert out.endswith(grade_setup_run_command(str(picked["agent_turn_id"])) + "\n")
    assert not (grade_setup_run.ROOT / ".local/lab-3/exercise-receipt.json").exists()


def test_a_decision_aurora_cannot_save_prints_no_verdict(
    monkeypatch, capsys, proof
) -> None:
    """The grade's verdict prints only once its record is saved, never beside a failure."""
    import psycopg

    from scripts import lab_exercise

    def refused(*_args):
        raise psycopg.errors.ConnectionTimeout("connection timeout expired")

    monkeypatch.setattr(lab_exercise, "record_decision", refused)
    named = uuid4()
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py", "--run-id", str(named)])

    assert grade_setup_run.main() == 2

    out = capsys.readouterr().out
    assert "PASS" not in out and "Your Retrieval agent is live" not in out
    assert "CANNOT GRADE - Aurora did not answer (timed out)." in out
    assert not (grade_setup_run.ROOT / ".local/lab-3/exercise-receipt.json").exists()


def test_an_empty_database_setting_names_the_prepared_terminal(
    monkeypatch, capsys, workspace
) -> None:
    from service.db import DatabaseNotConfigured

    @contextmanager
    def connect():
        raise DatabaseNotConfigured("DATABASE_URL is not configured")
        yield

    monkeypatch.setattr("service.db.connect", connect)
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py"])

    assert grade_setup_run.main() == 2

    out = capsys.readouterr().out
    assert out.startswith(
        "Lab 3 exercise: CANNOT GRADE - DATABASE_URL is empty in this terminal"
    )
    assert "open a new terminal from the Terminal menu" in out and workspace == []


def test_a_grade_before_lab_3_starts_names_the_start_not_the_questions(
    monkeypatch, capsys, workspace
) -> None:
    """Before the start the shipped reference agent answers, so no run would count."""
    from scripts.lab_entry import entry_command

    monkeypatch.setattr(
        "service.agent_deploys.lab_3_started_at", lambda _root=None: None
    )
    _turns(monkeypatch, [_run(5, "grounded")])
    monkeypatch.setattr(sys, "argv", ["grade_setup_run.py"])

    assert grade_setup_run.main() == 2

    out = capsys.readouterr().out
    assert out.startswith("Lab 3 exercise: CANNOT GRADE - Lab 3 has not started")
    assert entry_command(3, grade_setup_run.ROOT) in out
    assert ASK_SETUP_IN_MOSAIC not in out
    assert workspace == []
