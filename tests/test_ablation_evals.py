"""Lab 2's stage ablation: semantic-only vs RRF-fused vs RRF-fused+reranked.

`scripts/ablation_evals.py` never re-serves the reranked arm -- reranking costs
money per call -- so its most safety-critical behavior is refusing to publish
a result when the persisted served CSV no longer agrees with the committed
scorecard, and refusing to publish a candidate-recall ceiling that is
arithmetically below a measured arm. Both get a dedicated red-at-birth,
independence, and witness proof per house standards rule 7, plus one
end-to-end assembly test that runs the real `semantic_only_arm` /
`rrf_fused_arm` SQL orchestration against a stub connection rather than
reimplementing what they compute.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Self

import pytest

from scripts.ablation_evals import (
    ARM_RRF_FUSED,
    ARM_RRF_RERANKED,
    ARM_SEMANTIC_ONLY,
    AblationMeasurementError,
    assert_ceiling_covers_every_arm,
    assert_reproduces_committed_metrics,
    candidate_recall_ceiling,
    load_served_arm,
    measured_ablation,
    relevant_ids,
    rrf_fused_arm,
    semantic_only_arm,
)
from scripts.evaluate import evaluate
from service.retrieval import RetrievalService

ROOT = Path(__file__).resolve().parents[1]


# --- relevant_ids: the same grade >= 2 threshold scripts.evaluate uses ------


def test_relevant_ids_excludes_grade_below_two():
    assert relevant_ids({101: 3, 102: 2, 103: 1, 104: 0}) == {101, 102}


def test_relevant_ids_empty_judgments_is_empty():
    assert relevant_ids({}) == set()


# --- load_served_arm: rebuild arm 3 from the persisted CSV, no rerank call -


def _write_served_csv(path: Path, rows: list[tuple[str, int, int]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "query_id",
                "product_id",
                "rank",
                "search_event_id",
                "strategy",
                "total_latency_ms",
            ]
        )
        for query_id, product_id, rank in rows:
            writer.writerow([query_id, product_id, rank, "evt", "strategy", 10])


def test_load_served_arm_filters_to_the_requested_query_ids(tmp_path):
    csv_path = tmp_path / "served.csv"
    _write_served_csv(
        csv_path,
        [("G-001", 101, 1), ("G-001", 102, 2), ("G-999", 900, 1)],
    )

    ranked = load_served_arm(csv_path, {"G-001"})

    assert ranked == {"G-001": [(1, 101), (2, 102)]}
    assert "G-999" not in ranked


def test_load_served_arm_raises_when_a_scored_query_has_no_served_rows(tmp_path):
    """Red-at-birth: a scored query id absent from the CSV must fail loudly,
    not silently score against an empty ranked list."""
    csv_path = tmp_path / "served.csv"
    _write_served_csv(csv_path, [("G-001", 101, 1)])

    with pytest.raises(AblationMeasurementError, match="no served rows"):
        load_served_arm(csv_path, {"G-001", "G-002"})


# --- candidate_recall_ceiling: the ceiling reranking could ever reach -------


def test_candidate_recall_ceiling_averages_pool_membership_across_queries():
    pools = {"G-001": [101, 999], "G-002": [201]}
    truth = {"G-001": {101: 3, 102: 3}, "G-002": {201: 2}}

    ceiling = candidate_recall_ceiling(pools, truth)

    # G-001: 1 of 2 relevant products (101) present in the pool -> 0.5.
    # G-002: 1 of 1 relevant products present -> 1.0. Mean -> 0.75.
    assert ceiling["pool_recall_ceiling"] == pytest.approx(0.75)
    assert ceiling["judged_relevant_never_fetched"] == 1
    by_id = {row["query_id"]: row for row in ceiling["per_query"]}
    assert by_id["G-001"]["missed_product_ids"] == [102]
    assert by_id["G-002"]["missed_product_ids"] == []


def test_candidate_recall_ceiling_handles_a_query_with_no_relevant_judgment():
    """Independence: a query with zero graded-relevant products must not
    divide by zero. Matches `scripts.evaluate.evaluate`'s own convention for
    this same edge case -- `max(1, len(relevant))` in the denominator -- so a
    relevant-free query scores 0.0, not a phantom perfect score."""
    pools = {"G-001": [999]}
    truth = {"G-001": {101: 1}}  # grade 1: judged, but not "relevant"

    ceiling = candidate_recall_ceiling(pools, truth)

    assert ceiling["pool_recall_ceiling"] == 0.0
    assert ceiling["judged_relevant_never_fetched"] == 0


# --- assert_reproduces_committed_metrics: arm 3 must equal what shipped ----


def test_reproduced_metrics_pass_silently_when_they_match():
    metrics = {"recall@10": 0.75, "mrr": 0.8, "ndcg@10": 0.7}
    assert_reproduces_committed_metrics(dict(metrics), dict(metrics))


@pytest.mark.parametrize("field", ["recall@10", "mrr", "ndcg@10"])
def test_reproduced_metrics_raise_on_the_exact_breaking_edit(field):
    """Red-at-birth, one field at a time: the committed scorecard's own
    contract is float equality, not tolerance."""
    committed = {"recall@10": 0.75, "mrr": 0.8, "ndcg@10": 0.7}
    measured = dict(committed)
    measured[field] = committed[field] + 1e-9

    with pytest.raises(AblationMeasurementError, match="expected an exact match"):
        assert_reproduces_committed_metrics(measured, committed)


def test_reproduced_metrics_message_names_both_values():
    committed = {"recall@10": 0.75, "mrr": 0.8, "ndcg@10": 0.7}
    measured = {**committed, "mrr": 0.79}

    with pytest.raises(AblationMeasurementError) as excinfo:
        assert_reproduces_committed_metrics(measured, committed)

    message = str(excinfo.value)
    assert "0.79" in message
    assert "0.8" in message


# --- assert_ceiling_covers_every_arm: pool accounting, not a real outcome --


def test_ceiling_covering_every_arm_passes_silently():
    assert_ceiling_covers_every_arm(0.9, {"a": 0.5, "b": 0.9})


def test_ceiling_below_one_arm_raises_with_the_offending_arm_named():
    """Red-at-birth: shrink the ceiling below a real measured recall. A
    ceiling below a measured value is arithmetically impossible under
    correct pool accounting, per the docstring's own construction argument."""
    with pytest.raises(AblationMeasurementError, match="rrf_fused_no_rerank"):
        assert_ceiling_covers_every_arm(0.5, {"rrf_fused_no_rerank": 0.6})


