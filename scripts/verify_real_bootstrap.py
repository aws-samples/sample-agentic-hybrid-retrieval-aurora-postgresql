#!/usr/bin/env python3
"""Verify a fresh Aurora workshop contains only the pinned real product catalog."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.stage_real_catalog import validate_dsn


def verify(connection, contract: dict) -> dict:
    """Check persisted source identities, saved vectors and the absence of legacy rows.

    Args:
        connection: Aurora connection using a dict row factory.
        contract: The source-owned real-catalog release contract.

    Returns:
        Measured catalog counts after every check passes.

    Raises:
        ValueError: A loaded catalog, vector, receipt or retrieval index disagrees.
    """
    connection.execute("SELECT aurora_version()")
    dataset, products = contract["dataset_id"], contract["products"]
    counts = connection.execute(
        """SELECT
          (SELECT count(*) FROM mosaic.product) AS registered_products,
          (SELECT count(*) FROM mosaic.product WHERE source_system IS DISTINCT FROM %s) AS foreign_products,
          (SELECT count(*) FROM mosaic.brand WHERE is_synthetic) AS synthetic_brands,
          (SELECT count(*) FROM mosaic_search.product_document) AS legacy_documents,
          (SELECT count(*) FROM mosaic_search.corpus_lexeme) AS legacy_lexemes,
          (SELECT count(*) FROM mosaic_search.corpus_surface_lexeme) AS legacy_surface_lexemes,
          count(*) AS products,
          count(*) FILTER (WHERE d.dataset_id=%s AND d.embedding IS NOT NULL
            AND vector_dims(d.embedding)=%s
            AND d.embedding_model_key=%s) AS embedded_products
        FROM mosaic_live_search.product_document d""",
        (dataset, dataset, contract["dimensions"], contract["embedding_model_id"]),
    ).fetchone()
    expected = {name: 0 for name in counts}
    expected.update(
        registered_products=products, products=products, embedded_products=products
    )
    if counts != expected:
        raise ValueError(
            f"Real-only bootstrap rule: found {counts}, expected {expected}; "
            "use a fresh Aurora database, run make db-bootstrap-schema, then restore the pinned real catalog."
        )
    receipt = connection.execute(
        "SELECT dataset_id,catalog_sha256 FROM mosaic_live_search.receipt "
        "WHERE singleton AND prepared_at IS NOT NULL"
    ).fetchone()
    if receipt != {"dataset_id": dataset, "catalog_sha256": contract["catalog_sha256"]}:
        raise ValueError(
            f"Real-only receipt rule: found {receipt!r}; restore the catalog matching db/config/real-catalog-cache.json."
        )
    missing = connection.execute(
        """SELECT required.name FROM (VALUES ('real_search_fts_idx'),
          ('real_search_trigram_idx'),('real_search_vector_idx')) required(name)
        WHERE NOT EXISTS (SELECT 1 FROM pg_index i
          JOIN pg_class c ON c.oid=i.indexrelid
          JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname='mosaic_catalog_search' AND c.relname=required.name
            AND i.indisvalid AND i.indisready)"""
    ).fetchall()
    if missing:
        raise ValueError(
            f"Real-only index rule: missing or invalid indexes {missing}; "
            "resume scripts/real_catalog_cache.py restore for the pinned archive."
        )
    ready = connection.execute(
        "SELECT EXISTS(SELECT 1 FROM mosaic_live_search.corpus_lexeme) "
        "AND EXISTS(SELECT 1 FROM mosaic_live_search.corpus_surface_lexeme) AS ready"
    ).fetchone()["ready"]
    if not ready:
        raise ValueError(
            "Real-only vocabulary rule: ready=False; restore the verified mosaic_live_search vocabulary cache."
        )
    return counts


def main() -> None:
    dsn = os.environ.get("DATABASE_URL", "")
    validate_dsn(dsn)
    contract = json.loads((ROOT / "db/config/real-catalog-cache.json").read_text())
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        print(json.dumps(verify(connection, contract), sort_keys=True))


if __name__ == "__main__":
    main()
