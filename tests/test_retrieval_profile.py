"""Precedence and bounds for the yaml-sourced retrieval profile.

Env > yaml is the documented contract, so it is **tested** here rather than
asserted in prose. The bounds tests generalize Phase 1's fix: `BUSINESS_WEIGHT`
at 0.15 against a `le=0.05` bound reached the request path and returned an
unhandled 500 on every query. A limit of 0 or a negative `k` must now refuse to
start, in the same error class.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.retrieval_profile import (
    BOUNDS,
    RETRIEVAL_YAML,
    ProfileError,
    load_profile,
    parse_yaml,
)

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def yaml_copy(tmp_path: Path) -> Path:
    target = tmp_path / "retrieval.yaml"
    target.write_text(RETRIEVAL_YAML.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def test_the_shipped_yaml_loads_and_validates():
    profile = load_profile()
    assert profile.fts_limit == 120
    assert profile.trigram_limit == 80
    assert profile.semantic_limit == 150
    assert profile.rrf_k == 60
    assert profile.business_weight == 0.003
    assert profile.trigram_threshold == 0.20


def test_the_ported_weights_round_trip_by_key_name():
    """LOSS-3's values must arrive under the names they left workshop.json with."""
    profile = load_profile()
    assert profile.weight_lexical == 0.30
    assert profile.weight_semantic == 0.45
    assert profile.weight_trigram == 0.10


def test_business_signals_weight_is_not_a_fusion_weight():
    """0.15 is history, not configuration; it must not be loadable as a weight."""
    profile = load_profile()
    assert not hasattr(profile, "weight_business_signals")
    assert profile.business_weight <= 0.05


@pytest.mark.parametrize(
    ("env", "field", "value"),
    [
        ("FTS_CANDIDATE_LIMIT", "fts_limit", "77"),
        ("TRIGRAM_CANDIDATE_LIMIT", "trigram_limit", "41"),
        ("SEMANTIC_CANDIDATE_LIMIT", "semantic_limit", "99"),
        ("RRF_K", "rrf_k", "13"),
        ("RERANK_CANDIDATE_LIMIT", "fused_limit", "25"),
        ("HNSW_EF_SEARCH", "hnsw_ef_search", "64"),
        ("VECTOR_DIM", "vector_dimension", "512"),
    ],
)
def test_environment_overrides_the_yaml(monkeypatch, yaml_copy, env, field, value):
    """Precedence is env > yaml. Tested per overridable setting, not asserted."""
    baseline = getattr(load_profile(yaml_path=yaml_copy), field)
    monkeypatch.setenv(env, value)
    overridden = getattr(load_profile(yaml_path=yaml_copy), field)
    assert overridden == type(baseline)(value)
    assert overridden != baseline, f"{env} must differ from the yaml to prove it wins"


def test_an_empty_environment_variable_does_not_win(monkeypatch, yaml_copy):
    """An unset-looking override must fall through, not resolve to nothing."""
    monkeypatch.setenv("FTS_CANDIDATE_LIMIT", "   ")
    assert load_profile(yaml_path=yaml_copy).fts_limit == 120


@pytest.mark.parametrize(
    ("env", "bad"),
    [
        ("FTS_CANDIDATE_LIMIT", "0"),
        ("FTS_CANDIDATE_LIMIT", "-5"),
        ("FTS_CANDIDATE_LIMIT", "1001"),
        ("RRF_K", "0"),
        ("RRF_K", "-1"),
        ("BUSINESS_WEIGHT", "0.15"),
        ("BUSINESS_WEIGHT", "-0.01"),
        ("HNSW_EF_SEARCH", "0"),
        ("VECTOR_DIM", "0"),
        ("RERANK_CANDIDATE_LIMIT", "251"),
    ],
)
def test_an_out_of_range_override_refuses_to_start(monkeypatch, yaml_copy, env, bad):
    monkeypatch.setenv(env, bad)
    with pytest.raises(ProfileError) as excinfo:
        load_profile(yaml_path=yaml_copy)
    message = str(excinfo.value)
    assert bad.lstrip("-") in message or bad in message
    assert "found " in message and "fix: " in message


