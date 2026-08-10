"""A config that cannot serve a request must not yield a running process.

`RetrievalProfile` bounds `business_weight` at `le=0.05`, but it is only
constructed per request. Before these checks existed, an out-of-range value in
the environment was accepted by `get_settings()` and escaped as an unhandled
HTTP 500 on every query, because `/api/search` catches `ClientError`,
`BotoCoreError` and `RuntimeError` but not `ValidationError`.

Since Phase 2 Unit C the values themselves come from `db/config/retrieval.yaml`
via `scripts.retrieval_profile`, which enforces the same bounds at load. These
checks assert the behavior through `get_settings`, which is the surface the
service reads, so they stay valid regardless of where the number is stored.
"""

from __future__ import annotations

import pytest

from service.config import ConfigurationError, get_settings
from service.models import RetrievalProfile


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """`get_settings` is `lru_cache`d, so each case needs a cold read."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_business_weight_above_bound_is_refused(monkeypatch):
    monkeypatch.setenv("BUSINESS_WEIGHT", "0.15")
    with pytest.raises(ConfigurationError) as excinfo:
        get_settings()
    message = str(excinfo.value)
    # The message has to name the parameter, the offending value and the bound,
    # or the reader cannot act on it.
    assert "BUSINESS_WEIGHT" in message
    assert "0.15" in message
    assert "0.05" in message


def test_shipped_example_value_is_accepted_and_validates(monkeypatch):
    monkeypatch.setenv("BUSINESS_WEIGHT", "0.003")
    settings = get_settings()
    assert settings.business_weight == pytest.approx(0.003)
    # The same number must survive the per-request model that rejected 0.15.
    profile = RetrievalProfile(business_weight=settings.business_weight)
    assert profile.business_weight == pytest.approx(0.003)


@pytest.mark.parametrize("value", ["-0.1", "abc"])
def test_negative_and_non_numeric_values_are_refused(monkeypatch, value):
    monkeypatch.setenv("BUSINESS_WEIGHT", value)
    with pytest.raises(ConfigurationError):
        get_settings()


def test_an_empty_override_falls_through_to_the_yaml(monkeypatch):
    """Deliberate change in Phase 2 Unit C: `BUSINESS_WEIGHT=` is not a value.

    Before the yaml became the single source, an empty variable reached
    `float("")` and refused to start. That was right when the fallback was a
    string literal in this module, because there was nothing else to fall back
    to. It is wrong now: an empty override is the *absence* of an override, and
    the value it falls through to is the validated yaml one.

    The property that mattered is preserved. The Phase 1 crash was an
    out-of-range value reaching the request path, not an empty one, and an empty
    variable can no longer produce an unvalidated config. What it avoids is a
    generated `.env` with an uninterpolated `BUSINESS_WEIGHT=` line taking the
    whole API down over a setting the yaml already answers.
    """
    monkeypatch.setenv("BUSINESS_WEIGHT", "")
    assert get_settings().business_weight == pytest.approx(0.003)


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
        "BUSINESS_WEIGHT",
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
