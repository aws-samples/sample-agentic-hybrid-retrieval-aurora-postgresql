"""Connection failures need safe, actionable responses without a guessed cause."""

from __future__ import annotations

from fastapi.testclient import TestClient
from psycopg import OperationalError
from psycopg_pool import PoolTimeout

from service import main


def _client() -> TestClient:
    # raise_server_exceptions=False so the handler's response is observed rather
    # than the exception being re-raised into the test.
    return TestClient(main.app, raise_server_exceptions=False)


def test_connection_timeout_answers_503_without_assuming_pool_exhaustion(monkeypatch):
    def saturated(*_args, **_kwargs):
        raise PoolTimeout("couldn't get a connection after 20.00 sec")

    monkeypatch.setattr(main, "catalog_summary", saturated)

    response = _client().get("/api/catalog/summary")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "catalog connection" in detail
    assert "Retry" in detail
    assert "Aurora connectivity" in detail
    assert "database capacity" in detail
    assert "Every database connection is busy" not in detail
    assert "DB_POOL_MAX_SIZE" not in detail
    assert "DB_POOL_TIMEOUT_SECONDS" not in detail


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
