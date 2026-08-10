"""Contract-level invariants that hold across both mission lists.

Shape and budget rules live in `scripts/mission_contract.py` (the gate) so there
is one implementation; these checks cover what the gate deliberately does not —
that both lists resolve against the curated demo products the UI and eval
harness read, and that the two lists together still cover every stage the
`MosaicLabStage` union declares.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "data/evals/mosaic_labs_missions.json"

CONTRACT = json.loads(MISSION_PATH.read_text(encoding="utf-8"))
ALL_MISSIONS = CONTRACT["missions"] + CONTRACT["self_paced"]


def test_the_session_budget_is_internally_consistent():
    session = CONTRACT["session"]
    timed = CONTRACT["missions"]

    assert CONTRACT["name"] == "Mosaic Labs Golden Missions"
    assert sum(m["duration_minutes"] for m in timed) == session["core_lab_minutes"]
    assert (
        session["orientation_minutes"]
        + session["core_lab_minutes"]
        + session["scorecard_minutes"]
        == session["total_minutes"]
    )


def test_both_lists_together_cover_every_stage_and_checkpoint():
    """Retiring a mission must not retire a stage the UI still renders copy for."""
    assert {
        "recover",
        "retrieve",
        "rank",
        "reason",
        "optimize",
    } == {mission["stage"] for mission in ALL_MISSIONS}
    assert {mission["checkpoint"] for mission in ALL_MISSIONS} >= {
        "baseline",
        "repair",
        "comparison",
        "advanced",
    }


def test_the_core_flag_agrees_with_the_list_a_mission_sits_in():
    """The UI narrows on `core`; the gate splits on the list. They must agree."""
    assert all(mission["core"] for mission in CONTRACT["missions"])
    assert not any(mission["core"] for mission in CONTRACT["self_paced"])


def test_golden_targets_are_curated_products():
    curated = {
        int(product["product_id"])
        for product in json.loads(
            (ROOT / "data/curated/demo_products.json").read_text(encoding="utf-8")
        )
    }

    for mission in ALL_MISSIONS:
        assert mission["target_product_ids"], mission["id"]
        assert set(mission["target_product_ids"]) <= curated, mission["id"]
        assert mission["top_k"] >= 1
        assert mission["assertions"]
