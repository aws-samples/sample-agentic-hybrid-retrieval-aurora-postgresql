"""A refused answer must recover by fixing what was wrong, never by loosening a check.

Measured on a fresh event (8 November 2026): Alex's setup request failed after every
draft was refused. One refusal was the claim reviewer quoting a record its passage did
not cite, a broken review rather than a wrong draft, yet the draft was thrown away. The
agent's retry and the controller fallback then drafted again without being told why the
earlier drafts were refused.
"""

import json
import re
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from claim_review_helpers import supported_review
from test_agent_coverage_decline import run_state
from test_synthesis_claims import evidence, product

from service import agent_tools
from service.claim_review import ClaimReviewError, assess_claim_support
from service.synthesis import (
    DRAFT_REPAIRS,
    SynthesisOutputError,
    synthesize_cited_answer,
)

ANSWER = "AuriLogic Flight ANC has 48 hours of battery life [1]."
RECORDS = [evidence("Battery life 48 hours."), evidence("Unrelated 100 Hz display.")]
SETTINGS = SimpleNamespace(synthesis_model_id="test", aws_region="us-east-1")
# One review, plus one corrected review when the first breaks its own rules.
REVIEW_CALLS = 2


def outside_citations(response):
    response["output"]["message"]["content"][0]["toolUse"]["input"]["passages"][0][
        "support"
    ] = [{"number": 2, "quote": "Unrelated 100 Hz display."}]


def misquoted(response):
    response["output"]["message"]["content"][0]["toolUse"]["input"]["passages"][0][
        "support"
    ] = [{"number": 1, "quote": "Battery life 100 hours."}]


def without_quote(response):
    response["output"]["message"]["content"][0]["toolUse"]["input"]["passages"][0][
        "support"
    ] = []


def duplicated(response):
    passages = response["output"]["message"]["content"][0]["toolUse"]["input"][
        "passages"
    ]
    passages.append(passages[0])


def truncated(response):
    response["stopReason"] = "max_tokens"


def malformed(response):
    response["output"]["message"]["content"][0]["toolUse"]["input"] = {"passages": []}


def unsupported(response):
    passage = response["output"]["message"]["content"][0]["toolUse"]["input"][
        "passages"
    ][0]
    passage.update(verdict="unsupported", support=[], reason="The record says 24 hours")


class Reviewer:
    """Answers record_claim_support calls, spoiling the first `faults` of them."""

    def __init__(self, fault, faults=1, draft=ANSWER):
        self.fault, self.faults, self.draft = fault, faults, draft
        self.reviews, self.drafts = [], []

    def converse(self, **request):
        tool = request.get("toolConfig", {}).get("tools", [{}])[0].get("toolSpec", {})
        if tool.get("name") == "record_answerability":
            return {
                "stopReason": "tool_use",
                "output": {
                    "message": {
                        "content": [
                            {
                                "toolUse": {
                                    "name": "record_answerability",
                                    "input": {
                                        "request_supported": True,
                                        "reason": "supported",
                                        "products": [
                                            {
                                                "product_id": 1,
                                                "supported": True,
                                                "evidence_ids": [1],
                                            }
                                        ],
                                    },
                                }
                            }
                        ]
                    }
                },
                "usage": {},
            }
        response = supported_review(request)
        if response is None:
            self.drafts.append(request)
            return {
                "stopReason": "end_turn",
                "output": {"message": {"content": [{"text": self.draft}]}},
                "usage": {"inputTokens": 5, "outputTokens": 3},
            }
        self.reviews.append(request)
        response["usage"] = {"inputTokens": 11, "outputTokens": 7}
        if len(self.reviews) <= self.faults:
            self.fault(response)
        return response


def review(client):
    return assess_claim_support(
        ANSWER, "Battery life?", [product()], RECORDS, client=client, model_id="test"
    )


RULE_BREAKS = [
    outside_citations,
    misquoted,
    without_quote,
    duplicated,
    truncated,
    malformed,
]


