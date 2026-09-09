"""Inspect AgentCore events and strategies alongside Aurora's retrieval records.

The browser cookie scopes actors; memory text is context, never product evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from service.config import get_settings
from service.db import connect
from service.models import AgentConversationContext, AgentRequest

COOKIE = "mosaic_shopper"
router = APIRouter(prefix="/api/session-memory", tags=["session-memory"])


class ConversationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=4, max_length=2000)
    session_id: UUID | None = None
    request_id: UUID


class MemoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=4, max_length=2000)


def shopper_id(request: Request | None, response: Response | None = None) -> str | None:
    """Resolve a random browser capability without accepting a caller's actor ID."""
    if request is None:
        return None
    token = request.cookies.get(COOKIE, "")
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        if response is None:
            return None
        token = secrets.token_hex(32)
        response.set_cookie(
            COOKIE,
            token,
            max_age=60 * 60 * 24 * 30,
            httponly=True,
            secure=request.scope.get("scheme") == "https",
            samesite="strict",
        )
    return hashlib.sha256(token.encode()).hexdigest()


def _client(service: str):
    return boto3.client(
        service,
        region_name=get_settings().aws_region,
        config=Config(
            connect_timeout=3,
            read_timeout=10,
            retries={"total_max_attempts": 2, "mode": "standard"},
        ),
    )


@lru_cache(maxsize=1)
def memory_client():
    return _client("bedrock-agentcore")


@lru_cache(maxsize=1)
def control_client():
    return _client("bedrock-agentcore-control")


def _memory_id() -> str:
    value = get_settings().agentcore_memory_id
    if not value:
        raise HTTPException(
            503,
            "AgentCore Memory is not connected. Aurora sessions are still available.",
        )
    return value


def _memory_error() -> HTTPException:
    return HTTPException(
        503,
        "AgentCore Memory could not be reached. Retry, or turn off memory for this request.",
    )


def _actor(request: Request) -> str:
    actor = shopper_id(request)
    if not actor:
        raise HTTPException(409, "Open Session & Memory first, then retry.")
    return actor


def _profile(connection, actor: str, *, lock: bool = False):
    connection.execute(
        "INSERT INTO mosaic.shopper_profile (shopper_id) VALUES (%s) ON CONFLICT DO NOTHING",
        (actor,),
    )
    return connection.execute(
        "SELECT * FROM mosaic.shopper_profile WHERE shopper_id = %s"
        + (" FOR UPDATE" if lock else ""),
        (actor,),
    ).fetchone()


def _own_session(connection, actor: str, session_id: UUID | str):
    row = connection.execute(
        "SELECT * FROM mosaic.agent_session WHERE agent_session_id = %s AND user_context->>'shopper_id' = %s",
        (session_id, actor),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "This session is not available in this browser.")
    return row


def _configuration() -> dict:
    memory = control_client().get_memory(memoryId=_memory_id())["memory"]
    return {
        "memory_id": memory["id"],
        "status": memory["status"],
        "event_expiry_days": memory["eventExpiryDuration"],
        "strategies": [
            {
                "id": item["strategyId"],
                "name": item["name"],
                "type": item["type"],
                "status": item["status"],
                "namespaces": item.get("namespaceTemplates")
                or item.get("namespaces", []),
                "reflection_namespaces": (
                    item.get("configuration", {})
                    .get("reflection", {})
                    .get("episodicReflectionConfiguration", {})
                    .get("namespaceTemplates")
                    or item.get("configuration", {})
                    .get("reflection", {})
                    .get("episodicReflectionConfiguration", {})
                    .get("namespaces", [])
                ),
            }
            for item in memory.get("strategies", [])
        ],
    }


def scoped_namespaces(strategy: dict, actor: str, session_id: str | None) -> list[str]:
    """Reject shared namespaces even if an operator configures one in AWS."""
    paths = []
    for template in [
        *strategy["namespaces"],
        *strategy.get("reflection_namespaces", []),
    ]:
        if not template.startswith("/mosaic/{actorId}/"):
            continue
        if "{sessionId}" in template and not session_id:
            continue
        path = template.replace("{actorId}", actor).replace(
            "{memoryStrategyId}", strategy["id"]
        )
        path = path.replace("{sessionId}", session_id or "")
        if "{" not in path and path not in paths:
            paths.append(path)
    return paths


