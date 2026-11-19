"""Grade saved changed-requirement evidence without asking a replacement question."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from service.claim_review import ClaimReview
from service.lab_checks import LabCheck, same_request
from service.telemetry_contract import load_agent_turn_rows

CHANGED_REQUIREMENT_CHECK = "changed requirement checked"
CHANGED_REQUIREMENT_DEPLOYMENT = "changed requirement deployment"
# The checks only the 100W follow-up's run can fail; asking it again is their fix.
FOLLOW_UP_CHECKS = frozenset(
    {CHANGED_REQUIREMENT_CHECK, CHANGED_REQUIREMENT_DEPLOYMENT}
)


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


def follow_up_saved(connection, root=None) -> bool:
    """Whether the 100W answer completion would read already comes from the deployed code.

    It reads the run with `load_changed_requirement`, as completion does, and compares the
    code that made it with the code deployed now, so a later deploy of changed code makes
    it count no longer. Completion's other checks on that run still run when it grades.
    """
    from service.agent_deploys import deploy_due, lab_3_started_at
    from service.lab_checks import mission_for_lab
    from service.lab_validation_receipt import application_digest

    if deploy_due(root):
        return False
    rows = load_changed_requirement(
        connection, mission_for_lab(3), lab_3_started_at(root)
    )
    if rows is None:
        return False
    intent = rows.turn.get("extracted_intent") or {}
    code = application_digest(root) if root else application_digest()
    return intent.get("application_sha256") == code


def follow_up_saved_now() -> bool:
    """`follow_up_saved` on a connection of its own.

    Only a connection that cannot be made counts as no saved answer, which leaves the
    guide's own order, the 100W question next. Any other error is a defect and raises.
    """
    import psycopg

    from service.db import connect

    try:
        with connect() as connection:
            return follow_up_saved(connection)
    except psycopg.OperationalError:
        return False


# A listing line ties a wattage to charging with words like these, which tells its
# charging figure apart from a speaker's or the screen's own power draw.
_CHARGING = re.compile(r"charg|power\s+deliver|\bPD\b", re.IGNORECASE)
_CLAUSE_BREAK = re.compile(r"[,;\n]|(?<=[.!?])\s+")
_CITATION = re.compile(r"\[(\d+)\]")


def required_watts(requirement: str) -> float | None:
    """The charging wattage the mission's changed requirement names, if any."""
    from service.synthesis import stated_figures

    found = stated_figures(requirement, "watt")
    return max(found) if found else None


def listing_charging_watts(text: str) -> set[float]:
    """Every wattage a listing states for charging, read clause by clause."""
    from service.synthesis import stated_figures

    return {
        watts
        for clause in _CLAUSE_BREAK.split(text)
        if _CHARGING.search(clause)
        for watts in stated_figures(clause, "watt")
    }


# Words that tie a wattage to what the monitor delivers over its cable, rather than to a
# speaker, the screen's own draw or any other figure.
_DELIVERY = re.compile(
    r"charg|power|\bPD\b|USB[- ]?C|deliver|suppl|output|tops? out", re.IGNORECASE
)


# A condition on the shopper ("if", "unless") or a denial of their need ("you don't
# need 100W") says nothing about what the product supplies.
_CONDITION = re.compile(r"\b(?:if|unless)\b", re.IGNORECASE)
_NEED_DENIED = re.compile(
    r"(?:\bnot|\bnever|n['’]t)\s+(?:\w+\s+)?(?:need|require|want)", re.IGNORECASE
)
# "whether" is the shopper's question unless the sources are what is denied: "the listing
# does not say whether it can provide 100W" is a finding about the product.
_WHETHER = re.compile(r"\bwhether\b", re.IGNORECASE)
_SOURCES_SILENT = re.compile(
    r"(?:\bnot|\bnever|n['’]t)\s+(?:\w+\s+){0,2}"
    r"(?:say|state|show|establish|confirm|specif|mention|list|indicat)\w*\s+whether"
    r"|\b(?:unclear|unknown|uncertain)\s+whether",
    re.IGNORECASE,
)
# A listed wattage belongs to the shopper's own equipment when a condition leads into it
# ("whether your adapter is 90W") or the shopper's device is its subject ("your adapter
# is 90W", "your laptop needs 90W"). A device that receives the power ("supply your
# laptop with up to 90W") leaves the monitor as the one supplying it.
_SHOPPERS_EQUIPMENT = re.compile(
    r"\b(?:if|unless|whether)\b"
    r"|\byour\s+(?:[\w'’-]+\s+){1,2}?"
    r"(?:is|are|was|were|needs?|uses?|draws?|takes?|requires?|accepts?|has|have|gets?"
    r"|charges?|runs?|supplies|provides|delivers|outputs)\b",
    re.IGNORECASE,
)


