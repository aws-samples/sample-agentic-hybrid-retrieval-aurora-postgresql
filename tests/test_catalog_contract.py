import pytest
from pathlib import Path

from scripts.catalog_contract import product_matches_filters, validate_filter_shape

ROOT = Path(__file__).resolve().parents[1]


PRODUCT = {
    "domain": "consumer_electronics",
    "category": "Audio",
    "subcategory": "Over-Ear Headphones",
    "brand": "AuriLogic",
    "availability": "In Stock",
    "price_usd": "179.99",
    "rating": "4.7",
    "attributes_json": '{"active_noise_cancellation":true,"battery_hours":48}',
}


def test_supported_scalar_and_attribute_filters_match():
    assert product_matches_filters(
        PRODUCT,
        {
            "domain": "consumer_electronics",
            "max_price": 200,
            "min_rating": 4.5,
            "attributes": {
                "active_noise_cancellation": True,
                "battery_hours": 48,
            },
        },
    )


def test_hard_filter_mismatch_is_rejected():
    assert not product_matches_filters(PRODUCT, {"max_price": 150})
    assert not product_matches_filters(
        PRODUCT,
        {"attributes": {"battery_hours": 60}},
    )


def test_unknown_filter_key_fails_closed():
    with pytest.raises(ValueError, match="Unsupported filter keys"):
        validate_filter_shape({"price_usd": 179.99})


def test_sql_attribute_filter_uses_explicit_json_operator_precedence():
    sql = (ROOT / "sql/04_search_functions.sql").read_text(encoding="utf-8")

    assert "(p).attributes @> (f->'attributes')" in sql
