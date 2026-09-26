"""Package, deploy and verify the workshop's agent and SQL tool runtimes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.package_agentcore import package
from service import agentcore_transport, gateway_tools
from service.lab_validation_receipt import source_digest


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


def stage(*, bootstrap: bool = False) -> tuple[str, str]:
    """Upload code to this participant account; credentials never enter the ZIP."""
    archive = ROOT / ".local/agentcore/mosaic.zip"
    package(ROOT, archive, archive.parent)
    with archive.open("rb") as source:
        sha = hashlib.file_digest(source, "sha256").hexdigest()
    key = (
        f"bootstrap/{required('SOURCE_REVISION')}.zip"
        if bootstrap
        else f"deployments/{sha}.zip"
    )
    bucket = required("MOSAIC_RUNTIME_CODE_BUCKET")
    client("s3").upload_file(
        str(archive),
        bucket,
        key,
        ExtraArgs={
            "ContentType": "application/zip",
            "Metadata": {"sha256": sha},
        },
    )
    if bootstrap:
        from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

        # The host's absolute certificate path does not exist in the managed
        # runtime. Both ZIP entry points start in the package root.
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
    return bucket, key


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
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        values = {}
        try:
            for resource, setting in logical.items():
                row = cfn.describe_stack_resource(
                    StackName=stack, LogicalResourceId=resource
                )["StackResourceDetail"]
                if row.get("ResourceStatus") not in {
                    "CREATE_COMPLETE",
                    "UPDATE_COMPLETE",
                }:
                    break
                values[setting] = row["PhysicalResourceId"]
            if len(values) == len(logical):
                values["MOSAIC_AGENTCORE_GATEWAY_TARGET_ID"] = values[
                    "MOSAIC_AGENTCORE_GATEWAY_TARGET_ID"
                ].split("|")[-1]
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
        except ClientError as error:
            # The EC2 CreationPolicy is already satisfied, so Runtime creation
            # and the policy attaching its exact ARNs finish asynchronously.
            if error.response["Error"]["Code"] not in {
                "ValidationError",
                "ResourceNotFoundException",
                "AccessDeniedException",
            }:
                raise
        time.sleep(5)
    raise TimeoutError(
        "Managed resources did not finish provisioning; inspect the workshop stack events."
    )


def update(bucket: str, key: str) -> None:
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
        payload["agentRuntimeArtifact"]["codeConfiguration"]["code"] = {
            "s3": {"bucket": bucket, "prefix": key}
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


def verify() -> dict:
    """Exercise deployed source, Gateway discovery, search and evidence on Aurora."""
    status = agentcore_transport.deployed_status()
    if status.get("source_sha256") != source_digest() or not status.get(
        "readiness", {}
    ).get("database", {}).get("catalog_ready"):
        raise RuntimeError(
            "Runtime acceptance rule: stale code or catalog not ready; redeploy and check Aurora readiness."
        )
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
        "source_sha256": source_digest(),
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
                    "Your agent is not ready to deploy. Open labs/lab3/agent.py, complete create_agent, then run make deploy-agent again."
                )
            update(*stage())
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
        else:
            print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
