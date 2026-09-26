"""Prove the review importer checks source bytes and selected product parents."""

import copy
import json
from unittest.mock import MagicMock

import pytest

from scripts import stage_catalog_evidence as staging
from scripts.fetch_catalog_reviews import review_record, source_identity


def sample_file(tmp_path):
    original = {
        "parent_asin": "PARENT0001",
        "asin": "VARIANT001",
        "title": "A review",
        "text": "Original experience.",
        "rating": 2,
        "verified_purchase": False,
        "helpful_vote": 1,
        "timestamp": 1600000000000,
    }
    raw = (json.dumps(original) + "\n").encode()
    row = review_record(raw, 123)
    state = {
        "source": source_identity("Electronics"),
        "parent_asins": ["PARENT0001"],
        "reviews": [row],
        "coverage": {"PARENT0001": 1},
        "next_byte": 500,
        "complete_source_scan": False,
    }
    path = tmp_path / "Electronics-reviews.json"
    path.write_text(json.dumps(state))
    return path, state, raw


def test_remote_source_byte_mismatch_fails_then_identical_restoration_passes(
    tmp_path, monkeypatch
):
    path, state, raw = sample_file(tmp_path)
    saved = path.read_bytes()
    remote = MagicMock(return_value=raw.replace(b"Original", b"Modified"))
    monkeypatch.setattr(staging, "fetch_range", remote)
    with pytest.raises(ValueError, match="Review source-byte rule.*restore"):
        staging.verified_samples(path)
    remote.assert_called_once_with(state["source"], 123, 123 + len(raw) - 1)
    remote.return_value = raw
    checked_state, rows = staging.verified_samples(path)
    assert checked_state == state and rows == state["reviews"]
    assert path.read_bytes() == saved
    state["operator_note"] = "Irrelevant to source identity"
    path.write_text(json.dumps(state))
    assert staging.verified_samples(path)[1] == rows
    assert remote.call_count == 3


def test_selected_parent_gate_runs_before_any_database_mutation(tmp_path, monkeypatch):
    _, state, _ = sample_file(tmp_path)
    conn = MagicMock()
    conn.execute.return_value = []
    create = MagicMock()
    monkeypatch.setattr(staging, "create_tables", create)
    with pytest.raises(ValueError, match="Review parent rule.*PARENT0001.*import"):
        staging.import_samples(conn, "dataset", state, state["reviews"], "Electronics")
    create.assert_not_called()
    conn.commit.assert_not_called()
    assert conn.execute.call_count == 1
    assert conn.execute.call_args.args[1] == ("dataset", ["PARENT0001"])
    conn.execute.reset_mock()
    conn.execute.return_value = [("PARENT0001",)]
    saved = copy.deepcopy(state)
    result = staging.import_samples(
        conn, "dataset", state, state["reviews"], "Electronics"
    )
    assert result["reviews_verified"] == 1
    assert state == saved
    create.assert_called_once_with(conn)
    conn.commit.assert_called_once()
    assert conn.execute.call_count == 2
    manifest = conn.execute.call_args.args[1][3].obj
    assert "evidence_ids" not in manifest and "coverage" not in manifest
    assert manifest["evidence_count"] == 1 and manifest["parents_selected"] == 1
    batches = conn.cursor.return_value.__enter__.return_value.executemany.call_args_list
    assert batches[0].args[1][0][-1] == "Electronics"
    assert batches[1].args[1] == [("dataset", "Electronics", "PARENT0001", 1)]


def test_sample_cannot_silently_add_an_unselected_parent(tmp_path, monkeypatch):
    path, state, raw = sample_file(tmp_path)
    state["parent_asins"] = ["OTHER00001"]
    path.write_text(json.dumps(state))
    remote = MagicMock(return_value=raw)
    monkeypatch.setattr(staging, "fetch_range", remote)
    with pytest.raises(ValueError, match="Review selection rule.*rebuild"):
        staging.verified_samples(path)
    remote.assert_not_called()
