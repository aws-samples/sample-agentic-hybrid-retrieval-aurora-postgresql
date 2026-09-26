"""Offline tests for the independent relevance corpus runner and metrics.

No DATABASE_URL is used anywhere in this file. `run_queries` is exercised
against a fake retrieval service (mirroring `tests/test_score_evals.py`'s
`FakeRetrieval`), never a real `RetrievalService`, and the metrics helpers
operate on hand-built `QueryOutcome` fixtures. The ESCI held-out readiness
tests use small synthetic stand-ins for `esci_judged_subset.json` and
`canonical_queries.jsonl`, never real ESCI data.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts.independent_relevance_eval import (
    ESCI_LABEL_TO_GRADE,
    QueryOutcome,
    _canonical_judged_product_ids,
    _mission_anchor_product_ids,
    build_report,
    classify_queries,
    compute_anchor_overlap,
    esci_grade,
    load_independent_relevance_queries,
    require_disjoint_from_tuning_sources,
    run_queries,
    tuning_source_query_id_overlap,
)

#: Real reference sets, loaded once, so `make_judgment` can auto-derive the
#: *correct* anchor_overlap for whatever product_id a test happens to pick
#: instead of every test having to avoid colliding with real catalog/mission
#: ids (canonical_queries.jsonl uses small synthetic-legacy ids like 1-5 that
#: would otherwise collide with a test's placeholder product_id).
_MISSION_IDS = _mission_anchor_product_ids()
_CANONICAL_IDS = _canonical_judged_product_ids()


def ranked(*product_ids):
    """Rank-1..N tuples in the given order, for outcomes with no rank quirk."""
    return list(enumerate(product_ids, 1))


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


def make_judgment(
    product_id,
    grade,
    status="agent_grounded",
    *,
    anchor_overlap=None,
    rationale=None,
    reviewed_by=None,
    reviewed_on=None,
):
    if anchor_overlap is None and isinstance(product_id, int):
        anchor_overlap = compute_anchor_overlap(
            product_id, mission_ids=_MISSION_IDS, canonical_ids=_CANONICAL_IDS
        )
    judgment = {
        "product_id": product_id,
        "grade": grade,
        "status": status,
        "anchor_overlap": anchor_overlap,
        "source": "data/evals/real_catalog_lab_products.json#" + str(product_id),
        "rationale": rationale or ("x" * 25),
    }
    if reviewed_by is not None:
        judgment["reviewed_by"] = reviewed_by
    if reviewed_on is not None:
        judgment["reviewed_on"] = reviewed_on
    return judgment


def write_jsonl(tmp_path, records, name="queries.jsonl"):
    path = tmp_path / name
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    return path


# ---------------------------------------------------------------------------
# Corpus loading: malformed and mismatched records must fail clearly.
# ---------------------------------------------------------------------------


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


def test_loader_rejects_reviewed_status_without_review_provenance(tmp_path):
    """'reviewed' is reserved for a human or independent second party; claiming
    it without reviewed_by/reviewed_on must fail, not silently pass as if an
    agent's own claim were a review."""
    bad = make_query(judgments=[make_judgment(1, 3, status="reviewed")])
    path = write_jsonl(tmp_path, [bad])

    with pytest.raises(ValueError, match="without review provenance"):
        load_independent_relevance_queries(path)


def test_loader_accepts_reviewed_status_with_review_provenance(tmp_path):
    good = make_query(
        judgments=[
            make_judgment(
                1,
                3,
                status="reviewed",
                reviewed_by="a.reviewer",
                reviewed_on="2026-09-27",
            )
        ]
    )
    path = write_jsonl(tmp_path, [good])

    loaded = load_independent_relevance_queries(path)

    assert loaded[0]["judgments"][0]["status"] == "reviewed"


def test_loader_rejects_anchor_overlap_that_disagrees_with_the_cross_reference(
    tmp_path,
):
    """1277987 is a live mission target (data/evals/mosaic_labs_missions.json);
    claiming it has no anchor overlap must fail against the real cross-reference
    files, not just accept whatever the record asserts."""
    bad = make_query(judgments=[make_judgment(1277987, 3, anchor_overlap="none")])
    path = write_jsonl(tmp_path, [bad])

    with pytest.raises(ValueError, match="anchor_overlap"):
        load_independent_relevance_queries(path)


