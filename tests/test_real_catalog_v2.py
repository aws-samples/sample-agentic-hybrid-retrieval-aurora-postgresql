"""Version-2 selection: pinned base kept whole, complete taxonomy leaves added, ids preserved."""

from __future__ import annotations

import gzip
import hashlib
import json

import pytest

from scripts import fetch_catalog_metadata as metadata
from scripts import fetch_product_questions as questions
from scripts import prepare_real_catalog as selection
from scripts import prepare_staged_catalog_search as projection


def record(asin: str, leaf: str, text: str = "x" * 200) -> dict:
    return {
        "parent_asin": asin,
        "title": f"Product {asin}",
        "features": [text],
        "description": [],
        "categories": ["Electronics", "Computers & Accessories", leaf],
        "details": {"Brand": "Acme"},
        "images": [{"variant": "MAIN", "hi_res": f"https://img.example/{asin}.jpg"}],
    }


PLAN = {
    "version": 2,
    "selection_seed": "seed",
    "minimum_source_text_characters": 160,
    "maximum_embedding_characters": 32000,
    "base": {
        "dataset_id": "v1",
        "parents_file": "base.tsv",
        "parents_sha256": "0" * 64,
        "products": 2,
    },
    "sources": [{"category": "Electronics", "leaves": ["Monitors"]}],
}


def test_targets_keep_every_base_product_and_every_eligible_leaf_product():
    records = [
        record("B000000001", "Cables"),
        record("B000000002", "Monitors"),
        record("B000000003", "Monitors"),
        record("B000000004", "Monitors", text="short"),
    ]
    found, targets, report = selection.select_targets(
        records, {"B000000001"}, {"Monitors"}, PLAN, set()
    )
    assert found == {"B000000001"}
    assert targets == {"B000000002", "B000000003"}
    assert report["excluded_counts"] == {"insufficient_source_text": 1}
    assert report["base_products"] == 1 and report["target_products"] == 2


def test_a_missing_base_product_is_a_hard_error():
    with pytest.raises(ValueError, match="Base selection rule"):
        selection.select_targets(
            [record("B000000002", "Monitors")], {"B000000001"}, set(), PLAN, set()
        )


def test_a_base_product_that_no_longer_qualifies_is_a_hard_error():
    with pytest.raises(ValueError, match="now insufficient_source_text"):
        selection.select_targets(
            [record("B000000001", "Monitors", text="short")],
            {"B000000001"},
            set(),
            PLAN,
            set(),
        )


def test_version_two_plan_needs_base_and_leaves():
    selection.validate_plan(PLAN)
    with pytest.raises(ValueError, match="base"):
        selection.validate_plan({**PLAN, "base": {}})
    with pytest.raises(ValueError, match="leaves"):
        selection.validate_plan(
            {**PLAN, "sources": [{"category": "Electronics", "leaves": "Monitors"}]}
        )


def test_base_parent_list_is_hash_pinned_and_gzip_aware(tmp_path):
    data = b"B000000001\tElectronics\nB000000002\tElectronics\n"
    path = tmp_path / "base.tsv.gz"
    with (
        path.open("wb") as raw,
        gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz,
    ):
        gz.write(data)
    plan = {
        **PLAN,
        "base": {
            **PLAN["base"],
            "parents_file": "base.tsv.gz",
            "parents_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
    }
    assert selection.read_base_parents(plan, tmp_path) == {
        "Electronics": {"B000000001", "B000000002"}
    }
    with pytest.raises(ValueError, match="pinned hash"):
        selection.read_base_parents(
            {**plan, "base": {**plan["base"], "parents_sha256": "1" * 64}}, tmp_path
        )


def test_preserved_ids_must_be_contiguous_and_unique(tmp_path):
    path = tmp_path / "ids.tsv"
    path.write_text("B000000002\t2\nB000000001\t1\n")
    assert projection.read_base_ids(path) == [("B000000002", 2), ("B000000001", 1)]
    path.write_text("B000000002\t3\nB000000001\t1\n")
    with pytest.raises(ValueError, match="contiguous"):
        projection.read_base_ids(path)
    assert projection.read_base_ids(None) == []


def test_stream_filter_verifies_the_whole_file_and_keeps_only_wanted_lines(
    tmp_path, monkeypatch
):
    lines = [
        json.dumps(record("B000000001", "Cables")),
        json.dumps(record("B000000002", "Monitors")),
        json.dumps(record("B000000003", "Cables")),
    ]
    body = ("\n".join(lines) + "\n").encode()
    monkeypatch.setattr(
        metadata,
        "SOURCES",
        {"Electronics": (len(body), hashlib.sha256(body).hexdigest())},
    )
    monkeypatch.setattr(metadata, "CHUNK_BYTES", 40)
    monkeypatch.setattr(
        metadata,
        "_fetch_range",
        lambda category, start, end, size: body[start : end + 1],
    )
    proof = metadata.stream_filter(
        "Electronics", tmp_path, {"B000000003"}, {"Monitors"}, workers=2
    )
    assert proof["filter"]["kept"] == 2 and proof["filter"]["lines"] == 3
    kept = [r["parent_asin"] for r in metadata.iter_records(tmp_path / "Electronics")]
    assert kept == ["B000000002", "B000000003"]


def test_stream_filter_refuses_a_file_whose_hash_differs(tmp_path, monkeypatch):
    body = (json.dumps(record("B000000001", "Monitors")) + "\n").encode()
    monkeypatch.setattr(metadata, "SOURCES", {"Electronics": (len(body), "0" * 64)})
    monkeypatch.setattr(
        metadata,
        "_fetch_range",
        lambda category, start, end, size: body[start : end + 1],
    )
    with pytest.raises(ValueError, match="Source hash rule"):
        metadata.stream_filter("Electronics", tmp_path, set(), {"Monitors"}, workers=1)
    assert not (tmp_path / "Electronics" / "verified.json").exists()


def test_question_record_keeps_answers_and_drops_unanswered_or_malformed_rows():
    raw = {
        "question_id": "Q1",
        "asin": "B000000001",
        "question_text": " Does it charge a MacBook? ",
        "answers": [
            {"answer_text": "Yes, at 65 W."},
            {"answer_text": " "},
            {"answer_text": "Only with the right cable"},
        ],
        "question_type": "yesno",
        "item_name": "Monitor",
    }
    kept = questions.question_record(raw)
    assert kept["question_text"] == "Does it charge a MacBook?"
    assert kept["answers"] == ["Yes, at 65 W.", "Only with the right cable"]
    assert questions.question_record({**raw, "answers": []}) is None
    assert questions.question_record({**raw, "asin": None}) is None


def test_base_ids_are_recovered_from_the_pinned_parent_list_in_byte_order(tmp_path):
    data = b"B00000000B\tElectronics\nB00000000A\tOffice_Products\nB000000009\tElectronics\n"
    path = tmp_path / "base.tsv.gz"
    with (
        path.open("wb") as raw,
        gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz,
    ):
        gz.write(data)
    plan = {
        **PLAN,
        "base": {
            **PLAN["base"],
            "products": 3,
            "parents_file": "base.tsv.gz",
            "parents_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
    }
    assert projection.base_ids_from_selection({"plan": plan}, tmp_path) == [
        ("B000000009", 1),
        ("B00000000A", 2),
        ("B00000000B", 3),
    ]
    assert projection.base_ids_from_selection({"plan": {"version": 1}}, tmp_path) == []
    assert projection.base_ids_from_selection({}, tmp_path) == []
