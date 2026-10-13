#!/usr/bin/env python3
"""Load a verified real-product import into mosaic_search.product_listing.

install.sql declares the table and the view searches read; this fills the table
once from the staged source records and then builds the indexes in
db/sql/07_indexes.sql, which is faster than indexing an empty table row by row.
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
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.catalog.embed_real_catalog import COHERE_EMBED_V4_MODEL_ID
from scripts.catalog.migrate_search_schema import require_migrated
from scripts.catalog.stage_real_catalog import require_aurora_writer, validate_dsn
from scripts.checks.retrieval_profile import load_profile
from service.catalog_runtime import LISTING_TABLE, SEARCH_SCHEMA
from service.search_sql import search_sql
from service.source_catalog import (
    ACCESSORY_KINDS,
    classification_sha256,
    classify_product,
    product_kind,
    reviewed_decisions,
)

LISTING = f"{SEARCH_SCHEMA}.{LISTING_TABLE}"
RECEIPT = f"{SEARCH_SCHEMA}.product_listing_receipt"
INDEX_SQL = ROOT / "db/sql/07_indexes.sql"

# Missing commerce facts stay null. In particular, a historical listing price
# cannot become a current price, and an unreported condition cannot mean new.
PROJECTION_COLUMNS = (
    "product_id, dataset_id, parent_asin, source_record_sha256, embedding_text_sha256, "
    "domain, category_key, category_path, brand_name, title, price_cents, availability, "
    "rating, attributes, is_refurbished, is_sponsored, catalog_asset_key, "
    "canonical_group_id, challenge_cohorts, is_retrieval_anchor, title_text, "
    "identity_text, feature_text, body_text, trigram_text, embedding_text, rerank_text, "
    "embedding, embedding_model_key, search_document"
)

PROJECTION_SELECT = """
WITH source AS (
    SELECT p.*, coalesce(l.kind, k.kind) AS kind, i.product_id AS base_product_id,
        nullif(btrim(p.original->'details'->>'Brand'), '') AS brand,
        concat_ws(' ', p.parent_asin, p.original->'details'->>'Brand',
            coalesce(p.original->'details'->>'Model Name',
                     p.original->'details'->>'Item model number'),
            array_to_string(p.categories, ' ')) AS identity,
        concat_ws(' ',
            (SELECT string_agg(value, ' ' ORDER BY ordinal)
             FROM jsonb_array_elements_text(p.original->'features')
                  WITH ORDINALITY AS f(value, ordinal)),
            p.original->'details') AS features,
        (SELECT string_agg(value, E'\\n' ORDER BY ordinal)
         FROM jsonb_array_elements_text(p.original->'description')
              WITH ORDINALITY AS d(value, ordinal)) AS body
    FROM mosaic_catalog_stage.product p
    JOIN source_product_kinds k ON p.categories=k.categories
    LEFT JOIN source_listing_kinds l ON l.parent_asin=p.parent_asin
    LEFT JOIN source_product_ids i ON i.parent_asin=p.parent_asin
    WHERE p.dataset_id=%s
)
SELECT coalesce(base_product_id,
           (SELECT count(*) FROM source_product_ids)
           + row_number() OVER (PARTITION BY base_product_id IS NULL ORDER BY parent_asin COLLATE "C")) AS product_id,
       dataset_id, parent_asin, source_record_sha256, embedding_text_sha256,
       CASE source_department
           WHEN 'Electronics' THEN 'consumer_electronics'
           WHEN 'Office_Products' THEN 'home_office'
           WHEN 'Home_and_Kitchen' THEN 'home_office'
       END::mosaic.product_domain AS domain,
       kind AS category_key, array_to_string(categories, ' > ') AS category_path,
       brand AS brand_name, title,
       NULL::bigint AS price_cents,
       NULL::mosaic.availability_status AS availability,
       (original->>'average_rating')::numeric AS rating,
       original->'details' AS attributes,
       CASE WHEN title ~* '\\m(renewed|refurbished)\\M' THEN true END AS is_refurbished,
       NULL::boolean AS is_sponsored,
       NULL::text AS catalog_asset_key,
       parent_asin AS canonical_group_id,
       ARRAY[]::text[] AS challenge_cohorts,
       false AS is_retrieval_anchor,
       title AS title_text, identity AS identity_text,
       features AS feature_text, coalesce(body, '') AS body_text,
       lower(concat_ws(' ', title, identity)) AS trigram_text,
       embedding_text, embedding_text AS rerank_text,
       embedding, embedding_model_key,
       setweight(to_tsvector('english', title), 'A') ||
       setweight(to_tsvector('english', identity), 'A') ||
       setweight(to_tsvector('english', features), 'B') ||
       setweight(to_tsvector('english', coalesce(body, '')), 'C') AS search_document
