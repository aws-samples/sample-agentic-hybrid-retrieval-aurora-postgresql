"""Catalog browsing and source-evidence reads over the `mosaic` schema.

Browsing reads `mosaic_search.product_document`, the same denormalized
projection the retrieval arms use, so browsing and search both call the same
scalar filter function. The public `matches_filters(product_document, jsonb)`
validator delegates to that function rather than carrying a second predicate.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from service.db import connect
from service.models import (
    CatalogPage,
    EvidenceRecord,
    ProductDetail,
    ProductMedia,
    ProductReview,
    ProductSummary,
    SearchFilters,
    SourceAttribution,
)

_SORTS = {
    "featured": "ma.shop_page, ma.shop_position, d.product_id",
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
    return (
        """mosaic_search.matches_filter_values(
        d.domain, d.category_key, d.brand_name, d.price_cents,
        d.availability, d.rating, d.attributes, d.is_refurbished,
        d.is_sponsored, %s::jsonb
    )""",
        [json.dumps(filters.as_sql_json())],
    )


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
    limit: int = 12,
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
            JOIN mosaic.merchandising_assignment ma USING (product_id)
            WHERE {where}
              AND ma.shop_page IS NOT NULL
            """,
            parameters,
        ).fetchone()["count"]
        rows = connection.execute(
            f"""
            SELECT {_SUMMARY_COLUMNS},
                   media.runtime_uri AS image_url,
                   media.image_source
            FROM mosaic_search.product_document d
            JOIN mosaic.merchandising_assignment ma USING (product_id)
            LEFT JOIN LATERAL (
                SELECT a.runtime_uri, a.tier::text AS image_source
                FROM mosaic.product_media pm
                JOIN mosaic.media_asset a USING (asset_id)
                WHERE pm.product_id = d.product_id AND pm.role = 'catalog'
                ORDER BY pm.sort_order
                LIMIT 1
            ) media ON true
            WHERE {where}
              AND ma.shop_page IS NOT NULL
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
                JOIN mosaic.merchandising_assignment ma USING (product_id)
                WHERE {where}
                  AND ma.shop_page IS NOT NULL
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
        # Generated review excerpts are labeled as synthetic customer evidence.
        # Legacy verified_review rows remain readable after a snapshot upgrade.
        review_rows = connection.execute(
            """
            SELECT evidence_id AS review_id, evidence_title AS title,
                   evidence_text AS body, source_name, source_reference,
                   rating, is_verified, source_date, metadata
            FROM mosaic.product_evidence
            WHERE product_id = %s
              AND evidence_type::text IN ('customer_review', 'verified_review')
            ORDER BY rating DESC NULLS LAST, evidence_id
            LIMIT 8
            """,
            (product_id,),
        ).fetchall()
    summary = _summary(dict(row))
    return _detail(summary, dict(row), media_rows, review_rows)


def _detail(
    summary: ProductSummary,
    row: dict[str, Any],
    media_rows: list[Any],
    review_rows: list[Any],
) -> ProductDetail:
    """Promote a summary to detail while replacing inherited optional fields."""
    return ProductDetail.model_validate(
        {
            **summary.model_dump(),
            "long_description": row["long_description"],
            "canonical_group_id": row["canonical_group_id"] or "",
            "source_system": row["source_system"],
            "updated_at": row["updated_at"],
            "media": [ProductMedia(**dict(item)) for item in media_rows],
            "reviews": [_review(dict(item)) for item in review_rows],
        }
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
        source_uri=row.get("source_reference")
        or f"mosaic://evidence/{row['review_id']}",
        source_name=row["source_name"],
    )


def get_product_evidence_records(
    product_id: int,
    query: str,
    query_embedding: list[float],
    *,
    limit: int = 6,
) -> list[EvidenceRecord]:
    """Return question-ranked, source-addressable evidence for one product."""
    if not query.strip():
        raise ValueError("Evidence retrieval requires a non-empty evidence query")
    with connect() as connection:
        ranked_ids = connection.execute(
            """
            SELECT evidence_id
            FROM mosaic_search.search_product_evidence(
                %s::bigint,
                %s::text,
                %s::vector,
                NULL,
                %s::integer
            )
            """,
            (product_id, query, query_embedding, max(1, min(limit, 12))),
        ).fetchall()
        evidence_ids = [row["evidence_id"] for row in ranked_ids]
        if not evidence_ids:
            return []
        rows = connection.execute(
            """
            SELECT evidence_id, product_id, evidence_type::text AS evidence_type,
                   source_name, source_reference, evidence_title, evidence_text,
                   source_date, rating, is_verified, metadata, updated_at
            FROM unnest(%s::bigint[]) WITH ORDINALITY AS ranked(evidence_id, position)
            JOIN mosaic.product_evidence USING (evidence_id)
            ORDER BY ranked.position
            """,
            (evidence_ids,),
        ).fetchall()
    return [_evidence_record(dict(row)) for row in rows]


def get_evidence_record(evidence_id: int) -> EvidenceRecord:
    """Resolve one source-addressable evidence record by its stable ID."""
    with connect() as connection:
        row = connection.execute(
            """
            SELECT evidence_id, product_id, evidence_type::text AS evidence_type,
                   source_name, source_reference, evidence_title, evidence_text,
                   source_date, rating, is_verified, metadata, updated_at
            FROM mosaic.product_evidence
            WHERE evidence_id = %s
            """,
            (evidence_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"Evidence {evidence_id} was not found")
    return _evidence_record(dict(row))


def _evidence_record(row: dict[str, Any]) -> EvidenceRecord:
    source_date = row.get("source_date")
    updated_at = row.get("updated_at")
    revision = (
        source_date.isoformat()
        if source_date
        else updated_at.isoformat()
        if updated_at
        else "unversioned"
    )
    return EvidenceRecord(
        evidence_id=row["evidence_id"],
        product_id=row["product_id"],
        evidence_type=row["evidence_type"],
        source_name=row["source_name"],
        source_uri=(
            row.get("source_reference") or f"mosaic://evidence/{row['evidence_id']}"
        ),
        revision=revision,
        title=row.get("evidence_title") or row["source_name"],
        text=row["evidence_text"],
        rating=None if row.get("rating") is None else float(row["rating"]),
        is_verified=bool(row.get("is_verified")),
        metadata=row.get("metadata") or {},
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
