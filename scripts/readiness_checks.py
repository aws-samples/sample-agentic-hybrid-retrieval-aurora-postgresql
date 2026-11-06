"""The read-only checks behind an event box's readiness record.

None of these checks resets a lab, runs a search that writes an audit row, or runs
the agent, so `--live` can repeat them on a participant's box during the event.
The checks that need a write ran once, in the bootstrap acceptance gate
(`phase_readiness` in deploy/mosaic-bootstrap.sh). The record lists those with the
time the gate passed instead of repeating them.

An absence counts as ready only after a positive control: the fuzzy matching
control finds the Logitech before the gate's "Logitech absent" means anything, a
runtime must report platform V1 rather than no platform, and a record in which no
check passed is not ready.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
EXPECTED_VERSIONS = Path("/opt/mosaic-workshop/readiness-expected.json")
MANAGED_SETTINGS = Path("/etc/claude-code/managed-settings.json")
API = "http://127.0.0.1:8000"
ORIGIN_HEADER = "X-Mosaic-Origin-Verify"
SERVICES = ("mosaic-api", "mosaic-ui", "nginx", "code-editor", "docker")
MODEL_VARIABLES = (
    "BEDROCK_EMBED_MODEL_ID",
    "BEDROCK_RERANK_MODEL_ID",
    "BEDROCK_CHAT_MODEL_ID",
)
EXPECTED_LAB_STATE = ("Lab 1: BROKEN", "Lab 2: NOT STARTED", "Lab 3: NOT STARTED")
LAB_STATE = "Lab state (valid before participants start)"
BOOTSTRAP_ONLY = (
    (
        "Lab 1 broken search returns headphones, no fuzzy matching candidates and "
        "no Logitech (valid before participants start)"
    ),
    "Search with Bedrock reranking applied",
    "Gateway search runs the lab SQL and returns source evidence",
    "Session Memory saves and reads back a conversation",
    "Claude Code answers as the participant",
    "Mission targets, evaluation queries, function census and smoke test",
    "Lab 2 validates against the SQL Aurora runs",
)
COMMAND_SECONDS = 20


class CheckError(Exception):
    """A check failed; the message names what was found and the fix."""


@dataclass(frozen=True)
class Line:
    """One line of a readiness record."""

    status: str
    name: str
    detail: str

    def text(self) -> str:
        return f"{self.status}  {self.name}: {self.detail}"


def passed(name: str, detail: str) -> Line:
    return Line("PASS", name, detail)


def failed(name: str, detail: str) -> Line:
    return Line("FAIL", name, detail)


@dataclass
class Context:
    """What the checks read: the repository, the workshop .env and the pins."""

    repo: Path
    env: Mapping[str, str]
    expected: Mapping[str, str] | None
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run
    home: Path = field(default_factory=Path.home)

    @classmethod
    def from_environment(cls) -> Context:
        try:
            expected = json.loads(EXPECTED_VERSIONS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            expected = None
        return cls(repo=REPO, env=dict(os.environ), expected=expected)

    def need(self, name: str) -> str:
        value = self.env.get(name, "").strip()
        if not value:
            raise CheckError(f"{name} is unset; fix: load this workshop's .env")
        return value

    def pin(self, name: str) -> str:
        if self.expected is None:
            raise CheckError(
                f"{EXPECTED_VERSIONS} is missing, so nothing records what bootstrap "
                "installed; fix: read /var/log/mosaic-bootstrap.log"
            )
        value = str(self.expected.get(name, "")).strip()
        if not value:
            raise CheckError(f"{EXPECTED_VERSIONS} has no {name}")
        return value

    def output(self, argv: list[str]) -> str:
        try:
            done = self.run(
                argv,
                capture_output=True,
                text=True,
                timeout=COMMAND_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CheckError(f"{argv[0]} did not run: {error}") from error
        if done.returncode != 0:
            raise CheckError(
                f"{' '.join(argv)} exited {done.returncode}: {done.stderr.strip()[:120]}"
            )
        return done.stdout.strip()


def imds(path: str) -> str:
    """One instance metadata value through IMDSv2."""
    token = urllib.request.Request(
        "http://169.254.169.254/latest/api/token",
        method="PUT",
        headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
    )
    with urllib.request.urlopen(token, timeout=2) as response:
        value = response.read().decode()
    request = urllib.request.Request(
        f"http://169.254.169.254/latest/{path}",
        headers={"X-aws-ec2-metadata-token": value},
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        return response.read().decode().strip()


def check_host(_ctx: Context) -> list[Line]:
    """The AMI and instance type this box booted: observed, compared by no check here."""
    try:
        found = f"{imds('meta-data/ami-id')}, {imds('meta-data/instance-type')}"
    except OSError as error:
        return [Line("INFO", "Host", f"instance metadata unreadable: {error}")]
    return [Line("INFO", "Host", f"{found}, {platform.machine()}")]


def mission_cases(repo: Path) -> tuple[dict, dict]:
    """Lab 1's typo request and its exact-identity control, from the manifest."""
    manifest = json.loads(
        (repo / "data" / "evals" / "mosaic_labs_missions.json").read_text("utf-8")
    )
    typo = next(m for m in manifest["missions"] if m["id"] == "typo-recovery")
    exact = next(
        c for c in manifest["supporting_checks"] if c["id"] == "exact-identity"
    )
    return typo, exact


