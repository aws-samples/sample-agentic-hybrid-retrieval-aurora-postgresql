#!/usr/bin/env python3
"""Invoke Verity's managed AgentCore Gateway with the current AWS identity."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


def _gateway_url() -> str:
    value = os.environ.get("AGENTCORE_GATEWAY_URL", "").strip()
    if not value:
        raise RuntimeError(
            "AGENTCORE_GATEWAY_URL is not set. In Workshop Studio, run "
            "`set -a; source /workshop/.env; set +a`."
        )
    return value if value.endswith("/mcp") else f"{value.rstrip('/')}/mcp"


def _signed_headers(url: str, body: bytes, region: str) -> dict[str, str]:
    credentials = boto3.Session().get_credentials()
    if credentials is None:
        raise RuntimeError("No AWS credentials are available for AgentCore Gateway.")
    request = AWSRequest(
        method="POST",
        url=url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    SigV4Auth(
        credentials.get_frozen_credentials(),
        "bedrock-agentcore",
        region,
    ).add_auth(request)
    return dict(request.headers)


def _mcp_request(
    url: str,
    region: str,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": f"verity-{method.replace('/', '-')}",
        "method": method,
    }
    if params is not None:
        payload["params"] = params
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers=_signed_headers(url, body, region),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"AgentCore Gateway returned HTTP {exc.code}: {detail}") from exc
    if result.get("error"):
        raise RuntimeError(f"AgentCore Gateway returned an MCP error: {result['error']}")
    return result


def _tool_name(tools: list[dict[str, Any]], suffix: str) -> str:
    for tool in tools:
        name = str(tool.get("name") or "")
        if name == suffix or name.endswith(f"___{suffix}"):
            return name
    available = ", ".join(str(tool.get("name") or "") for tool in tools)
    raise RuntimeError(f"Gateway tool '{suffix}' was not found. Available: {available}")


def _text_result(response: dict[str, Any]) -> dict[str, Any]:
    for block in (response.get("result") or {}).get("content") or []:
        if block.get("type") == "text" and block.get("text"):
            parsed = json.loads(block["text"])
            if isinstance(parsed, dict):
                if parsed.get("error"):
                    raise RuntimeError(str(parsed["error"]))
                wrapped = parsed.get("result")
                return wrapped if isinstance(wrapped, dict) else parsed
    raise RuntimeError("Gateway response did not contain an MCP text result.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prove Verity's Aurora retrieval contract through AgentCore Gateway."
    )
    parser.add_argument(
        "--query",
        default="Why did CHG-1842 block writes on checkout-prod-cluster-01?",
    )
    parser.add_argument("--cluster-id", default="checkout-prod-cluster-01")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--assert-incident",
        action="store_true",
        help="Fail unless CHG-1842 is the first ranked evidence item.",
    )
    args = parser.parse_args()

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    url = _gateway_url()
    identity = boto3.client("sts", region_name=region).get_caller_identity()

    listed = _mcp_request(url, region, "tools/list")
    tools = (listed.get("result") or {}).get("tools") or []
    search_tool_name = _tool_name(tools, "search_evidence")
    search_called = _mcp_request(
        url,
        region,
        "tools/call",
        {
            "name": search_tool_name,
            "arguments": {
                "query": args.query,
                "cluster_id": args.cluster_id,
                "limit": args.limit,
            },
        },
    )
    search_receipt = _text_result(search_called)
    results = search_receipt.get("results") or []
    if not results:
        raise RuntimeError("The managed retrieval returned no evidence rows.")
    top = results[0]
    if args.assert_incident and top.get("external_key") != "CHG-1842":
        raise RuntimeError(
            f"Expected CHG-1842 first, found {top.get('external_key') or 'unknown'}."
        )

    answer_tool_name = _tool_name(tools, "answer_with_citations")
    answer_called = _mcp_request(
        url,
        region,
        "tools/call",
        {
            "name": answer_tool_name,
            "arguments": {
                "question": (
                    "Why did CHG-1842 block checkout writes during INC-2047, "
                    "which visible customer was affected, and what was the safe fix?"
                ),
                "limit": 8,
            },
        },
    )
    answer_receipt = _text_result(answer_called)
    citations = answer_receipt.get("citations") or []
    if not citations:
        raise RuntimeError("The managed cited answer returned no citations.")
    if args.assert_incident:
        if answer_receipt.get("run_id") is None:
            raise RuntimeError(
                "The managed cited answer did not return a retrieval run ID."
            )
        if any(not citation.get("source_revision") for citation in citations):
            raise RuntimeError("At least one managed citation lacks a source revision.")

    print("MANAGED SEARCH RECEIPT")
    print(f"Gateway: {os.environ.get('AGENTCORE_GATEWAY_ID', 'managed')}")
    print("Authorization: AWS_IAM (SigV4)")
    print(f"Principal: {identity.get('Arn', 'unknown')}")
    print(f"Tool: {search_tool_name}")
    print(f"Run: {search_receipt.get('run_id')}")
    print(f"Mode: {search_receipt.get('retrieval_mode')}")
    print(
        "Top:",
        top.get("source_system"),
        top.get("external_key"),
        f"rerank={float(top.get('rerank_score') or 0):.3f}",
        f"sql={float(top.get('final_score') or 0):.3f}",
    )
    print()
    print("MANAGED CITED-ANSWER RECEIPT")
    print(f"Tool: {answer_tool_name}")
    print(f"Run: {answer_receipt.get('run_id')}")
    print(
        "Evidence:",
        f"citations={len(citations)}",
        f"synthesis={((answer_receipt.get('synthesis') or {}).get('mode'))}",
    )
    plan = answer_receipt.get("plan") or {}
    print(f"Plan steps: {len(plan.get('steps') or [])}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
