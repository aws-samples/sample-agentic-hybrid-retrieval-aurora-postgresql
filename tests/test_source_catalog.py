"""Falsify the boundaries between source facts, offers, ratings and reviews."""

import copy

import pytest

from scripts.prepare_real_catalog import canonical, embedding_text, sha256
from service.source_catalog import (
    historical_price,
    product_kind,
    project_product,
    rerank_document,
    review_evidence,
    specification_evidence,
)


def test_reranking_keeps_exact_identity_separate_from_unchanged_source_text():
    source_text = "27-inch monitor\nUSB-C connector.\n"
    document = rerank_document("b01g8jo5f2", source_text)
    identity, preserved_text = document.split("\n", 1)
    assert "b01g8jo5f2" in identity
    assert preserved_text == source_text


def source_row(**changes):
    original = {
        "parent_asin": "PARENT0001",
        "title": "27-inch USB-C monitor",
        "categories": ["Electronics", "Monitors"],
        "description": ["Original source description."],
        "features": ["USB-C connector."],
        "details": {"Brand": "Source brand", "Screen Size": "27 Inches"},
        "price": None,
        "images": [{"variant": "MAIN", "hi_res": "https://example.com/source.jpg"}],
        "average_rating": 4.4,
        "rating_number": 123,
        **changes,
    }
    text = embedding_text(original)
    return {
        "parent_asin": original["parent_asin"],
        "source_department": "Electronics",
        "original": original,
        "source_record_sha256": sha256(canonical(original)),
        "embedding_text": text,
        "embedding_text_sha256": sha256(text),
        "image_url": "https://example.com/source.jpg",
        "embedding_model_key": None,
    }


def test_missing_price_and_stock_remain_unknown_even_when_a_rating_exists():
    projected = project_product(source_row())
    assert projected["historical_price_cents"] is None
    assert projected["current_price_cents"] is None
    assert projected["availability"] is None
    assert projected["inventory_count"] is None
    assert projected["rating"] == {
        "average": 4.4,
        "count": 123,
        "basis": "historical_rating_aggregate",
    }
    assert "review_count" not in projected


def test_a_real_historical_price_never_becomes_a_current_offer():
    row = source_row(price=79.99)
    projected = project_product(row)
    assert projected["historical_price_cents"] == 7999
    assert projected["current_price_cents"] is None
    assert historical_price("0") == 0
    assert historical_price("None") is None
    with pytest.raises(ValueError, match="Source price rule.*inspect"):
        historical_price("79.999")


def test_accessories_do_not_become_the_compatible_products_named_in_the_title():
    row = source_row(
        title="Case compatible with famous noise-cancelling headphones",
        categories=["Electronics", "Headphones, Earbuds & Accessories", "Cases"],
    )
    assert project_product(row)["product_kind"] == "headphone_case"
    assert product_kind(["Office Products", "Chair Mats"]) == "chair_mat"
    assert product_kind(["Electronics", "Over-Ear Headphones"]) == "headphones"


@pytest.mark.parametrize(
    "leaf",
    [
        "On-Ear Headphones",
        "Earbud Headphones",
        "Open-Ear Headphones",
        "Headphones & Earbuds",
        "Computer Headsets",
        "Headphones",
        "Bluetooth Headsets",
        "Cell Phone Headsets",
        "Car Headphones",
    ],
)
def test_source_headphone_types_are_not_hidden_by_the_headphones_filter(leaf):
    assert product_kind(["Electronics", leaf]) == "headphones"


@pytest.mark.parametrize(
    "leaf",
    [
        "Guest & Reception Chairs",
        "Drafting Chairs",
        "Stacking Chairs",
    ],
)
def test_source_office_chairs_are_not_hidden_by_the_chair_filter(leaf):
    assert (
        product_kind(["Office Products", "Office Furniture & Lighting", leaf])
        == "chair"
    )


@pytest.mark.parametrize("parent", ["Telephone Accessories", "PC Gaming Accessories"])
def test_generic_headsets_require_a_reviewed_source_parent(parent):
    assert product_kind(["Electronics", parent, "Headsets"]) == "headphones"


