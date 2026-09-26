#!/usr/bin/env python3
"""Verify sampled review source bytes and join them to preserved Aurora products."""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_catalog_reviews import (
    expand_review,
    fetch_range,
    review_parent,
    source_identity,
)
from scripts.stage_real_catalog import require_aurora_writer, validate_dsn


def verified_samples(path: Path, refetch: bool = True) -> tuple[dict, list[dict]]:
    """Re-fetch each cited source line before trusting its product attribution.

    With `refetch=False` the per-line fetch is skipped for a sample whose scan
    covered the whole source and recorded every range hash; each row is still
    rebuilt from its stored bytes and checked against its hashes and parent.
    """
    state = json.loads(path.read_text())
    category = path.name.removesuffix("-reviews.json")
    expected = source_identity(category)
    scanned = dict(state.get("source") or {})
    # A file scanned before its digest was pinned carries sha256 null; the
    # observed whole-file digest below is what ties it to the pin.
    if {**scanned, "sha256": expected["sha256"]} != expected:
        raise ValueError(
            f"Review source rule: {path.name} names another release; use the pinned review sampler."
        )
    rows = state["reviews"]
    if not rows:
        raise ValueError(
            f"Review coverage rule: {path.name} contains no reviews; scan more source bytes before importing."
        )
    if not refetch and not (
        state.get("complete_source_scan")
        and state.get("ranges")
        and expected["sha256"] is not None
        and state.get("source_sha256_observed") == expected["sha256"]
    ):
        raise ValueError(
            "Review verification rule: skipping the source re-fetch needs one complete scan whose whole-file digest matches the pinned source; scan the whole file first."
        )
    parents = set(state["parent_asins"])

    def verify(row):
        # Rows stay as stored (full or compact); the rebuilt record is discarded
        # here and rebuilt again per batch at import time.
        if expand_review(row)["original"]["parent_asin"] not in parents:
            raise ValueError(
                "Review selection rule: unselected parent in sample; rebuild it with the intended parent IDs."
            )
        if not refetch:
            return row
        location = row["source_location"]
        raw = fetch_range(
            expected, location["offset"], location["offset"] + location["length"] - 1
        )
        if raw != row["raw_line"].encode("utf-8"):
            raise ValueError(
                f"Review source-byte rule: byte {location['offset']} does not match the pinned file; restore the original line."
            )
        return row

    with ThreadPoolExecutor(max_workers=4) as pool:
        checked = list(pool.map(verify, rows))
    return state, checked


