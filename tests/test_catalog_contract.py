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


def test_the_corpus_only_split_matches_what_the_database_actually_implements():
    """The two filter vocabularies differ; the split must say exactly how.

    Measured on the live cluster: a filter set carrying `subcategory` and
    `max_price` returns the same 194,824 products as `domain` alone, because jsonb
    filters ignore keys they do not recognise. 235 of the 720 eval queries send
    those keys. This asserts the recorded divergence stays accurate, so it cannot
    widen without a test failing.
    """
    from scripts.catalog_contract import (
        CORPUS_ONLY_FILTER_KEYS,
        SHARED_FILTER_KEYS,
        SUPPORTED_FILTER_KEYS,
    )

    sql = (ROOT / "db/sql/09_search_functions.sql").read_text(encoding="utf-8")
    assert CORPUS_ONLY_FILTER_KEYS | SHARED_FILTER_KEYS == SUPPORTED_FILTER_KEYS
    assert not CORPUS_ONLY_FILTER_KEYS & SHARED_FILTER_KEYS
    for key in CORPUS_ONLY_FILTER_KEYS:
        assert f"f ? '{key}'" not in sql, (
            f"{key} is listed corpus-only but the SQL now implements it; move it "
            f"to the shared set"
        )
    for key in SHARED_FILTER_KEYS:
        assert f"f ? '{key}'" in sql, (
            f"{key} is listed shared but the SQL does not implement it; it is "
            f"silently ignored by the database"
        )


def test_sql_attribute_filter_uses_explicit_json_operator_precedence():
    """`@>` and `->` share a precedence level and associate left.

    Without the parentheses, `a @> f->'k'` parses as `(a @> f)->'k'` and fails with
    "operator does not exist: boolean -> unknown". Retargeted from the deleted
    `sql/04_search_functions.sql` to the live tree in Phase 2 Unit E.
    """
    sql = (ROOT / "db/sql/09_search_functions.sql").read_text(encoding="utf-8")

    assert "(d).attributes @> (f->'attributes')" in sql
