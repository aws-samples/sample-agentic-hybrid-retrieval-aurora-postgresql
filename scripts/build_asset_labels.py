#!/usr/bin/env python3
"""Assign stable, descriptive asset keys to the 120-product premium cohort.

The upstream queue names 114 of the 120 products `premium-<product_id>`, which
says nothing about what the photograph should show. That makes the generation
backlog hard to work through and the runtime folder impossible to skim.

This derives a readable slug from each product's merchandising identity instead,
and reports exactly which images still need to be produced.

Naming scheme
-------------
    <domain-prefix>-<subcategory-slug>-<discriminator>-<role>.<ext>

    ce-over-ear-headphones-auraluxe-h9-catalog-3x2.webp
    rf-carbon-racing-shoes-01-catalog-3x2.webp
    ho-standing-desks-01-detail-1x1.webp

`role` is `catalog-3x2` (grid/card) or `detail-1x1` (product page hero). The
domain prefix keeps the three workshop domains sorted together on disk, and the
subcategory segment means a directory listing reads as a shot list.

Usage
-----
    uv run python scripts/build_asset_labels.py --cohort <path/to/premium_cohort_120.json>
    uv run python scripts/build_asset_labels.py --check   # exit 1 if the plan drifts
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO / "data" / "media" / "asset_labels_120.json"
RUNTIME_DIR = REPO / "ui" / "public" / "assets" / "images" / "mosaic"
# Every `import_batch_*.csv` in data/media is a provenance record for one
# generation batch. Globbing rather than naming one file means a new batch is
# picked up without editing this script; a hardcoded path silently dropped the
# provenance of every batch after the first.
IMPORT_MANIFEST_GLOB = "import_batch_*.csv"
IMPORT_MANIFEST_DIR = REPO / "data" / "media"

DOMAIN_PREFIX = {
    "consumer_electronics": "ce",
    "running_fitness": "rf",
    "home_office": "ho",
}

# Flagships keep the merchandising name as their discriminator; it is the name
# the UI shows and the workshop script says out loud.
FLAGSHIP_SLUGS = {
    1: "auraluxe-h9",
    17001: "echobud-s2",
    116001: "pulse-one",
    234001: "stride-pro",
    370001: "forma-ergonomic",
    420001: "atelier-32",
}


def slugify(value: str) -> str:
    """Lowercase, ASCII-only, hyphen-separated."""
    cleaned = re.sub(r"[&/]", " ", value.lower())
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned)
    return cleaned.strip("-")


def build_labels(cohort: list[dict]) -> list[dict]:
    """Return one label record per cohort product, in cohort order."""
    domain_sequences: Counter[str] = Counter()
    # Products sharing a subcategory need a stable discriminator. Sorting by
    # product_id first means the numbering does not shuffle between runs.
    by_subcategory: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in sorted(cohort, key=lambda r: r["product_id"]):
        by_subcategory[(row["domain"], row["subcategory"])].append(row)

    labels: dict[int, dict] = {}
    for (domain, subcategory), rows in by_subcategory.items():
        prefix = DOMAIN_PREFIX[domain]
        sub_slug = slugify(subcategory)
        for index, row in enumerate(rows, start=1):
            product_id = row["product_id"]
            domain_sequences[domain] += 1
            asset_id = f"{prefix.upper()}-{domain_sequences[domain]:03d}"
            flagship = FLAGSHIP_SLUGS.get(product_id)
            # Non-flagships in a single-product subcategory need no number.
            if flagship:
                discriminator = flagship
            elif len(rows) == 1:
                discriminator = ""
            else:
                discriminator = f"{index:02d}"

            stem = "-".join(part for part in (prefix, sub_slug, discriminator) if part)
            labels[product_id] = {
                "asset_id": asset_id,
                "product_id": product_id,
                "domain": domain,
                "category": row["category"],
                "subcategory": subcategory,
                "merchandising_title": row["merchandising_title"],
                "source_title": row["source_title"],
                "media_tier": row["media_tier"],
                "shop_page": row["shop_page"],
                "shop_position": row["shop_position"],
                "is_flagship": row["is_flagship"],
                "is_retrieval_anchor": row["is_retrieval_anchor"],
                "asset_stem": stem,
                "catalog_asset_key": f"{stem}-catalog-3x2",
                "catalog_runtime": f"{stem}-catalog-3x2.webp",
                "catalog_runtime_path": (
                    f"/assets/images/mosaic/{stem}-catalog-3x2.webp"
                ),
                # Only flagships get a square detail hero; the other 114 are
                # only ever seen in a 3:2 card frame.
                "detail_asset_key": f"{stem}-detail-1x1" if row["is_flagship"] else None,
                "detail_runtime": f"{stem}-detail-1x1.webp" if row["is_flagship"] else None,
                "upstream_catalog_asset_key": row["catalog_asset_key"],
            }

    return [labels[row["product_id"]] for row in cohort]


def installed_stems() -> set[str]:
    """Runtime filenames already present, without extension."""
    if not RUNTIME_DIR.is_dir():
        return set()
    return {path.stem for path in RUNTIME_DIR.glob("*.webp")}


def report(labels: list[dict]) -> dict:
    have = installed_stems()
    needed_catalog = [row for row in labels if row["catalog_runtime"][:-5] not in have]
    needed_detail = [
        row for row in labels if row["detail_runtime"] and row["detail_runtime"][:-5] not in have
    ]
    return {
        "products": len(labels),
        "by_domain": dict(Counter(row["domain"] for row in labels)),
        "catalog_images_required": len(labels),
        "detail_images_required": sum(1 for row in labels if row["detail_runtime"]),
        "catalog_still_to_generate": len(needed_catalog),
        "detail_still_to_generate": len(needed_detail),
        "total_still_to_generate": len(needed_catalog) + len(needed_detail),
    }


def import_provenance() -> dict[str, dict[str, str]]:
    """Map runtime filename to its generation-batch record.

    Later batches win on collision: re-importing an asset is a deliberate
    replacement, so the newest manifest naming it describes the file on disk.
    """
    provenance: dict[str, dict[str, str]] = {}
    for manifest in sorted(IMPORT_MANIFEST_DIR.glob(IMPORT_MANIFEST_GLOB)):
        with manifest.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                if row.get("output_filename"):
                    provenance[row["output_filename"]] = row
    return provenance


def attach_runtime_status(labels: list[dict]) -> None:
    provenance = import_provenance()
    for row in labels:
        runtime = RUNTIME_DIR / row["catalog_runtime"]
        row["catalog_installed"] = runtime.is_file()
        row["catalog_sha256"] = (
            hashlib.sha256(runtime.read_bytes()).hexdigest()
            if runtime.is_file()
            else None
        )
        imported = provenance.get(row["catalog_runtime"])
        row["source_batch"] = imported["source_batch"] if imported else None
        row["source_filename"] = imported["source_filename"] if imported else None

        detail_name = row["detail_runtime"]
        detail = RUNTIME_DIR / detail_name if detail_name else None
        row["detail_installed"] = bool(detail and detail.is_file())
        row["detail_sha256"] = (
            hashlib.sha256(detail.read_bytes()).hexdigest()
            if detail and detail.is_file()
            else None
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cohort",
        type=Path,
        required=True,
        help="premium_cohort_120.json from the schema package",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail instead of writing when the plan would change",
    )
    args = parser.parse_args()

    cohort = json.loads(args.cohort.read_text())
    labels = build_labels(cohort)
    attach_runtime_status(labels)

    collisions = [key for key, count in Counter(r["asset_stem"] for r in labels).items() if count > 1]
    if collisions:
        print(f"FAIL: duplicate asset stems: {collisions}", file=sys.stderr)
        return 1

    summary = report(labels)
    payload = {
        "version": 1,
        "naming_scheme": "<domain>-<subcategory>-<discriminator>-<role>",
        "summary": summary,
        "products": labels,
    }
    serialized = json.dumps(payload, indent=2) + "\n"

    if args.check:
        if not args.output.exists() or args.output.read_text() != serialized:
            print("FAIL: asset labels are stale; re-run without --check", file=sys.stderr)
            return 1
        print("asset labels up to date")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized)
    print(json.dumps(summary, indent=2))
    print(f"\nwrote {args.output.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
