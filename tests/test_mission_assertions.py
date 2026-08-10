"""The lexical arm can fail completely; an assertion has to notice.

`mosaic_search.search_fts` shipped an AND-only tsquery. Four of the six missions
lost the arm entirely and every gate stayed green, because no assertion in the
vocabulary named the lexical arm. These checks exercise `fts_signal_present` and
keep the contract and the vocabulary from drifting apart.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from service.assertions import (
    KNOWN_ASSERTIONS,
    SIGNAL_ASSERTIONS,
    UnknownAssertionError,
    arm_signal_present,
    evaluate_signal_assertions,
    signal_assertions_for,
)

ROOT = Path(__file__).resolve().parents[1]
MISSIONS = json.loads(
    (ROOT / "data/evals/mosaic_labs_missions.json").read_text(encoding="utf-8")
)["missions"]

# What the engine reports when every arm contributed.
HEALTHY_COUNTS = {
    "fused_pool": 50,
    "fts_in_pool": 24,
    "trigram_in_pool": 18,
    "semantic_in_pool": 40,
}


def test_fts_signal_present_is_defined():
    assert "fts_signal_present" in KNOWN_ASSERTIONS
    assert SIGNAL_ASSERTIONS["fts_signal_present"] == "fts"


def test_fts_signal_fails_when_the_arm_returns_no_rows():
    """The exact regression: the arm ran, matched nothing, and nobody noticed."""
    stubbed = dict(HEALTHY_COUNTS, fts_in_pool=0)
    assert arm_signal_present(HEALTHY_COUNTS, "fts") is True
    assert arm_signal_present(stubbed, "fts") is False


def test_every_fts_declaring_mission_asserts_the_lexical_arm():
    declaring = [m for m in MISSIONS if "fts" in m["expected_techniques"]]
    assert declaring, "the contract must still declare fts somewhere"
    for mission in declaring:
        assert "fts_signal_present" in mission["assertions"], mission["id"]


def test_missions_that_do_not_declare_fts_are_not_asserted_on_it():
    """A principled abstention must stay a pass, not become a false failure."""
    for mission in MISSIONS:
        if "fts" not in mission["expected_techniques"]:
            assert "fts_signal_present" not in mission["assertions"], mission["id"]
            assert "fts_signal_present" not in signal_assertions_for(
                mission["expected_techniques"]
            )


def test_signal_assertions_are_scoped_to_declared_arms():
    assert signal_assertions_for(["fts"]) == ["fts_signal_present"]
    assert "trigram_signal_present" in signal_assertions_for(["fts", "pg_trgm"])
    assert signal_assertions_for(["hnsw"]) == ["semantic_signal_present"]
    assert signal_assertions_for([]) == []


def test_dead_lexical_arm_fails_the_missions_that_declare_it():
    stubbed = dict(HEALTHY_COUNTS, fts_in_pool=0)
    for mission in MISSIONS:
        if "fts" not in mission["expected_techniques"]:
            continue
        healthy = evaluate_signal_assertions(mission, HEALTHY_COUNTS)
        assert healthy["fts_signal_present"] is True, mission["id"]
        dead = evaluate_signal_assertions(mission, stubbed)
        assert dead["fts_signal_present"] is False, mission["id"]


def test_every_assertion_named_by_the_contract_is_defined():
    """A name nobody resolves is a name nobody can trust."""
    for mission in MISSIONS:
        unknown = set(mission["assertions"]) - KNOWN_ASSERTIONS
        assert not unknown, f"{mission['id']} names undefined {sorted(unknown)}"


def test_an_undefined_assertion_is_refused_rather_than_ignored():
    mission = {"id": "invented", "assertions": ["target_in_top_k", "no_such_signal"]}
    with pytest.raises(UnknownAssertionError) as excinfo:
        evaluate_signal_assertions(mission, HEALTHY_COUNTS)
    assert "no_such_signal" in str(excinfo.value)


def test_a_missing_count_key_does_not_read_as_a_healthy_arm():
    """Absent evidence is not evidence of a working arm."""
    assert arm_signal_present({}, "fts") is False
    assert arm_signal_present({"fused_pool": 50}, "pg_trgm") is False