# ---------------------------------------------------------------------------
# compute_anchor_overlap: pure function, synthetic reference sets.
# ---------------------------------------------------------------------------


def test_compute_anchor_overlap_prioritizes_mission_over_canonical():
    mission_ids = {10}
    canonical_ids = {10, 20}

    assert (
        compute_anchor_overlap(10, mission_ids=mission_ids, canonical_ids=canonical_ids)
        == "mission"
    )
    assert (
        compute_anchor_overlap(20, mission_ids=mission_ids, canonical_ids=canonical_ids)
        == "canonical"
    )
    assert (
        compute_anchor_overlap(30, mission_ids=mission_ids, canonical_ids=canonical_ids)
        == "none"
    )


# ---------------------------------------------------------------------------
# Classification: unsatisfiable / answerable[tier] / judgment_gap.
# ---------------------------------------------------------------------------


def test_classify_queries_separates_every_tier():
    unsatisfiable = make_query(
        "Q-UNSAT", judgments=[make_judgment(1, 0)], expect_no_relevant_results=True
    )
    grounded = make_query(
        "Q-GROUNDED", judgments=[make_judgment(1, 3, "agent_grounded")]
    )
    inferred_only = make_query(
        "Q-INFERRED", judgments=[make_judgment(1, 3, "agent_inferred")]
    )
    gap = make_query("Q-GAP", judgments=[make_judgment(1, 1, "agent_grounded")])

    classification = classify_queries([unsatisfiable, grounded, inferred_only, gap])

    assert classification.unsatisfiable == ["Q-UNSAT"]
    assert classification.judgment_gap == ["Q-GAP"]
    assert set(classification.answerable["all_inclusive"]) == {
        "Q-GROUNDED",
        "Q-INFERRED",
    }
    assert classification.answerable["agent_grounded_only"] == ["Q-GROUNDED"]
    assert classification.answerable["certified"] == []


def test_classify_queries_anchor_free_tier_uses_only_non_overlapping_products():
    overlapping = make_query(
        "Q-OVERLAP", judgments=[make_judgment(1, 3, anchor_overlap="mission")]
    )
    independent = make_query(
        "Q-FREE", judgments=[make_judgment(2, 3, anchor_overlap="none")]
    )

    classification = classify_queries([overlapping, independent])

    assert classification.answerable["anchor_free"] == ["Q-FREE"]
    assert set(classification.answerable["all_inclusive"]) == {"Q-OVERLAP", "Q-FREE"}


# ---------------------------------------------------------------------------
# Metric fixtures: a known bad ranking and an empty-relevance case.
# ---------------------------------------------------------------------------


def test_bad_ranking_produces_bad_metrics_not_a_silent_pass():
    """A ranking that buries the relevant product and surfaces the hard
    negative first must score badly, proving the metric pipeline is sensitive
    rather than vacuously green (house standard: prove the gate can fail)."""
    query = make_query(
        "Q-BAD",
        judgments=[make_judgment(100, 3), make_judgment(200, 0)],
        hard_negative_ids=[200],
    )
    queries_by_id = {query["query_id"]: query}
    bad_outcome = {
        "Q-BAD": QueryOutcome(
            query_id="Q-BAD",
            ranked_product_ids=ranked(200, 999, 998, 997, 996, 995, 994, 993, 992, 100),
            result_count=10,
            search_event_id="e1",
            strategy="rrf_fusion+rerank+exact_sku_preservation",
            latency_ms=50.0,
        )
    }
    from scripts.independent_relevance_eval import TIER_PREDICATES, _relevance_tier

    result = _relevance_tier(
        queries_by_id,
        bad_outcome,
        ["Q-BAD"],
        predicate=TIER_PREDICATES["all_inclusive"],
        k=10,
    )
    assert result["metrics"]["recall@10"] == 1.0  # target is present at rank 10
    assert result["metrics"]["mrr"] == pytest.approx(0.1)  # but buried at rank 10
    assert result["metrics"]["ndcg@10"] < 0.5  # heavily discounted by position

    good_outcome = {
        "Q-BAD": QueryOutcome(
            query_id="Q-BAD",
            ranked_product_ids=ranked(100, 200),
            result_count=2,
            search_event_id="e2",
            strategy="rrf_fusion+rerank+exact_sku_preservation",
            latency_ms=50.0,
        )
    }
    good_result = _relevance_tier(
        queries_by_id,
        good_outcome,
        ["Q-BAD"],
        predicate=TIER_PREDICATES["all_inclusive"],
        k=10,
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

    assert classification.answerable["all_inclusive"] == []
    assert classification.answerable["certified"] == []
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
        "Q-EMPTY": QueryOutcome("Q-EMPTY", ranked(1, 2, 3), 3, "e", "strategy", 10.0),
    }

    behavior = _empty_result_behavior(queries_by_id, leaked, classification)

    assert behavior["unsatisfiable_returned_hard_negative"] == 1
    assert behavior["unsatisfiable_returned_zero_results"] == 0


