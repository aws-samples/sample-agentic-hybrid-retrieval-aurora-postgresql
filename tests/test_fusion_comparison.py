"""The substrate assertion must fail when the two fusion functions diverge.

House bar: a green check is not evidence on its own. The perturbation proven by
hand against Aurora — cap one arm differently in the weighted function — is kept
here as a permanent fixture, driven through a stub connection so it runs without
a database.

The stub is legitimate under "probes run the production path" because what is
under test is the *assertion*, not retrieval. The live-path proof is the recorded
red/green run against Aurora; this guards the assertion's logic against a future
edit that would make it unable to fail.
"""

from __future__ import annotations

import json
from typing import Any, Self

import pytest

from service.fusion_comparison import (
    FULL_POOL_LIMIT,
    FusionComparisonService,
    SubstrateError,
)
from service.models import SearchFilters
from service.retrieval import RetrievalService


def row(product_id: int, score: float) -> dict[str, Any]:
    return {
        "product_id": product_id,
        "fts_rank": 1,
        "trigram_rank": None,
        "semantic_rank": 2,
        "rrf_score": score,
        "provenance": {},
    }


class StubCursor:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.execute_params: list[Any] = []
        self.executemany_rows: list[Any] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append(sql)
        self.execute_params.append(params)

    def executemany(self, sql: str, rows: Any) -> None:
        self.executed.append(sql)
        self.executemany_rows.append(list(rows))

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class StubConnection:
    """Returns a scripted result per query, so divergence can be staged."""

    def __init__(self, unweighted: list[dict], weighted: list[dict]) -> None:
        self.unweighted = unweighted
        self.weighted = weighted
        self.commits = 0
        self.cursor_obj = StubCursor()

    def execute(self, sql: str, params: Any = None) -> StubConnection:
        self._last = (
            self.weighted if "search_hybrid_rrf_weighted" in sql else self.unweighted
        )
        self._params = params
        return self

    def fetchall(self) -> list[dict]:
        return self._last

    def cursor(self) -> StubCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.commits += 1

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class StubEmbedder:
    model_id = "stub"
    dimensions = 4

    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.1, 0.2, 0.3, 0.4]

    def embed_documents(self, texts: Any) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]


def service(unweighted: list[dict], weighted: list[dict]) -> FusionComparisonService:
    connection = StubConnection(unweighted, weighted)
    return FusionComparisonService(
        embedding_provider=StubEmbedder(),
        connection_factory=lambda: connection,
    )


IDENTICAL_UNWEIGHTED = [row(1, 0.9), row(2, 0.8), row(3, 0.7)]
# Same IDs, different order: what a weight change is supposed to produce.
IDENTICAL_WEIGHTED = [row(2, 0.95), row(1, 0.85), row(3, 0.6)]


def test_identical_sets_in_different_order_out_is_a_pass():
    result = service(IDENTICAL_UNWEIGHTED, IDENTICAL_WEIGHTED).compare(
        "mesh chair", SearchFilters(domain="home_office"), persist=False
    )
    assert result.candidate_sets_identical is True
    assert result.orders_differ is True
    assert result.candidate_count == 3
    assert result.unweighted_order == [1, 2, 3]
    assert result.weighted_order == [2, 1, 3]


@pytest.mark.parametrize(
    ("weighted", "reason"),
    [
        ([row(1, 0.9), row(2, 0.8)], "one arm capped lower: candidate missing"),
        ([row(1, 0.9), row(2, 0.8), row(3, 0.7), row(4, 0.6)], "extra candidate"),
        ([row(1, 0.9), row(2, 0.8), row(9, 0.7)], "different candidate substituted"),
        ([], "weighted arm returned nothing"),
    ],
)
def test_a_diverged_candidate_set_raises_rather_than_comparing(weighted, reason):
    """The perturbation proven red against Aurora, kept permanent."""
    with pytest.raises(SubstrateError) as excinfo:
        service(IDENTICAL_UNWEIGHTED, weighted).compare(
            "mesh chair", SearchFilters(), persist=False
        )
    assert "different candidate sets" in str(excinfo.value), reason


def test_the_substrate_failure_names_the_values_and_a_fix():
    """House error style, same as the gates."""
    with pytest.raises(SubstrateError) as excinfo:
        service(IDENTICAL_UNWEIGHTED, [row(1, 0.9)]).compare(
            "mesh chair", SearchFilters(), persist=False
        )
    message = str(excinfo.value)
    assert "found " in message and "fix: " in message
    assert "3 vs 1" in message


