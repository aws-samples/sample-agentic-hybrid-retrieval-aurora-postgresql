"""Search filters must reject combinations that can never match."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from service.models import SearchFilters


@pytest.mark.parametrize(
    ("filters", "message"),
    [
        (
            {"min_price_cents": 20_000, "max_price_cents": 10_000},
            "min_price_cents",
        ),
        (
            {"availability": "out_of_stock", "in_stock_only": True},
            "in_stock_only",
        ),
        (
            {"brand": "Mosaic", "brands": ["AuriLogic", "Sonora"]},
            "brand",
        ),
    ],
)
def test_contradictory_filters_are_rejected(filters, message):
    """Red-at-birth: each fixture currently reaches SQL as an empty predicate."""
    with pytest.raises(ValidationError, match=message):
        SearchFilters.model_validate(filters)


def test_consistent_redundant_filters_remain_valid():
    filters = SearchFilters(
        availability="low_stock",
        in_stock_only=True,
        min_price_cents=10_000,
        max_price_cents=20_000,
        brand="Mosaic",
        brands=["Mosaic", "Sonora"],
    )

    assert filters.brand == "Mosaic"
    assert filters.brands == ["Mosaic", "Sonora"]


@pytest.mark.parametrize(
    ("old_category", "category", "domain"),
    [
        ("over-ear-headphones", "headphones", "consumer_electronics"),
        ("mesh-office-chairs", "chair", "home_office"),
        ("ergonomic-office-chairs", "chair", "home_office"),
        ("productivity-monitors", "monitor", "consumer_electronics"),
        ("ultrawide-monitors", "monitor", "consumer_electronics"),
    ],
)
def test_real_catalog_accepts_saved_category_filters(
    monkeypatch, old_category, category, domain
):
    """An old Shop link must not lock every agent search to a retired key."""
    from service.models import AgentRequest, SearchRequest

    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-500k-v1")
    filters = {"category_key": old_category, "brand": "Example", "min_rating": 4}
    for request in (
        AgentRequest(question="Help me choose", filters=filters),
        SearchRequest(query="Help me choose", filters=filters),
    ):
        assert request.filters.as_sql_json() == {
            "domain": domain,
            "category_key": category,
            "brand": "Example",
            "min_rating": 4,
        }


def test_category_compatibility_preserves_explicit_constraints(monkeypatch):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-500k-v1")
    filters = SearchFilters(
        category_key="over-ear-headphones",
        domain="home_office",
        max_price_cents=10000,
        attributes={"Color": "Black"},
    )
    assert filters.category_key == "headphones"
    assert filters.domain == "home_office"
    assert filters.max_price_cents == 10000
    assert filters.attributes == {"Color": "Black"}


def test_category_compatibility_does_not_rewrite_other_catalogs(monkeypatch):
    monkeypatch.delenv("MOSAIC_CATALOG_DATASET", raising=False)
    assert (
        SearchFilters(category_key="over-ear-headphones").category_key
        == "over-ear-headphones"
    )
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-500k-v1")
    assert (
        SearchFilters(category_key="unknown-category").category_key
        == "unknown-category"
    )
