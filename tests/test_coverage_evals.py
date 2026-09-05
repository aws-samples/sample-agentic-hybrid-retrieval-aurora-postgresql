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

from scripts.retrieval_profile import load_profile

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
    "measured",
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


def test_identifier_cases_are_decidable_without_the_floor():
    """Identifier-shaped tokens take no trigram rescue, so their confidence does
    not depend on `coverage.similarity_floor`. At least one such case must
    exist: the word-shaped half of the calibration is separated by 0.019 of
    trigram similarity on this corpus, and a set with no floor-free negative
    would have nothing left if that margin ever closed."""
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
def test_a_case_claiming_verification_carries_the_run_that_verified_it(case):
    """Guards the house rule against inventing measured data.

    `verified_against_catalog: true` is a claim that this query was classified
    by the live cluster. The claim is only checkable if the run is recorded, so
    a case making it must ship a `measured` block naming the day, the floor, and
    a verdict per token -- and that block must agree with what the case expects,
    or the set is asserting two different things at once.

    The whole set was measured on 2026-09-04 against the 500,000-product Aurora
    corpus. `tests/test_coverage.py` replays every one of them.
    """
    measured = case["measured"]
    assert case["verified_against_catalog"] is True, (
        f"{case['query_id']} is unverified. Run it against the cluster and "
        "record the result, or delete it from the set."
    )
    assert measured["measured_on"], f"{case['query_id']} records no measurement date"
    assert measured["confidence"] == case["expected_confidence"], (
        f"{case['query_id']} expects {case['expected_confidence']} but the "
        f"recorded run produced {measured['confidence']}"
    )
    assert measured["terms"], f"{case['query_id']} records no per-token verdicts"
    for term in measured["terms"]:
        assert term["token"] in case["query"], (
            f"{case['query_id']} records a verdict for {term['token']!r}, which "
            "is not in its query"
        )
        assert term["verdict"] in {
            "matched",
            "recoverable",
            "unmatched_anchor",
            "ignored",
        }
    refused = [
        t["token"] for t in measured["terms"] if t["verdict"] == "unmatched_anchor"
    ]
    assert refused == measured["unmatched_terms"]
    if case["expected_unmatched_terms"]:
        assert measured["unmatched_terms"] == case["expected_unmatched_terms"]


def test_every_case_was_measured_at_the_floor_the_yaml_declares():
    """A recorded run at a floor the profile no longer serves is not evidence
    about the shipped system. Editing `coverage.similarity_floor` without
    re-measuring the set turns this red, which is the point."""
    floor = load_profile().coverage_similarity_floor
    for case in _cases():
        assert case["measured"]["similarity_floor"] == floor, (
            f"{case['query_id']} was measured at "
            f"{case['measured']['similarity_floor']} but db/config/retrieval.yaml "
            f"declares {floor}; fix: re-run the set against the live cluster and "
            "record the new verdicts, or restore the floor"
        )


def test_the_calibration_cases_still_bracket_the_floor():
    """The two tokens the floor sits between, asserted as data rather than prose.

    Measured 2026-09-04: 'enough' (C-105, must be rescued) reaches 0.250 and
    'Zylthorne' (C-005, must be refused) reaches 0.231. Any floor outside that
    interval reds one of them. This test states the interval so that a future
    edit to either case cannot quietly remove the evidence the floor rests on.
    """
    by_id = {case["query_id"]: case for case in _cases()}
    rescued = next(
        t for t in by_id["C-105"]["measured"]["terms"] if t["token"] == "enough"
    )
    refused = next(
        t for t in by_id["C-005"]["measured"]["terms"] if t["token"] == "Zylthorne"
    )
    assert rescued["verdict"] == "recoverable"
    assert refused["verdict"] == "unmatched_anchor"
    floor = load_profile().coverage_similarity_floor
    assert refused["similarity"] < floor <= rescued["similarity"]
