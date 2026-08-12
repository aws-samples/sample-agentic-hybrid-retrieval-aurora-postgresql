#!/usr/bin/env python3
"""Export and restore content-addressed Mosaic product embeddings."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
from typing import Any

import numpy as np

COHERE_EMBED_V4_MODEL_ID = "us.cohere.embed-v4:0"
COHERE_EMBED_V4_DIMENSIONS = 1024
DEFAULT_PRODUCT_COUNT = 500_000
DEFAULT_CONTRACT = (
    Path(__file__).resolve().parents[1] / "db" / "config" / "embedding-cache.json"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported embedding cache schema_version")
    if manifest.get("dtype") != "float32":
        raise ValueError("embedding cache must contain float32 vectors")
    shards = manifest.get("shards")
    if not isinstance(shards, list) or not shards:
        raise ValueError("embedding cache manifest must contain shards")
    seen_paths: set[str] = set()
    vector_count = 0
    previous_last_product_id: int | None = None
    for shard in shards:
        try:
            shard_path = str(shard["path"])
            count = int(shard["count"])
            first_product_id = int(shard["first_product_id"])
            last_product_id = int(shard["last_product_id"])
            checksum = str(shard["sha256"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("embedding cache shard metadata is invalid") from error
        if Path(shard_path).name != shard_path or shard_path in seen_paths:
            raise ValueError("embedding cache shard paths must be unique basenames")
        if count <= 0 or last_product_id - first_product_id + 1 != count:
            raise ValueError("embedding cache shard product range is invalid")
        if (
            previous_last_product_id is not None
            and first_product_id != previous_last_product_id + 1
        ):
            raise ValueError("embedding cache shard product ranges are not contiguous")
        if len(checksum) != 64:
            raise ValueError("embedding cache shard checksum is invalid")
        seen_paths.add(shard_path)
        vector_count += count
        previous_last_product_id = last_product_id
    if vector_count != int(manifest.get("vector_count", -1)):
        raise ValueError("embedding cache vector_count does not match its shards")
    if len(str(manifest.get("catalog_content_digest", ""))) != 64:
        raise ValueError("embedding cache catalog digest is invalid")
    return manifest


def load_contract(path: Path) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "manifest_sha256",
        "embedding_model_id",
        "dimensions",
        "vector_count",
        "shard_count",
    }
    missing = sorted(required - set(contract))
    if missing:
        raise ValueError(f"embedding cache contract is missing {missing}")
    if len(str(contract["manifest_sha256"])) != 64:
        raise ValueError("embedding cache contract manifest_sha256 is invalid")
    return contract


def verify_cache(
    manifest_path: Path,
    contract_path: Path = DEFAULT_CONTRACT,
) -> dict[str, Any]:
    """Verify the pinned workshop cache without connecting to a database."""
    manifest_path = manifest_path.resolve()
    contract = load_contract(contract_path.resolve())
    manifest_hash = file_sha256(manifest_path)
    if manifest_hash != contract["manifest_sha256"]:
        raise ValueError(
            "embedding cache manifest checksum mismatch: "
            f"found {manifest_hash}, expected {contract['manifest_sha256']}; "
            "download the pinned DAT410 asset release"
        )

    manifest = load_manifest(manifest_path)
    comparisons = {
        "schema_version": manifest["schema_version"],
        "embedding_model_id": manifest.get("embedding_model_id"),
        "dimensions": manifest.get("dimensions"),
        "vector_count": manifest.get("vector_count"),
        "shard_count": len(manifest["shards"]),
    }
    for field, found in comparisons.items():
        expected = contract[field]
        if found != expected:
            raise ValueError(
                f"embedding cache {field} mismatch: found {found!r}, "
                f"expected {expected!r}; download the pinned DAT410 asset release"
            )

    declared = {str(shard["path"]) for shard in manifest["shards"]}
    installed = {path.name for path in manifest_path.parent.glob("embeddings-*.npz")}
    if installed != declared:
        missing = sorted(declared - installed)
        unexpected = sorted(installed - declared)
        raise ValueError(
            "embedding cache shard set mismatch: "
            f"missing={missing}, unexpected={unexpected}; "
            "re-run make db-fetch-embeddings"
        )

    catalog_digest = hashlib.sha256()
    verified = 0
    dimensions = int(contract["dimensions"])
    for shard in manifest["shards"]:
        path = manifest_path.parent / shard["path"]
        product_ids, content_hashes, _ = validate_shard(path, shard, dimensions)
        catalog_digest.update(catalog_records(product_ids, content_hashes))
        verified += int(shard["count"])

    actual_catalog_digest = catalog_digest.hexdigest()
    if actual_catalog_digest != manifest["catalog_content_digest"]:
        raise ValueError(
            "embedding cache catalog digest mismatch: "
            f"found {actual_catalog_digest}, "
            f"expected {manifest['catalog_content_digest']}; "
            "replace the incomplete or mixed cache release"
        )
    print(
        "Verified DAT410 embedding cache: "
        f"{verified:,} vectors, {len(manifest['shards'])} shards, "
        f"model={manifest['embedding_model_id']}"
    )
    return manifest


def vector_float32(value: Any) -> np.ndarray:
    if hasattr(value, "to_numpy"):
        value = value.to_numpy()
    return np.asarray(value, dtype=np.float32)


def vector_binary_sha256(value: Any) -> str:
    """Match pgvector's binary representation for legacy shard verification."""
    vector = vector_float32(value)
    payload = struct.pack(">hh", len(vector), 0) + vector.astype(">f4").tobytes()
    return hashlib.sha256(payload).hexdigest()


