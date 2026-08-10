#!/usr/bin/env python3
"""Enumerate the governed local media the runtime serves, with hashes.

Extracted from `scripts/load_media.py` in Phase 2 Unit E. That script wrote to
`catalog.product_media`, which no longer exists, and was deleted — but two of its
parts never touched the database and are still the only implementation of a real
rule: **a mapped asset must exist on disk, live under `assets/images`, and be
content-addressed by SHA-256.**

Deleting them with the loader would have lost that coverage
(`tests/test_media_assets.py` asserts 500,007 records and their digests), so they
are preserved here as a pure enumeration over the checked-in files. Loading media
into `mosaic.product_media` is `db/sql/04_media.sql` and
`db/sql/15_load_premium_cohort.sql`, applied by `make db-load-cohort`.

Nothing here connects to a database.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAPPING = ROOT / "data" / "full" / "product_image_urls.csv.gz"
DEFAULT_CURATED_MANIFEST = ROOT / "data" / "curated" / "image_manifest.json"
DEFAULT_PUBLIC_DIR = ROOT / "ui" / "public"


@dataclass(frozen=True)
class MediaRecord:
    """One publishable asset reference, content-addressed."""

    product_id: int
    role: str
    sort_order: int
    image_url: str
    image_source: str
    image_key: str
    alt_text: str
    asset_sha256: str
    publication_status: str = "approved"


def normalize_asset_url(value: str) -> str:
    """Return a root-relative URL under the checked-in runtime media tree.

    Raises:
        ValueError: the path escapes the tree or is not under `assets/images`.
    """
    normalized = value.strip().split("?", 1)[0].lstrip("/")
    if normalized.startswith("ui/"):
        normalized = normalized.removeprefix("ui/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe media path: {value}")
    if path.parts[:2] != ("assets", "images"):
        raise ValueError(f"Media path must be under assets/images: {value}")
    return "/" + path.as_posix()


def _asset_digest(image_url: str, public_dir: Path, cache: dict[str, str]) -> str:
    """SHA-256 of the file the URL resolves to.

    Raises:
        FileNotFoundError: the mapping references an asset that is not on disk.
            This is the check that catches a retired photograph still being
            mapped — the dev server answers a missing asset with `index.html` and
            a 200, so the product grid renders empty boxes and nothing else fails.
    """
    if image_url in cache:
        return cache[image_url]
    path = public_dir / image_url.lstrip("/")
    if not path.is_file():
        raise FileNotFoundError(f"Mapped media asset does not exist: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    cache[image_url] = digest
    return digest


def iter_media_records(
    mapping_path: Path = DEFAULT_MAPPING,
    curated_manifest_path: Path = DEFAULT_CURATED_MANIFEST,
    public_dir: Path = DEFAULT_PUBLIC_DIR,
) -> Iterator[MediaRecord]:
    """Yield every primary, gallery, and detail asset reference, in that order."""
    digest_cache: dict[str, str] = {}
    with gzip.open(mapping_path, "rt", encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            image_url = normalize_asset_url(row["image_url"])
            yield MediaRecord(
                product_id=int(row["product_id"]),
                role="primary",
                sort_order=0,
                image_url=image_url,
                image_source=row["image_source"],
                image_key=row["image_key"],
                alt_text="",
                asset_sha256=_asset_digest(image_url, public_dir, digest_cache),
            )

    curated = json.loads(curated_manifest_path.read_text(encoding="utf-8"))
    for product_id, item in sorted(curated.items(), key=lambda entry: int(entry[0])):
        if detail_path := item.get("detail_path"):
            image_url = normalize_asset_url(detail_path)
            yield MediaRecord(
                product_id=int(product_id),
                role="detail",
                sort_order=0,
                image_url=image_url,
                image_source="curated_gallery",
                image_key=Path(image_url).name,
                alt_text="",
                asset_sha256=_asset_digest(image_url, public_dir, digest_cache),
            )
        for sort_order, gallery_path in enumerate(item.get("gallery_paths", [])):
            image_url = normalize_asset_url(gallery_path)
            yield MediaRecord(
                product_id=int(product_id),
                role="gallery",
                sort_order=sort_order,
                image_url=image_url,
                image_source="curated_gallery",
                image_key=Path(image_url).name,
                alt_text="",
                asset_sha256=_asset_digest(image_url, public_dir, digest_cache),
            )
