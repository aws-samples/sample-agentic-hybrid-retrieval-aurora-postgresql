#!/usr/bin/env python3
"""Check the photographed Shop selection for duplicate copy and image bindings."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_catalog import DEFAULT_MANIFEST, catalog_paths


def copy_violations(rows: list[dict]) -> list[str]:
    """Name repeated summaries and leaked authoring instructions with product IDs."""
    seen: dict[str, int] = {}
    seen_details: dict[str, int] = {}
    failures = []
    for row in rows:
        pid = int(row["product_id"])
        summary = row["short_description"].strip()
        key = re.sub(r"\W+", " ", summary.casefold()).strip()
        if key in seen:
            failures.append(
                f"Shop distinct-copy rule: {pid} repeats {seen[key]}: {summary!r}; write its own factual buying differences."
            )
        seen[key] = pid
        detail = row.get("long_description", "").strip()
        if detail:
            detail_key = re.sub(r"\W+", " ", detail.casefold()).strip()
            if detail_key in seen_details:
                failures.append(
                    f"Shop distinct-detail-copy rule: {pid} repeats {seen_details[detail_key]}; describe this product's own use, specifications and trade-offs."
                )
            seen_details[detail_key] = pid
        if not 20 <= len(summary) <= 120:
            failures.append(
                f"Shop concise-copy rule: {pid} has {len(summary)} characters; write 20–120 characters using concrete product facts."
            )
        if re.search(
            r"locked spec|locked field|schema|editorial note", summary, re.IGNORECASE
        ):
            failures.append(
                f"Shop shopper-copy rule: {pid} contains {summary!r}; remove authoring instructions."
            )
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    media = json.loads((ROOT / "data/media/asset_labels_200.json").read_text())[
        "products"
    ]
    ids = {r["product_id"] for r in media}
    rows = []
    for path in catalog_paths(DEFAULT_MANIFEST):
        with gzip.open(path, "rt", newline="") as handle:
            rows.extend(
                r for r in csv.DictReader(handle) if int(r["product_id"]) in ids
            )
    failures = copy_violations(rows)
    if {int(r["product_id"]) for r in rows} != ids or len(rows) != len(ids):
        failures.append(
            "Shop identity rule: photographed products are missing or repeated in the source; restore one canonical row per photographed ID."
        )
    hashes = {}
    for item in media:
        path = ROOT / "ui/public" / item["catalog_runtime_path"].lstrip("/")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item["catalog_sha256"]:
            failures.append(
                f"Shop image revision rule: {item['product_id']} has hash {digest}; rebuild the reviewed media manifest."
            )
        if digest in hashes:
            failures.append(
                f"Shop distinct-image rule: {item['product_id']} shares the exact image bytes of {hashes[digest]}; install a distinct product photograph."
            )
        hashes[digest] = item["product_id"]
    if args.live:
        from service.db import connect

        with connect() as connection:
            live = {
                r["product_id"]: r
                for r in connection.execute(
                    "SELECT product_id,short_description FROM mosaic_search.product_document WHERE product_id = ANY(%s)",
                    (sorted(ids),),
                ).fetchall()
            }
        for row in rows:
            pid = int(row["product_id"])
            if live.get(pid, {}).get("short_description") != row["short_description"]:
                failures.append(
                    f"Shop source agreement rule: {pid} has different live copy; promote the canonical record with its matching vector and evidence."
                )
    if failures:
        print("\n".join(failures))
        raise SystemExit(1)
    print(
        f"Shop quality: {len(rows)} products, distinct concise descriptions, {len(hashes)} distinct image files"
        + (", live source agreement" if args.live else "")
        + "."
    )
    print(
        "Image hashes prove distinct files, not visual or specification accuracy; photography still needs review."
    )


if __name__ == "__main__":
    main()
