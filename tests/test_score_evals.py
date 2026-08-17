import json
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest

from scripts.score_evals import (
    measured_scorecard,
    product_retrieval_queries,
    query_set_sha256,
    ranked_result_sha256,
    run_scored_queries,
    search_with_db_retry,
    validate_release_checks,
    verify_scorecard,
)
from service.models import SearchRequest

ROOT = Path(__file__).resolve().parents[1]


class FakeRetrieval:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.queries = []

    def search(self, request):
        self.queries.append(request.query)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def search_response(product_id):
    return SimpleNamespace(
        results=[
            SimpleNamespace(
                product_id=product_id,
                signals=SimpleNamespace(final_rank=1),
            )
        ],
        search_event_id=f"event-{product_id}",
        diagnostics=SimpleNamespace(
            strategy="rrf_fusion+rerank+exact_sku_preservation",
            total_latency_ms=125,
        ),
    )


def scorecard(*, recall=0.8, mrr=0.7, ndcg=0.75):
    return {
        "query_set": "data/evals/canonical_queries.jsonl",
        "query_set_sha256": query_set_sha256(
            ROOT / "data" / "evals" / "canonical_queries.jsonl"
        ),
        "scored_query_set_sha256": "scored-query-set",
        "canonical_query_count": 20,
        "product_retrieval_query_count": 19,
        "excluded_agent_contract_queries": ["G-010"],
        "deterministic_release_checks": [],
        "ranked_result_sha256": "ranked-result-set",
        "k": 10,
        "models": {
            "embedding": "us.cohere.embed-v4:0",
            "rerank": "cohere.rerank-v3-5:0",
        },
        "source": {"revision": "a" * 40, "worktree_dirty": False},
        "dataset_manifest_sha256": "b" * 64,
        "retrieval_profile": {"rrf_k": 60},
        "hnsw_settings": {
            "ef_search": 100,
            "iterative_scan": "relaxed_order",
            "max_scan_tuples": 20000,
            "scan_mem_multiplier": 1,
        },
        "aurora_configuration": {
            "engine": "aurora-postgresql",
            "database_version": "18.3",
            "vector_extension_version": "0.8.1",
            "instance_class": "db.r8g.2xlarge",
        },
        "database_instance_id": "workshop-writer",
        "measured_at": "2026-08-15T00:00:00+00:00",
        "strategy": "rrf_fusion+rerank+exact_sku_preservation",
        "metrics": {
            "recall@10": recall,
            "mrr": mrr,
            "ndcg@10": ndcg,
        },
    }


def test_scorecard_accepts_equal_or_improved_measured_metrics():
    baseline = scorecard()
    measured = scorecard(recall=0.85, mrr=0.72, ndcg=0.8)

    verify_scorecard(measured, baseline)


def test_committed_scorecard_keeps_per_query_and_ranked_result_provenance():
    baseline = json.loads(
        (ROOT / "data" / "evals" / "canonical_scorecard.json").read_text()
    )

    assert (
        len(baseline["per_query_metrics"]) == baseline["product_retrieval_query_count"]
    )
    assert {row["query_id"] for row in baseline["per_query_metrics"]} == {
        f"G-{number:03d}" for number in range(1, 21)
    } - {"G-010"}
    assert len(baseline["ranked_result_sha256"]) == 64
    assert len(baseline["dataset_manifest_sha256"]) == 64
    assert baseline["source"]["revision"]
    assert isinstance(baseline["source"]["worktree_dirty"], bool)
    assert baseline["aurora_configuration"]["instance_class"]
    assert baseline["retrieval_profile"]["rrf_k"] > 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("query_set_sha256", "changed"),
        ("product_retrieval_query_count", 20),
        ("k", 20),
        ("models", {"embedding": "another-space", "rerank": "rerank"}),
        ("dataset_manifest_sha256", "changed"),
        ("retrieval_profile", {"rrf_k": 1}),
        ("hnsw_settings", {"ef_search": 1}),
        ("aurora_configuration", {"engine": "postgresql"}),
        ("database_instance_id", "different-writer"),
        ("strategy", "weighted_rrf_fusion+rerank+exact_sku_preservation"),
        ("ranked_result_sha256", "changed"),
    ],
)
def test_scorecard_refuses_unreviewed_provenance_drift(field, value):
    baseline = scorecard()
    measured = scorecard()
    measured[field] = value

    with pytest.raises(ValueError, match="drifted"):
        verify_scorecard(measured, baseline)


