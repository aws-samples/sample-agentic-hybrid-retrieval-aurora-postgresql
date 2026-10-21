"""A citation can resolve perfectly while the sentence it sits in is false.

Citation resolution, evidence authorization and factual support are three
different questions, and this file covers only the third. Every case drives the
production validator, `service.synthesis._validated_output`, with the shape a
real draft arrives in.
"""

from __future__ import annotations

import pytest

from service.models import EvidenceRecord, ProductSummary
from service.synthesis import SynthesisOutputError, _validated_output, reference_name

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


def validate(answer: str, records, products=None, question: str = "") -> None:
    _validated_output(
        {
            "stopReason": "end_turn",
            "output": {"message": {"content": [{"text": answer}]}},
        },
        products if products is not None else [product()],
        records,
        question,
    )


@pytest.mark.parametrize("resolution", ["3840x2160", "3840 × 2160", "3840 x 2160"])
def test_supported_display_resolution_is_one_measurement(resolution):
    monitor = product(title="Mosaic Atelier 32", model="Atelier 32")
    validate(
        f"Mosaic Atelier 32 has a {resolution} display [1].",
        [evidence("Display resolution: 3840x2160.")],
        [monitor],
    )


@pytest.mark.parametrize("resolution", ["3840x1440", "2560x2160"])
def test_resolution_cannot_combine_dimensions_from_different_displays(resolution):
    monitor = product(title="Mosaic Atelier 32", model="Atelier 32")
    with pytest.raises(SynthesisOutputError, match="unsupported numeric claim"):
        validate(
            f"Mosaic Atelier 32 has a {resolution} display [1].",
            [evidence("Display options: 3840x2160 and 2560x1440.")],
            [monitor],
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


@pytest.mark.parametrize(
    "wording",
    [
        "48 hours of recommended daily use",
        "48-hour recommended use",
        "recommended daily use of 48 hours",
    ],
)
@pytest.mark.parametrize("structured", [False, True])
def test_battery_duration_cannot_be_relabelled_as_recommended_use(wording, structured):
    record = evidence(BATTERY_EVIDENCE)
    if structured:
        record = evidence("Catalog specification.").model_copy(
            update={"metadata": {"attributes": {"battery_hours": 48}}}
        )
    with pytest.raises(SynthesisOutputError, match="unsupported numeric claim"):
        validate(f"AuriLogic Flight ANC offers {wording} [1].", [record])


def test_equal_hour_values_keep_their_measurement_meanings():
    answer = "AuriLogic Flight ANC offers 48-hour battery life and 48-hour recommended use [1]."
    with pytest.raises(SynthesisOutputError, match="unsupported numeric claim"):
        validate(answer, [evidence(BATTERY_EVIDENCE)])
    validate(answer, [evidence(BATTERY_EVIDENCE + " Recommended use: 48 hours.")])


def test_recommended_use_cannot_authorize_battery_life():
    with pytest.raises(SynthesisOutputError, match="unsupported numeric claim"):
        validate(
            "AuriLogic Flight ANC offers 12-hour battery life [1].",
            [evidence("Recommended use: 12 hours.")],
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


@pytest.mark.parametrize(
    "sentence",
    [
        "AuriLogic Flight ANC is not in stock [1].",
        "AuriLogic Flight ANC isn't in stock [1].",
        "AuriLogic Flight ANC is no longer in stock [1].",
        "AuriLogic Flight ANC is not currently in stock [1].",
    ],
)
def test_a_negated_availability_claim_is_refuted_by_an_in_stock_product(sentence):
    with pytest.raises(SynthesisOutputError, match="in stock"):
        validate(
            sentence, [evidence("Ships today.")], [product(availability="in_stock")]
        )


def test_a_negated_in_stock_claim_is_refuted_by_low_stock():
    with pytest.raises(SynthesisOutputError, match="in stock"):
        validate(
            "AuriLogic Flight ANC is not in stock [1].",
            [evidence("Ships today.")],
            [product(availability="low_stock")],
        )


@pytest.mark.parametrize("availability", ["out_of_stock", "preorder"])
def test_a_true_negated_availability_claim_passes(availability):
    validate(
        "AuriLogic Flight ANC is not in stock [1].",
        [evidence("Ships later.")],
        [product(availability=availability)],
    )


def test_a_negated_out_of_stock_claim_is_decided_against_the_inverse():
    validate(
        "AuriLogic Flight ANC is not out of stock [1].",
        [evidence("Ships today.")],
        [product(availability="in_stock")],
    )
    with pytest.raises(SynthesisOutputError, match="out of stock"):
        validate(
            "AuriLogic Flight ANC is not out of stock [1].",
            [evidence("Ships later.")],
            [product(availability="out_of_stock")],
        )


def test_a_negator_in_another_clause_does_not_negate_the_claim():
    validate(
        "No other option comes close; AuriLogic Flight ANC is in stock [1].",
        [evidence("Ships today.")],
        [product(availability="in_stock")],
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


@pytest.mark.parametrize("amount", ["999.99", "19.99", "179.98"])
def test_uncited_currency_must_match_the_subject_price(amount):
    with pytest.raises(SynthesisOutputError):
        validate(
            f"AuriLogic Flight ANC is a good fit [1]. It costs ${amount}.",
            [evidence(BATTERY_EVIDENCE)],
        )
    validate(
        "AuriLogic Flight ANC is a good fit [1]. It costs $179.99.",
        [evidence(BATTERY_EVIDENCE)],
    )


@pytest.mark.parametrize("number", [1, 12, 48, 350])
@pytest.mark.parametrize("reverse", [False, True])
def test_each_occurrence_keeps_its_unit(number, reverse):
    facts = [f"{number}-hour battery life", f"a {number}-year warranty"]
    if reverse:
        facts.reverse()
    answer = f"AuriLogic Flight ANC has {' and '.join(facts)} [1]."
    with pytest.raises(SynthesisOutputError):
        validate(answer, [evidence(f"Battery life {number} hours.")])
    validate(
        answer,
        [evidence(f"Battery life {number} hours. Warranty {number} years.")],
    )


@pytest.mark.parametrize(
    ("attribute", "value", "wording"),
    [
        ("recommended_hours", 12, "12-hour recommended use"),
        ("max_user_weight_lb", 350, "350 lb weight capacity"),
        ("recline_deg", 135, "135-degree recline"),
    ],
)
def test_measurements_use_only_the_cited_records_structured_attributes(
    attribute, value, wording
):
    record = evidence("Catalog specification.").model_copy(
        update={"metadata": {"attributes": {attribute: value}}}
    )
    answer = f"AuriLogic Flight ANC offers {wording} [1]."
    validate(answer, [record])
    wrong_record = record.model_copy(
        update={"metadata": {"attributes": {attribute: value + 1}}}
    )
    with pytest.raises(SynthesisOutputError):
        validate(answer, [wrong_record])
    with pytest.raises(SynthesisOutputError):
        validate(answer, [evidence("No measured specification here."), record])


def test_pronoun_cannot_borrow_another_products_price():
    other = product(
        product_id=2, title="Travel Audio", model="Travel", price_cents=99999
    )
    other_record = evidence("Travel specification").model_copy(
        update={"product_id": 2, "evidence_id": 2}
    )
    with pytest.raises(SynthesisOutputError):
        validate(
            "Travel Audio is an alternative [2]. AuriLogic Flight ANC is the best fit [1]. It costs $999.99.",
            [evidence(BATTERY_EVIDENCE), other_record],
            [product(), other],
        )


@pytest.mark.parametrize(
    "source",
    [
        "Model A2342 has not been tested for compatibility. Power: 30W. GaN charger.",
        "Model A2342 is listed in a shopper question. Power: 30W. GaN charger.",
        "Not compatible with model A2342. Power: 30W. GaN charger.",
    ],
)
def test_model_identifier_presence_does_not_establish_compatibility(source):
    with pytest.raises(SynthesisOutputError, match="unsupported compatibility claim"):
        validate(
            "AuriLogic Flight ANC is compatible with model A2342 [1].",
            [evidence(source)],
        )


def test_explicit_supported_compatibility_can_be_stated():
    validate(
        "AuriLogic Flight ANC is compatible with model A2342 [1].",
        [evidence("Compatible with model A2342.")],
    )


@pytest.mark.parametrize(
    "claim",
    [
        "will charge Alex’s laptop",
        "works with your laptop",
        "is compatible with MacBook Pro",
        "will charge a Dell XPS laptop",
    ],
)
def test_ports_alone_do_not_establish_laptop_compatibility(claim):
    with pytest.raises(SynthesisOutputError, match="unsupported compatibility claim"):
        validate(
            f"AuriLogic Flight ANC {claim} [1].",
            [evidence("Connections: USB-C. USB-C power delivery: 65 W.")],
        )


@pytest.mark.parametrize(
    "source",
    [
        "MacBook Pro is mentioned in a shopper question.",
        "Not compatible with MacBook Pro.",
        "Compatible with MacBook Air.",
    ],
)
def test_named_laptop_needs_its_own_affirmative_relationship(source):
    with pytest.raises(SynthesisOutputError, match="unsupported compatibility claim"):
        validate(
            "AuriLogic Flight ANC is compatible with MacBook Pro [1].",
            [evidence(source)],
        )


def test_explicit_named_laptop_compatibility_can_be_stated():
    validate(
        "AuriLogic Flight ANC is compatible with MacBook Pro [1].",
        [evidence("Compatible with MacBook Pro with no adapter required.")],
    )


def test_compatibility_does_not_establish_charging():
    with pytest.raises(SynthesisOutputError, match="unsupported compatibility claim"):
        validate(
            "AuriLogic Flight ANC will charge MacBook Pro [1].",
            [evidence("Compatible with MacBook Pro.")],
        )


def test_explicit_named_laptop_charging_can_be_stated():
    validate(
        "AuriLogic Flight ANC will charge MacBook Pro [1].",
        [evidence("Can charge MacBook Pro.")],
    )


def test_laptop_uncertainty_can_be_stated():
    validate(
        "AuriLogic Flight ANC is not confirmed to work with your laptop [1].",
        [evidence("Connections: USB-C.")],
    )


def test_compatibility_cannot_borrow_a_cited_siblings_positive_relationship():
    first = product()
    second = product(product_id=2, title="AuriLogic Office ANC", model="Office ANC")
    records = [
        evidence("Not compatible with model A2342."),
        evidence("Compatible with model A2342.").model_copy(
            update={"evidence_id": 2, "product_id": 2}
        ),
    ]
    with pytest.raises(SynthesisOutputError, match="unsupported compatibility claim"):
        validate(
            "AuriLogic Flight ANC is compatible with model A2342 [1][2].",
            records,
            [first, second],
        )


def test_unrelated_negative_phrase_cannot_disable_compatibility_validation():
    with pytest.raises(SynthesisOutputError, match="unsupported compatibility claim"):
        validate(
            "AuriLogic Flight ANC is not expensive and is compatible with model A2342 [1].",
            [evidence("Model A2342 compatibility has not been tested.")],
        )


def test_unrelated_negative_feature_does_not_invalidate_explicit_compatibility():
    validate(
        "AuriLogic Flight ANC is compatible with model A2342 [1].",
        [evidence("Compatible with model A2342 with no adapter required.")],
    )


def test_ellipsized_product_title_keeps_its_citation_in_the_sentence():
    monitor = product(
        title="Dell UltraSharp 27-inch USB-C Monitor U2720Q", model="UltraSharp"
    )
    validate(
        "The Dell UltraSharp ... U2720Q has a 27-inch screen [1].",
        [evidence("Dell UltraSharp U2720Q. Screen size: 27 inches.")],
        [monitor],
    )
    with pytest.raises(SynthesisOutputError, match="does not cite|unsupported numeric"):
        validate(
            "The Dell UltraSharp ... U2720Q has a 27-inch screen. It looks good [1].",
            [evidence("Dell UltraSharp U2720Q. Screen size: 27 inches.")],
            [monitor],
        )


def test_unique_brand_subject_does_not_inherit_the_previous_products_claims():
    monitor = product(
        product_id=2, title="Dell UltraSharp Monitor", model="UltraSharp", brand="Dell"
    )
    chair = product(title="Steelcase Gesture Chair", model="Gesture", brand="Steelcase")
    monitor_record = evidence("Screen size: 27 inches.").model_copy(
        update={"product_id": 2, "evidence_id": 2}
    )
    records = [evidence("Adjustable lumbar support."), monitor_record]
    validate(
        "The Steelcase Gesture has lumbar support [1]. The Dell record confirms a 27-inch screen [2].",
        records,
        [chair, monitor],
    )
    with pytest.raises(SynthesisOutputError):
        validate(
            "The Steelcase Gesture has a 27-inch screen [2]. The Dell has lumbar support [1].",
            records,
            [chair, monitor],
        )


def _two_listings():
    first = product(
        product_id=1,
        title="Dell UltraSharp U2720Q 27 Inch 4K UHD USB-C Monitor",
        brand="Dell",
        model="DELU2720Q",
    )
    second = product(
        product_id=2,
        title='Dell UltraSharp 27" 4K UHD USB-C Monitor - U2720Q-Black',
        brand="Dell",
        model="UltraSharp",
    )
    # Specification evidence carries the source listing title, as in production.
    records = [
        evidence("USB-C connectivity. 3840 x 2160 resolution.", title=first.title),
        EvidenceRecord(
            evidence_id=2,
            product_id=2,
            evidence_type="specification",
            source_name="Dell",
            source_uri="https://example.invalid/spec-2",
            revision="r1",
            title=second.title,
            text="USB-C with up to 90W of power delivery.",
        ),
    ]
    return [first, second], records


def test_a_name_shared_by_two_listings_is_satisfied_by_either_citation():
    products, records = _two_listings()
    validate(
        # "UltraSharp" is one listing's model and a word in the other's title.
        "The UltraSharp listing specifies USB-C connectivity [1]. "
        'The Dell UltraSharp 27" states up to 90W of power delivery [2].',
        records,
        products,
    )


def test_a_name_unique_to_one_listing_still_needs_that_listings_citation():
    products, records = _two_listings()
    with pytest.raises(SynthesisOutputError, match="naming product 2"):
        validate(
            'The Dell UltraSharp 27" 4K UHD USB-C Monitor - U2720Q-Black specifies '
            "USB-C connectivity [1]. The other listing states up to 90W of power "
            "delivery [2].",
            records,
            products,
        )


@pytest.mark.parametrize(
    "title,brand,model,expected",
    [
        (
            "JK CCH-001 Noise Cancelling Call Center Headset For Cisco IP Phones",
            "",
            "",
            "JK CCH-001",
        ),
        (
            "Bose QuietComfort 35 (Series II) Wireless Headphones",
            "Bose",
            "",
            "Bose QuietComfort 35",
        ),
        (
            "Sony WH-1000XM4 Wireless Premium Noise Canceling Headphones",
            "Sony",
            "WH1000XM4",
            "Sony WH-1000XM4",
        ),
        (
            "Steelcase Gesture Office Chair, Licorice",
            "Steelcase",
            "",
            "Steelcase Gesture Office Chair",
        ),
        (
            "VELKPRO Wireless Headset with Microphone - Noise Canceling Headphones",
            "VELKPRO",
            "VPO-NC",
            "VELKPRO Wireless Headset",
        ),
        (
            "Howtai Ergonomic Office Chair with Lumbar Support Durable Mesh Computer Desk",
            "Howtai",
            "",
            "Howtai Ergonomic Office Chair",
        ),
        (
            "Bang & Olufsen Beoplay Portal Gaming Headset with Microphone",
            "Bang & Olufsen",
            "",
            "Bang & Olufsen Beoplay Portal",
        ),
        # The title's first sentence ends the name, so the model never writes a full
        # stop inside it (observed 21 October: every mention split its sentence).
        (
            "233621 Shell Noise Cancelling Headphones. Lightweight Over Ear ANC Headphones.",
            "233621",
            "7149",
            "233621 Shell Noise Cancelling Headphones",
        ),
        (
            "Acme Pro. Wireless Headset X1 for Calls",
            "Acme",
            "",
            "Acme Pro",
        ),
        ("JLab Go Air Pop.", "JLab", "", "JLab Go Air Pop"),
        (
            "Sony WH-1000XM4. Wireless Industry Leading Noise Canceling",
            "Sony",
            "WH1000XM4",
            "Sony WH-1000XM4",
        ),
        # No brand and no model code: a shortened generic phrase would match
        # ordinary prose, so the full title stays the reference.
        (
            "Noise Cancelling Headphones, Wireless Bluetooth Over Ear",
            "",
            "",
            "Noise Cancelling Headphones, Wireless Bluetooth Over Ear",
        ),
    ],
)
def test_each_product_gets_a_short_reference_name_from_its_own_title(
    title, brand, model, expected
):
    assert reference_name(product(title=title, brand=brand, model=model)) == expected


def test_a_short_title_name_is_recognized_as_that_product():
    """Listings without a brand or model were only recognized by their full title.

    A draft that named "JK CCH-001" was scoped to the previous sentence's product
    and its "001" was checked as a measurement, so every redraft failed.
    """
    velkpro = product(
        product_id=1,
        title="VELKPRO Wireless Headset with Microphone - Noise Canceling Headphones",
        brand="VELKPRO",
        model="VPO-NC",
    )
    jk = product(
        product_id=2,
        title="JK CCH-001 Noise Cancelling Call Center Headset For Cisco IP Phones",
        brand="",
        model="",
    )
    records = [
        evidence(
            "Wireless headset with a noise canceling microphone.", title=velkpro.title
        ),
        EvidenceRecord(
            evidence_id=2,
            product_id=2,
            evidence_type="specification",
            source_name="JK",
            source_uri="https://example.invalid/jk",
            revision="r1",
            title=jk.title,
            text="Wired call center headset with a noise cancelling microphone.",
        ),
    ]
    validate(
        "The VELKPRO Wireless Headset with Microphone has a noise canceling microphone [1].\n"
        "- JK CCH-001: a wired call center headset with a noise cancelling microphone [2].",
        records,
        [velkpro, jk],
    )


def test_an_uncited_product_sentence_is_named_so_the_redraft_can_fix_it():
    """A redraft only saw "does not cite evidence", so it kept the same sentence."""
    uncited = "The sources do not state a charging wattage for AuriLogic Flight ANC."
    with pytest.raises(SynthesisOutputError) as raised:
        validate(
            f"{uncited} AuriLogic Flight ANC has 48 hours of battery life [1].",
            [evidence(BATTERY_EVIDENCE)],
        )
    assert uncited in str(raised.value)
    assert "even when it says a source does not state something" in str(raised.value)


def test_a_rejected_number_tells_the_redraft_how_to_state_its_absence():
    """Redrafts kept writing "no figure such as 90W is given" until synthesis failed."""
    with pytest.raises(SynthesisOutputError) as raised:
        validate(
            "AuriLogic Flight ANC lists no charging figure such as 90W [1].",
            [evidence(BATTERY_EVIDENCE)],
        )
    assert "say so without writing the number" in str(raised.value)


# The Lab 3 follow-up: a monitor whose listing states 90W, and a shopper who now
# needs 100W. Every honest answer names both figures; the 100W is the shopper's
# bound, not a claim about the monitor.
FOLLOW_UP = "My laptop actually needs 100W. Does that change your pick?"
USB_C_90W = "USB-C connectivity, get up to 90W of power delivery"


def _monitor():
    return product(title='Dell UltraSharp 27" 4K UHD Monitor', model="UltraSharp")


@pytest.mark.parametrize(
    "sentence",
    [
        # Drafts the validator rejected on 2026-09-28, verbatim apart from names.
        "Dell UltraSharp 27\" delivers up to 90W of USB-C power delivery [1], which is below your laptop's 100W requirement.",
        'Dell UltraSharp 27" provides up to 90W of USB-C power delivery [1], which is below the 100W your laptop needs.',
        'Dell UltraSharp 27" is specified at up to 90W of USB-C power delivery [1], not 100W, so its cited specification does not meet a 100W laptop requirement.',
        'Dell UltraSharp 27" delivers only up to 90W of USB-C power delivery [1], so its cited specification does not meet a 100W laptop requirement.',
        'Reviewers describe charging a MacBook Pro on Dell UltraSharp 27" [1], but that does not establish that it can supply 100W.',
        'Dell UltraSharp 27" is specified at up to 90W of USB-C power delivery [1], the same shortfall against a 100W need.',
        'If your laptop strictly requires 100W while in use, Dell UltraSharp 27" does not meet that figure [1].',
        'A reviewer of Dell UltraSharp 27" reports charging a MacBook Pro [1], not a guarantee your 100W device will charge at full speed.',
        'Dell UltraSharp 27" records do not state a 100W charging capability [1].',
        'A reviewer charged a MacBook Pro on Dell UltraSharp 27" [1], with no mention of 100W.',
        'Since its record caps out at 90W [1], Dell UltraSharp 27" is not confirmed to meet a 100W charging need.',
    ],
)
def test_the_shoppers_stated_requirement_is_a_bound_not_a_product_claim(sentence):
    validate(sentence, [evidence(USB_C_90W)], [_monitor()], FOLLOW_UP)


@pytest.mark.parametrize(
    ("sentence", "question"),
    [
        # The requirement asserted as the product's own value.
        (
            'Dell UltraSharp 27" delivers up to 100W of USB-C power delivery [1].',
            FOLLOW_UP,
        ),
        # Satisfaction claimed against a smaller cited value.
        (
            'Dell UltraSharp 27" meets your 100W requirement with 90W of USB-C power delivery [1].',
            FOLLOW_UP,
        ),
        (
            'Dell UltraSharp 27" delivers 90W of USB-C power delivery [1], above your 100W requirement.',
            FOLLOW_UP,
        ),
        # Satisfaction claimed with no cited value to decide it.
        ('Dell UltraSharp 27" meets your 100W requirement [1].', FOLLOW_UP),
        # The requirement stated as the product's value after a negated clause.
        ('Dell UltraSharp 27" is not limited to 90W; it delivers 100W [1].', FOLLOW_UP),
        ('Dell UltraSharp 27" supports 100W charging [1].', FOLLOW_UP),
        # A shortfall a cited value contradicts: 120W is not below 100W.
        (
            'Dell UltraSharp 27" delivers up to 120W [1], below your 100W requirement.',
            FOLLOW_UP,
        ),
        # A bound the shopper never stated.
        (
            'Dell UltraSharp 27" delivers up to 90W [1], which is below your 100W requirement.',
            "Does it charge my laptop?",
        ),
    ],
)
def test_a_requirement_frame_cannot_carry_a_false_comparison(sentence, question):
    with pytest.raises(SynthesisOutputError, match="unsupported numeric claim"):
        validate(sentence, [evidence(USB_C_90W)], [_monitor()], question)


def test_a_rejected_compatibility_claim_names_the_claim_and_its_sentence():
    sentence = "AuriLogic Flight ANC is compatible with model A2342 [1]."
    with pytest.raises(SynthesisOutputError) as raised:
        validate(
            sentence,
            [evidence("Model A2342 is listed in a shopper question. Power: 30W.")],
        )
    message = str(raised.value)
    assert "compatible with model A2342" in message
    assert sentence in message
    assert "for from" not in message


SHELL = product(
    product_id=2,
    sku="B0BXYZ1234",
    title="233621 Shell Noise Cancelling Headphones. Lightweight Over Ear ANC Headphones.",
    brand="233621",
    model="7149",
)


def shell_evidence() -> EvidenceRecord:
    return evidence("Active noise cancellation for focused work.").model_copy(
        update={"evidence_id": 2, "product_id": 2}
    )


def test_a_bullet_that_only_names_a_product_is_a_label_not_a_claim():
    # Observed on Sonnet 5.5, 21 October: "Name. What its listing says [n]." The sentence
    # split leaves the name alone, and rejecting it failed whole runs.
    answer = (
        "AuriLogic Flight ANC is the strongest fit [1].\n"
        "### Other strong options\n"
        f"- {reference_name(SHELL)}. Its listing describes active noise cancellation [2]."
    )
    validate(
        answer,
        [evidence("Active noise cancellation."), shell_evidence()],
        [product(), SHELL],
    )


@pytest.mark.parametrize(
    "bullet",
    [
        "- {name} has active noise cancellation.",
        "- {name}: active noise cancellation.",
        "- Choose {name}.",
    ],
)
def test_a_named_product_with_any_words_of_its_own_still_needs_a_citation(bullet):
    # The product is cited later, so only the per-sentence rule can reject the bullet.
    answer = (
        "AuriLogic Flight ANC is the strongest fit [1].\n"
        + bullet.format(name=reference_name(SHELL))
        + "\nIts listing describes active noise cancellation [2]."
    )
    with pytest.raises(
        SynthesisOutputError, match="does not cite evidence for that product"
    ):
        validate(
            answer,
            [evidence("Active noise cancellation."), shell_evidence()],
            [product(), SHELL],
        )


def test_a_generic_one_word_model_does_not_name_its_product_in_ordinary_prose():
    # Observed 21 October: a listing whose model is "Headphones" made every sentence
    # mentioning headphones name it, and a sentence about another product's review failed.
    generic = product(
        product_id=3,
        sku="B0GEN",
        title="Phonicgrid Active Noise Cancelling Headphones",
        brand="Phonicgrid",
        model="Headphones",
    )
    answer = (
        "AuriLogic Flight ANC is the strongest fit [1]. One reviewer reports its noise "
        "cancellation is not as strong as music headphones [1].\n"
        f"- {reference_name(SHELL)} offers active noise cancellation [2].\n"
        f"- {reference_name(generic)} offers active noise cancellation [3]."
    )
    generic_evidence = evidence("Active noise cancellation.").model_copy(
        update={"evidence_id": 3, "product_id": 3}
    )
    validate(
        answer,
        [evidence("Active noise cancellation."), shell_evidence(), generic_evidence],
        [product(), SHELL, generic],
    )


THREE_M = product(
    product_id=2,
    sku="B09LK7TRYV",
    title="3M Quiet Space Headphones, Bluetooth Headphones, Wireless Headphones, 1 Pair",
    brand="3M",
    model="3M Quiet Space Headphones, Black, Wireless, Bluetooth Enabled",
)


def three_m_evidence(text: str = "Passive noise reduction of 30 dB.") -> EvidenceRecord:
    return evidence(text, title="Customer review").model_copy(
        update={"evidence_id": 2, "product_id": 2}
    )


@pytest.mark.parametrize(
    "named",
    [
        "the 3M Quiet Space [2]",
        "the 3M headphones [2]",
        "3M's Quiet Space Headphones [2]",
    ],
)
def test_a_brand_written_with_digits_names_its_product_and_is_not_a_figure(named):
    # Observed 21 October: "3M" was read as an unsupported figure about the product
    # named before it, and the whole answer was rejected.
    validate(
        f"Choose the AuriLogic Flight ANC [1] for calls, or {named} for quiet focus.",
        [evidence("Active noise cancellation."), three_m_evidence()],
        [product(), THREE_M],
    )


def test_a_figure_after_a_digit_brand_is_checked_against_that_brand():
    validate(
        "Choose the AuriLogic Flight ANC [1] for calls, or the 3M headphones [2], "
        "which reduce noise by 30 dB [2].",
        [evidence("Active noise cancellation."), three_m_evidence()],
        [product(), THREE_M],
    )
    with pytest.raises(SynthesisOutputError, match=r"\['40dB'\]|\['40'\]"):
        validate(
            "Choose the AuriLogic Flight ANC [1] for calls, or the 3M headphones [2], "
            "which reduce noise by 40 dB [2].",
            [evidence("Active noise cancellation."), three_m_evidence()],
            [product(), THREE_M],
        )


def test_a_measurement_containing_a_digit_brand_is_still_a_measurement():
    with pytest.raises(SynthesisOutputError, match=r"\['13mm'\]"):
        validate(
            "Choose the AuriLogic Flight ANC [1] for calls. The 3M headphones have "
            "13mm drivers [2].",
            [evidence("Active noise cancellation."), three_m_evidence()],
            [product(), THREE_M],
        )


def test_a_two_letter_brand_is_an_ordinary_abbreviation_not_a_name():
    centimetre_brand = product(
        product_id=2,
        sku="CM-1",
        title="CM Studio Monitor Stand",
        brand="CM",
        model="S1",
    )
    stand_evidence = evidence("Holds one monitor.").model_copy(
        update={"evidence_id": 2, "product_id": 2}
    )
    validate(
        "AuriLogic Flight ANC is 18 cm tall [1]. CM Studio Monitor Stand holds one "
        "monitor [2].",
        [evidence("Height 18 cm."), stand_evidence],
        [product(), centimetre_brand],
    )


def test_a_brand_that_reads_as_a_measurement_does_not_hide_that_measurement():
    # The catalog has brands such as "8MM", "52HZ" and "25H"; "8mm drivers" is a size.
    speaker = product(
        product_id=2,
        sku="8MM-1",
        title="8MM Bluetooth Speaker",
        brand="8MM",
        model="S1",
    )
    speaker_evidence = evidence("Portable speaker.").model_copy(
        update={"evidence_id": 2, "product_id": 2}
    )
    with pytest.raises(SynthesisOutputError, match=r"\['8mm'\]"):
        validate(
            "AuriLogic Flight ANC has active noise cancellation [1]. "
            "8MM Bluetooth Speaker has 8mm drivers [2].",
            [evidence("Active noise cancellation."), speaker_evidence],
            [product(), speaker],
        )
