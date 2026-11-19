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
from typing import Any, Literal, NamedTuple

from scripts.lab_state import (
    LABS,
    REPO,
    LabDatabaseState,
    LabProblem,
    _replace_block,
    applied_problem,
    assert_workshop_database,
    explain_problems,
    missing_file_problem,
    outside_block_problem,
    read_applied_sql_state,
    set_lab_state,
    source_problem,
)
from scripts.terminal_text import BOLD, GREEN, fill_words, next_text, tint, verdict
from service.participant_commands import (
    ADVANCE_TO_LAB_2,
    ADVANCE_TO_LAB_3,
    DEPLOY_AGENT,
    grade_setup_run_command,
    reset_command,
    start_command,
    start_record_recovery,
    validate_applied_command,
)

#: Each lab and the earlier repairs it needs before it starts.
PREREQUISITES: dict[int, tuple[int, ...]] = {1: (), 2: (1,), 3: (1, 2)}
#: The labs whose fault is installed when they start rather than at boot.
FAULT_AT_ENTRY = frozenset({2, 3})
#: The labs whose saved files Aurora runs; every apply sends both.
SQL_LABS = (1, 2)
RECORD_VERSION = 1

Say = Callable[[str], None]


class LabEntryError(RuntimeError):
    """A start that cannot proceed, with what the participant should do next."""


class StartRecordError(LabEntryError, ValueError):
    """A lab's start record cannot be read; its fix keeps the participant's edits.

    It is also a ValueError: the commands that read Lab 3's start time report it beside an
    unreadable deploy record, which is one.
    """

    def __init__(self, lab: int, problem: str) -> None:
        self.lab = lab
        self.problem = problem
        sentence, commands = start_record_recovery(lab)
        self.finding = (
            f"Lab {lab} start record rule: .local/lab-{lab}/start.json cannot be read "
            f"({problem})."
        )
        again = ["Then ask both Lab 3 questions again."] if lab == 3 else []
        super().__init__(
            "\n\n".join(
                [fill_words(self.finding, 100), next_text(sentence, *commands), *again]
            )
        )


def record_path(lab: int, repo: Path = REPO) -> Path:
    return repo / ".local" / f"lab-{lab}" / "start.json"


def entry_command(lab: int, repo: Path = REPO) -> str:
    """The command that enters a lab that has not started, as the guide names it.

    Lab 1 starts itself. Labs 2 and 3 are prepared by the earlier lab's hand-off, so
    `start` there only finishes a start that a hand-off began and was cut off.
    """
    if lab == 1:
        return start_command(1)
    try:
        begun = load_record(lab, repo) is not None
    except StartRecordError:
        begun = True
    if begun:
        return start_command(lab)
    if lab == 3 and not _handed_off_into(2, repo):
        return entry_command(2, repo)
    return ADVANCE_TO_LAB_2 if lab == 2 else ADVANCE_TO_LAB_3


def _handed_off_into(lab: int, repo: Path) -> bool:
    try:
        record = load_record(lab, repo)
    except StartRecordError:
        return False
    return bool(record and record.get("completed_at"))


def completion_path(lab: int, repo: Path = REPO) -> Path:
    return repo / ".local" / f"lab-{lab}" / "completion.json"


CompletionState = Literal[
    "valid",
    "legacy_verified",
    "legacy_unverified",
    "absent",
    "unreadable",
    "other_attempt",
    "other_sql",
]


class CompletionReading(NamedTuple):
    """What a SQL lab's completion receipt says about the lab as it stands now.

    `valid` and `legacy_verified` count as proved. A receipt is never deleted for
    being any other state: the next passing proof replaces it, and `receipt` keeps
    what was read for the states that still parse.
    """

    state: CompletionState
    receipt: dict[str, Any] | None
    detail: str

    @property
    def proved(self) -> bool:
        return self.state in {"valid", "legacy_verified"}