FROM source
"""

PROJECTION_SQL = (
    f"INSERT INTO {SEARCH_SCHEMA}.{LISTING_TABLE} ({PROJECTION_COLUMNS})"
    + PROJECTION_SELECT
)


CATEGORY_DECISIONS = ROOT / "db/config/catalog-category-decisions.jsonl"


def projection_sha256() -> str:
    """Version the projection SQL, the category rules and the reviewed decisions."""
    decisions = hashlib.sha256(CATEGORY_DECISIONS.read_bytes()).hexdigest()
    return hashlib.sha256(
        (PROJECTION_SELECT + classification_sha256() + decisions).encode()
    ).hexdigest()


def reference_functions_sha256(root: Path = ROOT) -> str:
    """Identity of the reference search SQL a restore leaves Aurora running."""
    return hashlib.sha256(search_sql(root, solutions=True).encode()).hexdigest()


def index_statements(path: Path = INDEX_SQL) -> list[tuple[str, str]]:
    """The index names and statements in 07_indexes.sql, in file order."""
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.startswith(("\\", "--"))
    ]
    statements = []
    for statement in "\n".join(lines).split(";"):
        statement = statement.strip()
        if statement:
            name = statement.split("IF NOT EXISTS", 1)[1].split()[0]
            statements.append((name, statement))
    return statements


def load_source_kinds(conn, dataset_id: str) -> None:
    """Stage each taxonomy path's category, then each lab-category listing's.

    Paths decide every category except the three lab categories, where the
    listing itself decides what is sold. A reviewed decision then replaces the
    result for its listing on any path. Both temporary tables drop at commit.
    """
    paths = conn.execute(
        "SELECT DISTINCT categories FROM mosaic_catalog_stage.product WHERE dataset_id=%s",
        (dataset_id,),
    ).fetchall()
    conn.execute(
        "CREATE TEMP TABLE source_product_kinds (categories text[] PRIMARY KEY, kind text NOT NULL) ON COMMIT DROP"
    )
    with conn.cursor().copy("COPY source_product_kinds FROM STDIN") as copy:
        for (path,) in paths:
            copy.write_row((path, product_kind(path)))
    listings = conn.execute(
        """SELECT p.parent_asin,p.categories,p.title,p.original->'details',
            concat_ws(' ',p.original->>'features',p.original->>'description')
        FROM mosaic_catalog_stage.product p
        JOIN source_product_kinds k ON p.categories=k.categories
        WHERE p.dataset_id=%s AND k.kind=ANY(%s)""",
        (dataset_id, list(ACCESSORY_KINDS)),
    ).fetchall()
    conn.execute(
        "CREATE TEMP TABLE source_listing_kinds (parent_asin text PRIMARY KEY, kind text NOT NULL, reason text NOT NULL) ON COMMIT DROP"
    )
    kinds = {
        parent_asin: classify_product(path, title, details, text)
        for parent_asin, path, title, details, text in listings
    }
    reviewed = reviewed_decisions(
        CATEGORY_DECISIONS.read_text().splitlines(), dataset_id
    )
    kinds.update(
        {
            asin: (kind, f"reviewed: {reason}")
            for asin, (kind, reason) in reviewed.items()
        }
    )
    with conn.cursor().copy("COPY source_listing_kinds FROM STDIN") as copy:
        for parent_asin, (kind, reason) in kinds.items():
            copy.write_row((parent_asin, kind, reason))
    unknown = conn.execute(
        """SELECT count(*) FROM source_listing_kinds l
        WHERE NOT EXISTS (SELECT 1 FROM mosaic_catalog_stage.product p
                          WHERE p.dataset_id=%s AND p.parent_asin=l.parent_asin)""",
        (dataset_id,),
    ).fetchone()[0]
    if unknown:
        raise ValueError(
            f"Category decision rule: {unknown} reviewed listings are not in {dataset_id}; "
            "review decisions against this exact selection."
        )


def require_complete(dataset: tuple | None, actual: int) -> None:
    """Refuse incomplete or empty inputs even when their flags claim success."""
    if dataset is None:
        raise ValueError(
            "Search input rule: dataset is absent; stage the selected catalog first."
        )
    expected, records_complete, embeddings_complete, _ = dataset
    if (
        expected <= 0
        or actual != expected
        or not records_complete
        or not embeddings_complete
    ):
        raise ValueError(
            f"Search input rule: found {actual}/{expected} verified vectors with "
            f"records_complete={records_complete}, embeddings_complete={embeddings_complete}; "
            "finish and verify the embedding import first."
        )


def base_ids_from_selection(selection: dict, plan_dir: Path) -> list[tuple[str, int]]:
    """Recover the ids a version-2 base keeps: its parents in C-collation order, from 1.

    Version 1 numbered every product by parent ASIN order, so the pinned base
    parent list reproduces those ids without a separate id file.
    """
    plan = selection.get("plan") or {}
    if plan.get("version") != 2:
        return []
    from scripts.catalog.prepare_real_catalog import read_base_parents

    parents = sorted(
        {
            asin
            for group in read_base_parents(plan, plan_dir).values()
            for asin in group
        },
        key=lambda asin: asin.encode("ascii"),
    )
    return [(asin, index) for index, asin in enumerate(parents, start=1)]


def read_base_ids(path: Path | None) -> list[tuple[str, int]]:
    """Physical ids to preserve for products carried over from an earlier projection.

    The file lists `parent_asin<TAB>product_id`. Ids must be positive, unique
    and contiguous from 1, because every addition is numbered after them.
    """
    if path is None:
        return []
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        identity, number = line.split("\t")
        rows.append((identity, int(number)))
    ids = sorted(number for _, number in rows)
    if ids != list(range(1, len(ids) + 1)) or len({i for i, _ in rows}) != len(rows):
        raise ValueError(
            "Base id rule: preserved ids must be unique and contiguous from 1; rebuild the base id list from the earlier projection."
        )
    return rows


def configure_index_build_workers(conn) -> int:
    """Use the Aurora session's parallel capacity, reserving one worker for its leader."""
    workers = max(
        0,
        int(
            conn.execute("SELECT current_setting('max_parallel_workers')").fetchone()[0]
        )
        - 1,
    )
    conn.execute(
        sql.SQL("SET max_parallel_maintenance_workers = {}").format(
            sql.Literal(workers)
        )
    )
    return workers


