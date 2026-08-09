#!/usr/bin/env python3
"""Split the existing Mosaic 500K flat catalog into normalized load files.

Input is the products_500k.csv.gz format from the full workshop bundle. Output:
brands.csv.gz, categories.csv.gz, products.csv.gz, offers.csv.gz, and
product_documents.csv.gz. Embedding columns remain empty for the embedding job.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    brand_ids: dict[str, int] = {}
    category_ids: dict[tuple[str, str, str], int] = {}

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
        with gzip.open(args.input, "rt", newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            for index, row in enumerate(reader, start=1):
                if args.limit and index > args.limit:
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
                    c_writer.writerow({
                        "category_id": category_id,
                        "domain": domain,
                        "parent_category_id": "",
                        "category_key": stable_key("category", *category_key_tuple),
                        "display_name": row["subcategory"],
                        "category_path": f"{row['category']} > {row['subcategory']}",
                        "depth": 1,
                        "metadata": json.dumps({"category_family": row["category"]}, separators=(",", ":")),
                    })
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
    finally:
        for handle in (b_handle, c_handle, p_handle, o_handle):
            handle.close()

    print(json.dumps({"brands": len(brand_ids), "categories": len(category_ids), "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
