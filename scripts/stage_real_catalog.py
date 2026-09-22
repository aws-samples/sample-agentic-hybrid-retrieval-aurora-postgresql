#!/usr/bin/env python3
"""Load preserved product records and verified embeddings into Aurora staging.

The live mosaic and mosaic_search schemas are never written by this tool.
Records and vectors are checkpointed separately, so either phase can resume.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.embed_real_catalog import (
    COHERE_EMBED_V4_MODEL_ID,
    batch_identity,
    iter_batches,
    load_batch,
    verified_selection,
)
from scripts.prepare_real_catalog import canonical, embedding_text, sha256
from scripts.retrieval_profile import load_profile

SCHEMA = "mosaic_catalog_stage"
# About 8 MiB of vector payload per commit, independent of retrieval settings.
EMBEDDING_TRANSACTION_ROWS = 2048


def validate_dsn(dsn: str) -> None:
    """Require an Aurora endpoint and TLS without echoing secret connection data."""
    try:
        values = conninfo_to_dict(dsn)
        host = values.get("host", "")
        valid = (
            ".cluster-" in host
            and host.endswith((".rds.amazonaws.com", ".rds.amazonaws.com.cn"))
            and values.get("sslmode") in {"require", "verify-ca", "verify-full"}
        )
    except psycopg.ProgrammingError:
        valid = False
    if not valid:
        raise ValueError(
            "Aurora connection rule: use DATABASE_URL with an Aurora cluster endpoint and TLS; "
            "local databases and unencrypted connections are not accepted."
        )


def require_aurora_writer(conn, dataset: str) -> None:
    """Refuse non-Aurora, unencrypted or concurrent dataset writers."""
    conn.execute("SET lock_timeout = '5s'")
    conn.execute("SET statement_timeout = '120s'")
    conn.execute("SELECT aurora_version()")
    if not conn.execute(
        "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
    ).fetchone()[0]:
        raise ValueError(
            "Aurora TLS rule: connection is not encrypted; reconnect with TLS."
        )
    if not conn.execute(
        "SELECT pg_try_advisory_lock(hashtext(%s))", (SCHEMA + ":" + dataset,)
    ).fetchone()[0]:
        raise ValueError(
            "Staging writer rule: dataset is locked; let its existing writer finish."
        )


def create_staging_tables(conn) -> None:
    """Keep imported data isolated from every live application table."""
    conn.execute("CREATE SCHEMA IF NOT EXISTS mosaic_catalog_stage")
    conn.execute("REVOKE ALL ON SCHEMA mosaic_catalog_stage FROM PUBLIC")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mosaic_catalog_stage.dataset (
            dataset_id text PRIMARY KEY,
            catalog_sha256 text NOT NULL,
            manifest jsonb NOT NULL,
            expected_products integer NOT NULL CHECK (expected_products > 0),
            records_complete boolean NOT NULL DEFAULT false,
            embeddings_complete boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    conn.execute(
        sql.SQL("""
        CREATE TABLE IF NOT EXISTS mosaic_catalog_stage.product (
            dataset_id text NOT NULL REFERENCES mosaic_catalog_stage.dataset,
            parent_asin text NOT NULL,
            source_department text NOT NULL,
            original jsonb NOT NULL,
            source_record_sha256 text NOT NULL,
            title text NOT NULL,
            categories text[] NOT NULL,
            image_url text NOT NULL,
            embedding_text text NOT NULL,
            embedding_text_sha256 text NOT NULL,
            embedding_model_key text,
            embedded_input_sha256 text,
            embedding vector({dimensions}),
            PRIMARY KEY (dataset_id, parent_asin),
            CHECK (
                (embedding IS NULL AND embedding_model_key IS NULL AND embedded_input_sha256 IS NULL)
                OR (embedding IS NOT NULL AND embedding_model_key IS NOT NULL
                    AND embedded_input_sha256 IS NOT NULL
                    AND embedded_input_sha256 = embedding_text_sha256)
            )
        )
    """).format(dimensions=sql.Literal(load_profile().vector_dimension))
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mosaic_catalog_stage.loaded_batch (
            dataset_id text NOT NULL REFERENCES mosaic_catalog_stage.dataset,
            batch_sha256 text NOT NULL,
            kind text NOT NULL CHECK (kind IN ('records', 'embeddings')),
            products integer NOT NULL CHECK (products > 0),
            loaded_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (dataset_id, batch_sha256, kind)
        )
    """)


