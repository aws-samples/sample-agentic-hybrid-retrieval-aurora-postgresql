"""IAM-authenticated transport from the workshop API to its deployed agent."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from threading import Lock
from typing import Literal
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import StreamingResponse

from service.agent_setup import AGENT_STARTER_MESSAGE, AgentSetupError
from service.config import get_settings
from service.models import AgentRequest, AgentResponse


class RuntimeInvocation(BaseModel):
    """Private service envelope; never accept it on the browser API."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["answer", "stream", "status"]
    request: AgentRequest | None = None
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    shopper_token: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


def runtime_arn() -> str | None:
    """Return the configured destination, refusing malformed deployment values."""
    value = os.getenv("MOSAIC_AGENTCORE_RUNTIME_ARN", "").strip()
    if not value:
        return None
    if not re.fullmatch(
        r"arn:aws(?:-[a-z-]+)?:bedrock-agentcore:[a-z0-9-]+:\d{12}:runtime/[A-Za-z0-9_-]+",
        value,
    ):
        raise RuntimeError(
            "Runtime destination rule: invalid MOSAIC_AGENTCORE_RUNTIME_ARN; "
            "fix: use the runtime ARN from this workshop's stack."
        )
    return value


@lru_cache(maxsize=1)
def runtime_client():
    return boto3.client(
        "bedrock-agentcore",
        region_name=get_settings().aws_region,
        config=Config(
            connect_timeout=10,
            read_timeout=get_settings().agent_turn_deadline_seconds + 30,
            # Retrying an agent invocation can create another billed turn.
            retries={"total_max_attempts": 1, "mode": "standard"},
        ),
    )


def invoke(
    operation: Literal["answer", "stream", "status"],
    request: AgentRequest | None = None,
    http_request: Request | None = None,
):
    """Open a fresh execution session and bind it to the participant's code."""
    from scripts.lab_state import lab_is_solved
    from service.lab_validation_receipt import source_digest
    from service.session_memory import COOKIE

    destination = runtime_arn()
    if destination is None:
        raise RuntimeError("Runtime is not configured; fix: load the workshop .env.")
    if operation != "status" and not lab_is_solved(3):
        raise AgentSetupError(AGENT_STARTER_MESSAGE)
    token = http_request.cookies.get(COOKIE) if http_request else None
    if token and not re.fullmatch(r"[a-f0-9]{64}", token):
        token = None
    envelope = RuntimeInvocation(
        operation=operation,
        request=request,
        source_sha256=source_digest(),
        shopper_token=token,
    )
    # Conversation identity lives in Aurora and Memory. Reusing a Runtime
    # execution session after an update can silently execute the old code.
    try:
        response = runtime_client().invoke_agent_runtime(
            agentRuntimeArn=destination,
            qualifier="DEFAULT",
            runtimeSessionId=str(uuid4()),
            contentType="application/json",
            accept="text/event-stream" if operation == "stream" else "application/json",
            payload=envelope.model_dump_json().encode(),
        )
    except (BotoCoreError, ClientError) as error:
        if (
            isinstance(error, ClientError)
            and error.response.get("Error", {}).get("Code") == "RuntimeClientError"
            and "(409)" in error.response["Error"].get("Message", "")
        ):
            raise AgentSetupError(
                "The deployed agent differs from your workspace. In Code Editor, "
                "run make deploy-agent. Next: retry Alex's question after deployment succeeds."
            ) from error
        raise AgentSetupError(
            "Mosaic could not run the deployed agent. In Code Editor, run make "
            "verify-agent. If you changed code, run make deploy-agent first. "
            "Next: retry your question; if deployment fails, share the terminal message with your facilitator."
        ) from error
    return response["response"]


def deployed_status() -> dict:
    with invoke("status") as body:
        return json.loads(body.read())


def answer(request: AgentRequest, http_request: Request | None) -> AgentResponse:
    with invoke("answer", request, http_request) as body:
        return AgentResponse.model_validate_json(body.read())


def stream(request: AgentRequest, http_request: Request | None) -> StreamingResponse:
    """Keep admission and the upstream stream owned until delivery finishes."""
    from service.access_control import (
        acquire_model_admission_slot,
        release_model_admission_slot,
    )

    slot = acquire_model_admission_slot()
    try:
        body = invoke("stream", request, http_request)
    except BaseException:
        release_model_admission_slot(slot)
        raise

    lock = Lock()
    closed = False

    def close():
        nonlocal closed
        with lock:
            if closed:
                return
            closed = True
        try:
            body.close()
        finally:
            release_model_admission_slot(slot)

    class RuntimeStream(StreamingResponse):
        async def __call__(self, scope, receive, send):
            # A disconnect can occur before the iterator starts. Owning cleanup
            # at the response boundary also covers cancellation and send errors.
            try:
                await super().__call__(scope, receive, send)
            finally:
                close()

    return RuntimeStream(
        body.iter_chunks(chunk_size=1024),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


def require_current_source(expected: str) -> str:
    """Refuse to grade a deployed reference when a participant has edited it."""
    from service.lab_validation_receipt import source_digest

    actual = source_digest()
    if expected != actual:
        raise HTTPException(
            409,
            "Runtime code rule: deployed code differs from your workspace; "
            "fix: run `make deploy-agent`, then repeat the check.",
        )
    return actual
