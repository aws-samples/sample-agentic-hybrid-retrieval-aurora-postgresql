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
