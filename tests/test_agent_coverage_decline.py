"""An unanchored question gets a declining answer, not a confident one.

`service.coverage` already labels a request that names something the catalog
does not carry. Shop shows the closest products under that label, because a
shopper reading a caveat above real chargers is better served than one reading
an empty page. The agent has no equivalent: it returns one answer of record, so
the same absence has to become a refusal to recommend.

Two failure modes bound this file, and they pull in opposite directions.

The first is the one the feature exists to stop: the controller overruling a
declining model because products happen to sit in run state, which is what
`_finalize_if_needed` did before this change. `_fallback_product_ids` has no
relevance criterion at all -- it takes the first two results of each search --
so an unanchored query returned whatever RRF ranked highest and the answer of
record presented it as the best fit.

The second is worse and is why several tests here assert that nothing happens.
An unseeded vocabulary makes every term look absent. If `unavailable` were
treated as `unanchored`, one skipped seed step would refuse every request on
the deployment while presenting as a working guardrail. The `unavailable`, the
missing-verdict, and the no-search tests are permanent falsifiers: a decline
firing in any of them means the gate is wrong, not the run.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest

from service import agent_tools
from service.agent import SYSTEM_PROMPT, ProductDiscoveryAgent
from service.coverage import summarize
from service.lab_checks import load_mission
from service.models import (
    AgentRequest,
    ProductSummary,
    QueryCoverage,
    RetrievalDiagnostics,
    RetrievalProfile,
    SearchFilters,
    SearchResponse,
    SourceAttribution,
    TermCoverage,
)

QUESTION = "replacement charging brick for model A2342"


def _term(
    token: str,
    verdict: str,
    *,
    ordinal: int = 1,
    token_kind: str = "asciiword",
    ndoc: int = 0,
) -> TermCoverage:
    return TermCoverage(
        ordinal=ordinal,
        token=token,
        token_kind=token_kind,
        lexeme=token.lower(),
        ndoc=ndoc,
        verdict=verdict,
    )


def unanchored(*tokens: str) -> QueryCoverage:
    """The verdict `mosaic_search.query_term_coverage` returns for an absence.

    Built through `service.coverage.summarize`, the same reduction the request
    path runs, rather than by hand-setting `confidence`. A hand-built verdict
    would keep passing after `summarize` stopped producing it.
    """
    return summarize(
        [
            _term("charging", "matched", ordinal=1, ndoc=9120),
            *(
                _term(token, "unmatched_anchor", ordinal=index, token_kind="numword")
                for index, token in enumerate(tokens, 2)
            ),
        ]
    )


def grounded() -> QueryCoverage:
    return summarize([_term("charging", "matched", ndoc=9120)])


def unavailable() -> QueryCoverage:
    """What an unseeded corpus vocabulary reports. Never a refusal."""
    return QueryCoverage(
        confidence="unavailable",
        note="Corpus vocabulary is empty; run CALL "
        "mosaic_search.refresh_corpus_lexeme() to enable coverage.",
    )


def product(product_id: int = 101) -> ProductSummary:
    return ProductSummary(
        product_id=product_id,
        sku=f"CE-POWER-{product_id:07d}",
        title="Voltiq 65W GaN Charger",
        short_description="A 65W USB-C charger for laptops and phones.",
        domain="consumer_electronics",
        category_key="chargers",
        category_path="Power > Chargers",
        brand="Voltiq",
        model="GN-65",
        price_cents=4_999,
        list_price_cents=5_999,
        rating=4.5,
        review_count=210,
        availability="in_stock",
        inventory_count=88,
        attributes={"usb_c_power_w": 65},
        tags=["usb-c"],
        sources=[
            SourceAttribution(
                source_uri=f"mosaic://product/{product_id}",
                revision="2026-09-04T00:00:00+00:00",
                title="Voltiq 65W GaN Charger",
                quote="A 65W USB-C charger for laptops and phones.",
            )
        ],
    )


def run_state(
    *,
    coverage: list[QueryCoverage | None],
    question: str = QUESTION,
    products: dict[int, ProductSummary] | None = None,
) -> dict[str, Any]:
    """A run state in the shape `agent_tools.start_run` builds it."""
    run_id = uuid4()
    return {
        "agent_session_id": uuid4(),
        "agent_turn_id": run_id,
        "agent_run_id": run_id,
        "question": question,
        "base_filters": SearchFilters(),
        "result_limit": 2,
        "execution_path": "full_retrieval",
        "trace": [],
        "search_event_ids": [uuid4() for _ in coverage],
        "context_search_event_ids": [],
        "context_product_ids": [],
        "products": dict(products if products is not None else {101: product()}),
        "evidence": {},
        "evidence_by_product": {},
        "searches": [
            {
                "query": question,
                "filters": SearchFilters(),
                "purpose": f"Retrieve products for: {question}",
                "product_ids": [101],
            }
            for _ in coverage
        ],
        "search_coverage": list(coverage),
        "answer_of_record": None,
    }


class _NoSynthesis:
    """Witness that no synthesis call happened, wherever it was attempted."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *_args: Any, **_kwargs: Any):
        self.calls += 1
        raise AssertionError(
            "synthesize_cited_answer invoked the citation model on a declined "
            "run; a declined answer of record is deterministic and must not "
            "reach Bedrock"
        )


