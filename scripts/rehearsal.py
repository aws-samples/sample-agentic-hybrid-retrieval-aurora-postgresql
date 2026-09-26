"""Record a clean-account Workshop Studio rehearsal as one evidence manifest.

`READINESS.md`'s "Clean-account acceptance test" names eleven steps a
maintainer must run and record on a fresh Aurora deployment before a release
is ready. Nothing in this repository turned that list into a machine-readable
artifact: rehearsals happened, if at all, as a paragraph in a chat log. This
script is the runner for that list. It never deploys, provisions, or resets
anything itself -- it records what an operator already ran, plus a handful of
read-only measurements (a live cold/warm HTTP call, a local file hash, `git
rev-parse`) that are safe to take from this repository's own worktree.

Usage, in the order a rehearsal actually happens:

    uv run python scripts/rehearsal.py init --output build/rehearsal-evidence.json \\
        --operator "<name>" --workshop-studio-stack-id <stack-id> --aws-region us-east-1

    # after CloudFormation reports CREATE_COMPLETE and readiness reports "ready"
    uv run python scripts/rehearsal.py capture-identity \\
        --manifest build/rehearsal-evidence.json --api-url https://<stack-host> \\
        --started-at ... --ended-at ...

    # right after capture-identity, while the deployment is fresh
    uv run python scripts/rehearsal.py record-first-query \\
        --manifest build/rehearsal-evidence.json --api-url https://<stack-host>

    # after `aws s3 sync` + `real_catalog_cache.py join` on the Code Editor host
    uv run python scripts/rehearsal.py record-stage \\
        --manifest build/rehearsal-evidence.json --stage archive_transfer_and_join \\
        --status passed --detail "3 parts synced, sha256 join verified against
        db/config/real-catalog-cache.json" --started-at ... --ended-at ...

    # after `make db-bootstrap-schema`
    uv run python scripts/rehearsal.py import-bootstrap-timings \\
        --manifest build/rehearsal-evidence.json \\
        --timings-file build/bootstrap-timings.tsv

    # after `scripts/real_catalog_cache.py restore` and its printed verification
    uv run python scripts/rehearsal.py record-stage \\
        --manifest build/rehearsal-evidence.json --stage catalog_restore_verification \\
        --status passed --detail "553911 real products, 553911 saved vectors, no synthetic rows"

    # after each lab's reset/solution/validate cycle
    uv run python scripts/rehearsal.py record-stage \\
        --manifest build/rehearsal-evidence.json --stage lab_1_rehearsal \\
        --status passed --detail "reset isolated; solution applied; validate-lab-1 PASS" \\
        --artifact .local/lab-1-validation.log

    # live cold/warm calls against the running deployment
    uv run python scripts/rehearsal.py record-cold-warm \\
        --manifest build/rehearsal-evidence.json --target reranker --condition cold \\
        --api-url https://<stack-host>
    uv run python scripts/rehearsal.py record-cold-warm \\
        --manifest build/rehearsal-evidence.json --target ask_mosaic --condition warm \\
        --api-url https://<stack-host>

    # visual walkthrough
    uv run python scripts/rehearsal.py record-layout \\
        --manifest build/rehearsal-evidence.json --device projector --status ok \\
        --detail "readiness strip and lab cards legible at 1080p from the back row"

    # once every stage above is recorded
    uv run python scripts/rehearsal.py compute-timing-summary \\
        --manifest build/rehearsal-evidence.json
    uv run python scripts/rehearsal.py validate --manifest build/rehearsal-evidence.json
    uv run python scripts/rehearsal.py summary --manifest build/rehearsal-evidence.json

No subcommand here ever runs `make`, `psql`, or an AWS mutation. The operator
runs the real command in their own authorized shell and hands this script the
resulting facts (timestamps, exit status, a short detail sentence, a path to
the saved log). That keeps this tool honest about what it can prove: it can
prove the manifest is well-formed and secret-free; it cannot prove the
operator told it the truth about what ran. Cross-checking `record-stage`
details against saved artifacts is a reviewer's job, which is why every stage
requires an `--artifact` path wherever one exists to check.

Manifest schema (schema_version 1, kind "measured" -- see docs/rehearsal-runbook.md):

    {
      "schema_version": 1,
      "kind": "measured",
      "recorded_at": "<ISO-8601 UTC, updated on every write>",
      "operator": "<free text, no PII beyond what the operator chooses>",
      "environment": {
        "workshop_studio_stack_id": str | null,
        "aws_region": str | null,
        "api_base_url": str | null,
        "source_revision": "<git sha or 'unknown'>",
        "source_worktree_dirty": bool,
        "bootstrap_script_sha256": "<sha256 of deploy/mosaic-bootstrap.sh>",
        "served": {"health": {...}, "readiness": {...}} | null
      },
      "dataset_identity": {
        "expected_dataset_id": "<dataset_id from the pinned catalog contract>",
        "expected_catalog_sha256": "<catalog_sha256 from the pinned contract>",
        "real_catalog_cache_contract_sha256": "<sha256 of db/config/real-catalog-cache.json>",
        "corpus_vocabulary_contract_sha256": "<sha256 of db/config/corpus-vocabulary-cache.json>",
        "served_dataset_id": str | null,
        "served_catalog_sha256": str | null
      },
      "effective_settings": {"retrieval_profile": {...}, "configured_models": {...} | null},
      "session_contract": {"total_minutes": 60, "orientation_minutes": 10,
                            "core_lab_minutes": 40, "contingency_minutes": 10,
                            "required_lab_count": 3},
      "stages": {
        "<name in REQUIRED_STAGES>": {
          "status": "not_started" | "passed" | "failed" | "skipped",
          "detail": str,
          "started_at": str | null,
          "ended_at": str | null,
          "elapsed_seconds": number | null,
          "artifact_paths": [str, ...],
          ... stage-specific fields (phases, cold, warm, devices,
          first_query_ms on deployment_identity) ...
        },
        ...
      },
      "overall_status": "not_started" | "in_progress" | "complete" | "blocked",
      "blockers": [str, ...]
    }

`validate_manifest()` is the schema check; it rejects a manifest missing any
of the eleven `REQUIRED_STAGES` and rejects one whose serialized JSON contains
a credential-shaped value (a DSN with an embedded password, an AWS access key
ID, a bearer token, or a `password=`/`secret=`-style assignment). Both
conditions have permanent fixtures in `tests/test_rehearsal.py`, proven red at
birth per `docs/house-standards.md` rule 4.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SCHEMA_VERSION = 1
#: Distinguishes a recorded rehearsal from `scripts/simulate_scale.py`'s
#: `projection_kind: "simulated_calibrated"` output and from
#: `data/benchmarks/hnsw_measured.json`'s own `kind` field, which this
#: mirrors on purpose: "measured" means someone watched it happen.
MANIFEST_KIND = "measured"

BOOTSTRAP_SCRIPT = REPO / "deploy" / "mosaic-bootstrap.sh"
REAL_CATALOG_CACHE_CONTRACT = REPO / "db" / "config" / "real-catalog-cache.json"
CORPUS_VOCABULARY_CONTRACT = REPO / "db" / "config" / "corpus-vocabulary-cache.json"
MISSIONS_FILE = REPO / "data" / "evals" / "mosaic_labs_missions.json"
DEFAULT_BOOTSTRAP_TIMINGS = REPO / "build" / "bootstrap-timings.tsv"

#: The eleven items in READINESS.md's "Clean-account acceptance test", in
#: order. A manifest missing any of these is not a rehearsal record, whatever
#: else it contains.
REQUIRED_STAGES: tuple[str, ...] = (
    "deployment_identity",
    "archive_transfer_and_join",
    "bootstrap_phases",
    "catalog_restore_verification",
    "lab_1_rehearsal",
    "lab_2_rehearsal",
    "lab_3_rehearsal",
    "reranker_cold_warm",
    "ask_mosaic_cold_warm",
    "timing_summary",
    "layout_walkthrough",
)

ALLOWED_STAGE_STATUS = ("not_started", "passed", "failed", "skipped")
LAYOUT_DEVICES = ("laptop", "tablet", "mobile", "projector")
COLD_WARM_TARGETS = ("reranker", "ask_mosaic")
COLD_WARM_CONDITIONS = ("cold", "warm")

DEFAULT_RERANK_QUESTION = (
    "wireless noise-cancelling headphones under $200"  # a Lab 1-shaped query
)
DEFAULT_ASK_MOSAIC_QUESTION = (
    "Compare quiet mechanical keyboards for shared-office calls under $200"
)


class RehearsalError(RuntimeError):
    """A manifest, an argument, or a live response failed a named rule."""


def explain(found: str, fix: str) -> str:
    """House style (docs/house-standards.md rule 1): name the value, name the fix."""
    return f"found {found}; fix: {fix}"


# --------------------------------------------------------------------------
# Secret detection and redaction
# --------------------------------------------------------------------------

#: Patterns a manifest must never contain, serialized or not. Matched against
#: the full JSON text so a leak nested three keys deep is still caught.
#: Deliberately narrow: a bare `secret` or `token` in prose (e.g. this
#: docstring) must not trip the gate, only a value that carries one.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "a DSN with an embedded password",
        re.compile(r"postgres(?:ql)?://[^:/\s@\"]+:[^@\s\"]+@"),
    ),
    ("an AWS access key ID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("a bearer token", re.compile(r"[Bb]earer\s+[A-Za-z0-9\-_.=]{16,}")),
    (
        "a password/secret/token assignment",
        re.compile(
            # `\\?["']?` rather than `["']?`: this scans the *serialized* JSON
            # text, where an embedded literal quote is escaped as a literal
            # backslash followed by a literal quote (`\"`), two characters,
            # not one. Matching only `["']?` let a quoted value like
            # `"password: \"hunter2...\""` slip through with zero characters
            # consumed after the colon, because the lone backslash isn't a
            # quote and the mandatory run below excludes the quote itself.
            # `security[_-]?token` also matches an `x-amz-security-token`
            # header or query-parameter name, since the match only needs to
            # find that substring followed by `:`/`=` and a value -- it does
            # not need to anchor on the `x-amz-` prefix.
            r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?key|"
            r"auth[_-]?token|session[_-]?token|security[_-]?token)\b\s*[:=]\s*"
            r"\\?[\"']?[^\s\"',}]{6,}"
        ),
    ),
    (
        # Workshop Studio's Code Editor URL carries a bare `tkn=` query
        # parameter (deploy/README.md); `token=` is the generic form of the
        # same shape. Neither is a "password/secret/..."-prefixed assignment
        # above, so it needs its own pattern rather than another keyword.
        "a tkn= or token= query parameter",
        re.compile(r"(?i)[?&]?\b(?:tkn|token)\b=[^\s\"'&,}]{6,}"),
    ),
)

#: The redaction side of the same rules, applied to free-text fields
#: (`detail`, `--field` values) before they are written to disk. This is
#: defense in depth: the manifest a maintainer builds by hand should never
#: contain a raw secret in the first place, and `validate_manifest` refuses
#: one that slips through.
_REDACTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    pattern for _, pattern in _SECRET_PATTERNS
)


def redact(text: str) -> str:
    """Replace every secret-shaped substring in `text` with `[REDACTED]`."""
    redacted = text
    for pattern in _REDACTION_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def find_secret_leaks(manifest: dict[str, Any]) -> list[str]:
    """Return one message per secret-shaped substring found anywhere in `manifest`."""
    serialized = json.dumps(manifest)
    problems = []
    for label, pattern in _SECRET_PATTERNS:
        if pattern.search(serialized):
            problems.append(
                explain(
                    f"what looks like {label} inside the manifest",
                    "remove or redact the value before recording it; "
                    "record-stage and record-cold-warm redact free-text "
                    "fields automatically, so a raw secret usually entered "
                    "through a hand-edited --field or a pasted --detail",
                )
            )
    return problems


# --------------------------------------------------------------------------
# Manifest construction and I/O
# --------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _empty_stage() -> dict[str, Any]:
    return {
        "status": "not_started",
        "detail": "",
        "started_at": None,
        "ended_at": None,
        "elapsed_seconds": None,
        "artifact_paths": [],
    }


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_revision(repo: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "unknown"


def _git_dirty(repo: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return bool(result.stdout.strip())
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return True


def _session_contract() -> dict[str, Any]:
    if not MISSIONS_FILE.is_file():
        return {}
    missions = json.loads(MISSIONS_FILE.read_text(encoding="utf-8"))
    session = dict(missions.get("session", {}))
    session["required_lab_count"] = len(
        {mission["stage"] for mission in missions.get("missions", [])}
    )
    return session


def new_manifest(
    *,
    operator: str = "",
    workshop_studio_stack_id: str | None = None,
    aws_region: str | None = None,
    api_base_url: str | None = None,
) -> dict[str, Any]:
    """Build an empty manifest with every required stage present but unrun."""
    catalog = json.loads(REAL_CATALOG_CACHE_CONTRACT.read_text(encoding="utf-8"))
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": MANIFEST_KIND,
        "recorded_at": _utc_now_iso(),
        "operator": redact(operator),
        "environment": {
            "workshop_studio_stack_id": workshop_studio_stack_id,
            "aws_region": aws_region,
            "api_base_url": api_base_url,
            "source_revision": _git_revision(REPO),
            "source_worktree_dirty": _git_dirty(REPO),
            "bootstrap_script_sha256": _sha256_file(BOOTSTRAP_SCRIPT),
            "served": None,
        },
        "dataset_identity": {
            "expected_dataset_id": catalog["dataset_id"],
            "expected_catalog_sha256": catalog["catalog_sha256"],
            "real_catalog_cache_contract_sha256": _sha256_file(
                REAL_CATALOG_CACHE_CONTRACT
            ),
            "corpus_vocabulary_contract_sha256": _sha256_file(
                CORPUS_VOCABULARY_CONTRACT
            ),
            "served_dataset_id": None,
            "served_catalog_sha256": None,
        },
        "effective_settings": {"retrieval_profile": None, "configured_models": None},
        "session_contract": _session_contract(),
        "stages": {name: _empty_stage() for name in REQUIRED_STAGES},
        "overall_status": "not_started",
        "blockers": [],
    }


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RehearsalError(
            explain(f"no manifest at {path}", "run the init subcommand first")
        )
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    manifest["recorded_at"] = _utc_now_iso()
    manifest["overall_status"] = compute_overall_status(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


# --------------------------------------------------------------------------
# Stage bookkeeping
# --------------------------------------------------------------------------


def _elapsed_seconds(started_at: str | None, ended_at: str | None) -> float | None:
    if not started_at or not ended_at:
        return None
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(ended_at)
    except ValueError:
        return None
    return max((end - start).total_seconds(), 0.0)


def upsert_stage(
    manifest: dict[str, Any],
    name: str,
    *,
    status: str,
    detail: str,
    started_at: str | None = None,
    ended_at: str | None = None,
    artifact_paths: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    if status not in ALLOWED_STAGE_STATUS:
        raise RehearsalError(
            explain(
                f"status {status!r} for stage {name!r}",
                f"use one of {', '.join(ALLOWED_STAGE_STATUS)}",
            )
        )
    stage = manifest.setdefault("stages", {}).setdefault(name, _empty_stage())
    stage["status"] = status
    stage["detail"] = redact(detail)
    stage["started_at"] = started_at
    stage["ended_at"] = ended_at
    stage["elapsed_seconds"] = _elapsed_seconds(started_at, ended_at)
    if artifact_paths:
        existing = set(stage.get("artifact_paths", []))
        stage["artifact_paths"] = sorted(existing | set(artifact_paths))
    if extra:
        stage.update(extra)


def compute_overall_status(manifest: dict[str, Any]) -> str:
    statuses = {
        name: manifest.get("stages", {}).get(name, _empty_stage())["status"]
        for name in REQUIRED_STAGES
    }
    if any(status == "failed" for status in statuses.values()):
        return "blocked"
    if all(status == "passed" for status in statuses.values()):
        return "complete"
    if any(status != "not_started" for status in statuses.values()):
        return "in_progress"
    return "not_started"


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return every problem with `manifest`; an empty list means it is valid."""
    problems: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        problems.append(
            explain(
                f"schema_version {manifest.get('schema_version')!r}",
                f"use schema_version {SCHEMA_VERSION}",
            )
        )
    if manifest.get("kind") != MANIFEST_KIND:
        problems.append(
            explain(
                f"kind {manifest.get('kind')!r}",
                f"set kind to {MANIFEST_KIND!r}; a simulated projection belongs in "
                "scripts/simulate_scale.py's output, never in a rehearsal manifest",
            )
        )
    stages = manifest.get("stages")
    if not isinstance(stages, dict):
        problems.append(explain("no stages object", "run init to create one"))
        stages = {}
    missing = [name for name in REQUIRED_STAGES if name not in stages]
    if missing:
        problems.append(
            explain(
                f"missing stage(s) {missing}",
                "record every stage in REQUIRED_STAGES, even as 'skipped' with a "
                "reason, before treating this manifest as a rehearsal record",
            )
        )
    for name, stage in stages.items():
        if not isinstance(stage, dict) or "status" not in stage:
            problems.append(
                explain(f"stage {name!r} with no status field", "record-stage it")
            )
            continue
        if stage["status"] not in ALLOWED_STAGE_STATUS:
            problems.append(
                explain(
                    f"stage {name!r} status {stage['status']!r}",
                    f"use one of {', '.join(ALLOWED_STAGE_STATUS)}",
                )
            )
        if (
            stage["status"] != "not_started"
            and not str(stage.get("detail", "")).strip()
        ):
            problems.append(
                explain(
                    f"stage {name!r} marked {stage['status']!r} with no detail",
                    "pass --detail describing what ran and what it showed",
                )
            )
    problems.extend(find_secret_leaks(manifest))
    return problems


