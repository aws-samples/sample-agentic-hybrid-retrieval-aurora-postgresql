"""Contract-level invariants that hold across labs and supporting checks.

Shape and budget rules live in `scripts/mission_contract.py` (the gate) so there
is one implementation; these checks cover what the gate deliberately does not —
that all entries resolve against the curated demo products the UI and eval
harness read, and that the lists together still cover every stage the
`MosaicLabStage` union declares.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "data/evals/mosaic_labs_missions.json"

CONTRACT = json.loads(MISSION_PATH.read_text(encoding="utf-8"))
ALL_CHECKS = CONTRACT["missions"] + CONTRACT["supporting_checks"]


def test_the_session_budget_is_internally_consistent():
    session = CONTRACT["session"]
    timed = CONTRACT["missions"]

    assert CONTRACT["name"] == "Mosaic Retrieve Rank Reason Lab Contract"
    assert sum(m["duration_minutes"] for m in timed) == session["core_lab_minutes"]
    assert (
        session["orientation_minutes"]
        + session["core_lab_minutes"]
        + session["scorecard_minutes"]
        + session["contingency_minutes"]
        == session["total_minutes"]
    )


def test_both_lists_together_cover_every_stage_and_checkpoint():
    assert {
        "retrieve",
        "rank",
        "reason",
        "optimize",
    } == {check["stage"] for check in ALL_CHECKS}
    assert {check["checkpoint"] for check in ALL_CHECKS} >= {
        "baseline",
        "repair",
        "advanced",
    }


def test_core_flags_distinguish_required_checkpoints_from_advanced_labs():
    assert all(lab["core"] for lab in CONTRACT["missions"])
    supporting = {check["id"]: check for check in CONTRACT["supporting_checks"]}
    assert supporting["exact-identity"]["core"] is True
    assert supporting["semantic-intent-contrast"]["core"] is False
    assert supporting["semantic-eligibility"]["core"] is True
    assert supporting["compare-cheaper-alternative"]["core"] is True
    assert supporting["ranking-filter-control"]["core"] is True
    assert supporting["evidence-grounding"]["core"] is True
    assert supporting["hnsw-performance"]["core"] is False


def test_eight_participant_queries_are_distributed_across_three_labs():
    participant_checks = CONTRACT["missions"] + [
        check for check in CONTRACT["supporting_checks"] if check["core"]
    ]
    assert len(participant_checks) == 8
    assert {
        check["placement"] for check in CONTRACT["supporting_checks"] if check["core"]
    } == {"lab-1", "lab-2", "lab-3"}


def test_each_required_lab_declares_golden_before_and_after_observations():
    for lab in CONTRACT["missions"]:
        edit = lab["participant_edit"]
        assert 5 <= edit["approximate_lines"] <= 15
        assert len(edit["observe_before"]) >= 2
        assert len(edit["observe_after"]) >= 2
        assert edit["checkpoint_question"].endswith("?")


def test_every_retrieval_scenario_has_a_distinct_discover_label():
    labels = [check["discover_label"] for check in ALL_CHECKS]

    assert all(label.strip() for label in labels)
    assert len(set(labels)) == len(labels)


def test_golden_targets_are_curated_products():
    curated = {
        int(product["product_id"])
        for product in json.loads(
            (ROOT / "data/curated/demo_products.json").read_text(encoding="utf-8")
        )
    }

    for check in ALL_CHECKS:
        assert check["target_product_ids"], check["id"]
        assert set(check["target_product_ids"]) <= curated, check["id"]
        assert check["top_k"] >= 1
        assert check["assertions"]
