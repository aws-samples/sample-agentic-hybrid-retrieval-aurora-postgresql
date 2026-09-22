"""Reject unsafe destinations and altered source data before Aurora writes."""

import gzip
import json
from unittest.mock import MagicMock

import pytest

from scripts import stage_real_catalog as stage
from scripts.prepare_real_catalog import canonical, embedding_text, sha256
from scripts.stage_real_catalog import iter_record_pages, validate_dsn


@pytest.mark.parametrize(
    "dsn",
    [
        "",
        "postgresql://user:secret@localhost/db?sslmode=require",
        "host=example.cluster-123.us-east-1.rds.amazonaws.com sslmode=disable password=secret",
        "postgresql://user:secret@example.com/db?sslmode=require",
        "host='broken secret",
    ],
)
def test_unsafe_destination_rejected_without_echoing_credentials(dsn):
    with pytest.raises(ValueError, match="Aurora connection rule") as failure:
        validate_dsn(dsn)
    assert "secret" not in str(failure.value)


def test_tls_aurora_destination_is_accepted():
    validate_dsn(
        "host=demo.cluster-123.us-east-1.rds.amazonaws.com sslmode=verify-full password=secret"
    )


def test_staged_source_must_match_its_declared_hash_and_projection(tmp_path):
    original = {
        "title": "Original title",
        "description": ["Source description."],
        "features": [],
        "categories": [],
        "details": {},
    }
    text = embedding_text(original)
    row = {
        "parent_asin": "SOURCE01",
        "original": original,
        "source_record_sha256": sha256(canonical(original)),
        "embedding_text": text,
        "embedding_text_sha256": sha256(text),
    }
    path = tmp_path / "catalog.jsonl.gz"
    with gzip.open(path, "wt") as stream:
        stream.write(json.dumps(row) + "\n")
    assert list(iter_record_pages(tmp_path)) == [[row]]
    row["original"]["description"] = ["Invented replacement."]
    with gzip.open(path, "wt") as stream:
        stream.write(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="Staging source rule"):
        list(iter_record_pages(tmp_path))


def embedding_groups():
    return [
        (key, [{"parent_asin": key, "embedding_text_sha256": key + "-text"}], [[0.5]])
        for key in ("first", "second")
    ]


def test_embedding_group_commits_vectors_and_all_checkpoints_together():
    conn = MagicMock()
    conn.execute.return_value.rowcount = 2
    assert stage.write_embedding_transaction(conn, "dataset", embedding_groups()) == 2
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    checkpoints = conn.cursor.return_value.__enter__.return_value.executemany
    assert checkpoints.call_args.args[1] == [
        ("dataset", "first", "embeddings", 1),
        ("dataset", "second", "embeddings", 1),
    ]


def test_missing_product_prevents_embedding_group_checkpoint():
    conn = MagicMock()
    conn.execute.return_value.rowcount = 1
    with pytest.raises(ValueError, match="updated 1 of 2"):
        stage.write_embedding_transaction(conn, "dataset", embedding_groups())
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()
    conn.cursor.return_value.__enter__.return_value.executemany.assert_not_called()


def test_checkpoint_failure_rolls_back_its_vector_updates():
    conn = MagicMock()
    conn.execute.return_value.rowcount = 2
    conn.cursor.return_value.__enter__.return_value.executemany.side_effect = (
        RuntimeError("interrupted")
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        stage.write_embedding_transaction(conn, "dataset", embedding_groups())
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()