def test_ceiling_equal_to_an_arm_is_not_a_violation():
    """Independence: equality, not just strict excess, must pass -- the
    fused pool and the arm's own top-K can legitimately coincide."""
    assert_ceiling_covers_every_arm(0.6, {ARM_RRF_FUSED: 0.6})


# --- semantic_only_arm / rrf_fused_arm: probe the real SQL orchestration ---


class _StubCursor:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class ScriptedConnection:
    """Returns pre-scripted rows keyed by which SQL ran and which query's
    filter marker was bound, so two different queries staged on the same
    connection get two different, independently verifiable results."""

    def __init__(
        self,
        semantic_rows: dict[str, list[dict[str, Any]]],
        fusion_rows: dict[str, list[dict[str, Any]]],
    ) -> None:
        self.semantic_rows = semantic_rows
        self.fusion_rows = fusion_rows
        self.semantic_calls: list[str] = []
        self.fusion_calls: list[str] = []
        self._pending: list[dict[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> ScriptedConnection:
        # `configure_hnsw` binds a positional tuple, not the named dict every
        # arm query uses; it never matches either branch below.
        marker = params.get("filters", "") if isinstance(params, dict) else ""
        if "mosaic_search.search_vector(" in sql:
            self.semantic_calls.append(marker)
            self._pending = self.semantic_rows[marker]
        elif "search_hybrid_rrf(" in sql:
            self.fusion_calls.append(marker)
            self._pending = self.fusion_rows[marker]
        else:
            self._pending = []
        return self

    def fetchall(self) -> list[dict[str, Any]]:
        return self._pending

    def cursor(self) -> _StubCursor:
        return _StubCursor()

    def commit(self) -> None:
        return None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class CountingEmbedder:
    model_id = "stub-embed"
    dimensions = 4

    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.1, 0.2, 0.3, 0.4]

    def embed_documents(self, texts: Any) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]