def check_source(ctx: Context) -> list[Line]:
    name = "Source revision"
    pinned = ctx.pin("source_revision")
    head = ctx.output(["git", "-C", str(ctx.repo), "rev-parse", "HEAD"])
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        return [failed(name, f"git rev-parse HEAD printed {head[:40]!r}, not a commit")]
    if head != pinned:
        return [failed(name, f"HEAD is {head[:12]}, not the pinned {pinned[:12]}")]
    return [passed(name, f"{head[:12]}, the pinned revision")]


def observed_versions(ctx: Context) -> dict[str, str]:
    psql = re.search(r"\(PostgreSQL\) (\d+)\.", ctx.output(["psql", "--version"]))
    editor = (ctx.home / ".local" / "bin" / "code-editor-server").resolve()
    found = re.search(r"code-editor-(v[\d.]+)-", str(editor))
    return {
        "node": ctx.output(["node", "--version"]),
        "python": ctx.output(["python3.13", "--version"]),
        "uv": ctx.output(["uv", "--version"]).split()[1],
        "psql_major": psql.group(1) if psql else "unknown",
        "claude_code": ctx.output(["claude", "--version"]).split()[0],
        "code_editor": found.group(1) if found else f"unknown ({editor.name})",
    }


def check_tool_versions(ctx: Context) -> list[Line]:
    name = "Tool versions"
    observed = observed_versions(ctx)
    wrong = [
        f"{key} is {value}, bootstrap installed {ctx.pin(key)}"
        for key, value in observed.items()
        if value != ctx.pin(key)
    ]
    summary = ", ".join(f"{key} {value}" for key, value in observed.items())
    return [failed(name, "; ".join(wrong)) if wrong else passed(name, summary)]


def check_services(ctx: Context) -> list[Line]:
    name = "Services"
    done = ctx.run(
        ["systemctl", "is-active", *SERVICES],
        capture_output=True,
        text=True,
        timeout=COMMAND_SECONDS,
        check=False,
    )
    states = done.stdout.split()
    if len(states) != len(SERVICES):
        return [
            failed(name, f"systemctl printed {len(states)} states for {len(SERVICES)}")
        ]
    down = [f"{unit} {state}" for unit, state in zip(SERVICES, states, strict=True)]
    down = [item for item in down if not item.endswith(" active")]
    if down:
        return [failed(name, f"{', '.join(down)}; fix: systemctl status <unit>")]
    return [passed(name, f"{', '.join(SERVICES)} active")]


def http_get(path: str, secret: str | None) -> tuple[int, Any]:
    request = urllib.request.Request(f"{API}{path}")
    if secret:
        request.add_header(ORIGIN_HEADER, secret)
    try:
        with urllib.request.urlopen(request, timeout=COMMAND_SECONDS) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, None


def catalog_line(ctx: Context, readiness: Any) -> Line:
    name = "Catalog"
    products = json.loads(
        (ctx.repo / "db" / "config" / "real-catalog-cache.json").read_text("utf-8")
    )["products"]
    dataset = json.loads(
        (ctx.repo / "data" / "evals" / "mosaic_labs_missions.json").read_text("utf-8")
    )["corpus"]["dataset_id"]
    database = (readiness or {}).get("database") or {}
    expected = {
        "dataset_id": dataset,
        "database_name": "mosaic_catalog",
        "product_count": products,
        "embedded_product_count": products,
        "catalog_ready": True,
        "embedding_model_ids": [ctx.need("BEDROCK_EMBED_MODEL_ID")],
    }
    wrong = [
        f"{key} is {database.get(key)!r}, not {value!r}"
        for key, value in expected.items()
        if database.get(key) != value
    ]
    if (readiness or {}).get("status") != "ready" or wrong:
        status = (readiness or {}).get("status")
        return failed(name, "; ".join([f"status is {status!r}", *wrong]))
    return passed(name, f"{dataset}, {products:,} listings, all with an embedding")