# --------------------------------------------------------------------------
# Bootstrap timings
# --------------------------------------------------------------------------


def parse_bootstrap_timings(text: str) -> list[dict[str, Any]]:
    """Parse `make db-bootstrap-schema`'s `phase\\tseconds` TSV, `total` last."""
    phases = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            raise RehearsalError(
                explain(
                    f"malformed timings line {line!r}", "expected 'name<TAB>seconds'"
                )
            )
        name, seconds = parts
        try:
            phases.append({"name": name, "elapsed_seconds": float(seconds)})
        except ValueError as error:
            raise RehearsalError(
                explain(
                    f"non-numeric elapsed seconds {seconds!r} for {name!r}", str(error)
                )
            ) from error
    return phases


#: The bootstrap-phase order `Makefile`'s `db-bootstrap-schema` writes, from
#: `bootstrap-phase` calls plus the awk-computed `total` line. Used only to
#: decide whether the TSV looks complete, not to re-derive the timings.
_EXPECTED_BOOTSTRAP_PHASES = (
    "schema_install",
    "lab_schema_install",
    "smoke_test",
    "total",
)


def import_bootstrap_timings(
    manifest: dict[str, Any],
    timings_path: Path,
    *,
    started_at: str | None,
    ended_at: str | None,
    restore_report: Path | None = None,
) -> None:
    if not timings_path.is_file():
        upsert_stage(
            manifest,
            "bootstrap_phases",
            status="failed",
            detail=explain(
                f"no timings file at {timings_path}", "run make db-bootstrap-schema"
            ),
        )
        return
    phases = parse_bootstrap_timings(timings_path.read_text(encoding="utf-8"))
    found = {phase["name"] for phase in phases}
    missing = [name for name in _EXPECTED_BOOTSTRAP_PHASES if name not in found]
    total = next(
        (phase["elapsed_seconds"] for phase in phases if phase["name"] == "total"), None
    )
    status = "failed" if missing else "passed"
    detail = (
        f"{len(phases)} phases recorded, total {total:g}s"
        if total is not None
        else f"{len(phases)} phases recorded, no total row"
    )
    if missing:
        detail = explain(
            f"timings missing phase(s) {missing}",
            "re-run make db-bootstrap-schema to completion",
        )
    artifacts = [str(timings_path)]
    if restore_report is not None:
        report = json.loads(restore_report.read_text(encoding="utf-8"))
        restore_seconds = report.get("restore_seconds")
        indexes = report.get("index_ensure_seconds", {})
        durations = [restore_seconds, *indexes.values()]
        if not indexes or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
            for value in durations
        ):
            raise RehearsalError(
                explain(
                    f"invalid restore timings in {restore_report}",
                    "run real_catalog_cache.py restore --report with the pinned archive",
                )
            )
        phases.extend(
            [
                {"name": "catalog_restore", "elapsed_seconds": restore_seconds},
                {"name": "index_creation", "elapsed_seconds": sum(indexes.values())},
            ]
        )
        if total is not None:
            total += restore_seconds
        artifacts.append(str(restore_report))
        detail += f"; catalog restore {restore_seconds:g}s (includes index creation)"
    upsert_stage(
        manifest,
        "bootstrap_phases",
        status=status,
        detail=detail,
        started_at=started_at,
        ended_at=ended_at,
        artifact_paths=artifacts,
        extra={"phases": phases, "total_elapsed_seconds": total},
    )


