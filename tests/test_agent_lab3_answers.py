"""Lab 3 answers stay useful and honest when the catalog cannot check a request."""

import json
from types import SimpleNamespace

import pytest
from test_agent_coverage_decline import (
    _empty_run_state,
    grounded,
    product,
    run_state,
    search_response,
)
from test_answerability import Client, decision
from test_synthesis_claims import evidence
from test_synthesis_claims import product as synthesis_product

from service import agent_tools
from service.answerability import Answerability, SynthesisDeclined
from service.models import SearchFilters
from service.synthesis import ReportedLimits, synthesize_cited_answer

REAL_CATALOG = "reviews-2023-v2"


PRICE_NOTE = "matched against the prices recorded in the 2023 source listings"
STOCK_NOTE = (
    "does not record stock, so current stock or availability could not be checked"
)


def _searched(monkeypatch, results=None):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", REAL_CATALOG)
    searched = []

    def search(request):
        searched.append(request.filters)
        return search_response(
            request.query,
            coverage=grounded(),
            results=[product()] if results is None else results,
        )

    monkeypatch.setattr(agent_tools, "_search_with_telemetry", search)
    return searched


@pytest.mark.parametrize(
    "limits,requirement",
    [
        ({"max_price_cents": 30_000}, "a price of at most $300.00"),
        ({"min_price_cents": 5_000}, "a price of at least $50.00"),
        (
            {"min_price_cents": 5_000, "max_price_cents": 30_000},
            "a price between $50.00 and $300.00",
        ),
    ],
)
def test_a_budget_is_applied_to_the_source_listing_price(
    monkeypatch, limits, requirement
):
    searched = _searched(monkeypatch)
    state = _empty_run_state()
    with agent_tools.bind_run(state):
        result = agent_tools.search_products("noise cancelling headphones", **limits)

    applied = searched[0]
    assert applied.min_price_cents == limits.get("min_price_cents")
    assert applied.max_price_cents == limits.get("max_price_cents")
    assert state["source_price_limits"] == [requirement]
    assert not state.get("unverifiable_requirements")
    assert result["ok"] is True
    assert any("source" in warning for warning in result["diagnostics"]["warnings"])
    assert state["trace"][-1]["arguments"]["source_price_limits"] == [requirement]


@pytest.mark.parametrize(
    "limits", [{"in_stock_only": True}, {"availability": "in_stock"}]
)
def test_a_stock_requirement_is_reported_because_the_catalog_has_no_stock(
    monkeypatch, limits
):
    searched = _searched(monkeypatch)
    state = _empty_run_state()
    with agent_tools.bind_run(state):
        result = agent_tools.search_products("office chair", **limits)

    applied = searched[0]
    assert applied.in_stock_only is False and applied.availability is None
    assert state["unverifiable_requirements"] == ["current stock or availability"]
    assert not state.get("source_price_limits")
    assert any(
        "Not applied" in warning for warning in result["diagnostics"]["warnings"]
    )
    assert state["trace"][-1]["arguments"]["unverified_limits"] == [
        "current stock or availability"
    ]


def test_request_level_budget_is_reported_once_across_searches(monkeypatch):
    _searched(monkeypatch)
    state = _empty_run_state()
    state["base_filters"] = SearchFilters(max_price_cents=30_000)
    with agent_tools.bind_run(state):
        agent_tools.search_products("noise cancelling headphones")
        agent_tools.search_products("headset for calls")
    assert state["source_price_limits"] == ["a price of at most $300.00"]


def test_earlier_products_are_rechecked_with_the_budget_but_not_stock(monkeypatch):
    """Stock is never applied, so it cannot exclude a product from a follow-up."""
    from unittest.mock import MagicMock

    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", REAL_CATALOG)
    state = run_state(coverage=[grounded()])
    state["context_product_ids"] = [101]
    state["base_filters"] = SearchFilters(max_price_cents=30_000, in_stock_only=True)
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchall.return_value = [{"product_id": 101}]
    monkeypatch.setattr(agent_tools, "connect", lambda: connection)
    assert agent_tools._excluded_inherited_products(state, [101]) == []
    rechecked = json.loads(connection.execute.call_args.args[1][1])
    assert rechecked["max_price_cents"] == 30_000
    assert not rechecked.get("in_stock_only")


def test_price_limits_still_apply_when_the_catalog_records_offers(monkeypatch):
    monkeypatch.delenv("MOSAIC_CATALOG_DATASET", raising=False)
    searched = []

    def search(request):
        searched.append(request.filters)
        return search_response(request.query, coverage=grounded(), results=[product()])

    monkeypatch.setattr(agent_tools, "_search_with_telemetry", search)
    state = _empty_run_state()
    with agent_tools.bind_run(state):
        agent_tools.search_products("headphones", max_price_cents=30_000)
    assert searched[0].max_price_cents == 30_000
    assert not state.get("unverifiable_requirements")
    assert not state.get("source_price_limits")


def _declined(unmet: list[str]) -> SynthesisDeclined:
    review = Answerability(
        request_supported=False,
        reason="unsupported_requirements",
        products=[{"product_id": 101, "supported": False, "evidence_ids": []}],
        unmet_requirements=unmet,
    )
    return SynthesisDeclined(review, {})