@pytest.fixture
def no_synthesis(monkeypatch) -> _NoSynthesis:
    sentinel = _NoSynthesis()
    monkeypatch.setattr(agent_tools, "synthesize_answer", sentinel)
    return sentinel


class _SilentAgent:
    """A model turn that ends without calling its final tool."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def invoke_async(self, prompt: str):
        self.prompts.append(prompt)
        return type("Result", (), {"metrics": {}})()


def _install_run(monkeypatch, state: dict[str, Any]) -> None:
    def start_run(*_args):
        agent_tools._RUN.set(state)
        return state

    monkeypatch.setattr(agent_tools, "start_run", start_run)
    monkeypatch.setattr(agent_tools, "persist_completed_run", lambda *_a, **_k: None)


def test_a_run_whose_every_search_is_unanchored_declines(monkeypatch, no_synthesis):
    """The headline behavior: HTTP 200, an answer of record, no product."""
    state = run_state(coverage=[unanchored("A2342")])
    model = _SilentAgent()
    _install_run(monkeypatch, state)
    monkeypatch.setattr("service.agent.build_agent", lambda: model)

    response = ProductDiscoveryAgent().answer(
        AgentRequest(question=QUESTION, result_limit=2)
    )

    assert model.prompts, "the model turn never ran, so nothing was exercised"
    assert response.outcome == "declined"
    assert response.recommendations == []
    assert response.citations == []
    assert "'A2342'" in response.answer
    assert response.decline_reason == "unanchored_query_terms: 'A2342'"
    assert no_synthesis.calls == 0


def test_the_declining_answer_never_says_the_results_are_below():
    """Shop's wording promises products under the caveat. The agent has none."""
    state = run_state(coverage=[unanchored("A2342")])
    assert agent_tools.record_declined_answer(state) is True
    answer = state["answer_of_record"]["answer"]

    assert "results below" not in answer
    assert "No product is recommended for this request." in answer


def test_one_grounded_search_keeps_the_run_grounded(monkeypatch, no_synthesis):
    """The permanent falsifier for the decline.

    Same run, same products, same controller path; only the coverage verdict
    changes. If this ever declines, the gate has stopped discriminating and
    every request on the deployment is refused.
    """
    state = run_state(coverage=[unanchored("A2342"), grounded()])
    completions: list[str] = []

    def complete(question: str) -> None:
        completions.append(question)
        state["answer_of_record"] = {
            "answer": "Choose the Voltiq 65W GaN Charger [1].",
            "citations": [],
            "recommendations": [product()],
            "usage": {},
        }

    monkeypatch.setattr(agent_tools, "complete_grounded_answer", complete)
    _install_run(monkeypatch, state)
    monkeypatch.setattr("service.agent.build_agent", _SilentAgent)

    response = ProductDiscoveryAgent().answer(
        AgentRequest(question=QUESTION, result_limit=2)
    )

    assert completions == [QUESTION]
    assert response.outcome == "grounded"
    assert response.decline_reason is None
    assert [item.product_id for item in response.recommendations] == [101]


@pytest.mark.parametrize(
    ("verdicts", "case"),
    [
        ([unavailable()], "unseeded-vocabulary"),
        ([None], "coverage-not-installed"),
        ([], "closed-world-follow-up"),
        ([unavailable(), unanchored("A2342")], "mixed-verdicts"),
    ],
)
def test_a_run_without_a_full_unanchored_verdict_never_declines(verdicts, case):
    """Permanent falsifiers, one per way the verdict can be absent.

    `unavailable` and a missing row are the same fact seen from two database
    states, and an empty list is a follow-up that issued no search of its own.
    None of them is evidence that the catalog lacks something.
    """
    state = run_state(coverage=list(verdicts))

    assert agent_tools.coverage_refusal(state) is None, case
    assert agent_tools.record_declined_answer(state) is False, case
    assert state["answer_of_record"] is None, case