# --------------------------------------------------------------------------
# Live HTTP calls (identity capture, cold/warm)
# --------------------------------------------------------------------------


def _http_get_json(client: Any, url: str, timeout: float) -> dict[str, Any]:
    import httpx

    try:
        response = client.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as error:
        raise RehearsalError(
            explain(
                f"{url} unreachable or non-2xx ({error})",
                "confirm the API is running and reachable",
            )
        ) from error


def _http_post_json(
    client: Any, url: str, payload: dict[str, Any], timeout: float
) -> tuple[dict[str, Any], int, float]:
    from time import perf_counter

    import httpx

    started = perf_counter()
    try:
        response = client.post(url, json=payload, timeout=timeout)
    except httpx.HTTPError as error:
        raise RehearsalError(
            explain(
                f"{url} unreachable ({error})",
                "confirm the API is running and reachable",
            )
        ) from error
    elapsed_ms = (perf_counter() - started) * 1_000
    if response.status_code >= 400:
        raise RehearsalError(
            explain(
                f"{url} returned HTTP {response.status_code}: {response.text[:300]}",
                "inspect the service logs before recording this as a cold/warm call",
            )
        )
    return response.json(), response.status_code, elapsed_ms


def capture_identity(
    manifest: dict[str, Any],
    *,
    api_url: str | None,
    timeout: float,
    started_at: str | None = None,
    ended_at: str | None = None,
    client: Any = None,
) -> None:
    """Fold local file facts and, if reachable, one live health+readiness pair.

    `started_at`/`ended_at` are required for `deployment_identity.elapsed_seconds`
    to be non-null, which `compute_timing_summary`'s `deployment_seconds` rollup
    field reads: without them the timing rollup, and therefore
    `overall_status: "complete"`, can never be reached even after a perfect
    rehearsal (see `tests/test_rehearsal.py`'s
    `test_a_fully_populated_manifest_reaches_complete_overall_status`).
    """
    from scripts.retrieval_profile import load_profile

    manifest["effective_settings"]["retrieval_profile"] = load_profile().as_dict()
    stage_detail_parts = [
        f"source_revision={manifest['environment']['source_revision'][:12]}",
        f"bootstrap_script_sha256={manifest['environment']['bootstrap_script_sha256']}",
    ]
    if api_url:
        import httpx

        owns_client = client is None
        client = client or httpx.Client()
        try:
            health = _http_get_json(
                client, api_url.rstrip("/") + "/api/health", timeout
            )
            readiness = _http_get_json(
                client, api_url.rstrip("/") + "/api/readiness", timeout
            )
        finally:
            if owns_client:
                client.close()
        manifest["environment"]["api_base_url"] = api_url
        manifest["environment"]["served"] = {"health": health, "readiness": readiness}
        database = readiness.get("database", {})
        manifest["dataset_identity"]["served_dataset_id"] = database.get("dataset_id")
        manifest["dataset_identity"]["served_catalog_sha256"] = readiness.get(
            "source", {}
        ).get("dataset_manifest_sha256")
        manifest["effective_settings"]["configured_models"] = readiness.get(
            "configured_models"
        )
        stage_detail_parts.append(f"served status={readiness.get('status')}")
        status = "passed" if readiness.get("status") == "ready" else "failed"
        identity = manifest["dataset_identity"]
        for name in ("dataset_id", "catalog_sha256"):
            expected = identity.get(f"expected_{name}")
            actual = identity.get(f"served_{name}")
            if not expected or actual != expected:
                status = "failed"
                stage_detail_parts.append(
                    explain(
                        f"served {name}={actual!r}, expected {expected!r}",
                        "initialize evidence from the pinned catalog contract and "
                        "deploy that catalog before recording a passing identity",
                    )
                )
    else:
        stage_detail_parts.append(
            "no --api-url supplied; identity captured from git and config files only"
        )
        status = "skipped"
    upsert_stage(
        manifest,
        "deployment_identity",
        status=status,
        detail="; ".join(stage_detail_parts),
        started_at=started_at,
        ended_at=ended_at,
    )


