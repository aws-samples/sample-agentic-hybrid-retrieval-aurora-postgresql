#!/usr/bin/env python3
"""Prepare the loaded listings for the app: prices, identities and search SQL.

Searches read mosaic_search.product_listing_view (db/sql/06_retrieval_projection.sql),
which reuses product_listing's indexes. Its offset reserves distinct product
identities for telemetry and citations; original parent ASINs and every saved
vector remain unchanged.
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.catalog.corpus_vocabulary import refresh as refresh_vocabulary
from scripts.catalog.embedding_model import COHERE_EMBED_V4_MODEL_ID
from scripts.catalog.migrate_search_schema import require_migrated
from scripts.catalog.prepare_staged_catalog_search import require_complete
from scripts.catalog.stage_real_catalog import require_aurora_writer, validate_dsn
from scripts.checks.retrieval_profile import load_profile
from service.catalog_runtime import LISTING_TABLE, LISTING_VIEW, SEARCH_SCHEMA
from service.search_sql import search_sql, without_psql_lines

PRODUCT_ID_OFFSET = 1_000_000
LISTING = f"{SEARCH_SCHEMA}.{LISTING_TABLE}"
VIEW = f"{SEARCH_SCHEMA}.{LISTING_VIEW}"
PROJECTION_FILE = Path("db/sql/06_retrieval_projection.sql")
COVERAGE_FILE = Path("db/sql/11_query_coverage.sql")

# Each listing's recorded source price, keyed for the budget filter
# (db/sql/06_retrieval_projection.sql explains why it is a separate table). Only
# exact numeric prices qualify: "from 19.99" is not one price.
SOURCE_PRICE_SQL = f"""
INSERT INTO {SEARCH_SCHEMA}.source_price (product_id, price_cents)
SELECT d.product_id + {PRODUCT_ID_OFFSET},
       round((s.original->>'price')::numeric * 100)::bigint
FROM {LISTING} d
JOIN mosaic_catalog_stage.product s
  ON s.dataset_id = d.dataset_id AND s.parent_asin = d.parent_asin
WHERE jsonb_typeof(s.original->'price') = 'number'
ON CONFLICT (product_id) DO UPDATE SET price_cents = EXCLUDED.price_cents
"""


def preparation_sha256(root: Path = ROOT) -> str:
    """Identity of the SQL this preparation runs: prices, view, search and coverage."""
    return hashlib.sha256(
        (
            SOURCE_PRICE_SQL
            + without_psql_lines((root / PROJECTION_FILE).read_text(encoding="utf-8"))
            + without_psql_lines(search_sql(root, solutions=True))
            + without_psql_lines((root / COVERAGE_FILE).read_text(encoding="utf-8"))
        ).encode()
    ).hexdigest()


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


def load_source_prices(connection) -> int:
    """Copy each listing's recorded source price into the keyed budget table."""
    loaded = connection.execute(SOURCE_PRICE_SQL).rowcount
    stored = connection.execute(
        f"SELECT count(*) FROM {SEARCH_SCHEMA}.source_price"
    ).fetchone()[0]
    if stored != loaded:
        raise ValueError(
            f"Source price rule: {stored} stored prices for {loaded} priced listings; "
            "fix: rebuild the source price table from the selected catalog."
        )
    connection.execute(f"ANALYZE {SEARCH_SCHEMA}.source_price")
    return loaded


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
    require_migrated(connection)
    register_embedding_model(connection)
    projection = connection.execute(
        f"SELECT dataset_id,catalog_sha256 FROM {SEARCH_SCHEMA}.product_listing_receipt "
        "WHERE singleton"
    ).fetchone()
    if projection != (dataset_id, dataset[3]):
        raise ValueError(
            f"Live catalog rule: projection {projection!r} differs from {dataset_id}; prepare and verify that exact selection first."
        )
    collision = connection.execute(
        f"""SELECT p.product_id FROM mosaic.product p
        JOIN {LISTING} d ON p.product_id=d.product_id+%s
        WHERE p.source_system<>%s OR p.sku<>d.parent_asin LIMIT 1""",
        (PRODUCT_ID_OFFSET, dataset_id),
    ).fetchone()
    if collision:
        raise ValueError(
            f"Product identity rule: {collision[0]} is already assigned; choose and review another reserved range before preparing."
        )
    connection.execute("SET statement_timeout='30min'")
    connection.execute(f"""CREATE TABLE IF NOT EXISTS {SEARCH_SCHEMA}.receipt (
        singleton boolean PRIMARY KEY CHECK(singleton), dataset_id text NOT NULL,
        catalog_sha256 text NOT NULL, prepared_at timestamptz,
        product_id_offset bigint NOT NULL, preparation_sha256 text NOT NULL
    )""")
    existing = connection.execute(
        f"SELECT dataset_id,catalog_sha256,product_id_offset FROM {SEARCH_SCHEMA}.receipt"
    ).fetchone()
    if existing and existing != (dataset_id, dataset[3], PRODUCT_ID_OFFSET):
        raise ValueError(
            f"Live catalog identity rule: existing receipt {existing!r} differs; preserve it and prepare a separately reviewed migration."
        )
    load_source_prices(connection)
    connection.execute(f"""INSERT INTO mosaic.brand(brand_key,display_name,is_synthetic)
        SELECT DISTINCT 'reviews-2023:'||md5(coalesce(brand_name,'')),
            coalesce(brand_name,''),false FROM {LISTING}
        ON CONFLICT(brand_key) DO NOTHING""")
    # A taxonomy path can hold listings of several derived categories; its
    # display name is the category most of its listings carry.
    connection.execute(f"""INSERT INTO mosaic.category(domain,category_key,display_name,category_path,depth)
        SELECT domain,'reviews-2023:'||md5(domain::text||':'||category_path),
            mode() WITHIN GROUP (ORDER BY category_key),category_path,1
        FROM {LISTING} GROUP BY domain,category_path
        ON CONFLICT(category_key) DO NOTHING""")
    connection.execute(
        f"""INSERT INTO mosaic.product
        (product_id,sku,brand_id,category_id,canonical_group_id,model_name,title,
         short_description,long_description,attributes,source_system,content_hash)
        SELECT d.product_id,d.parent_asin,b.brand_id,c.category_id,d.parent_asin,
            d.model_name,d.title,d.short_description,d.body_text,d.attributes,%s,d.source_record_sha256
        FROM {VIEW} d
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

    connection.execute(without_psql_lines(search_sql(ROOT, solutions=True)))
    connection.execute(
        without_psql_lines((ROOT / COVERAGE_FILE).read_text(encoding="utf-8"))
    )
    connection.commit()
    ready = connection.execute(
        f"SELECT EXISTS(SELECT 1 FROM {SEARCH_SCHEMA}.corpus_lexeme) "
        f"AND EXISTS(SELECT 1 FROM {SEARCH_SCHEMA}.corpus_surface_lexeme)"
    ).fetchone()[0]
    if not ready:
        refresh_vocabulary(connection, SEARCH_SCHEMA)
    connection.commit()
    checked = connection.execute(f"""SELECT count(*),count(*) FILTER(WHERE p.content_hash=d.source_record_sha256)
        FROM {VIEW} d JOIN mosaic.product p USING(product_id)""").fetchone()
    if checked != (actual, actual):
        raise ValueError(
            f"Live identity verification: found {checked}, expected {(actual, actual)}; restore the registered source identities before enabling the app."
        )
    preparation_hash = preparation_sha256()
    connection.execute(
        f"""INSERT INTO {SEARCH_SCHEMA}.receipt VALUES(true,%s,%s,now(),%s,%s)
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
