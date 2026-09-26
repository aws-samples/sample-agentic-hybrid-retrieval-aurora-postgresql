"""Select an explicitly prepared catalog without reassigning saved identities."""

from __future__ import annotations

import os

# Saved storefront links predate the source catalog's category keys.
LEGACY_CATEGORY_FILTERS = {
    "over-ear-headphones": ("headphones", "consumer_electronics"),
    "mesh-office-chairs": ("chair", "home_office"),
    "ergonomic-office-chairs": ("chair", "home_office"),
    "productivity-monitors": ("monitor", "consumer_electronics"),
    "ultrawide-monitors": ("monitor", "consumer_electronics"),
}


def active_dataset() -> str | None:
    """Return the real catalog selected by the operator, or the legacy catalog."""
    return os.getenv("MOSAIC_CATALOG_DATASET", "").strip() or None


def search_schema() -> str:
    """Return an allowlisted SQL identifier, never a request-supplied value."""
    return "mosaic_live_search" if active_dataset() else "mosaic_search"


def filter_predicate(placeholder: str) -> str:
    """Render the Shop filter rule over the scalar columns of alias `d`.

    `matches_filters(d, f)` takes the whole document row. Over the live view
    that row is built per product, including the TOASTed embedding, and the
    function is not inlined, so a catalog-wide scan detoasts every product.
    Passing the scalar columns lets PostgreSQL inline the rule and evaluate
    plain predicates, so whole-catalog counts and browse pages stay cheap.
    """
    return f"""{search_schema()}.matches_filter_values(
        d.domain, d.category_key, d.brand_name, d.price_cents,
        d.availability, d.rating, d.attributes, d.is_refurbished,
        d.is_sponsored, {placeholder}::jsonb
    )"""
