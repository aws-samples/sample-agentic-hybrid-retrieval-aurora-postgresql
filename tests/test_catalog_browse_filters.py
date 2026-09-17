"""Shop browsing must preserve the filters displayed by its caller."""

import json

import pytest
from fastapi.testclient import TestClient

from service import main


def test_browse_forwards_structured_filters_to_the_catalog(monkeypatch):
    captured = []

    def listing(filters, **options):
        captured.append((filters.as_sql_json(), options))
        return {"total": 0, "offset": 0, "limit": 12, "products": [], "facets": {}}

    monkeypatch.setattr(main, "list_products", listing)
    attributes = {"active_noise_cancellation": True, "connectivity": ["Bluetooth"]}
    response = TestClient(main.app).get(
        "/api/catalog/products",
        params=[
            ("attributes", json.dumps(attributes)),
            ("brands", "Sonora"),
            ("brands", "AuriLogic"),
            ("sort", "price_asc"),
        ],
    )

    assert response.status_code == 200
    assert len(captured) == 1
    filters, options = captured[0]
    assert filters["attributes"] == attributes
    assert filters["brands"] == ["Sonora", "AuriLogic"]
    assert filters["include_refurbished"] is True
    assert options["sort"] == "price_asc"


@pytest.mark.parametrize("attributes", ["{broken", "[]", "null", '{"usb_c": {"x": 1}}'])
def test_browse_rejects_invalid_attributes_before_database_work(
    monkeypatch, attributes
):
    def unexpected(*_args, **_kwargs):
        pytest.fail("invalid attribute filters reached the catalog")

    monkeypatch.setattr(main, "list_products", unexpected)
    response = TestClient(main.app).get(
        "/api/catalog/products", params={"attributes": attributes}
    )
    assert response.status_code == 422


def test_browse_rejects_contradictory_brand_filters(monkeypatch):
    monkeypatch.setattr(
        main,
        "list_products",
        lambda *_args, **_kwargs: pytest.fail(
            "contradictory brand filters reached the catalog"
        ),
    )
    response = TestClient(main.app).get(
        "/api/catalog/products", params={"brand": "Sonora", "brands": "AuriLogic"}
    )
    assert response.status_code == 422
