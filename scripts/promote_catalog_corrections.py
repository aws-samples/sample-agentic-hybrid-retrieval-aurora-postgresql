#!/usr/bin/env python3
"""Atomically install reviewed catalog corrections and matching Bedrock vectors.

The staging directory holds an old/new source ledger, the production projection's
new text, and resumable vector chunks. No model calls occur inside the transaction.
Without --apply this validates the bundle and current Aurora rows without writes.

This is an operator repair, not a participant lab step. Large updates maintain
every vector index, including unchanged vectors on rows with indexed timestamp
changes. Plan bulk index maintenance separately, preserve exact index definitions,
and verify all indexes are ready again before measuring retrieval.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from service.db import connect


def content_hash(row: dict) -> str:
    return hashlib.sha256(
        (row["title"] + row["long_description"] + row["attributes_json"]).encode()
    ).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    with gzip.open(path, "rt") as stream:
        return [json.loads(line) for line in stream]


def validate_vectors(
    ids: np.ndarray,
    hashes: np.ndarray,
    vectors: np.ndarray,
    expected: dict,
    dimensions: int,
) -> None:
    """Reject missing identity, text drift, invalid shape and unusable vectors."""
    if vectors.shape != (len(ids), dimensions) or len(hashes) != len(ids):
        raise ValueError(
            f"Catalog vector shape rule: found {vectors.shape} with {len(hashes)} hashes; expected {(len(ids), dimensions)} and {len(ids)} hashes. Regenerate the affected chunk."
        )
    if not np.isfinite(vectors).all() or np.any(np.linalg.norm(vectors, axis=1) == 0):
        raise ValueError(
            "Catalog vector value rule: non-finite or zero vector; regenerate the affected chunk."
        )
    for pid, digest in zip(ids, hashes):
        if (
            int(pid) not in expected
            or bytes(digest).decode() != expected[int(pid)]["text_sha256"]
        ):
            raise ValueError(
                f"Catalog vector text rule: product {pid} has different input text; regenerate its vector."
            )


def synchronize_reviews(conn, reviews: list[dict], retired: list[dict]) -> dict:
    """Install current excerpts without reassigning or deleting historical IDs."""
    # No other writer may create a duplicate source reference during this sync.
    conn.execute("LOCK TABLE mosaic.product_evidence IN SHARE ROW EXCLUSIVE MODE")
    for row in retired:
        count = conn.execute(
            """UPDATE mosaic.product_evidence SET is_current=false,
            metadata=metadata || '{"retired_reason":"Replaced in the reviewed synthetic source corpus"}'::jsonb
            WHERE evidence_id=%s AND product_id=%s AND source_reference=%s
              AND evidence_title IS NOT DISTINCT FROM %s AND evidence_text=%s""",
            (
                row["evidence_id"],
                row["product_id"],
                row["source_reference"],
                row["evidence_title"],
                row["evidence_text"],
            ),
        ).rowcount
        if count != 1:
            raise ValueError(
                f"Catalog retired review rule: {row['evidence_id']} changed; rollback and refresh the review audit."
            )
    conn.execute(
        """CREATE TEMP TABLE current_review ON COMMIT DROP AS
        SELECT * FROM jsonb_to_recordset(%s::jsonb) AS r(
            review_id bigint, product_id bigint, rating numeric, title text,
            body text, verified_purchase boolean, helpful_votes integer,
            review_date date, sentiment_score numeric)""",
        (Jsonb(reviews),),
    )
    conn.execute("""UPDATE mosaic.product_evidence e SET
        evidence_type='customer_review', source_name='Mosaic synthetic review corpus',
        evidence_title=r.title,evidence_text=r.body,source_date=r.review_date,
        rating=r.rating,is_verified=r.verified_purchase,is_current=true,
        metadata=jsonb_build_object('review_id',r.review_id,'helpful_votes',r.helpful_votes,'sentiment_score',r.sentiment_score),
        trigram_text=lower(concat_ws(' ',r.title,r.body)),embedding_text=concat_ws(' ',r.title,r.body),
        embedding=CASE WHEN e.embedding_text=concat_ws(' ',r.title,r.body) THEN e.embedding ELSE NULL END
        FROM current_review r
        WHERE e.source_reference=format('mosaic://evidence/review/%s',r.review_id) AND e.product_id=r.product_id""")
    inserted = conn.execute("""INSERT INTO mosaic.product_evidence (
        product_id,evidence_type,source_name,source_reference,evidence_title,evidence_text,
        source_date,rating,is_verified,metadata,trigram_text,embedding_text)
        SELECT r.product_id,'customer_review','Mosaic synthetic review corpus',
            format('mosaic://evidence/review/%s',r.review_id),r.title,r.body,r.review_date,r.rating,r.verified_purchase,
            jsonb_build_object('review_id',r.review_id,'helpful_votes',r.helpful_votes,'sentiment_score',r.sentiment_score),
            lower(concat_ws(' ',r.title,r.body)),concat_ws(' ',r.title,r.body)
        FROM current_review r WHERE NOT EXISTS(SELECT 1 FROM mosaic.product_evidence e
            WHERE e.source_reference=format('mosaic://evidence/review/%s',r.review_id))""").rowcount
    current = conn.execute("""SELECT count(*) AS n FROM mosaic.product_evidence
        WHERE is_current AND source_reference LIKE 'mosaic://evidence/review/%'""").fetchone()[
        "n"
    ]
    if current != len(reviews):
        raise ValueError(
            f"Catalog current review rule: {current}/{len(reviews)}; rollback and inspect duplicate or stale source records."
        )
    return {
        "current": current,
        "inserted": inserted,
        "retired_preserving_ids": len(retired),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", required=True, type=Path)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    stage = args.staged
    edits = read_jsonl(stage / "semantic-edits.jsonl.gz")
    inputs = {
        x["product_id"]: x for x in read_jsonl(stage / "embedding-inputs.jsonl.gz")
    }
    offers = json.loads((stage / "offer-edits.json").read_text())
    with gzip.open(stage / "reviews_15000.csv.gz", "rt") as stream:
        reviews = list(csv.DictReader(stream))
    retired = json.loads((stage / "review-sync.json").read_text())["orphan"]
    contract = json.loads((ROOT / "db/config/embedding-cache.json").read_text())
    expected_count = json.loads((stage / "live-preview-summary.json").read_text())[
        "semantic_edits"
    ]
    ids = [x["product_id"] for x in edits]
    if (
        not ids
        or len(set(ids)) != len(ids)
        or set(ids) != set(inputs)
        or len(ids) != expected_count
    ):
        raise ValueError(
            "Catalog correction identity rule: staged identities disagree; rebuild the reviewed bundle."
        )
    vectors = {}
    for path in sorted((stage / "vectors").glob("changed-*.npz")):
        with np.load(path, allow_pickle=False) as data:
            if str(data["embedding_model_id"]) != contract["embedding_model_id"]:
                raise ValueError(
                    f"Catalog vector model rule: {path.name} differs; use the pinned model."
                )
            validate_vectors(
                data["product_ids"],
                data["text_sha256"],
                data["embeddings"],
                inputs,
                contract["dimensions"],
            )
            for pid, vector in zip(data["product_ids"], data["embeddings"]):
                if int(pid) in vectors:
                    raise ValueError(
                        f"Catalog duplicate vector rule: {pid}; remove overlapping chunks."
                    )
                vectors[int(pid)] = vector.copy()
    if set(vectors) != set(ids):
        raise ValueError(
            f"Catalog vector completeness rule: {len(vectors)} of {len(ids)} prepared; finish generation before promotion."
        )
    for edit in edits:
        for key in [
            "product_id",
            "sku",
            "product_uid",
            "brand",
            "model",
            "price_usd",
            "availability",
            "inventory_count",
        ]:
            if edit["old"][key] != edit["new"][key]:
                raise ValueError(
                    f"Catalog identity/offer rule: {edit['product_id']}/{key} changed; preserve existing identity and commerce values."
                )
    with connect() as conn:
        conn.execute("SET LOCAL statement_timeout='30min'")
        conn.execute("SET LOCAL lock_timeout='10s'")
        conn.execute(
            "CREATE TEMP TABLE correction (product_id bigint PRIMARY KEY, old_hash text, old_short text, old_attrs jsonb, old_text_hash text, old_vector_hash text, title text, short_description text, long_description text, attributes jsonb, tags text[], aliases text[], domain text, category_path text, content_hash text, new_text text, embedding vector(1024)) ON COMMIT DROP"
        )
        with conn.cursor().copy("COPY correction FROM STDIN (FORMAT BINARY)") as copy:
            copy.set_types(
                [
                    "int8",
                    "text",
                    "text",
                    "jsonb",
                    "text",
                    "text",
                    "text",
                    "text",
                    "text",
                    "jsonb",
                    "text[]",
                    "text[]",
                    "text",
                    "text",
                    "text",
                    "text",
                    "vector",
                ]
            )
            for x in edits:
                pid = x["product_id"]
                old = x["old"]
                new = x["new"]
                text = inputs[pid]
                copy.write_row(
                    (
                        pid,
                        content_hash(old),
                        old["short_description"],
                        Jsonb(json.loads(old["attributes_json"])),
                        text["old_text_sha256"],
                        text["old_vector_sha256"],
                        new["title"],
                        new["short_description"],
                        new["long_description"],
                        Jsonb(json.loads(new["attributes_json"])),
                        json.loads(new["tags_json"]),
                        json.loads(new["aliases_json"]),
                        new["domain"],
                        new["category"] + " > " + new["subcategory"],
                        content_hash(new),
                        text["text"],
                        vectors[pid],
                    )
                )
        conn.execute(
            "CREATE TEMP TABLE offer_correction(product_id bigint PRIMARY KEY, old_value int, new_value int) ON COMMIT DROP"
        )
        with conn.cursor().copy("COPY offer_correction FROM STDIN") as copy:
            for x in offers:
                copy.write_row((x["product_id"], x["old"], x["new"]))
        conn.execute("ANALYZE correction")
        conn.execute("ANALYZE offer_correction")
        mismatch = conn.execute("""SELECT x.product_id FROM correction x
            LEFT JOIN mosaic.product p USING(product_id)
            LEFT JOIN mosaic_search.product_document d USING(product_id)
            LEFT JOIN mosaic.category c ON c.domain::text=x.domain AND c.category_path=x.category_path
            WHERE p.content_hash IS DISTINCT FROM x.old_hash OR p.short_description IS DISTINCT FROM x.old_short
              OR p.attributes IS DISTINCT FROM x.old_attrs OR c.category_id IS NULL
              OR encode(digest(d.embedding_text,'sha256'),'hex') IS DISTINCT FROM x.old_text_hash
              OR encode(digest(vector_send(d.embedding),'sha256'),'hex') IS DISTINCT FROM x.old_vector_hash LIMIT 5""").fetchall()
        offer_bad = conn.execute(
            "SELECT x.product_id FROM offer_correction x LEFT JOIN mosaic.product_offer o USING(product_id) WHERE o.warranty_months IS DISTINCT FROM x.old_value LIMIT 5"
        ).fetchall()
        review_bad = conn.execute(
            """SELECT e.source_reference FROM mosaic.product_evidence e
            JOIN jsonb_to_recordset(%s::jsonb) AS r(review_id bigint, product_id bigint, title text, body text)
            ON e.source_reference=format('mosaic://evidence/review/%%s',r.review_id)
            WHERE e.product_id IS DISTINCT FROM r.product_id
               OR e.evidence_title IS DISTINCT FROM r.title
               OR e.evidence_text IS DISTINCT FROM r.body LIMIT 5""",
            (Jsonb(reviews),),
        ).fetchall()
        if len(reviews) != 15000 or len({r["review_id"] for r in reviews}) != 15000:
            raise ValueError(
                "Catalog review count rule: expected 15000 unique reviews; rebuild the reviewed source bundle."
            )
        if mismatch or offer_bad or review_bad:
            raise ValueError(
                f"Catalog source drift rule: {mismatch or offer_bad or review_bad}; review Aurora changes and rebuild the preview."
            )
        print(
            f"Validated {len(ids)} text/vector pairs and {len(offers)} warranty changes.",
            flush=True,
        )
        if not args.apply:
            conn.rollback()
            return
        args.backup.mkdir(parents=True, exist_ok=False)
        # The backup must complete before any durable data is changed.
        for table, predicate in [
            ("product", "product_id IN (SELECT product_id FROM correction)"),
            (
                "product_evidence",
                "product_id IN (SELECT product_id FROM correction) OR source_reference LIKE 'mosaic://evidence/review/%'",
            ),
            (
                "product_offer",
                "product_id IN (SELECT product_id FROM offer_correction)",
            ),
        ]:
            with (
                gzip.open(
                    args.backup / f"{table}.jsonl.gz", "wt", compresslevel=3
                ) as stream,
                conn.cursor(name="backup_" + table) as cursor,
            ):
                cursor.execute(
                    f"SELECT to_jsonb(t) AS value FROM mosaic.{table} t WHERE {predicate}"
                )
                while batch := cursor.fetchmany(1000):
                    for row in batch:
                        stream.write(json.dumps(row["value"]) + "\n")
        with conn.cursor(name="backup_vectors", binary=True) as cursor:
            cursor.execute(
                "SELECT d.product_id,d.embedding,d.embedding_model_key,d.embedding_updated_at FROM mosaic_search.product_document d JOIN correction x USING(product_id) ORDER BY product_id"
            )
            i = 0
            while batch := cursor.fetchmany(1000):
                np.savez_compressed(
                    args.backup / f"vectors-{i:03}.npz",
                    product_ids=np.array([r["product_id"] for r in batch]),
                    embeddings=np.asarray(
                        [r["embedding"].to_numpy() for r in batch], dtype=np.float32
                    ),
                    models=np.array([r["embedding_model_key"] for r in batch]),
                    updated_at=np.array(
                        [str(r["embedding_updated_at"]) for r in batch]
                    ),
                )
                i += 1
        (args.backup / "manifest.json").write_text(
            json.dumps(
                {
                    "semantic_rows": len(ids),
                    "offer_rows": len(offers),
                    "vector_chunks": i,
                    "model": contract["embedding_model_id"],
                },
                indent=2,
            )
        )
        print("Recovery backup complete. Installing in one transaction.", flush=True)
        changed = conn.execute("""UPDATE mosaic.product p SET title=x.title,short_description=x.short_description,long_description=x.long_description,
            attributes=x.attributes,tags=x.tags,aliases=x.aliases,category_id=c.category_id,content_hash=x.content_hash
            FROM correction x JOIN mosaic.category c ON c.domain::text=x.domain AND c.category_path=x.category_path
            WHERE p.product_id=x.product_id AND p.content_hash=x.old_hash AND p.short_description=x.old_short AND p.attributes=x.old_attrs""").rowcount
        if changed != len(ids):
            raise ValueError(
                f"Catalog concurrent update rule: changed {changed}/{len(ids)}; rollback and refresh the preview."
            )
        changed_offers = conn.execute(
            "UPDATE mosaic.product_offer o SET warranty_months=x.new_value FROM offer_correction x WHERE o.product_id=x.product_id AND o.warranty_months=x.old_value"
        ).rowcount
        if changed_offers != len(offers):
            raise ValueError(
                "Catalog concurrent offer rule: warranty values changed during promotion; rollback and refresh preview."
            )
        # Warranty is not part of search or embedding text; only its source clock changes.
        print("Refreshing source clocks and production search text.", flush=True)
        conn.execute("""UPDATE mosaic_search.product_document d
            SET source_updated_at=greatest(d.source_updated_at,o.updated_at),updated_at=clock_timestamp()
            FROM mosaic.product_offer o JOIN offer_correction x USING(product_id)
            WHERE d.product_id=o.product_id AND NOT EXISTS(SELECT 1 FROM correction c WHERE c.product_id=d.product_id)""")
        conn.execute(
            "CALL mosaic_search.refresh_product_documents(%s::bigint[])", (ids,)
        )
        text_bad = conn.execute(
            "SELECT d.product_id FROM mosaic_search.product_document d JOIN correction x USING(product_id) WHERE d.embedding_text IS DISTINCT FROM x.new_text LIMIT 5"
        ).fetchall()
        if text_bad:
            raise ValueError(
                f"Catalog production projection rule: {text_bad}; rollback and regenerate vectors from production text."
            )
        installed = conn.execute(
            "UPDATE mosaic_search.product_document d SET embedding=x.embedding,embedding_model_key=%s,embedding_updated_at=clock_timestamp() FROM correction x WHERE d.product_id=x.product_id",
            (contract["embedding_model_id"],),
        ).rowcount
        if installed != len(ids):
            raise ValueError(
                "Catalog vector install rule: incomplete update; rollback and restore matching text/vector pairs."
            )
        print("Text/vector pairs installed. Refreshing supporting records.", flush=True)
        evidence = conn.execute("""UPDATE mosaic.product_evidence e SET
            evidence_title=d.title||' specifications',
            evidence_text=concat_ws(' ',d.title||'.',d.short_description,'Availability: '||d.availability::text||'.','Price: '||d.price_cents||' cents.','Attributes: '||d.attributes::text),
            source_date=d.updated_at::date,
            metadata=jsonb_build_object('sku',d.sku,'domain',d.domain,'category_key',d.category_key,'attributes',d.attributes),
            trigram_text=lower(concat_ws(' ',d.title,d.brand_name,d.model_name,d.sku)),
            embedding_text=concat_ws(' ',d.title,d.short_description,d.attributes::text),embedding=NULL
            FROM mosaic_search.product_document d JOIN correction x USING(product_id)
            WHERE e.product_id=d.product_id AND e.source_name='Mosaic catalog specification'""").rowcount
        if evidence != len(ids):
            raise ValueError(
                f"Catalog evidence count rule: {evidence}/{len(ids)}; rollback and restore missing specification records."
            )
        review_sync = synchronize_reviews(conn, reviews, retired)
        totals = conn.execute(
            "SELECT count(*) AS rows,count(*) FILTER(WHERE embedding IS NULL OR vector_norm(embedding)=0 OR embedding_model_key IS DISTINCT FROM %s) AS invalid FROM mosaic_search.product_document",
            (contract["embedding_model_id"],),
        ).fetchone()
        if totals["rows"] != contract["vector_count"] or totals["invalid"]:
            raise ValueError(
                f"Catalog embedding completeness rule: {totals}; rollback and inspect the incomplete rows."
            )
        conn.commit()
        (stage / "promotion-result.json").write_text(
            json.dumps(
                {
                    "committed": True,
                    "semantic_rows": len(ids),
                    "offer_rows": len(offers),
                    "evidence_rows": evidence,
                    "review_sync": review_sync,
                    "embedding_totals": totals,
                    "backup": str(args.backup),
                },
                indent=2,
            )
        )
        print("COMMITTED", json.dumps(totals), flush=True)


if __name__ == "__main__":
    main()
