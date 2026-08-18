"""Catalog autocomplete stays bounded to indexed Aurora identity reads."""

from __future__ import annotations

from contextlib import contextmanager

from fastapi.testclient import TestClient

from service import catalog, main
from service.models import (
    CatalogSuggestion,
    CatalogSuggestionsResponse,
    SearchFilters,
)

SUGGESTION_ROW = {
    "kind": "product",
    "label": "Mosaic Forma Ergonomic Office Chair",
    "query": "Mosaic Forma Ergonomic Office Chair",
    "product_id": 370001,
    "domain": "home_office",
    "brand": "Mosaic",
    "category_key": "ergonomic-office-chairs",
    "category_path": "Seating > Ergonomic Office Chairs",
}


class _Cursor:
    def fetchall(self):
        return [SUGGESTION_ROW]


class _Connection:
    def __init__(self):
        self.sql = ""
        self.parameters = ()

    def execute(self, sql, parameters):
        self.sql = sql
        self.parameters = parameters
        return _Cursor()


class _BrowseCursor:
    def __init__(self, result):
        self.result = result

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result


class _BrowseConnection:
    def __init__(self):
        self.calls = []
        self.results = [
            {"count": 200},
            [],
            [],
            [],
            [],
            [],
        ]

    def execute(self, sql, parameters):
        self.calls.append((sql, parameters))
        return _BrowseCursor(self.results.pop(0))


def test_catalog_browse_is_bounded_to_the_installed_200_product_edit(
    monkeypatch,
):
    connection = _BrowseConnection()

    @contextmanager
    def fake_connect():
        yield connection

    monkeypatch.setattr(catalog, "connect", fake_connect)

    response = catalog.list_products(SearchFilters())

    assert response.total == 200
    assert all("WITH photographed AS" in sql for sql, _ in connection.calls)
    assert all("ma.shop_page" not in sql for sql, _ in connection.calls)
    assert len(connection.calls[0][1][0]) == 200
    assert all(
        parameters[0] == connection.calls[0][1][0] for _, parameters in connection.calls
    )
    assert "ORDER BY photographed.ordinality" in connection.calls[1][0]


def test_catalog_suggestions_use_the_indexed_projection_without_model_calls(
    monkeypatch,
):
    connection = _Connection()

    @contextmanager
    def fake_connect():
        yield connection

    monkeypatch.setattr(catalog, "connect", fake_connect)

    response = catalog.catalog_suggestions("  ergonomic   chair ")

    assert response.query == "ergonomic chair"
    assert response.suggestions[0].product_id == 370001
    assert "d.search_document @@ prefix_query.value" in connection.sql
    assert "mosaic_search.product_document" in connection.sql
    assert "embedding" not in connection.sql.lower()
    assert "rerank" not in connection.sql.lower()
    assert connection.parameters[0] == "ergonomic chair"


def test_catalog_suggestion_route_preserves_the_typed_contract(monkeypatch):
    def suggest(query: str) -> CatalogSuggestionsResponse:
        return CatalogSuggestionsResponse(
            query=query,
            suggestions=[CatalogSuggestion(**SUGGESTION_ROW)],
        )

    monkeypatch.setattr(main, "catalog_suggestions", suggest)
    response = TestClient(main.app).get(
        "/api/catalog/suggestions",
        params={"q": "  ergonomic   chair "},
    )

    assert response.status_code == 200
    assert response.json()["query"] == "ergonomic chair"
    assert response.json()["suggestions"][0] == SUGGESTION_ROW


def test_catalog_suggestion_route_rejects_whitespace_only_queries():
    response = TestClient(main.app).get(
        "/api/catalog/suggestions",
        params={"q": "   "},
    )

    assert response.status_code == 422
    assert "two non-space characters" in response.json()["detail"]