def create_tables(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mosaic_catalog_stage.review_evidence (
            dataset_id text NOT NULL,
            evidence_id text NOT NULL,
            parent_asin text NOT NULL,
            variant_asin text NOT NULL,
            original jsonb NOT NULL,
            source_record_sha256 text NOT NULL,
            source_reference text NOT NULL,
            source_location jsonb NOT NULL,
            source_bytes_verified_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (dataset_id, evidence_id),
            FOREIGN KEY (dataset_id, parent_asin)
                REFERENCES mosaic_catalog_stage.product(dataset_id, parent_asin),
            CHECK (original->>'parent_asin' = parent_asin),
            CHECK (original->>'asin' = variant_asin)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS staged_review_product_idx ON mosaic_catalog_stage.review_evidence(dataset_id, parent_asin)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mosaic_catalog_stage.review_sample (
            dataset_id text NOT NULL REFERENCES mosaic_catalog_stage.dataset,
            category text NOT NULL,
            source jsonb NOT NULL,
            sample_manifest jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (dataset_id, category)
        )
    """)
    # Membership lives in rows, not inside one manifest value: a review names
    # the sample that imported it, and each selected parent has one row with
    # the count kept for it, so a six-figure sample never becomes one jsonb.
    conn.execute(
        "ALTER TABLE mosaic_catalog_stage.review_evidence ADD COLUMN IF NOT EXISTS sample_category text"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mosaic_catalog_stage.review_sample_parent (
            dataset_id text NOT NULL,
            category text NOT NULL,
            parent_asin text NOT NULL,
            reviews_selected integer NOT NULL CHECK (reviews_selected >= 0),
            PRIMARY KEY (dataset_id, category, parent_asin)
        )
    """)


def import_samples(
    conn, dataset: str, state: dict, rows: list[dict], category: str
) -> dict:
    """Use the original parent relation; never merge by title or model name."""
    parents = {review_parent(row) for row in rows}
    known = {
        row[0]
        for row in conn.execute(
            "SELECT parent_asin FROM mosaic_catalog_stage.product WHERE dataset_id=%s AND parent_asin=ANY(%s)",
            (dataset, sorted(parents)),
        )
    }
    if parents != known:
        raise ValueError(
            f"Review parent rule: missing selected products {sorted(parents - known)}; import their exact parent records before joining reviews."
        )
    create_tables(conn)
    with conn.cursor() as cursor:
        for start in range(0, len(rows), 2000):
            cursor.executemany(
                """
                INSERT INTO mosaic_catalog_stage.review_evidence
                (dataset_id,evidence_id,parent_asin,variant_asin,original,source_record_sha256,source_reference,source_location,sample_category)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (dataset_id,evidence_id) DO UPDATE SET sample_category=EXCLUDED.sample_category
            """,
                [
                    (
                        dataset,
                        "review-" + row["source_record_sha256"],
                        row["original"]["parent_asin"],
                        row["original"]["asin"],
                        Jsonb(row["original"]),
                        row["source_record_sha256"],
                        state["source"]["url"],
                        Jsonb(row["source_location"]),
                        category,
                    )
                    for row in map(expand_review, rows[start : start + 2000])
                ],
            )
        coverage = sorted(state["coverage"].items())
        for start in range(0, len(coverage), 5000):
            cursor.executemany(
                """
                INSERT INTO mosaic_catalog_stage.review_sample_parent
                (dataset_id,category,parent_asin,reviews_selected)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (dataset_id,category,parent_asin)
                DO UPDATE SET reviews_selected=EXCLUDED.reviews_selected
            """,
                [
                    (dataset, category, parent, count)
                    for parent, count in coverage[start : start + 5000]
                ],
            )
    manifest = {
        key: value
        for key, value in state.items()
        if key not in ("reviews", "coverage", "parent_asins")
    }
    manifest["evidence_count"] = len(rows)
    manifest["parents_selected"] = len(state["coverage"])
    conn.execute(
        """
        INSERT INTO mosaic_catalog_stage.review_sample (dataset_id,category,source,sample_manifest)
        VALUES (%s,%s,%s,%s) ON CONFLICT(dataset_id,category) DO UPDATE
        SET source=EXCLUDED.source,sample_manifest=EXCLUDED.sample_manifest,updated_at=now()
    """,
        (dataset, category, Jsonb(state["source"]), Jsonb(manifest)),
    )
    conn.commit()
    return {
        "category": category,
        "reviews_verified": len(rows),
        "products_with_reviews": len(parents),
        "variants": len({json.loads(row["raw_line"])["asin"] for row in rows}),
        "coverage": state["coverage"],
        "scanned_bytes": state["next_byte"],
        "complete_source_scan": state["complete_source_scan"],
        "live_catalog_promoted": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--samples", type=Path, nargs="+", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--skip-refetch",
        action="store_true",
        help="Trust a complete scan's range hashes instead of re-fetching every cited line",
    )
    args = parser.parse_args()
    dsn = os.environ.get("DATABASE_URL", "")
    validate_dsn(dsn)
    reports = []
    for path in args.samples:
        state, rows = verified_samples(path, refetch=not args.skip_refetch)
        with psycopg.connect(
            dsn, connect_timeout=10, application_name="mosaic-real-evidence-stage"
        ) as conn:
            require_aurora_writer(conn, args.dataset_id)
            report = import_samples(
                conn,
                args.dataset_id,
                state,
                rows,
                path.name.removesuffix("-reviews.json"),
            )
            reports.append(report)
            print(json.dumps(report), flush=True)
    args.report.write_text(json.dumps(reports, indent=2) + "\n")


if __name__ == "__main__":
    main()
