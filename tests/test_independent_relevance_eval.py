"""Offline tests for the independent relevance corpus runner and metrics.

No DATABASE_URL is used anywhere in this file. `run_queries` is exercised
against a fake retrieval service (mirroring `tests/test_score_evals.py`'s
`FakeRetrieval`), never a real `RetrievalService`, and the metrics helpers
operate on hand-built `QueryOutcome` fixtures.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.independent_relevance_eval import (
    QueryOutcome,
    build_report,
    classify_queries,
    load_independent_relevance_queries,
    run_queries,
)


def make_query(
    query_id="Q-1",
    *,
    cohort_category="headphones",
    cohort_intent="semantic_intent",
    judgments=(),
    hard_negative_ids=(),
    expect_no_relevant_results=False,
    filters=None,
):
    return {
        "query_id": query_id,
        "query": f"query text for {query_id}",
        "dataset_id": "reviews-2023-500k-v1",
        "cohort_category": cohort_category,
        "cohort_intent": cohort_intent,
        "filters": filters or {},
        "expect_no_relevant_results": expect_no_relevant_results,
        "judgments": list(judgments),
        "hard_negative_ids": list(hard_negative_ids),
    }


def make_judgment(product_id, grade, status="reviewed", rationale=None):
    return {
        "product_id": product_id,
        "grade": grade,
        "status": status,
        "source": "data/evals/real_catalog_lab_products.json#" + str(product_id),
        "rationale": rationale or ("x" * 25),
    }


# ---------------------------------------------------------------------------
# Corpus loading: malformed and mismatched records must fail clearly.
# ---------------------------------------------------------------------------


def write_jsonl(tmp_path, records):
    import json

    path = tmp_path / "queries.jsonl"
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    return path


def test_loader_rejects_duplicate_query_ids(tmp_path):
    record = make_query(judgments=[make_judgment(1, 3)])
    path = write_jsonl(tmp_path, [record, record])

    with pytest.raises(ValueError, match="Duplicate independent relevance query_id"):
        load_independent_relevance_queries(path)


def test_loader_rejects_unknown_judgment_status(tmp_path):
    bad = make_query(judgments=[make_judgment(1, 3, status="unverified")])
    path = write_jsonl(tmp_path, [bad])

    with pytest.raises(ValueError, match="invalid judgment status"):
        load_independent_relevance_queries(path)


def test_loader_rejects_out_of_range_grade(tmp_path):
    bad = make_query(judgments=[make_judgment(1, 5)])
    path = write_jsonl(tmp_path, [bad])

    with pytest.raises(ValueError, match="invalid grade"):
        load_independent_relevance_queries(path)


def test_loader_rejects_non_integer_product_id(tmp_path):
    bad = make_query(judgments=[make_judgment("not-an-id", 3)])
    path = write_jsonl(tmp_path, [bad])

    with pytest.raises(TypeError, match="non-integer product_id"):
        load_independent_relevance_queries(path)


def test_loader_rejects_hard_negative_with_nonzero_grade(tmp_path):
    bad = make_query(
        judgments=[make_judgment(1, 3), make_judgment(2, 2)],
        hard_negative_ids=[2],
    )
    path = write_jsonl(tmp_path, [bad])

    with pytest.raises(ValueError, match="non-zero judgment"):
        load_independent_relevance_queries(path)


def test_loader_rejects_hard_negative_referencing_unjudged_product(tmp_path):
    bad = make_query(judgments=[make_judgment(1, 3)], hard_negative_ids=[999])
    path = write_jsonl(tmp_path, [bad])

    with pytest.raises(ValueError, match="unjudged product"):
        load_independent_relevance_queries(path)


def test_loader_rejects_unsatisfiable_query_with_a_relevant_judgment(tmp_path):
    bad = make_query(judgments=[make_judgment(1, 3)], expect_no_relevant_results=True)
    path = write_jsonl(tmp_path, [bad])

    with pytest.raises(ValueError, match="marked unsatisfiable"):
        load_independent_relevance_queries(path)


def test_loader_rejects_missing_required_field(tmp_path):
    bad = make_query(judgments=[make_judgment(1, 3)])
    del bad["cohort_intent"]
    path = write_jsonl(tmp_path, [bad])

    with pytest.raises(ValueError, match="missing required fields"):
        load_independent_relevance_queries(path)


def test_loader_rejects_unknown_cohort_intent(tmp_path):
    bad = make_query(judgments=[make_judgment(1, 3)], cohort_intent="mystery")
    path = write_jsonl(tmp_path, [bad])

    with pytest.raises(ValueError, match="unknown cohort_intent"):
        load_independent_relevance_queries(path)


# ---------------------------------------------------------------------------
# Classification: unsatisfiable / answerable / answerable_reviewed / gap.
# ---------------------------------------------------------------------------


def test_classify_queries_separates_every_tier():
    unsatisfiable = make_query(
        "Q-UNSAT", judgments=[make_judgment(1, 0)], expect_no_relevant_results=True
    )
    reviewed = make_query("Q-REVIEWED", judgments=[make_judgment(1, 3, "reviewed")])
    provisional_only = make_query(
        "Q-PROVISIONAL", judgments=[make_judgment(1, 3, "provisional")]
    )
    gap = make_query("Q-GAP", judgments=[make_judgment(1, 1, "reviewed")])

    classification = classify_queries([unsatisfiable, reviewed, provisional_only, gap])

    assert classification.unsatisfiable == ["Q-UNSAT"]
    assert classification.judgment_gap == ["Q-GAP"]
    assert set(classification.answerable_all) == {"Q-REVIEWED", "Q-PROVISIONAL"}
    assert classification.answerable_reviewed == ["Q-REVIEWED"]


# ---------------------------------------------------------------------------
# Metric fixtures: a known bad ranking and an empty-relevance case.
# ---------------------------------------------------------------------------


def test_bad_ranking_produces_bad_metrics_not_a_silent_pass():
    """A ranking that buries the relevant product and surfaces the hard
    negative first must score badly, proving the metric pipeline is sensitive
    rather than vacuously green (house standard: prove the gate can fail)."""
    query = make_query(
        "Q-BAD",
        judgments=[
            make_judgment(100, 3, "reviewed"),
            make_judgment(200, 0, "reviewed"),
        ],
        hard_negative_ids=[200],
    )
    queries_by_id = {query["query_id"]: query}
    bad_outcome = {
        "Q-BAD": QueryOutcome(
            query_id="Q-BAD",
            result_ids=[200, 999, 998, 997, 996, 995, 994, 993, 992, 100],
            result_count=10,
            search_event_id="e1",
            strategy="rrf_fusion+rerank+exact_sku_preservation",
            latency_ms=50.0,
        )
    }
    from scripts.independent_relevance_eval import _relevance_tier

    result = _relevance_tier(
        queries_by_id, bad_outcome, ["Q-BAD"], reviewed_only=False, k=10
    )
    assert result["metrics"]["recall@10"] == 1.0  # target is present at rank 10
    assert result["metrics"]["mrr"] == pytest.approx(0.1)  # but buried at rank 10
    assert result["metrics"]["ndcg@10"] < 0.5  # heavily discounted by position

    good_outcome = {
        "Q-BAD": QueryOutcome(
            query_id="Q-BAD",
            result_ids=[100, 200],
            result_count=2,
            search_event_id="e2",
            strategy="rrf_fusion+rerank+exact_sku_preservation",
            latency_ms=50.0,
        )
    }
    good_result = _relevance_tier(
        queries_by_id, good_outcome, ["Q-BAD"], reviewed_only=False, k=10
    )
    assert good_result["metrics"]["mrr"] == 1.0
    assert good_result["metrics"]["ndcg@10"] == 1.0


def test_empty_relevance_case_is_excluded_from_relevance_metrics():
    """An unsatisfiable query must never enter Recall/MRR/nDCG -- there is no
    relevant item to rank, so the metric is undefined, not zero."""
    unsatisfiable = make_query(
        "Q-EMPTY", judgments=[make_judgment(1, 0)], expect_no_relevant_results=True
    )
    classification = classify_queries([unsatisfiable])

    assert classification.answerable_all == []
    assert classification.answerable_reviewed == []
    assert classification.unsatisfiable == ["Q-EMPTY"]


def test_empty_relevance_case_with_clean_response_is_reported_correct():
    from scripts.independent_relevance_eval import _empty_result_behavior

    query = make_query(
        "Q-EMPTY",
        judgments=[make_judgment(1, 0)],
        expect_no_relevant_results=True,
        hard_negative_ids=[1],
    )
    queries_by_id = {query["query_id"]: query}
    classification = classify_queries([query])
    clean = {
        "Q-EMPTY": QueryOutcome("Q-EMPTY", [], 0, "e", "strategy", 10.0),
    }

    behavior = _empty_result_behavior(queries_by_id, clean, classification)

    assert behavior["unsatisfiable_returned_zero_results"] == 1
    assert behavior["unsatisfiable_returned_hard_negative"] == 0


def test_empty_relevance_case_leaking_a_hard_negative_is_flagged():
    from scripts.independent_relevance_eval import _empty_result_behavior

    query = make_query(
        "Q-EMPTY",
        judgments=[make_judgment(1, 0)],
        expect_no_relevant_results=True,
        hard_negative_ids=[1],
    )
    queries_by_id = {query["query_id"]: query}
    classification = classify_queries([query])
    leaked = {
        "Q-EMPTY": QueryOutcome("Q-EMPTY", [1, 2, 3], 3, "e", "strategy", 10.0),
    }

    behavior = _empty_result_behavior(queries_by_id, leaked, classification)

    assert behavior["unsatisfiable_returned_hard_negative"] == 1
    assert behavior["unsatisfiable_returned_zero_results"] == 0


# ---------------------------------------------------------------------------
# Hard-negative eligibility violations.
# ---------------------------------------------------------------------------


def test_hard_negative_violation_reports_its_rank():
    from scripts.independent_relevance_eval import _hard_negative_violations

    query = make_query(
        "Q-1",
        judgments=[make_judgment(1, 3), make_judgment(2, 0)],
        hard_negative_ids=[2],
    )
    queries_by_id = {"Q-1": query}
    outcomes = {"Q-1": QueryOutcome("Q-1", [1, 2], 2, "e", "s", 1.0)}

    violations = _hard_negative_violations(queries_by_id, outcomes)

    assert violations == [{"query_id": "Q-1", "leaked_product_ids": [2], "ranks": [2]}]


def test_no_violation_when_hard_negative_is_absent():
    from scripts.independent_relevance_eval import _hard_negative_violations

    query = make_query(
        "Q-1",
        judgments=[make_judgment(1, 3), make_judgment(2, 0)],
        hard_negative_ids=[2],
    )
    queries_by_id = {"Q-1": query}
    outcomes = {"Q-1": QueryOutcome("Q-1", [1], 1, "e", "s", 1.0)}

    assert _hard_negative_violations(queries_by_id, outcomes) == []


# ---------------------------------------------------------------------------
# run_queries: failures must not crash the batch, and must be excluded.
# ---------------------------------------------------------------------------


class FakeRetrieval:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def search(self, request):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def fake_response(product_ids, *, latency_ms=42.0):
    return SimpleNamespace(
        results=[SimpleNamespace(product_id=pid) for pid in product_ids],
        search_event_id="event-id",
        diagnostics=SimpleNamespace(
            strategy="rrf_fusion+rerank+exact_sku_preservation",
            total_latency_ms=latency_ms,
        ),
    )


def test_run_queries_records_a_failure_without_aborting_the_batch():
    ok_query = make_query("Q-OK", judgments=[make_judgment(1, 3)])
    bad_query = make_query("Q-BAD", judgments=[make_judgment(1, 3)])
    retrieval = FakeRetrieval([fake_response([1]), RuntimeError("boom")])

    outcomes, failures = run_queries(
        [ok_query, bad_query], retrieval, k=10, retry_delays=(), sleep=lambda _: None
    )

    assert "Q-OK" in outcomes
    assert "Q-BAD" not in outcomes
    assert failures == [
        {"query_id": "Q-BAD", "error_type": "RuntimeError", "error_message": "boom"}
    ]


def test_run_queries_preserves_service_return_order_as_rank():
    query = make_query("Q-1", judgments=[make_judgment(1, 3), make_judgment(2, 2)])
    retrieval = FakeRetrieval([fake_response([2, 1])])

    outcomes, failures = run_queries(
        [query], retrieval, k=10, retry_delays=(), sleep=lambda _: None
    )

    assert failures == []
    assert outcomes["Q-1"].result_ids == [2, 1]
    assert outcomes["Q-1"].latency_ms == 42.0


# ---------------------------------------------------------------------------
# End-to-end report assembly over a small synthetic corpus.
# ---------------------------------------------------------------------------


def test_build_report_separates_failures_relevance_violations_and_latency(tmp_path):
    answerable = make_query("Q-A", judgments=[make_judgment(1, 3, "reviewed")])
    provisional = make_query("Q-P", judgments=[make_judgment(2, 3, "provisional")])
    unsatisfiable = make_query(
        "Q-U",
        judgments=[make_judgment(3, 0)],
        expect_no_relevant_results=True,
        hard_negative_ids=[3],
    )
    failing = make_query("Q-F", judgments=[make_judgment(4, 3)])
    queries = [answerable, provisional, unsatisfiable, failing]
    import json

    path = tmp_path / "queries.jsonl"
    path.write_text(
        "\n".join(json.dumps(query) for query in queries) + "\n", encoding="utf-8"
    )

    outcomes = {
        "Q-A": QueryOutcome("Q-A", [1], 1, "e1", "s", 30.0),
        "Q-P": QueryOutcome("Q-P", [2], 1, "e2", "s", 50.0),
        "Q-U": QueryOutcome("Q-U", [], 0, "e3", "s", 10.0),
    }
    failures = [{"query_id": "Q-F", "error_type": "RuntimeError", "error_message": "x"}]

    report = build_report(queries, outcomes, failures, k=10, queries_path=path)

    assert report["denominator"]["queries_attempted"] == 4
    assert report["denominator"]["queries_failed"] == 1
    assert report["denominator"]["unsatisfiable_query_count"] == 1
    # Q-A and Q-F both carry a reviewed grade>=2 judgment by corpus definition;
    # Q-F failing to run is a *scoring-time* exclusion, checked separately below.
    assert report["denominator"]["answerable_reviewed_only_query_count"] == 2
    assert report["failures"] == failures
    assert report["relevance"]["all_inclusive"]["scored_query_count"] == 2
    assert report["relevance"]["reviewed_only"]["scored_query_count"] == 1
    assert report["relevance"]["reviewed_only"]["excluded_due_to_failure"] == ["Q-F"]
    assert report["empty_result_behavior"]["unsatisfiable_returned_zero_results"] == 1
    assert report["latency"]["sample_count"] == 3
    assert set(report["by_cohort_category"]) == {"headphones"}
