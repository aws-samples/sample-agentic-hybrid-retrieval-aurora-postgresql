"""Select an explicitly prepared catalog without reassigning saved identities."""

from __future__ import annotations

import os
from dataclasses import dataclass

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


#: The one schema search lives in: the listings table and its indexes, the view
#: searches read, and the functions the lab files define, under the name the
#: files use.
SEARCH_SCHEMA = "mosaic_search"
#: The table that holds the listings and owns their indexes.
LISTING_TABLE = "product_listing"
#: The view every search reads: shop product IDs and recorded source prices.
LISTING_VIEW = "product_listing_view"


def search_schema() -> str:
    """Return an allowlisted SQL identifier, never a request-supplied value."""
    return SEARCH_SCHEMA


def filter_predicate(placeholder: str) -> str:
    """Render the Shop filter rule over the scalar columns of alias `d`.

    `matches_filters(d, f)` takes the whole document row. Over the live view
    that row is built per product, including the TOASTed embedding, and the
    function is not inlined, so a catalog-wide scan detoasts every product.
    Passing the scalar columns lets PostgreSQL inline the rule and evaluate
    plain predicates, so whole-catalog counts and browse pages stay cheap. A
    budget matches the price each source listing recorded, the same rule the
    search functions apply.
    """
    return f"""{SEARCH_SCHEMA}.matches_filter_values(
        d.domain, d.category_key, d.brand_name,
        coalesce(d.price_cents, d.historical_price_cents),
        d.availability, d.rating, d.attributes, d.is_refurbished,
        d.is_sponsored, {placeholder}::jsonb
    )"""


#: The catalog identity queries carry when no prepared catalog is selected.
SYNTHETIC_DATASET_ID = "synthetic-legacy"


#: The served catalog's indexes, named for the search each one serves, so an
#: attendee listing them in psql can tell which belongs to which search.
LIVE_INDEXES = {
    "fts": "product_search_fts_idx",
    "trigram": "product_search_trigram_idx",
    "vector": "product_search_vector_idx",
    "vector_halfvec": "product_search_vector_halfvec_idx",
    "vector_binary": "product_search_vector_binary_idx",
    "kind": "product_search_kind_idx",
    "public_id": "product_search_public_id_idx",
}


@dataclass(frozen=True)
class CatalogIndexes:
    """Where the served catalog's vectors physically live, and its index names.

    Searches read `product_listing_view`, so the table that carries the HNSW
    index is not the relation queries name. Anything that inspects an
    index by name (size, validity, the plan's `Index Name`) must look here.

    Attributes:
        schema: Schema of the physical table that owns the indexes.
        table: Physical table name.
        fp32: The cosine HNSW index over the fp32 column.
        halfvec: The halfvec expression index, if it has ever been built.
        binary: The binary-quantized expression index, if it has ever been built.
    """

    schema: str
    table: str
    fp32: str
    halfvec: str
    binary: str

    @property
    def qualified_table(self) -> str:
        return f"{self.schema}.{self.table}"

    def qualified(self, name: str) -> str:
        return f"{self.schema}.{name}"


def catalog_indexes() -> CatalogIndexes:
    """The served catalog's vector table and index names."""
    return CatalogIndexes(
        schema=SEARCH_SCHEMA,
        table=LISTING_TABLE,
        fp32=LIVE_INDEXES["vector"],
        halfvec=LIVE_INDEXES["vector_halfvec"],
        binary=LIVE_INDEXES["vector_binary"],
    )


def listing_view() -> str:
    """The relation every search reads products from."""
    return f"{SEARCH_SCHEMA}.{LISTING_VIEW}"