def _about_the_shopper(lead: str) -> bool:
    """Whether the words before the required wattage make it the shopper's condition."""
    if _CONDITION.search(lead) or _NEED_DENIED.search(lead):
        return True
    return bool(_WHETHER.search(lead)) and not _SOURCES_SILENT.search(lead)


def _product_shortfall(mention, listed: set[float], needed: float | None) -> bool:
    """Whether a mention of the required wattage says the product falls short of it."""
    from service.synthesis import denies_or_falls_short

    return (
        mention.value == needed
        and denies_or_falls_short(mention.lead)
        and not _about_the_shopper(mention.lead)
        and all(watts < needed for watts in listed)
    )


def _settles_charging(
    text: str, listed: set[float], needed: float | None, supported: set[float]
) -> bool:
    """Whether a passage citing the listing settles the charging requirement.

    Each wattage is read in its own clause, with the label a colon gives it, and a
    listed wattage counts only as the monitor's, never as the shopper's equipment. The
    passage settles it by giving a charging wattage the listing states, in a clause
    about what the monitor delivers, beside the required wattage named as a shortfall,
    or where the answer check's saved support for this passage is the listing's own
    charging line for that figure (`supported`); or by naming the required wattage,
    in a clause about charging, as one the product falls short of or the sources do
    not establish, when the listing's figures bear that out.
    """
    from service.synthesis import figure_mentions

    mentions = figure_mentions(text, "watt")
    shortfall = [m for m in mentions if _product_shortfall(m, listed, needed)]
    for mention in mentions:
        if mention.value not in listed or _SHOPPERS_EQUIPMENT.search(mention.lead):
            continue
        about_delivery = _DELIVERY.search(mention.clause) or _DELIVERY.search(
            mention.label
        )
        if about_delivery or shortfall or mention.value in supported:
            return True
    return any(_DELIVERY.search(m.clause) for m in shortfall)


def _support_watts(support, number_listings, numbered) -> set[float]:
    """Charging wattages in the saved support quotes this passage drew from a listing.

    A quote counts only when it is the cited listing's own text, so the answer check's
    support names the listing's charging line rather than something it paraphrased.
    """
    found: set[float] = set()
    for quote in support:
        number, text = (
            quote.get("number"),
            " ".join(str(quote.get("quote", "")).split()),
        )
        if (
            number in number_listings
            and text
            and text in " ".join(numbered[number].text.split())
        ):
            found |= listing_charging_watts(text)
    return found


def charging_problem(requirement, answer, numbered, picks, review=None) -> str:
    """Why a grounded answer leaves the changed charging requirement unsettled, or "".

    A passage citing the named product's listing must settle the requirement (see
    `_settles_charging`). Any passage about the product that gives the required
    wattage as its value must have it from the listing: one reviewer's laptop is not
    Alex's.
    """
    from service.claim_review import passages
    from service.synthesis import claims_question_figure

    target = requirement["product_id"]
    listings = {
        number
        for number, record in numbered.items()
        if record.product_id == target
        and record.evidence_type == requirement["evidence_type"]
    }
    if not listings:
        return "the answer does not cite the monitor's listing"
    needed = required_watts(requirement["requirement"])
    listed = set().union(*(listing_charging_watts(numbered[n].text) for n in listings))
    support = {
        decision.get("id"): decision.get("support") or []
        for decision in (review or {}).get("passages") or []
        if isinstance(decision, dict) and decision.get("verdict") == "supported"
    }
    settled = False
    for passage in passages(answer):
        text = passage["text"]
        cited = {int(n) for n in _CITATION.findall(text) if int(n) in numbered}
        if not any(numbered[n].product_id == target for n in cited):
            continue
        records = [numbered[n] for n in sorted(cited)]
        if needed not in listed and claims_question_figure(
            text, requirement["query"], picks, records
        ):
            return (
                f"the answer gives {needed:g}W as the monitor's charging, which its "
                "listing does not state"
            )
        supported = _support_watts(support.get(passage["id"], []), listings, numbered)
        settled = settled or bool(
            cited & listings and _settles_charging(text, listed, needed, supported)
        )
    if settled:
        return ""
    return "the answer does not give the charging wattage in the monitor's listing"


