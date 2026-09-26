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


#: The catalog identity queries carry when no prepared catalog is selected.
SYNTHETIC_DATASET_ID = "synthetic-legacy"


@dataclass(frozen=True)
class CatalogIndexes:
    """Where the served catalog's vectors physically live, and its index names.

    The live catalog is served through a view, so the table that carries the
    HNSW index is not the relation queries name. Anything that inspects an
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
    """Resolve the physical vector table and index names for the served catalog."""
    if active_dataset():
        return CatalogIndexes(
            schema="mosaic_catalog_search",
            table="product_document",
            fp32="real_search_vector_idx",
            halfvec="real_search_vector_halfvec_idx",
            binary="real_search_vector_binary_idx",
        )
    return CatalogIndexes(
        schema="mosaic_search",
        table="product_document",
        fp32="product_document_embedding_hnsw_cosine_idx",
        halfvec="product_document_embedding_hnsw_halfvec_idx",
        binary="product_document_embedding_hnsw_binary_idx",
    )


def product_document() -> str:
    """The relation queries read products from: the live view or the legacy table."""
    return f"{search_schema()}.product_document"
