"""AgentCore Runtime entry point for the Mosaic retrieval service.

AgentCore Runtime's HTTP protocol checks `GET /ping` and delivers invocations to
`POST /invocations` on port 8080. The workshop service answers `GET /api/health`
and `POST /api/agent/answer`, and it keeps answering exactly those: this module
is an adapter, not a second application. It mounts `service.main.app` whole and
adds the two platform routes around it, so the process AgentCore starts is the
process the labs run, with the same middleware, the same exception handlers, the
same connection-pool lifespan, and the same agent code path.

That is the claim this beat supports and the reason the adapter is this thin.
Retrieval, ranking, citation, and the `mosaic.agent_turn` receipt are decided in
Aurora by `service/agent_tools.py` and `service/retrieval_scope.py`. If moving
the harness changed the answers, the evidence authority was in the harness.

Nothing is added beyond the two contract routes. `tests/test_agentcore_adapter.py`
asserts that count, and asserts that importing this module leaves the workshop
application without a platform route on it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from service.config import get_settings
from service.main import agent_answer
from service.main import app as service_app
from service.models import AgentRequest, AgentResponse


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run the mounted service's own startup and shutdown.

    A Starlette mount routes requests to the sub-application but does not forward
    lifespan events to it. Without this delegation the pool would never be opened
    at startup, so the first invocation after a cold start would pay for pool
    construction, and it would never be closed on SIGTERM, so a scaled-in
    container would leave Aurora sessions to time out. uvicorn turns SIGTERM into
    the shutdown half of this context, which is how the container meets the
    graceful-shutdown requirement.
    """
    async with service_app.router.lifespan_context(service_app):
        yield


app = FastAPI(
    title="Mosaic retrieval service on AgentCore Runtime",
    description=(
        "AgentCore Runtime HTTP protocol adapter over the workshop retrieval "
        "service. Adds GET /ping and POST /invocations; every other route is "
        "the service's own."
    ),
    version=service_app.version,
    lifespan=_lifespan,
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


@app.post("/invocations", response_model=AgentResponse)
def invocations(request: AgentRequest) -> AgentResponse:
    """Run one agent turn, on the same code path `POST /api/agent/answer` runs.

    The HTTP protocol carries the request body through unchanged, so the payload
    is the `AgentRequest` the service already takes and the response is the
    `AgentResponse` it already returns. There is no wrapper to unpack and none to
    add; inventing one would put a second request contract in front of the agent
    and the receipts would stop matching a local run.

    `service.main.agent_answer` is called rather than reimplemented so the
    exception mapping cannot drift: a Bedrock `ClientError` or `BotoCoreError`
    becomes the same redacted 503 here as on the application route, a
    `RuntimeError` from the fail-closed pipeline becomes the same 503, and an
    unparseable body is refused with a 422 by the same model, which forbids
    unknown fields.
    """
    return agent_answer(request)


# Mounted last and at the root, so the two routes above are matched first and
# everything else is served by the workshop application itself, middleware,
# exception handlers and all. Registering selected routes onto this application
# instead would fork the surface, and the fork would be found by a participant.
app.mount("/", service_app)
