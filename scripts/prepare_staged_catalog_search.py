#!/usr/bin/env python3
"""Build isolated retrieval indexes for a verified real-product import.

The production search functions are installed unchanged apart from their schema
qualifier. This validates the new corpus without replacing the served catalog or
claiming that the old workshop's product targets still apply.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import sys
import time
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.embed_real_catalog import COHERE_EMBED_V4_MODEL_ID
from scripts.lab_state import LABS, _replace_block
from scripts.retrieval_profile import load_profile
from scripts.stage_real_catalog import require_aurora_writer, validate_dsn
from service.source_catalog import product_kind

SEARCH_SCHEMA = "mosaic_catalog_search"

# Missing commerce facts stay null. In particular, a historical listing price
# cannot become a current price, and an unreported condition cannot mean new.
PROJECTION_SQL = """
CREATE TABLE mosaic_catalog_search.product_document AS
WITH source AS (
    SELECT p.*, k.kind,
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
    LEFT JOIN source_product_ids i ON i.parent_asin=p.parent_asin
    WHERE p.dataset_id=%s
)
SELECT coalesce(i.product_id,
           (SELECT count(*) FROM source_product_ids)
           + row_number() OVER (PARTITION BY i.product_id IS NULL ORDER BY parent_asin COLLATE "C")) AS product_id,
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


def search_functions(source: str, *, repair_labs: bool = True) -> str:
    """Scope the shipped retrieval functions to the new corpus, with labs repaired.

    Args:
        source: The repository's complete search-function SQL.
        repair_labs: Restore the reference implementation during initial loading;
            false preserves participant edits when applying a lab repair.

    Returns:
        SQL for the isolated schema, excluding legacy product-evidence tables.
    """
    boundary = "CREATE OR REPLACE FUNCTION mosaic_search.search_product_evidence("
    if source.count(boundary) != 1:
        raise ValueError(
            "Search source rule: missing unique evidence boundary; inspect the production SQL before preparing the catalog."
        )
    scoped = source.split(boundary)[0]
    if repair_labs:
        for lab in (1, 2):
            for start, end, fixed, _ in LABS[lab][1]:
                scoped = _replace_block(scoped, start, end, fixed)
    scoped = "\n".join(
        line for line in scoped.splitlines() if not line.startswith("\\")
    )
    return scoped.replace("mosaic_search.", SEARCH_SCHEMA + ".")


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
    from scripts.prepare_real_catalog import read_base_parents

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
    functions = search_functions((ROOT / "db/sql/09_search_functions.sql").read_text())
    function_hash = hashlib.sha256(functions.encode()).hexdigest()
    projection_hash = hashlib.sha256(
        (PROJECTION_SQL + inspect.getsource(product_kind)).encode()
    ).hexdigest()
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
    conn.execute("SET statement_timeout='60min'")
    conn.execute("CREATE SCHEMA IF NOT EXISTS mosaic_catalog_search")
    conn.execute("""CREATE TABLE IF NOT EXISTS mosaic_catalog_search.receipt (
        singleton boolean PRIMARY KEY CHECK (singleton), dataset_id text NOT NULL,
        catalog_sha256 text NOT NULL, projection_sha256 text NOT NULL,
        functions_sha256 text NOT NULL, prepared_at timestamptz
    )""")
    existing = conn.execute(
        "SELECT dataset_id,catalog_sha256,projection_sha256 FROM mosaic_catalog_search.receipt"
    ).fetchone()
    identity = (dataset_id, dataset[3], projection_hash)
    if existing is not None and existing != identity:
        raise ValueError(
            "Search selection rule: existing projection belongs to a different source or projection; "
            "keep it isolated and review an explicit rebuild before replacing it."
        )
    conn.execute(
        """INSERT INTO mosaic_catalog_search.receipt
        (singleton,dataset_id,catalog_sha256,projection_sha256,functions_sha256)
        VALUES (true,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
        (*identity, function_hash),
    )
    present = conn.execute(
        "SELECT to_regclass('mosaic_catalog_search.product_document') IS NOT NULL"
    ).fetchone()[0]
    started = time.monotonic()
    if not present:
        categories = conn.execute(
            "SELECT DISTINCT categories FROM mosaic_catalog_stage.product WHERE dataset_id=%s",
            (dataset_id,),
        ).fetchall()
        conn.execute(
            "CREATE TEMP TABLE source_product_kinds (categories text[] PRIMARY KEY, kind text NOT NULL) ON COMMIT DROP"
        )
        with conn.cursor().copy("COPY source_product_kinds FROM STDIN") as copy:
            for (path,) in categories:
                copy.write_row((path, product_kind(path)))
        conn.execute(
            "CREATE TEMP TABLE source_product_ids (parent_asin text PRIMARY KEY, product_id bigint NOT NULL UNIQUE) ON COMMIT DROP"
        )
        with conn.cursor().copy("COPY source_product_ids FROM STDIN") as copy:
            for identity, number in base_ids or []:
                copy.write_row((identity, number))
        conn.execute(PROJECTION_SQL, (dataset_id,))
        conn.execute("""ALTER TABLE mosaic_catalog_search.product_document
            ADD PRIMARY KEY (product_id), ADD UNIQUE (parent_asin),
            ALTER COLUMN embedding SET NOT NULL,
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
    indexes = {
        "real_search_fts_idx": "USING gin(search_document)",
        "real_search_trigram_idx": "USING gin(trigram_text gin_trgm_ops)",
        "real_search_kind_idx": "(category_key,product_id)",
        "real_search_vector_idx": (
            "USING hnsw(embedding vector_cosine_ops) "
            f"WITH (m={profile.hnsw_m},ef_construction={profile.hnsw_ef_construction})"
        ),
    }
    timings = {}
    for name, definition in indexes.items():
        started = time.monotonic()
        conn.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {} ON mosaic_catalog_search.product_document "
            ).format(sql.Identifier(name))
            + sql.SQL(definition)
        )
        conn.commit()
        timings[name] = round(time.monotonic() - started, 2)
        print(
            json.dumps(
                {"phase": "search_index", "index": name, "seconds": timings[name]}
            ),
            flush=True,
        )
    conn.execute(functions, prepare=False)
    conn.execute("ANALYZE mosaic_catalog_search.product_document")
    counts = conn.execute(
        """
        SELECT count(*), count(*) FILTER (WHERE
            d.dataset_id<>%s OR p.parent_asin IS NULL OR
            d.title IS DISTINCT FROM p.title OR
            d.source_record_sha256 IS DISTINCT FROM p.source_record_sha256 OR
            d.embedding_text IS DISTINCT FROM p.embedding_text OR
            d.embedding_text_sha256 IS DISTINCT FROM p.embedded_input_sha256 OR
            d.embedding IS DISTINCT FROM p.embedding OR
            d.embedding_model_key IS DISTINCT FROM p.embedding_model_key)
        FROM mosaic_catalog_search.product_document d
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
        "UPDATE mosaic_catalog_search.receipt SET functions_sha256=%s,prepared_at=now()",
        (function_hash,),
    )
    sizes = conn.execute("""SELECT c.relname,pg_relation_size(c.oid),i.indisvalid
        FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
        WHERE i.indrelid='mosaic_catalog_search.product_document'::regclass
        ORDER BY c.relname""").fetchall()
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
