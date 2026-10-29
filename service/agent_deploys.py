"""The Retrieval agent deploys made from this workspace, read when Lab 3 asks and proves.

AgentCore Runtime refuses to run code other than the workspace's, but it compares code
digests only. The account is provisioned with the reference Retrieval agent, whose digest
is the reference answer's, so after Lab 3 starts a pasted reference answer would answer,
and pass, on the provisioned runtime without a deploy. `scripts/deploy_agentcore.py
deploy` records each deploy here once the Retrieval agent runtime is ready on its new
version. Provisioning records nothing and `verify` deploys nothing, so neither counts.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from service.participant_commands import DEPLOY_AGENT, complete_lab_3, reset

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Deploy:
    """When a deploy's Retrieval agent runtime version was ready, and the code it runs."""

    deployed_at: datetime
    runtime_version: str
    application_sha256: str


def _aware(moment: datetime) -> datetime:
    """A timestamp without a zone was written by this workspace's tools in UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def deploys_path(root: Path | None = None) -> Path:
    """Where the record lives; the workspace root is read at call time, so tests can move it."""
    return (root or ROOT) / ".local" / "agentcore" / "deploys.json"


def load_deploys(root: Path | None = None) -> list[Deploy]:
    """Every recorded deploy, oldest first.

    Raises:
        ValueError: The record exists but cannot be read; a deploy rewrites it.
    """
    path = deploys_path(root)
    if not path.exists():
        return []
    try:
        deploys = sorted(
            (
                Deploy(
                    _aware(datetime.fromisoformat(row["deployed_at"])),
                    str(row["runtime_version"]),
                    str(row["application_sha256"]),
                )
                for row in json.loads(path.read_text(encoding="utf-8"))
            ),
            key=lambda deploy: deploy.deployed_at,
        )
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError(
            f"Deploy record rule: {path} cannot be read ({type(error).__name__}); "
            f"fix: deploy with {DEPLOY_AGENT}, which writes it again."
        ) from error
    return deploys


def record_deploy(
    runtime_version: str,
    application_sha256: str,
    *,
    root: Path | None = None,
    now: datetime | None = None,
) -> Deploy:
    """Add one deploy to the record; an unreadable record is replaced, not extended.

    The read-modify-write holds a file lock, so two deploys recorded together both
    survive, and the record is replaced atomically from a temporary file of its own.
    """
    path = deploys_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    deploy = Deploy(
        _aware(now or datetime.now(UTC)), runtime_version, application_sha256
    )
    with (path.parent / "deploys.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            earlier = load_deploys(root)
        except ValueError:
            earlier = []
        rows = [
            {
                "deployed_at": item.deployed_at.isoformat(),
                "runtime_version": item.runtime_version,
                "application_sha256": item.application_sha256,
            }
            for item in [*earlier, deploy]
        ]
        with tempfile.NamedTemporaryFile(
            "w", dir=path.parent, suffix=".tmp", delete=False, encoding="utf-8"
        ) as temporary:
            temporary.write(json.dumps(rows, indent=2) + "\n")
        os.replace(temporary.name, path)
    return deploy


def lab_3_started_at(root: Path | None = None) -> datetime | None:
    """When Lab 3 last started (Lab 2's hand-off, a start or a reset), or None."""
    from scripts.lab_entry import load_record

    try:
        started = (load_record(3, root or ROOT) or {}).get("completed_at")
        return _aware(datetime.fromisoformat(started)) if started else None
    except (OSError, AttributeError, TypeError, ValueError) as error:
        # A hand-edited, truncated or unreadable record would otherwise be a bare 500.
        raise ValueError(
            f"Lab 3 start record rule: the saved start of Lab 3 cannot be read "
            f"({type(error).__name__}); fix: run {reset(3)}."
        ) from error


def _clock(moment: datetime) -> str:
    return f"{moment.astimezone(UTC):%H:%M} UTC"


def _since(started: datetime, root: Path | None) -> list[Deploy]:
    return [deploy for deploy in load_deploys(root) if deploy.deployed_at > started]


REFERENCE_AGENT_NOTICE = (
    "This answer comes from the reference Retrieval agent this account was prepared with. "
    "In Lab 3 you build and deploy your own, and from then on your questions go to it."
)


def reference_agent_notice(*, root: Path | None = None) -> str | None:
    """What to tell someone whose question the provisioned reference agent answers, or None.

    That is every question before Lab 3 starts; from the start, `ask_problem` holds a
    question until the participant's own deploy carries today's code.
    """
    return REFERENCE_AGENT_NOTICE if lab_3_started_at(root) is None else None


def ask_problem(workspace_sha256: str, *, root: Path | None = None) -> str | None:
    """Why a question must wait for a deploy, or None when Runtime runs today's code.

    Before Lab 3 starts nothing is asked of the participant: the provisioned reference
    Retrieval agent answers. Afterwards the latest deploy since the start must carry
    the workspace's code. Runtime's own digest check stays behind this one; this one
    says which command is missing before a request reaches Runtime.
    """
    started = lab_3_started_at(root)
    if started is None:
        return None
    since = _since(started, root)
    if not since:
        return (
            "Your Retrieval agent has not been deployed since Lab 3 started at "
            f"{_clock(started)}, so AgentCore Runtime still runs the reference Retrieval "
            "agent this account was prepared with. "
            f"Next: deploy with {DEPLOY_AGENT}, then ask your question again."
        )
    latest = since[-1]
    if latest.application_sha256 != workspace_sha256:
        return (
            f"Your code in Code Editor changed after your deploy at {_clock(latest.deployed_at)}, "
            "so AgentCore Runtime still runs the earlier code. "
            f"Next: deploy with {DEPLOY_AGENT}, then ask your question again."
        )
    return None


def run_deploy_problem(
    run_created_at: datetime, run_sha256: object, *, root: Path | None = None
) -> str | None:
    """Why a Lab 3 run did not come from the participant's own deploy, or None.

    The run must have been made after a deploy since Lab 3 started that carried the
    code the run recorded. A lab that has not started is the entry check's to report.
    """
    started = lab_3_started_at(root)
    if started is None:
        return None
    run_created_at = _aware(run_created_at)
    since = _since(started, root)
    if not since:
        return (
            f"You have not deployed since Lab 3 started at {_clock(started)}, so this run "
            "came from the reference Retrieval agent this account was prepared with. "
            f"Next: deploy with {DEPLOY_AGENT}, ask Alex's setup request again, then run "
            f"{complete_lab_3()}."
        )
    if any(
        deploy.application_sha256 == run_sha256 and deploy.deployed_at <= run_created_at
        for deploy in since
    ):
        return None
    return (
        f"This run, made at {_clock(run_created_at)}, did not come from a deploy of yours "
        f"since Lab 3 started; your first was at {_clock(since[0].deployed_at)}. "
        f"Next: ask Alex's setup request again, then run {complete_lab_3()}."
    )