def test_the_comparison_reads_the_untruncated_pool():
    """Comparing served windows would fail a healthy substrate on every call.

    Both functions apply `LIMIT result_limit` after fusion, so two different
    orderings truncated at the same depth necessarily disagree about the tail —
    measured at 36 of 50 in common while the full pools were identical at 250.
    """
    connection = StubConnection(IDENTICAL_UNWEIGHTED, IDENTICAL_WEIGHTED)
    FusionComparisonService(
        embedding_provider=StubEmbedder(), connection_factory=lambda: connection
    ).compare("mesh chair", SearchFilters(), top_k=2, persist=False)
    assert connection._params["result_limit"] == FULL_POOL_LIMIT
    assert FULL_POOL_LIMIT > 350, "must exceed the summed arm caps"


def test_both_functions_receive_identical_arguments():
    """Same caps, same threshold, same embedding — or the pools differ by input."""
    captured: list[dict] = []

    class Capturing(StubConnection):
        def execute(self, sql: str, params: Any = None):
            if "search_hybrid_rrf" in sql:
                captured.append(dict(params))
            return super().execute(sql, params)

    connection = Capturing(IDENTICAL_UNWEIGHTED, IDENTICAL_WEIGHTED)
    FusionComparisonService(
        embedding_provider=StubEmbedder(), connection_factory=lambda: connection
    ).compare("mesh chair", SearchFilters(), persist=False)

    assert len(captured) == 2
    shared = (
        "embedding",
        "filters",
        "rrf_k",
        "fts_limit",
        "trigram_limit",
        "semantic_limit",
        "result_limit",
        "trigram_threshold",
    )
    for key in shared:
        assert captured[0][key] == captured[1][key], key


def test_rank_delta_sign_means_moved_up():
    result = service(IDENTICAL_UNWEIGHTED, IDENTICAL_WEIGHTED).compare(
        "mesh chair", SearchFilters(), persist=False
    )
    by_id = {c.product_id: c for c in result.candidates}
    assert by_id[2].rank_delta == -1, "product 2 rose from #2 to #1"
    assert by_id[1].rank_delta == 1, "product 1 fell from #1 to #2"
    assert by_id[3].rank_delta == 0
    assert result.moved_count == 2


def test_weights_come_from_the_yaml_not_from_literals():
    """No coefficient may be invented in code; the tripwire enforces the rest."""
    from scripts.retrieval_profile import load_profile

    profile = load_profile()
    result = service(IDENTICAL_UNWEIGHTED, IDENTICAL_WEIGHTED).compare(
        "mesh chair", SearchFilters(), persist=False
    )
    assert result.weights == {
        "lexical": profile.weight_lexical,
        "semantic": profile.weight_semantic,
        "trigram": profile.weight_trigram,
    }
    assert result.rrf_k == profile.rrf_k


def test_persistence_writes_the_run_and_every_candidate_in_one_transaction():
    connection = StubConnection(IDENTICAL_UNWEIGHTED, IDENTICAL_WEIGHTED)
    FusionComparisonService(
        embedding_provider=StubEmbedder(), connection_factory=lambda: connection
    ).compare("mesh chair", SearchFilters(), persist=True)
    written = " ".join(connection.cursor_obj.executed)
    assert "INSERT INTO mosaic.fusion_comparison " in written
    assert "INSERT INTO mosaic.fusion_comparison_candidate" in written
    assert connection.commits == 1


def test_persistence_keeps_full_orders_when_the_response_is_truncated():
    connection = StubConnection(IDENTICAL_UNWEIGHTED, IDENTICAL_WEIGHTED)
    result = FusionComparisonService(
        embedding_provider=StubEmbedder(), connection_factory=lambda: connection
    ).compare("mesh chair", SearchFilters(), top_k=1, persist=True)

    run_params = connection.cursor_obj.execute_params[0]
    candidate_rows = connection.cursor_obj.executemany_rows[0]
    assert result.unweighted_order == [1]
    assert result.weighted_order == [2]
    assert run_params[10] == [1, 2, 3]
    assert run_params[11] == [2, 1, 3]
    assert len(candidate_rows) == 3


