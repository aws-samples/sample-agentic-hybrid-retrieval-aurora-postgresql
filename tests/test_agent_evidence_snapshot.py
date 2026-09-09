"""Source comparison must show the evidence read by this run, including uncited records."""

from test_agent_coverage_decline import run_state
from test_synthesis_claims import evidence, product

from service.agent import ProductDiscoveryAgent
from service.agent_tools import _persisted_intent
from service.models import AgentCitation, AgentRequest


def test_response_and_saved_turn_keep_uncited_source_snapshots():
    specification = evidence("Has a microphone.")
    review = evidence("Fit depends on your setup.").model_copy(
        update={
            "evidence_id": 2,
            "evidence_type": "verified_review",
            "revision": "review-r1",
        }
    )
    state = run_state(coverage=[], products={1: product()})
    state["evidence"] = {1: specification, 2: review}
    state["answer_of_record"] = {
        "answer": "Has a microphone [1].",
        "recommendations": [product()],
        "citations": [
            AgentCitation(
                number=1,
                evidence_id=1,
                product_id=1,
                evidence_type="product_spec",
                source_uri=specification.source_uri,
                revision=specification.revision,
                title=specification.title,
                quote=specification.text,
            )
        ],
        "usage": {},
    }
    response = ProductDiscoveryAgent()._response(
        AgentRequest(question=state["question"]), state, None, None
    )
    assert [item.evidence_id for item in response.retrieved_evidence] == [1, 2]
    assert [item.evidence_id for item in response.citations] == [1]
    persisted = _persisted_intent(state, state["answer_of_record"], [], {})
    assert persisted["retrieved_evidence"][1]["revision"] == "review-r1"
    assert persisted["retrieved_evidence"][1]["text"] == review.text