def check_api(ctx: Context) -> list[Line]:
    secret = ctx.need("MOSAIC_ORIGIN_VERIFY_SECRET")
    code, readiness = http_get("/api/readiness", secret)
    if code != 200:
        return [
            failed("Catalog", f"/api/readiness returned {code} with the origin secret")
        ]
    lines = [catalog_line(ctx, readiness)]
    refused, _ = http_get("/api/readiness", None)
    origin = "API origin rule"
    lines.append(
        passed(origin, "a call without the origin secret gets 401")
        if refused == 401
        else failed(origin, f"a call without the origin secret got {refused}, not 401")
    )
    _, health = http_get("/api/health", None)
    models = (health or {}).get("models") or {}
    wanted = {
        "agent": ctx.need("BEDROCK_AGENT_MODEL_ID"),
        "synthesis": ctx.need("BEDROCK_SYNTHESIS_MODEL_ID"),
        "rerank": ctx.need("BEDROCK_RERANK_MODEL_ID"),
        "embedding": ctx.need("BEDROCK_EMBED_MODEL_ID"),
    }
    wrong = [
        f"{role} {models.get(role)!r}, the box has {model!r}"
        for role, model in wanted.items()
        if models.get(role) != model
    ]
    name = "API model IDs"
    lines.append(
        failed(name, "; ".join(wrong))
        if wrong
        else passed(
            name, ", ".join(f"{role} {model}" for role, model in wanted.items())
        )
    )
    return lines


def connect(ctx: Context):
    import psycopg

    return psycopg.connect(
        ctx.need("DATABASE_URL"),
        connect_timeout=10,
        options="-c statement_timeout=20000",
    )


def check_aurora(ctx: Context) -> list[Line]:
    name = "Aurora and extensions"
    with connect(ctx) as connection:
        server, vector, trigram = connection.execute(
            "SELECT current_setting('server_version'),"
            " (SELECT extversion FROM pg_extension WHERE extname = 'vector'),"
            " (SELECT extversion FROM pg_extension WHERE extname = 'pg_trgm')"
        ).fetchone()
    detail = f"PostgreSQL {server}, pgvector {vector}, pg_trgm {trigram}"
    if not server or server.split(".")[0] != ctx.pin("psql_major"):
        return [
            failed(name, f"{detail}; the engine major is not {ctx.pin('psql_major')}")
        ]
    if vector is None or trigram is None:
        return [failed(name, f"{detail}; an extension the labs use is missing")]
    return [passed(name, detail)]


def check_fuzzy_control(ctx: Context) -> list[Line]:
    """Fuzzy matching itself must find the Logitech, or its absence proves nothing."""
    from scripts.checks.retrieval_profile import load_profile

    name = "Fuzzy matching control (Lab 1)"
    profile = load_profile()
    ranks = []
    with connect(ctx) as connection:
        for case in mission_cases(ctx.repo):
            target = case["target_product_ids"][0]
            rows = connection.execute(
                # Typed to match search_fuzzy(text, jsonb, integer, real): psycopg
                # sends a small int as smallint and a float as double precision.
                "SELECT product_id, fuzzy_rank FROM mosaic_search.search_fuzzy("
                "%s::text, %s::jsonb, %s::integer, %s::real)",
                (
                    case["query"],
                    json.dumps(case["filters"]),
                    profile.fuzzy_limit,
                    profile.fuzzy_threshold,
                ),
            ).fetchall()
            rank = next((r for product, r in rows if product == target), None)
            if rank is None:
                return [
                    failed(
                        name,
                        f"search_fuzzy({case['query']!r}) returns {len(rows)} "
                        f"products without {target}; Lab 1 cannot recover it",
                    )
                ]
            ranks.append(f"rank {rank} for {case['query']}")
    return [passed(name, f"finds {target} at {' and '.join(ranks)}")]


