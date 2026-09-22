#!/usr/bin/env python3
"""Verify teaching quotes and identities against current, unmodified Aurora records."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_real_catalog import canonical, sha256


def verify_product(review: dict, row: dict) -> None:
    """Reject stale identities, changed inputs, or unsupported source excerpts.

    Args:
        review: One product's separate teaching review.
        row: Current original catalog record and saved embedding input hashes.
    """
    for key in (
        "product_id",
        "parent_asin",
        "source_record_sha256",
        "embedding_text_sha256",
    ):
        if review[key] != row[key]:
            raise ValueError(
                f"Reviewed identity rule: {key} is {row[key]!r}, expected {review[key]!r}; re-review the current record before teaching it."
            )
    if sha256(canonical(row["original"])) != row["source_record_sha256"]:
        raise ValueError(
            "Source integrity rule: original record hash changed; inspect the import instead of approving saved quotes."
        )
    if (
        sha256(row["embedding_text"]) != row["embedding_text_sha256"]
        or row["embedded_input_sha256"] != row["embedding_text_sha256"]
    ):
        raise ValueError(
            "Embedding reuse rule: current text and embedded input differ; regenerate only changed inputs before claiming vector reuse."
        )
    if not review["facts"]:
        raise ValueError(
            f"Source quote rule: {review['parent_asin']} has no facts; review at least one explicit source field."
        )
    for fact in review["facts"]:
        value = row["original"]
        try:
            for key in fact["path"]:
                value = value[key]
        except (KeyError, IndexError, TypeError):
            value = None
        if not fact["quote"] or value != fact["quote"]:
            raise ValueError(
                f"Source quote rule: {review['parent_asin']} path {fact['path']} differs from the review; read the source and correct or remove that claim."
            )
    label = review.get("source_label")
    if label and (
        label["product_id"] != review["parent_asin"]
        or label["locale"] != "us"
        or label["label"] not in {"E", "S", "C", "I"}
    ):
        raise ValueError(
            "Reference label rule: product, locale or label differs; retain the exact source judgment separately from the workshop requirement."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    import psycopg
    from psycopg.rows import dict_row

    from scripts.stage_real_catalog import validate_dsn

    manifest = json.loads(
        (ROOT / "data/evals/reviewed_product_examples.json").read_text()
    )
    reviews = [p for c in manifest["cases"] for p in c["products"]]
    if not reviews:
        raise ValueError(
            "Reviewed set rule: zero products; select and review real records before running this check."
        )
    dsn = os.environ.get("DATABASE_URL", "")
    validate_dsn(dsn)
    with psycopg.connect(dsn, connect_timeout=15, row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        rows = conn.execute(
            """SELECT d.product_id,p.parent_asin,p.source_record_sha256,p.embedding_text_sha256,p.embedded_input_sha256,p.embedding_text,p.original FROM mosaic_catalog_stage.product p JOIN mosaic_live_search.product_document d USING(dataset_id,parent_asin) WHERE p.dataset_id=%s AND d.product_id=ANY(%s)""",
            (manifest["dataset_id"], [p["product_id"] for p in reviews]),
        ).fetchall()
    found = {r["product_id"]: r for r in rows}
    for review in reviews:
        if review["product_id"] not in found:
            raise ValueError(
                f"Reviewed set rule: missing product {review['product_id']}; use records from the selected catalog."
            )
        verify_product(review, found[review["product_id"]])
    result = {
        "dataset_id": manifest["dataset_id"],
        "cases_verified": len(manifest["cases"]),
        "products_verified": len(reviews),
        "quotes_verified": sum(len(p["facts"]) for p in reviews),
        "manifest_sha256": sha256(canonical(manifest)),
        "embedding_inputs_unchanged": True,
        "scope": "Source facts and input identity only; does not grade search quality.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
