"""Lambda MCP adapter for the Strands retrieval tools.

This module is deployable code only. Workshop Studio owns any Lambda,
permissions, and AgentCore Gateway resources that front it.
"""
from __future__ import annotations

import json
from typing import Any

from backend.app.agent import (
    _infer_sources,
    follow_evidence_links_impl,
    search_evidence_impl,
    synthesize_cited_answer_impl,
)

GATEWAY_TOOL_DELIMITER = "___"


def _resolve_tool_name(event: dict[str, Any], context: Any) -> str:
    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    gateway_tool = custom.get("bedrockAgentCoreToolName")
    if gateway_tool:
        return gateway_tool.split(GATEWAY_TOOL_DELIMITER)[-1]
    return str(event.get("tool") or event.get("name") or "")


def _resolve_args(event: dict[str, Any]) -> dict[str, Any]:
    args = event.get("arguments") if isinstance(event, dict) else {}
    if isinstance(args, dict):
        return args
    return event if isinstance(event, dict) else {}


def _mcp_result(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}


def _search_evidence(args: dict[str, Any]) -> dict[str, Any]:
    return search_evidence_impl(
        query=args.get("query", ""),
        source_systems=args.get("source_systems"),
        project_key=args.get("project_key"),
        account_name=args.get("account_name"),
        component=args.get("component"),
        limit=int(args.get("limit") or 8),
    )


def _synthesize(args: dict[str, Any]) -> dict[str, Any]:
    return synthesize_cited_answer_impl(
        question=args.get("question", ""),
        results=args.get("results") or [],
    )


def _follow_evidence_links(args: dict[str, Any]) -> dict[str, Any]:
    return follow_evidence_links_impl(
        seed_external_ids=args.get("seed_external_ids") or [],
        max_depth=int(args.get("max_depth") or 3),
    )


TOOLS = {
    "infer_sources": lambda args: _infer_sources(args.get("question", "")),
    "search_evidence": _search_evidence,
    "follow_evidence_links": _follow_evidence_links,
    "synthesize_cited_answer": _synthesize,
}


def lambda_handler(event, context):
    event = event or {}
    tool_name = _resolve_tool_name(event, context)
    args = _resolve_args(event)
    impl = TOOLS.get(tool_name)
    if impl is None:
        return _mcp_result({"error": f"Unknown tool '{tool_name}'", "tools": sorted(TOOLS)})

    try:
        return _mcp_result({"tool": tool_name, "result": impl(args)})
    except Exception as exc:
        return _mcp_result({"tool": tool_name, "error": str(exc)})
