"""Shared product-catalog and evaluation filter contracts."""
from __future__ import annotations

import json
from typing import Any, Mapping

SUPPORTED_FILTER_KEYS = frozenset(
    {
        "domain",
        "category",
        "subcategory",
        "brand",
        "availability",
        "max_price",
        "min_price",
        "min_rating",
        "attributes",
    }
)


def unsupported_filter_keys(filters: Mapping[str, Any]) -> set[str]:
    return set(filters) - SUPPORTED_FILTER_KEYS


def validate_filter_shape(filters: Mapping[str, Any]) -> None:
    unknown = unsupported_filter_keys(filters)
    if unknown:
        raise ValueError(f"Unsupported filter keys: {sorted(unknown)}")
    if "attributes" in filters and not isinstance(filters["attributes"], dict):
        raise ValueError("The attributes filter must be an object")


def product_matches_filters(
    product: Mapping[str, Any],
    filters: Mapping[str, Any],
) -> bool:
    validate_filter_shape(filters)
    for key in ("domain", "category", "subcategory", "brand", "availability"):
        if key in filters and product[key] != filters[key]:
            return False
    if "max_price" in filters and float(product["price_usd"]) > float(filters["max_price"]):
        return False
    if "min_price" in filters and float(product["price_usd"]) < float(filters["min_price"]):
        return False
    if "min_rating" in filters and float(product["rating"]) < float(filters["min_rating"]):
        return False

    attributes = product.get("attributes")
    if attributes is None:
        attributes = json.loads(str(product.get("attributes_json") or "{}"))
    for key, value in filters.get("attributes", {}).items():
        if attributes.get(key) != value:
            return False
    return True
