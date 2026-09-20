"""Catalog names must not route unrelated products into another specification set."""

from __future__ import annotations

import random

import pytest

from scripts.generate_catalog import ProductContext, specialized_attributes


@pytest.mark.parametrize(
    "subcategory,category,required,forbidden",
    [
        ("Mesh Office Chairs", "Seating", "lumbar_support", "wifi_generation"),
        ("Monitor Arms", "Displays", "max_screen_in", "resolution"),
        ("Monitor Light Bars", "Lighting", "lumens", "panel"),
        ("Air Quality Monitors", "Air & Environment", "measures", "resolution"),
        ("Heart Rate Monitors", "Wearables", "sensor_type", "refresh_hz"),
        ("Desk Lamps", "Lighting", "lumens", "load_capacity_lb"),
        ("Desk Dividers", "Acoustics", "mounting", "memory_presets"),
        ("Desk Fans", "Air & Environment", "speed_levels", "load_capacity_lb"),
        ("Keyboard Trays", "Ergonomics", "mounting", "switch_type"),
        ("Game Controllers", "Gaming", "buttons", "firmness"),
        ("Shoe Care", "Accessories", "kit_contents", "carbon_plate"),
        ("Camera Lenses", "Imaging", "focal_length_mm", "resolution_mp"),
        ("Gimbals", "Imaging", "payload_kg", "video"),
        ("Graphic Tablets", "Input Devices", "pressure_levels", "processor_tier"),
    ],
)
def test_category_name_selects_appropriate_specifications(
    subcategory, category, required, forbidden
):
    ctx = ProductContext(
        product_id=900001,
        domain="home_office",
        category=category,
        subcategory=subcategory,
        ordinal=1,
    )
    attrs, _, _, _ = specialized_attributes(ctx, random.Random(7), [])
    assert required in attrs, f"{subcategory} needs {required}, found {attrs}"
    assert forbidden not in attrs, f"{subcategory} incorrectly has {forbidden}: {attrs}"


def test_repair_preserves_identity_and_ignores_valid_lamp_memory_setting():
    from scripts.catalog_semantics import misplaced_fields

    assert not misplaced_fields(
        "Desk Lamps", {"brightness_lm": 400, "memory_presets": 0}
    )
    assert misplaced_fields("Desk Lamps", {"depth_in": 30, "memory_presets": 4}) == {
        "depth_in"
    }


def test_warranty_only_repair_does_not_change_embedding_input():
    from scripts.catalog_semantics import repair_catalog_row

    row = {
        "product_id": "900001",
        "title": "Example",
        "subcategory": "Phone Cases",
        "attributes_json": "{}",
        "tags_json": "[]",
        "aliases_json": "[]",
        "short_description": "Fabric sleeve.",
        "long_description": "Fabric sleeve. Warranty: 24 months.",
        "warranty_months": "12",
        "embedding_text": "preserved",
        "price_usd": "19.99",
        "sku": "EXAMPLE",
    }
    result, changes = repair_catalog_row(row)
    assert changes == ["warranty-offer-agreement"]
    assert result == {**row, "warranty_months": "24"}
    assert repair_catalog_row(result) == (result, [])


def test_disclaimed_certification_is_not_left_in_searchable_attributes():
    import json

    from scripts.catalog_semantics import repair_catalog_row

    row = {
        "product_id": "900003",
        "title": "Example 4K Webcam",
        "brand": "Example",
        "model": "4K",
        "category": "Collaboration",
        "subcategory": "Webcams",
        "attributes_json": '{"certified_platforms":["Zoom"],"privacy_shutter":true}',
        "tags_json": "[]",
        "aliases_json": "[]",
        "short_description": "4K webcam with privacy shutter.",
        "long_description": "No platform approvals are claimed here.",
        "warranty_months": "12",
    }
    repaired, changes = repair_catalog_row(row)
    assert changes == ["disclaimed-certification"]
    assert json.loads(repaired["attributes_json"]) == {"privacy_shutter": True}
    assert "certified_platforms" not in repaired["embedding_text"]
    assert repair_catalog_row(repaired) == (repaired, [])
    ordinary = {**row, "attributes_json": '{"privacy_shutter":true}'}
    assert repair_catalog_row(ordinary) == (ordinary, [])
