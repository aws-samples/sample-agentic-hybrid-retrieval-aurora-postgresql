"""AgentCore Runtime (BYO, Python 3.12) for the hybrid retrieval agent.

This is the runtime entrypoint the AgentCore CLI packages and deploys. It hosts
the same cited-answer agent the FastAPI service exposes at /v1/agent/answer, but
behind the AgentCore Runtime contract: a BedrockAgentCoreApp with an
@app.entrypoint that AgentCore invokes on port 8080.

The payload is normalized by resolve_invocation, which accepts both a direct
invocation ({"question": "..."} or {"prompt": "..."}) and a gateway-wrapped
invocation (the AgentCore Gateway / MCP shape that nests the arguments under an
"input" or "arguments" key). Either way we end up with a question string plus
optional filters, run the hybrid retrieval agent, and return a cited answer.

Local run:   python main.py        (starts the runtime on :8080)
Local test:  INVOKE_LOCAL=1 python main.py '{"question": "Why did Orion slip?"}'
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

# The retrieval agent lives in the repo's backend package. The AgentCore build
# packages backend/ alongside this entrypoint (see agentcore.json codeLocation),
# so these imports resolve at runtime. Kept lazy-friendly: import errors surface
# as a structured error rather than crashing the container at import time.
try:
    from backend.app.agent import ALL_SYSTEMS, answer_question
    from backend.app.models import AgentAnswerRequest
except Exception:  # pragma: no cover - packaging fallback
    ALL_SYSTEMS = ["slack", "jira", "confluence", "salesforce", "github"]
    answer_question = None
    AgentAnswerRequest = None


def resolve_invocation(payload: Any) -> dict[str, Any]:
    """Normalize direct and gateway-wrapped payloads into agent arguments.

    Shapes handled:
      * Direct:          {"question": "...", "source_systems": [...], ...}
      * Prompt alias:    {"prompt": "..."}  or  {"input": "..."} (plain string)
      * Gateway / MCP:   {"input": {"question": "..."}}  or
                         {"arguments": {"question": "..."}}
    """
    if isinstance(payload, str):
        return {"question": payload}
    if not isinstance(payload, dict):
        return {"question": ""}

    # Unwrap a gateway/MCP envelope if the real args are nested.
    for key in ("arguments", "input", "body"):
        inner = payload.get(key)
        if isinstance(inner, dict):
            payload = {**payload, **inner}
            break
        if isinstance(inner, str) and "question" not in payload and "prompt" not in payload:
            return {"question": inner}

    question = payload.get("question") or payload.get("prompt") or ""
    return {
        "question": question,
        "source_systems": payload.get("source_systems"),
        "project_key": payload.get("project_key"),
        "account_name": payload.get("account_name"),
        "component": payload.get("component"),
        "limit": payload.get("limit"),
    }


def handle_invoke(payload: Any) -> dict[str, Any]:
    args = resolve_invocation(payload)
    question = (args.get("question") or "").strip()
    if not question:
        return {"error": "Provide a 'question' (or 'prompt') to answer."}

    if answer_question is None or AgentAnswerRequest is None:
        return {"error": "Retrieval agent is not packaged with this runtime (backend.app import failed)."}

    req = AgentAnswerRequest(
        question=question,
        source_systems=args.get("source_systems"),
        project_key=args.get("project_key"),
        account_name=args.get("account_name"),
        component=args.get("component"),
        limit=int(args["limit"]) if args.get("limit") else 8,
    )
    return answer_question(req)


def _build_app():
    """Construct the BedrockAgentCoreApp lazily so local test mode needs no SDK."""
    from bedrock_agentcore.runtime import BedrockAgentCoreApp

    app = BedrockAgentCoreApp()

    @app.entrypoint
    def invoke(payload: dict, context: Any = None) -> dict:
        return handle_invoke(payload)

    return app


if __name__ == "__main__":
    # Local test path: INVOKE_LOCAL=1 python main.py '{"question": "..."}'
    if os.environ.get("INVOKE_LOCAL"):
        raw = sys.argv[1] if len(sys.argv) > 1 else "{}"
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            event = raw  # treat as a bare question string
        print(json.dumps(handle_invoke(event), default=str, indent=2))
    else:
        _build_app().run()