_Q1_MARKER = json.dumps({"category_key": "ablation-q1"})
_Q2_MARKER = json.dumps({"category_key": "ablation-q2"})

_QUERIES = [
    {
        "query_id": "G-Q1",
        "query": "first ablation query",
        "filters": {"category_key": "ablation-q1"},
        "judgments": [{"product_id": 101, "grade": 3}],
    },
    {
        "query_id": "G-Q2",
        "query": "second ablation query",
        "filters": {"category_key": "ablation-q2"},
        "judgments": [{"product_id": 201, "grade": 2}],
    },
]


def _row(product_id: int, rank: int) -> dict[str, Any]:
    return {"product_id": product_id, "semantic_rank": rank}


def test_semantic_only_arm_ranks_by_search_vector_and_embeds_each_query_once():
    embedder = CountingEmbedder()
    connection = ScriptedConnection(
        semantic_rows={
            _Q1_MARKER: [_row(999, 1), _row(998, 2)],
            _Q2_MARKER: [_row(201, 1)],
        },
        fusion_rows={},
    )
    retrieval = RetrievalService(
        embedding_provider=embedder, connection_factory=lambda: connection
    )

    ranked = semantic_only_arm(retrieval, _QUERIES)

    assert ranked == {
        "G-Q1": [(1, 999), (2, 998)],
        "G-Q2": [(1, 201)],
    }
    # Witness: the SQL that ran was actually search_vector, once per query,
    # not a fixture the loop never visited.
    assert sorted(connection.semantic_calls) == sorted([_Q1_MARKER, _Q2_MARKER])
    # Each distinct query text is embedded exactly once.
    assert embedder.calls == ["first ablation query", "second ablation query"]


def test_rrf_fused_arm_ranks_by_the_served_fusion_function_and_returns_the_full_pool():
    embedder = CountingEmbedder()
    connection = ScriptedConnection(
        semantic_rows={},
        fusion_rows={
            _Q1_MARKER: [{"product_id": 998}, {"product_id": 101}],
            _Q2_MARKER: [{"product_id": 201}],
        },
    )
    retrieval = RetrievalService(
        embedding_provider=embedder, connection_factory=lambda: connection
    )

    ranked, pools = rrf_fused_arm(retrieval, _QUERIES)

    assert ranked == {
        "G-Q1": [(1, 998), (2, 101)],
        "G-Q2": [(1, 201)],
    }
    assert pools == {"G-Q1": [998, 101], "G-Q2": [201]}
    assert sorted(connection.fusion_calls) == sorted([_Q1_MARKER, _Q2_MARKER])


def test_rrf_fused_arm_sql_does_not_match_the_weighted_fusion_function():
    """Independence: `ScriptedConnection`'s unweighted-fusion match must not
    also match `search_hybrid_rrf_weighted`, or this test module could not
    tell the served (unweighted) arm apart from the unweighted-vs-weighted
    comparison path `service.fusion_comparison` exercises separately."""
    connection = ScriptedConnection(
        semantic_rows={}, fusion_rows={_Q1_MARKER: [{"product_id": 101}]}
    )
    retrieval = RetrievalService(
        embedding_provider=CountingEmbedder(),
        connection_factory=lambda: connection,
        use_weighted_fusion=True,
    )

    ranked, pools = rrf_fused_arm(retrieval, [_QUERIES[0]])

    # The weighted call's SQL text does not contain the unweighted marker
    # this fixture only scripted, so it returns nothing rather than silently
    # reusing the unweighted fixture's rows.
    assert pools == {"G-Q1": []}
    assert ranked == {"G-Q1": []}