@pytest.mark.parametrize("fault", RULE_BREAKS)
def test_a_review_that_breaks_its_rules_is_corrected_not_charged_to_the_draft(fault):
    client = Reviewer(fault)
    receipt, usage = review(client)

    assert len(client.reviews) == 2
    assert receipt["passages"][0]["verdict"] == "supported"
    assert usage == {"inputTokens": 22, "outputTokens": 14, "reviewCalls": 2}
    first, second = (r["messages"][0]["content"] for r in client.reviews)
    assert second[0] == first[0], "the corrected review judges the same draft"
    assert "rejected an earlier review" in second[-1]["text"]
    assert "claim support:" in second[-1]["text"], "it is told which rule it broke"


@pytest.mark.parametrize("fault", RULE_BREAKS)
def test_a_review_that_breaks_its_rules_twice_fails_closed(fault):
    client = Reviewer(fault, faults=REVIEW_CALLS)
    with pytest.raises(ClaimReviewError) as caught:
        review(client)

    assert len(client.reviews) == REVIEW_CALLS
    assert caught.value.verdict is False
    assert caught.value.usage == {
        "inputTokens": 22,
        "outputTokens": 14,
        "reviewCalls": 2,
    }


def test_an_unsupported_verdict_refuses_the_draft_without_a_second_review():
    client = Reviewer(unsupported)
    with pytest.raises(ClaimReviewError, match="24 hours") as caught:
        review(client)

    assert len(client.reviews) == 1
    assert caught.value.verdict is True
    assert caught.value.usage == {
        "inputTokens": 11,
        "outputTokens": 7,
        "reviewCalls": 1,
    }


def test_a_corrected_review_delivers_the_draft_without_writing_another():
    client = Reviewer(outside_citations)
    answer, _, usage = synthesize_cited_answer(
        "What is the battery life?",
        [product()],
        RECORDS[:1] + [RECORDS[1].model_copy(update={"evidence_id": 2})],
        client=client,
        settings=SETTINGS,
    )

    assert answer == ANSWER
    assert len(client.drafts) == 1
    assert usage["attempts"] == 1
    assert usage["claim_review_usage"]["reviewCalls"] == 2


def draft_text(request):
    return "\n".join(block["text"] for block in request["messages"][0]["content"])


def test_earlier_refusals_reach_the_first_draft_and_its_repairs():
    client = Reviewer(unsupported, faults=DRAFT_REPAIRS + 1)
    refusal = (
        "Synthesized claim naming product 1 does not cite evidence for that product"
    )
    with pytest.raises(SynthesisOutputError):
        synthesize_cited_answer(
            "What is the battery life?",
            [product()],
            RECORDS[:1],
            client=client,
            settings=SETTINGS,
            earlier_refusals=[refusal, refusal],
        )

    assert len(client.drafts) == DRAFT_REPAIRS + 1
    for request in client.drafts:
        assert draft_text(request).count(refusal) == 1, "each reason is named once"
    first = client.drafts[0]["messages"][0]["content"]
    assert json.loads(first[0]["text"].split("Numbered evidence records:\n")[1])


def test_a_draft_refused_twice_is_repaired_inside_the_same_call():
    """A refusal the caller sees costs the agent a turn; two repairs come first."""
    client = Reviewer(unsupported, faults=DRAFT_REPAIRS)

    answer, _, usage = synthesize_cited_answer(
        "What is the battery life?",
        [product()],
        RECORDS[:1],
        client=client,
        settings=SETTINGS,
    )

    assert answer == ANSWER
    assert len(client.drafts) == DRAFT_REPAIRS + 1
    assert usage["claim_review_usage"]["reviewCalls"] == DRAFT_REPAIRS + 1
    roles = [message["role"] for message in client.drafts[-1]["messages"]]
    assert roles == ["user", "assistant", "user", "assistant", "user"]
    assert (
        "The record says 24 hours"
        in client.drafts[-1]["messages"][-1]["content"][0]["text"]
    )


def test_a_first_draft_without_earlier_refusals_is_unchanged():
    client = Reviewer(lambda response: None)
    synthesize_cited_answer(
        "What is the battery life?",
        [product()],
        RECORDS[:1],
        client=client,
        settings=SETTINGS,
    )

    assert len(client.drafts[0]["messages"][0]["content"]) == 1
    assert "refused earlier drafts" not in draft_text(client.drafts[0])


