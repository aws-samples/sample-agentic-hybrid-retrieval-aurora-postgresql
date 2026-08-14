import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from pgvector import Vector

from scripts.embedding_cache import (
    file_sha256,
    load_contract,
    load_manifest,
    validate_shard,
    vector_float32,
    verify_cache,
)


def test_embedding_cache_converts_pgvector_wrapper_to_float32():
    value = vector_float32(Vector([1.25, 2.5]))

    assert value.tolist() == [1.25, 2.5]
    assert value.dtype == np.float32


def test_embedding_cache_validates_checksum_shape_and_dtype(tmp_path: Path):
    path = tmp_path / "embeddings-00001.npz"
    np.savez(
        path,
        product_ids=np.asarray([1, 2], dtype=np.int64),
        content_hashes=np.asarray([b"a" * 64, b"b" * 64], dtype="S64"),
        embeddings=np.ones((2, 1024), dtype=np.float32),
    )
    shard = {
        "count": 2,
        "sha256": file_sha256(path),
    }

    product_ids, content_hashes, embeddings = validate_shard(
        path,
        shard,
        1024,
    )

    assert product_ids.tolist() == [1, 2]
    assert content_hashes.tolist() == [b"a" * 64, b"b" * 64]
    assert embeddings.shape == (2, 1024)
    assert embeddings.dtype == np.float32


def test_embedding_cache_rejects_changed_shard(tmp_path: Path):
    path = tmp_path / "embeddings-00001.npz"
    path.write_bytes(b"not an npz")

    with pytest.raises(ValueError, match="checksum mismatch"):
        validate_shard(
            path,
            {"count": 1, "sha256": hashlib.sha256(b"other").hexdigest()},
            1024,
        )


def test_embedding_cache_rejects_unknown_manifest_version(tmp_path: Path):
    path = tmp_path / "manifest.json"
    path.write_text('{"schema_version": 2, "dtype": "float32"}')

    with pytest.raises(ValueError, match="schema_version"):
        load_manifest(path)


def test_embedding_cache_rejects_duplicate_manifest_shards(tmp_path: Path):
    path = tmp_path / "manifest.json"
    path.write_text(
        """{
          "schema_version": 1,
          "dtype": "float32",
          "vector_count": 2,
          "catalog_content_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "shards": [
            {
              "path": "embeddings-00001.npz",
              "count": 1,
              "first_product_id": 1,
              "last_product_id": 1,
              "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            },
            {
              "path": "embeddings-00001.npz",
              "count": 1,
              "first_product_id": 2,
              "last_product_id": 2,
              "sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
            }
          ]
        }"""
    )

    with pytest.raises(ValueError, match="unique basenames"):
        load_manifest(path)


def test_embedding_cache_contract_is_pinned_to_the_workshop_artifact():
    contract = load_contract(
        Path(__file__).resolve().parents[1] / "db/config/embedding-cache.json"
    )

    assert contract == {
        "schema_version": 1,
        "manifest_sha256": (
            "134d255b14d72bcf955d5e1bde93bf4982543506464844f91291e1c84b22fc8c"
        ),
        "embedding_model_id": "us.cohere.embed-v4:0",
        "dimensions": 1024,
        "vector_count": 500000,
        "shard_count": 50,
    }


def _write_cache_fixture(tmp_path: Path) -> tuple[Path, Path]:
    shard_path = tmp_path / "embeddings-00001.npz"
    product_ids = np.asarray([1, 2], dtype=np.int64)
    content_hashes = np.asarray([b"a" * 64, b"b" * 64], dtype="S64")
    np.savez(
        shard_path,
        product_ids=product_ids,
        content_hashes=content_hashes,
        embeddings=np.ones((2, 1024), dtype=np.float32),
    )
    from scripts.embedding_cache import catalog_records

    catalog_digest = hashlib.sha256(
        catalog_records(product_ids, content_hashes)
    ).hexdigest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "embedding_model_id": "us.cohere.embed-v4:0",
                "dimensions": 1024,
                "dtype": "float32",
                "vector_count": 2,
                "catalog_content_digest": catalog_digest,
                "shards": [
                    {
                        "path": "embeddings-00001.npz",
                        "count": 2,
                        "first_product_id": 1,
                        "last_product_id": 2,
                        "sha256": file_sha256(shard_path),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "manifest_sha256": file_sha256(manifest_path),
                "embedding_model_id": "us.cohere.embed-v4:0",
                "dimensions": 1024,
                "vector_count": 2,
                "shard_count": 1,
            }
        ),
        encoding="utf-8",
    )
    return manifest_path, contract_path


def test_verify_cache_checks_manifest_shards_and_catalog_digest(tmp_path: Path):
    manifest_path, contract_path = _write_cache_fixture(tmp_path)

    manifest = verify_cache(manifest_path, contract_path)

    assert manifest["vector_count"] == 2


def test_verify_cache_rejects_unexpected_shards(tmp_path: Path):
    manifest_path, contract_path = _write_cache_fixture(tmp_path)
    np.savez(
        tmp_path / "embeddings-00002.npz",
        product_ids=np.asarray([3], dtype=np.int64),
        content_hashes=np.asarray([b"c" * 64], dtype="S64"),
        embeddings=np.ones((1, 1024), dtype=np.float32),
    )

    with pytest.raises(ValueError, match="shard set mismatch"):
        verify_cache(manifest_path, contract_path)


def test_verify_cache_rejects_manifest_hash_drift(tmp_path: Path):
    manifest_path, contract_path = _write_cache_fixture(tmp_path)
    contract = load_contract(contract_path)
    contract["manifest_sha256"] = "f" * 64
    contract_path.write_text(
        __import__("json").dumps(contract),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="manifest checksum mismatch"):
        verify_cache(manifest_path, contract_path)
