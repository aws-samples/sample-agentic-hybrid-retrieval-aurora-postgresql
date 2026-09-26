"""The shared origin secret and process-local admission control, end to end.

`tests/conftest.py` overrides `verify_origin_access` open for the rest of the
suite, because every other test file is exercising retrieval, agent, or
catalog behavior, not this gate. This file is the one place that puts the
override back and drives requests through the real FastAPI dependency and the
real admission-control primitives in `service.access_control`, the way an
actual caller -- authorized, unauthorized, or spoofed -- would experience them.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from service.access_control import (
    acquire_model_admission_slot,
    assert_bootable,
    release_model_admission_slot,
    require_model_admission,
    reset_admission_state,
    verify_origin_access,
)
from service.config import ConfigurationError, get_settings
from service.main import app
from service.models import AgentResponse

ORIGIN_HEADER = "X-Mosaic-Origin-Verify"
SECRET = "offline-test-suite-secret"


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def enforce_real_origin_check():
    """Undo the suite-wide bypass so a test exercises the real dependency."""
    app.dependency_overrides.pop(verify_origin_access, None)
    yield
    app.dependency_overrides[verify_origin_access] = lambda: None


# --------------------------------------------------------------------------
# Fail-closed startup
# --------------------------------------------------------------------------


def test_assert_bootable_refuses_a_deployment_missing_its_secret():
    broken = replace(
        get_settings(), require_origin_verification=True, origin_verify_secret=None
    )
    with pytest.raises(ConfigurationError, match="MOSAIC_ORIGIN_VERIFY_SECRET"):
        assert_bootable(broken)


def test_assert_bootable_accepts_a_configured_secret_or_an_explicit_bypass():
    settings = get_settings()
    assert_bootable(
        replace(settings, require_origin_verification=True, origin_verify_secret="x")
    )
    assert_bootable(
        replace(settings, require_origin_verification=False, origin_verify_secret=None)
    )


def test_lifespan_startup_refuses_to_serve_without_a_configured_secret(monkeypatch):
    """The ASGI lifespan itself refuses to start, not just individual requests."""
    monkeypatch.setenv("MOSAIC_REQUIRE_ORIGIN_VERIFICATION", "true")
    monkeypatch.delenv("MOSAIC_ORIGIN_VERIFY_SECRET", raising=False)

    with (
        pytest.raises(ConfigurationError, match="MOSAIC_ORIGIN_VERIFY_SECRET"),
        TestClient(app),
    ):
        pass


# --------------------------------------------------------------------------
# Origin verification
# --------------------------------------------------------------------------


def test_health_is_public_without_any_header(enforce_real_origin_check):
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200


def test_protected_route_rejects_a_missing_header(
    enforce_real_origin_check, monkeypatch
):
    spy = _CallSpy()
    monkeypatch.setattr("service.main.catalog_summary", spy)

    response = TestClient(app).get("/api/catalog/summary")

    assert response.status_code == 401
    assert "workshop origin secret" in response.json()["detail"]
    assert spy.calls == 0, "no protected work should run for an unauthorized request"


def test_protected_route_rejects_a_spoofed_header(
    enforce_real_origin_check, monkeypatch
):
    spy = _CallSpy()
    monkeypatch.setattr("service.main.catalog_summary", spy)

    response = TestClient(app).get(
        "/api/catalog/summary", headers={ORIGIN_HEADER: "not-the-secret"}
    )

    assert response.status_code == 401
    assert spy.calls == 0, "no protected work should run for a spoofed header"


def test_protected_route_admits_the_correct_header(
    enforce_real_origin_check, monkeypatch
):
    spy = _CallSpy(result={"status": "ok"})
    monkeypatch.setattr("service.main.catalog_summary", spy)

    response = TestClient(app).get(
        "/api/catalog/summary", headers={ORIGIN_HEADER: SECRET}
    )

    assert response.status_code == 200
    assert spy.calls == 1


@pytest.mark.parametrize(
    ("client_host", "expected_status"),
    [
        ("127.0.0.1", 200),
        ("203.0.113.5", 403),
    ],
)
def test_development_bypass_is_loopback_only(
    enforce_real_origin_check, monkeypatch, client_host, expected_status
):
    """`MOSAIC_REQUIRE_ORIGIN_VERIFICATION=false` must still refuse a remote caller."""
    monkeypatch.setenv("MOSAIC_REQUIRE_ORIGIN_VERIFICATION", "false")
    monkeypatch.setattr("service.main.catalog_summary", _CallSpy(result={"ok": True}))
    client = TestClient(app, client=(client_host, 12345))

    response = client.get("/api/health")
    assert response.status_code == 200, "health stays public regardless of the bypass"

    response = client.get("/api/catalog/summary")
    assert response.status_code == expected_status


# --------------------------------------------------------------------------
# Admission control: a tiny standalone app exercises the real dependency in
# isolation from retrieval/model mocking, which is an orthogonal concern.
# --------------------------------------------------------------------------

_admission_probe_app = FastAPI()


@_admission_probe_app.get("/probe", dependencies=[Depends(require_model_admission)])
def _probe() -> dict[str, bool]:
    return {"ok": True}


@_admission_probe_app.get("/explode", dependencies=[Depends(require_model_admission)])
def _explode() -> None:
    raise RuntimeError("simulated route failure")


def test_admission_rejects_once_the_concurrency_limit_is_reached(monkeypatch):
    monkeypatch.setenv("MOSAIC_MAX_CONCURRENT_MODEL_RUNS", "1")
    monkeypatch.setenv("MOSAIC_MODEL_RATE_LIMIT_PER_MINUTE", "100")
    client = TestClient(_admission_probe_app)

    held_slot = acquire_model_admission_slot()
    try:
        response = client.get("/probe")
        assert response.status_code == 429
        assert response.headers["retry-after"]
        assert "retry" in response.json()["detail"].lower()
    finally:
        release_model_admission_slot(held_slot)

    # Releasing frees the slot for the next caller.
    assert client.get("/probe").status_code == 200


def test_admission_slot_releases_after_a_route_exception(monkeypatch):
    monkeypatch.setenv("MOSAIC_MAX_CONCURRENT_MODEL_RUNS", "1")
    monkeypatch.setenv("MOSAIC_MODEL_RATE_LIMIT_PER_MINUTE", "100")
    client = TestClient(_admission_probe_app, raise_server_exceptions=False)

    failed = client.get("/explode")
    assert failed.status_code == 500

    # A route that raised must still have given its slot back.
    assert client.get("/probe").status_code == 200


def test_admission_rate_limit_rejects_after_the_per_minute_budget(monkeypatch):
    monkeypatch.setenv("MOSAIC_MAX_CONCURRENT_MODEL_RUNS", "100")
    monkeypatch.setenv("MOSAIC_MODEL_RATE_LIMIT_PER_MINUTE", "1")
    client = TestClient(_admission_probe_app)

    assert client.get("/probe").status_code == 200
    second = client.get("/probe")
    assert second.status_code == 429
    assert "per minute" in second.json()["detail"]


def test_search_route_rejects_excess_work_before_any_search_runs(monkeypatch):
    """The real `/api/search` route, wired to the real admission dependency."""
    monkeypatch.setenv("MOSAIC_MAX_CONCURRENT_MODEL_RUNS", "1")
    monkeypatch.setenv("MOSAIC_MODEL_RATE_LIMIT_PER_MINUTE", "100")
    app.dependency_overrides.pop(verify_origin_access, None)
    try:
        spy = _CallSpy()
        monkeypatch.setattr("service.main.search_with_telemetry", spy)
        client = TestClient(app)
        headers = {ORIGIN_HEADER: SECRET}

        held_slot = acquire_model_admission_slot()
        try:
            response = client.post(
                "/api/search",
                json={"query": "quiet mechanical keyboard"},
                headers=headers,
            )
            assert response.status_code == 429
            assert spy.calls == 0, "search must not run once admission is exhausted"
        finally:
            release_model_admission_slot(held_slot)
    finally:
        app.dependency_overrides[verify_origin_access] = lambda: None


def test_streaming_route_holds_its_admission_slot_until_the_stream_completes(
    monkeypatch,
):
    monkeypatch.setenv("MOSAIC_MAX_CONCURRENT_MODEL_RUNS", "1")
    monkeypatch.setenv("MOSAIC_MODEL_RATE_LIMIT_PER_MINUTE", "100")
    reset_admission_state()

    response = AgentResponse(
        agent_run_id=uuid4(),
        question="What should I buy?",
        answer="Choose the quiet option.",
        plan=[],
        recommendations=[],
        citations=[],
        trace=[],
    )

    class FakeStreamingAgent:
        # `service.main.stream_agent_answer` hands its acquired slot to
        # whatever `.stream()` implementation `get_product_discovery_agent()`
        # returns; `ProductDiscoveryAgent.stream` releases it through
        # `release_run_admission` in its own `finally`, so a stand-in agent
        # must do the same to keep this test meaningful about the route, not
        # about the real class's internals.
        async def stream(self, _request, admission_slot=None, **_kwargs):
            try:
                yield {"agent_response": response}
            finally:
                if admission_slot is not None:
                    release_model_admission_slot(admission_slot)

    monkeypatch.setattr(
        "service.main.get_product_discovery_agent", lambda: FakeStreamingAgent()
    )

    client = TestClient(app)
    completed = client.post(
        "/api/agent/answer/stream",
        json={"question": "What should I buy?"},
    )
    assert completed.status_code == 200

    # The generator's own `finally` released the slot once the stream ended, so
    # a fresh acquire must succeed rather than block or raise.
    slot = acquire_model_admission_slot()
    release_model_admission_slot(slot)


def test_streaming_route_rejects_before_starting_the_stream_when_saturated(
    monkeypatch,
):
    monkeypatch.setenv("MOSAIC_MAX_CONCURRENT_MODEL_RUNS", "1")
    monkeypatch.setenv("MOSAIC_MODEL_RATE_LIMIT_PER_MINUTE", "100")
    reset_admission_state()

    agent_spy = _CallSpy()
    monkeypatch.setattr("service.main.get_product_discovery_agent", agent_spy)

    held_slot = acquire_model_admission_slot()
    try:
        response = TestClient(app).post(
            "/api/agent/answer/stream",
            json={"question": "What should I buy?"},
        )
        assert response.status_code == 429
        assert agent_spy.calls == 0, "no agent work before admission is granted"
    finally:
        release_model_admission_slot(held_slot)


class _CallSpy:
    """A callable that counts its invocations and optionally returns a value."""

    def __init__(self, result=None) -> None:
        self.calls = 0
        self.result = result

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.result
