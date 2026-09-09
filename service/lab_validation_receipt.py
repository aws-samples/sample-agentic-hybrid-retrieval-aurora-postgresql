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
from uuid import UUID

from service import lab_checks
from service.config import get_settings
from service.db import connect
from service.lab_proof import (
    _persisted_mission_checks,
    _persisted_run,
    lab_states,
)
from service.retrieval_fingerprint import (
    compute_live_retrieval_settings_sha256,
    compute_retrieval_fingerprint,
)
from service.telemetry_contract import load_agent_turn_rows

ROOT = Path(__file__).resolve().parents[1]


def source_digest(root: Path = ROOT) -> str:
    """Bind agent code and its validators as well as the retrieval closure."""
    files = sorted((root / "service").rglob("*.py")) + [
        root / "scripts/validate_lab.py",
        root / "scripts/lab_state.py",
        root / "uv.lock",
    ]
    digest = hashlib.sha256(compute_retrieval_fingerprint(root).encode())
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def validation_identity(base_url: str, readiness: dict[str, Any]) -> dict[str, Any]:
    """Capture the environment the participant's validation actually uses."""
    settings = get_settings()
    if not settings.database_url:
        raise ValueError(
            "found no DATABASE_URL; fix: load the Mosaic Aurora environment"
        )
    return {
        "api_url": base_url.rstrip("/"),
        "source": {
            key: readiness["source"][key]
            for key in ("revision", "dataset_manifest_sha256")
        },
        "models": readiness["configured_models"],
        "source_sha256": source_digest(),
        "settings_sha256": compute_live_retrieval_settings_sha256(),
        "database_sha256": hashlib.sha256(settings.database_url.encode()).hexdigest(),
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
