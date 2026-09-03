"""The coverage set must stay separable from the frozen canonical scorecard.

`scripts.score_evals.query_set_sha256` hashes the whole of
`canonical_queries.jsonl`, and `canonical_scorecard.json` validates that hash.
Adding abstention cases there would red the release gate with no way to regreen
it short of a live re-measurement, so this set lives in its own file and these
tests hold that boundary.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COVERAGE_QUERIES = ROOT / "data" / "evals" / "coverage_queries.jsonl"
CANONICAL_QUERIES = ROOT / "data" / "evals" / "canonical_queries.jsonl"

REQUIRED_FIELDS = {
    "query_id",
    "teaching_concept",
    "query",
    "expected_confidence",
    "expected_unmatched_terms",
    "floor_dependent",
    "verified_against_catalog",
    "rationale",
}

#: Lab 1's headline query. Its presence in this set, expecting `grounded`, is
#: what stops a future floor change from silently breaking the workshop.
FALSIFIER_ID = "C-101"
FALSIFIER_QUERY = "noice cancelng hedfones"


def _cases() -> list[dict]:
    return [
        json.loads(line)
        for line in COVERAGE_QUERIES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_every_case_declares_the_full_contract():
    for case in _cases():
        missing = REQUIRED_FIELDS - set(case)
        assert not missing, f"{case.get('query_id')} is missing {sorted(missing)}"


def test_confidences_are_only_the_two_decidable_values():
    """`unavailable` describes an unseeded database, not a query. A case
    expecting it would be asserting a deployment fault, not a retrieval one."""
    for case in _cases():
        assert case["expected_confidence"] in {"grounded", "unanchored"}


def test_query_ids_are_unique():
    ids = [case["query_id"] for case in _cases()]
    assert len(ids) == len(set(ids))


def test_query_ids_do_not_collide_with_the_canonical_set():
    canonical = {
        json.loads(line)["query_id"]
        for line in CANONICAL_QUERIES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    overlap = canonical & {case["query_id"] for case in _cases()}
    assert not overlap, f"coverage ids collide with canonical ids: {sorted(overlap)}"


def test_the_permanent_falsifier_is_present_and_expects_grounded():
    """If this case is ever deleted or flipped to `unanchored`, the gate has
    been allowed to fire on Lab 1 and the workshop's headline query is broken."""
    cases = {case["query_id"]: case for case in _cases()}
    assert FALSIFIER_ID in cases, "the Lab 1 falsifier was removed from the set"
    falsifier = cases[FALSIFIER_ID]
    assert falsifier["query"] == FALSIFIER_QUERY
    assert falsifier["expected_confidence"] == "grounded"
    assert falsifier["expected_unmatched_terms"] == []


def test_set_holds_both_directions():
    """A set of only-negatives measures abstention without measuring false
    abstention, which is the failure that costs more here."""
    confidences = [case["expected_confidence"] for case in _cases()]
    assert confidences.count("unanchored") >= 3
    assert confidences.count("grounded") >= 3


def test_grounded_cases_declare_no_unmatched_terms():
    for case in _cases():
        if case["expected_confidence"] == "grounded":
            assert case["expected_unmatched_terms"] == [], case["query_id"]


def test_unanchored_terms_appear_in_their_query():
    """A declared unmatched term that is not in the query cannot be produced by
    any implementation, so the case would be unfalsifiable."""
    for case in _cases():
        for term in case["expected_unmatched_terms"]:
            assert term.lower() in case["query"].lower(), (
                f"{case['query_id']} expects '{term}', absent from its query"
            )


def test_identifier_cases_are_decidable_without_the_unmeasured_floor():
    """Identifier-shaped tokens take no trigram rescue, so their verdict does
    not depend on `word_similarity_floor`. At least one such case must exist,
    or nothing in the set can be validated before the floor is measured."""
    floor_free = [c for c in _cases() if not c["floor_dependent"]]
    assert floor_free
    unanchored_floor_free = [
        c for c in floor_free if c["expected_confidence"] == "unanchored"
    ]
    assert unanchored_floor_free, (
        "every unanchored case depends on the unmeasured floor; at least one "
        "identifier-shaped case must be decidable without it"
    )


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["query_id"])
def test_no_case_claims_live_verification_it_has_not_had(case):
    """Guards the house rule against inventing measured data.

    Every case ships `verified_against_catalog: false` because the Aurora
    security group has had no inbound rules since 2026-08-28 and none of these
    expectations has been run against the 500,000-product corpus. Flipping a
    case to true is a claim that it was; make that claim only from a real run.
    """
    assert case["verified_against_catalog"] is False, (
        f"{case['query_id']} claims live verification. If that is real, record "
        "the run; if it is aspirational, set it back to false."
    )