def test_the_refusal_names_every_unmatched_term_once():
    state = run_state(
        coverage=[unanchored("A2342"), unanchored("A2342", "X9911")],
    )
    refusal = agent_tools.coverage_refusal(state)

    assert refusal is not None
    answer, reason = refusal
    assert "terms 'A2342', 'X9911'" in answer
    assert reason == "unanchored_query_terms: 'A2342', 'X9911'"


def test_finalize_does_not_fabricate_a_product_on_a_declined_run(monkeypatch):
    """The regression this unit exists for.

    `_fallback_product_ids` selects by search order and nothing else, so a
    populated `state["products"]` was enough to produce a recommendation. The
    products are still there; the controller must not reach them.
    """
    state = run_state(coverage=[unanchored("A2342")])

    def refuse(_question: str) -> None:
        raise AssertionError(
            "the controller fallback ran on a declined run and would have "
            "manufactured a recommendation from the unanchored candidate pool"
        )

    monkeypatch.setattr(agent_tools, "complete_grounded_answer", refuse)

    error = ProductDiscoveryAgent._finalize_if_needed(
        AgentRequest(question=QUESTION, result_limit=2),
        state,
    )

    assert error is None
    assert state["products"], "the candidate pool emptied, so this proves nothing"
    assert state["answer_of_record"]["outcome"] == "declined"
    assert state["answer_of_record"]["recommendations"] == []


def test_finalize_still_completes_a_grounded_run(monkeypatch):
    """Independence: the guard must not fire on an ordinary run."""
    state = run_state(coverage=[grounded()])
    completions: list[str] = []
    monkeypatch.setattr(
        agent_tools,
        "complete_grounded_answer",
        completions.append,
    )

    error = ProductDiscoveryAgent._finalize_if_needed(
        AgentRequest(question=QUESTION, result_limit=2),
        state,
    )

    assert error is None
    assert completions == [QUESTION]


def test_a_grounded_mission_question_reaches_the_controller_unrefused(monkeypatch):
    """The controller path for Lab 3's question, with its verdict assumed.

    The verdict is a fixture, not a measurement. `coverage=[grounded()]` is
    asserted here rather than derived, so this cannot detect an unanchored term
    creeping into the mission question; it proves only that the decline gate
    stays out of the way of a grounded run carrying that exact question text.

    Whether the mission's terms are actually in the catalog is decided by
    `mosaic_search.query_term_coverage` against a seeded database, so it is
    owned by the live probes: `make validate-missions` with a DSN, and
    `make validate-lab-3`. No offline vocabulary check is invented here, because
    a check built from the same question it judges could not fail.
    """
    mission = load_mission("reason")
    state = run_state(coverage=[grounded()], question=mission["query"])
    completions: list[str] = []

    def complete(question: str) -> None:
        completions.append(question)
        state["answer_of_record"] = {
            "answer": "Choose the Voltiq 65W GaN Charger [1].",
            "citations": [],
            "recommendations": [product()],
            "usage": {},
        }

    monkeypatch.setattr(agent_tools, "complete_grounded_answer", complete)
    _install_run(monkeypatch, state)
    monkeypatch.setattr("service.agent.build_agent", _SilentAgent)

    response = ProductDiscoveryAgent().answer(
        AgentRequest(question=mission["query"], result_limit=2)
    )

    assert completions == [mission["query"]]
    assert response.outcome == "grounded"
    assert response.recommendations, "Lab 3's mission lost its recommendation"


def search_response(
    query: str,
    *,
    coverage: QueryCoverage,
    results: list[ProductSummary],
) -> SearchResponse:
    """One `RetrievalService.search` return value, in its production shape."""
    return SearchResponse(
        search_event_id=uuid4(),
        query=query,
        normalized_query=query,
        applied_filters={},
        results=results,
        diagnostics=RetrievalDiagnostics(
            strategy="rrf_fusion+rerank",
            embedding_model_id="fake",
            embedding_dimensions=1024,
            rerank_model_id="fake",
            rerank_status="applied",
            ranking_policy=["RRF candidate fusion"],
            retrieval_profile=RetrievalProfile(),
            candidate_counts={"fused_pool": len(results)},
            stage_timings_ms={},
            total_latency_ms=1,
            warnings=[],
        ),
        coverage=coverage,
    )