def record_first_query(
    manifest: dict[str, Any],
    *,
    api_url: str,
    timeout: float,
    client: Any = None,
) -> None:
    """Time one plain, non-reranked `/api/search` call as the deployment's first query.

    READINESS.md's clean-account acceptance test names "first-query" among the
    seven timing figures a rehearsal must record (item 10), alongside
    deployment, transfer, bootstrap, index, reranker, and agent timing. This
    is the only one of those seven with no other natural source: the others
    come from `capture_identity`, `import_bootstrap_timings`, and
    `record_cold_warm`. Run it once the deployment reports readiness, right
    after `capture-identity`. The measurement is stored on `deployment_identity`
    without touching its `status`/`detail`, which `capture_identity` already owns.
    """
    import httpx

    owns_client = client is None
    client = client or httpx.Client()
    try:
        payload = {
            "query": DEFAULT_RERANK_QUESTION,
            "filters": {},
            "limit": 10,
            "include_diagnostics": True,
            "rerank": False,
        }
        _, _, elapsed_ms = _http_post_json(
            client, api_url.rstrip("/") + "/api/search", payload, timeout
        )
    finally:
        if owns_client:
            client.close()
    stage = manifest.setdefault("stages", {}).setdefault(
        "deployment_identity", _empty_stage()
    )
    stage["first_query_ms"] = round(elapsed_ms, 1)


