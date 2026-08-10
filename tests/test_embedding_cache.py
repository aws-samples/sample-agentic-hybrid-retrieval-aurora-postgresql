import hashlib
from pathlib import Path

import numpy as np
from pgvector import Vector
import pytest

from scripts.embedding_cache import (
    file_sha256,
    load_manifest,
    validate_shard,
    vector_float32,
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