def _install_retrieval(monkeypatch, responses: list[SearchResponse]) -> None:
    """Serve one prepared response per `search_products` call, in order."""
    remaining = list(responses)

    def search(request):
        assert remaining, "search_products was called more times than planned"
        return remaining.pop(0)

    monkeypatch.setattr(agent_tools, "_search_with_telemetry", search)


def _empty_run_state() -> dict[str, Any]:
    """A run that has not searched yet, for driving `search_products` directly."""
    state = run_state(coverage=[])
    state["searches"] = []
    state["search_event_ids"] = []
    state["products"] = {}
    return state


def test_search_products_records_the_coverage_of_every_search(monkeypatch):
    """The production tool, not a hand-filled state key.

    A test that appended to `search_coverage` itself would keep passing after
    `search_products` stopped recording it, and the whole decision reads that
    list.
    """
    _install_retrieval(
        monkeypatch,
        [search_response(QUESTION, coverage=unanchored("A2342"), results=[product()])],
    )
    state = _empty_run_state()
    token = agent_tools._RUN.set(state)
    try:
        result = agent_tools.search_products(QUESTION, limit=1)
    finally:
        agent_tools._RUN.reset(token)

    assert result["ok"] is True
    assert result["coverage"]["confidence"] == "unanchored"
    assert result["coverage"]["unmatched_terms"] == ["A2342"]
    assert [item.confidence for item in state["search_coverage"]] == ["unanchored"]
    assert agent_tools.coverage_refusal(state) is not None


def test_the_tool_payload_never_hands_the_model_shops_wording(monkeypatch):
    """`coverage.note` promises results the agent has none of.

    Shop's note ends "The results below answer the rest of the request." A
    declined turn returns nothing below, so putting that sentence in the tool
    payload would be a false statement the model can quote verbatim.
    """
    verdict = unanchored("A2342")
    assert "results below" in verdict.note, (
        "the note stopped carrying Shop's wording, so this test no longer "
        "guards anything; re-derive it from service.coverage.unanchored_note"
    )
    _install_retrieval(
        monkeypatch,
        [search_response(QUESTION, coverage=verdict, results=[product()])],
    )
    state = _empty_run_state()
    token = agent_tools._RUN.set(state)
    try:
        result = agent_tools.search_products(QUESTION, limit=1)
    finally:
        agent_tools._RUN.reset(token)

    assert "note" not in result["coverage"]
    assert "results below" not in json.dumps(result, default=str)


def test_a_grounded_search_with_an_empty_window_still_counts(monkeypatch):
    """The grounded verdict survives a search that returned no eligible product.

    `search_products` fails an empty ranked window, and that failure used to
    return before the coverage verdict was recorded. The verdict was still real:
    the search ran, and the catalog did carry its terms. Losing it let the next
    unanchored search decline the whole run on a single verdict, which is not
    what `coverage_refusal` promises or what `docs/api-contract.md` states.
    """
    _install_retrieval(
        monkeypatch,
        [
            search_response(QUESTION, coverage=grounded(), results=[]),
            search_response(
                QUESTION, coverage=unanchored("A2342"), results=[product()]
            ),
        ],
    )
    state = _empty_run_state()
    token = agent_tools._RUN.set(state)
    try:
        empty = agent_tools.search_products("quiet mechanical keyboard", limit=1)
        second = agent_tools.search_products(QUESTION, limit=1)
    finally:
        agent_tools._RUN.reset(token)

    assert empty["ok"] is False, "the empty-window guard stopped firing"
    assert second["ok"] is True
    assert [item.confidence for item in state["search_coverage"]] == [
        "grounded",
        "unanchored",
    ]
    assert agent_tools.coverage_refusal(state) is None
    assert agent_tools.record_declined_answer(state) is False
    assert state["answer_of_record"] is None


def test_an_unanchored_verdict_naming_no_term_refuses_to_decide():
    """A shape `service.coverage.summarize` cannot produce, so it must not pass.

    Hand-built, because that is the only way to reach it. Returning `None` here
    would let an unanchored run recommend, and declining would write an answer
    of record that names no term at all.
    """
    state = run_state(coverage=[QueryCoverage(confidence="unanchored")])

    with pytest.raises(agent_tools.CoverageContractError, match="unmatched_terms"):
        agent_tools.coverage_refusal(state)


