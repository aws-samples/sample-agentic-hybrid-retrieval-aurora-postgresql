"""A real citation must not authorize an irrelevant product pitch."""

import json
from types import SimpleNamespace

import pytest
from test_synthesis_claims import evidence, product

from service.synthesis import synthesize_cited_answer


class Client:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        text = (
            json.dumps(self.decision)
            if len(self.calls) == 1
            else "AuriLogic Flight ANC has active noise cancellation [1]."
        )
        return {
            "stopReason": "end_turn",
            "output": {"message": {"content": [{"text": text}]}},
            "usage": {"inputTokens": 10, "outputTokens": 10},
        }


def decision(*, supported=True, reason="supported", ids=None):
    return {
        "request_supported": supported,
        "reason": reason,
        "products": [
            {
                "product_id": 1,
                "supported": supported,
                "evidence_ids": [1] if ids is None else ids,
            }
        ],
    }


def run(client, question="Find noise cancelling headphones"):
    return synthesize_cited_answer(
        question,
        [product()],
        [evidence("Active noise cancellation. Bluetooth connectivity.")],
        client=client,
        settings=SimpleNamespace(synthesis_model_id="test", aws_region="us-east-1"),
    )


@pytest.mark.parametrize(
    "question,reason",
    [
        ("What is the capital of France?", "unrelated_request"),
        ("Find me a used Toyota Camry under $15,000 near me", "unrelated_request"),
        ("Will these work with model A2342?", "unsupported_requirements"),
        (
            "I need a replacement charging brick for model A2342",
            "unsupported_requirements",
        ),
    ],
)
def test_unsupported_current_intent_never_reaches_shopping_synthesis(question, reason):
    client = Client(decision(supported=False, reason=reason))
    with pytest.raises(ValueError, match="answerability"):
        run(client, question)
    assert len(client.calls) == 1, "unsupported request reached the shopping model"


def test_supported_request_has_separate_review_and_synthesis_witnesses():
    client = Client(decision())
    answer, citations, usage = run(client)
    assert "noise cancellation" in answer
    assert citations[0].evidence_id == 1
    assert len(client.calls) == 2
    assert usage["answerability"]["request_supported"] is True


@pytest.mark.parametrize(
    "bad",
    [
        decision(ids=[999]),
        {**decision(), "products": []},
        {**decision(), "products": [{**decision()["products"][0], "product_id": 999}]},
        {**decision(), "request_supported": "true"},
        {**decision(), "reason": "unrelated_request"},
    ],
)
def test_malformed_or_unwitnessed_allow_decisions_fail_closed(bad):
    client = Client(bad)
    with pytest.raises(ValueError, match="answerability"):
        run(client)
    assert len(client.calls) == 1


@pytest.mark.parametrize("fallback", [False, True])
def test_both_finalizers_bind_original_intent_and_drop_cards(monkeypatch, fallback):
    from test_agent_coverage_decline import run_state

    from service import agent_tools
    from service.answerability import Answerability, SynthesisDeclined

    state = run_state(coverage=[], products={1: product()})
    state.update(
        question="What is the capital of France?",
        previous_question="Find noise cancelling headphones",
        searches=[],
        evidence={1: evidence("Active noise cancellation.")},
        evidence_by_product={1: [1]},
        trace=[],
    )
    witnessed = []

    def reviewed(question, products, records):
        witnessed.append(json.loads(question))
        raise SynthesisDeclined(
            Answerability.model_validate(
                decision(supported=False, reason="unrelated_request")
            ),
            {"inputTokens": 10},
        )

    monkeypatch.setattr(agent_tools, "synthesize_answer", reviewed)
    token = agent_tools._RUN.set(state)
    try:
        if fallback:
            agent_tools.finalize_retrieved_answer(
                "Recommend these headphones", product_ids=[1]
            )
        else:
            result = agent_tools.synthesize_cited_answer(
                "Recommend these headphones", [1]
            )
            assert result["ok"] is True
            saved = state["answer_of_record"]
            replay = agent_tools.synthesize_cited_answer("Try a different answer", [1])
            assert replay["answer"] == saved["answer"]
            assert state["answer_of_record"] is saved
    finally:
        agent_tools._RUN.reset(token)
    assert witnessed == [
        {
            "current_request": state["question"],
            "previous_request_for_reference_resolution_only": state[
                "previous_question"
            ],
        }
    ]
    assert state["answer_of_record"]["outcome"] == "declined"
    assert state["answer_of_record"]["recommendations"] == []
    assert state["answer_of_record"]["citations"] == []
    assert state["trace"][-1]["outcome"] == "denied"
    assert state["trace"][-1]["tool"] == "synthesize_cited_answer"


@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize("runtime_error", [False, True])
def test_no_product_turn_declines_but_runtime_failure_still_fails(
    monkeypatch, streamed, runtime_error
):
    import asyncio

    from test_agent_coverage_decline import _install_run, run_state

    from service.agent import ProductDiscoveryAgent
    from service.models import AgentRequest

    state = run_state(coverage=[], products={})
    state.update(products={}, searches=[], trace=[])
    _install_run(monkeypatch, state)
    witnessed = []

    class Model:
        async def invoke_async(self, prompt):
            witnessed.append("model")
            if runtime_error:
                raise RuntimeError("simulated orchestration failure")
            return SimpleNamespace(metrics={})

        async def stream_async(self, prompt):
            yield {"result": await self.invoke_async(prompt)}

    monkeypatch.setattr("service.agent.build_agent", Model)
    agent = ProductDiscoveryAgent()
    request = AgentRequest(question="What is the capital of France?")
    if streamed:
        events = []

        async def collect():
            async for item in agent.stream(request):
                events.append(item)

        if runtime_error:
            with pytest.raises(RuntimeError):
                asyncio.run(collect())
            assert any("agent_failure" in event for event in events)
        else:
            asyncio.run(collect())
    elif runtime_error:
        with pytest.raises(RuntimeError):
            agent.answer(request)
    else:
        assert agent.answer(request).outcome == "declined"
    assert witnessed == ["model"]
    if runtime_error:
        assert state["answer_of_record"] is None
    else:
        assert state["answer_of_record"]["outcome"] == "declined"
        assert state["answer_of_record"]["recommendations"] == []


def test_review_cannot_borrow_another_products_evidence():
    from service.answerability import assess_answerability

    response = decision()
    response["products"].append(
        {"product_id": 2, "supported": True, "evidence_ids": [1]}
    )
    client = Client(response)
    with pytest.raises(ValueError, match="answerability: evidence scope for product 2"):
        assess_answerability(
            "Compare these headphones",
            [product(), product(product_id=2)],
            [
                evidence("Noise cancellation"),
                evidence("Bluetooth").model_copy(
                    update={"evidence_id": 2, "product_id": 2}
                ),
            ],
            client=client,
            model_id="test",
        )
    assert len(client.calls) == 1
