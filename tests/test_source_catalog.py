"""Falsify the boundaries between source facts, offers, ratings and reviews."""

import copy

import pytest

from scripts.catalog.prepare_real_catalog import canonical, embedding_text, sha256
from service.source_catalog import (
    classification_sha256,
    classify_product,
    historical_price,
    product_kind,
    project_product,
    rerank_document,
    review_evidence,
    reviewed_decisions,
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


HEADPHONES = ["Electronics", "Headphones, Earbuds & Accessories", "Headphones"]
MONITORS = ["Electronics", "Computers & Accessories", "Monitors"]
CHAIRS = [
    "Office Products",
    "Office Furniture & Lighting",
    "Chairs & Sofas",
    "Desk Chairs",
]
RANKED = "Best Sellers Rank"


# Permanent false-positive guards: complete products whose titles mention a
# case, casters, a battery or a replacement warranty stay in their category.
@pytest.mark.parametrize(
    "path, title, details",
    [
        (
            HEADPHONES,
            "Koss Porta Pro Classic with Official Hard Carry Case",
            {
                RANKED: {"Electronics": 125013, "On-Ear Headphones": 1632},
                "Form Factor": "Case",
            },
        ),
        (
            HEADPHONES,
            "Jabra Elite 75t – True Wireless Earbuds with Charging Case, Titanium Black",
            {},
        ),
        (
            HEADPHONES,
            (
                "Edifier W820BT Bluetooth Headphones - Foldable Wireless Headphone with "
                "80-Hour Long Battery Life"
            ),
            {},
        ),
        (HEADPHONES, "Sony MDREX110AP - Black (Renewed)", {"Form Factor": "In Ear"}),
        (
            HEADPHONES,
            "Jabra Evolve2 65 UC Wireless Headset with Link380c, Mono, Black",
            {},
        ),
        (HEADPHONES, "Urbeats, Clear", {RANKED: {"Earbud & In-Ear Headphones": 900}}),
        (MONITORS, "MSI Optix MAG274QRF-QD", {RANKED: {"Computer Monitors": 9281}}),
        (MONITORS, "Dell S Series S2415H", {"Refresh Rate": "60 Hz"}),
        (
            MONITORS,
            "LG 32UN500-W 32 inch UHD Monitor with HDR10 AMD FreeSync Bundle with 2X 6FT Cable",
            {},
        ),
        (
            MONITORS,
            (
                'Philips 273V5LHSB 27" Monitor, Full HD 1920x1080, 1ms, VESA, '
                "4Yr Advance Replacement Warranty"
            ),
            {},
        ),
        (
            MONITORS,
            "Kwumsy Triple Laptop Monitor Extender – 360° Rotation Portable Screen",
            {},
        ),
        (CHAIRS, "Steelcase Gesture Office Chair, Licorice", {}),
        (
            CHAIRS,
            "Amazon Basics Low-Back Armless Office Task Desk Chair with Casters, Black",
            {},
        ),
        (CHAIRS, "Ergonomic Mesh Office Chair Adjustable Lumbar Support Headrest", {}),
        (
            CHAIRS,
            "X Rocker, 5129401, Deluxe Mesh Wireless 2.1 Pedestal Gaming, Black/Purple",
            {},
        ),
        # Found in the 2026-09-27 review of the reviews-2023-v2 plan.
        (
            HEADPHONES,
            "Apple MFI Certified Compatible Lightning Headphone/Earphone/Earbud with Mic",
            {},
        ),
        (
            HEADPHONES,
            "Audio Technica ATH-E40 In Ear Monitors w/Extension Cable and Geartree Cloth",
            {"Form Factor": "In Ear"},
        ),
        (
            HEADPHONES,
            (
                "AUGLAMOUR RX-1 Earbuds Stereo Clear Sound Earphones Oxygen-Free Copper "
                "Earphone Cable for iPhones/Android"
            ),
            {},
        ),
        (HEADPHONES, "Jabra Evolve 30 II Replacement Headset Stereo 14401-21", {}),
        (
            MONITORS,
            (
                "2021 Premium HP 27Q Pavilion 27 Inch 2K WQHD 2560x1440 LED VESA Compatible "
                "Monitor, HDMI"
            ),
            {},
        ),
        (MONITORS, "Acer 2 Lamp Series B243Hbdr 24-Inch LCD(Black)", {}),
        (MONITORS, "Samsung S24D300H LED 61CM 24IN Wide", {}),
        (MONITORS, 'Sony SDM-V72W 17" Flat Panel LCD Black', {}),
        (
            CHAIRS,
            "Hillsdale Warrington Wood Adjustable Swivel Caster, Game Chair, Rich Cherry",
            {},
        ),
        (CHAIRS, "Pulse BT BoomChair by Lumisource", {}),
    ],
)
def test_complete_products_and_bundles_keep_their_category(path, title, details):
    kind, reason = classify_product(path, title, details)
    assert kind == product_kind(path), reason


@pytest.mark.parametrize(
    "path, title, details, expected",
    [
        (
            HEADPHONES,
            (
                "Sennheiser HD 280 Pro headband pad Genuine HD280 headphones cushion "
                "replacement padding"
            ),
            {RANKED: {"Headphones & Earbuds": 31892}},
            "headphone_accessory",
        ),
        (
            HEADPHONES,
            "4 Medium Gray Earbuds Eartips Set Compatible with Plantronics Voyager 5200",
            {},
            "headphone_accessory",
        ),
        (
            HEADPHONES,
            "MightySkins Skin Compatible with Skullcandy Hesh 2 Wireless Headphones",
            {},
            "headphone_accessory",
        ),
        (
            CHAIRS,
            'Apontus 24" Replacement Metal Office Chair Base w/ Casters',
            {"Back Style": "Solid Back"},
            "chair_accessory",
        ),
        (
            CHAIRS,
            "Conversion Chair Base Kit for Aeron Chair to Aeron Stool",
            {},
            "chair_accessory",
        ),
        (
            CHAIRS,
            "HON Headrest, Black",
            {RANKED: {"Home Office Desk Chairs": 1100}},
            "chair_accessory",
        ),
        (
            MONITORS,
            "2Pcs Computer Monitor Memo Board for Frameless Monitors",
            {},
            "monitor_accessory",
        ),
        (
            HEADPHONES,
            "Justfitgear Replacement Protein Leather Ear Pads for Sony MDR-7506 Headphones",
            {},
            "headphone_accessory",
        ),
        (
            MONITORS,
            "Original 12.1 Inch 800600 TFT LCD Panel LQ121S1DG11",
            {},
            "monitor_accessory",
        ),
        (
            CHAIRS,
            "Replacement Mirra 1 Chair Seat Pan - Flex Front",
            {},
            "chair_accessory",
        ),
        # Misfiled lab products leave the wrong category but are not refiled:
        # outside their taxonomy path, "monitor" and "seat" name baby monitors
        # and toilet seats as often as the lab products.
        (
            MONITORS,
            "SimpTronic True Wireless Earbuds Bluetooth 5.0 Headphones in-Ear TWS Mini Headset",
            {},
            "other",
        ),
        (HEADPHONES, "Safety 1st Crystal Clear Audio 49 Mhz Baby Monitor", {}, "other"),
        (
            HEADPHONES,
            "YOJA Room Darkening Thermal Insulated Window Blackout Curtains",
            {},
            "other",
        ),
        (HEADPHONES, "LERAMED Posture Corrector for Women Men", {}, "other"),
        (
            MONITORS,
            "Kindle Paperwhite Case, Leafbook Thinnest and Lightest Leather Cover",
            {"Screen Size": "6 Inches"},
            "other",
        ),
        (
            MONITORS,
            "iPhone Xs Max Screen Protector, Clear HD Tempered Glass",
            {},
            "other",
        ),
        (CHAIRS, 'H.B. Smith Heavy Duty Steel Rake, 30"', {}, "other"),
    ],
)
def test_accessories_and_miscategorized_listings_leave_the_lab_categories(
    path, title, details, expected
):
    kind, reason = classify_product(path, title, details)
    assert kind == expected, reason
    assert reason


def test_a_model_only_title_is_kept_by_its_own_features_not_by_its_brand():
    model_only = "Skullcandy Skullcrusher (Discontinued by Manufacturer)"
    features = '["Over-ear headphones with adjustable bass"]'
    assert (
        classify_product(HEADPHONES, model_only, {"Brand": "Skullcandy"}, features)[0]
        == "headphones"
    )
    assert (
        classify_product(HEADPHONES, model_only, {"Brand": "Skullcandy"})[0] == "other"
    )


def test_non_lab_paths_keep_the_source_taxonomy_and_the_rules_are_versioned():
    stand = ["Electronics", "Monitor Accessories", "Monitor Arms"]
    assert classify_product(stand, "Dual Monitor Arm", None) == (
        "monitor_stand",
        "source taxonomy",
    )
    assert len(classification_sha256()) == 64


def test_reviewed_decisions_are_bound_to_one_selection_and_known_categories():
    header = '{"dataset_id": "reviews-2023-v2", "decided_by": "review"}'
    good = '{"parent_asin": "B000", "category": "headphone_accessory", "reason": "ear pads"}'
    assert reviewed_decisions([header, good], "reviews-2023-v2") == {
        "B000": ("headphone_accessory", "ear pads")
    }
    with pytest.raises(ValueError, match="reviewed for"):
        reviewed_decisions([header, good], "reviews-2023-v3")
    with pytest.raises(ValueError, match="known category"):
        reviewed_decisions(
            [header, good.replace("headphone_accessory", "curtains")], "reviews-2023-v2"
        )
    with pytest.raises(ValueError, match="one decision per listing"):
        reviewed_decisions([header, good, good], "reviews-2023-v2")