def check_lab_state(ctx: Context) -> list[Line]:
    from scripts.lab_entry import load_record
    from scripts.lab_state import status_line

    started = [lab for lab in (1, 2, 3) if load_record(lab, ctx.repo) is not None]
    if started:
        return [Line("INFO", LAB_STATE, f"Lab {started[-1]} has started on this box")]
    lines = tuple(status_line(lab, repo=ctx.repo) for lab in (1, 2, 3))
    if lines != EXPECTED_LAB_STATE:
        return [failed(LAB_STATE, f"status reads {'; '.join(lines)}")]
    return [passed(LAB_STATE, "; ".join(lines))]


def runtime_line(ctx: Context, control: Any, label: str, runtime: dict) -> Line:
    from scripts.deploy_agentcore import RUNTIME_PLATFORM_VERSION

    platform = runtime.get("platformVersion")
    if runtime.get("status") != "READY":
        return failed(label, f"status {runtime.get('status')}")
    if platform != RUNTIME_PLATFORM_VERSION:
        return failed(
            label,
            f"reports platform {platform!r}; a missing value is not "
            f"{RUNTIME_PLATFORM_VERSION}; fix: check the stack's "
            "PlatformVersion",
        )
    endpoint = control.get_agent_runtime_endpoint(
        agentRuntimeId=runtime["agentRuntimeId"], endpointName="DEFAULT"
    )
    version = runtime["agentRuntimeVersion"]
    if endpoint.get("status") != "READY" or endpoint.get("liveVersion") != version:
        return failed(
            label,
            f"DEFAULT endpoint {endpoint.get('status')} serves "
            f"{endpoint.get('liveVersion')}, not version {version}",
        )
    env = runtime.get("environmentVariables") or {}
    wrong = [
        f"{key}={env.get(key)!r}"
        for key in MODEL_VARIABLES
        if env.get(key) != ctx.env.get(key)
    ]
    if wrong:
        return failed(label, f"runs {', '.join(wrong)}, unlike the box's .env")
    artifact = runtime.get("agentRuntimeArtifact") or {}
    uri = (artifact.get("containerConfiguration") or {}).get("containerUri")
    if not uri:
        return failed(
            label, "runs no container image; the stack runs the workshop's from ECR"
        )
    return passed(
        label,
        f"READY on {platform}, version {version}, image "
        f"{uri.rsplit(':', 1)[-1][:22]}, models match the box",
    )


def check_runtimes(ctx: Context) -> list[Line]:
    from scripts.deploy_agentcore import RUNTIME_ROLES, client

    control = client("bedrock-agentcore-control")
    lines = []
    for variable, label, _role in RUNTIME_ROLES:
        runtime_id = ctx.need(variable).rsplit("/", 1)[-1]
        runtime = control.get_agent_runtime(agentRuntimeId=runtime_id)
        lines.append(runtime_line(ctx, control, label, runtime))
    return lines


def check_gateway(ctx: Context) -> list[Line]:
    from scripts.deploy_agentcore import client
    from service import gateway_tools

    name = "Gateway"
    gateway = client("bedrock-agentcore-control").get_gateway(
        gatewayIdentifier=ctx.need("MOSAIC_AGENTCORE_GATEWAY_ID")
    )
    if gateway.get("status") != "READY":
        return [failed(name, f"status {gateway.get('status')}")]
    listed = {
        tool["name"] for tool in gateway_tools.rpc("tools/list", {}).get("tools", [])
    }
    wanted = {f"{gateway_tools.TARGET_NAME}___{n}" for n in gateway_tools.TOOL_NAMES}
    if missing := sorted(wanted - listed):
        return [failed(name, f"tools/list lacks {', '.join(missing)}")]
    return [passed(name, f"READY and lists the {len(wanted)} SQL tools")]


def check_memory(ctx: Context) -> list[Line]:
    from scripts.deploy_agentcore import client

    memory = client("bedrock-agentcore-control").get_memory(
        memoryId=ctx.need("MOSAIC_AGENTCORE_MEMORY_ID")
    )["memory"]
    if memory.get("status") != "ACTIVE":
        return [failed("Memory", f"status {memory.get('status')}")]
    return [passed("Memory", "ACTIVE")]


