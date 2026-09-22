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
