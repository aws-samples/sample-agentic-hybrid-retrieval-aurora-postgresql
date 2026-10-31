"""A grounding_contract failure says why there is no answer, and says it truthfully.

Every cause is decided by the type of the failure that the real raise sites produce
inside the controller fallback, never by message text. These tests build run state that
makes each real site fire, run it through `ProductDiscoveryAgent._finalize_or_failure`,
and assert the cause; then they assert each cause's message on the streaming and the
non-streaming path, and that no other cause is given that message.
"""

import asyncio
import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_agent_coverage_decline import product, run_state
from test_model_runtime import evidence

from service import agent_tools, synthesis
from service.agent import (
    DRAFT_REFUSED,
    DRAFT_STOPPED,
    PRODUCTS_EXCLUDED,
    REVIEW_DECLINED,
    STEP_INCOMPLETE,
    UNEXPECTED,
    GroundingContractError,
    ProductDiscoveryAgent,
)
from service.answerability import AnswerabilityError, PartlySupportedSelection
from service.main import app
from service.models import AgentRequest, SearchFilters

CAUSES = [
    DRAFT_REFUSED,
    DRAFT_STOPPED,
    REVIEW_DECLINED,
    PRODUCTS_EXCLUDED,
    STEP_INCOMPLETE,
    UNEXPECTED,
]

#: A phrase only that cause's message contains.
MARKER = {
    DRAFT_REFUSED: "refused every draft",
    DRAFT_STOPPED: "stopped before it was finished",
    REVIEW_DECLINED: "do not support this request",
    PRODUCTS_EXCLUDED: "do not meet this request's filters",
    STEP_INCOMPLETE: "did not complete",
    UNEXPECTED: "could not finish an answer with sources",
}
RUN_ID = "6f1c2b8e-0d7a-4f43-9a51-2f7d3c9e8b10"


def _step(tool: str, **arguments) -> dict:
    return {
        "sequence": 1,
        "tool": tool,
        "detail": "",
        "outcome": "success",
        "arguments": arguments,
    }


def _state(*ids: int, compared: bool = True, explained: bool = True) -> dict:
    """A run that searched, found `ids`, and holds evidence for each, as start_run builds."""
    ids = ids or (101,)
    state = run_state(coverage=[], products={i: product(i) for i in ids})
    state["searches"] = [
        {
            "query": state["question"],
            "filters": SearchFilters(),
            "purpose": "p",
            "product_ids": list(ids),
        }
    ]
    state["search_event_ids"] = [uuid4()]
    state["trace"] = [_step("search_products")]
    if explained:
        state["trace"].append(_step("explain_retrieval"))
    if compared and len(ids) > 1:
        state["trace"].append(_step("compare_products", product_ids=list(ids)))
    state["evidence"] = {
        i: evidence().model_copy(update={"evidence_id": i, "product_id": i})
        for i in ids
    }
    state["evidence_by_product"] = {i: [i] for i in ids}
    return state


def _classify(monkeypatch, state: dict) -> GroundingContractError:
    monkeypatch.setattr(agent_tools, "set_declined_answer_of_record", lambda _s: False)
    with agent_tools.bind_run(state):
        failure = ProductDiscoveryAgent._finalize_or_failure(
            AgentRequest(question=state["question"]), state
        )
    assert isinstance(failure, GroundingContractError), failure
    assert failure.agent_run_id == str(state["agent_run_id"])
    return failure


def _tool_result(ok: bool, **extra):
    return lambda *_a, **_k: {
        "ok": ok,
        **({} if ok else {"error": "tool failed"}),
        **extra,
    }


# --- every real raise site, classified by type ---------------------------------------


def test_no_products_after_a_search_is_an_incomplete_step(monkeypatch):
    state = _state()
    state["searches"][0]["product_ids"] = []

    assert _classify(monkeypatch, state).cause == STEP_INCOMPLETE


def test_a_failed_comparison_is_an_incomplete_step(monkeypatch):
    state = _state(101, 102, compared=False)
    monkeypatch.setattr(agent_tools, "compare_products", _tool_result(False))

    assert _classify(monkeypatch, state).cause == STEP_INCOMPLETE


def test_a_comparison_that_never_ran_is_an_incomplete_step(monkeypatch):
    state = _state(101, 102, compared=False)
    monkeypatch.setattr(agent_tools, "compare_products", _tool_result(True))

    assert _classify(monkeypatch, state).cause == STEP_INCOMPLETE


def test_failed_evidence_is_an_incomplete_step(monkeypatch):
    state = _state()
    state["evidence_by_product"] = {}
    monkeypatch.setattr(agent_tools, "get_product_evidence", _tool_result(False))

    assert _classify(monkeypatch, state).cause == STEP_INCOMPLETE


def test_evidence_that_never_arrived_is_an_incomplete_step(monkeypatch):
    state = _state()
    state["evidence_by_product"] = {}
    monkeypatch.setattr(agent_tools, "get_product_evidence", _tool_result(True))

    assert _classify(monkeypatch, state).cause == STEP_INCOMPLETE


