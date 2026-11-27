"""Follow-ups compare against the last answer the shopper actually saw."""

import json
from functools import partial
from types import SimpleNamespace

import pytest
from claim_review_helpers import supported_review
from test_agent_coverage_decline import run_state
from test_recommendation_order import _Writer
from test_synthesis_claims import evidence, product

from service import agent_tools
from service.synthesis import synthesize_cited_answer

PREVIOUS = "My top pick is VELKPRO for your home office [1]."
QUESTION = "I want over-ear headphones under $100. Does that change your pick?"
UNCHANGED = "The budget doesn't change my pick: AUSDOM stays first [1]."
CHANGED = "AUSDOM is my new pick for your budget [1]."


class FollowupWriter(_Writer):
    """Script the model's draft and semantic reading; the application judges the IDs."""

    def __init__(self, pick, drafts, comparisons):
        super().__init__([pick], drafts)
        self.comparisons = iter(comparisons)
        self.review_requests = []

    def converse(self, **request):
        response = supported_review(request)
        if response is None:
            return super().converse(**request)
        self.review_requests.append(request)
        schema = request["toolConfig"]["tools"][0]["toolSpec"]["inputSchema"]["json"]
        if "lead_comparison" in schema["properties"]:
            response["output"]["message"]["content"][0]["toolUse"]["input"][
                "lead_comparison"
            ] = next(self.comparisons)
        return response


@pytest.mark.parametrize("fallback", [False, True])
def test_changed_pick_cannot_be_delivered_as_unchanged(monkeypatch, fallback):
    pick = product(
        product_id=2, title="AUSDOM headphones", brand="AUSDOM", model="AUSDOM"
    )
    state = run_state(coverage=[], products={2: pick})
    state.update(
        question=QUESTION,
        previous_question="Which headphones would you choose for my office?",
        previous_answer={"text": PREVIOUS, "first_product_id": 1},
        evidence={
            2: evidence("AUSDOM over-ear headphones.").model_copy(
                update={"product_id": 2, "evidence_id": 2}
            )
        },
        evidence_by_product={2: [2]},
    )
    writer = FollowupWriter(pick, [UNCHANGED, CHANGED], ["same", "changed"])
    monkeypatch.setattr(
        agent_tools,
        "synthesize_answer",
        partial(
            synthesize_cited_answer,
            client=writer,
            settings=SimpleNamespace(synthesis_model_id="test", aws_region="us-east-1"),
        ),
    )
    with agent_tools.bind_run(state):
        if fallback:
            agent_tools.finalize_retrieved_answer(QUESTION, product_ids=[2])
        else:
            assert agent_tools.synthesize_cited_answer(QUESTION, [2])["ok"]
    record = state["answer_of_record"]
    assert record["answer"] == CHANGED
    assert [p.product_id for p in record["recommendations"]] == [2]
    assert [c.product_id for c in record["citations"]] == [2]
    assert len(writer.review_requests) == 2
    assert PREVIOUS in writer.calls[1]["messages"][0]["content"][-1]["text"]
    reviewed = json.loads(
        writer.review_requests[-1]["messages"][0]["content"][0]["text"]
    )
    assert reviewed["previous_answer"] == state["previous_answer"]
    assert [row["product_id"] for row in reviewed["evidence"]] == [2]


@pytest.mark.parametrize(
    "prior_id, claim, comparison, accepted",
    [
        (2, UNCHANGED, "same", True),
        (2, CHANGED, "changed", False),
        (None, UNCHANGED, "same", False),
        (None, CHANGED, "changed", False),
        (None, "I would choose AUSDOM [1].", "not_stated", True),
    ],
)
def test_followup_only_claims_changes_the_saved_order_can_verify(
    prior_id, claim, comparison, accepted
):
    from service.claim_review import ClaimReviewError, assess_claim_support

    pick = product(product_id=2, title="AUSDOM headphones", model="AUSDOM")
    before = "I recommend AUSDOM [1]." if prior_id else "Here are the headphones [1]."
    reviewer = FollowupWriter(pick, [], [comparison])
    review = partial(
        assess_claim_support,
        claim,
        QUESTION,
        [pick],
        [evidence("AUSDOM headphones.").model_copy(update={"product_id": 2})],
        previous_answer={"text": before, "first_product_id": prior_id},
        client=reviewer,
        model_id="test",
    )
    if accepted:
        receipt, usage = review()
        assert receipt["lead_comparison"] == comparison
        assert usage["reviewCalls"] == 1
    else:
        with pytest.raises(ClaimReviewError) as refusal:
            review()
        assert refusal.value.verdict


def test_followup_review_requires_a_comparison_decision():
    from unittest.mock import Mock

    from service.claim_review import ClaimReviewError, assess_claim_support

    pick = product()
    client = Mock()
    client.converse.side_effect = lambda **request: supported_review(request)
    with pytest.raises(ClaimReviewError, match="complete support schema") as refusal:
        assess_claim_support(
            "This is still my first pick [1].",
            QUESTION,
            [pick],
            [evidence("Headphones.")],
            client=client,
            model_id="test",
            previous_answer={"text": PREVIOUS, "first_product_id": 1},
        )
    assert (
        not refusal.value.verdict
    )  # The review was incomplete, not a supported draft.
    assert client.converse.call_count == 2
