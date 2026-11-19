"""A passing setup answer alone does not prove changed requirements were checked."""

import copy
import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from test_synthesis_claims import evidence, product

from service.lab_checks import mission_for_lab
from service.lab_followup import changed_requirement_check, claim_review_problem
from service.telemetry_contract import AgentTurnRows


def valid_followup():
    mission = mission_for_lab(3)
    target = mission["changed_requirement"]["product_id"]
    record = evidence("USB-C power delivery: 90W.").model_copy(
        update={
            "product_id": target,
            "evidence_id": 9002,
            "evidence_type": "product_spec",
        }
    )
    pick = product(
        product_id=target,
        title="ViewSonic VG2756-4K",
        brand="ViewSonic",
        model="VG2756-4K",
    )
    answer = "ViewSonic VG2756-4K provides 90W, below your 100W requirement [1]."
    receipt = {
        "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
        "passages": [
            {
                "id": 1,
                "verdict": "supported",
                "support": [{"number": 1, "quote": record.text}],
                "reason": "90W is less than the requested 100W.",
            }
        ],
    }
    intent = {
        "application_sha256": "current-code",
        "outcome": "grounded",
        "selected_products": [pick.model_dump(mode="json")],
        "retrieved_evidence": [record.model_dump(mode="json")],
        "usage": {"synthesis": {"claim_review": receipt}},
    }
    rows = AgentTurnRows(
        turn={
            "agent_turn_id": uuid4(),
            "agent_session_id": uuid4(),
            "created_at": datetime.now(UTC),
            "user_message": mission["changed_requirement"]["query"],
            "assistant_message": answer,
            "extracted_intent": intent,
        },
        session={},
        searches=[],
        candidates=[{"product_id": target}],
        tools=[
            {
                "tool_name": "synthesize_cited_answer",
                "outcome": "success",
                "output_payload": {"citations": [{"number": 1, "evidence_id": 9002}]},
            }
        ],
    )
    return rows, {record.evidence_id: record.model_dump(mode="json")}


def test_supported_shortfall_passes_with_unrelated_evidence_present():
    rows, records = valid_followup()
    records[2] = {"product_id": 999, "text": "100W"}
    result = changed_requirement_check(mission_for_lab(3), rows, rows, records)
    assert result.passed and str(rows.turn["agent_turn_id"]) in result.detail


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "other_code",
        "no_search",
        "no_spec",
        "changed_spec",
        "wrong_answer",
        "missing_review",
        "forged_citation",
    ],
)
def test_changed_requirement_gate_has_teeth(fault):
    rows, records = valid_followup()
    setup = copy.deepcopy(rows)
    intent = rows.turn["extracted_intent"]
    if fault == "missing":
        rows = None
    elif fault == "other_code":
        intent["application_sha256"] = "old"
    elif fault == "no_search":
        rows.candidates.clear()
    elif fault == "no_spec":
        intent["retrieved_evidence"].clear()
    elif fault == "changed_spec":
        records[9002]["text"] = "100W now"
    elif fault == "wrong_answer":
        rows.turn["assistant_message"] = "Yes, it meets 100W [1]."
    elif fault == "missing_review":
        intent["usage"] = {}
    elif fault == "forged_citation":
        rows.tools[0]["output_payload"]["citations"][0]["number"] = 2
    check = changed_requirement_check(mission_for_lab(3), rows, setup, records)
    assert not check.passed and "Next:" in check.detail


def test_a_decline_must_name_the_changed_requirement():
    rows, records = valid_followup()
    intent = rows.turn["extracted_intent"]
    intent.update(outcome="declined", selected_products=[])
    intent["usage"]["synthesis"] = {
        "answerability": {
            "request_supported": False,
            "reason": "unsupported_requirements",
            "unmet_requirements": ["100W charging"],
        }
    }
    rows.turn["assistant_message"] = (
        "The retrieved sources do not establish 100W charging. No product is recommended."
    )
    assert changed_requirement_check(mission_for_lab(3), rows, rows, records).passed
    rows.turn["assistant_message"] = "Yes, it provides 100W."
    assert not changed_requirement_check(mission_for_lab(3), rows, rows, records).passed
    intent["usage"]["synthesis"]["answerability"]["unmet_requirements"] = [
        "all-day comfort"
    ]
    assert not changed_requirement_check(mission_for_lab(3), rows, rows, records).passed


def test_setup_review_cannot_be_reused_for_a_changed_answer():
    rows, _ = valid_followup()
    assert claim_review_problem(rows.turn) is None
    rows.turn["assistant_message"] = "A different answer [1]."
    assert claim_review_problem(rows.turn) is not None


# The ViewSonic listing's own feature line, as `read_citation.py` printed it on an event.
LISTING = (
    "VERSATILE MONITOR: 27 Inch 4K (3840x2160p) IPS monitor with thin bezels and 60Hz "
    "refresh rate\nDITCH THE DOCK: Ethernet RJ45 and USB-C connectivity for fast data, "
    "audio and video transfer, 90W charging over one cable\nERGONOMIC STAND: Advanced "
    "ergonomics (40-degree tilt, swivel, rotate and height) for all-day comfort"
)
REVIEW = "With a USB-C connector to pass battery charging to my 100W laptop, it is all I need."