def sql_identity(lab: int, repo: Path = REPO) -> str | None:
    """Identity of one SQL lab's saved file, or None when it cannot be read.

    The tokens are the executable ones the retrieval fingerprint uses (comments and
    spacing do not count) over the whole lab file, so a change to the function outside
    the marked block, such as its final LIMIT, is a different SQL. Only this lab's own
    file counts: Lab 2's fault, in the other file, leaves Lab 1's proof alone.
    """
    from service.retrieval_fingerprint import _lab_sql_sha256

    try:
        return _lab_sql_sha256(repo / LABS[lab][0])
    except (OSError, ValueError):
        return None


def _attempt(lab: int, repo: Path) -> str | None:
    """When this lab's current attempt started, or None before any start record.

    Raises:
        StartRecordError: The start record is cut off, hand-edited or another lab's.
    """
    record = load_record(lab, repo)
    return record.get("completed_at") if record else None


def completion_binding(lab: int, repo: Path = REPO) -> dict[str, Any]:
    """The attempt and SQL a passing proof is about to vouch for; take it before proving."""
    try:
        attempt = _attempt(lab, repo)
    except StartRecordError:
        # No identity is better than a wrong one: a receipt with none never counts.
        return {"start_completed_at": None, "sql_sha256": None}
    return {"start_completed_at": attempt, "sql_sha256": sql_identity(lab, repo)}


def evidence_problem(evidence: dict[str, Any]) -> str | None:
    """What makes passing evidence unusable, or None: a receipt and a hand-off share it."""
    for key in ("checks", "search_event_ids"):
        values = evidence.get(key)
        if not (
            isinstance(values, list)
            and values
            and all(isinstance(value, str) and value for value in values)
        ):
            return f"its {key} are missing or empty"
    return None


def _receipt_problem(lab: int, receipt: Any) -> str | None:
    """What makes a parsed receipt incomplete, or None."""
    if not isinstance(receipt, dict):
        return "it is not a JSON object"
    if receipt.get("lab") != lab or isinstance(receipt.get("lab"), bool):
        return f"it is not marked lab {lab}"
    try:
        datetime.fromisoformat(receipt["passed_at"])
    except (KeyError, TypeError, ValueError):
        return "it has no valid passed_at time"
    if problem := evidence_problem(receipt):
        return problem
    saved = [key for key in ("start_completed_at", "sql_sha256") if key in receipt]
    if len(saved) == 1:
        return f"it names {saved[0]} but not the other half of its identity"
    if saved and not all(
        value is None or isinstance(value, str)
        for value in (receipt["start_completed_at"], receipt["sql_sha256"])
    ):
        return "its identity is not text"
    return None


def _legacy_handoff_matches(receipt: dict[str, Any], repo: Path) -> bool:
    """Whether Lab 1's saved handoff vouches for a receipt written without an identity.

    The handoff binds the same attempt and repaired block, so it verifies a receipt
    the released build wrote, offline. Lab 2 saved no such evidence.
    """
    try:
        saved = json.loads((repo / ".local/lab-1/handoff.json").read_text())
        binding = saved["binding"]
        seam = _seam_sha256(1, (repo / LABS[1][0]).read_text())
        return (
            binding["lab1_seam"] == seam
            and binding["lab1_entry"] == load_record(1, repo)
            and saved["search_event_ids"] == receipt["search_event_ids"]
        )
    except (OSError, ValueError, KeyError, TypeError, IndexError, StartRecordError):
        return False