def record_cold_warm(
    manifest: dict[str, Any],
    *,
    target: str,
    condition: str,
    api_url: str,
    question: str | None,
    timeout: float,
    client: Any = None,
) -> None:
    if target not in COLD_WARM_TARGETS:
        raise RehearsalError(
            explain(f"target {target!r}", f"use one of {COLD_WARM_TARGETS}")
        )
    if condition not in COLD_WARM_CONDITIONS:
        raise RehearsalError(
            explain(f"condition {condition!r}", f"use one of {COLD_WARM_CONDITIONS}")
        )
    import httpx

    owns_client = client is None
    client = client or httpx.Client()
    try:
        if target == "reranker":
            payload = {
                "query": question or DEFAULT_RERANK_QUESTION,
                "filters": {},
                "limit": 10,
                "include_diagnostics": True,
                "rerank": True,
            }
            body, status_code, elapsed_ms = _http_post_json(
                client, api_url.rstrip("/") + "/api/search", payload, timeout
            )
            diagnostics = body.get("diagnostics") or {}
            record = {
                "http_status": status_code,
                "client_elapsed_ms": round(elapsed_ms, 1),
                "rerank_status": diagnostics.get("rerank_status"),
                "rerank_model_id": diagnostics.get("rerank_model_id"),
                "stage_timings_ms": diagnostics.get("stage_timings_ms"),
                "total_latency_ms": diagnostics.get("total_latency_ms"),
            }
            stage_name = "reranker_cold_warm"
        else:
            payload = {
                "question": question or DEFAULT_ASK_MOSAIC_QUESTION,
                "filters": {},
                "result_limit": 6,
            }
            body, status_code, elapsed_ms = _http_post_json(
                client, api_url.rstrip("/") + "/api/agent/answer", payload, timeout
            )
            trace = body.get("trace") or []
            record = {
                "http_status": status_code,
                "client_elapsed_ms": round(elapsed_ms, 1),
                "outcome": body.get("outcome"),
                "tool_call_count": len(trace),
                "tool_names": [step.get("tool") for step in trace],
                "citation_count": len(body.get("citations") or []),
                "recommendation_count": len(body.get("recommendations") or []),
            }
            stage_name = "ask_mosaic_cold_warm"
    finally:
        if owns_client:
            client.close()
    stage = manifest.setdefault("stages", {}).setdefault(stage_name, _empty_stage())
    stage[condition] = record
    cold, warm = stage.get("cold"), stage.get("warm")
    if cold and warm:
        status, detail = "passed", f"cold and warm both recorded for {target}"
    else:
        pending = "warm" if condition == "cold" else "cold"
        status = "skipped"
        detail = f"{condition} recorded for {target}; {pending} still pending"
    upsert_stage(
        manifest,
        stage_name,
        status=status,
        detail=detail,
        extra={"cold": cold, "warm": warm},
    )