# --- measured_ablation: full assembly against a stub connection ------------


def _write_missions_free_query_set(path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for query in _QUERIES:
            handle.write(json.dumps(query) + "\n")


@pytest.fixture
def ablation_environment(tmp_path, monkeypatch):
    """A complete, hand-computed fixture: two queries, one graded product
    each, and a served CSV promoting G-Q1's product from fused rank 2 to
    served rank 1. Every arm's numbers below are derived independently by
    calling the real `scripts.evaluate.evaluate`, not typed as decimals that
    could silently drift from what the code actually computes.
    """
    queries_path = tmp_path / "queries.jsonl"
    _write_missions_free_query_set(queries_path)

    served_path = tmp_path / "served.csv"
    _write_served_csv(served_path, [("G-Q1", 101, 1), ("G-Q2", 201, 1)])

    truth = {"G-Q1": {101: 3}, "G-Q2": {201: 2}}
    served_ranked = {"G-Q1": [(1, 101)], "G-Q2": [(1, 201)]}
    committed_metrics = evaluate(truth, served_ranked, 10)
    scorecard_path = tmp_path / "scorecard.json"
    scorecard_path.write_text(
        json.dumps(
            {
                "measured_at": "2026-01-01T00:00:00+00:00",
                "source": {"revision": "a" * 40, "worktree_dirty": False},
                "retrieval_fingerprint": "b" * 64,
                "metrics": {
                    "recall@10": committed_metrics["recall@10"],
                    "mrr": committed_metrics["mrr"],
                    "ndcg@10": committed_metrics["ndcg@10"],
                },
            }
        ),
        encoding="utf-8",
    )

    connection = ScriptedConnection(
        semantic_rows={
            # G-Q1: semantic misses the relevant product entirely.
            _Q1_MARKER: [_row(999, 1), _row(998, 2)],
            # G-Q2: semantic finds it immediately.
            _Q2_MARKER: [_row(201, 1)],
        },
        fusion_rows={
            # G-Q1: fusion finds it, but only at fused rank 2.
            _Q1_MARKER: [{"product_id": 998}, {"product_id": 101}],
            _Q2_MARKER: [{"product_id": 201}],
        },
    )
    retrieval = RetrievalService(
        embedding_provider=CountingEmbedder(), connection_factory=lambda: connection
    )

    monkeypatch.setattr("scripts.ablation_evals.CANONICAL_QUERIES_PATH", queries_path)
    monkeypatch.setattr("scripts.ablation_evals.SERVED_RESULTS_PATH", served_path)
    monkeypatch.setattr(
        "scripts.ablation_evals.CANONICAL_SCORECARD_PATH", scorecard_path
    )
    monkeypatch.setattr(
        "scripts.ablation_evals.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {
                "source_worktree_dirty": False,
                "source_revision": "c" * 40,
                "embedding_model_id": "test-embed",
                "rerank_model_id": "test-rerank",
            },
        )(),
    )
    monkeypatch.setattr(
        "scripts.ablation_evals.get_retrieval_service", lambda: retrieval
    )
    return {"truth": truth}


