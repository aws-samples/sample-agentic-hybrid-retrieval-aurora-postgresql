import json
from pathlib import Path

import pytest

from scripts.score_evals import (
    product_retrieval_queries,
    query_set_sha256,
    ranked_result_sha256,
    validate_release_checks,
    verify_scorecard,
)

ROOT = Path(__file__).resolve().parents[1]


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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("query_set_sha256", "changed"),
        ("product_retrieval_query_count", 20),
        ("k", 20),
        ("models", {"embedding": "another-space", "rerank": "rerank"}),
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
