"""The ESCI judged subset and the k sweep measured on it must stay honest.

The subset is the only judged evidence the labs cite for tuning RRF's k, so its
provenance, its selection rule, and the arithmetic of the sweep are pinned here.
"""

import json
import math
from pathlib import Path

import pytest

from scripts import evaluate_esci_k, prepare_esci_judged_subset

ROOT = Path(__file__).resolve().parents[1]
SUBSET = json.loads((ROOT / "data/evals/esci_judged_subset.json").read_text())
SWEEP = json.loads((ROOT / "data/evals/esci_k_sweep.json").read_text())


def test_subset_names_its_pinned_source_and_license():
    source = SUBSET["source"]
    assert source["sha256"] == prepare_esci_judged_subset.EXAMPLES_SHA256
    assert prepare_esci_judged_subset.SOURCE_COMMIT in source["url"]
    assert source["license"] == "Apache-2.0"
    assert (ROOT / source["license_file"]).exists()


def test_every_case_meets_the_selection_rule():
    assert SUBSET["cases"] == len(SUBSET["queries"])
    for case in SUBSET["queries"]:
        assert (
            case["filters"]["category_key"] in prepare_esci_judged_subset.LAB_CATEGORIES
        )
        assert len(case["judgments"]) >= prepare_esci_judged_subset.MINIMUM_JUDGED
        assert {j["esci_label"] for j in case["judgments"]} <= set("ESCI")
        assert len({j["asin"] for j in case["judgments"]}) == len(case["judgments"])


def test_sweep_covers_the_subset_it_claims():
    assert SWEEP["queries"] == SUBSET["cases"]
    assert SWEEP["exact_judged"] == sum(
        j["esci_label"] == "E" for case in SUBSET["queries"] for j in case["judgments"]
    )
    assert SWEEP["exact_found_by_any_method"] <= SWEEP["exact_judged"]
    for measured in SWEEP["by_k"].values():
        assert measured["exact_in_cutoff"] <= SWEEP["exact_found_by_any_method"]


def test_fusion_breaks_ties_by_product_id():
    arms = {"fts": {9: 1, 4: 2}, "vector": {4: 1, 7: 2}}

    assert evaluate_esci_k.fuse(arms, 60) == [4, 9, 7]


def test_condensed_ndcg_ignores_unjudged_products():
    labels = {1: "E", 2: "I"}

    perfect = evaluate_esci_k.condensed_ndcg([99, 1, 98, 2], labels)
    inverted = evaluate_esci_k.condensed_ndcg([2, 1], labels)

    assert perfect == pytest.approx(1.0)
    assert inverted == pytest.approx((1.0 / math.log2(3)) / 1.0)