def read_completion(lab: int, repo: Path = REPO) -> CompletionReading:
    """Judge a SQL lab's completion receipt against its attempt and saved SQL, offline.

    The one reader every consumer shares: `status`, the hand-off, the proof's
    messages and the API. It reads files only, so it never needs a live search, which
    Lab 2's fault would fail for a correct Lab 1.
    """
    path = completion_path(lab, repo)
    if not path.exists():
        return CompletionReading("absent", None, "no completion was saved")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return CompletionReading("unreadable", None, "the saved completion is cut off")
    if problem := _receipt_problem(lab, receipt):
        return CompletionReading("unreadable", None, f"the saved completion: {problem}")
    if "sql_sha256" not in receipt:
        # Old evidence binds only the marked block, so it verifies the whole function
        # only while nothing outside the block changed.
        if outside_block_problem(lab, repo=repo) is None and _legacy_handoff_matches(
            receipt, repo
        ):
            return CompletionReading("legacy_verified", receipt, "verified by handoff")
        return CompletionReading(
            "legacy_unverified", receipt, "the saved completion names no attempt or SQL"
        )
    try:
        attempt = _attempt(lab, repo)
    except StartRecordError:
        return CompletionReading(
            "other_attempt", receipt, f"Lab {lab}'s start record cannot be read"
        )
    if receipt["start_completed_at"] != attempt:
        return CompletionReading(
            "other_attempt", receipt, f"Lab {lab} was restarted since it passed"
        )
    current = sql_identity(lab, repo)
    if current is None or receipt["sql_sha256"] != current:
        return CompletionReading(
            "other_sql", receipt, f"Lab {lab}'s saved SQL changed since it passed"
        )
    return CompletionReading("valid", receipt, "matches this attempt and SQL")


def started_clock(recorded: str) -> str:
    """A saved start time as "2026-11-01 17:25 UTC", not the record's microseconds."""
    from datetime import UTC, datetime

    try:
        moment = datetime.fromisoformat(recorded)
    except ValueError:
        return recorded
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return f"{moment.astimezone(UTC):%Y-%m-%d %H:%M} UTC"


def load_record(lab: int, repo: Path = REPO) -> dict[str, Any] | None:
    """The lab's start record, or None before its start.

    Raises:
        StartRecordError: The record is cut off, hand-edited or another lab's.
    """
    return read_record(record_path(lab, repo), lab)


def read_record(path: Path, lab: int) -> dict[str, Any] | None:
    """The start record saved at `path`, or None when there is no file.

    Raises:
        StartRecordError: The record is cut off, hand-edited or another lab's.
    """
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        reason = (error.strerror or "no reason given").lower()
        raise StartRecordError(lab, f"it cannot be opened: {reason}") from error
    except ValueError as error:
        raise StartRecordError(lab, "it is cut off or is not JSON") from error
    if problem := _record_problem(lab, record):
        raise StartRecordError(lab, problem)
    return record


# What json.loads returns for each JSON value, in the words the record's reader knows.
_JSON_KINDS: dict[type, str] = {
    list: "a JSON list",
    str: "a JSON string",
    int: "a JSON number",
    float: "a JSON number",
    bool: "JSON true or false",
    type(None): "JSON null",
}


def _json_kind(value: Any) -> str:
    return _JSON_KINDS.get(type(value), "a JSON object")


def _record_problem(lab: int, record: Any) -> str | None:
    """What makes a parsed start record unusable, in words, or None.

    Every field the commands read later is checked here, so a hand-edited record is
    refused once, with its fix, rather than crashing a later command.
    """
    if not isinstance(record, dict):
        return f"it holds {_json_kind(record)}, not a record"
    if record.get("lab") is None:
        return "it has no lab number"
    if record.get("version") is None:
        return "it has no version number"
    marked = (record["lab"], record["version"])
    if marked != (lab, RECORD_VERSION) or any(isinstance(v, bool) for v in marked):
        return (
            f"it is marked lab {json.dumps(marked[0])}, version {json.dumps(marked[1])}, "
            f"not lab {lab}, version {RECORD_VERSION}"
        )
    if "steps" not in record:
        return "it has no steps"
    if not isinstance(record["steps"], dict):
        return f"its steps are {_json_kind(record['steps'])}, not an object"
    return _start_time_problem(record.get("completed_at"))