@pytest.fixture
def refused_state():
    picks = {
        i: product(product_id=i, title=f"Pick {i}", model=f"P-{i}") for i in (1, 2)
    }
    state = run_state(coverage=[], products=picks)
    state["trace"] = [
        {"tool": "compare_products", "arguments": {"product_ids": [1, 2]}}
    ]
    state["evidence"] = {
        i: evidence("Supported specification.").model_copy(
            update={"product_id": i, "evidence_id": i}
        )
        for i in (1, 2)
    }
    state["evidence_by_product"] = {1: [1], 2: [2]}
    return state


@pytest.mark.parametrize("fallback", [False, True])
def test_a_refusal_reaches_the_next_draft_by_the_agent_or_the_fallback(
    monkeypatch, refused_state, fallback
):
    refusal = (
        "Synthesized claim naming product 2 does not cite evidence for that product"
    )
    synthesis = Mock(side_effect=SynthesisOutputError(refusal))
    monkeypatch.setattr(agent_tools, "synthesize_answer", synthesis)
    token = agent_tools._RUN.set(refused_state)
    try:
        failed = agent_tools.synthesize_cited_answer(refused_state["question"], [1, 2])
        assert failed["ok"] is False
        assert synthesis.call_args.kwargs["earlier_refusals"] == ()
        synthesis.side_effect = None
        synthesis.return_value = ("Pick 1 fits [1]; Pick 2 also fits [2].", [], {})
        if fallback:
            agent_tools.finalize_retrieved_answer(refused_state["question"])
        else:
            retry = agent_tools.synthesize_cited_answer(
                refused_state["question"], [1, 2]
            )
            assert retry["ok"] is True
    finally:
        agent_tools._RUN.reset(token)

    assert synthesis.call_args.kwargs["earlier_refusals"] == [refusal]
    assert refused_state["answer_of_record"] is not None


def cited_advice(response):
    passage = response["output"]["message"]["content"][0]["toolUse"]["input"][
        "passages"
    ][0]
    passage.update(verdict="non_claim", support=[], reason="Advice to the shopper.")


def uncited_non_claim_with_quote(response):
    passages = response["output"]["message"]["content"][0]["toolUse"]["input"][
        "passages"
    ]
    passages[1].update(
        verdict="non_claim",
        support=[{"number": 1, "quote": "Battery life 48 hours."}],
        reason="A heading.",
    )


def test_a_cited_sentence_that_states_no_fact_refuses_the_draft_and_names_it():
    client = Reviewer(cited_advice)
    with pytest.raises(ClaimReviewError) as caught:
        review(client)

    assert len(client.reviews) == 1, "the draft is at fault, not the review"
    assert caught.value.verdict is True
    message = str(caught.value)
    assert "passage 1 cites [1] but states no product fact" in message
    assert ANSWER in message
    assert "without citations" in message


def test_a_non_claim_with_quotes_is_a_review_rule_break_and_is_corrected():
    answer = ANSWER + "\nCheck your laptop's charging needs."
    client = Reviewer(uncited_non_claim_with_quote)
    receipt, _ = assess_claim_support(
        answer, "Battery life?", [product()], RECORDS, client=client, model_id="test"
    )

    assert len(client.reviews) == 2
    assert (
        "passage 2 is a non-claim with supporting quotes"
        in (client.reviews[1]["messages"][0]["content"][-1]["text"])
    )
    assert [p["verdict"] for p in receipt["passages"]] == ["supported", "non_claim"]


@pytest.mark.parametrize(
    ("fault", "named"),
    [
        (outside_citations, "passage 1 cites [1] but quotes record 2"),
        (misquoted, "passage 1: the quote is not in record 1"),
        (without_quote, "passage 1 is marked supported without a source quote"),
    ],
)
def test_each_review_rule_break_names_its_passage(fault, named):
    client = Reviewer(fault, faults=REVIEW_CALLS)
    with pytest.raises(ClaimReviewError, match=re.escape(named)):
        review(client)
