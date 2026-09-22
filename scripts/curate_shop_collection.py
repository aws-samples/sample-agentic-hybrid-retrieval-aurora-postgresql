#!/usr/bin/env python3
"""Build a balanced Shop edit from verified source records, without re-embedding."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_real_catalog import source_image
from service.source_catalog import product_kind, verify_source_product

GROUPS = {"headphones": "headphones", "chairs": "chair", "monitors": "monitor"}
# The opening rows make a supported match, a feature contrast, and an unknown
# easy to compare. These are identities, not boosts in the retrieval pipeline.
OPENING = {
    "headphones": ("B07G95TJ3P", "B08VD2NX25", "B0C5ZC7FWR", "B09WT4TM7P"),
    "chairs": ("B08QDNY2GK", "B08KTS3M9M", "B0BRSPW81P", "B08XZBQ6RS"),
    "monitors": ("B0939N79Y8", "B01L7XV85O", "B06XQ39Z7F", "B0BXDZVPQ5"),
}
REVIEW_EXCLUSIONS = {
    "B07NXDPLJ9": "Colour variant of the opening QuietComfort 35 II example.",
    "B08YN3258B": "Near-duplicate COMHOMA 400 lb brown executive chair listing.",
    "B000TJV9KW": "Legacy 1920 x 1200 display; clearer resolution contrasts are available.",
    "B002453K5G": "Legacy display with less useful connection coverage than alternatives.",
    "B0036V76NY": "Legacy professional display; prioritize current home-office connection patterns.",
    "B00JJVW2AW": "Another colour of the selected Beats Studio wired 2.0 example.",
}
EXCLUDE = {
    "headphones": r"replacement|ear\s?pads?|ear\s?cushions?|\bcase\b|\bkids?\b|children|toddler|sleep|headband|cat ear|cosplay|cartoon|earbuds|bone conduction|hearing protection|FM radio|\bon.ear\b",
    "chairs": r"replacement|\bmat\b|headrest only|headrest attachment|mechanism|massage|racing|kneeling|stool|guest chair|visitor chair|dining|kids|children|flag chair|american flag",
    "monitors": r"replacement|\bstand only\b|\bmount\b|\briser\b|\bprivacy\b|\bprotector\b|\blaptop\b|\bportable\b|baby monitor|camera monitor|\bCRT\b",
}
SIGNALS = {
    "headphones": {
        "noise control": r"noise.cancel|\bANC\b|open.back",
        "microphone or calls": r"microphone|\bmic\b|\bcalls?\b",
        "connection": r"bluetooth|wireless|wired|3\.5\s?mm|USB",
        "battery": r"battery|\d+.?(?:hour|hr)",
        "fit": r"weight|lightweight|ear.?cups?|ear.?pads?|over.ear",
    },
    "chairs": {
        "back support": r"lumbar|back support",
        "arm adjustment": r"adjustable arms?|arm.?rests?|flip.up",
        "seat adjustment": r"seat height|height.adjust|adjustable height",
        "recline": r"reclin|tilt|synchro",
        "materials": r"mesh|leather|fabric|upholster",
    },
    "monitors": {
        "screen size": r"\d+.?(?:inch|inches|\")",
        "resolution": r"\b[248]K\b|\d{4}\s?[x×]\s?\d{3,4}|\b[UWQF]*HD\b|\d{4}p",
        "connection": r"USB.C|HDMI|DisplayPort|Thunderbolt",
        "power delivery": r"power delivery|\d+\s?w(?:att)?\b|charg",
        "stand adjustment": r"height.adjust|adjustable height|pivot|swivel|tilt",
    },
}


def topics(row: dict, group: str) -> list[str]:
    """Identify topics to inspect, never treat a keyword as proof of a feature."""
    return [
        name
        for name, pattern in SIGNALS[group].items()
        if re.search(pattern, row["embedding_text"], re.IGNORECASE)
    ]


def eligible(row: dict, group: str) -> bool:
    """Reject weak source coverage and common source-taxonomy mistakes."""
    original = verify_source_product(row)
    title = original["title"]
    brand = original["details"].get("Brand")
    introduced = re.search(
        r"\b(?:19|20)\d{2}\b", str(original["details"].get("Date First Available", ""))
    )
    return bool(
        product_kind(original["categories"]) == GROUPS[group]
        and original["categories"][-1] != "Computer Gaming Chairs"
        and (group != "monitors" or introduced is None or int(introduced[0]) >= 2014)
        and row["parent_asin"] not in REVIEW_EXCLUSIONS
        and not re.search(
            EXCLUDE[group] + r"|renewed|refurbished|discontinued|\b2 pack\b",
            title,
            re.IGNORECASE,
        )
        and row["image_url"] == source_image(original)
        and row["image_url"].startswith("https://m.media-amazon.com/")
        and isinstance(brand, str)
        and brand.strip()
        and isinstance(original.get("average_rating"), (int, float))
        and (row["parent_asin"] in OPENING[group] or original["average_rating"] >= 3.8)
        and len(original["features"]) >= 2
        and len(original["details"]) >= 3
        and (original.get("rating_number") or 0)
        >= (1 if row["parent_asin"] in OPENING[group] else 25)
        and len(topics(row, group)) >= 2
    )


def evidence_score(row: dict, group: str) -> float:
    """Prefer inspectable records, with rating count only a secondary signal."""
    original = row["original"]
    return (
        len(topics(row, group)) * 10
        + min(len(original["features"]), 6)
        + min(len(original["details"]), 12) / 4
        + min(math.log10(max(1, original.get("rating_number") or 0)), 4)
        - (8 if re.search(r"gaming|\bDJ\b", original["title"], re.IGNORECASE) else 0)
    )


def select_group(rows: list[dict], group: str, amount: int) -> list[dict]:
    """Keep useful opening contrasts, then diversify source-rich products."""
    available = {row["parent_asin"]: row for row in rows if eligible(row, group)}
    for asin in OPENING[group]:
        if asin not in available:
            raise ValueError(
                f"Shop opening rule: {asin} is missing or ineligible; inspect its preserved source before changing the opening examples."
            )
    ordered = [available[asin] for asin in OPENING[group]]
    ordered += sorted(
        (row for asin, row in available.items() if asin not in OPENING[group]),
        key=lambda row: (-evidence_score(row, group), row["parent_asin"]),
    )
    chosen, images, models, titles = [], set(), set(), []
    brands: Counter[str] = Counter()
    for row in ordered:
        original = row["original"]
        details = original["details"]
        brand = details["Brand"].strip().casefold()
        model = (
            str(
                details.get("Model Name")
                or details.get("Item model number")
                or row["parent_asin"]
            )
            .strip()
            .casefold()
        )
        title = (
            original["title"]
            .casefold()
            .replace(str(details.get("Color", "")).casefold(), "")
            if details.get("Color")
            else original["title"].casefold()
        )
        title = re.sub(r"[^a-z0-9]+", " ", title).strip()
        numbers = re.findall(r"\d+", title)
        variant = any(
            brand == other_brand
            and numbers == other_numbers
            and SequenceMatcher(None, title, other_title).ratio() > 0.88
            for other_brand, other_title, other_numbers in titles
        )
        if (
            brands[brand] >= 4
            or row["image_url"] in images
            or (brand, model) in models
            or variant
        ):
            continue
        chosen.append(row)
        brands[brand] += 1
        images.add(row["image_url"])
        models.add((brand, model))
        titles.append((brand, title, numbers))
        if len(chosen) == amount:
            return chosen
    raise ValueError(
        f"Shop balance rule: only {len(chosen)} eligible, distinct {group}; requested {amount}. Review source coverage instead of padding the selection."
    )


def build_collection(rows: list[dict], dataset: str, amount: int = 40) -> dict:
    """Keep source hashes beside the order so this edit can be independently checked."""
    selected = {group: select_group(rows, group, amount) for group in GROUPS}
    return {
        "dataset_id": dataset,
        "selection_policy": "Original listings with clear specifications, original photos and recorded rating counts. Opening examples first, then source-topic coverage and brand/model variety. This is a browsing edit, not a search ranking or product endorsement.",
        "display_order": "One headphone, one chair, one monitor, repeated. Search uses the full catalog and its own ranking.",
        "review_exclusions": REVIEW_EXCLUSIONS,
        "groups": [
            {
                "category": group,
                "parent_asins": [row["parent_asin"] for row in products],
            }
            for group, products in selected.items()
        ],
        "records": {
            row["parent_asin"]: {
                "source_record_sha256": row["source_record_sha256"],
                "embedding_text_sha256": row["embedding_text_sha256"],
                "topics_to_inspect": topics(row, group),
                "opening_example": row["parent_asin"] in OPENING[group],
            }
            for group, products in selected.items()
            for row in products
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "pool", type=Path, help="Verified prepared source rows, JSONL or JSONL.gz"
    )
    parser.add_argument("--dataset", required=True)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "data/real-shop-collection.json"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail on a changed selection instead of writing it",
    )
    args = parser.parse_args()
    opener = gzip.open if args.pool.suffix == ".gz" else open
    with opener(args.pool, "rt") as handle:
        rows = [json.loads(line) for line in handle]
    if any(row.get("dataset_id") != args.dataset for row in rows):
        raise ValueError(
            "Shop dataset rule: source rows belong to a different dataset; export the selected catalog's source rows."
        )
    manifest = build_collection(rows, args.dataset)
    if args.check:
        if json.loads(args.output.read_text()) != manifest:
            raise ValueError(
                f"Shop selection rule: {args.output} differs from the verified selection; regenerate and review the product changes."
            )
    else:
        args.output.write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps(
            {
                group["category"]: len(group["parent_asins"])
                for group in manifest["groups"]
            }
        )
    )


if __name__ == "__main__":
    main()