# ---------------------------------------------------------------------------
# Hard-negative eligibility violations: ranks come from final_rank.
# ---------------------------------------------------------------------------


def test_hard_negative_violation_reports_its_final_rank():
    from scripts.independent_relevance_eval import _hard_negative_violations

    query = make_query(
        "Q-1",
        judgments=[make_judgment(1, 3), make_judgment(2, 0)],
        hard_negative_ids=[2],
    )
    queries_by_id = {"Q-1": query}
    outcomes = {"Q-1": QueryOutcome("Q-1", ranked(1, 2), 2, "e", "s", 1.0)}

    violations = _hard_negative_violations(queries_by_id, outcomes)

    assert violations == [{"query_id": "Q-1", "leaked_product_ids": [2], "ranks": [2]}]


def test_hard_negative_violation_uses_final_rank_not_list_position():
    """A permuted final_rank must be honoured: product 2 is returned FIRST in
    the raw list but its own final_rank says it is actually rank 5."""
    from scripts.independent_relevance_eval import _hard_negative_violations

    query = make_query(
        "Q-1",
        judgments=[make_judgment(1, 3), make_judgment(2, 0)],
        hard_negative_ids=[2],
    )
    queries_by_id = {"Q-1": query}
    # ranked_product_ids is (final_rank, product_id); list order is irrelevant.
    outcomes = {
        "Q-1": QueryOutcome("Q-1", [(5, 2), (1, 1)], 2, "e", "s", 1.0),
    }

    violations = _hard_negative_violations(queries_by_id, outcomes)

    assert violations == [{"query_id": "Q-1", "leaked_product_ids": [2], "ranks": [5]}]


def test_no_violation_when_hard_negative_is_absent():
    from scripts.independent_relevance_eval import _hard_negative_violations

    query = make_query(
        "Q-1",
        judgments=[make_judgment(1, 3), make_judgment(2, 0)],
        hard_negative_ids=[2],
    )
    queries_by_id = {"Q-1": query}
    outcomes = {"Q-1": QueryOutcome("Q-1", ranked(1), 1, "e", "s", 1.0)}

    assert _hard_negative_violations(queries_by_id, outcomes) == []


# ---------------------------------------------------------------------------
# run_queries: failures must not crash the batch, and rank comes from
# signals.final_rank, never from list position (score_evals.py's own pattern).
# ---------------------------------------------------------------------------


class FakeRetrieval:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def search(self, request):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def fake_response(final_ranks_by_product, *, latency_ms=42.0):
    """`final_ranks_by_product`: ordered [(product_id, final_rank), ...],
    deliberately allowed to be non-sequential in list order."""
    return SimpleNamespace(
        results=[
            SimpleNamespace(
                product_id=product_id, signals=SimpleNamespace(final_rank=final_rank)
            )
            for product_id, final_rank in final_ranks_by_product
        ],
        search_event_id="event-id",
        diagnostics=SimpleNamespace(
            strategy="rrf_fusion+rerank+exact_sku_preservation",
            total_latency_ms=latency_ms,
        ),
    )


