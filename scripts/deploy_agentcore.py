"""Package, deploy and verify the workshop's agent and SQL tool runtimes."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote, quote_plus

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.checks.rehearsal import redact
from scripts.package_agentcore import package
from scripts.progress import Progress
from service import agentcore_transport, gateway_tools
from service.agent_deploys import record_deploy
from service.agent_setup import AGENT_NOT_BUILT, agent_code_message
from service.lab_validation_receipt import application_digest, participant_sql_digest
from service.participant_commands import (
    AGENTCORE_RESOURCES,
    APPLY_SQL,
    DEPLOY_AGENT,
    DEPLOY_PHASE_SECONDS,
    VERIFY_AGENT,
    ask_setup,
)


def client(service: str):
    return boto3.client(
        service,
        region_name=os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-1",
        config=Config(
            connect_timeout=10,
            read_timeout=30,
            retries={"total_max_attempts": 3, "mode": "standard"},
        ),
    )


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(
            f"Deployment configuration rule: {name} is unset; load this workshop's .env."
        )
    return value


def safe_text(text: object, limit: int = 600) -> str:
    """Redact secret-shaped text and this environment's secret values from a message."""
    shown = redact(str(text))
    for name, value in os.environ.items():
        if value and any(
            part in name for part in ("PASSWORD", "SECRET", "TOKEN", "DATABASE_URL")
        ):
            for variant in (value, quote(value, safe=""), quote_plus(value)):
                shown = shown.replace(variant, "[REDACTED]")
    return " ".join(shown.split())[:limit]


DEPLOY_PHASES = (
    ("Build and push the image", "Built and pushed the image"),
    ("Update the tools runtime", "Updated the tools runtime"),
    ("Update the Retrieval agent runtime", "Updated the Retrieval agent runtime"),
    ("Synchronize the Gateway tools", "Synchronized the Gateway tools"),
    ("Verify the deployment", "Verified the deployment"),
)


def deploy_progress() -> Progress:
    """The deploy's five phases, each with its usual time from DEPLOY_PHASE_SECONDS."""
    progress = Progress("Deploying your Retrieval agent")
    progress.plan(DEPLOY_PHASE_SECONDS)
    return progress


def phase(progress: Progress, index: int) -> None:
    """Start a deploy phase: a bar toward its usual time, then a line with how long it took."""
    label, done = DEPLOY_PHASES[index]
    # docker prints its own build output, which a redrawn line would collide with.
    progress.begin(
        label,
        typical=DEPLOY_PHASE_SECONDS[index],
        done=done,
        animate=index != 0,
        number=index + 1,
    )


DOCKER_MISSING = (
    "Docker rule: the docker command was not found; fix: start Docker in Code Editor "
    f"(or ask your facilitator to), then retry {DEPLOY_AGENT}."
)


def run_docker(step: str, argv: list[str], *, environment: dict, timeout: int) -> None:
    """Run one docker step, its own output on screen, and a failure that names the step."""
    try:
        subprocess.run(argv, check=True, env=environment, timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError(DOCKER_MISSING) from None
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"Image {step} rule: docker {step} failed with exit code {error.returncode} "
            f"(its output is above); fix: correct that error, then retry {DEPLOY_AGENT}."
        ) from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Image {step} rule: docker {step} did not finish within {timeout} s; "
            f"fix: check the Code Editor's network connection, then retry {DEPLOY_AGENT}."
        ) from None


