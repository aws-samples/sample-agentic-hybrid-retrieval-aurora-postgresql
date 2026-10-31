"""A grounding_contract failure says why there is no answer.

Two different things used to read as "the answer checks refused every draft": a draft
the checks refused, and a step an answer with sources needs (finding products,
comparing them, reading their sources) that never completed, so no draft existed. Each
cause has its own message on the streaming path and on the non-streaming path, and each
message appears only for its own cause.
"""

import asyncio
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from service import agent_tools
from service.agent import (
    DRAFT_REFUSED,
    STEP_INCOMPLETE,
    GroundingContractError,
    ProductDiscoveryAgent,
)
from service.main import app
from service.models import AgentRequest
from service.synthesis import SynthesisOutputError

REFUSED_MARKER = "refused every draft"
STEP_MARKER = "did not complete"
RUN_ID = "6f1c2b8e-0d7a-4f43-9a51-2f7d3c9e8b10"

STEP_FAILURES = [
    "No retrieved products are available for synthesis",
    "Retrieved products were not compared before grounded synthesis",
    "No retrieved evidence is available for grounded synthesis",
]


def _stream_error(response_text: str) -> dict:
    block = next(
        part for part in response_text.split("\n\n") if part.startswith("event: error")
    )
    return json.loads(block.split("data: ", 1)[1])


def _stream_with_failure(monkeypatch, failure: dict) -> dict:
    class FailedAgent:
        async def stream(self, _request, **_kwargs):
            yield {"agent_failure": failure}

    monkeypatch.setattr("service.main.get_product_discovery_agent", FailedAgent)
    response = TestClient(app).post(
        "/api/agent/answer/stream", json={"question": "Find a quiet keyboard"}
    )
    assert response.status_code == 200
    return _stream_error(response.text)


def _stream_raising(monkeypatch, error: Exception) -> dict:
    class RaisingAgent:
        async def stream(self, _request, **_kwargs):
            if False:
                yield {}
            raise error

    monkeypatch.setattr("service.main.get_product_discovery_agent", RaisingAgent)
    response = TestClient(app).post(
        "/api/agent/answer/stream", json={"question": "Find a quiet keyboard"}
    )
    return _stream_error(response.text)


def _non_streaming_detail(monkeypatch, error: Exception) -> str:
    class RaisingAgent:
        def answer(self, _request):
            raise error

    monkeypatch.setattr("service.main.get_product_discovery_agent", RaisingAgent)
    response = TestClient(app).post(
        "/api/agent/answer", json={"question": "Compare these products", "filters": {}}
    )
    assert response.status_code == 503
    return response.json()["detail"]


def test_a_refused_draft_names_the_refusal_on_the_streaming_path(monkeypatch):
    payload = _stream_with_failure(
        monkeypatch,
        {
            "agent_run_id": RUN_ID,
            "code": "grounding_contract",
            "cause": DRAFT_REFUSED,
            "detail": "internal",
        },
    )

    assert REFUSED_MARKER in payload["detail"]
    assert STEP_MARKER not in payload["detail"]
    assert "internal" not in payload["detail"]
    assert payload["agent_run_id"] == RUN_ID
    assert payload["code"] == "grounding_contract"


def test_an_incomplete_step_names_the_step_on_the_streaming_path(monkeypatch):
    payload = _stream_with_failure(
        monkeypatch,
        {
            "agent_run_id": RUN_ID,
            "code": "grounding_contract",
            "cause": STEP_INCOMPLETE,
            "detail": "internal",
        },
    )

    assert STEP_MARKER in payload["detail"]
    assert REFUSED_MARKER not in payload["detail"]
    assert "internal" not in payload["detail"]
    assert payload["agent_run_id"] == RUN_ID
    assert payload["code"] == "grounding_contract"


def test_a_failure_with_no_recorded_cause_does_not_claim_a_refusal(monkeypatch):
    """An older runtime sends no cause; the honest reading is that no draft is known."""
    payload = _stream_with_failure(
        monkeypatch,
        {"agent_run_id": RUN_ID, "code": "grounding_contract", "detail": "internal"},
    )

    assert REFUSED_MARKER not in payload["detail"]
    assert STEP_MARKER in payload["detail"]