def _record(item: dict) -> dict:
    return {
        "id": item["memoryRecordId"],
        "strategy_id": item.get("memoryStrategyId"),
        "text": item.get("content", {}).get("text", ""),
        "namespaces": item.get("namespaces", []),
        "created_at": item.get("createdAt"),
        "score": item.get("score"),
    }


def _events(actor: str, session_id: str) -> dict:
    pages = (
        memory_client()
        .get_paginator("list_events")
        .paginate(
            memoryId=_memory_id(),
            actorId=actor,
            sessionId=session_id,
            includePayloads=True,
            PaginationConfig={"MaxItems": 30, "PageSize": 30},
        )
    )
    result = pages.build_full_result()
    events = [
        {
            "id": event["eventId"],
            "created_at": event["eventTimestamp"],
            "messages": [
                {
                    "role": payload["conversational"]["role"],
                    "text": payload["conversational"]["content"].get("text", ""),
                }
                for payload in event.get("payload", [])
                if "conversational" in payload
            ],
        }
        for event in result.get("events", [])
    ]
    return {
        "events": sorted(events, key=lambda e: e["created_at"]),
        "has_more": bool(result.get("NextToken")),
    }


@router.get("/identity")
def initialize_browser(request: Request, response: Response):
    shopper_id(request, response)
    response.headers["Cache-Control"] = "no-store"
    return {"ready": True}


@router.get("")
def read_session_memory(request: Request, response: Response):
    actor = shopper_id(request, response)
    with connect() as connection:
        profile = _profile(connection, actor)
        sessions = connection.execute(
            """SELECT agent_session_id, started_at, ended_at, metadata->>'label' AS label
               FROM mosaic.agent_session WHERE user_context->>'shopper_id' = %s
               ORDER BY started_at DESC LIMIT 12""",
            (actor,),
        ).fetchall()
        for session in sessions:
            turns = connection.execute(
                """SELECT t.agent_turn_id, t.user_message, t.assistant_message, t.created_at, t.extracted_intent,
                          (SELECT output_payload->'citations' FROM mosaic.agent_tool_event
                           WHERE agent_turn_id = t.agent_turn_id AND tool_name = 'synthesize_cited_answer'
                             AND outcome = 'success' ORDER BY occurred_at DESC LIMIT 1) AS citations
                   FROM mosaic.agent_turn t WHERE t.agent_session_id = %s ORDER BY t.turn_number DESC LIMIT 20""",
                (session["agent_session_id"],),
            ).fetchall()[::-1]
            session["turns"] = [
                {
                    "run_id": t["agent_turn_id"],
                    "question": t["user_message"],
                    "answer": t["assistant_message"],
                    "created_at": t["created_at"],
                    "products": t["extracted_intent"].get("selected_products", []),
                    "search_ids": t["extracted_intent"].get("search_event_ids", []),
                    "memory": t["extracted_intent"].get("memory", {}),
                    "citations": t["citations"] or [],
                }
                for t in turns
            ]
    status = "connected" if get_settings().agentcore_memory_id else "not_configured"
    config = None
    try:
        if status == "connected":
            config = _configuration()
    except (ClientError, BotoCoreError):
        status = "unavailable"
    response.headers["Cache-Control"] = "no-store"
    return {
        "memory_status": status,
        "configuration": config,
        "actor_id": actor,
        "sessions": sessions,
        "active_session_id": profile["active_session_id"],
    }


@router.get("/events")
def read_events(session_id: UUID, request: Request, response: Response):
    actor = _actor(request)
    with connect() as connection:
        _own_session(connection, actor, session_id)
    response.headers["Cache-Control"] = "no-store"
    try:
        return _events(actor, str(session_id))
    except (ClientError, BotoCoreError) as error:
        raise _memory_error() from error