def prepare(
    conn, dataset_id: str, base_ids: list[tuple[str, int]] | None = None
) -> dict:
    """Build a restartable projection and indexes bound to one source selection.

    Args:
        conn: Encrypted Aurora connection holding the import's writer lock.
        dataset_id: Identity of the complete staged catalog.
        base_ids: Physical ids to keep for carried-over products; additions
            are numbered after the highest one.

    Returns:
        Counts, source hashes, index sizes and preparation times; no quality claim.
    """
    profile = load_profile()
    function_hash = reference_functions_sha256()
    projection_hash = projection_sha256()
    dataset = conn.execute(
        "SELECT expected_products,records_complete,embeddings_complete,catalog_sha256 "
        "FROM mosaic_catalog_stage.dataset WHERE dataset_id=%s",
        (dataset_id,),
    ).fetchone()
    actual = conn.execute(
        """SELECT count(*) FROM mosaic_catalog_stage.product
        WHERE dataset_id=%s AND embedding IS NOT NULL
          AND embedded_input_sha256=embedding_text_sha256
          AND vector_dims(embedding)=%s
          AND embedding_model_key=%s""",
        (dataset_id, profile.vector_dimension, COHERE_EMBED_V4_MODEL_ID),
    ).fetchone()[0]
    require_complete(dataset, actual)
    require_migrated(conn)
    if not conn.execute("SELECT to_regclass(%s) IS NOT NULL", (LISTING,)).fetchone()[0]:
        raise ValueError(
            f"Search schema rule: {LISTING} is absent; fix: run make db-install, "
            "which declares it, before loading the listings."
        )
    conn.execute("SET statement_timeout='60min'")
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {RECEIPT} (
        singleton boolean PRIMARY KEY CHECK (singleton), dataset_id text NOT NULL,
        catalog_sha256 text NOT NULL, projection_sha256 text NOT NULL,
        functions_sha256 text NOT NULL, prepared_at timestamptz
    )""")
    existing = conn.execute(
        f"SELECT dataset_id,catalog_sha256,projection_sha256 FROM {RECEIPT}"
    ).fetchone()
    identity = (dataset_id, dataset[3], projection_hash)
    if existing is not None and existing != identity:
        raise ValueError(
            "Search selection rule: existing projection belongs to a different source or projection; "
            "keep it isolated and review an explicit rebuild before replacing it."
        )
    conn.execute(
        f"""INSERT INTO {RECEIPT}
        (singleton,dataset_id,catalog_sha256,projection_sha256,functions_sha256)
        VALUES (true,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
        (*identity, function_hash),
    )
    loaded = conn.execute(f"SELECT EXISTS (SELECT 1 FROM {LISTING})").fetchone()[0]
    started = time.monotonic()
    if not loaded:
        load_source_kinds(conn, dataset_id)
        conn.execute(
            "CREATE TEMP TABLE source_product_ids (parent_asin text PRIMARY KEY, product_id bigint NOT NULL UNIQUE) ON COMMIT DROP"
        )
        with conn.cursor().copy("COPY source_product_ids FROM STDIN") as copy:
            for identity, number in base_ids or []:
                copy.write_row((identity, number))
        conn.execute(PROJECTION_SQL, (dataset_id,))
        conn.execute(f"""ALTER TABLE {LISTING}
            ADD FOREIGN KEY (dataset_id,parent_asin)
                REFERENCES mosaic_catalog_stage.product(dataset_id,parent_asin)""")
    conn.commit()
    print(
        json.dumps(
            {
                "phase": "search_projection",
                "seconds": round(time.monotonic() - started, 2),
            }
        ),
        flush=True,
    )
    workers = configure_index_build_workers(conn)
    timings = {}
    for name, statement in index_statements():
        started = time.monotonic()
        conn.execute(statement)
        conn.commit()
        timings[name] = round(time.monotonic() - started, 2)
        print(
            json.dumps(
                {"phase": "search_index", "index": name, "seconds": timings[name]}
            ),
            flush=True,
        )
    # An index expression has no statistics until its table is analysed after
    # the index exists. Without them the planner expects 0.5% of the catalog per
    # product ID and scans every listing to fetch each search's shortlist.
    conn.execute(f"ANALYZE {LISTING}")
    counts = conn.execute(
        f"""
        SELECT count(*), count(*) FILTER (WHERE
            d.dataset_id<>%s OR p.parent_asin IS NULL OR
            d.title IS DISTINCT FROM p.title OR
            d.source_record_sha256 IS DISTINCT FROM p.source_record_sha256 OR
            d.embedding_text IS DISTINCT FROM p.embedding_text OR
            d.embedding_text_sha256 IS DISTINCT FROM p.embedded_input_sha256 OR
            d.embedding IS DISTINCT FROM p.embedding OR
            d.embedding_model_key IS DISTINCT FROM p.embedding_model_key)
        FROM {LISTING} d
        LEFT JOIN mosaic_catalog_stage.product p USING(dataset_id,parent_asin)
    """,
        (dataset_id,),
    ).fetchone()
    if counts != (dataset[0], 0):
        raise ValueError(
            f"Search projection rule: {counts[0]} products, {counts[1]} source/vector mismatches; "
            "inspect the projection before running retrieval checks."
        )
    conn.execute(
        f"UPDATE {RECEIPT} SET functions_sha256=%s,prepared_at=now()",
        (function_hash,),
    )
    sizes = conn.execute(
        """SELECT c.relname,pg_relation_size(c.oid),i.indisvalid
        FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
        WHERE i.indrelid=%s::regclass
        ORDER BY c.relname""",
        (LISTING,),
    ).fetchall()
    conn.commit()
    return {
        "dataset_id": dataset_id,
        "catalog_sha256": dataset[3],
        "projection_sha256": projection_hash,
        "functions_sha256": function_hash,
        "products": counts[0],
        "source_vector_mismatches": counts[1],
        "indexes": [
            {"name": name, "bytes": size, "valid": valid} for name, size, valid in sizes
        ],
        "index_ensure_seconds": timings,
        "index_build_workers": workers,
        "profile": profile.as_dict(),
        "live_catalog_promoted": False,
        "retrieval_quality_validated": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--base-ids",
        type=Path,
        help="TSV of parent_asin and physical product_id to preserve from an earlier projection",
    )
    args = parser.parse_args()
    dsn = os.getenv("DATABASE_URL", "")
    validate_dsn(dsn)
    base_ids = read_base_ids(args.base_ids)
    with psycopg.connect(
        dsn, connect_timeout=10, application_name="mosaic-real-catalog-search-prepare"
    ) as conn:
        require_aurora_writer(conn, args.dataset_id)
        report = prepare(conn, args.dataset_id, base_ids)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
