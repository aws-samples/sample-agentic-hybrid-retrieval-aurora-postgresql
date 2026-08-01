from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable
from uuid import UUID, uuid4

from .db import PERSONAS, get_dict_conn
from .models import DEFAULT_ROLE

logger = logging.getLogger(__name__)

CONTRACT_VERSION = "1.0.0"
TRANSPORTS = {"http", "stdio_mcp", "agentcore_gateway"}
_VOLATILE_RESPONSE_KEYS = {
    "agent_run_id",
    "completed_at",
    "created_at",
    "duration_ms",
    "ended_at",
    "invocation_id",
    "latency_ms",
    "request_id",
    "run_id",
    "started_at",
    "stage_timings",
    "total_latency_ms",
    "transport_trace_id",
}


@dataclass(frozen=True)
class InvocationContext:
    transport: str
    request_id: str
    transport_trace_id: str | None = None

    def __post_init__(self) -> None:
        if self.transport not in TRANSPORTS:
            raise ValueError(f"unsupported transport {self.transport!r}")


def new_request_id() -> str:
    return f"req-{uuid4()}"


def envelope(
    payload: dict[str, Any],
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "request_id": request_id or new_request_id(),
        **payload,
    }


def _canonical(value: Any, *, normalize_response: bool = False) -> Any:
    if isinstance(value, dict):
        return {
            key: _canonical(item, normalize_response=normalize_response)
            for key, item in sorted(value.items())
            if not normalize_response or key not in _VOLATILE_RESPONSE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [
            _canonical(item, normalize_response=normalize_response)
            for item in value
        ]
    if isinstance(value, UUID):
        return str(value)
    return value


def _sha256(value: Any, *, normalize_response: bool = False) -> str:
    serialized = json.dumps(
        _canonical(value, normalize_response=normalize_response),
        default=str,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _run_id(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    value = payload.get("run_id")
    if not value:
        retrievals = payload.get("retrievals") or []
        value = retrievals[0].get("run_id") if retrievals else None
    try:
        return str(UUID(str(value))) if value else None
    except ValueError:
        return None


def _request_role(request_payload: dict[str, Any]) -> str:
    role = request_payload.get("role") or DEFAULT_ROLE
    if role not in PERSONAS:
        raise ValueError(
            f"unknown persona {role!r}; expected one of {', '.join(PERSONAS)}"
        )
    return str(role)


def record_transport_invocation(
    context: InvocationContext,
    tool_name: str,
    request_payload: dict[str, Any],
    *,
    response_payload: dict[str, Any] | None,
    status: str,
    error: str | None = None,
) -> None:
    metadata = {"request_id": context.request_id}
    if error:
        metadata["error"] = error[:2000]
    role = _request_role(request_payload)
    with get_dict_conn(role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO proof.transport_invocations(
                  run_id,
                  role,
                  transport,
                  tool_name,
                  contract_version,
                  request_hash,
                  normalized_response_hash,
                  transport_trace_id,
                  status,
                  metadata
                )
                VALUES (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                )
                """,
                (
                    _run_id(response_payload),
                    role,
                    context.transport,
                    tool_name,
                    CONTRACT_VERSION,
                    _sha256({"tool": tool_name, "request": request_payload}),
                    (
                        _sha256(response_payload, normalize_response=True)
                        if response_payload is not None
                        else None
                    ),
                    context.transport_trace_id,
                    status,
                    json.dumps(metadata, separators=(",", ":")),
                ),
            )


def invoke_contract(
    context: InvocationContext,
    tool_name: str,
    request_payload: dict[str, Any],
    implementation: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    try:
        response = envelope(
            implementation(),
            request_id=context.request_id,
        )
    except Exception as error:
        try:
            record_transport_invocation(
                context,
                tool_name,
                request_payload,
                response_payload=None,
                status="failed",
                error=str(error),
            )
        except Exception as receipt_error:
            logger.error(
                "Could not persist failed %s invocation: %s",
                tool_name,
                receipt_error,
            )
        raise

    record_transport_invocation(
        context,
        tool_name,
        request_payload,
        response_payload=response,
        status="succeeded",
    )
    return response
