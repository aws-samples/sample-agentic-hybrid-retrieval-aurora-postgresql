"""Enter a lab once, and restart one lab on purpose.

Lab 1's fault ships installed, so its start only saves the failing request.
Labs 2 and 3 start by installing only their own fault, applying it where it
runs, and saving the starting evidence. Each step is recorded in
`.local/lab-N/start.json` before it acts and again when it finishes, so an
interrupted start is completed by running it again: a recorded step is never
repeated, and a fault is never reinstalled over the participant's edits.
Prerequisites are checked, never repaired: a start refuses to install a
reference solution for an earlier lab. A restart is the one action that
discards the entered lab's edits.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.lab_state import (
    LABS,
    REPO,
    _replace_block,
    assert_reset_database,
    lab_is_solved,
    set_lab_state,
    validate_database,
)
from service.participant_commands import APPLY_SQL, reset

#: Each lab and the earlier repairs it needs before it starts.
PREREQUISITES: dict[int, tuple[int, ...]] = {1: (), 2: (1,), 3: (1, 2)}
#: The labs whose fault is installed when they start rather than at boot.
FAULT_AT_ENTRY = frozenset({2, 3})
RECORD_VERSION = 1

Say = Callable[[str], None]


class LabEntryError(RuntimeError):
    """A start that cannot proceed, with what the participant should do next."""


def record_path(lab: int, repo: Path = REPO) -> Path:
    return repo / ".local" / f"lab-{lab}" / "start.json"


def completion_path(lab: int, repo: Path = REPO) -> Path:
    return repo / ".local" / f"lab-{lab}" / "completion.json"


def load_record(lab: int, repo: Path = REPO) -> dict[str, Any] | None:
    path = record_path(lab, repo)
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    if record.get("version") != RECORD_VERSION or record.get("lab") != lab:
        raise LabEntryError(
            f"Lab entry rule: {path} is not a Lab {lab} start record; fix: reset "
            f"the lab with {reset(lab)}."
        )
    return record


def _save(lab: int, repo: Path, record: dict[str, Any]) -> None:
    path = record_path(lab, repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n")
    temporary.replace(path)


def _seam(lab: int, source: str) -> str:
    return "\n".join(
        source.split(start, 1)[1].split(end, 1)[0] for start, end, _, _ in LABS[lab][1]
    )


def _seam_sha256(lab: int, source: str) -> str:
    return hashlib.sha256(_seam(lab, source).encode()).hexdigest()


def _broken_seam_sha256(lab: int, source: str) -> str:
    for start, end, _, broken in LABS[lab][1]:
        source = _replace_block(source, start, end, broken)
    return _seam_sha256(lab, source)


def _connect(dsn: str | None):
    """A short autocommit session, so no read holds a transaction across an apply."""
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(
        dsn, connect_timeout=15, autocommit=True, row_factory=dict_row
    )


def unmet_prerequisites(lab: int, connection: Any, repo: Path = REPO) -> list[str]:
    """Explain each earlier repair the entered lab needs; never make one."""
    problems = []
    for earlier in PREREQUISITES[lab]:
        if not lab_is_solved(earlier, repo=repo):
            problems.append(
                f"Lab {earlier} is not repaired in {LABS[earlier][0]}. Next: complete "
                f"its LAB{earlier}_ block and apply it, or follow Hint 4 in the "
                f"Lab {earlier} guide; then start this lab again."
            )
        elif validate_database(earlier, connection).state == "stale":
            problems.append(
                f"Lab {earlier}'s repair is in {LABS[earlier][0]} but not in Aurora. "
                f"Next: apply it with {APPLY_SQL}, then start this lab again."
            )
    return problems


def _install_fault(lab: int, repo: Path, record: dict[str, Any], say: Say) -> None:
    step = record["steps"].get("fault", {})
    if step.get("state") == "done":
        return
    path = repo / LABS[lab][0]
    current = _seam_sha256(lab, path.read_text())
    broken = _broken_seam_sha256(lab, path.read_text())
    if step.get("state") == "installing" and current not in {step["before"], broken}:
        # Interrupted after the file changed, and the participant has edited
        # since: their edit is the lab now.
        say(f"Kept your edits in {LABS[lab][0]}.")
    elif current != broken:
        record["steps"]["fault"] = {"state": "installing", "before": current}
        _save(lab, repo, record)
        set_lab_state(lab, solved=False, repo=repo)
        installed = "the agent starter" if lab == 3 else f"Lab {lab}'s fault"
        say(f"Installed {installed} in {LABS[lab][0]}.")
    record["steps"]["fault"] = {
        "state": "done",
        "seam_sha256": _seam_sha256(lab, path.read_text()),
    }
    _save(lab, repo, record)


def _apply(dsn: str | None, repo: Path, say: Say) -> str:
    import psycopg

    from scripts.apply_search_functions import apply
    from scripts.configure_retrieval_database import configure
    from service.lab_validation_receipt import PARTICIPANT_SQL, participant_sql_digest

    digest = participant_sql_digest(repo)
    with psycopg.connect(dsn, connect_timeout=15) as connection:
        apply(connection, (repo / PARTICIPANT_SQL).read_text(), digest)
    configure(dsn)
    say("Applied it to Aurora.")
    return digest


def _apply_sql(dsn: str | None, repo: Path, record: dict[str, Any], say: Say) -> None:
    if record["steps"].get("applied", {}).get("state") == "done":
        return
    digest = _apply(dsn, repo, say)
    record["steps"]["applied"] = {"state": "done", "sql_sha256": digest}
    _save(record["lab"], repo, record)


def _capture(
    lab: int,
    api_url: str,
    repo: Path,
    record: dict[str, Any],
    connection: Any,
    say: Say,
) -> None:
    if record["steps"].get("evidence", {}).get("state") == "done":
        return
    if lab == 3:
        from service.agent_setup import AGENT_STARTER_MESSAGE

        evidence = {"state": "done", "agent_refusal": AGENT_STARTER_MESSAGE}
        say(f"Mosaic now refuses agent requests: {AGENT_STARTER_MESSAGE}")
    elif validate_database(lab, connection).state == "applied":
        evidence = {
            "state": "done",
            "note": "repair already applied; no failing run saved",
        }
        say(f"Your Lab {lab} repair is already applied, so no failing run was saved.")
    else:
        from scripts.lab_terminal import prepare

        output = repo / ".local" / f"lab-{lab}"
        prepare(lab, "before", api_url, output)
        saved = json.loads((output / "before-state.json").read_text())
        evidence = {"state": "done", "search_event_id": str(saved["run_id"])}
    record["steps"]["evidence"] = evidence
    _save(lab, repo, record)


def start(
    lab: int, *, api_url: str, dsn: str | None, repo: Path = REPO, say: Say = print
) -> dict[str, Any]:
    """Prepare one lab, or finish an interrupted preparation, and return its record.

    Raises:
        LabEntryError: A prerequisite is unmet or the record is unreadable.
    """
    if lab not in PREREQUISITES:
        raise LabEntryError(
            f"Lab entry rule: found Lab {lab}; fix: start Lab 1, 2 or 3."
        )
    record = load_record(lab, repo)
    if record and record.get("completed_at"):
        say(
            f"Lab {lab} was started at {record['completed_at']}; your edits are unchanged."
        )
        return record
    assert_reset_database(dsn)
    with _connect(dsn) as connection:
        problems = unmet_prerequisites(lab, connection, repo)
    if problems:
        raise LabEntryError(
            f"Lab {lab} cannot start yet.\n" + "\n".join(f"- {p}" for p in problems)
        )
    record = record or {"version": RECORD_VERSION, "lab": lab, "steps": {}}
    if lab in FAULT_AT_ENTRY:
        _install_fault(lab, repo, record, say)
    if lab == 2:
        _apply_sql(dsn, repo, record, say)
    with _connect(dsn) as connection:
        _capture(lab, api_url, repo, record, connection, say)
    record["completed_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    _save(lab, repo, record)
    return record


def restart(
    lab: int, *, api_url: str, dsn: str | None, repo: Path = REPO, say: Say = print
) -> dict[str, Any]:
    """Discard the entered lab's edits and prepare it again from its starter."""
    assert_reset_database(dsn)
    with _connect(dsn) as connection:
        problems = unmet_prerequisites(lab, connection, repo)
    if problems:
        raise LabEntryError(
            f"Lab {lab} cannot restart yet.\n" + "\n".join(f"- {p}" for p in problems)
        )
    set_lab_state(lab, solved=False, repo=repo)
    for path in (record_path(lab, repo), completion_path(lab, repo)):
        path.unlink(missing_ok=True)
    say(f"Discarded your Lab {lab} edits.")
    if lab == 1:
        # Lab 2's start applies its own file; Lab 1's start never edits or
        # applies, so the restored starter is applied here.
        _apply(dsn, repo, say)
    return start(lab, api_url=api_url, dsn=dsn, repo=repo, say=say)
