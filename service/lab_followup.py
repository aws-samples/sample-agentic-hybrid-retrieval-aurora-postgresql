"""Grade saved changed-requirement evidence without asking a replacement question."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from service.claim_review import ClaimReview
from service.lab_checks import LabCheck, same_request
from service.telemetry_contract import load_agent_turn_rows


def claim_review_problem(turn: Mapping[str, Any]) -> str | None:
    """Require the completed answer's support receipt, not a review of another draft."""
    intent = turn.get("extracted_intent") or {}
    receipt = intent.get("usage", {}).get("synthesis", {}).get("claim_review") or {}
    answer = turn.get("assistant_message") or ""
    if (
        not answer
        or receipt.get("answer_sha256") != hashlib.sha256(answer.encode()).hexdigest()
    ):
        return "the saved answer has no matching claim-support review"
    try:
        review = ClaimReview.model_validate({"passages": receipt.get("passages")})
    except ValueError:
        return "the saved claim-support review is malformed"
    if any(p.verdict == "unsupported" for p in review.passages):
        return "the saved review rejected a claim in the answer"
    if not any(p.verdict == "supported" and p.support for p in review.passages):
        return "the saved review contains no supported product claim"
    return None


def load_changed_requirement(connection, mission, started_at):
    """Select the newest answered exercise run since this lab started."""
    request = mission["changed_requirement"]["query"]
    candidates = connection.execute(
        """SELECT agent_turn_id, user_message FROM mosaic.agent_turn
           WHERE created_at > %s AND assistant_message IS NOT NULL
           ORDER BY created_at DESC LIMIT 200""",
        (started_at,),
    ).fetchall()
    found = next(
        (r for r in candidates if same_request(r["user_message"], request)), None
    )
    return load_agent_turn_rows(connection, found["agent_turn_id"]) if found else None


def changed_requirement_check(mission, rows, setup_rows, resolved_evidence) -> LabCheck:
    """Check the actual answer/decline, new searches, and the product records it read."""
    from service.models import EvidenceRecord, ProductSummary
    from service.participant_commands import ask_agent_command
    from service.synthesis import validate_cited_answer

    requirement = mission["changed_requirement"]
    failure = "no answered changed-requirement run was saved since Lab 3 started"
    if rows is not None and setup_rows is not None:
        intent = rows.turn.get("extracted_intent") or {}
        setup_intent = setup_rows.turn.get("extracted_intent") or {}
        target = requirement["product_id"]
        records = [
            record
            for record in resolved_evidence.values()
            if record.get("product_id") == target
        ]
        read_ids = {
            item.get("evidence_id")
            for item in intent.get("retrieved_evidence", [])
            if isinstance(item, dict)
        }
        read_spec = any(
            record.get("evidence_type") == requirement["evidence_type"]
            and record.get("evidence_id") in read_ids
            and any(
                old.get("evidence_id") == record.get("evidence_id")
                and old.get("revision") == record.get("revision")
                and old.get("text") == record.get("text")
                for old in intent.get("retrieved_evidence", [])
                if isinstance(old, dict)
            )
            for record in records
        )
        outcome = intent.get("outcome")
        failure = ""
        if not same_request(rows.turn.get("user_message"), requirement["query"]):
            failure = "the run answered another question"
        elif not intent.get("application_sha256") or intent.get(
            "application_sha256"
        ) != setup_intent.get("application_sha256"):
            failure = "the two exercise runs were made by different or unrecorded code"
        elif not any(row["product_id"] == target for row in rows.candidates):
            failure = (
                "the changed request has no new search containing the named monitor"
            )
        elif not read_spec:
            failure = "the changed request did not read the named monitor's current specification"
        elif outcome == "declined":
            review = (
                intent.get("usage", {}).get("synthesis", {}).get("answerability") or {}
            )
            unmet = " ".join(review.get("unmet_requirements") or [])
            watts = re.search(r"(\d+)\s*W\b", requirement["requirement"], re.IGNORECASE)
            names_requirement = (
                watts is not None
                and re.search(rf"\b{watts[1]}\s*(?:w|watts?)\b", unmet, re.IGNORECASE)
                and re.search(r"charg|power|USB", unmet, re.IGNORECASE)
            )
            gaps = "; ".join(
                " ".join(item.split()) for item in review.get("unmet_requirements", [])
            )
            expected = f"The retrieved sources do not establish {gaps}. No product is recommended."
            if (
                review.get("request_supported") is not False
                or review.get("reason")
                not in {"unsupported_requirements", "insufficient_evidence"}
                or not names_requirement
                or intent.get("selected_products")
                or not (rows.turn.get("assistant_message") or "").startswith(expected)
            ):
                failure = (
                    "the decline does not identify the changed charging requirement"
                )
        elif outcome == "grounded":
            failure = claim_review_problem(rows.turn) or ""
            if not failure:
                synthesis = next(
                    (
                        t
                        for t in reversed(rows.tools)
                        if t["tool_name"] == "synthesize_cited_answer"
                        and t.get("outcome") == "success"
                    ),
                    {},
                )
                citations = (synthesis.get("output_payload") or {}).get(
                    "citations"
                ) or []
                try:
                    numbered = {
                        c["number"]: EvidenceRecord.model_validate(
                            resolved_evidence[c["evidence_id"]]
                        )
                        for c in citations
                    }
                    if not numbered or not any(
                        r.product_id == target for r in numbered.values()
                    ):
                        raise ValueError("no monitor citation")
                    positions = {
                        number: index
                        for index, number in enumerate(sorted(numbered), 1)
                    }
                    answer = re.sub(
                        r"\[(\d+)\]",
                        lambda m: f"[{positions[int(m[1])]}]",
                        rows.turn["assistant_message"],
                    )
                    evidence = [numbered[n] for n in sorted(numbered)]
                    picks = [
                        ProductSummary.model_validate(p)
                        for p in intent.get("selected_products", [])
                    ]
                    if not picks:
                        raise ValueError("no selected product")
                    validate_cited_answer(answer, picks, evidence, requirement["query"])
                except (KeyError, TypeError, ValueError) as error:
                    failure = f"the saved changed-requirement answer fails citation checks ({type(error).__name__})"
        else:
            failure = f"the changed-requirement run ended with outcome {outcome!r}"
    return LabCheck(
        name="changed requirement checked",
        passed=not failure,
        falsifier="the changed question was skipped, used other code, did not search/read the named product, or its answer/decline lacks checked support for the new requirement",
        detail=f"Changed-requirement run {rows.turn['agent_turn_id']} checked against current sources"
        if not failure
        else f"Changed requirement: {failure}. Next: {ask_agent_command(requirement['query'])}, then grade again.",
    )