def _decline_problem(requirement, rows, intent) -> str:
    """Why a decline does not name the changed charging requirement, or ""."""
    from service.synthesis import stated_figures

    review = intent.get("usage", {}).get("synthesis", {}).get("answerability") or {}
    unmet = " ".join(review.get("unmet_requirements") or [])
    needed = required_watts(requirement["requirement"])
    names_requirement = (
        needed is not None
        and needed in stated_figures(unmet, "watt")
        and re.search(r"charg|power|USB", unmet, re.IGNORECASE)
    )
    gaps = "; ".join(
        " ".join(item.split()) for item in review.get("unmet_requirements", [])
    )
    expected = (
        f"The retrieved sources do not establish {gaps}. No product is recommended."
    )
    if (
        review.get("request_supported") is not False
        or review.get("reason")
        not in {"unsupported_requirements", "insufficient_evidence"}
        or not names_requirement
        or intent.get("selected_products")
        or not (rows.turn.get("assistant_message") or "").startswith(expected)
    ):
        return "the decline does not identify the changed charging requirement"
    return ""


def _grounded_problem(requirement, rows, intent, resolved_evidence) -> str:
    """Why a grounded answer fails its citation or charging checks, or ""."""
    from service.models import EvidenceRecord, ProductSummary
    from service.synthesis import validate_cited_answer

    failure = claim_review_problem(rows.turn)
    if failure:
        return failure
    synthesis = next(
        (
            t
            for t in reversed(rows.tools)
            if t["tool_name"] == "synthesize_cited_answer"
            and t.get("outcome") == "success"
        ),
        {},
    )
    citations = (synthesis.get("output_payload") or {}).get("citations") or []
    try:
        numbered = {
            c["number"]: EvidenceRecord.model_validate(
                resolved_evidence[c["evidence_id"]]
            )
            for c in citations
        }
        if not numbered or not any(
            r.product_id == requirement["product_id"] for r in numbered.values()
        ):
            raise ValueError("no monitor citation")
        positions = {number: index for index, number in enumerate(sorted(numbered), 1)}
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
        return f"the saved changed-requirement answer fails citation checks ({type(error).__name__})"
    review = intent.get("usage", {}).get("synthesis", {}).get("claim_review") or {}
    return charging_problem(
        requirement, rows.turn["assistant_message"], numbered, picks, review
    )


def changed_requirement_check(
    mission, rows, setup_rows, resolved_evidence, *, managed: bool = False
) -> LabCheck:
    """Check the actual answer/decline, new searches, and the product records it read."""
    from service.participant_commands import ask_agent_command

    requirement = mission["changed_requirement"]
    failure = "no answered changed-requirement run was saved since Lab 3 started"
    if rows is not None and setup_rows is not None:
        intent = rows.turn.get("extracted_intent") or {}
        setup_intent = setup_rows.turn.get("extracted_intent") or {}
        followup_code = intent.get("application_sha256")
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
        # Managed proof checks each run against deployed code. Comparing the two
        # here would blame a current 100W answer for a stale setup run.
        elif not followup_code or (
            not managed and followup_code != setup_intent.get("application_sha256")
        ):
            failure = "the 100W answer came from different or unrecorded code"
        elif not any(row["product_id"] == target for row in rows.candidates):
            failure = (
                "the changed request has no new search containing the named monitor"
            )
        elif not read_spec:
            failure = "the changed request did not read the named monitor's current specification"
        elif outcome == "declined":
            failure = _decline_problem(requirement, rows, intent)
        elif outcome == "grounded":
            failure = _grounded_problem(requirement, rows, intent, resolved_evidence)
        else:
            failure = f"the changed-requirement run ended with outcome {outcome!r}"
    return LabCheck(
        name=CHANGED_REQUIREMENT_CHECK,
        passed=not failure,
        falsifier="the changed question was skipped, used other code, did not search/read the named product, its answer/decline lacks checked support for the new requirement, or a grounded answer never gives the wattage the product's listing states for charging (or the required wattage as a shortfall the listing bears out), or takes the required wattage from a review",
        detail=f"Changed-requirement run {rows.turn['agent_turn_id']} checked against current sources"
        if not failure
        else f"Changed requirement: {failure}. Next: {ask_agent_command(requirement['query'])}, then grade again.",
    )
