#!/usr/bin/env python3
"""Validate the checked-in Mosaic catalog package without a database."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

from catalog_contract import unsupported_filter_keys

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DOMAIN_COUNTS = {
    "consumer_electronics": 210_000,
    "running_fitness": 160_000,
    "home_office": 130_000,
}
EXPECTED_SAMPLE_DOMAIN_COUNTS = {
    "consumer_electronics": 2_100,
    "running_fitness": 1_600,
    "home_office": 1_300,
}


def require(condition: bool, message: str) -> None:
    """Fail with the violated catalog-package rule and its nearest repair."""
    if not condition:
        raise SystemExit(f"PACKAGE VALIDATION FAILED: {message}")


def csv_row_count(path: Path) -> int:
    """Return the number of data rows in a gzip-compressed CSV."""
    with gzip.open(path, "rt", encoding="utf-8", newline="") as source:
        return sum(1 for _ in source) - 1


def main() -> None:
    """Validate catalog assets, quality claims, and evaluator input shape."""
    manifest = json.loads((ROOT / "data/full/manifest.json").read_text())
    quality = json.loads((ROOT / "data/full/quality_report.json").read_text())

    require(
        manifest["total_products"] == 500_000,
        (
            f"catalog manifest declares {manifest['total_products']} products; expected 500000. "
            "Regenerate the full catalog and manifest together."
        ),
    )
    require(
        manifest["domain_counts"] == EXPECTED_DOMAIN_COUNTS,
        (
            f"catalog domain counts are {manifest['domain_counts']}; expected "
            f"{EXPECTED_DOMAIN_COUNTS}. Regenerate the full catalog and manifest together."
        ),
    )

    shards = [ROOT / path for path in manifest["full_datasets"]]
    require(
        len(shards) == 3,
        f"manifest lists {len(shards)} full dataset shards; expected 3. Regenerate data/full/manifest.json.",
    )
    missing_shards = [str(path.relative_to(ROOT)) for path in shards if not path.is_file()]
    require(
        not missing_shards,
        f"full dataset shards are missing: {missing_shards}. Restore the checked-in data/full artifacts.",
    )
    oversized_shards = [
        f"{path.relative_to(ROOT)}={path.stat().st_size}"
        for path in shards
        if path.stat().st_size >= 100_000_000
    ]
    require(
        not oversized_shards,
        (
            f"full dataset shard exceeds the 100 MB package limit: {oversized_shards}. "
            "Split the source catalog before packaging."
        ),
    )

    expected_hashes = {
        item["path"]: item["sha256"]
        for item in quality["full_dataset_shards"]
    }
    for path in shards:
        relative_path = str(path.relative_to(ROOT))
        actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        expected_digest = expected_hashes.get(relative_path)
        require(
            expected_digest is not None,
            (
                f"{relative_path} is absent from quality_report.json. "
                "Regenerate the quality report after changing a full dataset shard."
            ),
        )
        require(
            actual_digest == expected_digest,
            (
                f"{relative_path} SHA-256 is {actual_digest}, expected {expected_digest}. "
                "Restore the checked-in shard or regenerate the manifest and quality report."
            ),
        )

    media = manifest["media_mapping"]
    media_path = ROOT / media["path"]
    require(
        media_path.is_file(),
        (
            f"media mapping {media_path.relative_to(ROOT)} is missing. "
            "Run 'make media-map' after restoring the full catalog."
        ),
    )
    require(
        media_path.stat().st_size < 100_000_000,
        (
            f"media mapping is {media_path.stat().st_size} bytes; expected less than 100000000. "
            "Split the mapping before packaging."
        ),
    )
    media_digest = hashlib.sha256(media_path.read_bytes()).hexdigest()
    require(
        media_digest == media["sha256"],
        (
            f"media mapping SHA-256 is {media_digest}, expected {media['sha256']}. "
            "Run 'make media-map' and regenerate the catalog manifest."
        ),
    )
    media_rows = csv_row_count(media_path)
    require(
        media_rows == media["rows"] == 500_000,
        (
            f"media mapping has {media_rows} rows; manifest={media['rows']}, expected 500000. "
            "Run 'make media-map' and regenerate the catalog manifest."
        ),
    )

    for key in (
        "invalid_updated_before_launch",
        "malformed_skus",
        "unsupported_filter_queries",
        "filter_target_mismatches",
    ):
        require(
            quality[key] == 0,
            (
                f"quality_report.json has {key}={quality[key]}; expected 0. "
                "Run 'make quality' and repair the reported catalog rows."
            ),
        )

    queries = [
        json.loads(line)
        for line in (ROOT / "data/evals/queries.jsonl").read_text().splitlines()
        if line.strip()
    ]
    unsupported_filters = {
        query["query_id"]: sorted(unsupported_filter_keys(query.get("filters") or {}))
        for query in queries
        if unsupported_filter_keys(query.get("filters") or {})
    }
    require(
        not unsupported_filters,
        (
            f"evaluation queries use unsupported filters: {unsupported_filters}. "
            "Use only service.models.SearchFilters fields and regenerate the evaluation corpus."
        ),
    )

    sample_path = ROOT / "data/sample/products_5000.csv.gz"
    with gzip.open(sample_path, "rt", encoding="utf-8", newline="") as source:
        sample_rows = list(csv.DictReader(source))
    require(
        len(sample_rows) == 5_000,
        (
            f"sample catalog has {len(sample_rows)} rows; expected 5000. "
            "Run 'make prepare' after restoring the full catalog."
        ),
    )
    sample_domain_counts = Counter(row["domain"] for row in sample_rows)
    require(
        sample_domain_counts == EXPECTED_SAMPLE_DOMAIN_COUNTS,
        (
            f"sample domain counts are {dict(sample_domain_counts)}; expected "
            f"{EXPECTED_SAMPLE_DOMAIN_COUNTS}. Run 'make prepare' to rebuild the sample."
        ),
    )

    typo_path = ROOT / "data/evals/typo_cases.csv"
    with typo_path.open(encoding="utf-8") as source:
        typo_rows = sum(1 for _ in source) - 1
    require(
        typo_rows == 5_000,
        (
            f"typo cohort has {typo_rows} rows; expected 5000. "
            "Regenerate the evaluation assets with the catalog."
        ),
    )
    print("Package validation passed: shards, hashes, row quality, eval filters, sample, and typo cohort.")


if __name__ == "__main__":
    main()