@router.post("/events")
def add_event(event: ConversationEvent, request: Request):
    """Write the visitor's actual message; never fabricate an assistant reply."""
    actor = _actor(request)
    try:
        with connect() as connection:
            _profile(connection, actor, lock=True)
            if event.session_id:
                _own_session(connection, actor, event.session_id)
                session_id = event.session_id
            else:
                session_id = connection.execute(
                    "INSERT INTO mosaic.agent_session (user_context, metadata) VALUES (%s::jsonb, %s::jsonb) RETURNING agent_session_id",
                    (
                        json.dumps({"shopper_id": actor}),
                        json.dumps({"label": event.text[:100]}),
                    ),
                ).fetchone()["agent_session_id"]
            saved = memory_client().create_event(
                memoryId=_memory_id(),
                actorId=actor,
                sessionId=str(session_id),
                eventTimestamp=datetime.now(UTC),
                clientToken=str(event.request_id),
                payload=[
                    {
                        "conversational": {
                            "role": "USER",
                            "content": {"text": event.text},
                        }
                    }
                ],
            )["event"]
            connection.execute(
                "UPDATE mosaic.shopper_profile SET active_session_id = %s WHERE shopper_id = %s",
                (session_id, actor),
            )
        return {"session_id": session_id, "event_id": saved["eventId"]}
    except (ClientError, BotoCoreError) as error:
        raise _memory_error() from error


@router.get("/records")
def read_records(
    strategy_id: str,
    request: Request,
    response: Response,
    session_id: UUID | None = None,
):
    actor = _actor(request)
    if session_id:
        with connect() as connection:
            _own_session(connection, actor, session_id)
    response.headers["Cache-Control"] = "no-store"
    try:
        strategy = next(
            (s for s in _configuration()["strategies"] if s["id"] == strategy_id), None
        )
        if not strategy:
            raise HTTPException(404, "This memory strategy is not configured.")
        paths = scoped_namespaces(
            strategy, actor, str(session_id) if session_id else None
        )
        records, more = {}, False
        for path in paths:
            page = (
                memory_client()
                .get_paginator("list_memory_records")
                .paginate(
                    memoryId=_memory_id(),
                    namespace=path,
                    memoryStrategyId=strategy_id,
                    PaginationConfig={"MaxItems": 20, "PageSize": 20},
                )
                .build_full_result()
            )
            more = more or bool(page.get("NextToken"))
            for item in page.get("memoryRecordSummaries", []):
                if item.get("memoryStrategyId") == strategy_id and path in item.get(
                    "namespaces", []
                ):
                    records[item["memoryRecordId"]] = _record(item)
        return {
            "records": list(records.values()),
            "has_more": more,
            "namespaces": paths,
        }
    except (ClientError, BotoCoreError) as error:
        raise _memory_error() from error


def recall_records(actor: str, query: str) -> list[dict]:
    """Retrieve actor-scoped facts and preferences; leave product evidence in Aurora."""
    records = []
    for strategy in _configuration()["strategies"]:
        if (
            strategy["type"] not in {"SEMANTIC", "USER_PREFERENCE"}
            or strategy["status"] != "ACTIVE"
        ):
            continue
        for path in scoped_namespaces(strategy, actor, None):
            result = memory_client().retrieve_memory_records(
                memoryId=_memory_id(),
                namespace=path,
                searchCriteria={
                    "searchQuery": query,
                    "memoryStrategyId": strategy["id"],
                    "topK": 3,
                },
            )
            for item in result.get("memoryRecordSummaries", []):
                if item.get("memoryStrategyId") == strategy["id"] and path in item.get(
                    "namespaces", []
                ):
                    records.append({**_record(item), "strategy_type": strategy["type"]})
    return records