def image_digest(ecr, repository: str, tag: str) -> str | None:
    """Return an existing immutable image, allowing an interrupted push to resume."""
    try:
        rows = ecr.describe_images(
            repositoryName=repository, imageIds=[{"imageTag": tag}]
        )["imageDetails"]
    except ecr.exceptions.ImageNotFoundException:
        return None
    digest = rows[0]["imageDigest"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError(
            "Runtime image rule: ECR returned an invalid digest; inspect the repository."
        )
    return digest


def publish_image(repository_uri: str, *, bootstrap: bool) -> str:
    """Build the participant's exact source and publish an immutable ARM64 image."""
    if not re.fullmatch(
        r"[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com(?:\.cn)?/[a-z0-9][a-z0-9/_-]*",
        repository_uri,
    ):
        raise ValueError(
            "Runtime image rule: invalid ECR repository URI; load this workshop's .env."
        )
    registry, repository = repository_uri.split("/", 1)
    ecr = client("ecr")
    with tempfile.TemporaryDirectory(prefix="mosaic-image-") as workspace:
        context = Path(workspace) / "context"
        source_sha = package(ROOT, context)
        revision = required("SOURCE_REVISION") if bootstrap else source_sha
        if not re.fullmatch(
            r"[0-9a-f]{40}" if bootstrap else r"[0-9a-f]{64}", revision
        ):
            raise ValueError(
                "Runtime image rule: invalid source revision; use the pinned workshop revision."
            )
        tag = ("bootstrap-" if bootstrap else "source-") + revision
        digest = image_digest(ecr, repository, tag)
        if digest is None:
            # Docker's login file is sensitive too. It exists only in this private
            # temporary directory, never in the participant checkout or ~/.docker.
            config = Path(workspace) / "docker"
            config.mkdir(mode=0o700)
            environment = {**os.environ, "DOCKER_CONFIG": str(config)}
            token = ecr.get_authorization_token()["authorizationData"][0]
            if token["proxyEndpoint"] != "https://" + registry:
                raise ValueError(
                    "Runtime image rule: ECR login registry differs from the workshop repository."
                )
            user, password = (
                base64.b64decode(token["authorizationToken"]).decode().split(":", 1)
            )
            for attempt in range(3):
                try:
                    subprocess.run(
                        [
                            "docker",
                            "login",
                            "--username",
                            user,
                            "--password-stdin",
                            registry,
                        ],
                        input=password + "\n",
                        text=True,
                        check=True,
                        env=environment,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=60,
                    )
                    break
                except FileNotFoundError:
                    raise RuntimeError(DOCKER_MISSING) from None
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    if attempt == 2:
                        raise RuntimeError(
                            "Registry login rule: ECR login failed after three attempts; "
                            f"fix: check the Code Editor's ECR permissions and HTTPS connectivity, then retry {DEPLOY_AGENT}."
                        ) from None
                    time.sleep(2**attempt)
            image = f"{repository_uri}:{tag}"
            print(
                "Building your Retrieval agent image; the first build is the slowest. "
                "docker's own output follows.",
                flush=True,
            )
            run_docker(
                "build",
                [
                    "docker",
                    "build",
                    "--platform",
                    "linux/arm64",
                    "--tag",
                    image,
                    "--file",
                    str(context / "deploy/agentcore/Dockerfile"),
                    str(context),
                ],
                environment=environment,
                timeout=1200,
            )
            run_docker(
                "push", ["docker", "push", image], environment=environment, timeout=600
            )
            digest = image_digest(ecr, repository, tag)
            if digest is None:
                raise RuntimeError(
                    "Runtime image rule: pushed image is absent from ECR; retry deployment."
                )
        # Twelve hex digits, as docker shortens image IDs, keep the line inside a laptop
        # terminal; the full digest is in the image URI the deployment records.
        kind, _, revision = tag.partition("-")
        print(
            f"Runtime image ready: {kind}-{revision[:12]}, digest "
            f"sha256:{digest.removeprefix('sha256:')[:12]}"
        )
        return f"{repository_uri}@{digest}"


def stage(*, bootstrap: bool = False) -> str:
    """Publish the image; the bootstrap then releases CloudFormation's runtime dependency."""
    image_uri = publish_image(
        required("MOSAIC_RUNTIME_IMAGE_REPOSITORY"), bootstrap=bootstrap
    )
    if bootstrap:
        from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

        # The host's absolute certificate path does not exist in the managed
        # runtime. Both container entry points start in the application root.
        dsn = urlsplit(required("MOSAIC_RUNTIME_DATABASE_URL"))
        query = parse_qs(dsn.query)
        query.update(sslmode=["verify-full"], sslrootcert=["rds-ca-bundle.pem"])
        runtime_dsn = urlunsplit(dsn._replace(query=urlencode(query, doseq=True)))
        client("secretsmanager").put_secret_value(
            SecretId=required("MOSAIC_RUNTIME_DATABASE_SECRET_ARN"),
            SecretString=json.dumps({"DATABASE_URL": runtime_dsn}),
        )
    return image_uri


RUNTIME_FAILED = {"CREATE_FAILED", "UPDATE_FAILED", "DELETING"}


def wait_runtime(control, runtime_id: str, label: str | None = None) -> dict:
    """Wait for the runtime and its DEFAULT endpoint to serve the new version."""
    label = label or f"runtime {runtime_id}"
    deadline = time.monotonic() + 900
    last = "no status yet"
    while time.monotonic() < deadline:
        runtime = control.get_agent_runtime(agentRuntimeId=runtime_id)
        last = f"runtime {runtime['status']}"
        if runtime["status"] == "READY":
            endpoint = control.get_agent_runtime_endpoint(
                agentRuntimeId=runtime_id, endpointName="DEFAULT"
            )
            version = runtime["agentRuntimeVersion"]
            last = (
                f"runtime READY, endpoint {endpoint['status']} serving version "
                f"{endpoint.get('liveVersion')} of {version}"
            )
            if endpoint["status"] == "READY" and endpoint.get("liveVersion") == version:
                return runtime
            if endpoint["status"] in RUNTIME_FAILED:
                raise RuntimeError(
                    f"Runtime deployment rule: the endpoint of {label} is "
                    f"{endpoint['status']}: "
                    f"{safe_text(endpoint.get('failureReason', 'no reason supplied'))}; "
                    f"fix: retry {DEPLOY_AGENT}; if it repeats, share this line with your facilitator."
                )
        if runtime["status"] in RUNTIME_FAILED:
            raise RuntimeError(
                f"Runtime deployment rule: {label} is {runtime['status']}: "
                f"{safe_text(runtime.get('failureReason', 'no reason supplied'))}; "
                f"fix: retry {DEPLOY_AGENT}; if it repeats, share this line with your facilitator."
            )
        time.sleep(5)
    raise TimeoutError(
        f"Runtime deployment rule: {label} was not ready after 900 s (last seen: {last}); "
        f"fix: retry {DEPLOY_AGENT}; if it repeats, share this line with your facilitator."
    )


def discover() -> dict[str, str]:
    """Resolve native resources after the bootstrap package releases their dependency."""
    stack = required("MOSAIC_EDITOR_STACK")
    cfn, control = client("cloudformation"), client("bedrock-agentcore-control")
    logical = {
        "MosaicAgentRuntime": "MOSAIC_AGENTCORE_RUNTIME_ARN",
        "MosaicToolsRuntime": "MOSAIC_AGENTCORE_TOOLS_RUNTIME_ARN",
        "MosaicGateway": "MOSAIC_AGENTCORE_GATEWAY_ID",
        "MosaicGatewayTarget": "MOSAIC_AGENTCORE_GATEWAY_TARGET_ID",
    }
    paginator = cfn.get_paginator("list_stack_resources")
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        values = {}
        # Agent creation waits on Gateway and the tools Runtime. Polling the
        # missing agent first used to conceal a failed tools dependency.
        for page in paginator.paginate(StackName=stack):
            for row in page["StackResourceSummaries"]:
                resource = row["LogicalResourceId"]
                if resource not in logical:
                    continue
                status = row["ResourceStatus"]
                if (
                    "FAILED" in status
                    or "ROLLBACK" in status
                    or status.startswith("DELETE_")
                ):
                    reason = safe_text(
                        row.get("ResourceStatusReason", "No reason supplied"), 800
                    )
                    raise RuntimeError(
                        f"Managed provisioning rule: {resource} is {status}: {reason}; "
                        "fix: correct this resource in the workshop template and retry provisioning."
                    )
                if status in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
                    values[logical[resource]] = row["PhysicalResourceId"]
        if len(values) == len(logical):
            values["MOSAIC_AGENTCORE_GATEWAY_TARGET_ID"] = values[
                "MOSAIC_AGENTCORE_GATEWAY_TARGET_ID"
            ].split("|")[-1]
            try:
                gateway = control.get_gateway(
                    gatewayIdentifier=values["MOSAIC_AGENTCORE_GATEWAY_ID"]
                )
                values["MOSAIC_AGENTCORE_GATEWAY_URL"] = gateway["gatewayUrl"]
                for name in (
                    "MOSAIC_AGENTCORE_RUNTIME_ARN",
                    "MOSAIC_AGENTCORE_TOOLS_RUNTIME_ARN",
                ):
                    runtime = wait_runtime(control, values[name].rsplit("/", 1)[-1])
                    values[name] = runtime["agentRuntimeArn"]
                return values
            except (
                control.exceptions.ResourceNotFoundException,
                control.exceptions.AccessDeniedException,
            ):
                # The policy containing the newly created ARNs attaches
                # asynchronously. CFN listing itself must already be permitted.
                pass
        time.sleep(5)
    raise TimeoutError(
        "Managed resources did not finish provisioning; inspect the workshop stack events."
    )


def update(image_uri: str, progress: Progress, application_sha256: str) -> None:
    """Point both runtimes at the new image, then synchronize Gateway's tools.

    The deploy is recorded once the Retrieval agent runtime is ready on its new
    version, before Gateway and the checks: Runtime already runs the new code, and
    a later `verify` that passes should not need another deploy.
    """
    control = client("bedrock-agentcore-control")
    fields = set(
        control.meta.service_model.operation_model(
            "UpdateAgentRuntime"
        ).input_shape.members
    )
    for index, (setting, label) in enumerate(
        (
            ("MOSAIC_AGENTCORE_TOOLS_RUNTIME_ARN", "tools runtime"),
            ("MOSAIC_AGENTCORE_RUNTIME_ARN", "Retrieval agent runtime"),
        ),
        start=1,
    ):
        phase(progress, index)
        runtime_id = required(setting).rsplit("/", 1)[-1]
        current = control.get_agent_runtime(agentRuntimeId=runtime_id)
        payload = {name: value for name, value in current.items() if name in fields}
        # Get returns this legacy flag, but new runtimes reject it on Update.
        payload.get("networkConfiguration", {}).get("networkModeConfig", {}).pop(
            "requireServiceS3Endpoint", None
        )
        payload["agentRuntimeId"] = runtime_id
        payload["agentRuntimeArtifact"] = {
            "containerConfiguration": {"containerUri": image_uri}
        }
        control.update_agent_runtime(**payload)
        print(f"Updating the {label}; AWS replaces its running version.", flush=True)
        deployed = wait_runtime(control, runtime_id, label)
        print(f"Ready: {label} version {deployed['agentRuntimeVersion']}", flush=True)
        if setting == "MOSAIC_AGENTCORE_RUNTIME_ARN":
            record_deploy(str(deployed["agentRuntimeVersion"]), application_sha256)
    phase(progress, 3)
    gateway = required("MOSAIC_AGENTCORE_GATEWAY_ID")
    target = required("MOSAIC_AGENTCORE_GATEWAY_TARGET_ID")
    control.synchronize_gateway_targets(
        gatewayIdentifier=gateway, targetIdList=[target]
    )
    print("Synchronizing Gateway tools from the tools runtime.", flush=True)
    deadline = time.monotonic() + 600
    state = "no status yet"
    while time.monotonic() < deadline:
        target_status = control.get_gateway_target(
            gatewayIdentifier=gateway, targetId=target
        )
        state = target_status["status"]
        if state == "READY":
            return
        if state in {"FAILED", "SYNCHRONIZE_UNSUCCESSFUL", "UPDATE_UNSUCCESSFUL"}:
            reasons = target_status.get("statusReasons") or ["no reason supplied"]
            raise RuntimeError(
                f"Gateway sync rule: the target is {state}: {safe_text(reasons[0])}; "
                f"fix: retry {DEPLOY_AGENT}; if it repeats, share this line with your facilitator."
            )
        time.sleep(5)
    raise TimeoutError(
        f"Gateway sync rule: the target was still {state} after 600 s; "
        f"fix: retry {DEPLOY_AGENT}; if it repeats, share this line with your facilitator."
    )


def require_applied_sql() -> str:
    """Refuse a deployment whose tools would call SQL other than the workspace's.

    The Runtime check covers the code the image runs; this covers the SQL the
    tools call, which lives in Aurora and changes only when it is applied.
    """
    from service.db import connect
    from service.search_sql import applied_sql_digest

    workspace = participant_sql_digest()
    with connect() as connection:
        applied = applied_sql_digest(connection)
    if applied != workspace:
        raise RuntimeError(
            "Aurora SQL rule: Aurora runs participant SQL "
            f"{(applied or 'with no recorded identity')[:12]}, not your workspace's "
            f"{workspace[:12]}; fix: apply the file with {APPLY_SQL}, then "
            f"recheck with {VERIFY_AGENT}."
        )
    return workspace


def verify() -> dict:
    """Exercise deployed source, Gateway discovery, search and evidence on Aurora."""
    status = agentcore_transport.deployed_status()
    deployed = status.get("application_sha256")
    workspace = application_digest()
    if deployed != workspace:
        raise RuntimeError(
            "Runtime acceptance rule: the deployed Retrieval agent runs code "
            f"{(deployed or 'with no recorded identity')[:12]}, not your workspace's "
            f"{workspace[:12]}; fix: deploy your current code with {DEPLOY_AGENT}."
        )
    database = status.get("readiness", {}).get("database", {})
    if not database.get("catalog_ready"):
        raise RuntimeError(
            "Runtime acceptance rule: the deployed Retrieval agent reports its catalog is not "
            f"ready ({safe_text(json.dumps(database, default=str), 300)}); this is an "
            f"environment failure, not your code. fix: share this message with your "
            f"facilitator, then recheck with {VERIFY_AGENT}."
        )
    workspace_sql = require_applied_sql()
    tools = gateway_tools.rpc("tools/list", {})
    names = {tool["name"] for tool in tools.get("tools", [])}
    expected = {
        f"{gateway_tools.TARGET_NAME}___{name}" for name in gateway_tools.TOOL_NAMES
    }
    if names != expected:
        raise RuntimeError(
            f"Gateway discovery rule: found {sorted(names)}; expected {sorted(expected)}. Synchronize the target."
        )
    from scripts.prove_lab import _case

    case = _case("exact-identity")
    response = gateway_tools.call_tool(
        "search_products",
        {
            "request": {
                "query": case["query"],
                "filters": case["filters"],
                "limit": 2,
                "authorized_limit": 2,
                "rerank": False,
                "include_diagnostics": True,
            }
        },
    )
    if not response.get("results"):
        raise RuntimeError(
            "Gateway search rule: exact-identity returned no products; inspect the deployed SQL tools."
        )
    searched_sql = (response.get("diagnostics") or {}).get("search_sql_sha256")
    if searched_sql != workspace_sql:
        raise RuntimeError(
            "Gateway SQL rule: the search through Gateway ran search SQL "
            f"{(searched_sql or 'with no recorded identity')[:12]}, not your lab files' "
            f"{workspace_sql[:12]}; fix: apply them with {APPLY_SQL}, then recheck "
            f"with {VERIFY_AGENT}."
        )
    product = response["results"][0]
    evidence = gateway_tools.call_tool(
        "get_product_evidence",
        {
            "product_id": product["product_id"],
            "request": {
                "retrieval_scope_id": response["search_event_id"],
                "evidence_query": case["query"],
                "limit": 1,
            },
        },
    )
    if not evidence.get("evidence"):
        raise RuntimeError(
            "Gateway evidence rule: no source record returned; inspect the evidence grant."
        )
    receipt = {
        "application_sha256": application_digest(),
        "participant_sql_sha256": participant_sql_digest(),
        "runtime_arn": required("MOSAIC_AGENTCORE_RUNTIME_ARN"),
        "gateway_url": required("MOSAIC_AGENTCORE_GATEWAY_URL"),
        "search_event_id": response["search_event_id"],
    }
    destination = ROOT / ".local/agentcore/deployment.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        "A search through Gateway ran your Lab 1 and Lab 2 SQL in Aurora "
        f"({workspace_sql[:12]}): passed"
    )
    print("Runtime code, Gateway discovery, Aurora search and scoped evidence: passed")
    return receipt