def test_the_synthesis_tool_refuses_to_recommend_on_a_declined_run(
    monkeypatch, no_synthesis
):
    """The model's own path, not just the controller's.

    The refusal is checked before the product bounds, so which products the
    model selected cannot change the verdict.
    """
    state = run_state(coverage=[unanchored("A2342")])
    token = agent_tools._RUN.set(state)
    try:
        result = agent_tools.synthesize_cited_answer(QUESTION, [101])
    finally:
        agent_tools._RUN.reset(token)

    assert result["ok"] is True
    assert result["citations"] == []
    assert "'A2342'" in result["answer"]
    assert no_synthesis.calls == 0
    assert state["answer_of_record"]["outcome"] == "declined"
    step = state["trace"][-1]
    assert step["tool"] == "synthesize_cited_answer"
    assert step["outcome"] == "denied"
    assert "unanchored_query_terms: 'A2342'" in step["detail"]


class _FakeCursor:
    def __init__(self, sink: list[list[dict[str, Any]]]) -> None:
        self._sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def executemany(self, _sql: str, rows) -> None:
        self._sink.append(list(rows))


class _FakeConnection:
    """Captures the parameters `persist_completed_run` writes."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, Any]] = []
        self.tool_rows: list[list[dict[str, Any]]] = []
        self.committed = False

    def execute(self, sql: str, params=None):
        self.statements.append((sql, params))
        return self

    def cursor(self):
        return _FakeCursor(self.tool_rows)

    def commit(self) -> None:
        self.committed = True


def _persisted_intent(connection: _FakeConnection) -> dict[str, Any]:
    turn_updates = [
        params
        for sql, params in connection.statements
        if "UPDATE mosaic.agent_turn" in sql
    ]
    assert len(turn_updates) == 1, (
        f"expected exactly one agent_turn update, found {len(turn_updates)}; "
        "the persisted intent is read from that statement's parameters"
    )
    return json.loads(turn_updates[0][1])


@pytest.mark.parametrize(
    ("verdict", "expected_outcome", "expected_reason"),
    [
        (unanchored("A2342"), "declined", "unanchored_query_terms: 'A2342'"),
        (grounded(), "grounded", None),
    ],
    ids=["declined", "grounded"],
)
def test_the_outcome_reaches_extracted_intent(
    monkeypatch, verdict, expected_outcome, expected_reason
):
    """Lab 3's proof and the telemetry contract both read this column.

    Parameterized against both verdicts, so the assertion cannot pass by
    writing one constant.
    """
    state = run_state(coverage=[verdict])
    if expected_outcome == "declined":
        assert agent_tools.record_declined_answer(state) is True
    else:
        state["answer_of_record"] = {
            "answer": "Choose the Voltiq 65W GaN Charger [1].",
            "citations": [],
            "recommendations": [product()],
            "usage": {},
        }
    connection = _FakeConnection()

    @contextmanager
    def connect():
        yield connection

    monkeypatch.setattr(agent_tools, "connect", connect)
    agent_tools.persist_completed_run(state, usage={})

    assert connection.committed
    intent = _persisted_intent(connection)
    assert intent["outcome"] == expected_outcome
    assert intent["decline_reason"] == expected_reason


def test_a_failed_run_persists_no_outcome(monkeypatch):
    """A turn with no answer of record has no outcome, and must not claim one."""
    state = run_state(coverage=[grounded()])
    connection = _FakeConnection()

    @contextmanager
    def connect():
        yield connection

    monkeypatch.setattr(agent_tools, "connect", connect)
    agent_tools.persist_completed_run(state, usage={}, error_type="RuntimeError")

    intent = _persisted_intent(connection)
    assert intent["outcome"] is None
    assert intent["decline_reason"] is None


def test_the_search_event_ids_are_uuids_the_state_holds():
    """Guards the fixture itself, which several assertions above depend on."""
    state = run_state(coverage=[unanchored("A2342")])
    assert all(isinstance(value, UUID) for value in state["search_event_ids"])


def test_a_grounded_run_with_no_products_still_fails_closed(monkeypatch):
    """The decline's sibling, which it must not have converted into a 200.

    A grounded run that retrieved nothing has no answer of record and no way to
    make one. That is the 503 Lab 3 teaches. The decline shares the same seam,
    so a guard written one branch too high would swallow this case and return an
    empty 200 instead of the fail-closed signal.
    """
    request = AgentRequest(question=QUESTION, result_limit=2)
    state = run_state(coverage=[grounded()], products={})

    def refuse(_question: str) -> None:
        raise AssertionError(
            "the controller fallback ran with no retrieved product at all"
        )

    monkeypatch.setattr(agent_tools, "complete_grounded_answer", refuse)

    assert ProductDiscoveryAgent._finalize_if_needed(request, state) is None
    assert state["answer_of_record"] is None

    with pytest.raises(RuntimeError, match="citation-bounded answer"):
        ProductDiscoveryAgent()._response(request, state, None, None)


def _stream_events(agent: ProductDiscoveryAgent, request: AgentRequest) -> list[Any]:
    async def collect() -> list[Any]:
        return [event async for event in agent.stream(request)]

    return asyncio.run(collect())


class _SilentStreamingAgent:
    """A streamed model turn that ends without calling its final tool."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def stream_async(self, prompt: str):
        self.prompts.append(prompt)
        yield {"result": type("Result", (), {"metrics": {}})()}