def test_run_queries_records_a_failure_without_aborting_the_batch():
    ok_query = make_query("Q-OK", judgments=[make_judgment(1, 3)])
    bad_query = make_query("Q-BAD", judgments=[make_judgment(1, 3)])
    retrieval = FakeRetrieval([fake_response([(1, 1)]), RuntimeError("boom")])

    outcomes, failures = run_queries(
        [ok_query, bad_query], retrieval, k=10, retry_delays=(), sleep=lambda _: None
    )

    assert "Q-OK" in outcomes
    assert "Q-BAD" not in outcomes
    assert failures == [
        {"query_id": "Q-BAD", "error_type": "RuntimeError", "error_message": "boom"}
    ]


def test_run_queries_reads_rank_from_final_rank_not_list_position():
    """The service can return results in an order that does not match
    final_rank once downstream filtering runs; the runner must read the
    authoritative field, exactly as scripts/score_evals.py does."""
    query = make_query("Q-1", judgments=[make_judgment(1, 3), make_judgment(2, 2)])
    # Listed as [2, 1] but product 2's own final_rank is 2, product 1's is 1.
    retrieval = FakeRetrieval([fake_response([(2, 2), (1, 1)])])

    outcomes, failures = run_queries(
        [query], retrieval, k=10, retry_delays=(), sleep=lambda _: None
    )

    assert failures == []
    assert outcomes["Q-1"].result_ids == [1, 2]
    assert outcomes["Q-1"].rank_by_product == {2: 2, 1: 1}
    assert outcomes["Q-1"].latency_ms == 42.0


def test_run_queries_drops_results_with_no_signals():
    query = make_query("Q-1", judgments=[make_judgment(1, 3)])
    response = SimpleNamespace(
        results=[SimpleNamespace(product_id=1, signals=None)],
        search_event_id="event-id",
        diagnostics=SimpleNamespace(strategy="s", total_latency_ms=1.0),
    )
    retrieval = FakeRetrieval([response])

    outcomes, failures = run_queries(
        [query], retrieval, k=10, retry_delays=(), sleep=lambda _: None
    )

    assert failures == []
    assert outcomes["Q-1"].ranked_product_ids == []
    assert outcomes["Q-1"].result_count == 1  # returned, just unranked


# ---------------------------------------------------------------------------
# End-to-end report assembly over a small synthetic corpus.
# ---------------------------------------------------------------------------


def test_build_report_separates_failures_relevance_violations_and_latency(tmp_path):
    answerable = make_query(
        "Q-A",
        judgments=[
            make_judgment(1, 3, "reviewed", reviewed_by="r", reviewed_on="2026-09-27")
        ],
    )
    grounded_only = make_query("Q-P", judgments=[make_judgment(2, 3, "agent_grounded")])
    unsatisfiable = make_query(
        "Q-U",
        judgments=[make_judgment(3, 0)],
        expect_no_relevant_results=True,
        hard_negative_ids=[3],
    )
    failing = make_query(
        "Q-F",
        judgments=[
            make_judgment(4, 3, "reviewed", reviewed_by="r", reviewed_on="2026-09-27")
        ],
    )
    queries = [answerable, grounded_only, unsatisfiable, failing]
    path = write_jsonl(tmp_path, queries)

    outcomes = {
        "Q-A": QueryOutcome("Q-A", ranked(1), 1, "e1", "s", 30.0),
        "Q-P": QueryOutcome("Q-P", ranked(2), 1, "e2", "s", 50.0),
        "Q-U": QueryOutcome("Q-U", [], 0, "e3", "s", 10.0),
    }
    failures = [{"query_id": "Q-F", "error_type": "RuntimeError", "error_message": "x"}]

    report = build_report(queries, outcomes, failures, k=10, queries_path=path)

    assert report["denominator"]["queries_attempted"] == 4
    assert report["denominator"]["queries_failed"] == 1
    assert report["denominator"]["unsatisfiable_query_count"] == 1
    # Q-A and Q-F both carry a certified grade>=2 judgment by corpus definition;
    # Q-F failing to run is a *scoring-time* exclusion, checked separately below.
    assert report["denominator"]["answerable_query_counts"]["certified"] == 2
    assert report["denominator"]["answerable_query_counts"]["all_inclusive"] == 3
    assert report["failures"] == failures
    assert report["relevance"]["all_inclusive"]["scored_query_count"] == 2
    assert report["relevance"]["certified"]["scored_query_count"] == 1
    assert report["relevance"]["certified"]["excluded_due_to_failure"] == ["Q-F"]
    assert report["empty_result_behavior"]["unsatisfiable_returned_zero_results"] == 1
    assert report["latency"]["sample_count"] == 3
    assert set(report["by_cohort_category"]) == {"headphones"}
    assert "anchor_free" in report["by_cohort_category"]["headphones"]["relevance"]