def record_layout(
    manifest: dict[str, Any], *, device: str, status: str, detail: str
) -> None:
    if device not in LAYOUT_DEVICES:
        raise RehearsalError(
            explain(f"device {device!r}", f"use one of {LAYOUT_DEVICES}")
        )
    if status not in ("ok", "issue"):
        raise RehearsalError(
            explain(f"layout status {status!r}", "use 'ok' or 'issue'")
        )
    stage = manifest.setdefault("stages", {}).setdefault(
        "layout_walkthrough", _empty_stage()
    )
    devices = stage.setdefault("devices", {})
    devices[device] = {"status": status, "detail": redact(detail)}
    recorded = {
        name: devices[name]["status"] for name in LAYOUT_DEVICES if name in devices
    }
    if len(recorded) < len(LAYOUT_DEVICES):
        overall = "skipped"
        summary = f"{len(recorded)}/{len(LAYOUT_DEVICES)} device(s) walked through"
    elif any(value == "issue" for value in recorded.values()):
        overall = "failed"
        summary = "at least one device reported a layout issue: " + ", ".join(
            name for name, value in recorded.items() if value == "issue"
        )
    else:
        overall = "passed"
        summary = "laptop, tablet, mobile, and projector all confirmed ok"
    upsert_stage(
        manifest,
        "layout_walkthrough",
        status=overall,
        detail=summary,
        extra={"devices": devices},
    )