def catalog_records(
    product_ids: np.ndarray,
    content_hashes: np.ndarray,
) -> bytes:
    records = bytearray()
    for product_id, content_hash in zip(product_ids, content_hashes):
        records.extend(struct.pack(">q", int(product_id)))
        records.extend(bytes(content_hash))
    return bytes(records)


def validate_shard(
    path: Path,
    shard: dict[str, Any],
    dimensions: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if file_sha256(path) != shard["sha256"]:
        raise ValueError(f"embedding cache checksum mismatch: {path}")
    with np.load(path, allow_pickle=False) as payload:
        product_ids = payload["product_ids"]
        content_hashes = payload["content_hashes"]
        embeddings = payload["embeddings"]
    expected_count = int(shard["count"])
    if product_ids.shape != (expected_count,):
        raise ValueError(f"invalid product_ids shape in {path}")
    if product_ids.dtype != np.int64:
        raise ValueError(f"invalid product_ids dtype in {path}")
    if content_hashes.shape != (expected_count,):
        raise ValueError(f"invalid content_hashes shape in {path}")
    if content_hashes.dtype != np.dtype("S64"):
        raise ValueError(f"invalid content_hashes dtype in {path}")
    if embeddings.shape != (expected_count, dimensions):
        raise ValueError(f"invalid embeddings shape in {path}")
    if embeddings.dtype != np.float32:
        raise ValueError(f"invalid embedding dtype in {path}")
    if "first_product_id" in shard and int(product_ids[0]) != int(
        shard["first_product_id"]
    ):
        raise ValueError(f"invalid first product ID in {path}")
    if "last_product_id" in shard and int(product_ids[-1]) != int(
        shard["last_product_id"]
    ):
        raise ValueError(f"invalid last product ID in {path}")
    if expected_count > 1 and not np.all(np.diff(product_ids) == 1):
        raise ValueError(f"non-contiguous product IDs in {path}")
    if not np.isfinite(embeddings).all():
        raise ValueError(f"non-finite embedding in {path}")
    return product_ids, content_hashes, embeddings


def export_shard(
    *,
    database_url: str,
    output: Path,
    model_id: str,
    dimensions: int,
    shard_number: int,
    first_product_id: int,
    last_product_id: int,
    resume: bool,
) -> tuple[dict[str, Any], bytes, bool]:
    import psycopg
    from pgvector.psycopg import register_vector

    filename = f"embeddings-{shard_number:05d}.npz"
    path = output / filename
    with psycopg.connect(database_url) as connection:
        register_vector(connection)
        if resume and path.exists():
            with np.load(path, allow_pickle=False) as payload:
                product_ids = payload["product_ids"]
                content_hashes = payload["content_hashes"]
                embeddings = payload["embeddings"]
                cached_model_id = (
                    str(payload["embedding_model_id"].item())
                    if "embedding_model_id" in payload
                    else None
                )
            expected_count = last_product_id - first_product_id + 1
            expected_ids = np.arange(
                first_product_id,
                last_product_id + 1,
                dtype=np.int64,
            )
            if (
                product_ids.shape == (expected_count,)
                and np.array_equal(product_ids, expected_ids)
                and content_hashes.shape == (expected_count,)
                and embeddings.shape == (expected_count, dimensions)
                and embeddings.dtype == np.float32
                and cached_model_id in {None, model_id}
            ):
                include_vector_hash = cached_model_id is None
                hash_column = (
                    ", encode(digest(vector_send(d.embedding), 'sha256'), 'hex')"
                    if include_vector_hash
                    else ""
                )
                existing_rows = connection.execute(
                    f"""
                    SELECT d.product_id, p.content_hash {hash_column}
                    FROM mosaic_search.product_document d
                    JOIN mosaic.product p USING (product_id)
                    WHERE d.product_id BETWEEN %s AND %s
                      AND d.embedding IS NOT NULL
                      AND d.embedding_model_key = %s
                    ORDER BY d.product_id
                    """,
                    (first_product_id, last_product_id, model_id),
                ).fetchall()
                database_ids = np.asarray(
                    [row[0] for row in existing_rows],
                    dtype=np.int64,
                )
                database_hashes = np.asarray(
                    [row[1].encode("ascii") for row in existing_rows],
                    dtype="S64",
                )
                vectors_match = True
                if include_vector_hash:
                    vectors_match = all(
                        vector_binary_sha256(embedding) == row[2]
                        for embedding, row in zip(embeddings, existing_rows)
                    )
                if (
                    np.array_equal(product_ids, database_ids)
                    and np.array_equal(content_hashes, database_hashes)
                    and vectors_match
                ):
                    shard = {
                        "path": filename,
                        "count": expected_count,
                        "first_product_id": int(product_ids[0]),
                        "last_product_id": int(product_ids[-1]),
                        "sha256": file_sha256(path),
                        "size_bytes": path.stat().st_size,
                    }
                    return (
                        shard,
                        catalog_records(product_ids, content_hashes),
                        True,
                    )

        # A binary cursor avoids pgvector's much larger textual wire format.
        with connection.cursor(binary=True) as cursor:
            cursor.execute(
                """
                SELECT d.product_id, p.content_hash, d.embedding
                FROM mosaic_search.product_document d
                JOIN mosaic.product p USING (product_id)
                WHERE d.product_id BETWEEN %s AND %s
                  AND d.embedding IS NOT NULL
                  AND d.embedding_model_key = %s
                ORDER BY d.product_id
                """,
                (first_product_id, last_product_id, model_id),
            )
            rows = cursor.fetchall()

    expected_count = last_product_id - first_product_id + 1
    if len(rows) != expected_count:
        raise RuntimeError(
            f"shard {shard_number} expected {expected_count:,} vectors; "
            f"found {len(rows):,}"
        )
    product_ids = np.asarray([row[0] for row in rows], dtype=np.int64)
    content_hashes = np.asarray(
        [row[1].encode("ascii") for row in rows],
        dtype="S64",
    )
    embeddings = np.stack([vector_float32(row[2]) for row in rows])

    temporary_path = output / f".{filename}.tmp"
    with temporary_path.open("wb") as handle:
        np.savez(
            handle,
            product_ids=product_ids,
            content_hashes=content_hashes,
            embeddings=embeddings,
            embedding_model_id=np.asarray(model_id),
        )
    temporary_path.replace(path)
    shard = {
        "path": filename,
        "count": len(rows),
        "first_product_id": int(product_ids[0]),
        "last_product_id": int(product_ids[-1]),
        "sha256": file_sha256(path),
        "size_bytes": path.stat().st_size,
    }
    return shard, catalog_records(product_ids, content_hashes), False


def export_cache(args: argparse.Namespace) -> None:
    import psycopg

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    catalog_digest = hashlib.sha256()

    with psycopg.connect(args.database_url) as connection:
        total, ready, first_product_id, last_product_id = connection.execute(
            """
            SELECT
                count(*),
                count(*) FILTER (
                    WHERE embedding IS NOT NULL
                      AND embedding_model_key = %s
                ),
                min(product_id),
                max(product_id)
            FROM mosaic_search.product_document
            """,
            (args.model_id,),
        ).fetchone()
    if total != args.expected_count or ready != args.expected_count:
        raise RuntimeError(
            f"cache export requires {args.expected_count:,} ready vectors; "
            f"found total={total:,}, ready={ready:,}"
        )
    if last_product_id - first_product_id + 1 != args.expected_count:
        raise RuntimeError("parallel cache export requires contiguous product IDs")

    shard_specs = []
    for shard_number, start in enumerate(
        range(first_product_id, last_product_id + 1, args.shard_size),
        1,
    ):
        shard_specs.append(
            {
                "database_url": args.database_url,
                "output": output,
                "model_id": args.model_id,
                "dimensions": args.dimensions,
                "shard_number": shard_number,
                "first_product_id": start,
                "last_product_id": min(
                    start + args.shard_size - 1,
                    last_product_id,
                ),
                "resume": args.resume,
            }
        )

    shards: list[dict[str, Any]] = []
    vector_count = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(export_shard, **spec)
            for spec in shard_specs
        ]
        for future in futures:
            shard, records, reused = future.result()
            catalog_digest.update(records)
            shards.append(shard)
            vector_count += int(shard["count"])
            print(
                f"  {'reused' if reused else 'exported'} "
                f"{vector_count:,} vectors through {shard['path']}",
                flush=True,
            )

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "embedding_model_id": args.model_id,
        "dimensions": args.dimensions,
        "dtype": "float32",
        "vector_count": vector_count,
        "catalog_content_digest": catalog_digest.hexdigest(),
        "shards": shards,
    }
    manifest_path = output / "manifest.json"
    temporary_manifest = output / ".manifest.json.tmp"
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_manifest.replace(manifest_path)
    print(f"Wrote {manifest_path} with {vector_count:,} vectors")


