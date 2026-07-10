"""AgentCore Gateway Lambda MCP target for the hybrid retrieval engine.

This Lambda backs four MCP tools exposed by the AgentCore Gateway:

  * full_text_search  -> ops.full_text_search  (lexical / tsvector)
  * vector_search     -> ops.vector_search     (semantic / pgvector cosine)
  * fuzzy_match       -> ops.fuzzy_match        (pg_trgm typo-tolerant)
  * hybrid_search     -> ops.hybrid_search      (RRF fusion of all three)

Every tool wraps the SAME SQL the API uses. In particular full_text_search
calls ops.full_text_search, which builds its tsquery through ops.to_or_tsquery
-- the single home of the OR-combine invariant. Do not inline a websearch_to_tsquery
here or the exact-ID teaching moment (ORION-1489 surfacing by lexical match)
silently breaks in this tool too.

The same handler answers three invocation shapes so it can be dropped behind an
AgentCore Gateway, a classic Bedrock Agent action group, or a direct test call
(see resolve_invocation).
"""
from __future__ import annotations

import json
import os
from typing import Any

import psycopg
from psycopg.rows import dict_row

# Tool argument delimiter used by AgentCore Gateway. The Gateway prefixes the
# tool name with the target name, e.g. "retrieval___full_text_search"; we split
# on this and keep the trailing tool name.
GATEWAY_TOOL_DELIMITER = "___"

# Five connected systems (ServiceNow is out of scope for this workshop).
ALL_SYSTEMS = ["slack", "jira", "confluence", "salesforce", "github"]

DEFAULT_EMBEDDING_MODEL = os.environ.get("BEDROCK_EMBEDDING_MODEL", "us.cohere.embed-v4:0")
EMBED_DIM = int(os.environ.get("EMBED_DIM", "1024"))
AWS_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))


# --------------------------------------------------------------------------- #
# Database access
# --------------------------------------------------------------------------- #
_DATABASE_URL: str | None = None


def _database_url() -> str:
    """Resolve the Aurora/Postgres connection string.

    Prefers DATABASE_URL. Otherwise reconstructs it from the CDK-provided
    AURORA_SECRET_ARN + AURORA_CLUSTER_ENDPOINT + AURORA_DATABASE_NAME, reading
    the credentials from Secrets Manager. Cached across warm invocations.
    """
    global _DATABASE_URL
    if _DATABASE_URL:
        return _DATABASE_URL

    url = os.environ.get("DATABASE_URL")
    if url:
        _DATABASE_URL = url
        return _DATABASE_URL

    secret_arn = os.environ.get("AURORA_SECRET_ARN")
    host = os.environ.get("AURORA_CLUSTER_ENDPOINT")
    dbname = os.environ.get("AURORA_DATABASE_NAME", "retrieval")
    if not (secret_arn and host):
        raise RuntimeError(
            "Set DATABASE_URL, or AURORA_SECRET_ARN + AURORA_CLUSTER_ENDPOINT so the "
            "Gateway Lambda can reach Aurora."
        )

    import boto3
    from urllib.parse import quote

    secret = json.loads(
        boto3.client("secretsmanager", region_name=AWS_REGION)
        .get_secret_value(SecretId=secret_arn)["SecretString"]
    )
    user = quote(secret["username"], safe="")
    password = quote(secret["password"], safe="")
    port = secret.get("port", 5432)
    _DATABASE_URL = f"postgresql://{user}:{password}@{host}:{port}/{dbname}?sslmode=require"
    return _DATABASE_URL


