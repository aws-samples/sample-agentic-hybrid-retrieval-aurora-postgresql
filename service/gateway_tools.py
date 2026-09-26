"""Call the workshop's SQL tools through AgentCore Gateway using MCP and IAM."""

from __future__ import annotations

import json
import os
import re
from uuid import uuid4

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from service.agent_setup import AgentSetupError
from service.config import get_settings

TARGET_NAME = "mosaic"
TOOL_NAMES = ("search_products", "get_product_evidence", "inspect_retrieval_run")


def gateway_url() -> str | None:
    value = os.getenv("MOSAIC_AGENTCORE_GATEWAY_URL", "").strip()
    if not value:
        return None
    if not re.fullmatch(
        r"https://[a-z0-9-]+\.gateway\.bedrock-agentcore\.[a-z0-9-]+\.amazonaws\.com/mcp",
        value,
    ):
        raise RuntimeError(
            "Gateway destination rule: invalid MOSAIC_AGENTCORE_GATEWAY_URL; "
            "fix: use this workshop's Gateway MCP URL."
        )
    return value


def rpc(method: str, params: dict) -> dict:
    """Sign each call with refreshed role credentials; never retry a search."""
    endpoint = gateway_url()
    if endpoint is None:
        raise RuntimeError(
            "Gateway is not configured; fix: load the workshop environment."
        )
    request_id = str(uuid4())
    body = json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    )
    credentials = boto3.Session().get_credentials()
    if credentials is None:
        raise RuntimeError(
            "Gateway IAM rule: no role credentials; fix: check the Runtime execution role."
        )
    signed = AWSRequest(
        method="POST",
        url=endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-03-26",
        },
    )
    SigV4Auth(
        credentials.get_frozen_credentials(),
        "bedrock-agentcore",
        get_settings().aws_region,
    ).add_auth(signed)
    try:
        with httpx.Client(
            timeout=httpx.Timeout(90, connect=10), follow_redirects=False
        ) as client:
            response = client.post(endpoint, content=body, headers=dict(signed.headers))
            response.raise_for_status()
    except httpx.HTTPError as error:
        raise AgentSetupError(
            "The agent could not reach its SQL tools through Gateway. In Code Editor, "
            "run make verify-agent. Next: share a failed deployment check with your facilitator, "
            "or retry your question if the check passes."
        ) from error
    try:
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            messages = [
                json.loads(line[5:].strip())
                for line in response.text.splitlines()
                if line.startswith("data:")
            ]
            payload = next(
                (
                    item
                    for item in messages
                    if isinstance(item, dict) and item.get("id") == request_id
                ),
                {},
            )
        else:
            payload = response.json()
    except (ValueError, KeyError, TypeError) as error:
        raise AgentSetupError(
            "Gateway returned an unreadable tool response. Next: run make verify-agent in Code Editor and share the message with your facilitator."
        ) from error
    if (
        not isinstance(payload, dict)
        or payload.get("id") != request_id
        or "error" in payload
        or not isinstance(payload.get("result"), dict)
    ):
        raise AgentSetupError(
            "Gateway could not complete the tool request. Next: run make verify-agent in Code Editor; ask your facilitator to inspect the Gateway target if it fails."
        )
    return payload["result"]


def call_tool(name: str, arguments: dict) -> dict:
    """Validate both the MCP result and the code version that produced it."""
    from service.lab_validation_receipt import source_digest

    if name not in TOOL_NAMES:
        raise ValueError(f"Unknown Mosaic SQL tool: {name}")
    result = rpc(
        "tools/call", {"name": f"{TARGET_NAME}___{name}", "arguments": arguments}
    )
    if result.get("isError"):
        raise AgentSetupError(
            f"Gateway tool {name} refused the request; check the retrieval scope and target logs."
        )
    try:
        envelope = result.get("structuredContent")
        if envelope is None:
            blocks = result.get("content", [])
            texts = [
                item.get("text")
                for item in blocks
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            envelope = json.loads(texts[0]) if len(texts) == 1 else None
        if not isinstance(envelope, dict) or not isinstance(envelope.get("data"), dict):
            raise TypeError("Missing tool data")
    except (ValueError, TypeError) as error:
        raise AgentSetupError(
            "Gateway returned incomplete tool data. Next: run make verify-agent in Code Editor and share the message with your facilitator."
        ) from error
    if envelope.get("source_sha256") != source_digest():
        raise AgentSetupError(
            "The deployed SQL tools differ from your workspace. Next: run make deploy-agent in Code Editor, then ask your question again."
        )
    return envelope["data"]