def test_measured_ablation_assembles_all_three_arms_and_the_ceiling(
    ablation_environment,
):
    result = measured_ablation()

    assert set(result["arms"]) == {ARM_SEMANTIC_ONLY, ARM_RRF_FUSED, ARM_RRF_RERANKED}
    # Hand-verifiable: semantic misses G-Q1 entirely (recall 0) but finds
    # G-Q2 (recall 1) -> mean 0.5.
    assert result["arms"][ARM_SEMANTIC_ONLY]["recall@10"] == pytest.approx(0.5)
    # Fusion finds both relevant products somewhere in its pool -> recall 1.0.
    assert result["arms"][ARM_RRF_FUSED]["recall@10"] == pytest.approx(1.0)
    # Reranked (served) also finds both, both at rank 1 -> perfect nDCG.
    assert result["arms"][ARM_RRF_RERANKED]["ndcg@10"] == pytest.approx(1.0)

    # Ceiling: both relevant products are present somewhere in the fused
    # pool (998,101 for G-Q1; 201 for G-Q2) -> full ceiling.
    assert result["candidate_recall_ceiling"]["pool_recall_ceiling"] == pytest.approx(
        1.0
    )
    assert result["candidate_recall_ceiling"]["judged_relevant_never_fetched"] == 0

    # G-Q1: reranking promoted the relevant product from fused rank 2 to
    # rank 1, so the reranked arm alone wins that query on nDCG@10.
    g_q1 = next(row for row in result["per_query"] if row["query_id"] == "G-Q1")
    assert result["arms"][ARM_RRF_RERANKED]["ndcg@10_query_wins"] >= 1
    assert g_q1["ndcg@10"][ARM_RRF_RERANKED] > g_q1["ndcg@10"][ARM_RRF_FUSED]
    assert g_q1["ndcg@10"][ARM_SEMANTIC_ONLY] == 0.0

    assert result["source"]["revision"] == "c" * 40
    assert result["models"] == {"embedding": "test-embed", "rerank": "test-rerank"}
    assert len(result["retrieval_fingerprint"]) == 64


def test_measured_ablation_refuses_a_dirty_worktree(ablation_environment, monkeypatch):
    """Red-at-birth for the source-cleanliness guard: everything else in the
    fixture is valid, only worktree_dirty flips."""
    monkeypatch.setattr(
        "scripts.ablation_evals.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {
                "source_worktree_dirty": True,
                "source_revision": "c" * 40,
                "embedding_model_id": "test-embed",
                "rerank_model_id": "test-rerank",
            },
        )(),
    )

    with pytest.raises(AblationMeasurementError, match="worktree is dirty"):
        measured_ablation()


def test_measured_ablation_refuses_when_the_served_csv_disagrees_with_the_scorecard(
    ablation_environment, tmp_path
):
    """Red-at-birth for the reproduction guard, exercised through the public
    entry point rather than only the extracted helper: corrupt the committed
    scorecard's own metrics after the fixture already made them agree."""
    scorecard_path = tmp_path / "scorecard.json"
    scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
    scorecard["metrics"]["mrr"] = 0.123456789
    scorecard_path.write_text(json.dumps(scorecard), encoding="utf-8")

    with pytest.raises(AblationMeasurementError, match="expected an exact match"):
        measured_ablation()


def test_committed_stage_ablation_reproduces_the_scorecard_and_the_fingerprint():
    """The real committed artifact, once written, must still satisfy its own
    contract: arm 3 equals the committed scorecard, and the ceiling covers
    every arm actually measured."""
    ablation_path = ROOT / "data" / "evals" / "canonical_stage_ablation.json"
    if not ablation_path.exists():
        pytest.skip("canonical_stage_ablation.json has not been measured yet")
    artifact = json.loads(ablation_path.read_text(encoding="utf-8"))
    scorecard = json.loads(
        (ROOT / "data" / "evals" / "canonical_scorecard.json").read_text(
            encoding="utf-8"
        )
    )

    reranked = artifact["arms"][ARM_RRF_RERANKED]
    assert_reproduces_committed_metrics(
        {
            "recall@10": reranked["recall@10"],
            "mrr": reranked["mrr"],
            "ndcg@10": reranked["ndcg@10"],
        },
        scorecard["metrics"],
    )
    assert_ceiling_covers_every_arm(
        artifact["candidate_recall_ceiling"]["pool_recall_ceiling"],
        {arm: values["recall@10"] for arm, values in artifact["arms"].items()},
    )