def test_the_streaming_route_declines_the_same_way(monkeypatch, no_synthesis):
    """The SSE route is a second entry point, not a view of the first.

    `answer` and `stream` each assemble their own response, so a decline proven
    on one says nothing about the other. A declined stream must still terminate
    with an `agent_response`, not with the raised error a failed run yields.
    """
    state = run_state(coverage=[unanchored("A2342")])
    model = _SilentStreamingAgent()
    _install_run(monkeypatch, state)
    monkeypatch.setattr("service.agent.build_agent", lambda: model)

    events = _stream_events(
        ProductDiscoveryAgent(), AgentRequest(question=QUESTION, result_limit=2)
    )

    assert model.prompts, "the streamed model turn never ran"
    responses = [
        event["agent_response"] for event in events if "agent_response" in event
    ]
    assert len(responses) == 1
    assert responses[0].outcome == "declined"
    assert responses[0].recommendations == []
    assert responses[0].decline_reason == "unanchored_query_terms: 'A2342'"
    assert no_synthesis.calls == 0


def test_a_grounded_search_after_the_decline_does_not_reopen_it(monkeypatch):
    """The chosen behaviour, pinned so a later reading cannot call it a bug.

    The model is instructed to call `synthesize_cited_answer` exactly once, so a
    turn that synthesized and then searched again has already produced its
    answer of record. That answer stands. Letting a later search revoke it would
    mean the answer a caller received could stop being the answer of record,
    which is a worse contract than a stale decline.
    """
    state = run_state(coverage=[unanchored("A2342")])
    token = agent_tools._RUN.set(state)
    try:
        agent_tools.synthesize_cited_answer(QUESTION, [101])
    finally:
        agent_tools._RUN.reset(token)
    assert state["answer_of_record"]["outcome"] == "declined"

    state["search_coverage"].append(grounded())

    def refuse(_question: str) -> None:
        raise AssertionError(
            "the controller re-synthesized over an existing answer of record"
        )

    monkeypatch.setattr(agent_tools, "complete_grounded_answer", refuse)
    error = ProductDiscoveryAgent._finalize_if_needed(
        AgentRequest(question=QUESTION, result_limit=2),
        state,
    )

    assert error is None
    assert agent_tools.coverage_refusal(state) is None, (
        "the snapshot now reads grounded, which is exactly why the answer of "
        "record must not be recomputed from it"
    )
    assert state["answer_of_record"]["outcome"] == "declined"


def test_the_prompt_tells_the_model_what_an_unanchored_verdict_outranks():
    """Three instructions the deterministic guard cannot supply.

    The guard decides the outcome either way, so these lines only govern how
    much budget the model burns and what it says last. They are pinned because
    a paraphrase that drops the precedence rule sends the model back into the
    retry loop each failing tool suggests.
    """
    prompt = " ".join(SYSTEM_PROMPT.split())

    assert (
        "When a search comes back unanchored, that verdict outranks any tool's "
        "retry instruction." in prompt
    )
    assert (
        "Skip the shortlist, comparison, and evidence steps and call "
        "synthesize_cited_answer once" in prompt
    )
    assert (
        "Close a declined run with one short sentence saying the catalog does "
        "not carry the term the request named." in prompt
    )
    assert (
        "Close a grounded run with one short sentence saying the cited answer "
        "is ready." in prompt
    ), "the grounded closing instruction was lost while adding the declined one"
    assert (
        "call synthesize_cited_answer once with the products you retrieved"
        not in prompt
    ), "the superseded instruction to synthesize over retrieved products is back"
