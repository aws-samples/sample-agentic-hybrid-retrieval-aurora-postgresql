"""Project real commerce fields for the 120-product offline showcase.

Usage:
    uv run python scripts/build_showcase_commerce_facts.py
"""

from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COHORT_PATH = ROOT / "db/data/premium_cohort_120.json"
OUTPUT_PATH = ROOT / "data/curated/showcase_commerce_facts_120.json"
CATALOG_PATHS = (
    ROOT / "data/full/products_consumer_electronics.csv.gz",
    ROOT / "data/full/products_running_fitness.csv.gz",
    ROOT / "data/full/products_home_office.csv.gz",
)


def project_commerce_facts() -> list[dict[str, Any]]:
    """Return commerce facts in the premium cohort's stable display order."""
    cohort = json.loads(COHORT_PATH.read_text(encoding="utf-8"))
    product_ids = [int(row["product_id"]) for row in cohort]
    wanted = set(product_ids)
    facts: dict[int, dict[str, Any]] = {}

    for path in CATALOG_PATHS:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                product_id = int(row["product_id"])
                if product_id not in wanted:
                    continue
                facts[product_id] = {
                    "product_id": product_id,
                    "price_usd": float(row["price_usd"]),
                    "list_price_usd": float(row["list_price_usd"]),
                    "currency": row["currency"],
                    "rating": float(row["rating"]) if row["rating"] else None,
                    "review_count": int(row["review_count"]),
                    "availability": row["availability"],
                    "inventory_count": int(row["inventory_count"]),
                }

    missing = wanted - facts.keys()
    if missing:
        raise ValueError(
            "Showcase commerce projection is missing premium product IDs "
            f"{sorted(missing)}. Regenerate the catalog before this projection."
        )
    return [facts[product_id] for product_id in product_ids]


def main() -> None:
    rows = project_commerce_facts()
    OUTPUT_PATH.write_text(
        json.dumps(rows, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT_PATH.relative_to(ROOT)} with {len(rows)} products")


if __name__ == "__main__":
    main()
