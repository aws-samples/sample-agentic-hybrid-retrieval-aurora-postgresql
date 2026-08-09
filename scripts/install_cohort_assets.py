#!/usr/bin/env python3
"""Install already-generated photographs under their cohort asset keys.

Six of the 120 premium products are flagships whose photographs already exist,
but they were installed under ad-hoc names (`auraluxe-h9.webp`,
`forma-ergonomic-studio.webp`) before the cohort defined asset keys. This copies
them to the scheme in `data/media/asset_labels_120.json` so the runtime folder
matches the manifest and the "still to generate" count is truthful.

Source images stay in place; nothing is deleted. The 3:2 catalog crop is taken
from the widest available render, and the 1:1 detail crop from the squarest, so
neither role is produced by stretching.

Usage
-----
    python scripts/install_cohort_assets.py --dry-run
    python scripts/install_cohort_assets.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LABELS = REPO / "data" / "media" / "asset_labels_120.json"
RUNTIME = REPO / "ui" / "public" / "assets" / "images" / "mosaic"

# product_id -> (preferred source for the 3:2 catalog crop,
#                preferred source for the 1:1 detail crop)
# Chosen by eye from the installed renders: the "-scene" files are landscape
# room shots that survive a 3:2 crop; the square studio files suit 1:1.
FLAGSHIP_SOURCES: dict[int, tuple[str, str]] = {
    1: ("auraluxe-h9-scene.webp", "auraluxe-h9-studio.webp"),
    17001: ("echobud-s2-scene.webp", "echobud-s2-studio.webp"),
    116001: ("pulse-one-scene.webp", "pulse-one-studio.webp"),
    234001: ("stride-pro-scene.webp", "stride-pro-studio.webp"),
    370001: ("forma-ergonomic-scene.webp", "forma-ergonomic-studio.webp"),
    420001: ("atelier-32-scene.webp", "atelier-32-studio.webp"),
}

CATALOG_SIZE = (1200, 800)  # 3:2 runtime
DETAIL_SIZE = (1200, 1200)  # 1:1 runtime


def crop_to(image, ratio: float):
    """Centre-crop to an aspect ratio without distorting the subject."""
    width, height = image.size
    if width / height > ratio:
        new_width = round(height * ratio)
        left = (width - new_width) // 2
        return image.crop((left, 0, left + new_width, height))
    new_height = round(width / ratio)
    top = (height - new_height) // 2
    return image.crop((0, top, width, top + new_height))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        from PIL import Image
    except ImportError:
        print("FAIL: Pillow is required (pip install pillow)", file=sys.stderr)
        return 1

    labels = json.loads(LABELS.read_text())["products"]
    by_id = {row["product_id"]: row for row in labels}

    planned: list[tuple[Path, str, tuple[int, int]]] = []
    for product_id, (catalog_src, detail_src) in FLAGSHIP_SOURCES.items():
        row = by_id[product_id]
        planned.append((RUNTIME / catalog_src, row["catalog_runtime"], CATALOG_SIZE))
        if row["detail_runtime"]:
            planned.append((RUNTIME / detail_src, row["detail_runtime"], DETAIL_SIZE))

    missing = [src for src, _, _ in planned if not src.exists()]
    if missing:
        for src in missing:
            print(f"FAIL: missing source {src.name}", file=sys.stderr)
        return 1

    for src, target_name, size in planned:
        ratio = size[0] / size[1]
        action = "would write" if args.dry_run else "wrote"
        if not args.dry_run:
            with Image.open(src) as image:
                out = crop_to(image.convert("RGB"), ratio).resize(size, Image.LANCZOS)
                out.save(RUNTIME / target_name, "WEBP", quality=88, method=6)
        print(f"{action} {target_name:<62} from {src.name}")

    print(f"\n{len(planned)} runtime files for 6 flagship products")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