@pytest.mark.parametrize(
    ("metric", "value"),
    [
        ("recall@10", 0.79),
        ("mrr", 0.69),
        ("ndcg@10", 0.74),
    ],
)
def test_scorecard_refuses_metric_regressions(metric, value):
    baseline = scorecard()
    measured = scorecard()
    measured["metrics"][metric] = value

    with pytest.raises(ValueError, match=f"regressed for {metric}"):
        verify_scorecard(measured, baseline)


def test_scorecard_requires_source_revision_and_worktree_state():
    baseline = scorecard()
    measured = scorecard()
    measured["source"] = {"revision": "", "worktree_dirty": "unknown"}

    with pytest.raises(ValueError, match="source provenance is incomplete"):
        verify_scorecard(measured, baseline)


def test_scorecard_refuses_a_dirty_measured_source():
    baseline = scorecard()
    measured = scorecard()
    measured["source"]["worktree_dirty"] = True

    with pytest.raises(ValueError, match="source is dirty"):
        verify_scorecard(measured, baseline)


def test_scorecard_refuses_a_dirty_committed_baseline():
    baseline = scorecard()
    baseline["source"]["worktree_dirty"] = True

    with pytest.raises(ValueError, match="baseline was not captured from a clean"):
        verify_scorecard(scorecard(), baseline)


@pytest.mark.parametrize(
    ("revision", "dirty", "message"),
    [
        ("a" * 40, True, "clean committed source"),
        ("a7ddc1b", False, "full 40-character Git SHA"),
    ],
)
def test_scorecard_rejects_invalid_source_before_aurora_work(
    monkeypatch,
    tmp_path,
    revision,
    dirty,
    message,
):
    monkeypatch.setattr(
        "scripts.score_evals.get_settings",
        lambda: SimpleNamespace(
            source_revision=revision,
            source_worktree_dirty=dirty,
        ),
    )
    monkeypatch.setattr(
        "scripts.score_evals.connect",
        lambda: pytest.fail("Aurora should not be queried before source validation"),
    )

    with pytest.raises(ValueError, match=message):
        measured_scorecard(
            ROOT / "data" / "evals" / "canonical_queries.jsonl",
            tmp_path / "results.csv",
            k=10,
        )


def test_scorecard_refuses_a_baseline_with_intervening_code_changes(monkeypatch):
    baseline = scorecard()
    measured = scorecard()
    measured["source"]["revision"] = "c" * 40
    monkeypatch.setattr(
        "scripts.score_evals._scorecard_only_revision_delta",
        lambda baseline_revision, measured_revision: False,
    )

    with pytest.raises(ValueError, match="source revision drifted"):
        verify_scorecard(measured, baseline)


def test_scorecard_accepts_the_commit_that_only_records_the_baseline(monkeypatch):
    baseline = scorecard()
    measured = scorecard()
    measured["source"]["revision"] = "c" * 40
    monkeypatch.setattr(
        "scripts.score_evals._scorecard_only_revision_delta",
        lambda baseline_revision, measured_revision: True,
    )

    verify_scorecard(measured, baseline)


def test_scorecard_retries_only_a_transient_database_failure():
    retrieval = FakeRetrieval(
        [psycopg.OperationalError("connection reset by peer"), search_response(101)]
    )
    delays = []

    response = search_with_db_retry(
        retrieval,
        SearchRequest(query="travel headphones", limit=10),
        query_id="G-001",
        retry_delays=(0.25,),
        sleep=delays.append,
    )

    assert response.search_event_id == "event-101"
    assert retrieval.queries == ["travel headphones", "travel headphones"]
    assert delays == [0.25]


def test_scorecard_does_not_retry_a_non_database_failure():
    retrieval = FakeRetrieval([RuntimeError("reranker contract failed")])

    with pytest.raises(RuntimeError, match="reranker contract failed"):
        search_with_db_retry(
            retrieval,
            SearchRequest(query="travel headphones", limit=10),
            query_id="G-001",
            retry_delays=(0.25,),
            sleep=lambda _: None,
        )

    assert retrieval.queries == ["travel headphones"]


