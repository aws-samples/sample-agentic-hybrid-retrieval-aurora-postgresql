import csv
import json
from pathlib import Path

from scripts.export_premium_cohort import export_cohort


def test_export_premium_cohort_renders_load_contract(tmp_path: Path):
    source = tmp_path / "cohort.json"
    output = tmp_path / "cohort.csv"
    source.write_text(
        json.dumps(
            [
                {
                    "product_id": 1,
                    "product_uid": "f87d2541-a671-5a88-a0db-80a10e5dfb88",
                    "sku": "SKU-1",
                    "domain": "consumer_electronics",
                    "category": "Audio",
                    "subcategory": "Headphones",
                    "source_title": "Source title",
                    "merchandising_title": "Mosaic title",
                    "media_tier": "flagship",
                    "shop_page": 1,
                    "shop_position": 1,
                    "is_flagship": True,
                    "is_retrieval_anchor": True,
                    "catalog_asset_key": "catalog-key",
                    "detail_asset_key": "detail-key",
                    "image_status": "generated",
                    "challenge_cohorts": ["semantic_intent", "curated_demo"],
                }
            ]
        ),
        encoding="utf-8",
    )

    assert export_cohort(source, output) == 1
    with output.open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))

    assert row["is_flagship"] == "true"
    assert row["is_retrieval_anchor"] == "true"
    assert row["challenge_cohorts"] == "semantic_intent|curated_demo"
