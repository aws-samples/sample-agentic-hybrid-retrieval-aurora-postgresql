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

from scripts.package_agentcore import package
from scripts.rehearsal import redact
from service import agentcore_transport, gateway_tools
from service.lab_validation_receipt import application_digest, participant_sql_digest
from service.participant_commands import APPLY_SQL, DEPLOY_AGENT, VERIFY_AGENT


def client(service: str):
    return boto3.client(
        service,
        region_name=os.getenv("AWS_REGION", "us-east-1"),
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
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    if attempt == 2:
                        raise RuntimeError(
                            "Registry login rule: ECR login failed after three attempts; "
                            f"fix: check the Code Editor's ECR permissions and HTTPS connectivity, then retry {DEPLOY_AGENT}."
                        ) from None
                    time.sleep(2**attempt)
            image = f"{repository_uri}:{tag}"
            subprocess.run(
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
                check=True,
                env=environment,
                timeout=1200,
            )
            subprocess.run(
                ["docker", "push", image], check=True, env=environment, timeout=600
            )
            digest = image_digest(ecr, repository, tag)
            if digest is None:
                raise RuntimeError(
                    "Runtime image rule: pushed image is absent from ECR; retry deployment."
                )
        print(f"Runtime image ready: {tag} ({digest})")
        return f"{repository_uri}@{digest}"


def stage(*, bootstrap: bool = False) -> str:
    """Publish the image before releasing CloudFormation's runtime dependency."""
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
        client("cloudformation").signal_resource(
            StackName=required("MOSAIC_EDITOR_STACK"),
            LogicalResourceId="CodeEditorInstance",
            UniqueId="userdata",
            Status="SUCCESS",
        )
    return image_uri


def wait_runtime(control, runtime_id: str) -> dict:
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        runtime = control.get_agent_runtime(agentRuntimeId=runtime_id)
        if runtime["status"] == "READY":
            endpoint = control.get_agent_runtime_endpoint(
                agentRuntimeId=runtime_id, endpointName="DEFAULT"
            )
            if (
                endpoint["status"] == "READY"
                and endpoint.get("liveVersion") == runtime["agentRuntimeVersion"]
            ):
                return runtime
        if runtime["status"] in {"CREATE_FAILED", "UPDATE_FAILED", "DELETING"}:
            raise RuntimeError(
                f"Runtime {runtime_id} is {runtime['status']}; inspect its deployment events."
            )
        time.sleep(5)
    raise TimeoutError(
        f"Runtime {runtime_id} did not become ready; inspect CloudFormation and Runtime status."
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
                    reason = redact(
                        row.get("ResourceStatusReason", "No reason supplied")
                    )
                    for name, value in os.environ.items():
                        if value and any(
                            part in name
                            for part in ("PASSWORD", "SECRET", "TOKEN", "DATABASE_URL")
                        ):
                            for variant in (
                                value,
                                quote(value, safe=""),
                                quote_plus(value),
                            ):
                                reason = reason.replace(variant, "[REDACTED]")
                    reason = " ".join(reason.split())[:800]
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


def update(image_uri: str) -> None:
    control = client("bedrock-agentcore-control")
    fields = set(
        control.meta.service_model.operation_model(
            "UpdateAgentRuntime"
        ).input_shape.members
    )
    for setting in (
        "MOSAIC_AGENTCORE_TOOLS_RUNTIME_ARN",
        "MOSAIC_AGENTCORE_RUNTIME_ARN",
    ):
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
        deployed = wait_runtime(control, runtime_id)
        print(f"Ready: {setting} version {deployed['agentRuntimeVersion']}")
    gateway = required("MOSAIC_AGENTCORE_GATEWAY_ID")
    target = required("MOSAIC_AGENTCORE_GATEWAY_TARGET_ID")
    control.synchronize_gateway_targets(
        gatewayIdentifier=gateway, targetIdList=[target]
    )
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        state = control.get_gateway_target(gatewayIdentifier=gateway, targetId=target)[
            "status"
        ]
        if state == "READY":
            return
        if state in {"FAILED", "SYNCHRONIZE_UNSUCCESSFUL", "UPDATE_UNSUCCESSFUL"}:
            raise RuntimeError(
                f"Gateway target is {state}; inspect its status reasons."
            )
        time.sleep(5)
    raise TimeoutError(
        "Gateway tool synchronization timed out; inspect its target status."
    )


def require_applied_sql() -> str:
    """Refuse a deployment whose tools would call SQL other than the workspace's.

    The Runtime check covers the code the image runs; this covers the SQL the
    tools call, which lives in Aurora and changes only when it is applied.
    """
    from scripts.apply_search_functions import applied_sql_digest
    from service.db import connect

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
    if status.get("application_sha256") != application_digest() or not status.get(
        "readiness", {}
    ).get("database", {}).get("catalog_ready"):
        raise RuntimeError(
            "Runtime acceptance rule: stale code or catalog not ready; redeploy and check Aurora readiness."
        )
    require_applied_sql()
    tools = gateway_tools.rpc("tools/list", {})
    names = {tool["name"] for tool in tools.get("tools", [])}
    expected = {
        f"{gateway_tools.TARGET_NAME}___{name}" for name in gateway_tools.TOOL_NAMES
    }
    if names != expected:
        raise RuntimeError(
            f"Gateway discovery rule: found {sorted(names)}; expected {sorted(expected)}. Synchronize the target."
        )
    from scripts.validate_lab import _case

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
            }
        },
    )
    if not response.get("results"):
        raise RuntimeError(
            "Gateway search rule: exact-identity returned no products; inspect the deployed SQL tools."
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
    print("Runtime code, Gateway discovery, Aurora search and scoped evidence: passed")
    return receipt


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("stage-bootstrap", "connect-bootstrap", "deploy", "verify", "tools"),
    )
    args = parser.parse_args()
    try:
        if args.action == "stage-bootstrap":
            stage(bootstrap=True)
        elif args.action == "connect-bootstrap":
            values = discover()
            for path in (ROOT / ".env", Path("/etc/mosaic-api.env")):
                with path.open("a") as output:
                    for key, value in values.items():
                        output.write(f"{key}='{value}'\n")
            os.environ.update(values)
            verify()
        elif args.action == "deploy":
            from scripts.lab_state import lab_is_solved

            if not lab_is_solved(3):
                raise ValueError(
                    f"Your agent is not ready to deploy. Open labs/lab3/agent.py, complete create_agent, then deploy with {DEPLOY_AGENT} again."
                )
            update(stage())
            verify()
            print(
                "Your agent is deployed and its SQL tools are connected through Gateway. Next: open Mosaic → Playground → Reason and ask Alex's question."
            )
        elif args.action == "tools":
            for tool in gateway_tools.rpc("tools/list", {}).get("tools", []):
                print(f"{tool['name']}: {tool.get('description', '')}")
            print(
                "Next: open labs/lab3/agent.py and connect these SQL tools to your Strands agent."
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
        # AWS exceptions can include deployment environment values. The console
        # has the service details; the participant sees a safe actionable error.
        if isinstance(error, (BotoCoreError, ClientError)):
            print(
                f"Deployment failed ({type(error).__name__}); inspect the Runtime/Gateway events and this instance's IAM role.",
                file=sys.stderr,
            )
        elif isinstance(error, (OSError, subprocess.SubprocessError)):
            print(
                f"Image build/push failed; check Docker is running and this instance can reach ECR, then retry {DEPLOY_AGENT}.",
                file=sys.stderr,
            )
        else:
            print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
