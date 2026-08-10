#!/usr/bin/env python3
"""Render the checked-in premium cohort JSON as the PostgreSQL load CSV."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


FIELDS = [
    "product_id",
    "product_uid",
    "sku",
    "domain",
    "category",
    "subcategory",
    "source_title",
    "merchandising_title",
    "media_tier",
    "shop_page",
    "shop_position",
    "is_flagship",
    "is_retrieval_anchor",
    "catalog_asset_key",
    "detail_asset_key",
    "image_status",
    "challenge_cohorts",
]


def csv_value(field: str, value: Any) -> Any:
    if field == "challenge_cohorts":
        return "|".join(value)
    if isinstance(value, bool):
        return str(value).lower()
    return value


def export_cohort(input_path: Path, output_path: Path) -> int:
    rows = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("premium cohort must be a JSON array")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=FIELDS,
            extrasaction="raise",
            quoting=csv.QUOTE_ALL,
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            missing = set(FIELDS) - set(row)
            if missing:
                raise ValueError(
                    f"premium cohort row is missing fields: {sorted(missing)}"
                )
            writer.writerow(
                {
                    field: csv_value(field, row[field])
                    for field in FIELDS
                }
            )
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("db/data/premium_cohort_120.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/normalized/premium_cohort_120.csv"),
    )
    args = parser.parse_args()
    count = export_cohort(args.input, args.output)
    print(f"Wrote {args.output} with {count:,} premium products")


if __name__ == "__main__":
    main()