def _start_time_problem(started: Any) -> str | None:
    """What is wrong with a record's start time, or None when it is absent or a UTC-aware time."""
    if started is None or started == "":
        return None
    shown = json.dumps(started)
    if not isinstance(started, str):
        return f"its start time {shown} is not a time"
    try:
        moment = datetime.fromisoformat(started)
    except ValueError:
        return f"its start time {shown} is not a time"
    if moment.tzinfo is None:
        return f"its start time {shown} has no time zone, such as +00:00"
    return None


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
            earlier, read_applied_sql_state(earlier, connection, repo=repo)
        )
        if problem:
            problems.append(problem)
    return problems


def _apply_saved_repairs(lab: int, dsn: str | None, repo: Path, say: Say) -> None:
    """Apply the saved SQL when every lab before `lab` is repaired but Aurora runs other SQL.

    A participant can apply one correct repair and then save another, such as the
    reference answer pasted over their own: both pass, yet the handoff would refuse
    until they applied again. It applies the saved files instead, exactly as the
    apply command does. A saved block that is not repaired is never applied here,
    so its refusal still names it.

    Raises:
        LabEntryError: Aurora rejected the saved SQL; nothing was applied.
    """
    import psycopg

    from scripts.apply_search_functions import describe_apply_failure

    earlier = PREREQUISITES[lab]
    if any(source_problem(each, repo=repo) for each in earlier):
        return
    with _connect(dsn) as connection:
        stale = [
            each
            for each in earlier
            if applied_problem(
                each, read_applied_sql_state(each, connection, repo=repo)
            )
        ]
    if not stale:
        return
    files = " and ".join(Path(LABS[each][0]).name for each in stale)
    verb = "is" if len(stale) == 1 else "are"
    say(
        f"Your saved {files} {verb} repaired, but Aurora runs an earlier version of "
        f"{'it' if len(stale) == 1 else 'them'}; applying the saved SQL first."
    )
    try:
        _apply(dsn, repo, say)
    except ValueError as error:
        reason = (
            f"{error}\nNothing was applied: Aurora still runs its previous functions."
        )
    except psycopg.Error as error:
        reason = describe_apply_failure(error, rolled_back=True)
    else:
        return
    then = ADVANCE_TO_LAB_2 if lab == 2 else ADVANCE_TO_LAB_3
    raise LabEntryError(
        f"Lab {lab - 1} cannot hand off yet: applying your saved SQL failed.\n"
        f"{reason}\n\nNext: after fixing that, run\n{then}"
    )