def test_a_decline_names_what_the_sources_do_not_establish():
    state = run_state(coverage=[grounded()])
    agent_tools.record_unsupported_answer(state, _declined(["90W laptop charging"]))
    answer = state["answer_of_record"]["answer"]
    assert "90W laptop charging" in answer
    assert "No product is recommended" in answer


def test_a_decline_without_named_gaps_keeps_the_general_explanation():
    state = run_state(coverage=[grounded()])
    agent_tools.record_unsupported_answer(state, _declined([]))
    assert "do not establish the requirements" in state["answer_of_record"]["answer"]


def test_missing_prerequisites_are_refusals_not_errors():
    state = run_state(coverage=[grounded()])
    with agent_tools.bind_run(state):
        result = agent_tools.synthesize_cited_answer("headphones for calls", [101])
    assert result["ok"] is False
    assert state["trace"][-1]["outcome"] == "denied"


class DraftClient(Client):
    """A review that supports the request, then a fixed synthesis draft."""

    def __init__(self, draft: str):
        super().__init__(decision())
        self.draft = draft

    def converse(self, **kwargs):
        response = super().converse(**kwargs)
        if len(self.calls) > 1:
            response["output"]["message"]["content"] = [{"text": self.draft}]
        return response


def _synthesize(client, **kwargs):
    return synthesize_cited_answer(
        "Find noise cancelling headphones",
        [synthesis_product()],
        [evidence("Active noise cancellation. Bluetooth connectivity.")],
        client=client,
        settings=SimpleNamespace(synthesis_model_id="test", aws_region="us-east-1"),
        **kwargs,
    )


def test_a_source_priced_budget_reaches_the_review_and_the_answer():
    client = DraftClient("AuriLogic Flight ANC has active noise cancellation [1].")
    answer, _, _ = _synthesize(
        client, limits=ReportedLimits(source_priced=("a price of at most $300.00",))
    )
    review_request = client.calls[0]["messages"][0]["content"][0]["text"]
    assert "a price of at most $300.00" in review_request
    assert f"A price of at most $300.00 was {PRICE_NOTE}" in answer
    assert "confirm today's price in the original listing" in answer


def test_a_stock_requirement_ends_the_answer_with_the_stock_note():
    client = DraftClient("AuriLogic Flight ANC has active noise cancellation [1].")
    answer, _, _ = _synthesize(
        client, limits=ReportedLimits(unchecked=("current stock or availability",))
    )
    assert STOCK_NOTE in answer


def test_the_writer_leaves_reported_limits_to_the_fixed_notes():
    """A drafted "stock cannot be confirmed" sentence fails the availability check.

    The writer is told the limits are reported after its answer, so it does not
    spend a validation retry restating them.
    """
    client = DraftClient("AuriLogic Flight ANC has active noise cancellation [1].")
    _synthesize(
        client,
        limits=ReportedLimits(
            source_priced=("a price of at most $300.00",),
            unchecked=("current stock or availability",),
        ),
    )
    writer_request = client.calls[1]["messages"][0]["content"][0]["text"]
    assert "a price of at most $300.00" in writer_request
    assert "current stock or availability" in writer_request
    assert "Do not state prices" in writer_request


def test_the_writer_gets_no_limit_note_when_there_are_no_limits():
    client = DraftClient("AuriLogic Flight ANC has active noise cancellation [1].")
    _synthesize(client)
    assert (
        "Do not state prices"
        not in client.calls[1]["messages"][0]["content"][0]["text"]
    )


def test_an_empty_alternatives_section_is_not_shown():
    client = DraftClient(
        "AuriLogic Flight ANC has active noise cancellation [1].\n\n"
        "### Other strong options\nNo alternative headphones were supplied.\n\n"
        "### The deciding trade-off\nChoose AuriLogic Flight ANC for quiet calls [1]."
    )
    answer, _, _ = _synthesize(client)
    assert "Other strong options" not in answer
    assert "### The deciding trade-off" in answer


def test_a_declined_budget_question_still_says_how_the_budget_was_matched():
    state = run_state(coverage=[grounded()])
    state["source_price_limits"] = ["a price of at most $300.00"]
    agent_tools.record_unsupported_answer(state, _declined(["clear call audio"]))
    answer = state["answer_of_record"]["answer"]
    assert "clear call audio" in answer
    assert PRICE_NOTE in answer


def test_an_empty_budget_search_says_listings_without_a_price_were_left_out(
    monkeypatch,
):
    _searched(monkeypatch, results=[])
    state = _empty_run_state()
    with agent_tools.bind_run(state):
        agent_tools.search_products("headphones", max_price_cents=500)
    assert agent_tools.record_no_results_answer(state)
    answer = state["answer_of_record"]["answer"]
    assert PRICE_NOTE in answer
    assert "listings without one were left out" in answer


def test_an_empty_stock_search_still_says_stock_was_not_checked(monkeypatch):
    _searched(monkeypatch, results=[])
    state = _empty_run_state()
    with agent_tools.bind_run(state):
        agent_tools.search_products("chair", in_stock_only=True)
    assert agent_tools.record_no_results_answer(state)
    assert STOCK_NOTE in state["answer_of_record"]["answer"]