RUNTIME_ROLES = (
    (
        "MOSAIC_AGENTCORE_RUNTIME_ARN",
        "Retrieval agent runtime",
        (
            "your create_agent: the Retrieval agent, with compare_products and "
            "synthesize_cited_answer"
        ),
    ),
    (
        "MOSAIC_AGENTCORE_TOOLS_RUNTIME_ARN",
        "Tools runtime",
        "the SQL tools: search, source records and saved retrieval runs",
    ),
)


def _when(value: object) -> str:
    return f"{value:%H:%M} UTC" if hasattr(value, "strftime") else "unknown"


def _row(label: str, *cells: object) -> str:
    return f"  {label:<24} " + "   ".join(str(cell) for cell in cells)


def _runtime_lines(control) -> list[str]:
    lines = []
    for variable, label, role in RUNTIME_ROLES:
        runtime_id = required(variable).rsplit("/", 1)[-1]
        runtime = control.get_agent_runtime(agentRuntimeId=runtime_id)
        lines.append(
            _row(
                label,
                runtime["agentRuntimeName"],
                runtime["status"],
                f"version {runtime['agentRuntimeVersion']}",
                f"updated {_when(runtime.get('lastUpdatedAt'))}",
            )
        )
        lines.append(_row("", role))
    return lines