@pytest.mark.parametrize(
    "path, expected",
    [
        (["Electronics", "Headphones", "Earpads"], "other"),
        (["Electronics", "Headphones", "Adapters"], "other"),
        (["Electronics", "Headphones", "Cases"], "headphone_case"),
        (["Office Products", "Chairs", "Chair Arms"], "other"),
        (["Office Products", "Chair Mats", "Carpet Chair Mats"], "chair_mat"),
        (["Office Products", "Chair Mats", "Hard-Floor Chair Mats"], "chair_mat"),
        (["Furniture", "Chairs & Sofas"], "other"),
        (["Sporting Goods", "Cycling", "Headsets"], "other"),
        (["Electronics", "Headsets & Microphones"], "other"),
        ([], "other"),
    ],
)
def test_accessories_and_ambiguous_source_categories_stay_distinct(path, expected):
    assert product_kind(path) == expected


def test_source_price_placeholder_and_starting_price_do_not_become_exact_offers():
    missing = project_product(source_row(price="—"))
    assert missing["historical_price_cents"] is None
    assert missing["historical_price_basis"] == "not_reported"
    starting = project_product(source_row(price="from 5.99"))
    assert starting["historical_price_cents"] is None
    assert starting["historical_price_min_cents"] == 599
    assert starting["historical_price_basis"] == "starting_at"
    assert starting["historical_price_source_value"] == "from 5.99"
    assert starting["current_price_cents"] is None


def test_unknown_condition_and_unreported_charging_are_not_invented():
    result = project_product(source_row())
    assert result["condition"] == "unspecified"
    assert result["condition_source"] is None
    assert result["features"] == ["USB-C connector."]
    assert "usb_c_power_w" not in result["specifications"]
    renewed = project_product(source_row(title="27-inch monitor (Renewed)"))
    assert renewed["condition"] == "refurbished"
    assert renewed["condition_source"] == "/title"


def test_another_products_photo_cannot_be_attached_to_the_source_identity():
    row = source_row()
    row["image_url"] = "https://example.com/another-product.jpg"
    with pytest.raises(ValueError, match="Source photo rule.*restore"):
        project_product(row)


def test_source_rewrite_is_red_at_birth_and_restoration_is_byte_identical():
    row = source_row()
    saved = canonical(row)
    row["original"]["features"] = ["USB-C laptop charging at 90 W."]
    with pytest.raises(ValueError, match="Source product integrity rule.*restore"):
        project_product(row)
    import json

    row = json.loads(saved)
    assert canonical(row) == saved
    result = specification_evidence(row)
    assert result["text"] == row["embedding_text"]
    assert result["evidence_id"].endswith(row["source_record_sha256"])
    other = copy.deepcopy(row)
    other["image_url"] = "https://example.com/higher-resolution.jpg"
    assert specification_evidence(other) == result


def test_review_retains_variant_and_verification_but_does_not_expose_reviewer_id():
    original = {
        "parent_asin": "PARENT0001",
        "asin": "VARIANT001",
        "user_id": "private-from-display",
        "title": "A reviewer opinion",
        "text": "Works well for me.",
        "rating": 4,
        "verified_purchase": False,
        "helpful_vote": 3,
        "timestamp": 1600000000000,
    }
    row = {
        "parent_asin": "PARENT0001",
        "variant_asin": "VARIANT001",
        "original": original,
        "source_record_sha256": sha256(canonical(original)),
        "source_reference": "https://example.com/source",
        "source_location": {"offset": 100, "length": 200},
        "evidence_id": "review-source",
    }
    projected = review_evidence(row)
    assert projected["variant_asin"] == "VARIANT001"
    assert projected["parent_asin"] == "PARENT0001"
    assert projected["verified_purchase"] is False
    assert projected["source_date"] == "2020-09-13"
    assert "user_id" not in projected
    row["parent_asin"] = "OTHER00001"
    with pytest.raises(ValueError, match="Review product boundary rule.*restore"):
        review_evidence(row)


@pytest.mark.parametrize("leaf", ["Monitor Arms", "Monitor Stands"])
def test_monitor_supports_are_distinct_from_display_panels(leaf):
    assert product_kind(["Electronics", "Monitor Accessories", leaf]) == "monitor_stand"
