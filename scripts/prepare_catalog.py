#!/usr/bin/env python3
"""Apply presentation-quality catalog overrides without changing product identity."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import random
import sys
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.catalog_overrides import apply_curated_override, compact, text_parts

DEFAULT_MANIFEST = ROOT / "data" / "full" / "manifest.json"
DEFAULT_OVERRIDES = ROOT / "data" / "curated" / "demo_products.json"
DOMAIN_SAMPLE_TARGETS = {
    "consumer_electronics": 2_100,
    "running_fitness": 1_600,
    "home_office": 1_300,
}


def patch_known_quality_edges(row: dict[str, str]) -> bool:
    changed = False
    if row["subcategory"] == "Smartwatches" and "Smartwatche" in row["title"]:
        for field in (
            "title",
            "short_description",
            "long_description",
            "search_text",
            "embedding_text",
        ):
            row[field] = row[field].replace("Smartwatche", "Smartwatch")
        changed = True

    if row["subcategory"] == "Laptop Stands":
        rng = random.Random(0x434154414C4F47 ^ int(row["product_id"]))
        material = rng.choice(
            ["Anodized Aluminum", "Bamboo", "Steel", "Recycled Polymer"]
        )
        min_size = rng.choice([10, 11, 12])
        max_size = rng.choice([16, 17, 18])
        attributes = {
            "adjustable": rng.random() < 0.84,
            "material": material,
            "height_range_in": rng.choice(["2-6", "4-10", "6-12", "8-15"]),
            "tilt_levels": rng.choice([3, 5, 6, 8]),
            "compatible_laptop_in": [min_size, max_size],
            "weight_capacity_lb": rng.choice([18, 22, 30, 40]),
            "foldable": rng.random() < 0.68,
            "ventilated": rng.random() < 0.76,
            "phone_holder": rng.random() < 0.34,
        }
        tags = [
            "laptop stand",
            "ergonomic",
            "desk accessory",
            "adjustable",
            material.lower(),
        ]
        aliases = [
            row["brand"],
            row["model"],
            f"{row['brand']} {row['model']}",
            "notebook stand",
            "computer riser",
            "desk laptop riser",
        ]
        price = round(29 + rng.betavariate(2.1, 3.0) * 151, 2)
        row["price_usd"] = f"{price:.2f}"
        row["list_price_usd"] = (
            f"{max(price, round(price / rng.uniform(0.78, 1.0), 2)):.2f}"
        )
        row["short_description"] = (
            "Posture-supportive laptop elevation with adjustable height, angle, "
            "and ventilation for focused desk work."
        )
        row["long_description"] = (
            f"The {row['title']} raises laptops into a more neutral viewing "
            f"position. Its {material.lower()} frame supports {min_size}- to "
            f"{max_size}-inch notebooks, adds airflow, and adjusts for seated "
            "or standing work."
        )
        row["attributes_json"] = compact(attributes)
        row["tags_json"] = compact(tags)
        row["aliases_json"] = compact(aliases)
        row["metadata_completeness"] = "0.9800"
        row["search_text"], row["embedding_text"] = text_parts(
            row, attributes, tags, aliases
        )
        changed = True
    return changed


def catalog_paths(manifest_path: Path) -> list[Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [ROOT / relative for relative in manifest["full_datasets"]]


def sample_path(manifest_path: Path) -> Path:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return ROOT / manifest["sample_dataset"]


def rebuild_sample(
    paths: Iterable[Path],
    output: Path,
    required_product_ids: set[int],
) -> None:
    candidates: dict[str, list[dict[str, str]]] = defaultdict(list)
    required: dict[int, dict[str, str]] = {}
    fieldnames: list[str] | None = None
    for path in paths:
        with gzip.open(path, "rt", newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames is None:
                raise RuntimeError(f"{path} has no header")
            fieldnames = reader.fieldnames
            for row in reader:
                domain = row["domain"]
                product_id = int(row["product_id"])
                if product_id in required_product_ids:
                    required[product_id] = row
                if len(candidates[domain]) < DOMAIN_SAMPLE_TARGETS[domain]:
                    candidates[domain].append(row)
    missing = required_product_ids - set(required)
    if missing:
        raise RuntimeError(f"Required sample product IDs not found: {sorted(missing)}")
    if fieldnames is None:
        raise RuntimeError("No catalog rows were available for the sample")

    rows: list[dict[str, str]] = []
    for domain, target in DOMAIN_SAMPLE_TARGETS.items():
        domain_required = sorted(
            (row for row in required.values() if row["domain"] == domain),
            key=lambda row: int(row["product_id"]),
        )
        selected = list(domain_required)
        selected_ids = {int(row["product_id"]) for row in selected}
        selected.extend(
            row
            for row in candidates[domain]
            if int(row["product_id"]) not in selected_ids
        )
        if len(selected) < target:
            raise RuntimeError(
                f"Only {len(selected)} sample rows available for {domain}; "
                f"expected {target}"
            )
        rows.extend(selected[:target])

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    with gzip.open(
        temporary,
        "wt",
        newline="",
        encoding="utf-8",
        compresslevel=6,
    ) as target:
        writer = csv.DictWriter(
            target,
            fieldnames=fieldnames,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, output)
    print(
        f"Rebuilt {output.relative_to(ROOT)}: {len(rows):,} balanced rows, "
        f"{len(required):,} required demonstration products"
    )


def prepare_path(
    path: Path,
    overrides: dict[int, dict[str, Any]],
) -> tuple[int, int, set[int]]:
    temp_path = path.with_name(path.name + ".tmp")
    rows = 0
    repairs = 0
    seen: set[int] = set()
    with (
        gzip.open(path, "rt", newline="", encoding="utf-8") as source,
        gzip.open(
            temp_path,
            "wt",
            newline="",
            encoding="utf-8",
            compresslevel=6,
        ) as target,
    ):
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise RuntimeError(f"{path} has no header")
        writer = csv.DictWriter(
            target, fieldnames=reader.fieldnames, lineterminator="\n"
        )
        writer.writeheader()
        for row in reader:
            rows += 1
            repairs += patch_known_quality_edges(row)
            product_id = int(row["product_id"])
            if product_id in overrides:
                apply_curated_override(row, overrides[product_id])
                seen.add(product_id)
            writer.writerow(row)
    os.replace(temp_path, path)
    return rows, repairs, seen


def prepare_paths(
    paths: Iterable[Path],
    overrides: dict[int, dict[str, Any]],
) -> tuple[int, int, set[int]]:
    rows = 0
    repairs = 0
    seen: set[int] = set()
    for path in paths:
        path_rows, path_repairs, path_seen = prepare_path(path, overrides)
        rows += path_rows
        repairs += path_repairs
        seen.update(path_seen)
        print(
            f"Prepared {path.relative_to(ROOT)}: {path_rows:,} rows, "
            f"{path_repairs:,} quality repairs, {len(path_seen):,} overrides"
        )
    return rows, repairs, seen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--catalog", type=Path, action="append")
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    parser.add_argument("--skip-overrides", action="store_true")
    parser.add_argument("--allow-missing-overrides", action="store_true")
    parser.add_argument("--sample-output", type=Path)
    parser.add_argument("--skip-sample", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    override_rows = (
        []
        if args.skip_overrides
        else json.loads(args.overrides.read_text(encoding="utf-8"))
    )
    overrides = {int(item["product_id"]): item for item in override_rows}
    paths = args.catalog or catalog_paths(args.manifest)
    rows, repairs, seen = prepare_paths(paths, overrides)
    missing = set(overrides) - seen
    if missing and not args.allow_missing_overrides:
        raise RuntimeError(f"Override product IDs not found: {sorted(missing)}")
    if not args.skip_sample:
        rebuild_sample(
            paths,
            args.sample_output or sample_path(args.manifest),
            set(overrides),
        )
    print(
        f"Prepared {rows:,} rows; quality repairs={repairs:,}; "
        f"curated overrides={len(seen):,}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
