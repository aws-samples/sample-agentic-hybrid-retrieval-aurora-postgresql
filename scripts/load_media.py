#!/usr/bin/env python3
"""Load governed local product media into catalog.product_media."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAPPING = ROOT / "data" / "full" / "product_image_urls.csv.gz"
DEFAULT_CURATED_MANIFEST = ROOT / "data" / "curated" / "image_manifest.json"
DEFAULT_PUBLIC_DIR = ROOT / "ui" / "public"


@dataclass(frozen=True)
class MediaRecord:
    product_id: int
    role: str
    sort_order: int
    image_url: str
    image_source: str
    image_key: str
    alt_text: str
    asset_sha256: str
    publication_status: str = "approved"

    def copy_row(self) -> tuple[object, ...]:
        return (
            self.product_id,
            self.role,
            self.sort_order,
            self.image_url,
            self.image_source,
            self.image_key,
            self.alt_text,
            self.asset_sha256,
            self.publication_status,
        )


def normalize_asset_url(value: str) -> str:
    """Return a root-relative URL under the checked-in runtime media tree."""
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


def _copy_records(copy, records: Iterator[MediaRecord], chunk_bytes: int) -> int:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    count = 0
    for record in records:
        writer.writerow(record.copy_row())
        count += 1
        if buffer.tell() >= chunk_bytes:
            copy.write(buffer.getvalue())
            buffer.seek(0)
            buffer.truncate(0)
    if buffer.tell():
        copy.write(buffer.getvalue())
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument(
        "--curated-manifest",
        type=Path,
        default=DEFAULT_CURATED_MANIFEST,
    )
    parser.add_argument("--public-dir", type=Path, default=DEFAULT_PUBLIC_DIR)
    parser.add_argument("--chunk-bytes", type=int, default=4 * 1024 * 1024)
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL required")
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("Install config/requirements.txt") from exc

    copy_sql = """
        COPY catalog_stage.product_media_raw (
            product_id, role, sort_order, image_url, image_source, image_key,
            alt_text, asset_sha256, publication_status
        ) FROM STDIN WITH (FORMAT CSV)
    """
    upsert_sql = """
        INSERT INTO catalog.product_media (
            product_id, role, sort_order, image_url, image_source, image_key,
            alt_text, asset_sha256, publication_status
        )
        SELECT
            raw.product_id::bigint,
            raw.role,
            raw.sort_order::smallint,
            raw.image_url,
            raw.image_source,
            nullif(raw.image_key, ''),
            coalesce(nullif(raw.alt_text, ''), product.title || ' product image'),
            nullif(raw.asset_sha256, ''),
            raw.publication_status
        FROM catalog_stage.product_media_raw raw
        JOIN catalog.product product
          ON product.product_id = raw.product_id::bigint
        ON CONFLICT (product_id, role, sort_order) DO UPDATE SET
            image_url = EXCLUDED.image_url,
            image_source = EXCLUDED.image_source,
            image_key = EXCLUDED.image_key,
            alt_text = EXCLUDED.alt_text,
            asset_sha256 = EXCLUDED.asset_sha256,
            publication_status = EXCLUDED.publication_status
    """

    with psycopg.connect(args.database_url) as connection:
        connection.execute("TRUNCATE catalog_stage.product_media_raw")
        with connection.cursor().copy(copy_sql) as copy:
            copied = _copy_records(
                copy,
                iter_media_records(
                    args.mapping,
                    args.curated_manifest,
                    args.public_dir,
                ),
                args.chunk_bytes,
            )
        staged = connection.execute(
            "SELECT count(*) FROM catalog_stage.product_media_raw"
        ).fetchone()[0]
        if staged != copied:
            raise RuntimeError(f"Staged {staged} media rows after copying {copied}")
        connection.execute(
            """
            DELETE FROM catalog.product_media
            WHERE image_source IN (
                'category_fallback',
                'curated_photorealistic',
                'curated_gallery',
                'mosaic_showcase'
            )
            """
        )
        connection.execute(upsert_sql)
        loaded = connection.execute(
            """
            SELECT count(*)
            FROM catalog.product_media
            WHERE publication_status = 'approved'
              AND image_source IN (
                  'category_fallback',
                  'curated_photorealistic',
                  'curated_gallery',
                  'mosaic_showcase'
              )
            """
        ).fetchone()[0]
        if loaded != staged:
            raise RuntimeError(
                f"Loaded {loaded} approved media rows from {staged} staged rows; "
                "load the complete catalog before media"
            )
        counts = connection.execute(
            """
            SELECT image_source, role, count(*)
            FROM catalog.product_media
            WHERE publication_status = 'approved'
            GROUP BY image_source, role
            ORDER BY image_source, role
            """
        ).fetchall()
        connection.commit()
    print(f"Loaded {loaded} approved product-media rows: {counts}")


if __name__ == "__main__":
    main()
