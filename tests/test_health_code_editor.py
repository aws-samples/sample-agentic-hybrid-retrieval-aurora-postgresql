"""Mosaic links to the Code Editor without ever carrying its token.

The `CodeEditorURL` stack output is
`https://EDITOR-DOMAIN/?folder=HOME/sample-agentic-hybrid-retrieval-aurora-postgresql&tkn=TOKEN`,
and that token is a credential for the participant's editor. `/api/health`
publishes this value to every browser that loads the storefront, so the two
properties worth holding are that the tokenless form travels intact and that a
tokened one cannot start the process at all.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from service.config import ConfigurationError, get_settings
from service.main import app

TOKENLESS = (
    "https://d111111abcdef8.cloudfront.net/?folder=/home/participant/"
    "sample-agentic-hybrid-retrieval-aurora-postgresql"
)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """`get_settings` is `lru_cache`d, so each case needs a cold read."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_health_reports_no_editor_when_none_is_configured(monkeypatch):
    """Outside Workshop Studio there is no editor, and null is the honest answer."""
    monkeypatch.delenv("MOSAIC_CODE_EDITOR_URL", raising=False)

    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json()["code_editor_url"] is None


def test_health_reports_an_empty_setting_as_no_editor(monkeypatch):
    """The bootstrap leaves the variable empty when discovery fails.

    `config/.env.example` also ships it empty. An empty string would render as a
    link to the storefront's own origin, so it has to read as absent rather than
    as a URL.
    """
    monkeypatch.setenv("MOSAIC_CODE_EDITOR_URL", "   ")

    response = TestClient(app).get("/api/health")

    assert response.json()["code_editor_url"] is None


def test_health_publishes_the_tokenless_editor_url(monkeypatch):
    monkeypatch.setenv("MOSAIC_CODE_EDITOR_URL", TOKENLESS)

    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json()["code_editor_url"] == TOKENLESS


@pytest.mark.parametrize(
    "value",
    [
        f"{TOKENLESS}&tkn=s3cr3t-editor-token",
        f"{TOKENLESS}&TKN=s3cr3t-editor-token",
        "https://d111111abcdef8.cloudfront.net/?tkn=s3cr3t-editor-token",
    ],
)
def test_an_editor_token_refuses_to_start_the_service(monkeypatch, value):
    """A tokened value must fail at startup rather than reach a browser."""
    monkeypatch.setenv("MOSAIC_CODE_EDITOR_URL", value)

    with pytest.raises(ConfigurationError) as excinfo:
        get_settings()

    message = str(excinfo.value)
    assert "MOSAIC_CODE_EDITOR_URL" in message
    assert "tkn=" in message
    assert "?folder=" in message
    assert "s3cr3t-editor-token" not in message, (
        "the refusal is written to logs and to stack events; it must name the "
        "defect without reprinting the token"
    )
