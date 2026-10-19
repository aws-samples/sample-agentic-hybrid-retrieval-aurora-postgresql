"""Enter a lab once, and restart one lab on purpose.

Lab 1's fault ships installed, so its start only saves the failing request.
Labs 2 and 3 start by installing only their own fault, applying it where it
runs, and saving the starting evidence. Each step is recorded in
`.local/lab-N/start.json` before it acts and again when it finishes, so an
interrupted start is completed by running it again: a recorded step is never
repeated, and a fault is never reinstalled over the participant's edits.
Prerequisites are checked, never repaired: a start refuses to install a
reference solution for an earlier lab. A restart is the one action that
discards the entered lab's edits. A handoff (`advance`) proves Lab 1 or 2
live, saves the passing evidence, then starts the next lab.
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
    LabDatabaseState,
    LabProblem,
    _replace_block,
    applied_problem,
    assert_reset_database,
    explain_problems,
    set_lab_state,
    source_problem,
    validate_database,
)
from service.participant_commands import (
    ADVANCE_TO_LAB_2,
    ADVANCE_TO_LAB_3,
    APPLY_SQL,
    DEPLOY_AGENT,
    complete_lab_3,
    reset,
    validate,
    validate_applied,
)
from service.participant_commands import start as start_command

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


def unmet_prerequisites(
    lab: int, connection: Any, repo: Path = REPO
) -> list[LabProblem]:
    """Explain each earlier repair the entered lab needs; never make one.

    The saved block is judged first, so Aurora is read only once it is repaired
    and a refusal names the one problem the participant can act on next.
    """
    problems = []
    for earlier in PREREQUISITES[lab]:
        problem = source_problem(earlier, repo=repo) or applied_problem(
            earlier, validate_database(earlier, connection, repo=repo)
        )
        if problem:
            problems.append(problem)
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
        installed = "the Retrieval agent starter" if lab == 3 else f"Lab {lab}'s fault"
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
    from service.lab_validation_receipt import participant_sql_digest
    from service.search_sql import search_sql

    digest = participant_sql_digest(repo)
    with psycopg.connect(dsn, connect_timeout=15) as connection:
        apply(connection, search_sql(repo), digest)
    configure(dsn)
    say("Applied it to Aurora.")
    return digest


def _apply_sql(dsn: str | None, repo: Path, record: dict[str, Any], say: Say) -> None:
    if record["steps"].get("applied", {}).get("state") == "done":
        return
    digest = _apply(dsn, repo, say)
    record["steps"]["applied"] = {"state": "done", "sql_sha256": digest}
    _save(record["lab"], repo, record)


def _failing_search_evidence(
    lab: int, applied: LabDatabaseState, api_url: str, repo: Path, say: Say
) -> dict[str, Any]:
    """Save the lab's failing search, or record why no failing search exists."""
    if applied.state == "applied":
        say(
            f"Your Lab {lab} repair is already applied, so no failing run was saved "
            f"and there is no Before to compare. Next: {validate(lab)}"
        )
        return {"state": "done", "note": "repair already applied; no failing run saved"}
    from scripts.lab_terminal import AlreadyRepaired, prepare

    output = repo / ".local" / f"lab-{lab}"
    try:
        prepare(lab, "before", api_url, output)
    except AlreadyRepaired as repaired:
        # The live search works while the saved block does not count as
        # applied, so no failing request exists; the state says why.
        say(
            f"Lab {lab}: {repaired}. {applied.detail}\n"
            f"Next: {validate_applied(lab)} names what to change or run."
        )
        return {
            "state": "done",
            "note": "search already finds the target; no failing run saved",
        }
    saved = json.loads((output / "before-state.json").read_text())
    return {"state": "done", "search_event_id": str(saved["run_id"])}


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
        # The saved refusal is Mosaic's one-line message; on screen the deploy command gets
        # its own line, so no line wraps mid-word in a laptop terminal.
        say(
            "Mosaic now refuses Retrieval agent requests. Your Retrieval agent is not built yet.\n"
            "Open labs/lab3_reason/agent.py and complete create_agent with the supplied model,\n"
            "tools, instructions and hooks. Then deploy it and ask your question again:\n"
            f"      {DEPLOY_AGENT}"
        )
    else:
        applied = validate_database(lab, connection, repo=repo)
        evidence = _failing_search_evidence(lab, applied, api_url, repo, say)
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
            explain_problems(
                f"Lab {lab} cannot start yet.", problems, start_command(lab)
            )
        )
    record = record or {"version": RECORD_VERSION, "lab": lab, "steps": {}}
    if lab in FAULT_AT_ENTRY:
        _install_fault(lab, repo, record, say)
    if lab == 2:
        _apply_sql(dsn, repo, record, say)
    with _connect(dsn) as connection:
        _capture(lab, api_url, repo, record, connection, say)
    record["completed_at"] = datetime.now(UTC).isoformat()
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
            explain_problems(f"Lab {lab} cannot restart yet.", problems, reset(lab))
        )
    set_lab_state(lab, solved=False, repo=repo)
    for path in (record_path(lab, repo), completion_path(lab, repo)):
        path.unlink(missing_ok=True)
    if lab == 1:
        (repo / ".local/lab-1/handoff.json").unlink(missing_ok=True)
    say(f"Discarded your Lab {lab} edits.")
    if lab == 1:
        # Lab 2's start applies its own file; Lab 1's start never edits or
        # applies, so the restored starter is applied here.
        _apply(dsn, repo, say)
    return start(lab, api_url=api_url, dsn=dsn, repo=repo, say=say)


