"""False claims must fail even when their citations resolve to the right product."""

import json

import pytest
from test_synthesis_claims import evidence, product, validate

from service.claim_review import ClaimReview, ClaimReviewError, validate_review
from service.synthesis import SynthesisOutputError, synthesize_cited_answer


@pytest.mark.parametrize(
    ("source", "claim"),
    [
        ("Battery life 48 hours.", "has one hundred hours of battery life"),
        (
            "Display refresh rate 90 Hz. Microphone frequency response not stated.",
            "has a microphone frequency response of 90 Hz",
        ),
    ],
)
def test_a_number_needs_its_property_not_just_a_citation(source, claim):
    with pytest.raises(SynthesisOutputError, match="unsupported numeric claim"):
        validate(f"AuriLogic Flight ANC {claim} [1].", [evidence(source)])


@pytest.mark.parametrize(
    ("source", "claim"),
    [
        ("Battery life 48 hours.", "has forty-eight hours of battery life"),
        ("Battery life forty eight hours.", "has 48 hours of battery life"),
        (
            "Microphone frequency response 90 Hz.",
            "has a microphone frequency response of 90 Hz",
        ),
        ("Display refresh rate 90 Hz.", "has a display refresh rate of 90 Hz"),
    ],
)
def test_supported_measurements_still_pass(source, claim):
    validate(f"AuriLogic Flight ANC {claim} [1].", [evidence(source)])


def support_decision(**changes):
    return {
        "id": 1,
        "verdict": "supported",
        "support": [{"number": 1, "quote": "Battery life 48 hours."}],
        "reason": "The record states the measurement.",
        **changes,
    }


@pytest.mark.parametrize(
    "decisions",
    [
        [support_decision(id=2)],
        [support_decision(), support_decision()],
        [support_decision(support=[])],
        [support_decision(support=[{"number": 2, "quote": "Battery life 48 hours."}])],
        [support_decision(support=[{"number": 1, "quote": "Battery life 100 hours."}])],
        [support_decision(support=[{"number": 1, "quote": " "}])],
        [support_decision(verdict="non_claim", support=[])],
    ],
)
def test_review_must_cover_the_draft_and_quote_its_citations(decisions):
    with pytest.raises(ClaimReviewError, match="claim support"):
        validate_review(
            ClaimReview.model_validate({"passages": decisions}),
            "Battery life 48 hours [1].",
            [evidence("Battery life 48 hours.")],
        )


def test_valid_review_is_independent_of_unrelated_evidence():
    review = ClaimReview.model_validate({"passages": [support_decision()]})
    validate_review(
        review,
        "Battery life 48 hours [1].",
        [evidence("Battery life 48 hours."), evidence("Unrelated 100 Hz display.")],
    )


@pytest.mark.parametrize(
    "fault", ["truncated", "missing", "duplicate", "wrong_tool", "bad_schema"]
)
def test_incomplete_model_reviews_fail_closed_and_retain_usage(fault):
    from claim_review_helpers import supported_review

    from service.claim_review import assess_claim_support

    class Client:
        def converse(self, **request):
            response = supported_review(request)
            response["usage"] = {"inputTokens": 11, "outputTokens": 7}
            content = response["output"]["message"]["content"]
            if fault == "truncated":
                response["stopReason"] = "max_tokens"
            elif fault == "missing":
                content.clear()
            elif fault == "duplicate":
                content.append(content[0])
            elif fault == "wrong_tool":
                content[0]["toolUse"]["name"] = "another_tool"
            elif fault == "bad_schema":
                content[0]["toolUse"]["input"] = {"passages": []}
            return response

    with pytest.raises(ClaimReviewError) as caught:
        assess_claim_support(
            "Battery life is 48 hours [1].",
            "Battery life?",
            [product()],
            [evidence("Battery life 48 hours.")],
            client=Client(),
            model_id="test",
        )
    # A review that breaks its rules is asked once more; usage covers both calls.
    assert caught.value.usage == {
        "inputTokens": 22,
        "outputTokens": 14,
        "reviewCalls": 2,
    }


def test_successful_synthesis_receipt_names_the_delivered_answer_and_bills_review():
    import hashlib
    from types import SimpleNamespace

    from claim_review_helpers import supported_review

    class Client(DraftClient):
        def converse(self, **request):
            if response := supported_review(request):
                response["usage"] = {"inputTokens": 11, "outputTokens": 7}
                return response
            return super().converse(**request)

    answer, _, usage = synthesize_cited_answer(
        "What is the battery life?",
        [product()],
        [evidence("Battery life 48 hours.")],
        client=Client("AuriLogic Flight ANC has 48 hours of battery life [1]."),
        settings=SimpleNamespace(synthesis_model_id="test", aws_region="us-east-1"),
    )
    assert (
        usage["claim_review"]["answer_sha256"]
        == hashlib.sha256(answer.encode()).hexdigest()
    )
    assert usage["inputTokens"] == 11
    assert usage["outputTokens"] == 7


class DraftClient:
    def __init__(self, answer, verdict="unsupported"):
        self.answer = answer
        self.verdict = verdict
        self.reviews = []

    def converse(self, **request):
        tool = (
            request.get("toolConfig", {})
            .get("tools", [{}])[0]
            .get("toolSpec", {})
            .get("name")
        )
        if tool == "record_answerability":
            decision = {
                "request_supported": True,
                "reason": "supported",
                "products": [{"product_id": 1, "supported": True, "evidence_ids": [1]}],
            }
        elif tool == "record_claim_support":
            payload = json.loads(request["messages"][0]["content"][0]["text"])
            self.reviews.append(payload)
            decision = {
                "passages": [
                    {
                        "id": part["id"],
                        "verdict": self.verdict,
                        "support": [],
                        "reason": "The cited review says the opposite.",
                    }
                    for part in payload["passages"]
                ]
            }
        else:
            return {
                "stopReason": "end_turn",
                "output": {"message": {"content": [{"text": self.answer}]}},
                "usage": {},
            }
        return {
            "stopReason": "tool_use",
            "output": {
                "message": {"content": [{"toolUse": {"name": tool, "input": decision}}]}
            },
            "usage": {},
        }


@pytest.mark.parametrize(
    ("source", "claim"),
    [
        (
            "The headset was uncomfortable and hurt my ears.",
            "is comfortable for all-day wear according to the reviewer",
        ),
        ("Battery life 48 hours.", "supports your laptop"),
        (
            "Battery life 48 hours.",
            "guarantees perfectly clear calls in every noisy office",
        ),
    ],
)
def test_finished_draft_must_pass_semantic_support_review(source, claim):
    from types import SimpleNamespace

    client = DraftClient(f"AuriLogic Flight ANC {claim} [1].")
    with pytest.raises(SynthesisOutputError, match="claim support"):
        synthesize_cited_answer(
            "What do the supplied sources say?",
            [product()],
            [evidence(source)],
            client=client,
            settings=SimpleNamespace(synthesis_model_id="test", aws_region="us-east-1"),
        )
    assert len(client.reviews) == 2, (
        "both the draft and its replacement must be reviewed"
    )
    assert all(client.answer in str(review["passages"]) for review in client.reviews)
