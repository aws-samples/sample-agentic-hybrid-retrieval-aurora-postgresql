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
