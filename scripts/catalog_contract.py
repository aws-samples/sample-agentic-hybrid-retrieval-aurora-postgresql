"""Validate Mosaic database filters against the generated flat catalog.

The checked-in corpus predates normalization, so its rows still carry dollar
prices, display availability, and taxonomy labels. Evaluation queries use the
production `SearchFilters` contract exclusively. This module projects a flat row
into those semantics for offline package checks; `scripts/run_eval.py` performs
the authoritative preflight by calling `mosaic_search.matches_filters` on
Aurora before it invokes an embedding model.
"""

from __future__ import annotations

import csv
import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.scripts.transform_legacy_catalog import resolve_category_keys
from service.models import SearchFilters

SUPPORTED_FILTER_KEYS = frozenset(SearchFilters.model_fields)
_AVAILABILITY = {
    "In Stock": "in_stock",
    "Low Stock": "low_stock",
    "Out of Stock": "out_of_stock",
    "Preorder": "preorder",
    "Discontinued": "discontinued",
}


@lru_cache(maxsize=1)
def _category_keys() -> dict[tuple[str, str, str], str]:
    with (ROOT / "data/full/subcategory_distribution.csv").open(
        newline="",
        encoding="utf-8",
    ) as source:
        categories = [
            (row["domain"], row["category"], row["subcategory"])
            for row in csv.DictReader(source)
        ]
    return resolve_category_keys(categories)


def unsupported_filter_keys(filters: Mapping[str, Any]) -> set[str]:
    return set(filters) - SUPPORTED_FILTER_KEYS


def validate_filter_shape(filters: Mapping[str, Any]) -> None:
    unknown = unsupported_filter_keys(filters)
    if unknown:
        raise ValueError(f"Unsupported Mosaic filter keys: {sorted(unknown)}")
    SearchFilters.model_validate(filters)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def product_matches_filters(
    product: Mapping[str, Any],
    filters: Mapping[str, Any],
) -> bool:
    """Apply production filter semantics to one pre-normalization corpus row."""
    validate_filter_shape(filters)
    normalized = SearchFilters.model_validate(filters).as_sql_json()

    if (
        "domain" in normalized
        and product["domain"] != normalized["domain"]
    ):
        return False
    if "category_key" in normalized:
        identity = (
            str(product["domain"]),
            str(product["category"]),
            str(product["subcategory"]),
        )
        if _category_keys()[identity] != normalized["category_key"]:
            return False
    if (
        "brand" in normalized
        and str(product["brand"]).lower() != normalized["brand"].lower()
    ):
        return False
    if (
        normalized.get("brands")
        and product["brand"] not in normalized["brands"]
    ):
        return False

    price_cents = round(float(product["price_usd"]) * 100)
    if (
        "max_price_cents" in normalized
        and price_cents > normalized["max_price_cents"]
    ):
        return False
    if (
        "min_price_cents" in normalized
        and price_cents < normalized["min_price_cents"]
    ):
        return False

    availability = _AVAILABILITY[str(product["availability"])]
    if (
        "availability" in normalized
        and availability != normalized["availability"]
    ):
        return False
    if normalized.get("in_stock_only") and availability not in {
        "in_stock",
        "low_stock",
    }:
        return False
    if (
        "min_rating" in normalized
        and float(product["rating"]) < normalized["min_rating"]
    ):
        return False

    attributes = product.get("attributes")
    if attributes is None:
        attributes = json.loads(str(product.get("attributes_json") or "{}"))
    for key, value in normalized.get("attributes", {}).items():
        if attributes.get(key) != value:
            return False

    if (
        _as_bool(product.get("is_refurbished", False))
        and not normalized.get("include_refurbished", False)
    ):
        return False
    if (
        _as_bool(product.get("is_sponsored", False))
        and not normalized.get("include_sponsored", False)
    ):
        return False
    return True
