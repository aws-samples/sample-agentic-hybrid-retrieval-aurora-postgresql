"""Curated corrections must reach a fresh normalized bootstrap."""

from __future__ import annotations

import csv
import gzip
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_transform_module():
    path = ROOT / "db" / "scripts" / "transform_legacy_catalog.py"
    spec = importlib.util.spec_from_file_location("catalog_transform_for_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_transform_applies_curated_aliases_before_bootstrap_normalization(
    tmp_path, monkeypatch
):
    source = tmp_path / "catalog.csv.gz"
    fields = [
        "product_id",
        "product_uid",
        "sku",
        "domain",
        "category",
        "subcategory",
        "brand",
        "model",
        "title",
        "short_description",
        "long_description",
        "price_usd",
        "list_price_usd",
        "currency",
        "rating",
        "review_count",
        "availability",
        "inventory_count",
        "seller_count",
        "shipping_days",
        "warranty_months",
        "return_rate",
        "popularity_score",
        "quality_score",
        "freshness_score",
        "metadata_completeness",
        "launch_date",
        "updated_at",
        "source_system",
        "language",
        "is_refurbished",
        "is_sponsored",
        "attributes_json",
        "tags_json",
        "aliases_json",
        "search_text",
        "embedding_text",
        "challenge_cohorts_json",
        "canonical_group_id",
        "image_key",
    ]
    row = {
        "product_id": "30001",
        "product_uid": "ecd0ca9c-b942-5ed8-a8fa-cf7ddb3482eb",
        "sku": "CO-PORTA-0030001",
        "domain": "consumer_electronics",
        "category": "Audio",
        "subcategory": "Portable Speakers",
        "brand": "Sonora",
        "model": "Roam 2",
        "title": "stale title",
        "short_description": "stale description",
        "long_description": "stale details",
        "price_usd": "1.00",
        "list_price_usd": "1.00",
        "currency": "USD",
        "rating": "1.0",
        "review_count": "1",
        "availability": "In Stock",
        "inventory_count": "1",
        "seller_count": "1",
        "shipping_days": "1",
        "warranty_months": "1",
        "return_rate": "0.01",
        "popularity_score": "0.10",
        "quality_score": "0.10",
        "freshness_score": "0.10",
        "metadata_completeness": "0.10",
        "launch_date": "2026-01-01",
        "updated_at": "2026-08-01T00:00:00+00:00",
        "source_system": "source",
        "language": "en-US",
        "is_refurbished": "false",
        "is_sponsored": "false",
        "attributes_json": "{}",
        "tags_json": "[]",
        "aliases_json": "[]",
        "search_text": "",
        "embedding_text": "",
        "challenge_cohorts_json": "[]",
        "canonical_group_id": "speaker-30001",
        "image_key": "stale.webp",
    }
    with gzip.open(source, "wt", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)

    output = tmp_path / "normalized"
    module = _load_transform_module()
    monkeypatch.setattr(
        sys,
        "argv",
        ["transform_legacy_catalog.py", str(source), str(output)],
    )
    module.main()

    with gzip.open(
        output / "products.csv.gz", "rt", newline="", encoding="utf-8"
    ) as handle:
        normalized = next(csv.DictReader(handle))
    assert normalized["title"] == "Sonora Roam 2 Portable Bluetooth Speaker"
    assert "waterproof Wi-Fi Bluetooth speaker" in json.loads(normalized["aliases"])