def _gateway_lines(control) -> list[str]:
    gateway_id = required("MOSAIC_AGENTCORE_GATEWAY_ID")
    gateway = control.get_gateway(gatewayIdentifier=gateway_id)
    target = control.get_gateway_target(
        gatewayIdentifier=gateway_id,
        targetId=required("MOSAIC_AGENTCORE_GATEWAY_TARGET_ID"),
    )
    return [
        _row(
            "Gateway",
            gateway["name"],
            gateway["status"],
            gateway.get("protocolType", ""),
        ),
        _row(
            "",
            f"target {target['name']}, {target['status']}, synchronized "
            f"{_when(target.get('lastSynchronizedAt'))}: the three SQL tools the Retrieval agent calls",
        ),
    ]


def _memory_lines(control) -> list[str]:
    memory_id = os.getenv("MOSAIC_AGENTCORE_MEMORY_ID", "").strip()
    if not memory_id:
        return [_row("Memory", "not configured (optional)")]
    memory = control.get_memory(memoryId=memory_id)["memory"]
    strategies = ", ".join(
        f"{strategy['name']} ({strategy['type']})"
        for strategy in memory.get("strategies", [])
    )
    return [
        _row("Memory", memory["name"], memory["status"]),
        _row(
            "",
            f"strategies: {strategies or 'none'}; conversation context, never product facts",
        ),
    ]