@router.post("/recall")
def recall_memory(query: MemoryQuery, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return {"records": recall_records(_actor(request), query.query)}
    except (ClientError, BotoCoreError) as error:
        raise _memory_error() from error


@router.post("/new-session", status_code=204)
def new_session(request: Request):
    actor = shopper_id(request)
    if actor:
        with connect() as connection:
            profile = _profile(connection, actor, lock=True)
            if profile["active_session_id"]:
                connection.execute(
                    "UPDATE mosaic.agent_session SET ended_at = now() WHERE agent_session_id = %s",
                    (profile["active_session_id"],),
                )
            connection.execute(
                "UPDATE mosaic.shopper_profile SET active_session_id = NULL WHERE shopper_id = %s",
                (actor,),
            )
    return Response(status_code=204)


def prepare_request(
    request: AgentRequest, http_request: Request | None
) -> AgentRequest:
    """Restore owned conversation context and retrieve memories before the model runs."""
    actor = shopper_id(http_request)
    if not actor:
        if request.session_id:
            raise HTTPException(404, "This session is not available in this browser.")
        return request
    with connect() as connection:
        _profile(connection, actor)
        context = request.context
        if context:
            owner = connection.execute(
                """SELECT s.user_context->>'shopper_id' AS shopper_id FROM mosaic.agent_turn t
                   JOIN mosaic.agent_session s USING (agent_session_id) WHERE t.agent_turn_id = %s""",
                (context.previous_agent_run_id,),
            ).fetchone()
            if owner and owner["shopper_id"] and owner["shopper_id"] != actor:
                raise HTTPException(
                    404, "This session is not available in this browser."
                )
        if request.session_id:
            _own_session(connection, actor, request.session_id)
            row = connection.execute(
                """SELECT agent_turn_id, user_message, extracted_intent FROM mosaic.agent_turn
                   WHERE agent_session_id = %s AND assistant_message IS NOT NULL ORDER BY turn_number DESC LIMIT 1""",
                (request.session_id,),
            ).fetchone()
            products = (
                row["extracted_intent"].get("selected_products", [])[:4] if row else []
            )
            context = (
                AgentConversationContext(
                    previous_agent_run_id=row["agent_turn_id"],
                    previous_question=row["user_message"],
                    recommendations=[
                        {k: p[k] for k in ("product_id", "title", "model")}
                        for p in products
                    ],
                )
                if products
                else None
            )
    snapshot: dict[str, Any] = {
        "enabled": request.use_memory,
        "records": [],
        "events": [],
        "status": "off",
    }
    if request.use_memory and get_settings().agentcore_memory_id:
        try:
            snapshot.update(
                records=recall_records(actor, request.question), status="connected"
            )
            if request.session_id:
                snapshot["events"] = _events(actor, str(request.session_id))["events"][
                    -8:
                ]
        except (ClientError, BotoCoreError) as error:
            raise _memory_error() from error
    elif request.use_memory:
        snapshot["status"] = "not_configured"
    prepared = request.model_copy(update={"context": context})
    prepared._memory_context = {
        "shopper_id": actor,
        "session_id": request.session_id,
        **snapshot,
    }
    return prepared


def attach_run(request: AgentRequest, state: dict[str, Any]) -> None:
    """Attach history without adding a product or citation to the allowed scope."""
    if not request._memory_context:
        return
    actor = request._memory_context["shopper_id"]
    state["memory"] = {
        k: v
        for k, v in request._memory_context.items()
        if k not in {"shopper_id", "session_id", "events"}
    }
    state["memory"]["event_ids_read"] = [
        e["id"] for e in request._memory_context["events"]
    ]
    state["_memory_actor"] = actor
    with connect() as connection:
        row = connection.execute(
            "SELECT user_context FROM mosaic.agent_session WHERE agent_session_id = %s FOR UPDATE",
            (state["agent_session_id"],),
        ).fetchone()
        owner = row["user_context"].get("shopper_id")
        if owner and owner != actor:
            raise HTTPException(404, "This session is not available in this browser.")
        connection.execute(
            "UPDATE mosaic.agent_session SET user_context = user_context || %s::jsonb, ended_at = NULL WHERE agent_session_id = %s",
            (json.dumps({"shopper_id": actor}), state["agent_session_id"]),
        )
        connection.execute(
            "UPDATE mosaic.shopper_profile SET active_session_id = %s WHERE shopper_id = %s",
            (state["agent_session_id"], actor),
        )


def capture_turn(state: dict[str, Any]) -> None:
    """Record actual messages after a run, without making an AWS outage erase its answer."""
    if (
        not state.get("_memory_actor")
        or state.get("memory", {}).get("status") != "connected"
    ):
        return
    payload = [
        {"conversational": {"role": "USER", "content": {"text": state["question"]}}}
    ]
    record = state.get("answer_of_record")
    if record:
        payload.append(
            {
                "conversational": {
                    "role": "ASSISTANT",
                    "content": {"text": record["answer"]},
                }
            }
        )
    try:
        event = memory_client().create_event(
            memoryId=_memory_id(),
            actorId=state["_memory_actor"],
            sessionId=str(state["agent_session_id"]),
            eventTimestamp=datetime.now(UTC),
            clientToken=str(state["agent_run_id"]),
            payload=payload,
        )["event"]
        state["memory"]["written_event_id"] = event["eventId"]
        state["memory"]["write_status"] = "stored"
    except (ClientError, BotoCoreError):
        state["memory"]["write_status"] = "failed"