def test_no_retrieval_event_to_explain_is_an_incomplete_step(monkeypatch):
    state = _state(explained=False)
    state["search_event_ids"] = []

    assert _classify(monkeypatch, state).cause == STEP_INCOMPLETE


def test_a_failed_ranking_explanation_is_an_incomplete_step(monkeypatch):
    state = _state(explained=False)
    monkeypatch.setattr(agent_tools, "explain_retrieval", _tool_result(False))

    assert _classify(monkeypatch, state).cause == STEP_INCOMPLETE


def test_a_selection_outside_the_retrieved_products_is_an_incomplete_step(monkeypatch):
    state = _state()
    state["evidence_by_product"][999] = [101]
    monkeypatch.setattr(agent_tools, "_fallback_product_ids", lambda _s: [999])

    assert _classify(monkeypatch, state).cause == STEP_INCOMPLETE


def test_products_that_were_not_compared_before_synthesis_are_an_incomplete_step(
    monkeypatch,
):
    state = _state(101, 102, compared=False)
    monkeypatch.setattr(agent_tools, "compare_products", _tool_result(True))
    monkeypatch.setattr(agent_tools, "_comparison_covers", lambda *_a: False)

    assert _classify(monkeypatch, state).cause == STEP_INCOMPLETE


def test_no_evidence_for_the_selection_is_an_incomplete_step(monkeypatch):
    state = _state()
    monkeypatch.setattr(agent_tools, "_evidence_for_products", lambda *_a: [])

    assert _classify(monkeypatch, state).cause == STEP_INCOMPLETE


def test_products_from_an_earlier_answer_that_fail_the_filters_are_excluded(
    monkeypatch,
):
    state = _state(explained=False)
    state["searches"] = []
    state["trace"] = []
    state["context_product_ids"] = [101]
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchall.return_value = []
    monkeypatch.setattr(agent_tools, "connect", lambda: connection)

    assert _classify(monkeypatch, state).cause == PRODUCTS_EXCLUDED
    assert 101 not in state["products"]


def _synthesis_raising(monkeypatch, raiser) -> None:
    def synthesize(*_a, **_k):
        raiser()

    monkeypatch.setattr(agent_tools, "synthesize_answer", synthesize)


def test_a_draft_the_answer_checks_refuse_is_a_refused_draft(monkeypatch):
    _synthesis_raising(
        monkeypatch,
        lambda: synthesis.validate_cited_answer("No citation here.", [], []),
    )

    assert _classify(monkeypatch, _state()).cause == DRAFT_REFUSED


def test_a_draft_cut_off_by_max_tokens_is_a_refused_draft(monkeypatch):
    _synthesis_raising(
        monkeypatch,
        lambda: synthesis._validated_output({"stopReason": "max_tokens"}, [], []),
    )

    assert _classify(monkeypatch, _state()).cause == DRAFT_REFUSED


@pytest.mark.parametrize("stop_reason", ["content_filtered", "guardrail_intervened"])
def test_a_draft_that_stopped_before_it_finished_is_a_stopped_draft(
    monkeypatch, stop_reason
):
    _synthesis_raising(
        monkeypatch,
        lambda: synthesis._validated_output({"stopReason": stop_reason}, [], []),
    )

    assert _classify(monkeypatch, _state()).cause == DRAFT_STOPPED


def test_an_answerability_review_that_cannot_decide_is_a_declined_review(
    monkeypatch,
):
    def raiser():
        raise AnswerabilityError("answerability: invalid decision")

    _synthesis_raising(monkeypatch, raiser)

    assert _classify(monkeypatch, _state()).cause == REVIEW_DECLINED


def test_a_second_partial_verdict_after_narrowing_is_a_declined_review(monkeypatch):
    def raiser():
        raise PartlySupportedSelection([101], [102])

    _synthesis_raising(monkeypatch, raiser)

    assert _classify(monkeypatch, _state(101, 102)).cause == REVIEW_DECLINED


def test_any_other_failure_is_unexpected(monkeypatch):
    def raiser():
        raise KeyError("surprise")

    _synthesis_raising(monkeypatch, raiser)

    assert _classify(monkeypatch, _state()).cause == UNEXPECTED


def test_the_cause_comes_from_the_type_never_from_the_message(monkeypatch):
    def raiser():
        raise RuntimeError("The answer checks refused every draft; did not complete")

    _synthesis_raising(monkeypatch, raiser)

    assert _classify(monkeypatch, _state()).cause == UNEXPECTED


def test_a_bare_grounding_error_is_unexpected():
    assert GroundingContractError("x").cause == UNEXPECTED


# --- each cause's message, on both paths, and only for its cause ---------------------


def _sse_error(text: str) -> dict:
    block = next(p for p in text.split("\n\n") if p.startswith("event: error"))
    return json.loads(block.split("data: ", 1)[1])


