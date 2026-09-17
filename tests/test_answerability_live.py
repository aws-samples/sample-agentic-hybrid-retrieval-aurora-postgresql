"""Exercise the semantic review against real Aurora evidence and the active model."""

import json

import pytest

from service.answerability import assess_answerability
from service.bedrock import get_bedrock_client
from service.catalog import get_product_evidence_records, get_product_summaries
from service.config import get_settings
from service.retrieval import get_retrieval_service


@pytest.fixture(scope="module")
def real_sources():
    question = "Find noise cancelling headphones under $200"
    products = get_product_summaries([2, 5])
    assert {product.product_id for product in products} == {2, 5}
    embedding = get_retrieval_service().embed_query(question)
    evidence = [
        record
        for product in products
        for record in get_product_evidence_records(
            product.product_id, question, embedding
        )
    ]
    assert evidence, "the live answerability witness requires fresh Aurora evidence"
    return products, evidence


@pytest.mark.aurora
@pytest.mark.parametrize(
    "question,supported",
    [
        ("Find noise cancelling headphones under $200", True),
        ("Compare the battery life of these headphones", True),
        ("What is the capital of France?", False),
        ("What is two plus two?", False),
        ("Find me a used Toyota Camry under $15,000 near me", False),
        ("I need a replacement charging brick for model A2342", False),
        ("Will these work with model A2342?", False),
        ("Find headphones and a used Toyota Camry near me", False),
    ],
)
def test_current_intent_and_evidence_agree_live(real_sources, question, supported):
    products, evidence = real_sources
    settings = get_settings()
    review, usage = assess_answerability(
        json.dumps(
            {
                "current_request": question,
                "previous_request_for_reference_resolution_only": "Find noise cancelling headphones under $200",
            }
        ),
        products,
        evidence,
        client=get_bedrock_client("bedrock-runtime", settings.aws_region),
        model_id=settings.synthesis_model_id,
    )
    assert usage.get("outputTokens", 0) > 0, "the managed review never executed"
    assert review.request_supported is supported, (
        f"answerability: {question!r} returned {review.model_dump()}; "
        "inspect current intent and its source evidence before allowing a product answer"
    )


@pytest.mark.aurora
@pytest.mark.parametrize(
    "question,supported",
    [
        ("What do the specs and reviews say about OH-M349?", True),
        ("What do reviews say about the microphone on OH-M349?", True),
        ("Compare the specifications with customer experiences for OH-M349", True),
        (
            "Recommend OH-M349 only if customer reviews confirm clear calls in noisy rooms",
            False,
        ),
    ],
)
def test_missing_reviews_allow_source_limits_not_invented_endorsements(
    question, supported
):
    products = get_product_summaries([11192])
    evidence = get_product_evidence_records(
        11192, question, get_retrieval_service().embed_query(question)
    )
    assert evidence and {record.evidence_type for record in evidence} == {
        "product_spec"
    }
    settings = get_settings()
    review, usage = assess_answerability(
        json.dumps(
            {
                "current_request": question,
                "previous_request_for_reference_resolution_only": "Headphones for clearer calls at home",
            }
        ),
        products,
        evidence,
        client=get_bedrock_client("bedrock-runtime", settings.aws_region),
        model_id=settings.synthesis_model_id,
    )
    assert usage.get("outputTokens", 0) > 0
    assert review.request_supported is supported, review.model_dump()
