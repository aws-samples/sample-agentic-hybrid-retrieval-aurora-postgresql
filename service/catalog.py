"""Catalog browsing and source-evidence reads over the `mosaic` schema.

Browsing reads `mosaic_search.product_document`, the same denormalized
projection the retrieval arms use, so a filter applied while browsing and the
same filter applied while searching are evaluated by one function
(`mosaic_search.matches_filters`) rather than two hand-written WHERE clauses that
can drift apart.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from service.db import connect
from service.models import (
    CatalogPage,
    ProductDetail,
    ProductMedia,
    ProductReview,
    ProductSummary,
    SearchFilters,
    SourceAttribution,
)

_SORTS = {
    "featured": "d.popularity_score DESC, d.quality_score DESC, d.product_id",
    "price_asc": "d.price_cents ASC, d.product_id",
    "price_desc": "d.price_cents DESC, d.product_id",
    "rating": "d.rating DESC NULLS LAST, d.review_count DESC, d.product_id",
    "newest": "d.freshness_score DESC, d.product_id",
}

# Facets are grouped by column name; the values are interpolated into SQL, so
# they must come from this allowlist and never from a request.
_FACET_COLUMNS = ("domain", "category_key", "brand_name", "availability")

_SUMMARY_COLUMNS = """
    d.product_id, d.sku, d.title, d.short_description, d.domain,
    d.category_key, d.category_path, d.brand_name, d.model_name,
    d.price_cents, d.list_price_cents, d.currency, d.rating, d.review_count,
    d.availability, d.inventory_count, d.attributes, d.tags,
    d.catalog_asset_key, d.canonical_group_id, d.media_tier, d.is_flagship,
    d.is_retrieval_anchor, d.updated_at
