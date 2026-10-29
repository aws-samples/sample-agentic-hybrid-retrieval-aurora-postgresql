"""IAM-authenticated transport from the workshop API to its deployed agent."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterator
from threading import Lock
from typing import Literal
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import StreamingResponse

from service.agent_setup import AgentSetupError, agent_setup_message
from service.config import get_settings
from service.models import AgentRequest, AgentResponse
from service.participant_commands import DEPLOY_AGENT, VERIFY_AGENT, reset

logger = logging.getLogger(__name__)


class RuntimeInvocation(BaseModel):
    """Private service envelope; never accept it on the browser API."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["answer", "stream", "status"]
    request: AgentRequest | None = None
    application_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
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


#: AgentCore reports the status the agent returned inside its error message, as
#: "(503)"; the agent's own explanation is not passed on.
_AGENT_STATUS = re.compile(r"\((\d{3})\)")


def runtime_client():
    """Open a client for one agent turn.

    A shared client would reuse its pooled connection after a participant's
    pause, and the NAT gateway drops idle connections after 350 seconds. With
    retries off, that reset became a 503. A new client costs milliseconds
    against a turn that takes seconds.
    """
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
    """Open a fresh execution session and bind it to the participant's code.

    A question waits for the participant's own deploy: from Lab 3's start it needs
    an assembled `create_agent` and a deploy since the start that carries today's
    code, not the reference Retrieval agent the account was provisioned with.
    """
    from scripts.lab_state import lab3_problem
    from service.agent_deploys import ask_problem
    from service.lab_validation_receipt import application_digest
    from service.session_memory import COOKIE

    destination = runtime_arn()
    if destination is None:
        raise RuntimeError("Runtime is not configured; fix: load the workshop .env.")
    try:
        digest = application_digest()
        problem = lab3_problem() if operation != "status" else None
    except OSError as error:
        # A deleted or unreadable lab file would otherwise surface as a bare 500.
        raise AgentSetupError(
            "Your Retrieval agent files cannot be read "
            f"({type(error).__name__}). "
            f"Next: run {reset(3)} to put back the starting code, then deploy with "
            f"{DEPLOY_AGENT} and ask your question again."
        ) from error
    if operation != "status":
        if problem is not None:
            raise AgentSetupError(agent_setup_message(problem))
        try:
            undeployed = ask_problem(digest)
        except (RuntimeError, ValueError) as error:
            # An unreadable start or deploy record names its own fix.
            raise AgentSetupError(str(error)) from error
        if undeployed is not None:
            raise AgentSetupError(undeployed)
    token = http_request.cookies.get(COOKIE) if http_request else None
    if token and not re.fullmatch(r"[a-f0-9]{64}", token):
        token = None
    envelope = RuntimeInvocation(
        operation=operation,
        request=request,
        application_sha256=digest,
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
        code = (
            error.response.get("Error", {}).get("Code")
            if isinstance(error, ClientError)
            else None
        )
        logger.warning(
            "Deployed agent invocation failed: %s %s", type(error).__name__, code or ""
        )
        if (
            isinstance(error, ClientError)
            and error.response.get("Error", {}).get("Code") == "RuntimeClientError"
            and "(409)" in error.response["Error"].get("Message", "")
        ):
            # AgentCore exposes the HTTP conflict without its application body.
            # Both stale code and rejected conversation context can return 409.
            raise AgentSetupError(
                "The deployed Retrieval agent rejected this request. For a follow-up, "
                "clear chat and retry with a new question. Otherwise, check the "
                f"deployment with {VERIFY_AGENT} in Code Editor; if it reports "
                f"changed code, deploy with {DEPLOY_AGENT}."
            ) from error
        status = (
            _AGENT_STATUS.search(str(error)) if code == "RuntimeClientError" else None
        )
        if status:
            raise AgentSetupError(
                f"Your deployed Retrieval agent stopped this request with HTTP {status[1]} "
                f"({code}). Runtime does not pass on the reason; the Retrieval agent runtime's "
                "log in CloudWatch names it, such as a Bedrock model call that was "
                "throttled, the answer checks, or the turn's time limit. Next: retry "
                f"your question; if it fails again, check the deployment with "
                f"{VERIFY_AGENT} and share this message with your facilitator."
            ) from error
        raise AgentSetupError(
            f"Mosaic could not run the deployed Retrieval agent ({code or type(error).__name__}). "
            f"In Code Editor, check the deployment with {VERIFY_AGENT}. If you "
            f"changed code, deploy with {DEPLOY_AGENT} first. "
            "Next: retry your question; if deployment fails, share the terminal message with your facilitator."
        ) from error
    return response["response"]


def deployed_status() -> dict:
    with invoke("status") as body:
        return json.loads(body.read())


def answer(request: AgentRequest, http_request: Request | None) -> AgentResponse:
    with invoke("answer", request, http_request) as body:
        return AgentResponse.model_validate_json(body.read())


_STREAM_INTERRUPTED = "Retrieval agent stream was interrupted; ask again"


def _as_received(body, notice: str | None = None) -> Iterator[bytes]:
    if notice:
        payload = json.dumps(
            {
                "code": "reference_agent",
                "title": "Reference Retrieval agent",
                "detail": notice,
            }
        )
        yield f"event: notice\ndata: {payload}\n\n".encode()
    # A sized read waits for that many bytes, so a tool call sat in the relay until
    # later events filled the chunk; read1 passes on whatever the Runtime has sent.
    with body as raw:
        try:
            while chunk := raw.read1(1024):
                yield chunk
        except Exception as error:  # noqa: BLE001 - any transport fault cuts the stream
            # Headers are sent, so a status can no longer change; an error frame is
            # the only way the browser and ask_agent.py learn the stream was cut.
            logger.warning(
                "Runtime stream interrupted: error_type=%s", type(error).__name__
            )
            payload = json.dumps({"status": 503, "detail": _STREAM_INTERRUPTED})
            yield f"event: error\ndata: {payload}\n\n".encode()


def stream(request: AgentRequest, http_request: Request | None) -> StreamingResponse:
    """Keep admission and the upstream stream owned until delivery finishes.

    A question the provisioned reference agent answers starts with a `notice` event
    saying so, so the participant does not take it for the agent they build in Lab 3.
    """
    from service.access_control import (
        acquire_model_admission_slot,
        release_model_admission_slot,
    )
    from service.agent_deploys import reference_agent_notice

    try:
        notice = reference_agent_notice()
    except (RuntimeError, ValueError) as error:
        # An unreadable start record names its own fix, as `invoke` reports it.
        raise AgentSetupError(str(error)) from error
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
        _as_received(body, notice),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


def require_current_source(expected: str) -> str:
    """Refuse to run deployed code that differs from the participant's workspace.

    Compares the application identity only. The participant's SQL runs in
    Aurora, so a Lab 1 or Lab 2 edit needs `scripts/apply_search_functions.py`,
    not a redeploy; the applied-SQL record is checked where Lab 3 is proven.
    """
    from service.lab_validation_receipt import application_digest

    actual = application_digest()
    if expected != actual:
        raise HTTPException(
            409,
            "Runtime code rule: deployed code differs from your workspace; "
            f"fix: run `{DEPLOY_AGENT}`, then repeat the check.",
        )
    return actual
