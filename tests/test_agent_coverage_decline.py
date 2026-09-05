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

import json
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest

from service import agent_tools
from service.agent import ProductDiscoveryAgent
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


def test_the_declining_answer_never_says_the_results_are_below(monkeypatch):
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
        ([unavailable(), unanchored("A2342")], "one-verdict-missing"),
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


def test_the_lab_3_mission_question_still_produces_a_recommendation(monkeypatch):
    """No regression on the question Lab 3 is graded against.

    Its terms are all in the catalog, so its coverage is `grounded` and the
    decline must be invisible to it. A refusal here would fail Stage 03 for
    every participant.
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


def test_search_products_records_the_coverage_of_every_search(monkeypatch):
    """The production tool, not a hand-filled state key.

    A test that appended to `search_coverage` itself would keep passing after
    `search_products` stopped recording it, and the whole decision reads that
    list.
    """
    event_id = uuid4()
    verdict = unanchored("A2342")

    class FakeRetrieval:
        def search(self, request):
            return SearchResponse(
                search_event_id=event_id,
                query=request.query,
                normalized_query=request.query,
                applied_filters={},
                results=[product()],
                diagnostics=RetrievalDiagnostics(
                    strategy="rrf_fusion+rerank",
                    embedding_model_id="fake",
                    embedding_dimensions=1024,
                    rerank_model_id="fake",
                    rerank_status="applied",
                    ranking_policy=["RRF candidate fusion"],
                    retrieval_profile=RetrievalProfile(),
                    candidate_counts={"fused_pool": 1},
                    stage_timings_ms={},
                    total_latency_ms=1,
                    warnings=[],
                ),
                coverage=verdict,
            )

    monkeypatch.setattr(agent_tools, "get_retrieval_service", lambda: FakeRetrieval())
    monkeypatch.setattr(
        agent_tools,
        "_search_with_telemetry",
        lambda request: FakeRetrieval().search(request),
    )
    state = run_state(coverage=[])
    state["searches"] = []
    state["search_event_ids"] = []
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
