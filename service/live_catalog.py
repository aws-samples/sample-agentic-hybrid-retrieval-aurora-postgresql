"""Storefront reads of the verified real catalog and its original evidence."""

from __future__ import annotations

import json
from collections import OrderedDict
from functools import lru_cache
from itertools import zip_longest
from pathlib import Path
from threading import Lock
from time import monotonic
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException

from service.catalog_runtime import active_dataset, search_schema
from service.db import connect, index_states_on
from service.models import (
    CatalogPage,
    CatalogSuggestion,
    CatalogSuggestionsResponse,
    ProductDetail,
    ProductMedia,
    ProductReview,
    ProductSummary,
    SearchFilters,
    SourceAttribution,
)
from service.source_catalog import project_product
from service.staged_catalog import product_evidence

ROOT = Path(__file__).resolve().parents[1]
_BROWSE_STATISTICS: OrderedDict[tuple, dict] = OrderedDict()
_BROWSE_LOCK = Lock()
_SORTS = {
    "featured": "coalesce(array_position(%(featured)s::text[],d.parent_asin),2147483647),d.product_id",
    "rating": "d.rating DESC NULLS LAST,d.product_id",
    "newest": "d.product_id",
    "price_asc": "d.price_cents ASC NULLS LAST,d.product_id",
    "price_desc": "d.price_cents DESC NULLS LAST,d.product_id",
}


@lru_cache(maxsize=4)
def _collection(dataset: str) -> tuple[str, ...]:
    manifest = json.loads((ROOT / "data/real-shop-collection.json").read_text())
    if manifest["dataset_id"] != dataset:
        raise RuntimeError(
            f"Shop selection rule: {manifest['dataset_id']} does not match {dataset}; prepare a matching collection before enabling it."
        )
    groups = [group["parent_asins"] for group in manifest["groups"]]
    return tuple(
        dict.fromkeys(
            value for group in zip_longest(*groups) for value in group if value
        )
    )


def _selection_receipt(connection) -> dict:
    dataset = active_dataset()
    row = connection.execute(
        "SELECT dataset_id,prepared_at FROM mosaic_live_search.receipt WHERE singleton"
    ).fetchone()
    if not row or not row["prepared_at"] or row["dataset_id"] != dataset:
        raise HTTPException(
            503,
            "The selected catalog is not ready. Complete its verified preparation before starting the app.",
        )
    return row


def _selection(connection) -> str:
    return _selection_receipt(connection)["dataset_id"]


def summary_from_source(row: dict) -> ProductSummary:
    """Expose source facts while leaving unreported current offers unknown."""
    source = project_product(row)
    text = source["description"] or source["features"]
    rating = source["rating"]
    return ProductSummary(
        product_id=row["product_id"],
        sku=source["parent_asin"],
        title=source["title"],
        short_description=text[0] if text else "",
        domain=row["domain"],
        category_key=row["category_key"],
        category_path=" > ".join(source["categories"]),
        brand=source["brand"] or "",
        model=source["model"] or "",
        price_cents=None,
        list_price_cents=None,
        currency="USD",
        rating=rating["average"] if rating else None,
        review_count=rating["count"] if rating else 0,
        availability=None,
        inventory_count=None,
        attributes=source["specifications"],
        tags=[],
        canonical_group_id=source["parent_asin"],
        image_url=source["image_url"],
        image_source="original_listing",
        source_dataset=active_dataset(),
        listing_url=source["listing_url"],
        historical_price_cents=source["historical_price_cents"],
        historical_price_min_cents=source["historical_price_min_cents"],
        condition=source["condition"],
        source_features=source["features"],
        sources=[
            SourceAttribution(
                source_uri=source["listing_url"],
                revision=source["source_record_sha256"],
                title=source["title"],
                quote=text[0] if text else source["title"],
            )
        ],
    )


