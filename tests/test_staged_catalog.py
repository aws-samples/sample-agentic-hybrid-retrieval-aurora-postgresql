"""Exercise the actual HTTP boundary for opt-in source inspection."""

from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from service import staged_catalog


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(staged_catalog.router)
    return TestClient(app)


def test_staging_is_unavailable_unless_explicitly_enabled(client, monkeypatch):
    monkeypatch.delenv("MOSAIC_STAGED_CATALOG_DATASET", raising=False)
    reads = []
    monkeypatch.setattr(staged_catalog, "connect", lambda: reads.append(True))
    assert client.get("/api/catalog-staging/products/PARENT0001").status_code == 404
    assert reads == []


@pytest.mark.parametrize("parent", ["PARENT0001", "b01g8jo5f2"])
def test_product_citation_cannot_cross_the_parent_boundary(client, monkeypatch, parent):
    calls = []
    monkeypatch.setenv("MOSAIC_STAGED_CATALOG_DATASET", "selected-dataset")

    @contextmanager
    def connection():
        yield object()

    def load(_connection, dataset, parent):
        calls.append((dataset, parent))
        return {"parent_asin": parent}

    monkeypatch.setattr(staged_catalog, "connect", connection)
    monkeypatch.setattr(staged_catalog, "load_product", load)
    monkeypatch.setattr(staged_catalog, "project_product", lambda row: row)
    monkeypatch.setattr(
        staged_catalog,
        "product_evidence",
        lambda _connection, dataset, row: (
            [
                {
                    "evidence_id": "record-" + row["parent_asin"],
                    "parent_asin": row["parent_asin"],
                }
            ],
            [],
        ),
    )
    good = client.get(
        f"/api/catalog-staging/products/{parent}/evidence/record-{parent}"
    )
    assert good.status_code == 200
    assert good.json()["parent_asin"] == parent
    wrong = client.get(
        f"/api/catalog-staging/products/OTHER00001/evidence/record-{parent}"
    )
    assert wrong.status_code == 404
    assert calls == [
        ("selected-dataset", parent),
        ("selected-dataset", "OTHER00001"),
    ]


def test_invalid_parent_identifier_never_reaches_the_database(client, monkeypatch):
    calls = []
    monkeypatch.setenv("MOSAIC_STAGED_CATALOG_DATASET", "selected-dataset")
    monkeypatch.setattr(staged_catalog, "connect", lambda: calls.append(True))
    assert client.get("/api/catalog-staging/products/not-an-asin").status_code == 422
    assert calls == []