def _install_fault(lab: int, repo: Path, record: dict[str, Any], say: Say) -> None:
    step = record["steps"].get("fault", {})
    if step.get("state") == "done":
        return
    path = repo / LABS[lab][0]
    if not path.exists():
        # The same Git path a reset takes, so a deleted file starts from its starting
        # code rather than failing; the fault is then already in place.
        set_lab_state(lab, solved=False, repo=repo)
        say(f"Put back {LABS[lab][0]} with its starting code; it was deleted.")
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
        installed = (
            "the Retrieval agent's starting code" if lab == 3 else f"Lab {lab}'s fault"
        )
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

    for lab in SQL_LABS:
        # Before the first write, as the guide's apply command checks: SQL outside a
        # marked block is not the exercise.
        if changed := outside_block_problem(lab, repo=repo):
            raise LabEntryError(
                f"{changed.finding}\n"
                "Nothing was applied: Aurora still runs its previous functions.\n"
                f"Next: {changed.next_step}"
            )
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
    lab: int,
    applied: LabDatabaseState,
    api_url: str,
    repo: Path,
    say: Say,
    *,
    handoff: bool = False,
) -> dict[str, Any]:
    """Save the lab's failing search, or record why no failing search exists."""
    if applied.state == "applied":
        # The context the guide's psql step loads is saved once the start is
        # recorded, from the search as it is now (_save_missing_context).
        return {"state": "done", "note": "repair already applied; no failing run saved"}
    from scripts.lab_request import AlreadyRepaired, prepare

    output = repo / ".local" / f"lab-{lab}"
    try:
        prepare(lab, "before", api_url, output, handoff=handoff)
    except AlreadyRepaired as repaired:
        # The live search works while the saved block does not count as
        # applied, so no failing request exists; the state says why.
        say(
            f"Lab {lab}: {repaired}. {applied.detail}\n"
            f"To see what to change or run: {validate_applied_command(lab)}"
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
    *,
    handoff: bool = False,
) -> None:
    if record["steps"].get("evidence", {}).get("state") == "done":
        return
    if lab == 3:
        from service.agent_setup import AGENT_STARTER_MESSAGE

        evidence = {"state": "done", "agent_refusal": AGENT_STARTER_MESSAGE}
        # The saved refusal is Mosaic's one-line message; on screen the deploy command gets
        # its own line, so no line wraps mid-word in a laptop terminal.
        say(
            "\nMosaic now refuses Retrieval agent requests. Your Retrieval agent is not built yet.\n"
            "Open labs/lab3_reason/agent.py and complete create_agent with the supplied model,\n"
            "tools, instructions and hooks. Then deploy it and ask your question again:\n"
            f"      {DEPLOY_AGENT}"
        )
    else:
        applied = read_applied_sql_state(lab, connection, repo=repo)
        evidence = _failing_search_evidence(
            lab, applied, api_url, repo, say, handoff=handoff
        )
    record["steps"]["evidence"] = evidence
    _save(lab, repo, record)


def _save_missing_context(lab: int, api_url: str, repo: Path) -> None:
    """Leave the psql context a SQL lab's guide loads, even when no failing run was saved.

    Only a saved search writes `.local/lab-N/context.psql`, and psql skips a missing
    `PSQLRC` file without a word. A start that finds the repair already applied, or an
    already-repaired search, saves no failing run; the context then comes from the
    search as it is now, as the lab's repeat-request command saves it. It runs after
    the start is recorded, because that command refuses a lab that has not started.
    """
    if lab not in (1, 2):
        return
    output = repo / ".local" / f"lab-{lab}"
    if (output / "context.psql").exists():
        return
    from scripts.lab_request import prepare

    prepare(lab, "after", api_url, output)


def start(
    lab: int,
    *,
    api_url: str,
    dsn: str | None,
    repo: Path = REPO,
    say: Say = print,
    handoff: bool = False,
) -> dict[str, Any]:
    """Prepare one lab, or finish an interrupted preparation, and return its record.

    Args:
        handoff: The previous lab's hand-off is starting this lab. It prints only the
            request and its target, so the checks and the `Next:` step fit one terminal
            screen beside the guide; the `Next:` step names the saved context itself.

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
            f"Lab {lab} was started at {started_clock(record['completed_at'])}; "
            "your edits are unchanged."
        )
        _save_missing_context(lab, api_url, repo)
        return record
    if lab not in FAULT_AT_ENTRY and (missing := missing_file_problem(lab, repo)):
        raise LabEntryError(missing.line)
    assert_workshop_database(dsn)
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
        _capture(lab, api_url, repo, record, connection, say, handoff=handoff)
    record["completed_at"] = datetime.now(UTC).isoformat()
    _save(lab, repo, record)
    _save_missing_context(lab, api_url, repo)
    return record


def restart(
    lab: int, *, api_url: str, dsn: str | None, repo: Path = REPO, say: Say = print
) -> dict[str, Any]:
    """Discard the entered lab's edits and prepare it again from its starting code."""
    assert_workshop_database(dsn)
    with _connect(dsn) as connection:
        problems = unmet_prerequisites(lab, connection, repo)
    # A SQL lab's reset applies both SQL files, so the other one must apply as it is;
    # this lab's own file is rebuilt whole below.
    for other in SQL_LABS if lab in SQL_LABS else ():
        changed = outside_block_problem(other, repo=repo) if other != lab else None
        if changed is not None and changed not in problems:
            problems.append(changed)
    if problems:
        raise LabEntryError(
            explain_problems(
                f"Lab {lab} cannot restart yet. Your Lab {lab} edits are unchanged.",
                problems,
                reset_command(lab),
            )
        )
    set_lab_state(lab, solved=False, repo=repo, whole_file=True)
    for path in (record_path(lab, repo), completion_path(lab, repo)):
        path.unlink(missing_ok=True)
    if lab == 1:
        (repo / ".local/lab-1/handoff.json").unlink(missing_ok=True)
    say(f"Discarded your Lab {lab} edits.")
    if lab == 1:
        # Lab 2's start applies its own file; Lab 1's start never edits or
        # applies, so the restored starting code is applied here.
        _apply(dsn, repo, say)
    return start(lab, api_url=api_url, dsn=dsn, repo=repo, say=say)