def test_the_weighted_sql_declares_no_literal_coefficients():
    """Weights arrive as parameters; a literal in the body would be a fourth copy."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "db" / "sql" / "09_search_functions.sql"
    ).read_text(encoding="utf-8")
    body = source.split("search_hybrid_rrf_weighted", 1)[1]
    body = body.split("$$;", 1)[0]
    for coefficient in ("0.30", "0.45", "0.10"):
        occurrences = body.count(f"DEFAULT {coefficient}")
        assert occurrences <= 1, f"{coefficient} appears outside the signature"
    assert "weight_lexical *" in body
    assert "weight_semantic *" in body
    assert "weight_trigram *" in body


def test_the_schema_carries_everything_phase_4_recompute_needs():
    """rrf_recomputes must need zero schema change; assert the columns exist."""
    from pathlib import Path

    schema = (
        Path(__file__).resolve().parents[1] / "db" / "sql" / "12_telemetry.sql"
    ).read_text(encoding="utf-8")
    table = schema.split("mosaic.fusion_comparison_candidate", 1)[1]
    for column in (
        "fts_rank",
        "trigram_rank",
        "semantic_rank",
        "unweighted_rrf_score",
        "weighted_rrf_score",
        "unweighted_rank",
        "weighted_rank",
    ):
        assert column in table, f"recompute needs {column}"
    # The inputs the run used, not whatever the yaml holds at assertion time.
    run = schema.split("CREATE TABLE IF NOT EXISTS mosaic.fusion_comparison ", 1)[1]
    assert "rrf_k" in run and "weights" in run


def test_the_served_default_is_unweighted():
    """The flip is a recorded decision. A default that drifts is the failure mode."""
    from service.retrieval import STRATEGY, WEIGHTED_STRATEGY, RetrievalService

    assert RetrievalService().use_weighted_fusion is False
    assert STRATEGY == "rrf_fusion+rerank+exact_sku_preservation"
    assert "weighted" in WEIGHTED_STRATEGY


def test_the_strategy_names_the_fusion_that_ran():
    """Every surface labels what happened; nothing spells the method out itself."""
    from service.retrieval import STRATEGY, WEIGHTED_STRATEGY, RetrievalService

    assert RetrievalService()._strategy() == STRATEGY
    assert RetrievalService(use_weighted_fusion=True)._strategy() == WEIGHTED_STRATEGY


def test_query_embeddings_are_cached_per_service_instance():
    embedder = StubEmbedder()
    retrieval = RetrievalService(embedding_provider=embedder)

    assert retrieval.embed_query("  mesh\n chair ") == [0.1, 0.2, 0.3, 0.4]
    assert retrieval.embed_query("mesh chair") == [0.1, 0.2, 0.3, 0.4]
    assert embedder.queries == ["mesh chair"]


def test_fusion_mode_is_not_request_controlled():
    """A per-request flag would let a caller flip fusion without a decision."""
    from service.models import SearchRequest

    assert "use_weighted_fusion" not in SearchRequest.model_fields
    assert "fusion" not in SearchRequest.model_fields


def test_fusion_mode_is_not_an_environment_setting(monkeypatch):
    """An env var would be exactly the drift the spec forbids."""
    from service.config import Settings, get_settings

    assert not any(
        "weight" in f and "business" not in f for f in Settings.__annotations__
    )
    monkeypatch.setenv("USE_WEIGHTED_FUSION", "1")
    get_settings.cache_clear()
    try:
        assert RetrievalService().use_weighted_fusion is False
    finally:
        get_settings.cache_clear()


def test_the_profile_carries_the_weights_and_threshold_for_both_functions():
    """Both fusion calls must read one profile, or an arm's pool can diverge."""
    from scripts.retrieval_profile import load_profile
    from service.models import RetrievalProfile

    profile, yaml_profile = RetrievalProfile(), load_profile()
    assert profile.trigram_threshold == yaml_profile.trigram_threshold
    assert profile.weight_lexical == yaml_profile.weight_lexical
    assert profile.weight_semantic == yaml_profile.weight_semantic
    assert profile.weight_trigram == yaml_profile.weight_trigram


def test_filters_reach_the_sql_as_json():
    connection = StubConnection(IDENTICAL_UNWEIGHTED, IDENTICAL_WEIGHTED)
    FusionComparisonService(
        embedding_provider=StubEmbedder(), connection_factory=lambda: connection
    ).compare(
        "mesh chair",
        SearchFilters(domain="home_office", in_stock_only=True),
        persist=False,
    )
    sent = json.loads(connection._params["filters"])
    assert sent["domain"] == "home_office"
    assert sent["in_stock_only"] is True


def test_fusion_comparison_normalizes_the_sql_and_embedding_query():
    connection = StubConnection(IDENTICAL_UNWEIGHTED, IDENTICAL_WEIGHTED)
    embedder = StubEmbedder()
    FusionComparisonService(
        embedding_provider=embedder,
        connection_factory=lambda: connection,
    ).compare("  mesh\n  chair  ", persist=False)

    assert embedder.queries == ["mesh chair"]
    assert connection._params["query"] == "mesh chair"
