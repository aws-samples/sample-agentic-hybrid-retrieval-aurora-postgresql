"""Lambda adapter for Verity's AgentCore Gateway MCP tools.

Workshop Studio owns the Lambda function, IAM permissions, Gateway, and target.
This module keeps the managed boundary on the same application functions and
persisted Aurora receipts as the HTTP and local MCP paths. The tool dispatch table
is generated from ``agent/registry.py`` (see ``lambda_mcp/generated_dispatch.py``);
this file owns only the Lambda envelope, so G-17 diffs the transport, not adapter
logic.
"""
from __future__ import annotations

import json
from typing import Any

from backend.app.contracts import InvocationContext, invoke_contract, new_request_id
from lambda_mcp.generated_dispatch import TOOLS

GATEWAY_TOOL_DELIMITER = "___"


def _resolve_tool_name(event: dict[str, Any], context: Any) -> str:
    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    gateway_tool = custom.get("bedrockAgentCoreToolName")
    if gateway_tool:
        return gateway_tool.split(GATEWAY_TOOL_DELIMITER)[-1]
    return str(event.get("tool") or event.get("name") or "")


def _resolve_args(event: dict[str, Any]) -> dict[str, Any]:
    arguments = event.get("arguments")
    if isinstance(arguments, dict):
        return arguments
    return {
        key: value
        for key, value in event.items()
        if key not in {"tool", "name", "arguments"}
    }


def _mcp_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
        "isError": is_error,
    }


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    tool_name = _resolve_tool_name(event, context)
    implementation = TOOLS.get(tool_name)
    if implementation is None:
        return _mcp_result(
            {
                "error": f"Unknown tool '{tool_name}'",
                "tools": sorted(TOOLS),
            },
            is_error=True,
        )

    args = _resolve_args(event)
    request_id = str(
        event.get("request_id")
        or getattr(context, "aws_request_id", "")
        or new_request_id()
    )
    invocation = InvocationContext(
        transport="agentcore_gateway",
        request_id=request_id,
        transport_trace_id=str(
            event.get("transport_trace_id")
            or getattr(context, "aws_request_id", "")
            or ""
        )
        or None,
    )
    try:
        result = invoke_contract(
            invocation,
            tool_name,
            args,
            lambda: implementation(args),
        )
        return _mcp_result({"tool": tool_name, "result": result})
    except Exception as error:
        return _mcp_result(
            {"tool": tool_name, "error": str(error)},
            is_error=True,
        )
