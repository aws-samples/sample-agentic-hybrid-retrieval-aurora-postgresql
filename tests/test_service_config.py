"""A config that cannot serve a request must not yield a running process."""

from __future__ import annotations

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
    assert "localhost" not in dsn
    assert "127.0.0.1" not in dsn
    assert "rds.amazonaws.com" in dsn


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
