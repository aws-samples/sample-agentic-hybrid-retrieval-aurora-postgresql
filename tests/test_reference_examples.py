"""Reviewed references must retain their labels without becoming catalog truth."""

import copy
import json
from pathlib import Path

import pytest

from scripts.prepare_reference_examples import validate_bundle

ROOT = Path(__file__).resolve().parents[1]


def bundle():
    return json.loads(
        (ROOT / "data/evals/references/reviewed_sources.json").read_text()
    )


def test_all_three_needs_and_both_sources_are_verified():
    result = validate_bundle(bundle())
    assert result["cases"] == 5
    assert result["products"] == 10
    assert result["categories"] == ["chairs", "headphones", "monitors"]
    assert result["datasets"] == ["esci", "wands"]


@pytest.mark.parametrize(
    "fault",
    [
        "identity",
        "label",
        "conflict",
        "locale",
        "quote",
        "cross_dataset",
        "coverage",
        "empty_pair",
        "displayed_value",
        "query",
    ],
)
def test_reference_gate_fails_on_material_corruption(fault):
    data = bundle()
    product = data["cases"][0]["products"][0]
    if fault == "identity":
        product["original"]["product_id"] = "OTHER"
    elif fault == "label":
        product["label"] = "I"
    elif fault == "conflict":
        other = copy.deepcopy(product["original_judgments"][0])
        other["esci_label"] = "I"
        product["original_judgments"].append(other)
    elif fault == "locale":
        product["original_judgments"][0]["product_locale"] = "es"
    elif fault == "quote":
        data["cases"][-1]["products"][0]["facts"][0]["source_token"] = (
            "numberofscreens:3"
        )
    elif fault == "displayed_value":
        data["cases"][-1]["products"][0]["facts"][0]["value"] = "3"
    elif fault == "query":
        data["cases"][-1]["query"] = "single monitor stand"
    elif fault == "cross_dataset":
        data["cases"][-1]["products"][0]["catalog_product_id"] = 1170423
    elif fault == "coverage":
        data["cases"] = [c for c in data["cases"] if c["category"] != "headphones"]
    elif fault == "empty_pair":
        data["cases"][0]["products"] = []
    with pytest.raises(ValueError, match="rule:"):
        validate_bundle(data)


def test_review_copy_does_not_change_source_verification():
    data = bundle()
    original_result = validate_bundle(data)
    data["cases"][0]["products"][0]["reading_note"] = "Rephrased explanation."
    assert validate_bundle(data) == original_result


def test_references_are_linked_to_the_reviewed_current_products():
    reviewed = json.loads(
        (ROOT / "data/evals/reviewed_product_examples.json").read_text()
    )
    products = {p["parent_asin"]: p for c in reviewed["cases"] for p in c["products"]}
    checked = 0
    for case in bundle()["cases"]:
        if case["dataset"] != "esci":
            continue
        for reference in case["products"]:
            current = products[reference["source_product_id"]]
            assert reference["catalog_product_id"] == current["product_id"]
            assert reference["catalog_source_sha256"] == current["source_record_sha256"]
            assert reference["label"] == current["source_label"]["label"]
            assert case["query_id"] == current["source_label"]["query_id"]
            checked += 1
    assert checked == 6