def test_a_refused_draft_names_the_refusal_on_the_non_streaming_path(monkeypatch):
    detail = _non_streaming_detail(
        monkeypatch, GroundingContractError("private", cause=DRAFT_REFUSED)
    )

    assert REFUSED_MARKER in detail
    assert STEP_MARKER not in detail
    assert "run ID" in detail
    assert "private" not in detail


def test_an_incomplete_step_names_the_step_on_the_non_streaming_path(monkeypatch):
    detail = _non_streaming_detail(
        monkeypatch, GroundingContractError("private", cause=STEP_INCOMPLETE)
    )

    assert STEP_MARKER in detail
    assert REFUSED_MARKER not in detail
    assert "get_product_evidence" in detail
    assert "run ID" in detail
    assert "private" not in detail


@pytest.mark.parametrize(
    ("cause", "present", "absent"),
    [
        (DRAFT_REFUSED, REFUSED_MARKER, STEP_MARKER),
        (STEP_INCOMPLETE, STEP_MARKER, REFUSED_MARKER),
    ],
)
def test_an_error_raised_inside_the_stream_carries_its_cause(
    monkeypatch, cause, present, absent
):
    payload = _stream_raising(monkeypatch, GroundingContractError("x", cause=cause))

    assert present in payload["detail"]
    assert absent not in payload["detail"]


def test_a_bare_grounding_error_defaults_to_the_incomplete_step_cause():
    assert GroundingContractError("x").cause == STEP_INCOMPLETE


def _state() -> dict:
    return {
        "agent_run_id": uuid4(),
        "products": {101: object()},
        "searches": [],
        "trace": [],
        "answer_of_record": None,
        "context_search_event_ids": [],
    }


def _fallback_raising(monkeypatch, error: Exception) -> None:
    def fail(_question):
        raise error

    monkeypatch.setattr(agent_tools, "record_declined_answer", lambda _state: False)
    monkeypatch.setattr(agent_tools, "complete_grounded_answer", fail)


def test_the_answer_checks_refusing_a_draft_is_recorded_as_a_refused_draft(
    monkeypatch,
):
    _fallback_raising(monkeypatch, SynthesisOutputError("claim not stated by [1]"))

    failure = ProductDiscoveryAgent._finalize_if_needed(
        AgentRequest(question="What should I buy?"), _state()
    )

    assert isinstance(failure, GroundingContractError)
    assert failure.cause == DRAFT_REFUSED


@pytest.mark.parametrize("message", STEP_FAILURES)
def test_a_step_that_did_not_complete_is_recorded_as_an_incomplete_step(
    monkeypatch, message
):
    _fallback_raising(monkeypatch, RuntimeError(message))

    failure = ProductDiscoveryAgent._finalize_if_needed(
        AgentRequest(question="What should I buy?"), _state()
    )

    assert isinstance(failure, GroundingContractError)
    assert failure.cause == STEP_INCOMPLETE


@pytest.mark.parametrize(
    ("error", "cause"),
    [
        (SynthesisOutputError("claim not stated by [1]"), DRAFT_REFUSED),
        (RuntimeError(STEP_FAILURES[0]), STEP_INCOMPLETE),
    ],
)
def test_the_streamed_failure_event_carries_the_cause(monkeypatch, error, cause):
    state = _state()

    class QuietAgent:
        async def stream_async(self, _prompt):
            if False:
                yield {}

    monkeypatch.setattr(agent_tools, "start_run", lambda *_a, **_k: state)
    monkeypatch.setattr("service.agent.build_agent", lambda: QuietAgent())
    monkeypatch.setattr(
        agent_tools, "persist_completed_run", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr("service.session_memory.attach_run", lambda *_a, **_k: None)
    monkeypatch.setattr("service.session_memory.capture_turn", lambda *_a: None)
    _fallback_raising(monkeypatch, error)

    async def drain():
        collected = []
        try:
            async for event in ProductDiscoveryAgent().stream(
                AgentRequest(question="What should I buy?")
            ):
                collected.append(event)
        except GroundingContractError:
            pass
        return collected

    failures = [
        e["agent_failure"] for e in asyncio.run(drain()) if "agent_failure" in e
    ]

    assert [failure["code"] for failure in failures] == ["grounding_contract"]
    assert failures[0]["cause"] == cause
    assert failures[0]["agent_run_id"] == str(state["agent_run_id"])