def _run(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with psycopg.connect(_database_url(), autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


# --------------------------------------------------------------------------- #
# Embeddings (semantic arm) -- Cohere embed-v4 via Bedrock, same space as the
# seeded corpus. Mirrors backend/app/embeddings.py so vector_search compares
# vectors in the same space the dump was built in.
# --------------------------------------------------------------------------- #
def _embed_query(text: str) -> str:
    import boto3

    body = {
        "texts": [text],
        "input_type": "search_query",
        "embedding_types": ["float"],
        "output_dimension": EMBED_DIM,
        "truncate": "END",
    }
    resp = boto3.client("bedrock-runtime", region_name=AWS_REGION).invoke_model(
        modelId=DEFAULT_EMBEDDING_MODEL, body=json.dumps(body)
    )
    payload = json.loads(resp["body"].read())
    embeddings = payload.get("embeddings")
    if isinstance(embeddings, dict):
        embeddings = embeddings.get("float") or embeddings.get("floats")
    if not (isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list)):
        raise ValueError("Bedrock embedding response did not include a float embedding.")
    return "[" + ",".join(f"{v:.7f}" for v in embeddings[0]) + "]"


# --------------------------------------------------------------------------- #
# Tool implementations. Each wraps a single ops.* SQL function and returns a
# JSON-serializable list of rows.
# --------------------------------------------------------------------------- #
def _filters(args: dict[str, Any]) -> dict[str, Any]:
    """Common metadata/time filters shared by every tool."""
    return {
        "source_systems": args.get("source_systems"),
        "source_types": args.get("source_types"),
        "statuses": args.get("statuses"),
        "priorities": args.get("priorities"),
        "project_key": args.get("project_key"),
        "account_name": args.get("account_name"),
        "component": args.get("component"),
        "start_date": args.get("start_date"),
        "end_date": args.get("end_date"),
    }


def _limit(args: dict[str, Any], default: int = 10, cap: int = 50) -> int:
    try:
        return max(1, min(cap, int(args.get("limit") or default)))
    except (TypeError, ValueError):
        return default


def _jsonable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return json.loads(json.dumps(rows, default=str))


def tool_full_text_search(args: dict[str, Any]) -> list[dict[str, Any]]:
    return _jsonable(_run(
        """
        SELECT * FROM ops.full_text_search(
          p_query => %(query)s,
          p_source_systems => %(source_systems)s,
          p_source_types => %(source_types)s,
          p_statuses => %(statuses)s,
          p_priorities => %(priorities)s,
          p_project_key => %(project_key)s,
          p_account_name => %(account_name)s,
          p_component => %(component)s,
          p_start_date => %(start_date)s::timestamptz,
          p_end_date => %(end_date)s::timestamptz,
          p_limit => %(limit)s
        )
        """,
        {"query": args.get("query", ""), **_filters(args), "limit": _limit(args)},
    ))


def tool_vector_search(args: dict[str, Any]) -> list[dict[str, Any]]:
    return _jsonable(_run(
        """
        SELECT * FROM ops.vector_search(
          p_query_embedding => %(embedding)s::vector,
          p_source_systems => %(source_systems)s,
          p_source_types => %(source_types)s,
          p_statuses => %(statuses)s,
          p_priorities => %(priorities)s,
          p_project_key => %(project_key)s,
          p_account_name => %(account_name)s,
          p_component => %(component)s,
          p_start_date => %(start_date)s::timestamptz,
          p_end_date => %(end_date)s::timestamptz,
          p_limit => %(limit)s
        )
        """,
        {"embedding": _embed_query(args.get("query", "")), **_filters(args), "limit": _limit(args)},
    ))


def tool_fuzzy_match(args: dict[str, Any]) -> list[dict[str, Any]]:
    params = {"query": args.get("query", ""), **_filters(args), "limit": _limit(args)}
    params["threshold"] = args.get("threshold", 0.08)
    return _jsonable(_run(
        """
        SELECT * FROM ops.fuzzy_match(
          p_query => %(query)s,
          p_threshold => %(threshold)s,
          p_source_systems => %(source_systems)s,
          p_source_types => %(source_types)s,
          p_statuses => %(statuses)s,
          p_priorities => %(priorities)s,
          p_project_key => %(project_key)s,
          p_account_name => %(account_name)s,
          p_component => %(component)s,
          p_start_date => %(start_date)s::timestamptz,
          p_end_date => %(end_date)s::timestamptz,
          p_limit => %(limit)s
        )
        """,
        params,
    ))


def tool_hybrid_search(args: dict[str, Any]) -> list[dict[str, Any]]:
    return _jsonable(_run(
        """
        SELECT * FROM ops.hybrid_search(
          p_query => %(query)s,
          p_query_embedding => %(embedding)s::vector,
          p_source_systems => %(source_systems)s,
          p_source_types => %(source_types)s,
          p_statuses => %(statuses)s,
          p_priorities => %(priorities)s,
          p_project_key => %(project_key)s,
          p_account_name => %(account_name)s,
          p_component => %(component)s,
          p_start_date => %(start_date)s::timestamptz,
          p_end_date => %(end_date)s::timestamptz,
          p_limit => %(limit)s
        )
        """,
        {"query": args.get("query", ""), "embedding": _embed_query(args.get("query", "")),
         **_filters(args), "limit": _limit(args)},
    ))


TOOLS = {
    "full_text_search": tool_full_text_search,
    "vector_search": tool_vector_search,
    "fuzzy_match": tool_fuzzy_match,
    "hybrid_search": tool_hybrid_search,
}


# --------------------------------------------------------------------------- #
# Dual-shape invocation resolver.
# --------------------------------------------------------------------------- #
def resolve_invocation(event: dict[str, Any], context: Any) -> tuple[str, dict[str, Any]]:
    """Return (tool_name, arguments) for whichever caller invoked this Lambda.

    Three shapes are supported:
      1. AgentCore Gateway MCP target -- the tool name arrives on
         context.client_context.custom['bedrockAgentCoreToolName']
         (prefixed with the target name and split on GATEWAY_TOOL_DELIMITER),
         and the event body IS the tool's argument object.
      2. Classic Bedrock Agent action group -- event carries "actionGroup",
         with inputs in requestBody.content or a flat "parameters" list.
      3. Direct invocation / local test -- {"tool": "...", "arguments": {...}}.
    """
    # 1. AgentCore Gateway
    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    gateway_tool = custom.get("bedrockAgentCoreToolName")
    if gateway_tool:
        tool = gateway_tool.split(GATEWAY_TOOL_DELIMITER)[-1]
        args = event if isinstance(event, dict) else {}
        return tool, args

    # 2. Bedrock Agent action group
    if isinstance(event, dict) and "actionGroup" in event:
        api_path = (event.get("apiPath") or event.get("function") or "").strip("/")
        tool = api_path.split("/")[-1] or event.get("function", "")
        props = (
            event.get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
            .get("properties", [])
        )
        args = {p.get("name"): p.get("value") for p in props}
        for p in event.get("parameters", []) or []:
            args.setdefault(p.get("name"), p.get("value"))
        return tool, args

    # 3. Direct invocation
    if isinstance(event, dict):
        return event.get("tool", ""), event.get("arguments", {}) or {}
    return "", {}


def _agentcore_result(payload: Any) -> dict[str, Any]:
    """MCP tool result envelope the AgentCore Gateway expects."""
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}


def _bedrock_agent_result(event: dict[str, Any], payload: Any) -> dict[str, Any]:
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup"),
            "apiPath": event.get("apiPath"),
            "httpMethod": event.get("httpMethod"),
            "httpStatusCode": 200,
            "responseBody": {"application/json": {"body": json.dumps(payload, default=str)}},
        },
    }


def lambda_handler(event, context):
    tool, args = resolve_invocation(event or {}, context)
    is_bedrock_agent = isinstance(event, dict) and "actionGroup" in event

    impl = TOOLS.get(tool)
    if impl is None:
        error = {"error": f"Unknown tool '{tool}'. Expected one of: {sorted(TOOLS)}"}
        return _bedrock_agent_result(event, error) if is_bedrock_agent else _agentcore_result(error)

    try:
        payload = {"tool": tool, "results": impl(args)}
    except Exception as exc:  # surface a structured error rather than a 500
        payload = {"tool": tool, "error": str(exc)}

    return _bedrock_agent_result(event, payload) if is_bedrock_agent else _agentcore_result(payload)