#: What each part of a saved handoff's binding means when it no longer matches.
_HANDOFF_BINDING = {
    "database": "DATABASE_URL selects a different database",
    "lab1_seam": "your LAB1_EDIT block changed",
    "lab1_sql": "your Lab 1 function changed",
    "lab1_entry": "Lab 1 was restarted",
}

LAB_1_WAITS_FOR_LAB_2 = (
    "Lab 2's ranking fault can hide a correct Lab 1 repair, so Lab 1 cannot be proved "
    "again until Lab 2 is repaired and applied."
)


def _handoff_mismatch(saved: dict[str, Any], current: dict[str, Any]) -> str:
    """Say what changed since Lab 1's evidence was saved, when Lab 2's fault blocks a new proof."""
    changed = "; ".join(
        text for key, text in _HANDOFF_BINDING.items() if saved.get(key) != current[key]
    )
    return (
        "Lab 1 cannot hand off yet.\n"
        f"- Since Lab 1 was validated, {changed}. {LAB_1_WAITS_FOR_LAB_2}\n"
        "Next: continue in the Lab 2 guide. Once Lab 2 is repaired and applied, run "
        f"{ADVANCE_TO_LAB_2} to prove Lab 1 again. Your edits are unchanged."
    )


def _lab_1_binding(dsn: str | None, repo: Path) -> dict[str, Any]:
    return {
        "database": hashlib.sha256((dsn or "").encode()).hexdigest(),
        "lab1_seam": _seam_sha256(1, (repo / LABS[1][0]).read_text()),
        "lab1_sql": sql_identity(1, repo),
        "lab1_entry": load_record(1, repo),
    }


def _read_handoff(repo: Path) -> dict[str, Any] | None:
    """Lab 1's saved handoff evidence, or None when it is absent or unusable.

    An unusable file is left where it is; the next passing proof replaces it.
    """
    try:
        saved = json.loads((repo / ".local/lab-1/handoff.json").read_text())
    except (OSError, ValueError):
        return None
    if not (
        isinstance(saved, dict)
        and isinstance(saved.get("binding"), dict)
        and evidence_problem(saved) is None
    ):
        return None
    return saved


def lab_1_waits_for_lab_2(dsn: str | None, repo: Path = REPO) -> bool:
    """Whether Lab 1 cannot be proved yet because Lab 2's ranking fault can hide it.

    False when Lab 1's saved handoff still matches, since proving it again then reuses
    that evidence instead of searching.
    """
    if not _lab_2_masks_lab_1(dsn, repo):
        return False
    return not _lab_1_handoff_matches(dsn, repo)


def lab_1_handoff_restores_proof(dsn: str | None, repo: Path = REPO) -> bool:
    """Whether `advance --lab 1` would rebuild Lab 1's proof from its saved handoff.

    While Lab 2's fault can hide Lab 1, a fresh request cannot prove Lab 1, but a
    handoff that still matches the repair proves it without a search.
    """
    return _lab_2_masks_lab_1(dsn, repo) and _lab_1_handoff_matches(dsn, repo)


