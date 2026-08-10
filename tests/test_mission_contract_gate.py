"""The gate must fail on the defects it exists to catch.

A gate that cannot fail is worse than no gate, because it reads as evidence.
These checks drive `scripts/mission_contract.py` against deliberately broken
contracts and assert the specific rule fires. Shape checks only — no database —
so this suite runs anywhere; the live checks are exercised by
`make validate-missions` against Aurora.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts.mission_contract import (
    REQUIRED_RETIRED_FIELDS,
    Report,
    check_shape,
    load_contract,
    split_missions,
    stage_union,
)

ROOT = Path(__file__).resolve().parents[1]


def failures_for(contract: dict) -> list[str]:
    report = Report()
    check_shape(contract, report)
    return report.failures


def rules_failing(contract: dict) -> set[str]:
    """The rule ids that fired, e.g. {"A1.1", "A1.7"}."""
    return {failure.split()[0] for failure in failures_for(contract)}


@pytest.fixture
def passing() -> dict:
    """A contract shaped the way Unit B will leave it."""
    from service.assertions import SIGNAL_ASSERTIONS

    contract = copy.deepcopy(load_contract())
    keep = {"typo-recovery", "rank-with-evidence", "agentic-research"}
    timed = [m for m in contract["missions"] if m["id"] in keep]
    retired = [m for m in contract["missions"] if m["id"] not in keep]

    technique_to_assertion = {v: k for k, v in SIGNAL_ASSERTIONS.items()}
    for mission in timed + retired:
        for technique in set(mission["expected_techniques"]) & set(
            technique_to_assertion
        ):
            needed = technique_to_assertion[technique]
            if needed not in mission["assertions"]:
                mission["assertions"].append(needed)

    for mission, minutes in zip(timed, (11, 12, 11)):
        mission["duration_minutes"] = minutes

    contract["missions"] = timed
    contract["self_paced"] = retired
    contract["session"] = {
        "total_minutes": 40,
        "orientation_minutes": 2,
        "core_lab_minutes": 34,
        "scorecard_minutes": 4,
    }
    return contract


def test_the_target_shape_passes_every_check(passing):
    assert failures_for(passing) == []


def test_the_shipped_contract_fails_today(passing):
    """Documents first contact: the gate must not be green on the current file."""
    rules = rules_failing(load_contract())
    assert "A1.1" in rules, "five timed missions must fail the count check"
    assert "A1.4b" in rules, "47 minutes of content must fail the nominal check"
    assert "A1.7" in rules, "declared arms without assertions must fail"


def test_a_fourth_timed_mission_fails(passing):
    passing["missions"].append(dict(passing["missions"][0], id="invented-fourth"))
    assert "A1.1" in rules_failing(passing)


def test_a_mission_in_both_lists_fails(passing):
    passing["self_paced"].append(copy.deepcopy(passing["missions"][0]))
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
        ({"total_minutes": 45}, "A1.4c"),
        ({"total_minutes": 41}, "A1.4c"),
        ({"orientation_minutes": 10}, "A1.4b"),
        ({"scorecard_minutes": 10}, "A1.4b"),
    ],
)
def test_a_budget_that_programs_the_ceiling_fails(
    passing, session_patch, expected_rule
):
    """45 is a ceiling, not a target: declaring it is a failure."""
    passing["session"].update(session_patch)
    assert expected_rule in rules_failing(passing)


def test_forty_one_minutes_of_exercises_fails_the_lab_frame(passing):
    passing["missions"][0]["duration_minutes"] = 41 - sum(
        m["duration_minutes"] for m in passing["missions"][1:]
    )
    assert "A1.4a" in rules_failing(passing)


@pytest.mark.parametrize("field", REQUIRED_RETIRED_FIELDS)
def test_every_required_retired_field_is_enforced(passing, field):
    """The list is enumerated in the spec; each entry must actually be checked."""
    passing["self_paced"][0].pop(field, None)
    rules = rules_failing(passing)
    # Dropping `id` also breaks the disjointness report, so accept either rule.
    assert rules & {"A1.5", "A1.2"}, f"removing {field!r} was not caught"


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


def test_the_gate_reads_core_flags_before_unit_b_introduces_self_paced():
    """Until Unit B lands there is no self_paced key; the gate must still work."""
    contract = copy.deepcopy(load_contract())
    assert "self_paced" not in contract
    timed, retired = split_missions(contract)
    assert [m["id"] for m in retired] == ["hnsw-performance"]
    assert all(m["core"] for m in timed)


def test_required_retired_fields_match_the_spec():
    """The enumeration is a contract with the spec, not an implementation detail."""
    spec = (
        ROOT / "docs" / "superpowers" / "specs" / "2026-08-10-phase2-design.md"
    ).read_text(encoding="utf-8")
    for field in REQUIRED_RETIRED_FIELDS:
        assert f"`{field}`" in spec, f"{field!r} is enforced but not in the spec"
