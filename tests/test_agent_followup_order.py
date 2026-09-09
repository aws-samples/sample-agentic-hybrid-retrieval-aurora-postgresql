"""A saved answer may reorder synthesis inputs without changing its product scope."""

from contextlib import contextmanager
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from test_synthesis_claims import product

from service import agent_tools
from service.models import AgentConversationContext


@pytest.fixture
def saved_answer(monkeypatch):
    session_id, run_id, search_id = uuid4(), uuid4(), uuid4()
    products = {i: product(product_id=i, title=f"Headphone {i}", model=f"HP-{i}") for i in (1, 2, 3)}
    identities = [
        {key: getattr(products[i], key) for key in ("product_id", "title", "model")}
        for i in (2, 1, 3)
    ]
    row = {
        "agent_session_id": session_id,
        "user_message": "Headphones for clear calls",
        "input_payload": {"product_ids": [1, 2, 3]},
        "extracted_intent": {
            "selected_products": [products[i].model_dump(mode="json") for i in (2, 1, 3)],
            "search_event_ids": [str(search_id)],
        },
    }
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = row
    connection.execute.return_value.fetchall.side_effect = [
        [{"search_event_id": search_id}],
        [{"product_id": i} for i in (1, 2, 3)],
    ]

    @contextmanager
    def connect():
        yield connection

    hydrate = MagicMock(side_effect=lambda ids: [products[i] for i in ids])
    monkeypatch.setattr(agent_tools, "connect", connect)
    monkeypatch.setattr(agent_tools, "get_product_summaries", hydrate)
    monkeypatch.setattr(agent_tools, "signals_from_receipt", lambda receipt: {"product_id": receipt["product_id"]})
    context = AgentConversationContext(
        previous_agent_run_id=run_id,
        previous_question=row["user_message"],
        recommendations=identities,
    )
    return context, row, hydrate


@pytest.mark.parametrize("selection_order", [[1, 2, 3], [3, 1, 2], [2, 1, 3]])
def test_followup_preserves_answer_order_independent_of_synthesis_order(saved_answer, selection_order):
    context, row, hydrate = saved_answer
    row["input_payload"]["product_ids"] = selection_order
    session_id, products, events = agent_tools._load_conversation_context(context)
    assert session_id == row["agent_session_id"]
    assert [item.product_id for item in products] == [2, 1, 3]
    assert len(events) == 1
    hydrate.assert_called_once_with([2, 1, 3])


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate", "reordered", "renamed", "scope_changed"])
def test_followup_rejects_changed_answer_or_scope_before_hydrating(saved_answer, change):
    context, row, hydrate = saved_answer
    if change == "missing":
        context.recommendations.pop()
    elif change == "extra":
        context.recommendations.append(context.recommendations[0].model_copy(update={"product_id": 99}))
    elif change == "duplicate":
        context.recommendations.append(context.recommendations[0])
    elif change == "reordered":
        context.recommendations.reverse()
    elif change == "renamed":
        context.recommendations[0].title = "A different product"
    else:
        row["input_payload"]["product_ids"] = [1, 2, 99]
    with pytest.raises(agent_tools.ConversationContextError):
        agent_tools._load_conversation_context(context)
    hydrate.assert_not_called()