def _source_rows(
    connection, product_ids: list[int], *, dataset: str | None = None
) -> list[dict]:
    dataset = dataset or _selection(connection)
    return connection.execute(
        f"""SELECT d.product_id,d.domain::text AS domain,d.category_key,
            p.dataset_id,p.parent_asin,p.source_department,p.original,p.source_record_sha256,
            p.embedding_text,p.embedding_text_sha256,p.embedding_model_key,p.image_url
        FROM {search_schema()}.product_document d
        JOIN mosaic_catalog_stage.product p ON p.dataset_id=d.dataset_id AND p.parent_asin=d.parent_asin
        WHERE d.dataset_id=%s AND d.product_id=ANY(%s::bigint[])
        ORDER BY array_position(%s::bigint[],d.product_id)""",
        (dataset, product_ids, product_ids),
    ).fetchall()


def get_product_summaries(product_ids: list[int]) -> list[ProductSummary]:
    ids = list(dict.fromkeys(product_ids))
    if not ids:
        return []
    with connect() as connection:
        rows = _source_rows(connection, ids)
    found = {row["product_id"] for row in rows}
    if missing := [product_id for product_id in ids if product_id not in found]:
        raise KeyError(
            f"Products {missing} are not in this catalog. Run a new search against the current catalog."
        )
    return [summary_from_source(row) for row in rows]


def _browse_where(filters: dict, collection: str) -> str:
    where = f"d.dataset_id=%(dataset)s AND {search_schema()}.matches_filters(d,%(filters)s::jsonb)"
    # The composite SQL function is not inlined by PostgreSQL. This redundant
    # equality exposes the category index without replacing the production rule.
    if "category_key" in filters:
        where += " AND d.category_key=%(category_key)s"
    if collection == "workspace":
        where += " AND d.parent_asin=ANY(%(featured)s::text[])"
    return where


def _browse_statistics(
    connection,
    dataset: str,
    prepared_at,
    filters_json: str,
    featured: tuple[str, ...],
    collection: str,
    freshness: int,
) -> dict:
    # Counts and menus describe the same immutable imported snapshot across
    # pages. A changed preparation receipt invalidates them immediately; the
    # five-minute bucket also bounds freshness for operator-side changes.
    key = (dataset, prepared_at, filters_json, featured, collection, freshness)
    with _BROWSE_LOCK:
        if key in _BROWSE_STATISTICS:
            _BROWSE_STATISTICS.move_to_end(key)
            return _BROWSE_STATISTICS[key]
    filters = json.loads(filters_json)
    parameters = {
        "dataset": dataset,
        "filters": filters_json,
        "featured": list(featured),
        "category_key": filters.get("category_key"),
    }
    where = _browse_where(filters, collection)
    rows = connection.execute(
        f"""WITH filtered AS MATERIALIZED (
                SELECT d.domain,d.category_key,d.brand_name
                FROM {search_schema()}.product_document d WHERE {where}
            ), counts AS (
                SELECT CASE WHEN grouping(domain)=0 THEN 'domain'
                            WHEN grouping(category_key)=0 THEN 'category_key'
                            WHEN grouping(brand_name)=0 THEN 'brand' ELSE 'total' END AS facet,
                       coalesce(domain::text,category_key,brand_name) AS value,count(*) AS count
                FROM filtered
                GROUP BY GROUPING SETS ((),(domain),(category_key),(brand_name))
            ), ranked AS (
                SELECT *,row_number() OVER(PARTITION BY facet ORDER BY count DESC,value) AS position
                FROM counts WHERE facet='total' OR nullif(value,'') IS NOT NULL
            ) SELECT facet,value,count FROM ranked WHERE position<=30 ORDER BY facet,position""",
        parameters,
    ).fetchall()
    result = {
        "total": 0,
        "facets": {"domain": [], "category_key": [], "brand": [], "availability": []},
    }
    for row in rows:
        if row["facet"] == "total":
            result["total"] = row["count"]
        else:
            result["facets"][row["facet"]].append(
                {"value": row["value"], "count": row["count"]}
            )
    with _BROWSE_LOCK:
        _BROWSE_STATISTICS[key] = result
        while len(_BROWSE_STATISTICS) > 64:
            _BROWSE_STATISTICS.popitem(last=False)
    return result