def test_scorecard_resumes_completed_queries_after_an_interruption(tmp_path):
    queries = [
        {"query_id": "G-001", "query": "travel headphones"},
        {"query_id": "G-002", "query": "office headphones"},
    ]
    checkpoint = tmp_path / "scorecard.checkpoint.json"
    identity = {"source": {"revision": "a" * 40}, "database": "writer"}
    interrupted = FakeRetrieval(
        [search_response(101), RuntimeError("model service unavailable")]
    )

    with pytest.raises(RuntimeError, match="model service unavailable"):
        run_scored_queries(
            queries,
            interrupted,
            k=10,
            checkpoint_path=checkpoint,
            checkpoint_identity=identity,
            retry_delays=(),
            sleep=lambda _: None,
        )

    resumed = FakeRetrieval([search_response(102)])
    ranked, rows = run_scored_queries(
        queries,
        resumed,
        k=10,
        checkpoint_path=checkpoint,
        checkpoint_identity=identity,
        retry_delays=(),
        sleep=lambda _: None,
    )

    assert resumed.queries == ["office headphones"]
    assert ranked == {"G-001": [(1, 101)], "G-002": [(1, 102)]}
    assert rows["G-001"][0]["search_event_id"] == "event-101"
    assert rows["G-002"][0]["search_event_id"] == "event-102"


def test_scorecard_refuses_a_checkpoint_from_another_run_contract(tmp_path):
    queries = [{"query_id": "G-001", "query": "travel headphones"}]
    checkpoint = tmp_path / "scorecard.checkpoint.json"
    run_scored_queries(
        queries,
        FakeRetrieval([search_response(101)]),
        k=10,
        checkpoint_path=checkpoint,
        checkpoint_identity={"source": {"revision": "a" * 40}},
        retry_delays=(),
        sleep=lambda _: None,
    )

    with pytest.raises(ValueError, match="provenance drifted.*--restart"):
        run_scored_queries(
            queries,
            FakeRetrieval([]),
            k=10,
            checkpoint_path=checkpoint,
            checkpoint_identity={"source": {"revision": "b" * 40}},
            retry_delays=(),
            sleep=lambda _: None,
        )


def test_product_retrieval_scorecard_excludes_agent_contract_cases():
    queries = [
        {"query_id": "G-001"},
        {"query_id": "G-010", "evaluation_scope": "agent_contract"},
    ]

    scored, excluded = product_retrieval_queries(queries)

    assert [query["query_id"] for query in scored] == ["G-001"]
    assert excluded == ["G-010"]


def test_ranked_result_identity_is_stable_but_order_sensitive():
    first = {
        "G-002": [(2, 22), (1, 21)],
        "G-001": [(1, 11), (2, 12)],
    }
    same = {
        "G-001": [(2, 12), (1, 11)],
        "G-002": [(1, 21), (2, 22)],
    }
    changed = {
        "G-001": [(1, 12), (2, 11)],
        "G-002": [(1, 21), (2, 22)],
    }

    assert ranked_result_sha256(first) == ranked_result_sha256(same)
    assert ranked_result_sha256(first) != ranked_result_sha256(changed)


def test_scorecard_rejects_an_unknown_scope_with_a_fix():
    with pytest.raises(ValueError, match="Fix the canonical evaluation scope"):
        product_retrieval_queries(
            [{"query_id": "G-999", "evaluation_scope": "unbounded"}]
        )


def test_release_checks_prove_top_rank_and_top_k_membership():
    checks = validate_release_checks(
        [
            {
                "query_id": "G-001",
                "release_checks": [
                    {"type": "top_rank", "product_id": 17001},
                    {"type": "present_top_k", "product_id": 17002, "k": 2},
                ],
            }
        ],
        {"G-001": [(1, 17001), (2, 17002)]},
    )

    assert checks == [
        {"query_id": "G-001", "type": "top_rank", "product_id": 17001},
        {
            "query_id": "G-001",
            "type": "present_top_k",
            "product_id": 17002,
            "k": 2,
        },
    ]


def test_release_checks_fail_with_observed_results_and_a_fix():
    with pytest.raises(
        ValueError,
        match="requires product 17001 at final rank 1.*Fix the retrieval",
    ):
        validate_release_checks(
            [
                {
                    "query_id": "G-001",
                    "release_checks": [{"type": "top_rank", "product_id": 17001}],
                }
            ],
            {"G-001": [(1, 17002), (2, 17001)]},
        )