def initialize(conn, dataset: str, manifest: dict) -> None:
    """Create a separate dataset record, refusing to overwrite another selection."""
    require_aurora_writer(conn, dataset)
    create_staging_tables(conn)
    conn.execute(
        """INSERT INTO mosaic_catalog_stage.dataset
           (dataset_id, catalog_sha256, manifest, expected_products)
           VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
        (dataset, manifest["catalog_sha256"], Jsonb(manifest), manifest["products"]),
    )
    existing = conn.execute(
        "SELECT catalog_sha256, expected_products FROM mosaic_catalog_stage.dataset WHERE dataset_id = %s",
        (dataset,),
    ).fetchone()
    if existing != (manifest["catalog_sha256"], manifest["products"]):
        raise ValueError(
            f"Dataset identity rule: {dataset} contains another selection; use a new dataset ID."
        )
    conn.commit()


def iter_record_pages(directory: Path):
    page = []
    with gzip.open(directory / "catalog.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            original = row["original"]
            text = row["embedding_text"]
            if (
                row["source_record_sha256"] != sha256(canonical(original))
                or row["embedding_text_sha256"] != sha256(text)
                or text != embedding_text(original)
            ):
                raise ValueError(
                    f"Staging source rule: {row['parent_asin']} text changed; rebuild the selection."
                )
            page.append(row)
            if len(page) == 1000:
                yield page
                page = []
    if page:
        yield page


def loaded(conn, dataset: str, key: str, kind: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM mosaic_catalog_stage.loaded_batch WHERE dataset_id=%s AND batch_sha256=%s AND kind=%s",
            (dataset, key, kind),
        ).fetchone()
        is not None
    )


def mark_batch(conn, dataset: str, key: str, kind: str, count: int) -> None:
    conn.execute(
        "INSERT INTO mosaic_catalog_stage.loaded_batch (dataset_id, batch_sha256, kind, products) VALUES (%s,%s,%s,%s)",
        (dataset, key, kind, count),
    )
    conn.commit()


def load_records(conn, dataset: str, directory: Path, expected: int) -> None:
    """COPY complete source records in restartable transactions, with no upserts."""
    count = 0
    started = time.monotonic()
    for rows in iter_record_pages(directory):
        key = sha256(
            canonical(
                [[row["parent_asin"], row["source_record_sha256"]] for row in rows]
            )
        )
        if not loaded(conn, dataset, key, "records"):
            with conn.cursor().copy("""
                COPY mosaic_catalog_stage.product
                (dataset_id, parent_asin, source_department, original,
                 source_record_sha256, title, categories, image_url,
                 embedding_text, embedding_text_sha256) FROM STDIN
            """) as copy:
                for row in rows:
                    copy.write_row(
                        (
                            dataset,
                            row["parent_asin"],
                            row["source_department"],
                            Jsonb(row["original"]),
                            row["source_record_sha256"],
                            row["original"]["title"],
                            row["original"]["categories"],
                            row["image_url"],
                            row["embedding_text"],
                            row["embedding_text_sha256"],
                        )
                    )
            mark_batch(conn, dataset, key, "records", len(rows))
        count += len(rows)
        if count % 10000 == 0:
            print(
                json.dumps(
                    {
                        "phase": "records",
                        "products": count,
                        "elapsed_seconds": round(time.monotonic() - started),
                    }
                ),
                flush=True,
            )
    actual = conn.execute(
        "SELECT count(*) FROM mosaic_catalog_stage.product WHERE dataset_id=%s",
        (dataset,),
    ).fetchone()[0]
    if count != expected or actual != expected:
        raise ValueError(
            f"Staging count rule: read {count}, loaded {actual}, expected {expected}; inspect batch checkpoints."
        )
    conn.execute(
        "UPDATE mosaic_catalog_stage.dataset SET records_complete=true WHERE dataset_id=%s",
        (dataset,),
    )
    conn.commit()


def write_embedding_transaction(conn, dataset: str, batches: list) -> int:
    """Commit a bounded group of vectors and its original batch identities together.

    Args:
        conn: Aurora connection holding the dataset writer lock.
        dataset: Existing source selection identity.
        batches: Verified cache keys, source rows and matching vectors.

    Returns:
        Number of source records updated and checkpointed in this transaction.
    """
    count = sum(len(rows) for _, rows, _ in batches)
    if not count:
        return 0
    try:
        with conn.cursor().copy(
            "COPY stage_embedding_batch FROM STDIN (FORMAT BINARY)"
        ) as copy:
            copy.set_types(["text", "text", "text", "vector"])
            for _, rows, vectors in batches:
                for row, vector in zip(rows, vectors, strict=True):
                    copy.write_row(
                        (
                            row["parent_asin"],
                            row["embedding_text_sha256"],
                            COHERE_EMBED_V4_MODEL_ID,
                            vector,
                        )
                    )
        conn.execute("ANALYZE stage_embedding_batch")
        changed = conn.execute(
            """
            UPDATE mosaic_catalog_stage.product p
            SET embedding=b.embedding, embedded_input_sha256=b.text_sha256,
                embedding_model_key=b.model_id
            FROM stage_embedding_batch b
            WHERE p.dataset_id=%s AND p.parent_asin=b.parent_asin
              AND p.embedding_text_sha256=b.text_sha256 AND p.embedding IS NULL
            """,
            (dataset,),
        ).rowcount
        if changed != count:
            raise ValueError(
                f"Embedding staging rule: updated {changed} of {count} records; "
                "verify the loaded records and input hashes before retrying."
            )
        with conn.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO mosaic_catalog_stage.loaded_batch
                   (dataset_id, batch_sha256, kind, products) VALUES (%s,%s,%s,%s)""",
                [(dataset, key, "embeddings", len(rows)) for key, rows, _ in batches],
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return count


def load_embeddings(conn, dataset: str, directory: Path, expected: int) -> None:
    """Load matching cached vectors; a partial cache stays explicitly incomplete."""
    from pgvector.psycopg import register_vector

    register_vector(conn)
    conn.execute(
        sql.SQL("""
        CREATE TEMP TABLE stage_embedding_batch (
            parent_asin text PRIMARY KEY, text_sha256 text, model_id text,
            embedding vector({dimensions})
        ) ON COMMIT DELETE ROWS
    """).format(dimensions=sql.Literal(load_profile().vector_dimension))
    )
    checkpoints = dict(
        conn.execute(
            "SELECT batch_sha256, products FROM mosaic_catalog_stage.loaded_batch "
            "WHERE dataset_id=%s AND kind='embeddings'",
            (dataset,),
        ).fetchall()
    )
    available = 0
    unavailable = 0
    newly_loaded = 0
    pending = []
    pending_rows = 0
    started = time.monotonic()
    for rows in iter_batches(directory):
        identity = batch_identity(rows)
        key = sha256(canonical(identity))
        path = directory / "embeddings" / f"{key}.npz"
        if not path.exists():
            unavailable += len(rows)
            continue
        vectors, _ = load_batch(path, identity)
        if key in checkpoints:
            if checkpoints[key] != len(rows):
                raise ValueError(
                    f"Embedding checkpoint rule: {key} records {checkpoints[key]} products, "
                    f"expected {len(rows)}; inspect this dataset's saved checkpoint."
                )
        else:
            pending.append((key, rows, vectors))
            pending_rows += len(rows)
            if pending_rows >= EMBEDDING_TRANSACTION_ROWS:
                newly_loaded += write_embedding_transaction(conn, dataset, pending)
                pending = []
                pending_rows = 0
                print(
                    json.dumps(
                        {
                            "phase": "embeddings",
                            "newly_loaded": newly_loaded,
                            "total_loaded": sum(checkpoints.values()) + newly_loaded,
                            "elapsed_seconds": round(time.monotonic() - started),
                        }
                    ),
                    flush=True,
                )
        available += len(rows)
    newly_loaded += write_embedding_transaction(conn, dataset, pending)
    conn.execute(
        "UPDATE mosaic_catalog_stage.dataset SET embeddings_complete=%s WHERE dataset_id=%s",
        (available == expected and unavailable == 0, dataset),
    )
    conn.commit()
    print(
        json.dumps(
            {
                "phase": "embeddings",
                "available": available,
                "unavailable": unavailable,
                "complete": available == expected and unavailable == 0,
            }
        ),
        flush=True,
    )


def verify(conn, dataset: str, directory: Path) -> dict:
    """Report stored counts and text integrity without claiming search quality."""
    result = conn.execute(
        """
        SELECT count(*), count(embedding),
            count(*) FILTER (WHERE embedding IS NOT NULL AND
                (embedded_input_sha256 IS DISTINCT FROM embedding_text_sha256
                 OR embedding_model_key IS DISTINCT FROM %s OR vector_dims(embedding) <> %s)),
            count(*) FILTER (WHERE encode(sha256(convert_to(embedding_text, 'UTF8')), 'hex') <> embedding_text_sha256)
        FROM mosaic_catalog_stage.product WHERE dataset_id=%s
    """,
        (COHERE_EMBED_V4_MODEL_ID, load_profile().vector_dimension, dataset),
    ).fetchone()
    expected, records_complete, embeddings_complete = conn.execute(
        "SELECT expected_products, records_complete, embeddings_complete FROM mosaic_catalog_stage.dataset WHERE dataset_id=%s",
        (dataset,),
    ).fetchone()
    report = {
        "dataset_id": dataset,
        "expected_products": expected,
        "products": result[0],
        "embeddings": result[1],
        "incompatible_embeddings": result[2],
        "text_hash_mismatches": result[3],
        "records_complete": records_complete,
        "embeddings_complete": embeddings_complete,
        "ready_for_search_validation": result == (expected, expected, 0, 0)
        and records_complete
        and embeddings_complete,
        "live_catalog_promoted": False,
    }
    (directory / "aurora-staging-report.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps(report), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument(
        "--phase", choices=("records", "embeddings", "verify"), required=True
    )
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    dsn = os.getenv("DATABASE_URL", "")
    validate_dsn(dsn)
    manifest = verified_selection(args.selection)
    with psycopg.connect(
        dsn, connect_timeout=10, application_name="mosaic-real-catalog-stage"
    ) as conn:
        initialize(conn, args.dataset_id, manifest)
        if args.phase == "records":
            load_records(conn, args.dataset_id, args.selection, manifest["products"])
        elif args.phase == "embeddings":
            load_embeddings(conn, args.dataset_id, args.selection, manifest["products"])
        report = verify(conn, args.dataset_id, args.selection)
        if args.require_complete and not report["ready_for_search_validation"]:
            raise ValueError(
                f"Staging completeness rule: {report['embeddings']} embeddings for "
                f"{report['expected_products']} expected products; finish and verify both import phases."
            )


if __name__ == "__main__":
    main()