#: What each part of a saved handoff's binding means when it no longer matches.
_HANDOFF_BINDING = {
    "database": "DATABASE_URL selects a different database",
    "lab1_seam": "your LAB1_EDIT block changed",
    "lab1_entry": "Lab 1 was restarted",
}


def _handoff_mismatch(
    saved: dict[str, Any], current: dict[str, Any], repo: Path
) -> str:
    """Say what changed since Lab 1's evidence was saved, and what to do now."""
    changed = "; ".join(
        text for key, text in _HANDOFF_BINDING.items() if saved.get(key) != current[key]
    )
    lab_2 = load_record(2, repo)
    if lab_2 and lab_2.get("completed_at"):
        return (
            "Lab 1 does not need to hand off again: Lab 2 is already prepared.\n"
            f"- Since Lab 1 was validated, {changed}.\n"
            "Next: continue in the Lab 2 guide. If you changed Lab 1 on purpose, run "
            f"{APPLY_SQL} so Aurora runs it."
        )
    return (
        "Lab 1 cannot hand off yet.\n"
        f"- Since Lab 1 was validated, {changed}, and Lab 2's preparation did not "
        "finish.\n"
        "Next: copy this message to your facilitator. Your edits are unchanged."
    )


def advance(
    lab: int, *, api_url: str, dsn: str | None, repo: Path = REPO, say: Say = print
) -> dict[str, Any]:
    """Prove a SQL lab live, save its evidence, then prepare the next lab.

    Raises:
        LabEntryError: The lab has no handoff, or its repair is not ready to prove.
        LabValidationError: A live check failed; nothing for the next lab changed.
    """
    if lab == 1:
        return _advance_lab_1(api_url=api_url, dsn=dsn, repo=repo, say=say)
    if lab == 2:
        return _advance_lab_2(api_url=api_url, dsn=dsn, repo=repo, say=say)
    raise LabEntryError(
        f"Handoff rule: found Lab {lab}; fix: use advance --lab 1 or advance --lab 2. "
        f"Lab 3 ends when {complete_lab_3()} passes on your setup run."
    )


