"""Catalog browsing and source-evidence reads."""
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
    "featured": "p.popularity_score DESC, p.quality_score DESC, p.product_id",
    "price_asc": "p.price_usd ASC, p.product_id",
    "price_desc": "p.price_usd DESC, p.product_id",
    "rating": "p.rating DESC, p.review_count DESC, p.product_id",
    "newest": "p.launch_date DESC, p.product_id",
}


def _where(filters: SearchFilters) -> tuple[str, list[Any]]:
    values = filters.as_sql_json()
    return "catalog.filter_match(p, %s::jsonb)", [json.dumps(values)]


def _summary(row: dict[str, Any]) -> ProductSummary:
    revision = row["updated_at"].isoformat()
    return ProductSummary(
        product_id=row["product_id"],
        sku=row["sku"],
        title=row["title"],
        short_description=row["short_description"],
        domain=row["domain"],
        category=row["category"],
        subcategory=row["subcategory"],
        brand=row["brand"],
        model=row["model"],
        price_usd=float(row["price_usd"]),
        list_price_usd=float(row["list_price_usd"]),
        rating=float(row["rating"]),
        review_count=row["review_count"],
        availability=row["availability"],
        inventory_count=row["inventory_count"],
        attributes=row["attributes"],
        tags=row["tags"],
        image_url=row.get("image_url"),
        image_source=row.get("image_source"),
        sources=[
            SourceAttribution(
                source_uri=f"catalog://product/{row['product_id']}",
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
            f"SELECT count(*) AS count FROM catalog.product p WHERE {where}",
            parameters,
        ).fetchone()["count"]
        rows = connection.execute(
            f"""
            SELECT
                p.product_id, p.sku, p.title, p.short_description, p.domain,
                p.category, p.subcategory, p.brand, p.model, p.price_usd,
                p.list_price_usd, p.rating, p.review_count, p.availability,
                p.inventory_count, p.attributes, p.tags, p.updated_at,
                media.image_url, media.image_source
            FROM catalog.product p
            LEFT JOIN catalog.product_media media
              ON media.product_id = p.product_id
             AND media.role = 'primary'
             AND media.sort_order = 0
             AND media.publication_status = 'approved'
            WHERE {where}
            ORDER BY {_SORTS[sort]}
            OFFSET %s LIMIT %s
            """,
            [*parameters, offset, limit],
        ).fetchall()
        facets: dict[str, list[dict[str, Any]]] = {}
        for column in ("domain", "category", "brand", "availability"):
            facet_rows = connection.execute(
                f"""
                SELECT {column} AS value, count(*) AS count
                FROM catalog.product p
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
            """
            SELECT
                p.product_id, p.sku, p.title, p.short_description,
                p.long_description, p.domain, p.category, p.subcategory,
                p.brand, p.model, p.price_usd, p.list_price_usd, p.rating,
                p.review_count, p.availability, p.inventory_count, p.attributes,
                p.tags, p.updated_at, p.canonical_group_id, p.source_system,
                primary_media.image_url, primary_media.image_source
            FROM catalog.product p
            LEFT JOIN catalog.product_media primary_media
              ON primary_media.product_id = p.product_id
             AND primary_media.role = 'primary'
             AND primary_media.sort_order = 0
             AND primary_media.publication_status = 'approved'
            WHERE p.product_id = %s
            """,
            (product_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Product not found")
        media_rows = connection.execute(
            """
            SELECT role, sort_order, image_url, image_source, image_key, alt_text
            FROM catalog.product_media
            WHERE product_id = %s AND publication_status = 'approved'
            ORDER BY role, sort_order
            """,
            (product_id,),
        ).fetchall()
        review_rows = connection.execute(
            """
            SELECT review_id, rating, title, body, verified_purchase,
                   helpful_votes, review_date, sentiment_score, source_uri
            FROM catalog.product_review
            WHERE product_id = %s
            ORDER BY helpful_votes DESC, review_date DESC
            LIMIT 8
            """,
            (product_id,),
        ).fetchall()
    summary = _summary(dict(row))
    return ProductDetail(
        **summary.model_dump(),
        long_description=row["long_description"],
        canonical_group_id=row["canonical_group_id"],
        source_system=row["source_system"],
        updated_at=row["updated_at"],
        media=[ProductMedia(**dict(item)) for item in media_rows],
        reviews=[
            ProductReview(
                **{
                    **dict(item),
                    "review_date": item["review_date"].isoformat(),
                }
            )
            for item in review_rows
        ],
    )


def catalog_summary() -> dict[str, Any]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT domain, count(*) AS products, count(DISTINCT category) AS categories,
                   count(DISTINCT subcategory) AS subcategories,
                   count(DISTINCT brand) AS brands
            FROM catalog.product
            GROUP BY domain
            ORDER BY domain
            """
        ).fetchall()
        total = connection.execute(
            """
            SELECT count(*) AS products, count(DISTINCT brand) AS brands,
                   count(DISTINCT subcategory) AS subcategories,
                   count(*) FILTER (WHERE embedding IS NOT NULL) AS embedded_products
            FROM catalog.product
            """
        ).fetchone()
    return {"total": dict(total), "domains": [dict(row) for row in rows]}
