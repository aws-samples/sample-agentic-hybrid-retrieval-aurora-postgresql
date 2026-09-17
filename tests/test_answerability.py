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
        review = len(self.calls) == 1
        return {
            "stopReason": "tool_use" if review else "end_turn",
            "output": {
                "message": {
                    "content": [
                        {
                            "toolUse": {
                                "name": "record_answerability",
                                "input": self.decision,
                            }
                        }
                        if review
                        else {
                            "text": "AuriLogic Flight ANC has active noise cancellation [1]."
                        }
                    ]
                }
            },
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


def test_review_requires_a_typed_decision_before_synthesis():
    from service.answerability import Answerability

    class CommentaryClient(Client):
        def converse(self, **kwargs):
            response = super().converse(**kwargs)
            if len(self.calls) == 1:
                config = kwargs.get("toolConfig", {})
                if config.get("toolChoice") != {
                    "tool": {"name": "record_answerability"}
                }:
                    response["stopReason"] = "end_turn"
                    response["output"]["message"]["content"] = [
                        {
                            "text": (
                                "The request asks for headphones.\n```json\n"
                                + json.dumps(self.decision)
                                + "\n```"
                            )
                        }
                    ]
                else:
                    schema = Answerability.model_json_schema()
                    schema["properties"]["products"]["items"] = schema.pop("$defs")[
                        "ProductSupport"
                    ]
                    assert (
                        config["tools"][0]["toolSpec"]["inputSchema"]["json"] == schema
                    )
            return response

    client = CommentaryClient(decision())
    answer, citations, _ = run(client)
    assert answer and citations
    assert len(client.calls) == 2
    assert "toolConfig" not in client.calls[1]


@pytest.mark.parametrize(
    "fault", ["text_only", "wrong_tool", "duplicate", "interrupted"]
)
def test_review_rejects_missing_ambiguous_or_interrupted_decisions(fault):
    class InvalidClient(Client):
        def converse(self, **kwargs):
            response = super().converse(**kwargs)
            content = response["output"]["message"]["content"]
            if fault == "text_only":
                content[:] = [{"text": json.dumps(self.decision)}]
            elif fault == "wrong_tool":
                content[0]["toolUse"]["name"] = "skip_review"
            elif fault == "duplicate":
                content.append(content[0])
            else:
                response["stopReason"] = "max_tokens"
            return response

    client = InvalidClient(decision())
    with pytest.raises(ValueError, match="answerability"):
        run(client)
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    "bad,expected_calls",
    [
        (decision(ids=[999]), 1),
        ({**decision(), "products": []}, 2),
        (
            {
                **decision(),
                "products": [{**decision()["products"][0], "product_id": 999}],
            },
            1,
        ),
        ({**decision(), "request_supported": "true"}, 2),
        ({**decision(), "reason": "unrelated_request"}, 1),
    ],
)
def test_malformed_or_unwitnessed_allow_decisions_fail_closed(bad, expected_calls):
    client = Client(bad)
    with pytest.raises(ValueError, match="answerability"):
        run(client)
    assert len(client.calls) == expected_calls
    assert all("toolConfig" in call for call in client.calls)


@pytest.mark.parametrize("recovers", [True, False])
def test_format_retry_is_bounded_and_counts_both_reviews(recovers):
    from service.answerability import AnswerabilityError, assess_answerability

    class FormatClient:
        def __init__(self):
            self.calls = []

        def converse(self, **kwargs):
            self.calls.append(kwargs)
            result = decision()
            if not recovers or len(self.calls) == 1:
                result["products"] = json.dumps({"products": result["products"]})
            return {
                "stopReason": "tool_use",
                "output": {
                    "message": {
                        "content": [
                            {
                                "toolUse": {
                                    "name": "record_answerability",
                                    "input": result,
                                }
                            }
                        ]
                    }
                },
                "usage": {"inputTokens": 11, "outputTokens": 7, "totalTokens": 18},
            }

    client = FormatClient()
    args = ("Find headphones", [product()], [evidence("Noise cancellation")])
    if recovers:
        review, usage = assess_answerability(*args, client=client, model_id="test")
        assert review.request_supported
        assert usage == {"inputTokens": 22, "outputTokens": 14, "totalTokens": 36}
    else:
        with pytest.raises(AnswerabilityError, match="invalid decision"):
            assess_answerability(*args, client=client, model_id="test")
    assert len(client.calls) == 2
    assert client.calls[0]["messages"] == client.calls[1]["messages"]
    assert client.calls[0]["toolConfig"] == client.calls[1]["toolConfig"]


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