def answered(answer, listing=LISTING, review=REVIEW):
    """A grounded 100W run citing the monitor's listing as [1] and a review as [2]."""
    rows, records = valid_followup()
    listing_id = rows.tools[0]["output_payload"]["citations"][0]["evidence_id"]
    records[listing_id]["text"] = listing
    intent = rows.turn["extracted_intent"]
    intent["retrieved_evidence"][0]["text"] = listing
    review_record = dict(
        records[listing_id],
        evidence_id=9003,
        evidence_type="customer_review",
        text=review,
    )
    records[9003] = review_record
    rows.tools[0]["output_payload"]["citations"].append(
        {"number": 2, "evidence_id": 9003}
    )
    rows.turn["assistant_message"] = answer
    intent["usage"]["synthesis"]["claim_review"] = {
        "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
        "passages": [
            {
                "id": 1,
                "verdict": "supported",
                "support": [{"number": 1, "quote": "90W charging over one cable"}],
                "reason": "The listing states it.",
            }
        ],
    }
    return changed_requirement_check(mission_for_lab(3), rows, rows, records)


@pytest.mark.parametrize(
    "answer",
    [
        # Recorded on the 16 November test event (run 1 and run 4).
        (
            "The ViewSonic VG2756-4K's listing states 90W charging over one cable [1], "
            "which is below the 100W your laptop needs, so its records do not show it "
            "meets that requirement.\n\nA reviewer reports that the monitor's USB-C "
            "connection passes battery charging to their laptop and serves as the video "
            "input [2]."
        ),
        (
            "What the sources support\n\nThe ViewSonic VG2756-4K's listing states 90W "
            "charging over one cable [1]. A reviewer reports using its USB-C connection "
            "to pass battery charging to their laptop and carry the video input [2]."
        ),
        "The ViewSonic VG2756-4K's listing states 90W charging over one cable [1].",
        "The ViewSonic VG2756-4K's listed charging falls short of the 100W you need [1].",
        "The ViewSonic VG2756-4K's sources do not establish 100W charging [1].",
        "The ViewSonic VG2756-4K's listing states 90W, not 100W [1].",
        "The ViewSonic VG2756-4K provides ninety watts of USB-C power delivery [1].",
        "- The ViewSonic VG2756-4K's listing states up to 90W charging [1][2].",
        "The ViewSonic VG2756-4K’s USB-C PD tops out at 90 W [1].",
    ],
    ids=[
        "shortfall",
        "listing-and-review",
        "90W-alone",
        "short-of-100W",
        "not-100W",
        "90W-not-100W",
        "spelled-out",
        "bullet-two-citations",
        "pd-tops-out",
    ],
)
def test_a_grounded_answer_passes_when_it_settles_charging_from_the_listing(answer):
    check = answered(answer)
    assert check.passed, check.detail


@pytest.mark.parametrize(
    ("answer", "listing", "reason"),
    [
        (
            "The ViewSonic VG2756-4K has USB-C [1].",
            LISTING,
            "does not give the charging wattage",
        ),
        (
            "A reviewer reports the ViewSonic VG2756-4K charges their 100W laptop [2].",
            LISTING,
            "listing does not state",
        ),
        (
            (
                "The ViewSonic VG2756-4K's listing states 90W charging over one cable "
                "[1]. A reviewer reports it charges their 100W laptop [2]."
            ),
            LISTING,
            "listing does not state",
        ),
        (
            "The ViewSonic VG2756-4K has 3W speakers [1].",
            "USB-C with 65W charging over one cable; built-in speakers rated 3W",
            "does not give the charging wattage",
        ),
        (
            "Your laptop needs 100W, and the ViewSonic VG2756-4K has USB-C [1].",
            LISTING,
            "does not give the charging wattage",
        ),
        (
            "You need 100W charging; the ViewSonic VG2756-4K has a USB-C port [1].",
            LISTING,
            "does not give the charging wattage",
        ),
        (
            "The ViewSonic VG2756-4K's listing does not mention 100W [1].",
            LISTING,
            "does not give the charging wattage",
        ),
        (
            "The ViewSonic VG2756-4K has 90W [1].",
            LISTING,
            "does not give the charging wattage",
        ),
        (
            "Your laptop needs 100W, and the ViewSonic VG2756-4K has USB-C [1].",
            "VERSATILE MONITOR: 27 Inch 4K IPS monitor with USB-C",
            "does not give the charging wattage",
        ),
        (
            (
                "You need 100W charging, and the ViewSonic VG2756-4K offers not just "
                "USB-C but Ethernet as well [1]."
            ),
            LISTING,
            "does not give the charging wattage",
        ),
    ],
    ids=[
        "usb-c-only",
        "review-only-100W",
        "review-100W-beside-listing",
        "speaker-watts",
        "requirement-repeated",
        "requirement-repeated-with-charging",
        "not-mentioned-without-charging",
        "bare-90W",
        "listing-without-charging-figure",
        "negation-in-another-clause",
    ],
)
def test_a_grounded_answer_fails_when_charging_is_unsettled(answer, listing, reason):
    check = answered(answer, listing)
    assert not check.passed and reason in check.detail and "Next:" in check.detail
