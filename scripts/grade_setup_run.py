"""Check the participant's Lab 3 setup run and the deployed Retrieval agent.

    uv run python scripts/grade_setup_run.py
    uv run python scripts/grade_setup_run.py --run-id RUN_ID

Without --run-id it checks a run of Alex's setup request since Lab 3 started that
opened its own conversation, from the terminal, Playground or Ask Mosaic: the newest
grounded one, else the newest that answered. It says which run it chose and how many
newer runs it passed over, such as a retry that stopped on HTTP 503.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from scripts import lab_exercise

# Runs are compared in Python, with the completion check's own rule for "the same
# request"; a participant asks a handful, so a bounded window holds them all.
RECENT_RUNS = 200


@dataclass(frozen=True)
class SetupRunPick:
    """The setup run to check, the newer setup runs passed over, and all of them."""

    run: dict[str, Any] | None
    skipped: list[dict[str, Any]] = field(default_factory=list)
    asked: int = 0


def pick_setup_run(
    connection: Any, request: str, started_at: datetime | None
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
    """
    from service.lab_checks import same_request

    rows = connection.execute(
        """
        SELECT agent_turn_id, user_message, created_at,
               assistant_message IS NOT NULL AS answered,
               extracted_intent ->> 'outcome' AS outcome
        FROM mosaic.agent_turn
        WHERE turn_number = 1
          AND (%(started)s::timestamptz IS NULL OR created_at > %(started)s::timestamptz)
        ORDER BY created_at DESC
        LIMIT %(limit)s
        """,
        {"started": started_at, "limit": RECENT_RUNS},
    ).fetchall()
    setup = [row for row in rows if same_request(request, row["user_message"])]
    run = next((row for row in setup if row["outcome"] == "grounded"), None) or next(
        (row for row in setup if row["answered"]), None
    )
    skipped = setup[: setup.index(run)] if run is not None else setup
    return SetupRunPick(run, skipped, len(setup))


def _choice(pick: SetupRunPick) -> str:
    run = pick.run or {}
    asked = f"{run['created_at'].astimezone(UTC):%H:%M:%S} UTC"
    if not pick.skipped:
        return (
            f"Checking your newest setup run, {run['agent_turn_id']}, asked at {asked}."
        )
    newer = len(pick.skipped)
    runs = "run" if newer == 1 else "runs"
    if run["outcome"] == "grounded":
        return (
            f"Checking your newest grounded setup run, {run['agent_turn_id']}, asked at "
            f"{asked}; {newer} newer {runs} ended without a grounded answer."
        )
    return (
        f"Checking your newest setup run with an answer, {run['agent_turn_id']}, asked "
        f"at {asked}; {newer} newer {runs} stopped without one."
    )


def _pick_run() -> UUID | None:
    """Find the setup run to check and say which it is, or say how to make one."""
    from service.agent_deploys import lab_3_started_at
    from service.db import connect
    from service.lab_checks import mission_for_lab
    from service.participant_commands import ask_setup

    started_at = lab_3_started_at(ROOT)
    with connect() as connection:
        pick = pick_setup_run(connection, mission_for_lab(3)["query"], started_at)
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
        print(
            f"Lab 3 exercise: CANNOT GRADE - {found}. "
            f"Next: ask it with\n{ask_setup()}\nthen run this command again."
        )
        return None
    print(_choice(pick))
    return UUID(str(pick.run["agent_turn_id"]))


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--run-id", type=UUID, help="check this run instead of your newest setup run"
    )
    args = parser.parse_args()
    try:
        run_id = args.run_id or _pick_run()
    except RuntimeError as error:
        # An unreadable Lab 3 start record names its own fix.
        print(f"Lab 3 exercise: CANNOT GRADE - {error}")
        return 2
    if run_id is None:
        return 2
    output = ROOT / ".local/lab-3"
    output.mkdir(parents=True, exist_ok=True)
    values = {"lab_agent_id": str(run_id)}
    (output / "context.json").write_text(json.dumps(values) + "\n")
    (output / "context.psql").write_text(f"\\set lab_agent_id '{run_id}'\n")
    sys.argv = [sys.argv[0], "check", "--lab", "3"]
    return lab_exercise.main()


if __name__ == "__main__":
    raise SystemExit(main())
