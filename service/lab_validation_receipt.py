"""Replay a participant's Lab 3 validation against current Aurora records.

The file carries run identities, never a cached verdict or model answer. Reuse
requires the same code, configuration and API, then grades the persisted runs
and current evidence again without another model invocation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from service import lab_checks
from service.config import get_settings
from service.db import connect
from service.lab_files import LAB3_AGENT
from service.lab_proof import (
    _persisted_mission_checks,
    _persisted_run,
    lab_states,
)
from service.retrieval_fingerprint import (
    compute_live_retrieval_settings_sha256,
    compute_retrieval_fingerprint,
    manifest_files,
)
from service.search_sql import search_sql
from service.telemetry_contract import load_agent_turn_rows

ROOT = Path(__file__).resolve().parents[1]


def _code_files(root: Path) -> list[Path]:
    return (
        sorted((root / "service").rglob("*.py"))
        + sorted((root / "deploy/agentcore").glob("*.py"))
        + [
            root / LAB3_AGENT,
            root / "scripts/validate_lab.py",
            root / "scripts/lab_state.py",
            root / "scripts/evidence_registration_probe.py",
            root / "scripts/agent_assembly_probe.py",
            root / "scripts/package_agentcore.py",
            root / "scripts/deploy_agentcore.py",
            root / "scripts/lab_exercise.py",
            root / "scripts/complete_agent.py",
            root / "uv.lock",
        ]
    )


def _digest(seed: str, root: Path, files: list[Path]) -> str:
    digest = hashlib.sha256(seed.encode())
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def source_digest(root: Path = ROOT) -> str:
    """Bind agent code and its validators as well as the retrieval closure.

    The combined identity a saved Lab 3 validation commits to: code, retrieval
    configuration and the participant's SQL together.
    """
    return _digest(compute_retrieval_fingerprint(root), root, _code_files(root))


def application_digest(root: Path = ROOT) -> str:
    """Identity of the code the deployed Runtime and SQL tools execute.

    SQL is left out on purpose. The tools call the functions Aurora holds, which
    `scripts/apply_search_functions.py` installs, so a Lab 1 or Lab 2 edit changes
    what Aurora must run, not what Runtime must run; `participant_sql_digest`
    and the applied-SQL record in Aurora carry that identity instead.
    """
    configuration = [path for path in manifest_files(root) if path.suffix != ".sql"]
    return _digest("application", root, configuration + _code_files(root))


def participant_sql_digest(root: Path = ROOT) -> str:
    """Identity of the search SQL, with the participant's lab files, as it stands.

    `scripts/apply_search_functions.py` installs exactly this text, so the
    digest it records in Aurora can be compared with the workspace.
    """
    return hashlib.sha256(search_sql(root).encode("utf-8")).hexdigest()


def validation_identity(base_url: str, readiness: dict[str, Any]) -> dict[str, Any]:
    """Capture the environment the participant's validation actually uses."""
    settings = get_settings()
    if not settings.database_url:
        raise ValueError(
            "found no DATABASE_URL; fix: load the Mosaic Aurora environment"
        )
    # The receipt travels with the participant, so it commits to the cluster
    # identity (host and database name) and never to a digest of the full
    # DSN, which carries the password.
    dsn = urlsplit(settings.database_url)
    database_identity = f"{dsn.hostname or ''}:{dsn.port or ''}{dsn.path or ''}"
    return {
        "api_url": base_url.rstrip("/"),
        "source": {
            key: readiness["source"][key]
            for key in ("revision", "dataset_manifest_sha256")
        },
        "models": readiness["configured_models"],
        "source_sha256": source_digest(),
        "settings_sha256": compute_live_retrieval_settings_sha256(),
        "database_sha256": hashlib.sha256(database_identity.encode()).hexdigest(),
    }


def replay_receipt(
    receipt: dict[str, Any], identity: dict[str, Any]
) -> list[lab_checks.LabCheck]:
    """Recheck both canonical agent runs, current seams and citation records.

    Raises:
        ValueError: The receipt is stale, incomplete, or no longer resolves.
    """
    if receipt.get("version") != 1 or receipt.get("identity") != identity:
        raise ValueError(
            "found a Lab 3 receipt from different code or settings; "
            "fix: rerun validate_lab.py --lab 3 --save-receipt PATH"
        )
    missions = [
        lab_checks.load_mission("reason"),
        lab_checks.load_case("evidence-grounding"),
    ]
    runs = receipt.get("runs")
    expected = [mission["canonical_query_id"] for mission in missions]
    if not isinstance(runs, dict) or set(runs) != set(expected):
        raise ValueError(
            f"found Lab 3 run keys {list(runs) if isinstance(runs, dict) else runs}; "
            f"fix: run both {expected} through the Lab 3 validator"
        )
    states = lab_states().labs
    if {state.lab_id for state in states} != {1, 2, 3}:
        raise ValueError(
            "found incomplete lab states; fix: restore all three lab checks"
        )
    for state in states:
        if state.source_state != "solved" or state.database_state == "stale":
            raise ValueError(
                f"found Lab {state.lab_id}: {state.detail}; "
                "fix: repair and apply the lab before reusing its validation"
            )
    checks = []
    for mission in missions:
        try:
            run_id = UUID(runs[mission["canonical_query_id"]])
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError(
                f"found invalid {mission['canonical_query_id']} run ID; "
                "fix: save a fresh Lab 3 validation"
            ) from error
        with connect() as connection:
            rows = load_agent_turn_rows(connection, run_id)
        run = _persisted_run(rows) if rows else None
        if rows is None or rows.turn.get("user_message") != mission["query"]:
            raise ValueError(
                f"found missing or different {mission['canonical_query_id']} run {run_id}; "
                "fix: save a fresh Lab 3 validation in this Aurora environment"
            )
        checks.extend(_persisted_mission_checks(mission, rows, run, str(run_id)))
        checks.extend(
            lab_checks.lab_3_proof_checks(mission, run, requested_run_id=str(run_id))
        )
    return checks


def read_receipt(path: Path) -> dict[str, Any]:
    """Read the small run manifest with an actionable malformed-file error."""
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise TypeError("expected an object")
        return value
    except (OSError, TypeError, ValueError) as error:
        raise ValueError(
            f"found unreadable Lab 3 receipt {path}: {error}; "
            "fix: rerun validate_lab.py --lab 3 --save-receipt PATH"
        ) from error