def _browse_page_sql(where: str, sort: str, collection: str) -> str:
    if sort == "featured" and collection == "all":
        # Sorting the whole corpus by array_position defeats the ID index.
        # Bound each disjoint part before merging, preserving the exact order.
        return f"""WITH featured AS (
            SELECT d.product_id,array_position(%(featured)s::text[],d.parent_asin) AS position
            FROM {search_schema()}.product_document d
            WHERE {where} AND d.parent_asin=ANY(%(featured)s::text[])
            ORDER BY position,d.product_id LIMIT (%(offset)s+%(limit)s)
        ), remaining AS (
            SELECT d.product_id,2147483647 AS position
            FROM {search_schema()}.product_document d
            WHERE {where} AND NOT(d.parent_asin=ANY(%(featured)s::text[]))
            ORDER BY d.product_id LIMIT (%(offset)s+%(limit)s)
        ) SELECT product_id FROM (SELECT * FROM featured UNION ALL SELECT * FROM remaining) ordered
        ORDER BY position,product_id OFFSET %(offset)s LIMIT %(limit)s"""
    return f"SELECT d.product_id FROM {search_schema()}.product_document d WHERE {where} ORDER BY {_SORTS[sort]} OFFSET %(offset)s LIMIT %(limit)s"


def list_products(
    filters: SearchFilters, *, offset=0, limit=12, sort="featured", collection="all"
) -> CatalogPage:
    if collection not in {"all", "workspace"} or sort not in _SORTS:
        raise HTTPException(
            422, "Choose the all or workspace collection and a supported sort order."
        )
    with connect() as connection:
        receipt = _selection_receipt(connection)
        dataset = receipt["dataset_id"]
        featured = _collection(dataset)
        filter_values = filters.as_sql_json()
        filters_json = json.dumps(filter_values, sort_keys=True)
        parameters = {
            "dataset": dataset,
            "filters": filters_json,
            "featured": list(featured),
            "category_key": filters.category_key,
            "offset": offset,
            "limit": limit,
        }
        where = _browse_where(filter_values, collection)
        statistics = _browse_statistics(
            connection,
            dataset,
            receipt["prepared_at"],
            filters_json,
            featured,
            collection,
            int(monotonic() // 300),
        )
        rows = connection.execute(
            _browse_page_sql(where, sort, collection),
            parameters,
        ).fetchall()
        sources = _source_rows(
            connection, [row["product_id"] for row in rows], dataset=dataset
        )
    return CatalogPage(
        total=statistics["total"],
        offset=offset,
        limit=limit,
        products=[summary_from_source(row) for row in sources],
        facets=statistics["facets"],
    )


def count_products(filters: list[SearchFilters]) -> list[int]:
    with connect() as connection:
        _selection(connection)
        rows = connection.execute(
            f"""SELECT (SELECT count(*) FROM {search_schema()}.product_document d
            WHERE {search_schema()}.matches_filters(d,requested.filters)) AS count
            FROM jsonb_array_elements(%s::jsonb) WITH ORDINALITY AS requested(filters,position)
            ORDER BY requested.position""",
            (json.dumps([item.as_sql_json() for item in filters]),),
        ).fetchall()
    return [row["count"] for row in rows]


def _ensure_evidence(connection, row: dict) -> list[dict]:
    """Register exact sources once so citations keep their existing FK checks."""
    records, _ = product_evidence(connection, active_dataset(), row)
    persisted = []
    for record in records:
        identity = uuid5(
            NAMESPACE_URL,
            f"{active_dataset()}:{row['parent_asin']}:{record['evidence_id']}",
        )
        metadata = {
            key: record[key]
            for key in (
                "parent_asin",
                "variant_asin",
                "source_revision",
                "source_record_sha256",
                "scope",
                "helpful_votes",
                "source_location",
            )
            if key in record
        }
        result = connection.execute(
            """INSERT INTO mosaic.product_evidence
            (evidence_uid,product_id,evidence_type,source_name,source_reference,evidence_title,
             evidence_text,source_date,rating,is_verified,metadata,embedding_text,embedding,embedding_model_key)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,
                CASE WHEN %s THEN (SELECT embedding FROM mosaic_catalog_stage.product WHERE dataset_id=%s AND parent_asin=%s) END,
                CASE WHEN %s THEN %s END)
            ON CONFLICT(evidence_uid) DO NOTHING
            RETURNING evidence_id""",
            (
                identity,
                row["product_id"],
                record["evidence_type"],
                record["source_name"],
                record["source_reference"],
                record["title"],
                record["text"],
                record["source_date"],
                record["rating"],
                bool(record["verified_purchase"]),
                json.dumps(metadata),
                record["text"],
                record["evidence_type"] == "product_spec",
                active_dataset(),
                row["parent_asin"],
                record["evidence_type"] == "product_spec",
                row["embedding_model_key"],
            ),
        ).fetchone()
        if result is None:
            result = connection.execute(
                "SELECT evidence_id FROM mosaic.product_evidence WHERE evidence_uid=%s",
                (identity,),
            ).fetchone()
        persisted.append({**record, "evidence_id": result["evidence_id"]})
    return persisted


def ensure_product_evidence(product_id: int) -> None:
    with connect() as connection:
        rows = _source_rows(connection, [product_id])
        if not rows:
            raise HTTPException(404, "Product not found in the current catalog.")
        _ensure_evidence(connection, rows[0])


def get_product(product_id: int) -> ProductDetail:
    with connect() as connection:
        rows = _source_rows(connection, [product_id])
        if not rows:
            raise HTTPException(404, "Product not found in the current catalog.")
        row = rows[0]
        records = _ensure_evidence(connection, row)
        imported = connection.execute(
            "SELECT created_at FROM mosaic_catalog_stage.dataset WHERE dataset_id=%s",
            (active_dataset(),),
        ).fetchone()["created_at"]
    product = summary_from_source(row)
    original = row["original"]
    images = list(
        dict.fromkeys(
            image.get("hi_res") or image.get("large")
            for image in original["images"]
            if image.get("hi_res") or image.get("large")
        )
    )
    return ProductDetail(
        **product.model_dump(),
        long_description="\n\n".join(original["description"] or original["features"]),
        source_system="Amazon Reviews 2023",
        updated_at=imported,
        media=[
            ProductMedia(
                role="detail",
                sort_order=index,
                image_url=url,
                image_source="original_listing",
                alt_text=product.title,
            )
            for index, url in enumerate(images)
        ],
        reviews=[
            ProductReview(
                review_id=item["evidence_id"],
                rating=item["rating"],
                title=item["title"],
                body=item["text"],
                verified_purchase=bool(item["verified_purchase"]),
                helpful_votes=item.get("helpful_votes", 0),
                review_date=item["source_date"],
                source_uri=item["source_reference"],
                source_name=item["source_name"],
            )
            for item in records
            if item["evidence_type"] == "customer_review"
        ],
    )


def similar_products(product_id: int) -> list[ProductSummary]:
    with connect() as connection:
        _selection(connection)
        rows = connection.execute(
            f"""SELECT d.product_id FROM {search_schema()}.product_document d
            WHERE d.category_key=(SELECT category_key FROM {search_schema()}.product_document WHERE product_id=%s)
              AND d.product_id<>%s
            ORDER BY d.embedding <=> (SELECT embedding FROM {search_schema()}.product_document WHERE product_id=%s)
            LIMIT 4""",
            (product_id, product_id, product_id),
        ).fetchall()
        source = _source_rows(connection, [row["product_id"] for row in rows])
    return [summary_from_source(row) for row in source]


def catalog_suggestions(query: str) -> CatalogSuggestionsResponse:
    with connect() as connection:
        _selection(connection)
        rows = connection.execute(
            f"""WITH q AS (
            SELECT to_tsquery('english',string_agg(quote_literal(term)||':*',' & ')) AS tsq
            FROM unnest(tsvector_to_array(to_tsvector('english',%s))) AS term
        ) SELECT d.product_id,d.title,d.domain,d.brand_name,d.category_key,d.category_path
        FROM {search_schema()}.product_document d,q WHERE q.tsq IS NOT NULL AND d.search_document @@ q.tsq
        ORDER BY ts_rank_cd(d.search_document,q.tsq) DESC,d.product_id LIMIT 8""",
            (query,),
        ).fetchall()
    return CatalogSuggestionsResponse(
        query=query,
        suggestions=[
            CatalogSuggestion(
                kind="product",
                label=row["title"],
                query=row["title"],
                product_id=row["product_id"],
                domain=row["domain"],
                brand=row["brand_name"],
                category_key=row["category_key"],
                category_path=row["category_path"],
            )
            for row in rows
        ],
    )


@lru_cache(maxsize=4)
def catalog_summary_for(dataset: str) -> dict:
    with connect() as connection:
        _selection(connection)
        rows = connection.execute(f"""SELECT domain::text AS domain,count(*) AS products,
            count(DISTINCT category_key) AS categories,count(DISTINCT category_path) AS subcategories,
            count(DISTINCT nullif(brand_name,'')) AS brands FROM {search_schema()}.product_document GROUP BY domain ORDER BY domain""").fetchall()
        total = connection.execute(
            """SELECT count(*) AS products,count(DISTINCT nullif(original->'details'->>'Brand','')) AS brands,
            count(DISTINCT categories) AS subcategories,count(embedding) AS embedded_products,
            sum((original->>'rating_number')::bigint) AS reviews,
            count(*) FILTER(WHERE (original->>'rating_number')::bigint>0) AS reviewed_products,
            (sum((original->>'average_rating')::numeric*(original->>'rating_number')::bigint)/nullif(sum((original->>'rating_number')::bigint),0))::float8 AS average_rating
            FROM mosaic_catalog_stage.product WHERE dataset_id=%s""",
            (dataset,),
        ).fetchone()
    return {
        "total": total,
        "domains": rows,
        "dataset_id": dataset,
        "source_name": "Amazon Reviews 2023",
        "historical": True,
        "current_offers_available": False,
    }


def readiness() -> dict:
    """Check the selected corpus, without borrowing the old catalog's proof."""
    with connect() as connection:
        dataset = _selection(connection)
        row = connection.execute(
            """SELECT current_database() AS database_name,
            current_setting('server_version') AS server_version,
            (SELECT extversion FROM pg_extension WHERE extname='vector') AS vector_version,
            count(*) AS product_count,count(embedding) AS embedded_product_count,
            min(vector_dims(embedding)) AS embedding_dimensions,
            array_agg(DISTINCT embedding_model_key) AS embedding_model_ids
            FROM mosaic_catalog_search.product_document WHERE dataset_id=%s""",
            (dataset,),
        ).fetchone()
        receipt = connection.execute(
            "SELECT catalog_sha256 FROM mosaic_live_search.receipt WHERE singleton"
        ).fetchone()
        indexes = [
            {"name": name}
            for name, state in index_states_on(
                connection,
                (
                    "real_search_fts_idx",
                    "real_search_trigram_idx",
                    "real_search_vector_idx",
                ),
                schema="mosaic_catalog_search",
            ).items()
            if state != "valid"
        ]
        functions = connection.execute("""SELECT required.name FROM
            (VALUES('search_hybrid_rrf'),('search_product_evidence'),('matches_filters'),('query_term_coverage')) AS required(name)
            WHERE NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                WHERE n.nspname='mosaic_live_search' AND p.proname=required.name)""").fetchall()
        expected = connection.execute(
            "SELECT expected_products FROM mosaic_catalog_stage.dataset WHERE dataset_id=%s",
            (dataset,),
        ).fetchone()["expected_products"]
    return dict(row) | {
        "dataset_id": dataset,
        "dataset_manifest_sha256": receipt["catalog_sha256"],
        "schema_ready": True,
        "catalog_ready": row["product_count"]
        == expected
        == row["embedded_product_count"]
        and not indexes
        and not functions,
        "premium_product_count": 0,
        "evidence_product_count": row["product_count"],
        "evidence_note": "Original specification text is available for every product; citation records are registered on first access. Reviews are an explicitly sampled subset.",
        "missing_retrieval_indexes": [item["name"] for item in indexes] or None,
        "missing_retrieval_functions": [item["name"] for item in functions] or None,
        "exact_neighbor_ground_truth": "missing",
    }
