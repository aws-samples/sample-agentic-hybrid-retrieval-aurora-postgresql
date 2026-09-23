#!/usr/bin/env python3
"""Prepare the real catalog for the app without replacing the historical tree.

The live view reuses the verified search table and its existing HNSW index.
An offset reserves distinct product identities for telemetry and citations;
original parent ASINs and every saved vector remain unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.corpus_vocabulary import refresh as refresh_vocabulary
from scripts.embed_catalog import COHERE_EMBED_V4_MODEL_ID
from scripts.prepare_staged_catalog_search import require_complete, search_functions
from scripts.retrieval_profile import load_profile
from scripts.stage_real_catalog import require_aurora_writer, validate_dsn

PRODUCT_ID_OFFSET = 1_000_000
SCHEMA = "mosaic_live_search"

VIEW_SQL = f"""
CREATE OR REPLACE VIEW {SCHEMA}.product_document AS
SELECT d.product_id + {PRODUCT_ID_OFFSET} AS product_id,
       d.dataset_id, d.parent_asin, d.source_record_sha256, d.embedding_text_sha256,
       d.parent_asin AS sku, d.domain, d.category_key, d.category_path,
       coalesce(d.brand_name, '') AS brand_name, d.parent_asin AS model_name,
       d.title, coalesce(nullif(d.body_text, ''), d.feature_text) AS short_description,
       d.price_cents, NULL::bigint AS list_price_cents, 'USD'::text AS currency,
       d.availability, NULL::integer AS inventory_count, d.rating,
       NULL::integer AS review_count, d.attributes, ARRAY[]::text[] AS tags,
       d.is_refurbished, d.is_sponsored, d.catalog_asset_key, d.canonical_group_id,
       d.challenge_cohorts, d.is_retrieval_anchor, false AS is_flagship,
       NULL::text AS media_tier, NULL::real AS freshness_score,
       NULL::real AS popularity_score, NULL::timestamptz AS updated_at,
       d.title_text, d.identity_text, d.feature_text, d.body_text, d.trigram_text,
       d.embedding_text,
       'Catalog identity: parent ASIN ' || d.parent_asin || E'.\\n' || d.embedding_text AS rerank_text,
       d.embedding, d.embedding_model_key, d.search_document,
       -- The listing price the source recorded when it was collected. It is
       -- not a current offer, so it never feeds price_cents, filters or the
       -- synthesis price check; it is here for SQL that asks about it by name.
       CASE WHEN jsonb_typeof(s.original->'price') = 'number'
            THEN round((s.original->>'price')::numeric * 100)::bigint
       END AS historical_price_cents
FROM mosaic_catalog_search.product_document d
LEFT JOIN mosaic_catalog_stage.product s
       ON s.dataset_id = d.dataset_id AND s.parent_asin = d.parent_asin
