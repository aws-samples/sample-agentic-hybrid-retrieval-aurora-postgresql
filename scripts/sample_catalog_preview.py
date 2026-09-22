#!/usr/bin/env python3
"""Add a diverse, repeatable visual sample without changing catalog or embeddings."""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.embed_real_catalog import verified_selection
from scripts.prepare_real_catalog import sha256, source_image
from service.source_catalog import (
    product_kind,
    specification_evidence,
    verify_source_product,
)

GROUPS = {"headphones": "headphones", "chairs": "chair", "monitors": "monitor"}
SPECIFICATIONS = {
    "headphones": [
        ("Style", ("Form Factor",)),
        ("Connection", ("Connectivity Technology",)),
        ("Noise control", ("Noise Control",)),
        ("Features", ("Special Feature", "Special Features")),
    ],
    "chairs": [
        ("Material", ("Material",)),
        ("Colour", ("Color",)),
        ("Features", ("Special Feature", "Special Features")),
        ("Dimensions", ("Product Dimensions",)),
    ],
    "monitors": [
        ("Screen size", ("Screen Size", "Standing screen display size")),
        (
            "Resolution",
            ("Display Resolution Maximum", "Screen Resolution", "Resolution"),
        ),
        ("Refresh rate", ("Refresh Rate",)),
        ("Features", ("Special Feature", "Special Features")),
    ],
}
ACCESSORY = re.compile(
    r"\b(?:replacement|ear\s?pads?|ear\s?cushions?)\b|"
    r"\b(?:headphone|headset|monitor|screen|chair)s?\s+"
    r"(?:case|cover|stand|arm|mount|riser|filter|protector|mat)s?\b",
    re.IGNORECASE,
)


def category(row: dict) -> str | None:
    original = row["original"]
    if ACCESSORY.search(original["title"]):
        return None
    kind = product_kind(original["categories"])
    return next((group for group, expected in GROUPS.items() if expected == kind), None)


def brand_for(row: dict) -> str:
    original = row["original"]
    value = original["details"].get("Brand") or original.get("store")
    return (
        value.strip()
        if isinstance(value, str) and value.strip()
        else "Brand not supplied"
    )


def diverse_sample(rows: list[dict], amount: int) -> list[dict]:
    """Limit repeated brands and photos; stable identity hashes decide selection."""
    chosen = []
    brands: Counter[str] = Counter()
    images: set[str] = set()
    for row in sorted(
        rows, key=lambda item: sha256("mosaic-preview-v1:" + item["parent_asin"])
    ):
        brand = brand_for(row).casefold()
        if brands[brand] >= 2 or row["image_url"] in images:
            continue
        chosen.append(row)
        brands[brand] += 1
        images.add(row["image_url"])
        if len(chosen) == amount:
            return chosen
    raise ValueError(
        f"Preview diversity rule: found {len(chosen)} products, requested {amount}; "
        "lower the sample size or inspect category coverage."
    )


def preview_product(row: dict, group: str) -> dict:
    original = verify_source_product(row)
    if row["image_url"] != source_image(original):
        raise ValueError(
            f"Preview photo rule: {row['parent_asin']} changed; restore its source photo."
        )
    details = original["details"]
    facts = []
    for label, keys in SPECIFICATIONS[group]:
        value = next((details[key] for key in keys if details.get(key)), "Not supplied")
        facts.append(
            {
                "label": label,
                "value": value
                if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False),
            }
        )
    product = {
        "id": row["parent_asin"],
        "brand": brand_for(row),
        "model": str(
            details.get("Model Name")
            or details.get("Item model number")
            or original["title"]
        ),
        "title": original["title"],
        "description": original["categories"][-1],
        "image": row["image_url"],
        "originalDescription": "\n".join(original["description"]) or None,
        "originalBulletPoints": "\n".join(original["features"]) or None,
        "facts": facts,
        "sourceUrl": specification_evidence(row)["source_reference"],
        "sourceLabel": "Original dataset record",
        "sourceDataset": "Amazon Reviews 2023",
        "listingUrl": f"https://www.amazon.com/dp/{row['parent_asin']}",
        "selectedInBulk": True,
        "sourceRecordSha256": row["source_record_sha256"],
    }
    average, count = original.get("average_rating"), original.get("rating_number")
    if (
        type(average) in (int, float)
        and 1 <= average <= 5
        and type(count) is int
        and count > 0
    ):
        product["rating"] = {"average": average, "count": count}
    return product


def build_preview(selection: Path, preview: dict, amount: int) -> dict:
    """Read only the verified selection and preserve every reviewed example."""
    if not 1 <= amount <= 100:
        raise ValueError(
            f"Preview size rule: requested {amount}; choose between 1 and 100 per category."
        )
    manifest = verified_selection(selection)
    excluded = {
        product["id"] for group in preview["groups"] for product in group["products"]
    }
    rows_by_group = {group: [] for group in GROUPS}
    scanned = 0
    with gzip.open(selection / "catalog.jsonl.gz", "rt") as stream:
        for line in stream:
            row = json.loads(line)
            scanned += 1
            group = category(row)
            if group and row["parent_asin"] not in excluded:
                rows_by_group[group].append(row)
    if scanned != manifest["products"]:
        raise ValueError(
            f"Preview selection count rule: read {scanned}, expected {manifest['products']}; restore the complete selection."
        )
    for group in preview["groups"]:
        group["catalogSamples"] = [
            preview_product(row, group["id"])
            for row in diverse_sample(rows_by_group[group["id"]], amount)
        ]
    preview["catalogSample"] = {
        "productsPerCategory": amount,
        "selectedProducts": manifest["products"],
        "catalogSha256": manifest["catalog_sha256"],
        "selectionPolicy": "Stable product hashes; at most two products per brand; unique source photos; reviewed examples excluded.",
        "eligibleCounts": {key: len(rows) for key, rows in rows_by_group.items()},
    }
    return preview


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--preview", type=Path, required=True)
    parser.add_argument("--per-category", type=int, default=20)
    args = parser.parse_args()
    original = json.loads(args.preview.read_text())
    result = build_preview(args.selection, original, args.per_category)
    temporary = args.preview.with_suffix(".partial")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(args.preview)
    print(json.dumps(result["catalogSample"]))


if __name__ == "__main__":
    main()