def _lab_2_masks_lab_1(dsn: str | None, repo: Path) -> bool:
    try:
        begun = load_record(2, repo) is not None
    except StartRecordError:
        begun = True
    return begun and lab_2_can_mask(dsn, repo)


def _lab_1_handoff_matches(dsn: str | None, repo: Path) -> bool:
    saved = _read_handoff(repo)
    try:
        return saved is not None and saved["binding"] == _lab_1_binding(dsn, repo)
    except (OSError, ValueError):
        return False


def _passed(lab: int, count: int) -> str:
    """The hand-off's verdict in one green line, which stays in view when PASS lines scroll."""
    passed = tint(f"all {count} checks passed", GREEN)
    return f"Lab {lab}: {passed}. Passing evidence saved."


def advance(
    lab: int, *, api_url: str, dsn: str | None, repo: Path = REPO, say: Say = print
) -> dict[str, Any]:
    """Prove a SQL lab live, save its evidence, then prepare the next lab.

    Raises:
        LabEntryError: The lab has no handoff, or its repair is not ready to prove.
        LabValidationError: A live check failed; nothing for the next lab changed.
    """
    if lab in {1, 2} and (missing := missing_file_problem(lab, repo)):
        raise LabEntryError(missing.line)
    if lab == 1:
        return _advance_lab_1(api_url=api_url, dsn=dsn, repo=repo, say=say)
    if lab == 2:
        return _advance_lab_2(api_url=api_url, dsn=dsn, repo=repo, say=say)
    raise LabEntryError(
        f"Handoff rule: found Lab {lab}; fix: use advance --lab 1 or advance --lab 2. "
        f"Lab 3 ends when {grade_setup_run_command()} passes on your setup run."
    )


def _advance_lab_2(
    *, api_url: str, dsn: str | None, repo: Path, say: Say
) -> dict[str, Any]:
    """Prove Lab 2, then install the Retrieval agent's starting code; safe to rerun.

    Unlike Lab 2's ranking fault under Lab 1, the Retrieval agent's starting code never
    touches the searches Lab 2's checks run, so every rerun proves Lab 2 again
    rather than reusing saved evidence, and a started Lab 3 keeps its edits.
    """
    from scripts.prove_lab import prove_lab_2, record_completion
    from service.lab_proof import entry_check

    entered = entry_check(2, repo)
    if not entered.passed:
        raise LabEntryError(f"Lab 2 cannot hand off yet.\n- {entered.detail}")
    assert_workshop_database(dsn)
    _apply_saved_repairs(3, dsn, repo, say)
    with _connect(dsn) as connection:
        problems = unmet_prerequisites(3, connection, repo)
    if problems:
        raise LabEntryError(
            explain_problems("Lab 2 cannot hand off yet.", problems, ADVANCE_TO_LAB_3)
        )
    events: list[str] = []
    proof = completion_binding(2, repo)
    say(
        "Validating Lab 2 in Aurora: Alex's monitor request, then the requests that "
        "must still work…"
    )
    checks = prove_lab_2(api_url, events, rerun=ADVANCE_TO_LAB_3)
    for check in checks:
        say(verdict(f"PASS: {check}"))
    record_completion(2, checks, events, repo, proof)
    say("\n" + _passed(2, len(checks)))
    say("\nPreparing Lab 3: install the Retrieval agent's starting code once.")
    record = start(3, api_url=api_url, dsn=dsn, repo=repo, say=say)
    say(
        "\n"
        + tint("Lab 3: prepared.", BOLD)
        + " Continue in the Lab 3 guide. Your existing edits are preserved."
    )
    return record


def lab_2_can_mask(dsn: str | None, repo: Path) -> bool:
    """Whether Lab 2's saved block or the SQL Aurora runs still collapses ranks."""
    with _connect(dsn) as connection:
        return bool(
            source_problem(2, repo=repo)
            or applied_problem(2, read_applied_sql_state(2, connection, repo=repo))
        )