"""


def _where(filters: SearchFilters) -> tuple[str, list[Any]]:
    return "mosaic_search.matches_filters(d, %s::jsonb)", [
        json.dumps(filters.as_sql_json())
    ]


def _summary(row: dict[str, Any]) -> ProductSummary:
    updated_at = row.get("updated_at")
    revision = updated_at.isoformat() if updated_at else "unversioned"
    return ProductSummary(
        product_id=row["product_id"],
        sku=row["sku"],
        title=row["title"],
        short_description=row["short_description"],
        domain=row["domain"],
        category_key=row["category_key"],
        category_path=row["category_path"],
        brand=row["brand_name"],
        model=row["model_name"],
        price_cents=row["price_cents"],
        list_price_cents=row["list_price_cents"],
        currency=row.get("currency") or "USD",
        rating=None if row.get("rating") is None else float(row["rating"]),
        review_count=row["review_count"],
        availability=row["availability"],
        inventory_count=row["inventory_count"],
        attributes=row["attributes"],
        tags=list(row["tags"] or []),
        catalog_asset_key=row.get("catalog_asset_key"),
        canonical_group_id=row.get("canonical_group_id"),
        media_tier=row.get("media_tier"),
        is_flagship=bool(row.get("is_flagship")),
        is_retrieval_anchor=bool(row.get("is_retrieval_anchor")),
        image_url=row.get("image_url"),
        image_source=row.get("image_source"),
        sources=[
            SourceAttribution(
                source_uri=f"mosaic://product/{row['product_id']}",
                revision=revision,
                title=row["title"],
                quote=row["short_description"],
            )
        ],
    )


def list_products(
    filters: SearchFilters,
    *,
    offset: int = 0,
    limit: int = 24,
    sort: str = "featured",
) -> CatalogPage:
    if sort not in _SORTS:
        raise HTTPException(422, f"Unsupported sort: {sort}")
    where, parameters = _where(filters)
    with connect() as connection:
        total = connection.execute(
            f"""
            SELECT count(*) AS count
            FROM mosaic_search.product_document d
            WHERE {where}
            """,
            parameters,
        ).fetchone()["count"]
        rows = connection.execute(
            f"""
            SELECT {_SUMMARY_COLUMNS},
                   media.runtime_uri AS image_url,
                   media.image_source
            FROM mosaic_search.product_document d
            LEFT JOIN LATERAL (
                SELECT a.runtime_uri, a.tier::text AS image_source
                FROM mosaic.product_media pm
                JOIN mosaic.media_asset a USING (asset_id)
                WHERE pm.product_id = d.product_id AND pm.role = 'catalog'
                ORDER BY pm.sort_order
                LIMIT 1
            ) media ON true
            WHERE {where}
            ORDER BY {_SORTS[sort]}
            OFFSET %s LIMIT %s
            """,
            [*parameters, offset, limit],
        ).fetchall()
        facets: dict[str, list[dict[str, Any]]] = {}
        for column in _FACET_COLUMNS:
            facet_rows = connection.execute(
                f"""
                SELECT {column}::text AS value, count(*) AS count
                FROM mosaic_search.product_document d
                WHERE {where}
                GROUP BY {column}
                ORDER BY count(*) DESC, {column}
                LIMIT 20
                """,
                parameters,
            ).fetchall()
            facets[column] = [dict(row) for row in facet_rows]
    return CatalogPage(
        total=total,
        offset=offset,
        limit=limit,
        products=[_summary(dict(row)) for row in rows],
        facets=facets,
    )


def get_product(product_id: int) -> ProductDetail:
    with connect() as connection:
        row = connection.execute(
            f"""
            SELECT {_SUMMARY_COLUMNS},
                   p.long_description, p.source_system,
                   media.runtime_uri AS image_url,
                   media.image_source
            FROM mosaic_search.product_document d
            JOIN mosaic.product p USING (product_id)
            LEFT JOIN LATERAL (
                SELECT a.runtime_uri, a.tier::text AS image_source
                FROM mosaic.product_media pm
                JOIN mosaic.media_asset a USING (asset_id)
                WHERE pm.product_id = d.product_id
                ORDER BY (pm.role <> 'detail'), pm.sort_order
                LIMIT 1
            ) media ON true
            WHERE d.product_id = %s
            """,
            (product_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Product not found")
        media_rows = connection.execute(
            """
            SELECT pm.role::text AS role, pm.sort_order, a.runtime_uri AS image_url,
                   a.tier::text AS image_source, a.asset_key AS image_key,
                   pm.alt_text
            FROM mosaic.product_media pm
            JOIN mosaic.media_asset a USING (asset_id)
            WHERE pm.product_id = %s
            ORDER BY pm.role, pm.sort_order
            """,
            (product_id,),
        ).fetchall()
        # Reviews live in mosaic.product_evidence alongside specs and Q&A, each
        # row independently embedded so the agent can cite one claim rather than
        # a whole product.
        review_rows = connection.execute(
            """
            SELECT evidence_id AS review_id, evidence_title AS title,
                   evidence_text AS body, source_name, source_reference,
                   rating, is_verified, source_date, metadata
            FROM mosaic.product_evidence
            WHERE product_id = %s AND evidence_type = 'verified_review'
            ORDER BY rating DESC NULLS LAST, evidence_id
            LIMIT 8
            """,
            (product_id,),
        ).fetchall()
    summary = _summary(dict(row))
    return ProductDetail(
        **summary.model_dump(),
        long_description=row["long_description"],
        canonical_group_id=row["canonical_group_id"] or "",
        source_system=row["source_system"],
        updated_at=row["updated_at"],
        media=[ProductMedia(**dict(item)) for item in media_rows],
        reviews=[_review(dict(item)) for item in review_rows],
    )


def _review(row: dict[str, Any]) -> ProductReview:
    """Shape one `product_evidence` row of type `review` as a review.

    `rating`, `is_verified`, and `source_date` are first-class columns on the
    evidence table. Only the two fields the schema does not model — helpful votes
    and sentiment — are read from `metadata`, and a missing value is reported as
    absent rather than defaulted to something flattering.
    """
    metadata = row.get("metadata") or {}
    source_date = row.get("source_date")
    return ProductReview(
        review_id=row["review_id"],
        rating=None if row.get("rating") is None else float(row["rating"]),
        title=row.get("title"),
        body=row["body"],
        verified_purchase=bool(row.get("is_verified")),
        helpful_votes=int(metadata.get("helpful_votes", 0)),
        review_date=source_date.isoformat() if source_date else None,
        sentiment_score=(
            float(metadata["sentiment_score"])
            if metadata.get("sentiment_score") is not None
            else None
        ),
        source_uri=row.get("source_reference") or f"mosaic://evidence/{row['review_id']}",
    )


def catalog_summary() -> dict[str, Any]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT domain::text AS domain, count(*) AS products,
                   count(DISTINCT category_key) AS categories,
                   count(DISTINCT category_path) AS subcategories,
                   count(DISTINCT brand_name) AS brands
            FROM mosaic_search.product_document
            GROUP BY domain
            ORDER BY domain
            """
        ).fetchall()
        total = connection.execute(
            """
            SELECT count(*) AS products,
                   count(DISTINCT brand_name) AS brands,
                   count(DISTINCT category_path) AS subcategories,
                   count(*) FILTER (WHERE embedding IS NOT NULL) AS embedded_products
            FROM mosaic_search.product_document
            """
        ).fetchone()
    return {"total": dict(total), "domains": [dict(row) for row in rows]}
