"""Pool exhaustion has to say something a participant can act on.

`psycopg_pool.PoolTimeout` subclasses `psycopg.OperationalError`, not
`RuntimeError`, so the `except RuntimeError` in every route misses it and Starlette
answers a bare "Internal Server Error". Under a full workshop room that is the
most likely failure of all.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from psycopg import OperationalError
from psycopg_pool import PoolTimeout

from service import main


def _client() -> TestClient:
    # raise_server_exceptions=False so the handler's response is observed rather
    # than the exception being re-raised into the test.
    return TestClient(main.app, raise_server_exceptions=False)


def test_pool_exhaustion_answers_503_with_the_knobs_to_turn(monkeypatch):
    def saturated(*_args, **_kwargs):
        raise PoolTimeout("couldn't get a connection after 20.00 sec")

    monkeypatch.setattr(main, "catalog_summary", saturated)

    response = _client().get("/api/catalog/summary")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "Every database connection is busy" in detail
    assert "DB_POOL_MAX_SIZE" in detail
    assert "DB_POOL_TIMEOUT_SECONDS" in detail


def test_pool_exhaustion_never_echoes_the_connection_string(monkeypatch):
    def saturated(*_args, **_kwargs):
        raise PoolTimeout(
            "connection failed: postgresql://mosaic:secret@db.example.com:5432/x"
        )

    monkeypatch.setattr(main, "catalog_summary", saturated)

    body = _client().get("/api/catalog/summary").text

    assert "postgresql://" not in body
    assert "secret" not in body
    assert "db.example.com" not in body


def test_database_operational_errors_are_sanitized_as_503(monkeypatch):
    """Red-at-birth: connection resets currently escape as a generic HTTP 500."""

    def unavailable(*_args, **_kwargs):
        raise OperationalError(
            "connection failed: postgresql://mosaic:secret@db.example.com:5432/x"
        )

    monkeypatch.setattr(main, "catalog_summary", unavailable)

    response = _client().get("/api/catalog/summary")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "Database operation failed" in detail
    assert "fix:" in detail
    assert "postgresql://" not in response.text
    assert "secret" not in response.text
    assert "db.example.com" not in response.text