"""


def live_search_functions(source: str, *, repair_labs: bool = True) -> str:
    """Render the same retrieval SQL for source records with unknown commerce facts."""
    functions = search_functions(source, repair_labs=repair_labs).replace(
        "mosaic_catalog_search.", SCHEMA + "."
    )
    functions = functions.replace(
        "NOT product_is_refurbished", "product_is_refurbished IS NOT TRUE"
    ).replace("NOT product_is_sponsored", "product_is_sponsored IS NOT TRUE")
    boundary = "CREATE OR REPLACE FUNCTION mosaic_search.search_product_evidence("
    evidence_sql = boundary + source.split(boundary, 1)[1]
    return functions + "\n" + evidence_sql.replace("mosaic_search.", SCHEMA + ".")


def register_embedding_model(connection) -> None:
    """Register the verified cache model before evidence can reference its vectors."""
    connection.execute(
        """UPDATE mosaic.embedding_model SET is_active = false
        WHERE is_active AND model_key <> %s""",
        (COHERE_EMBED_V4_MODEL_ID,),
    )
    connection.execute(
        """INSERT INTO mosaic.embedding_model
        (model_key, provider, model_name, dimensions, distance_metric, is_active)
        VALUES (%s, 'bedrock', %s, %s, 'cosine', true)
        ON CONFLICT (model_key) DO UPDATE
        SET provider = EXCLUDED.provider, model_name = EXCLUDED.model_name,
            dimensions = EXCLUDED.dimensions, distance_metric = EXCLUDED.distance_metric,
            is_active = EXCLUDED.is_active""",
        (
            COHERE_EMBED_V4_MODEL_ID,
            COHERE_EMBED_V4_MODEL_ID,
            load_profile().vector_dimension,
        ),
    )


def prepare(connection, dataset_id: str) -> dict:
    """Prepare identities, source-bound search and vocabulary on encrypted Aurora."""
    started = time.monotonic()
    dataset = connection.execute(
        "SELECT expected_products,records_complete,embeddings_complete,catalog_sha256 "
        "FROM mosaic_catalog_stage.dataset WHERE dataset_id=%s",
        (dataset_id,),
    ).fetchone()
    actual = connection.execute(
        """SELECT count(*) FROM mosaic_catalog_stage.product WHERE dataset_id=%s
        AND embedding IS NOT NULL AND embedded_input_sha256=embedding_text_sha256
        AND vector_dims(embedding)=1024""",
        (dataset_id,),
    ).fetchone()[0]
    require_complete(dataset, actual)
    register_embedding_model(connection)
    projection = connection.execute(
        "SELECT dataset_id,catalog_sha256 FROM mosaic_catalog_search.receipt WHERE singleton"
    ).fetchone()
    if projection != (dataset_id, dataset[3]):
        raise ValueError(
            f"Live catalog rule: projection {projection!r} differs from {dataset_id}; prepare and verify that exact selection first."
        )
    collision = connection.execute(
        """SELECT p.product_id FROM mosaic.product p
        JOIN mosaic_catalog_search.product_document d ON p.product_id=d.product_id+%s
        WHERE p.source_system<>%s OR p.sku<>d.parent_asin LIMIT 1""",
        (PRODUCT_ID_OFFSET, dataset_id),
    ).fetchone()
    if collision:
        raise ValueError(
            f"Product identity rule: {collision[0]} is already assigned; choose and review another reserved range before preparing."
        )
    connection.execute("SET statement_timeout='30min'")
    connection.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    connection.execute(f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.receipt (
        singleton boolean PRIMARY KEY CHECK(singleton), dataset_id text NOT NULL,
        catalog_sha256 text NOT NULL, prepared_at timestamptz,
        product_id_offset bigint NOT NULL, preparation_sha256 text NOT NULL
    )""")
    existing = connection.execute(
        f"SELECT dataset_id,catalog_sha256,product_id_offset FROM {SCHEMA}.receipt"
    ).fetchone()
    if existing and existing != (dataset_id, dataset[3], PRODUCT_ID_OFFSET):
        raise ValueError(
            f"Live catalog identity rule: existing receipt {existing!r} differs; preserve it and prepare a separately reviewed migration."
        )
    connection.execute(VIEW_SQL)
    connection.execute(f"""CREATE INDEX IF NOT EXISTS real_search_public_id_idx
        ON mosaic_catalog_search.product_document ((product_id+{PRODUCT_ID_OFFSET}))""")
    connection.execute("""INSERT INTO mosaic.brand(brand_key,display_name,is_synthetic)
        SELECT DISTINCT 'reviews-2023:'||md5(coalesce(brand_name,'')),
            coalesce(brand_name,''),false FROM mosaic_catalog_search.product_document
        ON CONFLICT(brand_key) DO NOTHING""")
    connection.execute("""INSERT INTO mosaic.category(domain,category_key,display_name,category_path,depth)
        SELECT DISTINCT domain,'reviews-2023:'||md5(domain::text||':'||category_path),
            category_key,category_path,1 FROM mosaic_catalog_search.product_document
        ON CONFLICT(category_key) DO NOTHING""")
    connection.execute(
        f"""INSERT INTO mosaic.product
        (product_id,sku,brand_id,category_id,canonical_group_id,model_name,title,
         short_description,long_description,attributes,source_system,content_hash)
        SELECT d.product_id,d.parent_asin,b.brand_id,c.category_id,d.parent_asin,
            d.model_name,d.title,d.short_description,d.body_text,d.attributes,%s,d.source_record_sha256
        FROM {SCHEMA}.product_document d
        JOIN mosaic.brand b ON b.brand_key='reviews-2023:'||md5(d.brand_name)
        JOIN mosaic.category c ON c.category_key='reviews-2023:'||md5(d.domain::text||':'||d.category_path)
        ON CONFLICT(product_id) DO NOTHING""",
        (dataset_id,),
    )
    connection.execute(
        "SELECT setval(pg_get_serial_sequence('mosaic.product','product_id'),(SELECT max(product_id) FROM mosaic.product))"
    )
    connection.commit()
    print(
        json.dumps(
            {"phase": "identities", "seconds": round(time.monotonic() - started, 2)}
        ),
        flush=True,
    )

    source = (ROOT / "db/sql/09_search_functions.sql").read_text()
    functions = live_search_functions(source)
    connection.execute(functions)
    coverage_sql = "\n".join(
        line
        for line in (ROOT / "db/sql/20_query_coverage.sql").read_text().splitlines()
        if not line.startswith("\\")
    )
    connection.execute(coverage_sql.replace("mosaic_search.", SCHEMA + "."))
    connection.commit()
    ready = connection.execute(
        f"SELECT EXISTS(SELECT 1 FROM {SCHEMA}.corpus_lexeme) AND EXISTS(SELECT 1 FROM {SCHEMA}.corpus_surface_lexeme)"
    ).fetchone()[0]
    if not ready:
        refresh_vocabulary(connection, SCHEMA)
    connection.commit()
    checked = connection.execute(f"""SELECT count(*),count(*) FILTER(WHERE p.content_hash=d.source_record_sha256)
        FROM {SCHEMA}.product_document d JOIN mosaic.product p USING(product_id)""").fetchone()
    if checked != (actual, actual):
        raise ValueError(
            f"Live identity verification: found {checked}, expected {(actual, actual)}; restore the registered source identities before enabling the app."
        )
    preparation_hash = hashlib.sha256(
        (VIEW_SQL + functions + coverage_sql).encode()
    ).hexdigest()
    connection.execute(
        f"""INSERT INTO {SCHEMA}.receipt VALUES(true,%s,%s,now(),%s,%s)
        ON CONFLICT(singleton) DO UPDATE SET prepared_at=now(),preparation_sha256=EXCLUDED.preparation_sha256""",
        (dataset_id, dataset[3], PRODUCT_ID_OFFSET, preparation_hash),
    )
    connection.commit()
    return {
        "dataset_id": dataset_id,
        "catalog_sha256": dataset[3],
        "products": actual,
        "registered_products": checked[0],
        "product_id_offset": PRODUCT_ID_OFFSET,
        "new_embeddings_generated": 0,
        "historical_catalog_preserved": True,
        "seconds": round(time.monotonic() - started, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    dsn = os.environ.get("DATABASE_URL", "")
    validate_dsn(dsn)
    with psycopg.connect(dsn, connect_timeout=10) as connection:
        require_aurora_writer(connection, args.dataset_id)
        report = prepare(connection, args.dataset_id)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