def check_models(ctx: Context) -> list[Line]:
    from scripts.checks.check_model_access import (
        Outcome,
        probe_chat,
        probe_embedding,
        probe_rerank,
    )

    region = ctx.need("AWS_REGION")
    chats = dict.fromkeys(
        (ctx.need("BEDROCK_AGENT_MODEL_ID"), ctx.need("BEDROCK_SYNTHESIS_MODEL_ID"))
    )
    probes = [
        *(probe_chat(model, region, True) for model in chats),
        probe_embedding(ctx.need("BEDROCK_EMBED_MODEL_ID"), region, True),
        probe_rerank(ctx.need("BEDROCK_RERANK_MODEL_ID"), region, True),
    ]
    bad = [
        f"{p.model_id} {p.outcome}: {p.detail[:80]}"
        for p in probes
        if p.outcome != Outcome.OK
    ]
    if bad:
        return [failed("Bedrock models", "; ".join(bad))]
    return [
        passed("Bedrock models", ", ".join(f"{p.model_id} answered" for p in probes))
    ]


def check_deploy_path(ctx: Context) -> list[Line]:
    from scripts.deploy_agentcore import client, image_digest

    name = "Lab 3 deploy path"
    docker = ctx.output(["docker", "info", "--format", "{{.ServerVersion}}"])
    repository = ctx.need("MOSAIC_RUNTIME_IMAGE_REPOSITORY").split("/", 1)[-1]
    tag = f"bootstrap-{ctx.need('SOURCE_REVISION')}"
    digest = image_digest(client("ecr"), repository, tag)
    if digest is None:
        return [failed(name, f"ECR has no {tag} in {repository}")]
    return [
        passed(
            name,
            f"Docker {docker} answers the participant; ECR holds "
            f"{tag[:22]} ({digest[7:19]})",
        )
    ]


def check_coach(ctx: Context) -> list[Line]:
    name = "Claude Code managed settings"
    try:
        settings = json.loads(MANAGED_SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [failed(name, f"{MANAGED_SETTINGS} unreadable: {error}")]
    permissions = settings.get("permissions") or {}
    found = (
        permissions.get("defaultMode"),
        permissions.get("disableAutoMode"),
        settings.get("disableAutoMode"),
    )
    if found != ("default", "disable", "disable"):
        return [
            failed(name, f"defaultMode, disableAutoMode (both places) read {found}")
        ]
    return [passed(name, "manual mode, auto mode disabled")]


CHECKS: tuple[tuple[str, Callable[[Context], list[Line]]], ...] = (
    ("Host", check_host),
    ("Source revision", check_source),
    ("Tool versions", check_tool_versions),
    ("Services", check_services),
    ("Catalog", check_api),
    ("Aurora and extensions", check_aurora),
    ("Fuzzy matching control (Lab 1)", check_fuzzy_control),
    (LAB_STATE, check_lab_state),
    ("AgentCore runtimes", check_runtimes),
    ("Gateway", check_gateway),
    ("Memory", check_memory),
    ("Bedrock models", check_models),
    ("Lab 3 deploy path", check_deploy_path),
    ("Claude Code managed settings", check_coach),
)


def run_one(
    name: str, check: Callable[[Context], list[Line]], ctx: Context
) -> list[Line]:
    from scripts.checks.rehearsal import redact

    try:
        return check(ctx)
    except CheckError as error:
        return [failed(name, str(error))]
    except Exception as error:  # noqa: BLE001 - every failure becomes a record line
        text = " ".join(redact(str(error)).split())[:200]
        return [failed(name, f"{type(error).__name__}: {text}")]


def run_checks(
    ctx: Context,
    cap: float,
    checks: tuple[tuple[str, Callable[[Context], list[Line]]], ...] = CHECKS,
) -> list[Line]:
    """Every check's lines, or those finished when `cap` seconds ran out."""
    lines: list[Line] = []
    current = {"name": ""}

    def work() -> None:
        for name, check in checks:
            current["name"] = name
            lines.extend(run_one(name, check, ctx))
        current["name"] = ""

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(cap)
    if worker.is_alive():
        return [
            *lines,
            failed(
                "Readiness cap",
                f"checks did not finish within {cap:g} s; "
                f"{current['name']} was still running",
            ),
        ]
    return lines


def bootstrap_gate_lines(passed_at: str | None) -> list[Line]:
    """The gate's write-needing checks, with the time the gate passed."""
    if not passed_at:
        return [
            failed(
                "Bootstrap acceptance gate",
                "no record that it passed on this "
                "box; fix: read /var/log/mosaic-bootstrap.log",
            )
        ]
    return [
        passed(name, f"bootstrap gate, recorded {passed_at}") for name in BOOTSTRAP_ONLY
    ]