def _stream_event(monkeypatch, failure: dict) -> dict:
    class FailedAgent:
        async def stream(self, _request, **_kwargs):
            yield {"agent_failure": failure}

    monkeypatch.setattr("service.main.get_product_discovery_agent", FailedAgent)
    response = TestClient(app).post(
        "/api/agent/answer/stream", json={"question": "Find a quiet keyboard"}
    )
    return _sse_error(response.text)


def _stream_raised(monkeypatch, error: Exception) -> dict:
    class RaisingAgent:
        async def stream(self, _request, **_kwargs):
            if False:
                yield {}
            raise error

    monkeypatch.setattr("service.main.get_product_discovery_agent", RaisingAgent)
    response = TestClient(app).post(
        "/api/agent/answer/stream", json={"question": "Find a quiet keyboard"}
    )
    return _sse_error(response.text)


def _non_streaming(monkeypatch, error: Exception) -> str:
    class RaisingAgent:
        def answer(self, _request):
            raise error

    monkeypatch.setattr("service.main.get_product_discovery_agent", RaisingAgent)
    response = TestClient(app).post(
        "/api/agent/answer", json={"question": "Compare these products", "filters": {}}
    )
    assert response.status_code == 503
    return response.json()["detail"]


def _only_its_own_marker(detail: str, cause: str) -> None:
    assert MARKER[cause] in detail
    for other in CAUSES:
        if other != cause:
            assert MARKER[other] not in detail, (cause, other)
    assert "private" not in detail


@pytest.mark.parametrize("cause", CAUSES)
def test_a_streamed_failure_event_gets_its_causes_message(monkeypatch, cause):
    payload = _stream_event(
        monkeypatch,
        {
            "agent_run_id": RUN_ID,
            "code": "grounding_contract",
            "cause": cause,
            "detail": "private",
        },
    )

    _only_its_own_marker(payload["detail"], cause)
    assert payload["code"] == "grounding_contract"
    assert payload["cause"] == cause
    assert payload["agent_run_id"] == RUN_ID


@pytest.mark.parametrize("cause", CAUSES)
def test_an_error_raised_inside_the_stream_uses_the_same_code_and_message(
    monkeypatch, cause
):
    payload = _stream_raised(
        monkeypatch,
        GroundingContractError("private", cause=cause, agent_run_id=RUN_ID),
    )

    _only_its_own_marker(payload["detail"], cause)
    assert payload["code"] == "grounding_contract"
    assert payload["cause"] == cause
    assert payload["agent_run_id"] == RUN_ID


@pytest.mark.parametrize("cause", CAUSES)
def test_the_non_streaming_response_gets_its_causes_message_and_the_run_id(
    monkeypatch, cause
):
    detail = _non_streaming(
        monkeypatch,
        GroundingContractError("private", cause=cause, agent_run_id=RUN_ID),
    )

    _only_its_own_marker(detail, cause)
    assert f"Run ID: {RUN_ID}" in detail


def test_a_failure_with_no_recorded_cause_is_unexpected_on_both_paths(monkeypatch):
    payload = _stream_event(
        monkeypatch,
        {"agent_run_id": RUN_ID, "code": "grounding_contract", "detail": "private"},
    )
    detail = _non_streaming(monkeypatch, GroundingContractError("private"))

    _only_its_own_marker(payload["detail"], UNEXPECTED)
    _only_its_own_marker(detail, UNEXPECTED)


def test_messages_that_ask_to_share_the_run_id_can_be_given_it():
    from service.main import _GROUNDING_MESSAGES, _grounding_detail

    for cause, message in _GROUNDING_MESSAGES.items():
        if "run ID" in message:
            assert f"Run ID: {RUN_ID}" in _grounding_detail(cause, RUN_ID)


# --- the streamed failure event carries the cause the classifier found ---------------


def test_the_streamed_failure_event_carries_the_real_cause(monkeypatch):
    state = _state()
    _synthesis_raising(
        monkeypatch,
        lambda: synthesis._validated_output({"stopReason": "content_filtered"}, [], []),
    )

    class QuietAgent:
        async def stream_async(self, _prompt):
            if False:
                yield {}

    monkeypatch.setattr(agent_tools, "start_run", lambda *_a, **_k: state)
    monkeypatch.setattr("service.agent.build_agent", lambda: QuietAgent())
    monkeypatch.setattr(agent_tools, "persist_completed_run", lambda *_a, **_k: None)
    monkeypatch.setattr("service.session_memory.attach_run", lambda *_a, **_k: None)
    monkeypatch.setattr("service.session_memory.capture_turn", lambda *_a: None)
    monkeypatch.setattr(agent_tools, "set_declined_answer_of_record", lambda _s: False)

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

    assert [f["code"] for f in failures] == ["grounding_contract"]
    assert failures[0]["cause"] == DRAFT_STOPPED
    assert failures[0]["agent_run_id"] == str(state["agent_run_id"])
