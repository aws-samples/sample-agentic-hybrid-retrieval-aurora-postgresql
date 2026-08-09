import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "data/evals/mosaic_labs_missions.json"


def test_mosaic_labs_mission_contract_is_complete_and_time_bounded():
    contract = json.loads(MISSION_PATH.read_text(encoding="utf-8"))
    missions = contract["missions"]
    core_missions = [mission for mission in missions if mission["core"]]

    assert contract["name"] == "Mosaic Labs Golden Missions"
    assert 45 <= contract["session"]["total_minutes"] <= 50
    assert sum(mission["duration_minutes"] for mission in core_missions) == (
        contract["session"]["core_lab_minutes"]
    )
    assert {
        "recover",
        "retrieve",
        "rank",
        "reason",
        "optimize",
    } == {mission["stage"] for mission in missions}
    assert {mission["checkpoint"] for mission in missions} >= {
        "baseline",
        "repair",
        "comparison",
        "advanced",
    }


def test_mosaic_labs_golden_targets_are_curated_products():
    contract = json.loads(MISSION_PATH.read_text(encoding="utf-8"))
    curated = {
        int(product["product_id"])
        for product in json.loads(
            (ROOT / "data/curated/demo_products.json").read_text(encoding="utf-8")
        )
    }

    for mission in contract["missions"]:
        assert mission["target_product_ids"]
        assert set(mission["target_product_ids"]) <= curated
        assert mission["top_k"] >= 1
        assert mission["assertions"]