def test_a_non_numeric_override_refuses_to_start(monkeypatch, yaml_copy):
    monkeypatch.setenv("RRF_K", "sixty")
    with pytest.raises(ProfileError, match="not a int"):
        load_profile(yaml_path=yaml_copy)


@pytest.mark.parametrize("bound", [b for b in BOUNDS if b.env is None])
def test_yaml_only_settings_are_still_bounds_checked(yaml_copy, bound):
    """A value with no env override is still validated, or the bound is decoration."""
    text = yaml_copy.read_text(encoding="utf-8")
    leaf = bound.path.split(".")[-1]
    poisoned = "\n".join(
        f"{line.split(leaf)[0]}{leaf}: {bound.high + 1}"
        if line.strip().startswith(f"{leaf}:")
        else line
        for line in text.splitlines()
    )
    yaml_copy.write_text(poisoned + "\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(yaml_path=yaml_copy)


def test_a_missing_key_is_a_named_failure_not_a_silent_default(yaml_copy):
    """A default in code would be the fourth copy; absence must fail loudly."""
    text = yaml_copy.read_text(encoding="utf-8")
    yaml_copy.write_text(
        "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("rrf_k:")
        ),
        encoding="utf-8",
    )
    with pytest.raises(ProfileError, match="fusion.rrf_k"):
        load_profile(yaml_path=yaml_copy)


def test_a_missing_yaml_is_a_named_failure(tmp_path):
    with pytest.raises(ProfileError, match="no retrieval config"):
        load_profile(yaml_path=tmp_path / "absent.yaml")


def test_the_parser_refuses_a_construct_it_cannot_read():
    """Silently misreading a list would be worse than not supporting one."""
    with pytest.raises(ProfileError, match="YAML list"):
        parse_yaml("fusion:\n  weights:\n    - 0.3\n")


def test_the_parser_reads_nested_scalars_and_comments():
    tree = parse_yaml(
        "top: 1\nnested:\n  inner: 2.5\n  deeper:\n    leaf: 3  # trailing\n\n"
    )
    assert tree == {"top": 1, "nested": {"inner": 2.5, "deeper": {"leaf": 3}}}


def test_settings_reads_the_profile_rather_than_restating_it(monkeypatch):
    """service.config must carry no independent copy of these numbers."""
    from service.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("FTS_CANDIDATE_LIMIT", "88")
    try:
        assert get_settings().lexical_candidate_limit == 88
    finally:
        get_settings.cache_clear()


def test_configure_hnsw_arguments_are_explicitly_cast():
    """Regression: an integral float broke every live search.

    `scan_mem_multiplier: 1` in the yaml parses to `1.0`, where the previous
    hardcoded default was `1`. psycopg infers the SQL parameter type from the
    Python type, so `configure_hnsw`'s `real` argument resolved to `double
    precision`, no overload matched, and Aurora returned UndefinedFunction on
    every query. No unit test saw it — the probe that ran the production path
    did. The casts are the fix; this asserts they stay.
    """
    source = (REPO / "service" / "retrieval.py").read_text(encoding="utf-8")
    call = source.split("configure_hnsw(", 1)[1].split(")", 1)[0]
    for cast in ("::integer", "::text", "::real"):
        assert cast in call, f"configure_hnsw call lost its {cast} cast"


def test_retrieval_profile_model_defaults_come_from_the_yaml():
    from service.models import RetrievalProfile

    profile = RetrievalProfile()
    yaml_profile = load_profile()
    assert profile.fts_limit == yaml_profile.fts_limit
    assert profile.rrf_k == yaml_profile.rrf_k
    assert profile.business_weight == yaml_profile.business_weight
    assert profile.result_limit == yaml_profile.display_limit
