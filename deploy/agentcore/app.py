"""Run Mosaic's Strands agent behind AgentCore Runtime's IAM ingress.

The invocation envelope preserves the browser's opaque session capability and
requires the deployed source to match Code Editor. Search and evidence tools
call AgentCore Gateway; citation and ownership checks use the same production
functions as the workshop API.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from service.agentcore_transport import (
    RuntimeInvocation,
    require_current_source,
    runtime_arn,
)
from service.config import get_settings
from service.db import close_pool, get_pool
from service.main import agent_answer, get_readiness, stream_agent_answer
from service.main import app as service_app
from service.models import AgentRequest
from service.session_memory import COOKIE


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Own Aurora connections behind Runtime's IAM-authenticated ingress.

    The browser API checks its nginx origin secret. Runtime authenticates its
    caller with IAM instead; it must not receive that browser ingress secret.
    Mounted browser routes retain their origin dependency and remain closed.
    """
    try:
        get_pool()
    except RuntimeError:
        # Keep readiness available to explain missing database configuration;
        # a restart cannot supply it, and requests retry pool initialization.
        pass
    try:
        yield
    finally:
        close_pool()


app = FastAPI(
    title="Mosaic retrieval service on AgentCore Runtime",
    description=(
        "AgentCore Runtime HTTP protocol adapter over the workshop retrieval "
        "service. Adds GET /ping and POST /invocations; every other route is "
        "the service's own."
    ),
    version=service_app.version,
    lifespan=_lifespan,
    # /invocations runs on this outer app, outside the mounted API's handlers.
    exception_handlers=service_app.exception_handlers,
)


@app.get("/ping")
def ping() -> dict[str, str]:
    """Report readiness to serve, in the two states the contract defines.

    The contract's status values are `Healthy` and `HealthyBusy`, and this
    service has no queue that would make it the second one: it serves each
    invocation on the request that carried it, so a busy process is a slow one,
    not a differently healthy one.

    This deliberately touches neither Aurora nor Bedrock. A health check that
    failed on a dependency would have AgentCore replace a container that is
    working over an outage it cannot fix by replacing anything, and the failure
    would arrive as a recycled container rather than as an error a participant
    can read. `GET /api/readiness` is where the database and model answer lives,
    and it is reachable through the mount below.
    """
    get_settings()
    return {"status": "Healthy"}


@app.post("/invocations", response_model=None)
async def invocations(request: RuntimeInvocation | AgentRequest, http_request: Request):
    """Run the production API with the browser capability passed by its IAM caller."""
    if runtime_arn():
        raise HTTPException(
            503, "Runtime cannot forward to itself; unset MOSAIC_AGENTCORE_RUNTIME_ARN."
        )
    if isinstance(request, AgentRequest):
        return await asyncio.to_thread(agent_answer, request)
    digest = await asyncio.to_thread(require_current_source, request.source_sha256)
    if request.operation == "status":
        return {
            "source_sha256": digest,
            "readiness": await asyncio.to_thread(get_readiness),
        }
    if request.request is None:
        raise HTTPException(422, "Runtime invocation requires an agent request.")
    # The caller has InvokeAgentRuntime permission. Forward the opaque browser
    # capability, not an actor ID or client-supplied memory context, so the same
    # Aurora ownership checks execute on the deployed service.
    headers = (
        [(b"cookie", f"{COOKIE}={request.shopper_token}".encode())]
        if request.shopper_token
        else []
    )
    forwarded = Request(
        {**http_request.scope, "headers": headers}, receive=http_request.receive
    )
    if request.operation == "stream":
        return await stream_agent_answer(request.request, forwarded)
    return await asyncio.to_thread(agent_answer, request.request, forwarded)


# Mounted last and at the root, so the two routes above are matched first and
# everything else is served by the workshop application itself, middleware,
# exception handlers and all. Registering selected routes onto this application
# instead would fork the surface, and the fork would be found by a participant.
app.mount("/", service_app)
