#!/usr/bin/env python3
"""Split the existing Mosaic 500K flat catalog into normalized load files.

Inputs are products_500k.csv.gz shards from the full workshop bundle. Output:
brands.csv.gz, categories.csv.gz, products.csv.gz, offers.csv.gz, and
product_documents.csv.gz. Embedding columns remain empty for the embedding job.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re

DOMAIN_MAP = {
    "consumer_electronics": "consumer_electronics",
    "running_fitness": "running_fitness",
    "home_office": "home_office",
    "home_office_workspace": "home_office",
}

AVAILABILITY_MAP = {
    "In Stock": "in_stock",
    "Low Stock": "low_stock",
    "Out of Stock": "out_of_stock",
    "Preorder": "preorder",
    "Discontinued": "discontinued",
}


def open_csv_writer(path: Path, fieldnames: list[str]):
    handle = gzip.open(path, "wt", newline="", encoding="utf-8")
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    return handle, writer


def stable_key(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:20]


def category_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def resolve_category_keys(
    categories: list[tuple[str, str, str]],
) -> dict[tuple[str, str, str], str]:
    base_keys = {
        category: category_key(category[2])
        for category in categories
    }
    counts = Counter(base_keys.values())
    resolved = {
        category: (
            base_key
            if counts[base_key] == 1
            else category_key(" ".join(category))
        )
        for category, base_key in base_keys.items()
    }
    if len(set(resolved.values())) != len(resolved):
        raise SystemExit("category identities do not resolve to unique category keys")
    return resolved


def cohort_product_ids(path: Path | None) -> set[int] | None:
    if path is None:
        return None
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise SystemExit("--cohort must contain a JSON array")
    try:
        product_ids = {int(row["product_id"]) for row in rows}
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(
            "--cohort rows must contain integer product_id values"
        ) from error
    if len(product_ids) != len(rows):
        raise SystemExit("--cohort contains duplicate product_id values")
    return product_ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, nargs="+")
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--cohort",
        type=Path,
        help="Optional JSON cohort; only rows with listed product_id values are emitted.",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    selected_product_ids = cohort_product_ids(args.cohort)

    brand_ids: dict[str, int] = {}
    category_ids: dict[tuple[str, str, str], int] = {}
    category_records: dict[tuple[str, str, str], dict[str, object]] = {}
    emitted_product_ids: set[int] = set()

    b_handle, b_writer = open_csv_writer(args.output / "brands.csv.gz", ["brand_id", "brand_key", "display_name", "is_synthetic", "metadata"])
    c_handle, c_writer = open_csv_writer(args.output / "categories.csv.gz", ["category_id", "domain", "parent_category_id", "category_key", "display_name", "category_path", "depth", "metadata"])
    p_handle, p_writer = open_csv_writer(args.output / "products.csv.gz", [
        "product_id", "product_uid", "sku", "brand_id", "category_id", "canonical_group_id", "model_name", "title",
        "short_description", "long_description", "language", "attributes", "tags", "aliases", "challenge_cohorts",
        "launch_date", "source_system", "content_hash", "is_active"
    ])
    o_handle, o_writer = open_csv_writer(args.output / "offers.csv.gz", [
        "product_id", "price_cents", "list_price_cents", "currency", "availability", "inventory_count", "seller_count",
        "shipping_days", "warranty_months", "rating", "review_count", "return_rate", "popularity_score", "quality_score",
        "freshness_score", "metadata_completeness", "is_refurbished", "is_sponsored", "offer_metadata", "effective_at"
    ])

    try:
        for input_path in args.input:
            with gzip.open(input_path, "rt", newline="", encoding="utf-8") as source:
                reader = csv.DictReader(source)
                for row in reader:
                    product_id = int(row["product_id"])
                    if (
                        selected_product_ids is not None
                        and product_id not in selected_product_ids
                    ):
                        continue
                    if product_id in emitted_product_ids:
                        raise SystemExit(
                            f"duplicate product_id {product_id} across input shards"
                        )
                    if args.limit and len(emitted_product_ids) >= args.limit:
                        break

                    domain = DOMAIN_MAP[row["domain"]]
                    brand = row["brand"]
                    if brand not in brand_ids:
                        brand_id = len(brand_ids) + 1
                        brand_ids[brand] = brand_id
                        b_writer.writerow({"brand_id": brand_id, "brand_key": stable_key("brand", brand), "display_name": brand, "is_synthetic": "true", "metadata": "{}"})
                    brand_id = brand_ids[brand]

                    category_key_tuple = (domain, row["category"], row["subcategory"])
                    if category_key_tuple not in category_ids:
                        category_id = len(category_ids) + 1
                        category_ids[category_key_tuple] = category_id
                        category_records[category_key_tuple] = {
                            "category_id": category_id,
                            "domain": domain,
                            "parent_category_id": "",
                            "display_name": row["subcategory"],
                            "category_path": f"{row['category']} > {row['subcategory']}",
                            "depth": 1,
                            "metadata": json.dumps({"category_family": row["category"]}, separators=(",", ":")),
                        }
                    category_id = category_ids[category_key_tuple]

                    content_hash = hashlib.sha256((row["title"] + row["long_description"] + row["attributes_json"]).encode("utf-8")).hexdigest()
                    p_writer.writerow({
                        "product_id": row["product_id"], "product_uid": row["product_uid"], "sku": row["sku"], "brand_id": brand_id,
                        "category_id": category_id, "canonical_group_id": row["canonical_group_id"], "model_name": row["model"], "title": row["title"],
                        "short_description": row["short_description"], "long_description": row["long_description"], "language": row["language"],
                        "attributes": row["attributes_json"], "tags": row["tags_json"],
                        "aliases": row["aliases_json"],
                        "challenge_cohorts": row["challenge_cohorts_json"],
                        "launch_date": row["launch_date"], "source_system": row["source_system"], "content_hash": content_hash, "is_active": "true",
                    })
                    o_writer.writerow({
                        "product_id": row["product_id"], "price_cents": round(float(row["price_usd"]) * 100),
                        "list_price_cents": round(float(row["list_price_usd"]) * 100), "currency": row["currency"],
                        "availability": AVAILABILITY_MAP[row["availability"]], "inventory_count": row["inventory_count"],
                        "seller_count": row["seller_count"], "shipping_days": row["shipping_days"], "warranty_months": row["warranty_months"],
                        "rating": row["rating"], "review_count": row["review_count"], "return_rate": row["return_rate"],
                        "popularity_score": row["popularity_score"], "quality_score": row["quality_score"], "freshness_score": row["freshness_score"],
                        "metadata_completeness": row["metadata_completeness"], "is_refurbished": row["is_refurbished"],
                        "is_sponsored": row["is_sponsored"], "offer_metadata": "{}", "effective_at": row["updated_at"],
                    })
                    emitted_product_ids.add(product_id)

            if args.limit and len(emitted_product_ids) >= args.limit:
                break

        resolved_category_keys = resolve_category_keys(list(category_records))
        for category, record in category_records.items():
            c_writer.writerow(
                {
                    **record,
                    "category_key": resolved_category_keys[category],
                }
            )
    finally:
        for handle in (b_handle, c_handle, p_handle, o_handle):
            handle.close()

    if selected_product_ids is not None:
        missing = selected_product_ids - emitted_product_ids
        if missing:
            sample = ", ".join(str(value) for value in sorted(missing)[:10])
            raise SystemExit(
                f"{len(missing)} cohort product IDs were absent from the input shards: "
                f"{sample}"
            )

    print(json.dumps({
        "brands": len(brand_ids),
        "categories": len(category_ids),
        "products": len(emitted_product_ids),
        "inputs": [str(path) for path in args.input],
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
