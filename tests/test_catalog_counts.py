"""Count batches retain the catalog's typed filter boundary and ordering."""

import pytest
from fastapi.testclient import TestClient

from service import main


def test_count_route_preserves_filter_order_and_zero_results(monkeypatch):
    captured = []

    def count(filters):
        captured.extend(item.as_sql_json() for item in filters)
        return [101, 0, 190]

    monkeypatch.setattr(main, "count_products", count)
    response = TestClient(main.app).post(
        "/api/catalog/counts",
        json=[
            {"max_price_cents": 20000},
            {"in_stock_only": True, "attributes": {"usb_c": True}},
            {"min_rating": 4},
        ],
    )
    assert response.status_code == 200
    assert response.json() == [101, 0, 190]
    assert captured[0]["max_price_cents"] == 20000
    assert captured[0]["include_refurbished"] is True
    assert captured[0]["include_sponsored"] is True
    assert captured[1]["in_stock_only"] is True
    assert captured[1]["attributes"] == {"usb_c": True}
    assert captured[2]["min_rating"] == 4


@pytest.mark.parametrize("payload", [[], [{}] * 13, [{"min_rating": 6}]])
def test_count_route_rejects_invalid_batches_before_database_work(monkeypatch, payload):
    def unexpected(_filters):
        pytest.fail("invalid count request reached Aurora")

    monkeypatch.setattr(main, "count_products", unexpected)
    assert (
        TestClient(main.app).post("/api/catalog/counts", json=payload).status_code
        == 422
    )
