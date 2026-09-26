"""The /api/hnsw routes serve only the catalog their anchor set was selected from."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from service import main
from service.hnsw_anchors import AnchorSetError


def _anchor_set(dataset_id: str):
    return SimpleNamespace(dataset_id=dataset_id, sha256="a" * 64, product_ids=(1,))


def test_a_set_selected_from_another_catalog_is_refused_with_both_names(monkeypatch):
    monkeypatch.setattr(main, "load_anchor_set", lambda: _anchor_set("reviews-2023-v2"))
    monkeypatch.setattr(main, "served_dataset_id", lambda: "reviews-2023-500k-v1")

    response = TestClient(main.app).get("/api/hnsw/anchors")

    assert response.status_code == 409
    assert "reviews-2023-v2" in response.json()["detail"]
    assert "reviews-2023-500k-v1" in response.json()["detail"]


def test_the_legacy_catalog_cannot_borrow_the_real_catalog_anchors(monkeypatch):
    monkeypatch.setattr(main, "load_anchor_set", lambda: _anchor_set("reviews-2023-v2"))
    monkeypatch.setattr(main, "served_dataset_id", lambda: "synthetic-legacy")

    response = TestClient(main.app).get("/api/hnsw/measured")

    assert response.status_code == 409


def test_a_missing_or_invalid_anchor_set_is_a_503_with_the_fix(monkeypatch):
    def broken():
        raise AnchorSetError(
            "found: no anchor set; fix: run `make select-hnsw-anchors`"
        )

    monkeypatch.setattr(main, "load_anchor_set", broken)

    response = TestClient(main.app).get("/api/hnsw/substrate")

    assert response.status_code == 503
    assert "select-hnsw-anchors" in response.json()["detail"]


def test_a_matching_set_lets_the_route_through_to_the_service(monkeypatch):
    monkeypatch.setattr(main, "load_anchor_set", lambda: _anchor_set("reviews-2023-v2"))
    monkeypatch.setattr(main, "served_dataset_id", lambda: "reviews-2023-v2")
    monkeypatch.setattr(main.hnsw, "anchors", lambda: [{"product_id": 1}])

    response = TestClient(main.app).get("/api/hnsw/anchors")

    assert response.status_code == 200
    assert response.json() == {"anchors": [{"product_id": 1}]}