def _advance_lab_1(
    *, api_url: str, dsn: str | None, repo: Path, say: Say
) -> dict[str, Any]:
    """Prove Lab 1 before preparing Lab 2; resume without replaying masked checks.

    The handoff saves its own verified evidence before installing the ranking
    fault. It is bound to this database, Lab 1 entry and repaired seam, so a
    reset or a changed repair cannot silently reuse it.
    """
    from scripts.prove_lab import prove_lab_1, record_completion

    assert_workshop_database(dsn)
    _apply_saved_repairs(2, dsn, repo, say)
    with _connect(dsn) as connection:
        problems = unmet_prerequisites(2, connection, repo)
    if problems:
        raise LabEntryError(
            explain_problems("Lab 1 cannot hand off yet.", problems, ADVANCE_TO_LAB_2)
        )
    binding = _lab_1_binding(dsn, repo)
    path = repo / ".local/lab-1/handoff.json"
    saved = _read_handoff(repo)
    if saved is not None and saved["binding"] == binding:
        say(
            "Lab 1: using saved handoff validation; not repeating it under Lab 2's ranking fault."
        )
        if read_completion(1, repo).state != "valid":
            # The handoff is bound to this attempt and block, so it vouches for a
            # completion that is missing, cut off or written before receipts named them.
            record_completion(1, saved["checks"], saved["search_event_ids"], repo)
            if read_completion(1, repo).state != "valid":
                raise LabEntryError(
                    "Lab 1 cannot hand off: its saved completion did not validate "
                    f"({read_completion(1, repo).detail}).\n"
                    f"Next: run {ADVANCE_TO_LAB_2} again; your edits are unchanged."
                )
    else:
        # Lab 2's ranking fault can hide a correct Lab 1 repair; once Lab 2 is
        # repaired and applied it cannot, so Lab 1 is validated again. That also
        # covers a repair edited after its handoff (a reset of Lab 1 removes it).
        if load_record(2, repo) is not None and lab_2_can_mask(dsn, repo):
            if saved is not None:
                raise LabEntryError(_handoff_mismatch(saved["binding"], binding))
            damaged = (repo / ".local/lab-1/handoff.json").exists()
            raise LabEntryError(
                "Lab 1 cannot hand off: "
                + (
                    "its saved hand-off evidence is incomplete."
                    if damaged
                    else "Lab 2 was started directly, before Lab 1's passing evidence "
                    "was saved."
                )
                + "\n"
                f"Next: continue in the Lab 2 guide. {LAB_1_WAITS_FOR_LAB_2} Your edits "
                "are unchanged."
            )
        events: list[str] = []
        proof = completion_binding(1, repo)
        say(
            "Validating Lab 1 in Aurora: the mistyped-ID request, "
            "then two searches that must still work…"
        )
        checks = prove_lab_1(api_url, events, rerun=ADVANCE_TO_LAB_2)
        for check in checks:
            say(verdict(f"PASS: {check}"))
        record_completion(1, checks, events, repo, proof)
        saved = {"binding": binding, "checks": checks, "search_event_ids": events}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(saved, indent=2) + "\n")
        temporary.replace(path)
        say("\n" + _passed(1, len(checks)))
    resumed = bool((load_record(2, repo) or {}).get("completed_at"))
    say("\nPreparing Lab 2: install its fault once and save the starting request.")
    record = start(2, api_url=api_url, dsn=dsn, repo=repo, say=say, handoff=True)
    say(
        "\n"
        + tint("Lab 2: already prepared;", BOLD)
        + " continue where you left off in the Lab 2 guide. Your existing edits are preserved."
        if resumed
        else "\n"
        + tint("Lab 2: prepared.", BOLD)
        + " Continue with the saved failure in the Lab 2 guide. "
        "Your existing edits are preserved."
    )
    return record