# ---------------------------------------------------------------------------
# ESCI held-out readiness: grade mapping and tuning/canonical disjointness,
# both against small synthetic fixtures, never real ESCI data.
# ---------------------------------------------------------------------------


def test_esci_grade_mapping_matches_the_documented_scale():
    assert ESCI_LABEL_TO_GRADE == {"E": 3, "S": 2, "C": 1, "I": 0}
    assert esci_grade("E") == 3
    assert esci_grade("S") == 2
    assert esci_grade("C") == 1
    assert esci_grade("I") == 0


def test_esci_grade_rejects_an_unknown_label():
    with pytest.raises(ValueError, match="Unknown ESCI label"):
        esci_grade("X")


def _write_synthetic_esci_subset(tmp_path, query_ids):
    path = tmp_path / "esci_judged_subset.json"
    path.write_text(
        json.dumps({"queries": [{"query_id": qid} for qid in query_ids]}),
        encoding="utf-8",
    )
    return path


def _write_synthetic_canonical(tmp_path, query_ids):
    path = tmp_path / "canonical_queries.jsonl"
    path.write_text(
        "\n".join(json.dumps({"query_id": qid}) for qid in query_ids) + "\n",
        encoding="utf-8",
    )
    return path


def test_tuning_source_overlap_is_empty_for_a_disjoint_held_out_corpus(tmp_path):
    esci_subset_path = _write_synthetic_esci_subset(tmp_path, [101, 102])
    canonical_path = _write_synthetic_canonical(tmp_path, ["G-001", "G-002"])
    records = [
        {"query_id": "ESCI-HELDOUT-201", "esci_query_id": 201},
        {"query_id": "ESCI-HELDOUT-202", "esci_query_id": 202},
    ]

    overlap = tuning_source_query_id_overlap(
        records, esci_subset_path=esci_subset_path, canonical_path=canonical_path
    )

    assert overlap == {"esci_tuning_set": [], "canonical_scorecard": []}
    require_disjoint_from_tuning_sources(
        records, esci_subset_path=esci_subset_path, canonical_path=canonical_path
    )  # must not raise


def test_tuning_source_overlap_catches_a_reused_esci_tuning_id(tmp_path):
    esci_subset_path = _write_synthetic_esci_subset(tmp_path, [101, 102])
    canonical_path = _write_synthetic_canonical(tmp_path, ["G-001"])
    records = [{"query_id": "ESCI-HELDOUT-101", "esci_query_id": 101}]

    with pytest.raises(ValueError, match="collide with a source"):
        require_disjoint_from_tuning_sources(
            records, esci_subset_path=esci_subset_path, canonical_path=canonical_path
        )


def test_tuning_source_overlap_catches_a_reused_canonical_query_id(tmp_path):
    esci_subset_path = _write_synthetic_esci_subset(tmp_path, [101])
    canonical_path = _write_synthetic_canonical(tmp_path, ["G-001"])
    records = [{"query_id": "G-001", "esci_query_id": 999}]

    with pytest.raises(ValueError, match="collide with a source"):
        require_disjoint_from_tuning_sources(
            records, esci_subset_path=esci_subset_path, canonical_path=canonical_path
        )


def test_tuning_source_overlap_requires_esci_query_id_on_every_record(tmp_path):
    esci_subset_path = _write_synthetic_esci_subset(tmp_path, [101])
    canonical_path = _write_synthetic_canonical(tmp_path, ["G-001"])
    records = [{"query_id": "ESCI-HELDOUT-201"}]

    with pytest.raises(ValueError, match="missing esci_query_id"):
        tuning_source_query_id_overlap(
            records, esci_subset_path=esci_subset_path, canonical_path=canonical_path
        )