def resources() -> None:
    """Show this event's runtimes, Gateway and Memory by ID, with read-only Get calls.

    The Code Editor role reads the resources it deployed but holds no List* discovery
    actions, so every resource is named from the workshop's .env.
    """
    control = client("bedrock-agentcore-control")
    lines = _runtime_lines(control) + _gateway_lines(control) + _memory_lines(control)
    print("AgentCore resources in this event (read-only):")
    print("\n".join(lines))
    print(
        "Next: when your deploy finishes, run this again; the Retrieval agent runtime shows a "
        "new version and update time."
    )


def retry_command(action: str) -> str:
    """The command to repeat after a failed action."""
    if action == "verify":
        return VERIFY_AGENT
    if action == "deploy":
        return DEPLOY_AGENT
    if action == "resources":
        return AGENTCORE_RESOURCES
    return f"uv run python scripts/deploy_agentcore.py {action}"


def explain_failure(error: Exception, retry: str) -> str:
    """Name the AWS code, message and next command without leaking secrets."""
    if isinstance(error, ClientError):
        details = error.response.get("Error", {})
        code = details.get("Code", "UnknownError")
        action = (
            "this instance's IAM role is not allowed to do that; share this line "
            f"with your facilitator, who fixes it, then retry {retry}"
            if "AccessDenied" in code or "Unauthorized" in code
            else f"retry {retry}; if it repeats, share this line with your facilitator"
        )
        return (
            f"AWS rule: {error.operation_name} failed with {code}: "
            f"{safe_text(details.get('Message', 'no message supplied'))}; fix: {action}."
        )
    if isinstance(error, BotoCoreError):
        return (
            f"AWS rule: the request failed ({type(error).__name__}): "
            f"{safe_text(error)}; fix: check the Code Editor's network connection, "
            f"then retry {retry}."
        )
    if isinstance(error, (OSError, subprocess.SubprocessError)):
        return (
            f"Local file or process rule: {type(error).__name__}: {safe_text(error)}; "
            f"fix: correct that problem, then retry {retry}."
        )
    return safe_text(error, 1500)


