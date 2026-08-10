"""Filter contract for the generated CSV corpus — NOT for the database.

This module validates filters against the flat generated catalog
(`data/full/*.csv.gz`), where prices are `price_usd` floats and category is a
denormalized `subcategory` string. `mosaic_search.matches_filters` is the
database's contract, it takes different keys (`max_price_cents`, `category_key`),
and the two are **not** interchangeable. Unit A's mission gate exists because a
hand reimplementation of the SQL was used to validate database queries and did not
know what the SQL actually applied.

**Measured divergence, recorded rather than papered over.** Four keys here have no
counterpart in `matches_filters`: `category`, `subcategory`, `max_price`,
`min_price`. `data/evals/queries.jsonl` sends `subcategory` and `max_price` on 235
of its 720 queries, and jsonb filters ignore keys they do not recognise — verified
on the live cluster, where a filter set with those two keys returns exactly the
same 194,824 products as `domain` alone. Anything using this vocabulary against the
database is filtering less than it appears to.

`CORPUS_ONLY_FILTER_KEYS` names those four, and
`tests/test_catalog_contract.py` asserts the split stays accurate, so the
divergence cannot widen silently. Repointing the eval queries at the database
vocabulary is a data change with its own judgments and is out of Phase 2's scope.
"""

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

# Keys valid for the CSV corpus that `mosaic_search.matches_filters` does not
# implement. A jsonb filter naming one of these is silently ignored by the
# database, so it must never be sent there expecting it to constrain anything.
CORPUS_ONLY_FILTER_KEYS = frozenset(
    {"category", "subcategory", "max_price", "min_price"}
)

# Keys both vocabularies honour, so a filter using only these means the same thing
# to the CSV corpus and to the cluster.
SHARED_FILTER_KEYS = SUPPORTED_FILTER_KEYS - CORPUS_ONLY_FILTER_KEYS


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
    if "max_price" in filters and float(product["price_usd"]) > float(
        filters["max_price"]
    ):
        return False
    if "min_price" in filters and float(product["price_usd"]) < float(
        filters["min_price"]
    ):
        return False
    if "min_rating" in filters and float(product["rating"]) < float(
        filters["min_rating"]
    ):
        return False

    attributes = product.get("attributes")
    if attributes is None:
        attributes = json.loads(str(product.get("attributes_json") or "{}"))
    for key, value in filters.get("attributes", {}).items():
        if attributes.get(key) != value:
            return False
    return True
