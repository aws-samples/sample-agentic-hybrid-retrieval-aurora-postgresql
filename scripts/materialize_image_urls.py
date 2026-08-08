#!/usr/bin/env python3
"""Build the deterministic 500K product-to-media mapping."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def catalog_paths(manifest_path: Path) -> list[Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [ROOT / path for path in manifest["full_datasets"]]


def runtime_path(value: str) -> str:
    path = value.removeprefix("ui/").lstrip("/")
    if not path.startswith("assets/images/"):
        raise ValueError(f"Unexpected image path: {value}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data" / "full" / "manifest.json",
    )
    parser.add_argument(
        "--asset-map",
        type=Path,
        default=ROOT / "data" / "dictionaries" / "image_asset_map.json",
    )
    parser.add_argument(
        "--curated-map",
        type=Path,
        default=ROOT / "data" / "curated" / "image_manifest.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "full" / "product_image_urls.csv.gz",
    )
    args = parser.parse_args()

    asset_map = json.loads(args.asset_map.read_text(encoding="utf-8"))
    fallbacks = {
        (item["domain"], item["category"], item["subcategory"]): runtime_path(
            item["demo_asset"]
        )
        for item in asset_map["entries"]
    }
    curated = {
        int(product_id): item
        for product_id, item in json.loads(
            args.curated_map.read_text(encoding="utf-8")
        ).items()
    }
    fieldnames = ["product_id", "image_url", "image_source", "image_key"]
    counts = {
        "mosaic_showcase": 0,
        "curated_photorealistic": 0,
        "category_fallback": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(
        args.output,
        "wt",
        encoding="utf-8",
        newline="",
        compresslevel=6,
    ) as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for catalog_path in catalog_paths(args.manifest):
            with gzip.open(
                catalog_path,
                "rt",
                encoding="utf-8",
                newline="",
            ) as source:
                for product in csv.DictReader(source):
                    product_id = int(product["product_id"])
                    if product_id in curated:
                        image_url = runtime_path(curated[product_id]["path"])
                        image_source = (
                            "mosaic_showcase"
                            if "/mosaic/" in f"/{image_url}"
                            else "curated_photorealistic"
                        )
                    else:
                        image_url = fallbacks[
                            (
                                product["domain"],
                                product["category"],
                                product["subcategory"],
                            )
                        ]
                        image_source = "category_fallback"
                    writer.writerow(
                        {
                            "product_id": product["product_id"],
                            "image_url": image_url,
                            "image_source": image_source,
                            "image_key": product["image_key"],
                        }
                    )
                    counts[image_source] += 1
    print(f"Wrote {sum(counts.values()):,} media mappings: {counts}")


if __name__ == "__main__":
    main()
