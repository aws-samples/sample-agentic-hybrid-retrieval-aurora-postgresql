"""A config that cannot serve a request must not yield a running process."""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest

from service.config import ConfigurationError, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """`get_settings` is `lru_cache`d, so each case needs a cold read."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_env_example_declares_no_retrieval_number():
    """`config/.env.example` is what a participant copies; it must not carry a copy.

    The original defect was a value in this file the engine rejected: it shipped
    `BUSINESS_WEIGHT=0.15` against a `le=0.05` bound and every search returned an
    unhandled HTTP 500. Phase 2 Unit C moved these numbers to
    `db/config/retrieval.yaml` as their single source, so the stronger property is
    that this file declares **none** of them — an unusable value cannot ship from
    a file that ships no values. The env vars still work as overrides; they are
    documented here in a comment rather than set.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    lines = (root / "config" / ".env.example").read_text().splitlines()
    settings = [
        line.split("=", 1)[0] for line in lines if "=" in line and line[:1].isupper()
    ]
    for name in (
        "RRF_K",
        "VECTOR_DIM",
        "FTS_CANDIDATE_LIMIT",
        "TRIGRAM_CANDIDATE_LIMIT",
        "SEMANTIC_CANDIDATE_LIMIT",
        "RERANK_CANDIDATE_LIMIT",
        "HNSW_EF_SEARCH",
    ):
        assert name not in settings, (
            f"{name} is set in config/.env.example; it belongs in "
            f"db/config/retrieval.yaml, which is its single source"
        )


def test_env_example_does_not_point_at_a_local_database():
    """Aurora only: a localhost DSN in the file participants copy is a defect."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    text = (root / "config" / ".env.example").read_text()
    dsn = next(line for line in text.splitlines() if line.startswith("DATABASE_URL"))
    dsn_value = dsn.split("=", 1)[1].strip().strip("'\"")
    hostname = urlsplit(dsn_value).hostname

    assert hostname not in {"localhost", "127.0.0.1", "::1"}
    assert hostname is not None
    assert hostname.endswith(".rds.amazonaws.com")


def test_env_example_documents_every_non_retrieval_runtime_setting():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    text = (root / "config" / ".env.example").read_text()

    for name in (
        "CORS_ORIGINS",
        "RERANK_PROVIDER",
        "ALLOW_DEVELOPMENT_EMBEDDINGS",
    ):
        assert f"{name}=" in text, f"{name} is read at runtime but undocumented"
    assert "CATALOG_MANIFEST_PATH" not in text


def test_split_model_overrides_fall_back_to_the_legacy_chat_model(monkeypatch):
    monkeypatch.setenv("BEDROCK_CHAT_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
    monkeypatch.delenv("BEDROCK_AGENT_MODEL_ID", raising=False)
    monkeypatch.delenv("BEDROCK_SYNTHESIS_MODEL_ID", raising=False)

    settings = get_settings()

    assert settings.agent_model_id == "global.anthropic.claude-sonnet-4-6"
    assert settings.synthesis_model_id == "global.anthropic.claude-sonnet-4-6"


def test_split_model_overrides_are_independent(monkeypatch):
    monkeypatch.setenv("BEDROCK_CHAT_MODEL_ID", "legacy-model")
    monkeypatch.setenv("BEDROCK_AGENT_MODEL_ID", "planner-model")
    monkeypatch.setenv("BEDROCK_SYNTHESIS_MODEL_ID", "synthesis-model")

    settings = get_settings()

    assert settings.chat_model_id == "legacy-model"
    assert settings.agent_model_id == "planner-model"
    assert settings.synthesis_model_id == "synthesis-model"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("FTS_CANDIDATE_LIMIT", "0"),
        ("TRIGRAM_CANDIDATE_LIMIT", "5000"),
        ("SEMANTIC_CANDIDATE_LIMIT", "-1"),
        ("RERANK_CANDIDATE_LIMIT", "900"),
        ("RRF_K", "0"),
        ("HNSW_EF_SEARCH", "0"),
        ("VECTOR_DIM", "0"),
        ("BEDROCK_MAX_ATTEMPTS", "0"),
    ],
)
def test_every_bounded_setting_is_enforced(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError) as excinfo:
        get_settings()
    assert name in str(excinfo.value)


def test_unrecognized_boolean_spelling_raises_rather_than_disabling(monkeypatch):
    """A typo must not silently disable fail-closed reranking.

    `RERANK_REQUIRED=tru` used to normalize to `False`, because the old
    `_boolean` matched against an accept-list and treated every other
    spelling as false. That is a fail-open on a typo for a setting whose
    entire purpose is fail-closed reranking.

    The match string is `_boolean`'s own wording ("neither true nor false"),
    not just any `RuntimeError`: a numeric-bound failure elsewhere would also
    raise `RuntimeError` (`ConfigurationError` subclasses it) but would say
    "is not a valid int" or "is out of range" instead, so this cannot pass
    for the wrong reason.

    Falsifier: revert `_boolean` to the permissive membership test and this
    passes with `rerank_required` silently `False` instead of raising.
    """
    monkeypatch.setenv("RERANK_REQUIRED", "tru")

    with pytest.raises(ConfigurationError, match="neither true nor false") as excinfo:
        get_settings()

    assert "RERANK_REQUIRED" in str(excinfo.value)
    assert "tru" in str(excinfo.value)


def test_recognized_boolean_spellings_still_resolve(monkeypatch):
    """The accept-list itself must still work in both directions and case-fold.

    Pairs the rejection test above with a positive case: strictness must
    reject unrecognized spellings without narrowing the recognized ones.
    """
    monkeypatch.setenv("RERANK_REQUIRED", "NO")
    monkeypatch.setenv("ALLOW_DEVELOPMENT_EMBEDDINGS", "On")

    settings = get_settings()

    assert settings.rerank_required is False
    assert settings.allow_development_embeddings is True


def test_cors_origins_may_not_contain_a_wildcard(monkeypatch):
    """`CORS_ORIGINS=*` combined with credentials would echo any origin back.

    The match string is the guard's own wording ("wildcard origin"), not
    just any `RuntimeError`, so this cannot pass because an unrelated
    setting in the same env happened to be malformed.

    Falsifier: delete the `"*" in origins` guard in `get_settings` and this
    passes with a wildcard silently accepted.
    """
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173,*")

    with pytest.raises(ConfigurationError, match="wildcard origin") as excinfo:
        get_settings()

    assert "CORS_ORIGINS" in str(excinfo.value)


def test_cors_origins_without_a_wildcard_still_resolve(monkeypatch):
    """The positive twin: a normal origin list must not trip the new guard."""
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")

    settings = get_settings()

    assert settings.cors_origins == (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )


def test_cors_response_never_carries_the_credentials_header():
    """`allow_credentials=True` bought nothing: the API has no cookie/session auth.

    Checks the header on a real response rather than the middleware's
    constructor arguments, so this also proves Starlette does not add the
    header on its own. Paired with a positive assertion
    (`access-control-allow-origin` present) so this is not an absence-only
    check that would pass against a CORS middleware removed outright.

    Falsifier: restore `allow_credentials=True` on the `CORSMiddleware` call
    in `service/main.py` and this fails.
    """
    from fastapi.testclient import TestClient

    from service.main import app

    response = TestClient(app).get(
        "/api/health", headers={"Origin": "http://localhost:5173"}
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == (
        "http://localhost:5173"
    )
    assert "access-control-allow-credentials" not in response.headers
