"""A citation can resolve perfectly while the sentence it sits in is false.

Citation resolution, evidence authorization and factual support are three
different questions, and this file covers only the third. Every case drives the
production validator, `service.synthesis._validated_output`, with the shape a
real draft arrives in.
"""

from __future__ import annotations

import pytest

from service.models import EvidenceRecord, ProductSummary
from service.synthesis import SynthesisOutputError, _validated_output

BATTERY_EVIDENCE = "Battery life 48 hours of playback on a single charge."
RATING_EVIDENCE = "Weight 68 grams. Water rating IP55."


def product(**overrides) -> ProductSummary:
    fields = {
        "product_id": 1,
        "sku": "AL-FANC-1",
        "title": "AuriLogic Flight ANC",
        "short_description": "Over-ear ANC headphones",
        "domain": "electronics",
        "category_key": "headphones",
        "category_path": "Electronics > Headphones",
        "brand": "AuriLogic",
        "model": "Flight ANC",
        "price_cents": 17_999,
        "list_price_cents": 19_999,
        "review_count": 12,
        "availability": "in_stock",
        "inventory_count": 5,
        "attributes": {},
        "tags": [],
    }
    return ProductSummary(**{**fields, **overrides})


def evidence(text: str, title: str = "Specification sheet") -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=1,
        product_id=1,
        evidence_type="specification",
        source_name="AuriLogic",
        source_uri="https://example.invalid/spec",
        revision="r1",
        title=title,
        text=text,
    )


def validate(answer: str, records, products=None) -> None:
    _validated_output(
        {
            "stopReason": "end_turn",
            "output": {"message": {"content": [{"text": answer}]}},
        },
        products if products is not None else [product()],
        records,
    )


def test_an_uncited_sentence_cannot_ride_on_the_citation_before_it():
    """The citation resolves; the sentence after it is invented.

    The validator skipped any sentence without a citation marker, so one
    correctly cited sentence authorized every claim that followed it.
    """
    with pytest.raises(SynthesisOutputError, match="999"):
        validate(
            "AuriLogic Flight ANC is a good fit [1]. It has 999-hour battery life.",
            [evidence(BATTERY_EVIDENCE)],
        )


def test_the_same_figure_in_a_different_unit_is_not_support():
    """48 hours of playback does not make a 48-year warranty."""
    with pytest.raises(SynthesisOutputError, match="48"):
        validate(
            "AuriLogic Flight ANC has a 48-year warranty [1].",
            [evidence(BATTERY_EVIDENCE)],
        )


def test_an_identifier_is_supported_only_by_itself():
    """`IP68` is not 68 grams, and it is not IP55."""
    with pytest.raises(SynthesisOutputError, match="IP68"):
        validate(
            "AuriLogic Flight ANC is IP68 rated [1].",
            [evidence(RATING_EVIDENCE)],
        )


def test_an_availability_claim_is_decided_against_the_catalog_field():
    """ "in stock" is a substring of "not in stock", so prose cannot decide it."""
    with pytest.raises(SynthesisOutputError, match="in stock"):
        validate(
            "AuriLogic Flight ANC is in stock [1].",
            [evidence("Currently not in stock.")],
            [product(availability="out_of_stock")],
        )


@pytest.mark.parametrize("written", ["48h", "48 hours", "48-hour"])
def test_the_same_measurement_written_differently_still_passes(written: str):
    """The rule is unit identity, not string identity.

    A validator that only accepted the record's exact spelling would reject
    true answers, which is a worse failure here than the one being fixed: the
    participant would be shown a fail-closed error for a correct draft.
    """
    validate(
        f"AuriLogic Flight ANC gives {written} of playback [1].",
        [evidence(BATTERY_EVIDENCE)],
    )


def test_a_true_availability_claim_passes():
    validate(
        "AuriLogic Flight ANC is in stock [1].",
        [evidence("Ships today.")],
        [product(availability="in_stock")],
    )


def test_an_uncited_count_is_not_a_product_claim():
    """The false-positive this rule must not reintroduce.

    A bare number in an uncited sentence carries no unit and names no
    attribute, so no evidence record can confirm or refute it. Demanding
    support for it is how the validator has rejected correct answers before,
    and a fail-closed error on a good draft costs the participant more than a
    permissive count does.
    """
    validate(
        "AuriLogic Flight ANC gives 48 hours of playback [1]. "
        "Here are 3 options worth comparing.",
        [evidence(BATTERY_EVIDENCE)],
    )