def compute_timing_summary(manifest: dict[str, Any]) -> None:
    """Derive the timing rollup from stages already recorded; never re-enter numbers."""
    stages = manifest.get("stages", {})
    bootstrap = stages.get("bootstrap_phases", {})
    phases = {
        phase["name"]: phase["elapsed_seconds"] for phase in bootstrap.get("phases", [])
    }
    reranker = stages.get("reranker_cold_warm", {})
    ask_mosaic = stages.get("ask_mosaic_cold_warm", {})
    deployment_stage = stages.get("deployment_identity", {})
    rollup = {
        "deployment_seconds": deployment_stage.get("elapsed_seconds"),
        "archive_transfer_seconds": stages.get("archive_transfer_and_join", {}).get(
            "elapsed_seconds"
        ),
        "bootstrap_total_seconds": bootstrap.get("total_elapsed_seconds"),
        "index_creation_seconds": phases.get("index_creation"),
        "catalog_restore_seconds": stages.get("catalog_restore_verification", {}).get(
            "elapsed_seconds"
        ),
        # READINESS.md item 10's seventh figure alongside deployment, transfer,
        # bootstrap, index, reranker, and agent timing; recorded by
        # `record_first_query`, never re-derived here.
        "first_query_ms": deployment_stage.get("first_query_ms"),
        "reranker_cold_ms": (reranker.get("cold") or {}).get("client_elapsed_ms"),
        "reranker_warm_ms": (reranker.get("warm") or {}).get("client_elapsed_ms"),
        "ask_mosaic_cold_ms": (ask_mosaic.get("cold") or {}).get("client_elapsed_ms"),
        "ask_mosaic_warm_ms": (ask_mosaic.get("warm") or {}).get("client_elapsed_ms"),
    }
    known = {key: value for key, value in rollup.items() if value is not None}
    status = "passed" if known and len(known) == len(rollup) else "skipped"
    detail = f"{len(known)}/{len(rollup)} timing figures available from recorded stages"
    upsert_stage(
        manifest,
        "timing_summary",
        status=status,
        detail=detail,
        extra={"rollup": rollup},
    )


# --------------------------------------------------------------------------
# Human-readable summary
# --------------------------------------------------------------------------


