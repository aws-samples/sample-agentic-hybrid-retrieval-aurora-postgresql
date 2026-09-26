"""The anchor set is a verified contract, refused when it cannot be trusted."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from service.hnsw_anchors import (
    ANCHOR_FILE,
    ANCHOR_SET_KIND,
    AnchorSetError,
    anchor_ids_sha256,
    load_anchor_set,
    require_anchor_set_for_served_catalog,
)

ROOT = Path(__file__).resolve().parents[1]


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "hnsw_anchors.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _valid_payload(ids=(1277987, 1551237, 1540761), dataset_id="reviews-2023-v2"):
    return {
        "kind": ANCHOR_SET_KIND,
        "dataset_id": dataset_id,
        "catalog_sha256": "c" * 64,
        "selection": {"seed": "s", "algorithm": "a"},
        "anchors": [{"product_id": item, "title": f"product {item}"} for item in ids],
        "sha256": anchor_ids_sha256(list(ids)),
    }


def test_the_committed_anchor_set_is_valid_and_names_the_served_dataset():
    anchors = load_anchor_set(ANCHOR_FILE)

    assert anchors.dataset_id == "reviews-2023-v2"
    assert len(anchors.product_ids) == len(set(anchors.product_ids))
    assert {1277987, 1551237, 1540761} <= set(anchors.product_ids)
    assert anchors.selection["seed"]
    assert anchors.selection["algorithm"]


def test_the_hash_is_the_sorted_ids_and_nothing_else():
    assert anchor_ids_sha256([3, 1, 2]) == anchor_ids_sha256([1, 2, 3])
    assert anchor_ids_sha256([1, 2, 3]) != anchor_ids_sha256([1, 2, 4])


def test_a_valid_file_loads_with_its_identity(tmp_path):
    anchors = load_anchor_set(_write(tmp_path, _valid_payload()))

    assert anchors.product_ids == (1277987, 1551237, 1540761)
    assert anchors.sha256 == anchor_ids_sha256([1277987, 1551237, 1540761])
    assert 1551237 in anchors
    assert 42 not in anchors


def test_a_missing_file_is_refused_with_the_command_that_creates_it(tmp_path):
    with pytest.raises(AnchorSetError) as raised:
        load_anchor_set(tmp_path / "absent.json")

    assert "select-hnsw-anchors" in str(raised.value)
    assert "fix:" in str(raised.value)


def test_an_empty_anchor_set_is_refused(tmp_path):
    payload = _valid_payload(ids=())

    with pytest.raises(AnchorSetError) as raised:
        load_anchor_set(_write(tmp_path, payload))

    assert "no anchors" in str(raised.value)


def test_a_repeated_id_is_refused(tmp_path):
    payload = _valid_payload(ids=(1, 1, 2))

    with pytest.raises(AnchorSetError, match="repeats"):
        load_anchor_set(_write(tmp_path, payload))


def test_a_hash_that_does_not_match_the_ids_is_refused(tmp_path):
    """Editing the id list by hand without recomputing the hash is caught."""
    payload = _valid_payload()
    payload["anchors"].append({"product_id": 99})

    with pytest.raises(AnchorSetError, match="hash"):
        load_anchor_set(_write(tmp_path, payload))


def test_the_wrong_kind_is_refused(tmp_path):
    payload = _valid_payload() | {"kind": "projection"}

    with pytest.raises(AnchorSetError, match="kind"):
        load_anchor_set(_write(tmp_path, payload))


def test_an_anchor_set_for_another_catalog_is_refused(tmp_path, monkeypatch):
    """Wrong-catalog attribution: the set names v2, the service serves v1."""
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-500k-v1")
    path = _write(tmp_path, _valid_payload(dataset_id="reviews-2023-v2"))

    with pytest.raises(AnchorSetError) as raised:
        require_anchor_set_for_served_catalog(path)

    message = str(raised.value)
    assert "reviews-2023-v2" in message
    assert "reviews-2023-500k-v1" in message


def test_the_legacy_catalog_is_not_the_real_catalog(tmp_path, monkeypatch):
    monkeypatch.delenv("MOSAIC_CATALOG_DATASET", raising=False)
    path = _write(tmp_path, _valid_payload(dataset_id="reviews-2023-v2"))

    with pytest.raises(AnchorSetError, match="synthetic-legacy"):
        require_anchor_set_for_served_catalog(path)


def test_the_matching_catalog_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    path = _write(tmp_path, _valid_payload(dataset_id="reviews-2023-v2"))

    assert require_anchor_set_for_served_catalog(path).dataset_id == "reviews-2023-v2"
