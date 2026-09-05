"""The AgentCore Runtime adapter answers the platform contract and nothing else.

`deploy/agentcore/app.py` is the container entry point. It exists so the
workshop process ships unchanged: `service.main.app` is mounted whole and the
two routes AgentCore's HTTP protocol requires are added around it. These checks
hold that boundary from both sides. The platform routes have to answer the
shapes the contract states, and every `/api/*` route the service serves has to
stay reachable through the adapter, because the storefront talks to the same
process and a mount that swallowed those routes would be invisible until a
participant hit one.

Nothing here reaches Bedrock or Aurora. The agent factory is replaced with a
recording fake, which is also the only way to assert that `/invocations` lands
on the same code path `POST /api/agent/answer` lands on rather than on a second
implementation of it.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import BaseRoute, Mount, Route

from deploy.agentcore.app import app as adapter_app
from service.main import app as service_app
from service.models import AgentRequest, AgentResponse

FAKE_RUN_ID = UUID("00000000-0000-4000-8000-000000000abc")

#: The routes FastAPI installs on every application it builds. They are
#: `starlette.routing.Route`, not `APIRoute`, so they never reach the
#: exactly-two assertion below; the set is named to say why that is safe.
FASTAPI_DEFAULT_ROUTES = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


class _RecordingAgent:
    """Stands in for the Strands agent so no model and no database is reached."""

    def __init__(self) -> None:
        self.requests: list[AgentRequest] = []
        self.failure: Exception | None = None

    def answer(self, request: AgentRequest) -> AgentResponse:
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        return AgentResponse(
            agent_run_id=FAKE_RUN_ID,
            question=request.question,
            answer="A fake grounded answer.",
            plan=[],
            recommendations=[],
            citations=[],
            trace=[],
        )


@pytest.fixture
def agent(monkeypatch) -> _RecordingAgent:
    """Replace the factory the agent route resolves when it runs.

    `service/main.py` does `from service.agent import get_product_discovery_agent`,
    so the name its route body looks up at call time lives in `service.main`.
    Patching `service.agent` instead would install a fake nothing calls, and the
    test would reach Bedrock while appearing to pass.
    """
    fake = _RecordingAgent()
    monkeypatch.setattr("service.main.get_product_discovery_agent", lambda: fake)
    return fake


def _served_routes(routes: list[BaseRoute], prefix: str = "") -> set[tuple[str, str]]:
    """Every (method, path) an application answers, mounts walked through.

    A mounted sub-application contributes its routes under the mount path, and
    those routes do not appear in the outer application's own `routes` list.
    Comparing the outer lists alone would report a parity failure that is not
    real, or miss one that is.
    """
    served: set[tuple[str, str]] = set()
    for route in routes:
        if isinstance(route, Mount):
            served |= _served_routes(list(route.routes), prefix + route.path)
        elif isinstance(route, Route) and route.methods:
            # `APIRoute` subclasses `Route`, so this covers the application's
            # own endpoints and the docs routes FastAPI installs alike.
            served |= {(method, prefix + route.path) for method in route.methods}
    return served


def test_ping_reports_the_contract_health_status():
    """AgentCore checks `GET /ping` and reads `status` out of the body."""
    response = TestClient(adapter_app).get("/ping")

    assert response.status_code == 200
    assert response.json() == {"status": "Healthy"}


def test_invocations_answers_with_the_agent_response(agent):
    payload = {
        "question": "quiet keyboard for an open-plan office",
        "result_limit": 4,
        "filters": {"in_stock_only": True, "max_price_cents": 15000},
    }

    response = TestClient(adapter_app).post("/invocations", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["agent_run_id"] == str(FAKE_RUN_ID)
    assert body["answer"] == "A fake grounded answer."
    assert body["question"] == payload["question"]
    assert [request.question for request in agent.requests] == [payload["question"]]
    carried = agent.requests[0]
    assert carried.result_limit == 4
    assert carried.filters.max_price_cents == 15000
    assert carried.filters.in_stock_only is True


def test_invocations_rejects_a_malformed_payload(agent):
    """A typo has to fail loudly rather than run a request nobody wrote."""
    response = TestClient(adapter_app).post(
        "/invocations", json={"quesion": "no such field"}
    )

    assert response.status_code == 422, response.text
    assert agent.requests == []


def test_invocations_maps_a_failed_run_the_way_the_service_route_does(agent):
    """`RuntimeError` is 503 on `/api/agent/answer`, so it is 503 here."""
    agent.failure = RuntimeError("Rerank is required and the model is unreachable.")

    response = TestClient(adapter_app).post(
        "/invocations", json={"question": "quiet keyboard for an open-plan office"}
    )

    assert response.status_code == 503, response.text
    assert "Rerank is required" in response.json()["detail"]


def test_adapter_serves_every_route_the_service_serves():
    """The mount is whole. The storefront's endpoints survive the move."""
    service_routes = _served_routes(list(service_app.routes))
    adapter_routes = _served_routes(list(adapter_app.routes))
    api_routes = {route for route in service_routes if route[1].startswith("/api/")}

    assert len(api_routes) >= 10, (
        f"found {len(api_routes)} `/api/` routes on the service; fix: the "
        "route walk broke, so this gate was about to pass over an empty set"
    )
    missing = sorted(service_routes - adapter_routes)
    assert not missing, (
        f"found service routes the adapter does not serve: {missing}; fix: mount "
        "`service.main.app` whole instead of re-registering selected routes"
    )


def test_adapter_adds_exactly_the_two_contract_routes():
    """Two routes, and no place for a platform-only endpoint to accumulate."""
    own = {route.path for route in adapter_app.routes if isinstance(route, APIRoute)}

    assert own == {"/ping", "/invocations"}
    assert not FASTAPI_DEFAULT_ROUTES & own


def test_the_workshop_application_gains_no_platform_route():
    """Importing the adapter must not mutate the app the labs run."""
    service_paths = {route.path for route in service_app.routes}

    assert "/ping" not in service_paths
    assert "/invocations" not in service_paths