def not_ready_message(
    agent_file: Path = ROOT / "labs" / "lab3_reason" / "agent.py",
) -> str:
    """Why the Retrieval agent cannot deploy: a code mistake or the contract part it misses."""
    from scripts.lab_state import lab3_contract_problem

    source = agent_file.read_text(encoding="utf-8")
    try:
        compile(source, str(agent_file), "exec")
    except SyntaxError as error:
        return agent_code_message(error)
    problem = lab3_contract_problem(source)
    if problem is None or problem == AGENT_NOT_BUILT:
        return (
            "Your Retrieval agent is not ready to deploy. Open labs/lab3_reason/agent.py, "
            f"complete create_agent, then deploy with {DEPLOY_AGENT} again."
        )
    return (
        f"Your Retrieval agent is not ready to deploy: in labs/lab3_reason/agent.py, "
        f"{problem}. Fix that, save, then deploy with {DEPLOY_AGENT} again."
    )


def write_connection_values(paths: tuple[Path, ...], values: dict[str, str]) -> None:
    """Put the discovered connection keys into each env file, replacing earlier copies.

    A bootstrap resumed after a reboot runs connect-bootstrap again, so the keys are
    replaced rather than appended a second time.
    """
    for path in paths:
        kept = [
            line
            for line in path.read_text().splitlines()
            if line.split("=", 1)[0] not in values
        ]
        staged = path.with_name(path.name + ".next")
        staged.write_text(
            "".join(f"{line}\n" for line in kept)
            + "".join(f"{key}='{value}'\n" for key, value in values.items())
        )
        # A reboot between truncate and write would leave the API without its keys.
        os.replace(staged, path)


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "stage-bootstrap and connect-bootstrap run only during provisioning, "
            "from the host's bootstrap; participants use deploy, verify, tools "
            "and resources."
        ),
    )
    parser.add_argument(
        "action",
        help=(
            "tools, deploy, verify and resources are the participant commands; "
            "stage-bootstrap (publish the image and store the runtime DSN) and "
            "connect-bootstrap (write the discovered connection keys, then verify) "
            "run only during provisioning"
        ),
        choices=(
            "stage-bootstrap",
            "connect-bootstrap",
            "deploy",
            "verify",
            "tools",
            "resources",
        ),
    )
    args = parser.parse_args()
    try:
        if args.action == "stage-bootstrap":
            stage(bootstrap=True)
        elif args.action == "connect-bootstrap":
            values = discover()
            write_connection_values(
                (ROOT / ".env", Path("/etc/mosaic-api.env")), values
            )
            os.environ.update(values)
            verify()
        elif args.action == "deploy":
            from scripts.lab_state import lab_is_solved

            if not lab_is_solved(3):
                raise ValueError(not_ready_message())
            progress = deploy_progress()
            code = application_digest()
            try:
                phase(progress, 0)
                update(stage(), progress, code)
                phase(progress, 4)
                verify()
            except BaseException:
                # Ends the running phase's bar, so the failure prints on a clean line.
                progress.fail()
                raise
            progress.finish()
            print(
                "Your Retrieval agent is deployed and its SQL tools are connected through "
                f"Gateway. Next: ask Alex's setup request:\n{ask_setup()}"
            )
        elif args.action == "resources":
            resources()
        elif args.action == "tools":
            for tool in gateway_tools.rpc("tools/list", {}).get("tools", []):
                print(f"{tool['name']}: {tool.get('description', '')}")
            print(
                "Next: open labs/lab3_reason/agent.py and connect these SQL tools to your Retrieval agent."
            )
        else:
            verify()
        return 0
    except (
        OSError,
        subprocess.SubprocessError,
        BotoCoreError,
        ClientError,
        ValueError,
        RuntimeError,
        TimeoutError,
    ) as error:
        print(explain_failure(error, retry_command(args.action)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