def import_cache(args: argparse.Namespace) -> None:
    import psycopg
    from pgvector.psycopg import register_vector

    manifest_path = args.manifest.resolve()
    manifest = load_manifest(manifest_path)
    dimensions = int(manifest["dimensions"])
    if dimensions != COHERE_EMBED_V4_DIMENSIONS:
        raise RuntimeError(
            f"cache dimensions must be {COHERE_EMBED_V4_DIMENSIONS}; "
            f"found {dimensions}"
        )
    model_id = str(manifest["embedding_model_id"])
    if model_id != COHERE_EMBED_V4_MODEL_ID:
        raise RuntimeError(
            f"cache model must be {COHERE_EMBED_V4_MODEL_ID}; found {model_id}"
        )

    imported = 0
    with psycopg.connect(args.database_url) as connection:
        register_vector(connection)
        connection.execute(
            """
            UPDATE mosaic.embedding_model
            SET is_active = false
            WHERE is_active
              AND model_key <> %s
            """,
            (model_id,),
        )
        connection.execute(
            """
            INSERT INTO mosaic.embedding_model (
                model_key, provider, model_name, dimensions, distance_metric,
                is_active
            )
            VALUES (%s, 'bedrock', %s, %s, 'cosine', true)
            ON CONFLICT (model_key) DO UPDATE
            SET provider = EXCLUDED.provider,
                model_name = EXCLUDED.model_name,
                dimensions = EXCLUDED.dimensions,
                is_active = EXCLUDED.is_active
            """,
            (model_id, model_id, dimensions),
        )
        connection.commit()
        connection.execute(
            "CREATE TEMP TABLE embedding_cache_stage("
            "product_id bigint PRIMARY KEY, "
            "content_hash text NOT NULL, "
            f"embedding vector({dimensions}) NOT NULL"
            ") ON COMMIT DELETE ROWS"
        )

        for shard in manifest["shards"]:
            path = manifest_path.parent / shard["path"]
            product_ids, content_hashes, embeddings = validate_shard(
                path,
                shard,
                dimensions,
            )
            with connection.cursor().copy(
                "COPY embedding_cache_stage("
                "product_id, content_hash, embedding"
                ") FROM STDIN (FORMAT BINARY)"
            ) as copy:
                copy.set_types(["int8", "text", "vector"])
                for product_id, content_hash, embedding in zip(
                    product_ids,
                    content_hashes,
                    embeddings,
                ):
                    copy.write_row(
                        (
                            int(product_id),
                            bytes(content_hash).decode("ascii"),
                            embedding,
                        )
                    )
            updated = connection.execute(
                """
                UPDATE mosaic_search.product_document AS document
                SET embedding = cache.embedding,
                    embedding_model_key = %s,
                    embedding_updated_at = clock_timestamp()
                FROM embedding_cache_stage AS cache
                JOIN mosaic.product AS product
                  ON product.product_id = cache.product_id
                 AND product.content_hash = cache.content_hash
                WHERE document.product_id = cache.product_id
                """,
                (model_id,),
            ).rowcount
            if updated != int(shard["count"]):
                connection.rollback()
                raise RuntimeError(
                    f"{path.name} matched {updated:,} of "
                    f"{int(shard['count']):,} products"
                )
            connection.commit()
            imported += updated
            print(f"  imported {imported:,} vectors", flush=True)

    if imported != int(manifest["vector_count"]):
        raise RuntimeError(
            f"manifest declares {int(manifest['vector_count']):,} vectors; "
            f"imported {imported:,}"
        )
    print(f"Imported {imported:,} vectors with model={model_id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/embedding-cache"),
    )
    export_parser.add_argument("--shard-size", type=int, default=10_000)
    export_parser.add_argument("--workers", type=int, default=4)
    export_parser.add_argument(
        "--no-resume",
        action="store_false",
        dest="resume",
        help="overwrite existing shards instead of verifying and reusing them",
    )
    export_parser.set_defaults(resume=True)
    export_parser.add_argument(
        "--expected-count",
        type=int,
        default=DEFAULT_PRODUCT_COUNT,
    )
    export_parser.add_argument(
        "--model-id",
        default=COHERE_EMBED_V4_MODEL_ID,
    )
    export_parser.add_argument(
        "--dimensions",
        type=int,
        default=COHERE_EMBED_V4_DIMENSIONS,
    )
    export_parser.set_defaults(handler=export_cache)

    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("manifest", type=Path)
    import_parser.set_defaults(handler=import_cache)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("manifest", type=Path)
    verify_parser.add_argument(
        "--contract",
        type=Path,
        default=DEFAULT_CONTRACT,
    )
    verify_parser.set_defaults(
        handler=lambda parsed: verify_cache(parsed.manifest, parsed.contract)
    )

    args = parser.parse_args()
    if args.command in {"export", "import"} and not args.database_url:
        raise SystemExit("DATABASE_URL or --database-url is required")
    if args.command == "export":
        if args.shard_size <= 0:
            raise SystemExit("--shard-size must be positive")
        if args.expected_count <= 0:
            raise SystemExit("--expected-count must be positive")
        if args.workers <= 0 or args.workers > 16:
            raise SystemExit("--workers must be between 1 and 16")
    args.handler(args)


if __name__ == "__main__":
    main()
