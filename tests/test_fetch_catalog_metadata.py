"""Pin source integrity before any bulk embedding charges are incurred."""

import gzip
import hashlib
import json

import pytest

from scripts import fetch_catalog_metadata as source
from scripts.fetch_catalog_metadata import iter_records, read_chunk, validate_range


def test_range_rejects_full_response_or_cached_wrong_segment():
    validate_range(206, "bytes 10-19/30", 10, 19, 30)
    with pytest.raises(ValueError, match="Source range rule"):
        validate_range(200, None, 10, 19, 30)
    with pytest.raises(ValueError, match="Source range rule"):
        validate_range(206, "bytes 0-9/30", 10, 19, 30)


def test_resume_checks_length_and_compression_integrity(tmp_path):
    path = tmp_path / "chunk.gz"
    path.write_bytes(gzip.compress(b"unchanged"))
    assert read_chunk(path, 9) == b"unchanged"
    with pytest.raises(ValueError, match="Chunk length rule"):
        read_chunk(path, 8)
    path.write_bytes(b"corrupt")
    with pytest.raises(OSError):
        read_chunk(path, 9)


def test_source_proof_and_cross_range_unicode_lines(tmp_path, monkeypatch):
    raw = '{"parent_asin":"ONE","title":"écran"}\n{"parent_asin":"TWO"}'.encode()
    monkeypatch.setattr(
        source, "SOURCES", {"Electronics": (len(raw), hashlib.sha256(raw).hexdigest())}
    )
    identity = source.source_identity("Electronics")
    (tmp_path / "source.json").write_text(json.dumps(identity))
    with pytest.raises(ValueError, match="complete-source checksum"):
        list(iter_records(tmp_path))
    (tmp_path / "verified.json").write_text(json.dumps(identity))
    split = raw.index("é".encode()) + 1
    (tmp_path / "00000.jsonl.part.gz").write_bytes(gzip.compress(raw[:split]))
    (tmp_path / "00001.jsonl.part.gz").write_bytes(gzip.compress(raw[split:]))
    assert [row["parent_asin"] for row in iter_records(tmp_path)] == ["ONE", "TWO"]
    (tmp_path / "00001.jsonl.part.gz").write_bytes(
        gzip.compress(raw[split:].replace(b"TWO", b"BAD"))
    )
    with pytest.raises(ValueError, match="stored ranges changed"):
        list(iter_records(tmp_path))


def test_replacing_both_markers_cannot_change_the_pinned_source(tmp_path):
    identity = source.source_identity("Electronics")
    identity["sha256"] = hashlib.sha256(b"replacement").hexdigest()
    for marker in ("source.json", "verified.json"):
        (tmp_path / marker).write_text(json.dumps(identity))
    with pytest.raises(ValueError, match="Source identity rule"):
        list(iter_records(tmp_path))
