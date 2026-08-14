#!/usr/bin/env python3
"""Emit the outstanding image backlog as a working shot list.

Reads `data/media/asset_labels_120.json`, subtracts what is already installed,
and writes a CSV plus a grouped Markdown checklist. The Markdown is ordered by
domain then subcategory so a generation session can work straight down it, and
each row carries the exact output filename the app expects.

Usage
-----
    uv run python scripts/build_shot_list.py
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LABELS = REPO / "data" / "media" / "asset_labels_120.json"
RUNTIME = REPO / "ui" / "public" / "assets" / "images" / "mosaic"
OUT_CSV = REPO / "data" / "media" / "shot_list_outstanding.csv"
OUT_MD = REPO / "docs" / "media-shot-list.md"

DOMAIN_LABEL = {
    "consumer_electronics": "Consumer electronics",
    "running_fitness": "Running and fitness",
    "home_office": "Home office and workspace",
}
DOMAIN_PREFIX = {
    "consumer_electronics": "CE",
    "running_fitness": "RF",
    "home_office": "HO",
}

# The whole cohort is one photographic set; these are the constants a generation
# prompt has to repeat so 120 images look like one catalog.
SET_DIRECTION = (
    "Warm travertine and cream plaster set, soft directional daylight with leafy "
    "shadow play, muted sand and bone palette with a single deep maroon accent, "
    "product centred and sharp, shallow depth of field, no text or logos."
)


def main() -> int:
    payload = json.loads(LABELS.read_text())
    rows = payload["products"]
    have = {path.stem for path in RUNTIME.glob("*.webp")} if RUNTIME.is_dir() else set()

    outstanding = []
    for row in rows:
        for role, runtime, size in (
            (
                "catalog-3x2",
                row["catalog_runtime"],
                "1800x1200 master / 1200x800 runtime",
            ),
            (
                "detail-1x1",
                row["detail_runtime"],
                "1600x1600 master / 1200x1200 runtime",
            ),
        ):
            if not runtime or runtime[:-5] in have:
                continue
            outstanding.append(
                {
                    "product_id": row["product_id"],
                    "asset_id": row["asset_id"],
                    "domain": row["domain"],
                    "category": row["category"],
                    "subcategory": row["subcategory"],
                    "merchandising_title": row["merchandising_title"],
                    "source_title": row["source_title"],
                    "role": role,
                    "output_filename": runtime,
                    "size": (
                        "1536x1024 master / 1200x800 runtime"
                        if role == "catalog-3x2"
                        else "1024x1024 master / 1200x1200 runtime"
                    ),
                    "shop_page": row["shop_page"],
                    "is_retrieval_anchor": row["is_retrieval_anchor"],
                }
            )

    batch_sequence: dict[str, int] = defaultdict(int)
    for item in sorted(
        outstanding,
        key=lambda row: (
            row["domain"],
            row["category"],
            row["subcategory"],
            row["asset_id"],
        ),
    ):
        sequence = batch_sequence[item["domain"]]
        item["generation_batch"] = (
            f"{DOMAIN_PREFIX[item['domain']]}-B{sequence // 10 + 1:02d}"
        )
        batch_sequence[item["domain"]] += 1

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(outstanding[0]) if outstanding else ["product_id"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(outstanding)

    grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for item in outstanding:
        grouped[item["domain"]][item["subcategory"]].append(item)

    anchors = [item for item in outstanding if item["is_retrieval_anchor"]]
    lines = [
        "# Mosaic premium cohort — outstanding image shot list",
        "",
        (
            f"**{len(outstanding)} images to generate** across "
            f"{len({item['product_id'] for item in outstanding})} products. "
            "The 120-product cohort is fixed by the schema package; this is the "
            "subset whose runtime file is not yet installed."
        ),
        "",
        "## Exact domain count",
        "",
        "| Domain | Cohort | Installed | Outstanding | ChatGPT batches |",
        "|---|---:|---:|---:|---:|",
    ]
    all_rows = payload["products"]
    for domain in ("consumer_electronics", "running_fitness", "home_office"):
        cohort_count = sum(row["domain"] == domain for row in all_rows)
        outstanding_count = sum(row["domain"] == domain for row in outstanding)
        installed_count = cohort_count - outstanding_count
        batches = (outstanding_count + 9) // 10
        lines.append(
            f"| {DOMAIN_LABEL[domain]} | {cohort_count} | {installed_count} "
            f"| {outstanding_count} | {batches} |"
        )
    lines += [
        "",
        "Generate no more than 10 images per ChatGPT batch. Use the stable",
        "`Asset ID` in the prompt title and save the download under the exact",
        "`Output filename`; the importer will reject any other name.",
        "",
        f"## Priority: the {len(anchors)} retrieval anchors first",
        "",
        "Anchors back the workshop's scripted queries and the graded relevance",
        "judgments, so they appear on screen during the session. Generate these",
        f"{len(anchors)} before the remaining {len(outstanding) - len(anchors)}.",
        "",
        "| Asset ID | Subject | Output filename |",
        "|---|---|---|",
        *[
            f"| `{item['asset_id']}` | {item['source_title']} "
            f"| `{item['output_filename']}` |"
            for item in sorted(anchors, key=lambda row: row["output_filename"])
        ],
        "",
        "## Set direction (keep constant across every shot)",
        "",
        f"> {SET_DIRECTION}",
        "",
        "Anchors are used by the workshop's scripted queries and relevance",
        "judgments, so their photographs carry the most weight.",
        "",
        "## Output contract",
        "",
        "| Role | Master | Runtime | Used by |",
        "|---|---|---|---|",
        "| `catalog-3x2` | 1536x1024 PNG | 1200x800 WebP | catalog grid, rail, related |",
        "| `detail-1x1` | 1024x1024 PNG | 1200x1200 WebP | product page hero (flagships only) |",
        "",
        "Save runtime files to `ui/public/assets/images/mosaic/` using the exact",
        "filename in the tables below.",
        "",
    ]

    for domain in ("consumer_electronics", "running_fitness", "home_office"):
        if domain not in grouped:
            continue
        count = sum(len(items) for items in grouped[domain].values())
        lines += [f"## {DOMAIN_LABEL[domain]} ({count})", ""]
        for subcategory in sorted(grouped[domain]):
            items = grouped[domain][subcategory]
            lines += [
                f"### {subcategory}",
                "",
                "| Asset ID | Batch | Product | Subject | Output filename | Anchor |",
                "|---|---|---|---|---|---|",
            ]
            for item in sorted(items, key=lambda row: row["output_filename"]):
                anchor = "yes" if item["is_retrieval_anchor"] else ""
                lines.append(
                    f"| `{item['asset_id']}` | `{item['generation_batch']}` "
                    f"| {item['merchandising_title']} | {item['source_title']} "
                    f"| `{item['output_filename']}` | {anchor} |"
                )
            lines.append("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines))

    print(f"{len(outstanding)} outstanding images")
    print(f"wrote {OUT_CSV.relative_to(REPO)}")
    print(f"wrote {OUT_MD.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