def render_summary(manifest: dict[str, Any]) -> str:
    lines = [
        f"Rehearsal evidence: {manifest.get('overall_status', 'unknown').upper()}",
        f"  recorded_at: {manifest.get('recorded_at')}",
        (
            f"  source_revision: {manifest.get('environment', {}).get('source_revision')}"
            f" (dirty={manifest.get('environment', {}).get('source_worktree_dirty')})"
        ),
        f"  api_base_url: {manifest.get('environment', {}).get('api_base_url')}",
        (
            f"  expected dataset: {manifest.get('dataset_identity', {}).get('expected_dataset_id')}"
            f" served: {manifest.get('dataset_identity', {}).get('served_dataset_id')}"
        ),
        "  stages:",
    ]
    for name in REQUIRED_STAGES:
        stage = manifest.get("stages", {}).get(name, _empty_stage())
        lines.append(
            f"    [{stage['status']:>11}] {name}: {stage.get('detail') or '(no detail)'}"
        )
    problems = validate_manifest(manifest)
    if problems:
        lines.append("  VALIDATION PROBLEMS:")
        lines.extend(f"    - {problem}" for problem in problems)
    if manifest.get("overall_status") != "complete":
        lines.append(
            "  PENDING RUNTIME VERIFICATION: this manifest does not yet record a "
            "complete clean-account rehearsal; no deployment-time, latency, or "
            "throughput claim from it may be marked passed."
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _add_manifest_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=Path, required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init", help="Create an empty evidence manifest."
    )
    init_parser.add_argument("--output", type=Path, required=True)
    init_parser.add_argument("--operator", default="")
    init_parser.add_argument("--workshop-studio-stack-id")
    init_parser.add_argument("--aws-region")
    init_parser.add_argument("--api-base-url")

    identity_parser = subparsers.add_parser(
        "capture-identity",
        help="Record git/config identity and, if reachable, one live health+readiness read.",
    )
    _add_manifest_arg(identity_parser)
    identity_parser.add_argument("--api-url")
    identity_parser.add_argument("--timeout", type=float, default=30.0)
    identity_parser.add_argument("--started-at")
    identity_parser.add_argument("--ended-at")

    first_query_parser = subparsers.add_parser(
        "record-first-query",
        help="Issue one plain, non-reranked /api/search call and record its latency.",
    )
    _add_manifest_arg(first_query_parser)
    first_query_parser.add_argument("--api-url", required=True)
    first_query_parser.add_argument("--timeout", type=float, default=30.0)

    stage_parser = subparsers.add_parser(
        "record-stage", help="Record one stage's outcome."
    )
    _add_manifest_arg(stage_parser)
    stage_parser.add_argument("--stage", required=True)
    stage_parser.add_argument("--status", required=True, choices=ALLOWED_STAGE_STATUS)
    stage_parser.add_argument("--detail", required=True)
    stage_parser.add_argument("--started-at")
    stage_parser.add_argument("--ended-at")
    stage_parser.add_argument("--artifact", action="append", default=[])

    timings_parser = subparsers.add_parser(
        "import-bootstrap-timings",
        help="Fold build/bootstrap-timings.tsv into the bootstrap_phases stage.",
    )
    _add_manifest_arg(timings_parser)
    timings_parser.add_argument(
        "--timings-file", type=Path, default=DEFAULT_BOOTSTRAP_TIMINGS
    )
    timings_parser.add_argument("--restore-report", type=Path)
    timings_parser.add_argument("--started-at")
    timings_parser.add_argument("--ended-at")

    cold_warm_parser = subparsers.add_parser(
        "record-cold-warm",
        help="Issue one live reranker or Ask Mosaic call and record its latency.",
    )
    _add_manifest_arg(cold_warm_parser)
    cold_warm_parser.add_argument("--target", required=True, choices=COLD_WARM_TARGETS)
    cold_warm_parser.add_argument(
        "--condition", required=True, choices=COLD_WARM_CONDITIONS
    )
    cold_warm_parser.add_argument("--api-url", required=True)
    cold_warm_parser.add_argument("--question")
    cold_warm_parser.add_argument("--timeout", type=float, default=60.0)

    layout_parser = subparsers.add_parser(
        "record-layout", help="Record one device's layout walkthrough result."
    )
    _add_manifest_arg(layout_parser)
    layout_parser.add_argument("--device", required=True, choices=LAYOUT_DEVICES)
    layout_parser.add_argument("--status", required=True, choices=("ok", "issue"))
    layout_parser.add_argument("--detail", required=True)

    timing_summary_parser = subparsers.add_parser(
        "compute-timing-summary",
        help="Derive the timing rollup from already-recorded stages.",
    )
    _add_manifest_arg(timing_summary_parser)

    validate_parser = subparsers.add_parser(
        "validate", help="Check the manifest against the evidence schema."
    )
    _add_manifest_arg(validate_parser)

    summary_parser = subparsers.add_parser(
        "summary", help="Print a human-readable status block."
    )
    _add_manifest_arg(summary_parser)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            manifest = new_manifest(
                operator=args.operator,
                workshop_studio_stack_id=args.workshop_studio_stack_id,
                aws_region=args.aws_region,
                api_base_url=args.api_base_url,
            )
            save_manifest(args.output, manifest)
            print(f"Initialized {args.output}")
            return 0

        manifest = load_manifest(args.manifest)

        if args.command == "capture-identity":
            capture_identity(
                manifest,
                api_url=args.api_url,
                timeout=args.timeout,
                started_at=args.started_at,
                ended_at=args.ended_at,
            )
        elif args.command == "record-first-query":
            record_first_query(manifest, api_url=args.api_url, timeout=args.timeout)
        elif args.command == "record-stage":
            upsert_stage(
                manifest,
                args.stage,
                status=args.status,
                detail=args.detail,
                started_at=args.started_at,
                ended_at=args.ended_at,
                artifact_paths=args.artifact,
            )
        elif args.command == "import-bootstrap-timings":
            import_bootstrap_timings(
                manifest,
                args.timings_file,
                restore_report=args.restore_report,
                started_at=args.started_at,
                ended_at=args.ended_at,
            )
        elif args.command == "record-cold-warm":
            record_cold_warm(
                manifest,
                target=args.target,
                condition=args.condition,
                api_url=args.api_url,
                question=args.question,
                timeout=args.timeout,
            )
        elif args.command == "record-layout":
            record_layout(
                manifest, device=args.device, status=args.status, detail=args.detail
            )
        elif args.command == "compute-timing-summary":
            compute_timing_summary(manifest)
        elif args.command == "validate":
            problems = validate_manifest(manifest)
            if problems:
                print("INVALID:")
                for problem in problems:
                    print(f"  - {problem}")
                return 1
            print("VALID")
            return 0
        elif args.command == "summary":
            print(render_summary(manifest))
            return 0
    except RehearsalError as error:
        print(f"rehearsal.py: {error}", file=sys.stderr)
        return 2

    save_manifest(args.manifest, manifest)
    print(f"Updated {args.manifest} (overall_status={manifest['overall_status']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
