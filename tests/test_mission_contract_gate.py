"""The gate must fail on the defects it exists to catch.

A gate that cannot fail is worse than no gate, because it reads as evidence.
These checks drive `scripts/mission_contract.py` against deliberately broken
contracts and assert the specific rule fires. Shape checks only — no database —
so this suite runs anywhere; the live checks are exercised by
`make validate-missions` against Aurora.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from scripts.mission_contract import (
    REQUIRED_SUPPORTING_FIELDS,
    Report,
    check_shape,
    load_contract,
    split_missions,
    stage_union,
)

def failures_for(contract: dict) -> list[str]:
    report = Report()
    check_shape(contract, report)
    return report.failures


def rules_failing(contract: dict) -> set[str]:
    """The rule ids that fired, e.g. {"A1.1", "A1.7"}."""
    return {failure.split()[0] for failure in failures_for(contract)}


@pytest.fixture
def passing() -> dict:
    """The shipped contract, which Unit B left in the shape the gate demands.

    Every mutation test below starts from the real file rather than a synthetic
    stand-in, so a check cannot pass against a fixture that has drifted from what
    actually ships.
    """
    return copy.deepcopy(load_contract())


def test_the_shipped_contract_passes_every_shape_check(passing):
    assert failures_for(passing) == []


def test_the_shipped_contract_has_three_labs_and_supporting_checks(passing):
    labs, supporting = split_missions(passing)
    assert [m["id"] for m in labs] == [
        "typo-recovery",
        "rank-with-evidence",
        "agentic-research",
    ]
    assert [m["id"] for m in supporting] == [
        "exact-identity",
        "semantic-intent-contrast",
        "semantic-eligibility",
        "compare-cheaper-alternative",
        "ranking-filter-control",
        "evidence-grounding",
        "hnsw-performance",
    ]
    session = passing["session"]
    assert session["total_minutes"] == 60
    assert (
        session["orientation_minutes"]
        + sum(m["duration_minutes"] for m in labs)
        + session["scorecard_minutes"]
        == 60
    )


def test_a_fourth_required_lab_fails(passing):
    passing["missions"].append(dict(passing["missions"][0], id="invented-fourth"))
    assert "A1.1" in rules_failing(passing)


def test_a_check_in_both_lists_fails(passing):
    passing["supporting_checks"].append(copy.deepcopy(passing["missions"][0]))
    assert "A1.2" in rules_failing(passing)


def test_an_orphan_stage_in_the_union_fails(passing, monkeypatch):
    """A union member no mission uses is drift, and drift is how stages rot."""
    import scripts.mission_contract as gate

    monkeypatch.setattr(gate, "stage_union", lambda: stage_union() | {"invented"})
    assert "A1.3" in rules_failing(passing)


def test_a_mission_stage_missing_from_the_union_fails(passing):
    passing["missions"][0]["stage"] = "not-in-the-union"
    assert "A1.3" in rules_failing(passing)


@pytest.mark.parametrize(
    ("session_patch", "expected_rule"),
    [
        ({"total_minutes": 59}, "A1.4c"),
        ({"total_minutes": 61}, "A1.4c"),
        ({"orientation_minutes": 9}, "A1.4b"),
        ({"scorecard_minutes": 6}, "A1.4b"),
    ],
)
def test_a_budget_that_does_not_match_the_sixty_minute_program_fails(
    passing, session_patch, expected_rule
):
    passing["session"].update(session_patch)
    assert expected_rule in rules_failing(passing)


def test_a_lab_budget_other_than_forty_seven_minutes_fails(passing):
    passing["missions"][0]["duration_minutes"] -= 1
    assert "A1.4a" in rules_failing(passing)


@pytest.mark.parametrize("field", REQUIRED_SUPPORTING_FIELDS)
def test_every_required_supporting_field_is_enforced(passing, field):
    passing["supporting_checks"][0].pop(field, None)
    rules = rules_failing(passing)
    # Dropping `id` also breaks the disjointness report, so accept either rule.
    assert rules & {"A1.5", "A1.2"}, f"removing {field!r} was not caught"


def test_the_gate_reads_the_supporting_checks_list_when_present(passing):
    assert "supporting_checks" in passing
    labs, supporting = split_missions(passing)
    assert len(labs) == 3
    assert len(supporting) == 7
    assert all(m["core"] for m in labs)
    assert [m["core"] for m in supporting] == [True, False, True, True, True, True, False]


def test_the_gate_falls_back_to_placement_without_a_supporting_list(passing):
    flattened = dict(passing)
    flattened["missions"] = passing["missions"] + passing["supporting_checks"]
    del flattened["supporting_checks"]
    labs, supporting = split_missions(flattened)
    assert [m["id"] for m in labs] == [m["id"] for m in passing["missions"]]
    assert [m["id"] for m in supporting] == [
        m["id"] for m in passing["supporting_checks"]
    ]


def test_an_undefined_assertion_fails(passing):
    passing["missions"][0]["assertions"].append("no_such_assertion")
    assert "A1.6" in rules_failing(passing)


def test_declares_implies_asserts_for_every_signal_arm(passing):
    from service.assertions import SIGNAL_ASSERTIONS

    technique_to_assertion = {v: k for k, v in SIGNAL_ASSERTIONS.items()}
    for technique, assertion in technique_to_assertion.items():
        contract = copy.deepcopy(passing)
        mission = contract["missions"][0]
        if technique not in mission["expected_techniques"]:
            mission["expected_techniques"].append(technique)
        mission["assertions"] = [a for a in mission["assertions"] if a != assertion]
        assert "A1.7" in rules_failing(contract), (
            f"declaring {technique!r} without {assertion!r} was not caught"
        )


def test_asserting_an_undeclared_arm_is_allowed(passing):
    """The converse is deliberately not checked: it is a stricter promise."""
    mission = passing["missions"][0]
    mission["expected_techniques"] = [
        t for t in mission["expected_techniques"] if t != "pg_trgm"
    ]
    if "trigram_signal_present" not in mission["assertions"]:
        mission["assertions"].append("trigram_signal_present")
    assert "A1.7" not in rules_failing(passing)


def test_an_assertion_without_a_falsifier_is_refused(monkeypatch):
    """A1.8: an assertion that cannot fail reads as evidence while proving nothing.

    The dataclass refuses to build such an assertion, so the gate's own check is
    exercised with a stand-in rather than a real one.
    """
    import scripts.mission_contract as gate

    hollow = SimpleNamespace(name="target_in_top_k", arm=None, falsifier="   ")
    monkeypatch.setattr(
        gate, "ASSERTIONS", dict(gate.ASSERTIONS, target_in_top_k=hollow)
    )
    assert "A1.8" in rules_failing(copy.deepcopy(load_contract()))


def test_the_vocabulary_refuses_a_falsifierless_assertion_at_construction():
    """Defence in depth: the dataclass rejects it before any gate runs."""
    from service.assertions import Assertion

    with pytest.raises(ValueError, match="no falsifier"):
        Assertion(name="invented", arm=None, falsifier="")


def test_every_failure_message_names_the_offending_value_and_a_fix(passing):
    """House standard: name the rule, show the value, suggest the nearest fix."""
    passing["missions"].append(dict(passing["missions"][0], id="invented-fourth"))
    passing["missions"][0]["stage"] = "not-in-the-union"
    passing["supporting_checks"][0].pop("top_k", None)
    failures = failures_for(passing)
    assert failures
    for failure in failures:
        assert "found " in failure, failure
        assert "fix: " in failure, failure


def test_required_supporting_fields_match_the_shipped_contract():
    supporting = load_contract()["supporting_checks"]
    for field in REQUIRED_SUPPORTING_FIELDS:
        assert all(field in check for check in supporting), field
