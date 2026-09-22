"""Empty searches are completed reads, not model or database outages."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

import pytest
from test_agent_coverage_decline import (
    _empty_run_state,
    _install_run,
    _stream_events,
    grounded,
    product,
    search_response,
)

from service import agent_tools
from service.agent import ProductDiscoveryAgent
from service.models import AgentRequest

QUESTION = "headphones for clear video calls"


def test_empty_searches_keep_receipts_and_stop_at_the_search_budget(monkeypatch):
    state = _empty_run_state()
    responses = []

    def search(request):
        response = search_response(request.query, coverage=grounded(), results=[])
        responses.append(response)
        return response

    monkeypatch.setattr(agent_tools, "_search_with_telemetry", search)
    request = AgentRequest(question=QUESTION)
    with agent_tools.bind_run(state):
        for _ in range(len(agent_tools.SEARCH_SLOTS)):
            assert agent_tools.search_products(QUESTION)["ok"] is False
        blocked = agent_tools.search_products(QUESTION)
        assert len(responses) == len(agent_tools.SEARCH_SLOTS)
        assert "allows" in blocked["error"]
        assert state["search_event_ids"] == [r.search_event_id for r in responses]
        assert len(state["searches"]) == len(responses)
        assert all(step["outcome"] == "success" for step in state["trace"])
        error = ProductDiscoveryAgent._finalize_if_needed(request, state)

    assert error is None
    response = ProductDiscoveryAgent()._response(request, state, None, None)
    assert response.outcome == "declined"
    assert response.decline_reason == "no_matching_products"
    assert response.recommendations == []
    assert response.citations == []
    assert "filters" in response.answer
    assert len(response.plan) == len(responses)


@pytest.mark.parametrize("failure_first", [False, True])
def test_database_failures_are_not_reported_as_empty_searches(
    monkeypatch, failure_first
):
    state = _empty_run_state()
    calls = 0

    def search(request):
        nonlocal calls
        calls += 1
        if (calls == 1) == failure_first:
            raise TimeoutError("database read timed out")
        return search_response(request.query, coverage=grounded(), results=[])

    monkeypatch.setattr(agent_tools, "_search_with_telemetry", search)
    with agent_tools.bind_run(state):
        agent_tools.search_products(QUESTION)
        agent_tools.search_products(QUESTION)
        agent_tools.search_products(QUESTION)
        assert calls == len(agent_tools.SEARCH_SLOTS)
        ProductDiscoveryAgent._finalize_if_needed(
            AgentRequest(question=QUESTION), state
        )
    assert state["answer_of_record"] is None


def test_an_empty_search_does_not_discard_a_later_match(monkeypatch):
    state = _empty_run_state()
    responses = iter(
        [
            search_response(QUESTION, coverage=grounded(), results=[]),
            search_response(QUESTION, coverage=grounded(), results=[product()]),
        ]
    )
    monkeypatch.setattr(
        agent_tools, "_search_with_telemetry", lambda _r: next(responses)
    )
    with agent_tools.bind_run(state):
        agent_tools.search_products(QUESTION)
        assert agent_tools.search_products(QUESTION)["ok"] is True
    assert list(state["products"]) == [product().product_id]
    assert state["answer_of_record"] is None


@pytest.mark.parametrize("streaming", [False, True])
def test_both_agent_transports_finish_an_empty_search(monkeypatch, streaming):
    state = _empty_run_state()
    _install_run(monkeypatch, state)
    monkeypatch.setattr(
        agent_tools,
        "_search_with_telemetry",
        lambda request: search_response(request.query, coverage=grounded(), results=[]),
    )

    class Model:
        async def invoke_async(self, _prompt):
            agent_tools.search_products(QUESTION)
            agent_tools.search_products(QUESTION)

        async def stream_async(self, prompt):
            await self.invoke_async(prompt)
            yield {"result": None}

    monkeypatch.setattr("service.agent.build_agent", Model)
    agent = ProductDiscoveryAgent()
    request = AgentRequest(question=QUESTION)
    if streaming:
        events = _stream_events(agent, request)
        assert not any("agent_failure" in event for event in events)
        response = events[-1]["agent_response"]
    else:
        response = agent.answer(request)
    assert response.outcome == "declined"
    assert response.decline_reason == "no_matching_products"
    assert len(response.plan) == len(agent_tools.SEARCH_SLOTS)


def test_parallel_searches_reserve_their_slots_before_retrieval(monkeypatch):
    state = _empty_run_state()
    budget = len(agent_tools.SEARCH_SLOTS)
    started = Barrier(budget + 1)
    release = Event()
    lock = Lock()
    calls = 0

    def search(request):
        nonlocal calls
        with lock:
            calls += 1
            ordinal = calls
        if ordinal <= budget:
            started.wait(timeout=5)
            assert release.wait(timeout=5)
        return search_response(request.query, coverage=grounded(), results=[])

    def call():
        with agent_tools.bind_run(state):
            return agent_tools.search_products(QUESTION)

    monkeypatch.setattr(agent_tools, "_search_with_telemetry", search)
    with ThreadPoolExecutor(max_workers=budget + 1) as executor:
        pending = [executor.submit(call) for _ in range(budget)]
        try:
            started.wait(timeout=5)
            blocked = executor.submit(call).result(timeout=5)
            assert "allows" in blocked["error"]
            assert calls == budget
        finally:
            release.set()
        for future in pending:
            future.result(timeout=5)