def _advance_lab_2(
    *, api_url: str, dsn: str | None, repo: Path, say: Say
) -> dict[str, Any]:
    """Prove Lab 2, then install the Retrieval agent starter; safe to rerun.

    Unlike Lab 2's ranking fault under Lab 1, the Retrieval agent starter never
    touches the searches Lab 2's checks run, so every rerun proves Lab 2 again
    rather than reusing saved evidence, and a started Lab 3 keeps its edits.
    """
    from scripts.validate_lab import record_completion, validate_lab_2
    from service.lab_proof import entry_check

    entered = entry_check(2, repo)
    if not entered.passed:
        raise LabEntryError(f"Lab 2 cannot hand off yet.\n- {entered.detail}")
    assert_reset_database(dsn)
    with _connect(dsn) as connection:
        problems = unmet_prerequisites(3, connection, repo)
    if problems:
        raise LabEntryError(
            explain_problems("Lab 2 cannot hand off yet.", problems, ADVANCE_TO_LAB_3)
        )
    events: list[str] = []
    say(
        "Validating Lab 2 in Aurora: Alex's monitor request, then the requests that "
        "must still work…"
    )
    checks = validate_lab_2(api_url, events, rerun=ADVANCE_TO_LAB_3)
    for check in checks:
        say(f"PASS: {check}")
    record_completion(2, checks, events, repo)
    say("Lab 2: production-path validation passed. Passing evidence saved.")
    say("Preparing Lab 3: install the Retrieval agent starter once.")
    record = start(3, api_url=api_url, dsn=dsn, repo=repo, say=say)
    say(
        "Lab 3: prepared. Continue in the Lab 3 guide. Your existing edits are preserved."
    )
    return record


def _advance_lab_1(
    *, api_url: str, dsn: str | None, repo: Path, say: Say
) -> dict[str, Any]:
    """Prove Lab 1 before preparing Lab 2; resume without replaying masked checks.

    The handoff saves its own verified evidence before installing the ranking
    fault. It is bound to this database, Lab 1 entry and repaired seam, so a
    reset or a changed repair cannot silently reuse it.
    """
    from scripts.validate_lab import record_completion, validate_lab_1

    assert_reset_database(dsn)
    with _connect(dsn) as connection:
        problems = unmet_prerequisites(2, connection, repo)
    if problems:
        raise LabEntryError(
            explain_problems("Lab 1 cannot hand off yet.", problems, ADVANCE_TO_LAB_2)
        )
    binding = {
        "database": hashlib.sha256((dsn or "").encode()).hexdigest(),
        "lab1_seam": _seam_sha256(1, (repo / LABS[1][0]).read_text()),
        "lab1_entry": load_record(1, repo),
    }
    path = repo / ".local/lab-1/handoff.json"
    saved = json.loads(path.read_text()) if path.exists() else None
    if saved and saved.get("binding") != binding:
        raise LabEntryError(
            _handoff_mismatch(saved.get("binding") or {}, binding, repo)
        )
    if saved is None:
        if load_record(2, repo) is not None:
            raise LabEntryError(
                "Lab 1 cannot hand off: Lab 2 was started directly, before Lab 1's "
                "passing evidence was saved.\n"
                "Next: continue in the Lab 2 guide. Lab 2's ranking fault can hide a "
                "correct Lab 1 repair, so Lab 1 cannot be validated again until Lab 2 "
                "is repaired. Your edits are unchanged."
            )
        events: list[str] = []
        say(
            "Validating Lab 1 in Aurora: the typo request, then two searches that must still work…"
        )
        checks = validate_lab_1(api_url, events, rerun=ADVANCE_TO_LAB_2)
        for check in checks:
            say(f"PASS: {check}")
        record_completion(1, checks, events, repo)
        saved = {"binding": binding, "checks": checks, "search_event_ids": events}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(saved, indent=2) + "\n")
        temporary.replace(path)
        say("Lab 1: production-path validation passed. Passing evidence saved.")
    else:
        say(
            "Lab 1: using saved handoff validation; not repeating it under Lab 2's ranking fault."
        )
    say("Preparing Lab 2: install its fault once and save the starting request.")
    record = start(2, api_url=api_url, dsn=dsn, repo=repo, say=say)
    say(
        "Lab 2: prepared. Continue with the saved failure in the Lab 2 guide. Your existing edits are preserved."
    )
    return record
