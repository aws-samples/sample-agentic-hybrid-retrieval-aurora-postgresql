"""A tightened follow-up must not recommend the product it just ruled out.

Drives the production tools. Only `_search_with_telemetry` -- the Aurora and
Bedrock boundary -- is replaced, so the controller, the recovery path and the
synthesis entry point all execute.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_agent_coverage_decline import (
    _install_retrieval,
    grounded,
    product,
    run_state,
    search_response,
)

from service import agent_tools

BUDGET_CENTS = 10_000
OVER_BUDGET_CENTS = 17_999
FOLLOW_UP = "same thing but under $100"


def follow_up_state(over_budget: Any) -> dict[str, Any]:
    """A second turn carrying one product from the answer before it."""
    state = run_state(coverage=[], products={over_budget.product_id: over_budget})
    state["searches"] = []
    state["search_event_ids"] = []
    state["context_product_ids"] = [over_budget.product_id]
    state["execution_path"] = "focused_follow_up"
    return state


@pytest.fixture()
def over_budget():
    return product(202).model_copy(update={"price_cents": OVER_BUDGET_CENTS})


def run_search(state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    token = agent_tools._RUN.set(state)
    try:
        return agent_tools.search_products(FOLLOW_UP, limit=4, **kwargs)
    finally:
        agent_tools._RUN.reset(token)


def test_an_empty_tightened_search_drops_the_inherited_product(
    monkeypatch,
    over_budget,
):
    """The reproduced escape.

    The clearing of inherited eligibility used to sit *below* the empty-window
    guard, so a follow-up that tightened the budget and found nothing eligible
    returned early with the previous turn's product still in the pool. The
    recovery path then selected it and the finalizer recommended it, at the
    price the participant had just excluded.
    """
    _install_retrieval(
        monkeypatch,
        [search_response(FOLLOW_UP, coverage=grounded(), results=[])],
    )
    state = follow_up_state(over_budget)

    result = run_search(state, max_price_cents=BUDGET_CENTS)

    assert result["ok"] is False
    assert state["products"] == {}
    assert agent_tools._fallback_product_ids(state) == []


def test_a_failed_tightened_search_drops_the_inherited_product(
    monkeypatch,
    over_budget,
):
    """The same rule for the error outcome, which returns even earlier."""

    def explode(_request):
        raise TimeoutError("statement timeout")

    monkeypatch.setattr(agent_tools, "_search_with_telemetry", explode)
    state = follow_up_state(over_budget)

    result = run_search(state, max_price_cents=BUDGET_CENTS)

    assert result["ok"] is False
    assert state["products"] == {}
    assert agent_tools._fallback_product_ids(state) == []


def test_synthesis_refuses_a_product_no_successful_search_returned(
    monkeypatch,
    over_budget,
):
    """The boundary assertion, independent of how the product got into state.

    `finalize_retrieved_answer` is reached by the model's own tool and by the
    controller's recovery, so the rule is asserted where they meet rather than
    at each caller. A turn that searched and came back empty has no eligible
    product, and saying so is the answer; recommending yesterday's is not.
    """
    _install_retrieval(
        monkeypatch,
        [search_response(FOLLOW_UP, coverage=grounded(), results=[])],
    )
    state = follow_up_state(over_budget)
    run_search(state, max_price_cents=BUDGET_CENTS)
    # Put it back the way only a stale pool could, and force the selection.
    state["products"][over_budget.product_id] = over_budget

    token = agent_tools._RUN.set(state)
    try:
        with pytest.raises(RuntimeError, match="No retrieved products"):
            agent_tools.finalize_retrieved_answer(
                FOLLOW_UP,
                product_ids=[over_budget.product_id],
            )
    finally:
        agent_tools._RUN.reset(token)


def test_a_follow_up_that_never_searched_keeps_its_products(over_budget):
    """The case the rule must not break.

    "Tell me more about that one" issues no retrieval, so nothing has
    invalidated the products already in hand and they stay citable. The rule is
    keyed on whether this turn attempted a retrieval, not on whether products
    were inherited.
    """
    state = follow_up_state(over_budget)

    assert agent_tools._retrieval_attempted(state) is False
    assert agent_tools._fallback_product_ids(state) == [over_budget.product_id]
