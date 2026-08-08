#!/usr/bin/env python3
"""Inspect the canonical catalog shards and write a reproducible quality report."""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from catalog_contract import product_matches_filters, unsupported_filter_keys

ROOT = Path(__file__).resolve().parents[1]
GITHUB_FILE_LIMIT = 100_000_000
SKU_PATTERN = re.compile(r"^[A-Z]{2}-[A-Z0-9]{1,5}-[0-9]{7}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    values.sort()
    index = round((len(values) - 1) * fraction)
    return values[index]


def main() -> None:
    manifest = json.loads((ROOT / "data/full/manifest.json").read_text(encoding="utf-8"))
    paths = [ROOT / relative for relative in manifest["full_datasets"]]
    queries = [
        json.loads(line)
        for line in (ROOT / "data/evals/queries.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    target_filters: dict[int, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for query in queries:
        target_filters[int(query["target_product_id"])].append(
            (query["query_id"], query.get("filters") or {})
        )
    unsupported_queries = [
        query["query_id"]
        for query in queries
        if unsupported_filter_keys(query.get("filters") or {})
    ]

    rows = 0
    product_uids: set[str] = set()
    skus: set[str] = set()
    brands: set[str] = set()
    subcategories: set[str] = set()
    subcategory_models: set[tuple[str, str]] = set()
    prices: list[float] = []
    ratings: list[float] = []
    nonempty_attributes = 0
    availability: Counter[str] = Counter()
    source_systems: Counter[str] = Counter()
    canonical_groups: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    invalid_timestamps = 0
    malformed_skus = 0
    matched_queries: set[str] = set()
    mismatched_queries: set[str] = set()

    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as source:
            for row in csv.DictReader(source):
                rows += 1
                product_id = int(row["product_id"])
                product_uids.add(row["product_uid"])
                skus.add(row["sku"])
                brands.add(row["brand"])
                subcategories.add(row["subcategory"])
                subcategory_models.add((row["subcategory"], row["model"]))
                prices.append(float(row["price_usd"]))
                ratings.append(float(row["rating"]))
                nonempty_attributes += bool(json.loads(row["attributes_json"]))
                availability[row["availability"]] += 1
                source_systems[row["source_system"]] += 1
                canonical_groups[row["canonical_group_id"]] += 1
                domain_counts[row["domain"]] += 1
                invalid_timestamps += row["updated_at"][:10] < row["launch_date"]
                malformed_skus += not SKU_PATTERN.fullmatch(row["sku"])
                if product_id in target_filters:
                    for query_id, filters in target_filters[product_id]:
                        if product_matches_filters(row, filters):
                            matched_queries.add(query_id)
                        else:
                            mismatched_queries.add(query_id)

    shard_reports = [
        {
            "path": str(path.relative_to(ROOT)),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in paths
    ]
    report: dict[str, Any] = {
        "rows": rows,
        "domain_counts": dict(domain_counts),
        "unique_product_uids": len(product_uids),
        "unique_skus": len(skus),
        "brands": len(brands),
        "subcategory_model_pairs": len(subcategory_models),
        "subcategories": len(subcategories),
        "price_usd": {
            "min": min(prices),
            "p50": percentile(prices, 0.50),
            "p90": percentile(prices, 0.90),
            "max": max(prices),
        },
        "rating": {
            "mean": round(sum(ratings) / len(ratings), 3),
            "p50": percentile(ratings, 0.50),
        },
        "attributes_nonempty_pct": round(nonempty_attributes / rows * 100, 3),
        "availability": dict(availability),
        "source_systems": dict(source_systems),
        "canonical_variant_groups_with_multiple_rows": sum(
            count > 1 for count in canonical_groups.values()
        ),
        "largest_variant_group": max(canonical_groups.values()),
        "invalid_updated_before_launch": invalid_timestamps,
        "malformed_skus": malformed_skus,
        "evaluation_queries": len(queries),
        "unsupported_filter_queries": len(unsupported_queries),
        "filter_target_mismatches": len(mismatched_queries),
        "filter_targets_found": len(matched_queries),
        "full_dataset_shards": shard_reports,
        "github_file_limit_bytes": GITHUB_FILE_LIMIT,
        "github_file_limit_ok": all(
            shard["bytes"] < GITHUB_FILE_LIMIT for shard in shard_reports
        ),
    }
    (ROOT / "data/full/quality_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "Catalog quality:",
        f"{rows:,} rows,",
        f"{invalid_timestamps} invalid timestamps,",
        f"{malformed_skus} malformed SKUs,",
        f"{len(unsupported_queries)} unsupported eval filters,",
        f"{len(mismatched_queries)} target mismatches.",
    )


if __name__ == "__main__":
    main()
