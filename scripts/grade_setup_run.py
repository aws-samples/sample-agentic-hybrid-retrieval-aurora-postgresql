"""Grade the participant's Lab 3 setup run and the deployed Retrieval agent.

    uv run python scripts/grade_setup_run.py
    uv run python scripts/grade_setup_run.py --run-id RUN_ID

Without --run-id it grades a run of Alex's setup request since Lab 3 started that
opened its own conversation, from the terminal, Playground or Ask Mosaic: the newest
grounded one, else the newest that answered. It says which run it chose and how many
newer runs it passed over, such as a retry that stopped on HTTP 503.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg
from dotenv import load_dotenv

from scripts import lab_exercise
from scripts.lab_request import sql_context
from scripts.terminal_text import next_step, tidy, verdict
from service.config import get_settings
from service.lab_followup import follow_up_saved
from service.participant_commands import grade_setup_run_command, lab3_steps

# Runs are compared in Python, with the completion check's own rule for "the same
# request"; a participant asks a handful, so a bounded window holds them all.
RECENT_RUNS = 200


@dataclass(frozen=True)
class SetupRunPick:
    """The setup run to check, the newer setup runs passed over, and all of them."""

    run: dict[str, Any] | None
    skipped: list[dict[str, Any]] = field(default_factory=list)
    asked: int = 0
    pending_answers: dict[str, str] = field(default_factory=dict)


def pick_setup_run(
    connection: Any, request: str, started_at: datetime | None, *, follow_up: str = ""
) -> SetupRunPick:
    """Choose the setup run completion should check.

    A run is saved when it starts, so a retry that stopped on HTTP 503 or the time
    limit is a newer run with no answer, and a declined retry is a newer run that
    cannot pass. Either would hide an earlier grounded run, so the newest grounded
    run wins, then the newest run that answered at all.

    Args:
        connection: An open connection with a dictionary row factory.
        request: Alex's setup request, as the Lab 3 mission words it.
        started_at: When Lab 3 last started; earlier runs answered from the
            reference Retrieval agent, so they never count.
        follow_up: The required follow-up, which can be a later conversation turn.
    """
    from service.lab_checks import same_request

    rows = connection.execute(
        """
        SELECT agent_turn_id, turn_number, user_message, created_at,
               assistant_message IS NOT NULL AS answered,
               extracted_intent ->> 'outcome' AS outcome,
               assistant_message IS NULL
                 AND coalesce(extracted_intent #>> '{telemetry,status}', 'active') = 'active'
                 AND created_at > now() - make_interval(secs => %(deadline)s)
                 AS awaiting_answer
        FROM mosaic.agent_turn
        WHERE (%(started)s::timestamptz IS NULL OR created_at > %(started)s::timestamptz)
        ORDER BY created_at DESC
        LIMIT %(limit)s
        """,
        {
            "started": started_at,
            "limit": RECENT_RUNS,
            "deadline": get_settings().agent_turn_deadline_seconds,
        },
    ).fetchall()
    setup = [
        row
        for row in rows
        if row["turn_number"] == 1 and same_request(request, row["user_message"])
    ]
    run = next((row for row in setup if row["outcome"] == "grounded"), None) or next(
        (row for row in setup if row["answered"]), None
    )
    skipped = setup[: setup.index(run)] if run is not None else setup
    latest_follow_up = next(
        (row for row in rows if same_request(follow_up, row["user_message"])), None
    )
    pending = {
        kind: str(row["agent_turn_id"])
        for kind, row in (
            ("setup", next(iter(setup), None)),
            ("follow_up", latest_follow_up),
        )
        if row and row["awaiting_answer"]
    }
    return SetupRunPick(run, skipped, len(setup), pending)


def _choice(pick: SetupRunPick) -> str:
    run = pick.run or {}
    asked = f"{run['created_at'].astimezone(UTC):%H:%M:%S} UTC"
    if not pick.skipped:
        return (
            f"Checking your newest setup run, {run['agent_turn_id']}, asked at {asked}."
        )
    newer = len(pick.skipped)
    runs = "run" if newer == 1 else "runs"
    if any(row["awaiting_answer"] for row in pick.skipped):
        return (
            f"Checking saved setup run {run['agent_turn_id']}, asked at {asked}. "
            "A newer attempt is still awaiting an answer."
        )
    if run["outcome"] == "grounded":
        return (
            f"Checking your newest grounded setup run, {run['agent_turn_id']}, asked at "
            f"{asked}; {newer} newer {runs} ended without a grounded answer."
        )
    return (
        f"Checking your newest setup run with an answer, {run['agent_turn_id']}, asked "
        f"at {asked}; {newer} newer {runs} stopped without one."
    )


def _pick_run() -> SetupRunPick:
    """Find the setup run to check and say which it is, or say how to make one."""
    from service.agent_deploys import deploy_due, lab_3_started_at
    from service.db import connect
    from service.lab_checks import mission_for_lab

    started_at = lab_3_started_at(ROOT)
    mission = mission_for_lab(3)
    with connect() as connection:
        pick = pick_setup_run(
            connection,
            mission["query"],
            started_at,
            follow_up=mission["changed_requirement"]["query"],
        )
        # Only a setup attempt still running can supply the missing setup run. A 100W
        # run in flight cannot, so the participant asks setup now rather than waiting.
        if pick.run is None and "setup" in pick.pending_answers:
            lab_exercise.wait_for_saved_answer("setup", pick.pending_answers["setup"])
            return pick
        saved = pick.run is None and (
            "follow_up" in pick.pending_answers or follow_up_saved(connection, ROOT)
        )
    if pick.run is None:
        since = (
            f" since Lab 3 started at {started_at.astimezone(UTC):%H:%M} UTC"
            if started_at
            else ""
        )
        found = (
            f"your {pick.asked} run(s) of Alex's setup request{since} all stopped "
            "without an answer, for example on HTTP 503 or the time limit"
            if pick.asked
            else f"found no run of Alex's setup request{since}"
        )
        print(verdict(f"Lab 3 exercise: CANNOT GRADE - {found}."))
        steps, commands = lab3_steps(deploy=deploy_due(ROOT), follow_up=not saved)
        next_step(steps, *commands)
        return pick
    print(_choice(pick) + "\n")
    return pick


@tidy
def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--run-id", type=UUID, help="check this run instead of your newest setup run"
    )
    args = parser.parse_args()
    run_id = args.run_id
    pending = {}
    try:
        if run_id is None:
            pick = _pick_run()
            if pick.run is None:
                return 2
            run_id = pick.run["agent_turn_id"]
            pending = pick.pending_answers
    except RuntimeError as error:
        # An unreadable Lab 3 start record names its own fix.
        print(verdict(f"Lab 3 exercise: CANNOT GRADE - {error}"))
        next_step(
            "fix what it names, then run this command again:", grade_setup_run_command()
        )
        return 2
    except psycopg.Error as error:
        print(
            verdict(
                "Lab 3 exercise: CANNOT GRADE - Aurora did not answer "
                f"({type(error).__name__})."
            )
        )
        next_step(
            "open a new terminal from the Terminal menu, which loads the workshop "
            "settings, and run this command again; if it repeats, tell your "
            "facilitator:",
            grade_setup_run_command(),
        )
        return 2
    save_context(ROOT / ".local/lab-3", str(run_id))
    return lab_exercise.main(["grade", "--lab", "3"], pending_answers=pending)


def save_context(output: Path, run_id: str) -> None:
    """Name the run to grade in the lab's saved context, keeping the other saved values.

    `lab_request.py` writes the same files with more keys; replacing them whole would
    drop what it saved, and a crash between the two files would leave them apart.
    """
    output.mkdir(parents=True, exist_ok=True)
    context = output / "context.json"
    try:
        values = json.loads(context.read_text()) if context.exists() else {}
    except json.JSONDecodeError:
        # lab_request.py writes this file in place; a run killed mid-write leaves it cut off.
        values = {}
    values["lab_agent_id"] = run_id
    for path, text in (
        (context, json.dumps(values, indent=2) + "\n"),
        (output / "context.psql", sql_context(values)),
    ):
        staged = path.with_suffix(path.suffix + ".tmp")
        staged.write_text(text)
        os.replace(staged, path)


if __name__ == "__main__":
    raise SystemExit(main())
