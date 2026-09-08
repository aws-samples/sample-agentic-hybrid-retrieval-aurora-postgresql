#!/usr/bin/env python3
"""Promote a normalized, reviewed Shop cohort with matching vectors and evidence.

The first transaction rolls back after asking the production projection to build
its embedding text. Real vectors are then generated outside database locks. The
final transaction installs catalog rows, vectors and specification evidence
atomically. A local JSON backup records the prior Aurora rows for recovery.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from pathlib import Path

import numpy as np
from psycopg import sql
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.embedding_cache import vector_float32
from service.db import connect
from service.embeddings import get_embedding_provider


def read_rows(path: Path) -> list[dict]:
    """Read one normalized gzip CSV without changing its field values."""
    with gzip.open(path, "rt", newline="") as handle:
        return list(csv.DictReader(handle))


def update_row(connection, table: str, values: dict, product_id: int) -> None:
    """Update an existing product identity and reject a missing target.

    Args:
        connection: Aurora connection participating in the promotion transaction.
        table: Product or offer table in the mosaic schema.
        values: Reviewed normalized values keyed by column name.
        product_id: Existing catalog identity to preserve.
    """
    statement = sql.SQL("UPDATE mosaic.{} SET {} WHERE product_id = %s").format(
        sql.Identifier(table),
        sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(key)) for key in values
        ),
    )
    if connection.execute(statement, (*values.values(), product_id)).rowcount != 1:
        raise ValueError(
            f"Shop promotion identity rule: {product_id} missing from {table}; restore the existing Aurora product before promoting."
        )


def install_catalog(connection, products, offers, brands, categories) -> list[dict]:
    """Apply reviewed rows using Aurora's existing dimension identities.

    Args:
        connection: Aurora connection participating in the promotion transaction.
        products: Reviewed normalized product rows.
        offers: Offers keyed by product identity.
        brands: Normalized brands keyed by their local export identity.
        categories: Normalized categories keyed by their local export identity.

    Returns:
        Embedding text produced by the production projection for each product.
    """
    brand_ids = {
        r["display_name"]: r["brand_id"]
        for r in connection.execute(
            "SELECT brand_id,display_name FROM mosaic.brand"
        ).fetchall()
    }
    category_ids = {
        (r["domain"], r["category_path"]): r["category_id"]
        for r in connection.execute(
            "SELECT category_id,domain::text,category_path FROM mosaic.category"
        ).fetchall()
    }
    ids = []
    for row in products:
        pid = int(row["product_id"])
        ids.append(pid)
        category = categories[row["category_id"]]
        values = {
            key: row[key]
            for key in [
                "model_name",
                "title",
                "short_description",
                "long_description",
                "source_system",
                "content_hash",
            ]
        }
        values.update(
            brand_id=brand_ids[brands[row["brand_id"]]["display_name"]],
            category_id=category_ids[(category["domain"], category["category_path"])],
            attributes=Jsonb(json.loads(row["attributes"])),
        )
        values.update(
            {
                key: json.loads(row[key])
                for key in ["tags", "aliases", "challenge_cohorts"]
            }
        )
        update_row(connection, "product", values, pid)
        offer = offers[pid]
        values = {
            key: int(offer[key])
            for key in [
                "price_cents",
                "list_price_cents",
                "inventory_count",
                "seller_count",
            ]
        }
        values.update(
            {
                key: float(offer[key]) if offer[key] else None
                for key in [
                    "rating",
                    "return_rate",
                    "quality_score",
                    "popularity_score",
                    "freshness_score",
                    "metadata_completeness",
                ]
            }
        )
        values.update(
            {
                key: int(offer[key]) if offer[key] else None
                for key in ["shipping_days", "warranty_months", "review_count"]
            }
        )
        update_row(connection, "product_offer", values, pid)
    connection.execute(
        "CALL mosaic_search.refresh_product_documents(%s::bigint[])", (ids,)
    )
    return connection.execute(
        "SELECT product_id,embedding_text FROM mosaic_search.product_document WHERE product_id = ANY(%s) ORDER BY product_id",
        (ids,),
    ).fetchall()


def refresh_evidence(connection, ids: list[int]) -> None:
    """Refresh specifications and install sampled reviews while preserving IDs.

    Args:
        connection: Aurora connection participating in the promotion transaction.
        ids: Reviewed product identities whose source evidence must agree.
    """
    updated = connection.execute(
        """UPDATE mosaic.product_evidence e SET
      evidence_title=d.title || ' specifications',
      evidence_text=concat_ws(' ',d.title || '.',d.short_description,'Availability: ' || d.availability::text || '.','Price: ' || d.price_cents || ' cents.','Attributes: ' || d.attributes::text),
      source_date=d.updated_at::date,
      metadata=jsonb_build_object('sku',d.sku,'domain',d.domain,'category_key',d.category_key,'attributes',d.attributes),
      trigram_text=lower(concat_ws(' ',d.title,d.brand_name,d.model_name,d.sku)),
      embedding_text=concat_ws(' ',d.title,d.short_description,d.attributes::text)
      FROM mosaic_search.product_document d
      WHERE e.product_id=d.product_id AND d.product_id=ANY(%s)
        AND e.source_name='Mosaic catalog specification' """,
        (ids,),
    ).rowcount
    if updated != len(ids):
        raise ValueError(
            f"Shop evidence rule: refreshed {updated} specification rows for {len(ids)} products; restore one specification record per product."
        )
    reviews = [
        row
        for row in read_rows(ROOT / "data/sample/reviews_15000.csv.gz")
        if int(row["product_id"]) in ids
    ]
    connection.execute(
        """INSERT INTO mosaic.product_evidence (
            product_id, evidence_type, source_name, source_reference,
            evidence_title, evidence_text, source_date, rating, is_verified,
            metadata, trigram_text, embedding_text
        )
        SELECT r.product_id, 'customer_review'::mosaic.evidence_type,
            'Mosaic synthetic review corpus',
            format('mosaic://evidence/review/%s', r.review_id),
            r.title, r.body, r.review_date, r.rating, r.verified_purchase,
            jsonb_build_object('review_id', r.review_id,
                'helpful_votes', r.helpful_votes, 'sentiment_score', r.sentiment_score),
            lower(concat_ws(' ', r.title, r.body)), concat_ws(' ', r.title, r.body)
        FROM jsonb_to_recordset(%s::jsonb) AS r (
            review_id bigint, product_id bigint, rating numeric, title text,
            body text, verified_purchase boolean, helpful_votes integer,
            review_date date, sentiment_score numeric
        )
        WHERE NOT EXISTS (
            SELECT 1 FROM mosaic.product_evidence e
            WHERE e.source_reference = format('mosaic://evidence/review/%s', r.review_id)
        )""",
        (Jsonb(reviews),),
    )
    for row in reviews:
        connection.execute(
            """UPDATE mosaic.product_evidence SET evidence_title=%s,evidence_text=%s,
                source_name='Mosaic synthetic review corpus',
                trigram_text=lower(concat_ws(' ',%s::text,%s::text)),embedding_text=concat_ws(' ',%s::text,%s::text)
                WHERE product_id=%s AND source_reference=%s""",
            (
                row["title"],
                row["body"],
                row["title"],
                row["body"],
                row["title"],
                row["body"],
                int(row["product_id"]),
                f"mosaic://evidence/review/{row['review_id']}",
            ),
        )


def json_value(value):
    if hasattr(value, "to_numpy"):
        return value.to_numpy().tolist()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--normalized", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    products = read_rows(args.normalized / "products.csv.gz")
    offers = {
        int(r["product_id"]): r for r in read_rows(args.normalized / "offers.csv.gz")
    }
    brands = {r["brand_id"]: r for r in read_rows(args.normalized / "brands.csv.gz")}
    categories = {
        r["category_id"]: r for r in read_rows(args.normalized / "categories.csv.gz")
    }
    ids = [int(r["product_id"]) for r in products]
    expected = {
        r["product_id"]
        for r in json.loads((ROOT / "data/media/asset_labels_200.json").read_text())[
            "products"
        ]
    }
    if set(ids) != expected or len(ids) != len(expected):
        raise ValueError(
            f"Shop promotion scope rule: found {len(ids)} rows, expected the {len(expected)} photographed products; normalize exactly that cohort."
        )
    with connect() as connection:
        backup = {
            table: connection.execute(
                sql.SQL("SELECT * FROM {} WHERE product_id=ANY(%s)").format(
                    sql.Identifier(*table.split("."))
                ),
                (ids,),
            ).fetchall()
            for table in [
                "mosaic.product",
                "mosaic.product_offer",
                "mosaic_search.product_document",
                "mosaic.product_evidence",
            ]
        }
        args.backup.parent.mkdir(parents=True, exist_ok=True)
        with args.backup.open("x") as handle:
            json.dump(backup, handle, default=json_value)
        texts = install_catalog(connection, products, offers, brands, categories)
        connection.rollback()
    print(
        f"Validated production projection for {len(texts)} products; preview transaction rolled back.",
        flush=True,
    )
    if not args.apply:
        return
    embedder = get_embedding_provider()
    previous = {
        row["product_id"]: row for row in backup["mosaic_search.product_document"]
    }
    vectors = [None] * len(texts)
    pending = []
    for index, row in enumerate(texts):
        old = previous[row["product_id"]]
        if (
            old["embedding"] is not None
            and old["embedding_model_key"] == embedder.model_id
            and old["embedding_text"] == row["embedding_text"]
        ):
            vectors[index] = vector_float32(old["embedding"])
        else:
            pending.append(index)
    for offset in range(0, len(pending), 32):
        batch = pending[offset : offset + 32]
        generated = embedder.embed_documents(
            [texts[index]["embedding_text"] for index in batch]
        )
        for index, vector in zip(batch, generated, strict=True):
            vectors[index] = vector
        print(
            f"Embedded {min(offset + len(batch), len(pending))}/{len(pending)} changed products with {embedder.model_id}.",
            flush=True,
        )
    print(f"Reused {len(texts) - len(pending)} matching stored vectors.", flush=True)
    vector_array = np.asarray(vectors, dtype=np.float32)
    if (
        vector_array.shape != (len(texts), embedder.dimensions)
        or not np.isfinite(vector_array).all()
    ):
        raise ValueError(
            f"Shop vector rule: invalid shape or values {vector_array.shape}; regenerate real document embeddings."
        )
    with connect() as connection:
        current = install_catalog(connection, products, offers, brands, categories)
        if current != texts:
            raise ValueError(
                "Shop projection agreement rule: embedding text changed during promotion; restart from the reviewed source."
            )
        for row, vector in zip(texts, vector_array, strict=True):
            connection.execute(
                "UPDATE mosaic_search.product_document SET embedding=%s,embedding_model_key=%s WHERE product_id=%s",
                (vector, embedder.model_id, row["product_id"]),
            )
        refresh_evidence(connection, ids)
    print(
        f"Committed {len(ids)} catalog rows with matching vectors and refreshed source evidence.",
        flush=True,
    )


if __name__ == "__main__":
    main()
