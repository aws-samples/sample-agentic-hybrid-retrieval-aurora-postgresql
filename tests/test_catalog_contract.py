import pytest
from pathlib import Path

from scripts.catalog_contract import (
    SUPPORTED_FILTER_KEYS,
    product_matches_filters,
    validate_filter_shape,
)
from service.models import SearchFilters

ROOT = Path(__file__).resolve().parents[1]


PRODUCT = {
    "domain": "consumer_electronics",
    "category": "Audio",
    "subcategory": "Over-Ear Headphones",
    "brand": "AuriLogic",
    "availability": "In Stock",
    "price_usd": "179.99",
    "rating": "4.7",
    "is_refurbished": "false",
    "is_sponsored": "false",
    "attributes_json": '{"active_noise_cancellation":true,"battery_hours":48}',
}


def test_supported_scalar_and_attribute_filters_match():
    assert product_matches_filters(
        PRODUCT,
        {
            "domain": "consumer_electronics",
            "category_key": "over-ear-headphones",
            "max_price_cents": 20_000,
            "min_rating": 4.5,
            "attributes": {
                "active_noise_cancellation": True,
                "battery_hours": 48,
            },
        },
    )


def test_hard_filter_mismatch_is_rejected():
    assert not product_matches_filters(PRODUCT, {"max_price_cents": 15_000})
    assert not product_matches_filters(
        PRODUCT,
        {"attributes": {"battery_hours": 60}},
    )


@pytest.mark.parametrize("key", ["subcategory", "max_price", "price_usd"])
def test_predecessor_and_unknown_filter_keys_fail_closed(key):
    with pytest.raises(ValueError, match="Unsupported Mosaic filter keys"):
        validate_filter_shape({key: "stale"})


def test_filter_vocabulary_matches_the_typed_and_sql_contracts():
    sql = (ROOT / "db/sql/09_search_functions.sql").read_text(encoding="utf-8")
    assert SUPPORTED_FILTER_KEYS == set(SearchFilters.model_fields)
    for key in SUPPORTED_FILTER_KEYS:
        assert f"'{key}'" in sql, (
            f"{key} is accepted by SearchFilters but matches_filters never reads it"
        )


def test_refurbished_and_sponsored_defaults_match_the_database_policy():
    assert not product_matches_filters(
        {**PRODUCT, "is_refurbished": "true"},
        {},
    )
    assert product_matches_filters(
        {**PRODUCT, "is_refurbished": "true"},
        {"include_refurbished": True},
    )
    assert not product_matches_filters(
        {**PRODUCT, "is_sponsored": "true"},
        {},
    )
    assert product_matches_filters(
        {**PRODUCT, "is_sponsored": "true"},
        {"include_sponsored": True},
    )


def test_sql_attribute_filter_uses_explicit_json_operator_precedence():
    """`@>` and `->` share a precedence level and associate left.

    Without the parentheses, `a @> f->'k'` parses as `(a @> f)->'k'` and fails with
    "operator does not exist: boolean -> unknown". Retargeted from the deleted
    `sql/04_search_functions.sql` to the live tree in Phase 2 Unit E.
    """
    sql = (ROOT / "db/sql/09_search_functions.sql").read_text(encoding="utf-8")

    assert "(d).attributes @> (f->'attributes')" in sql
