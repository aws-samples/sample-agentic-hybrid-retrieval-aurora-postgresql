#!/usr/bin/env python3
"""Convert generated PNGs into runtime WebP assets under their cohort keys.

Drop a batch of generated images into a folder, name each one after its cohort
asset key (or the product's asset stem), and this crops to the role's aspect
ratio, resizes to the runtime dimensions, and writes WebP.

A file whose name is not in `data/media/asset_labels_200.json` (product-bound
cohort photography) or `data/media/category_plates.json` (category-representative
filler photography) is refused rather than guessed at: an unrecognised name means
either a typo or an image nobody asked for, and silently accepting it is how a
folder stops matching its manifest.

Usage
-----
    uv run python scripts/import_generated_images.py --source ~/Downloads/batch
    uv run python scripts/import_generated_images.py --source ~/Downloads/batch --dry-run
    uv run python scripts/import_generated_images.py --source ~/Downloads --hero
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LABELS = REPO / "data" / "media" / "asset_labels_200.json"
PLATES = REPO / "data" / "media" / "category_plates.json"
RUNTIME = REPO / "ui" / "public" / "assets" / "images" / "mosaic"
HERO_NAME = "hero-landing-scene.webp"

# role -> (aspect ratio, runtime pixel size)
ROLE_SPEC = {
    "catalog-3x2": (3 / 2, (1200, 800)),
    "detail-1x1": (1.0, (1200, 1200)),
}
# The hero frame is 770x938 CSS; at DPR 2 that is 1540x1876 device pixels.
HERO_SPEC = (770 / 938, (1568, 1908))
QUALITY = 88


def crop_to(image, ratio: float):
    """Centre-crop to an aspect ratio. Never distorts the subject."""
    width, height = image.size
    if width / height > ratio:
        new_width = round(height * ratio)
        left = (width - new_width) // 2
        return image.crop((left, 0, left + new_width, height))
    new_height = round(width / ratio)
    top = (height - new_height) // 2
    return image.crop((0, top, width, top + new_height))


def role_of(stem: str) -> str | None:
    for role in ROLE_SPEC:
        if stem.endswith(f"-{role}"):
            return role
    return None


def record_installed_plates(stems: set[str]) -> int:
    """Mark imported plates installed in the manifest and stamp their digest.

    `ui/src/media.ts` serves only plates whose `installed` flag is true, so a
    plate that is generated and imported but not recorded here never reaches a
    card. The digest is of the runtime WebP, which is what the browser fetches;
    a digest of the source PNG would not detect a re-import at a new quality.
    """
    spec = json.loads(PLATES.read_text())
    updated = 0
    for plate in spec["plates"] + spec["domain_neutral_plates"]:
        stem = f"{plate['plate_id']}-catalog-3x2"
        if stem not in stems:
            continue
        digest = hashlib.sha256((RUNTIME / f"{stem}.webp").read_bytes()).hexdigest()
        if plate["installed"] and plate["sha256"] == digest:
            continue
        plate["installed"] = True
        plate["sha256"] = digest
        updated += 1
    if updated:
        PLATES.write_text(json.dumps(spec, indent=2) + "\n")
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--hero",
        action="store_true",
        help="Treat the newest image in --source as the landing hero",
    )
    args = parser.parse_args()

    try:
        from PIL import Image
    except ImportError:
        print("FAIL: Pillow is required (pip install pillow)", file=sys.stderr)
        return 1

    if not args.source.is_dir():
        print(f"FAIL: not a directory: {args.source}", file=sys.stderr)
        return 1

    candidates = sorted(
        [
            p
            for p in args.source.iterdir()
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ]
    )
    if not candidates:
        print(f"FAIL: no images found in {args.source}", file=sys.stderr)
        return 1

    if args.hero:
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        ratio, size = HERO_SPEC
        print(f"hero source: {newest.name}")
        with Image.open(newest) as image:
            if image.width > image.height:
                print(
                    "WARNING: hero source is landscape but the frame is portrait; "
                    "most of the image will be cropped away",
                    file=sys.stderr,
                )
            if not args.dry_run:
                out = crop_to(image.convert("RGB"), ratio).resize(size, Image.LANCZOS)
                out.save(RUNTIME / HERO_NAME, "WEBP", quality=QUALITY, method=6)
        verb = "would write" if args.dry_run else "wrote"
        print(f"{verb} {HERO_NAME} at {size[0]}x{size[1]}")
        return 0

    cohort = json.loads(LABELS.read_text())["products"]
    known = {row["catalog_asset_key"] for row in cohort}
    known |= {row["detail_asset_key"] for row in cohort if row["detail_asset_key"]}
    # Category plates are the second manifest: filler photography for corpus rows
    # that have no product-bound plate. Same crop, resize and quality path, so a
    # plate and a cohort card are indistinguishable in sharpness. The three
    # domain-neutral still-lifes live in their own array and are imported the same
    # way, so both arrays are accepted here.
    plate_spec = json.loads(PLATES.read_text())
    known |= {
        f"{plate['plate_id']}-catalog-3x2"
        for plate in plate_spec["plates"] + plate_spec["domain_neutral_plates"]
    }

    written, refused, imported_stems = 0, [], set()
    for path in candidates:
        stem = path.stem
        role = role_of(stem)
        if role is None or stem not in known:
            refused.append(path.name)
            continue
        ratio, size = ROLE_SPEC[role]
        if not args.dry_run:
            with Image.open(path) as image:
                out = crop_to(image.convert("RGB"), ratio).resize(size, Image.LANCZOS)
                out.save(RUNTIME / f"{stem}.webp", "WEBP", quality=QUALITY, method=6)
            imported_stems.add(stem)
        verb = "would write" if args.dry_run else "wrote"
        print(f"{verb} {stem}.webp  ({size[0]}x{size[1]})")
        written += 1

    if imported_stems:
        recorded = record_installed_plates(imported_stems)
        if recorded:
            print(f"marked {recorded} plate(s) installed in {PLATES.name}")

    if refused:
        print(
            f"\nrefused {len(refused)} file(s) not in either manifest:", file=sys.stderr
        )
        for name in refused:
            print(f"  {name}", file=sys.stderr)
        print(
            "Rename them to a key from docs/media-shot-list.md or a plate id from "
            "docs/image-prompts-category-plates.md.",
            file=sys.stderr,
        )

    print(f"\n{written} runtime file(s) imported")
    return 1 if refused and not written else 0


if __name__ == "__main__":
    raise SystemExit(main())
