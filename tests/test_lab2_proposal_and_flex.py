"""Proposal and flex grading must judge decisions, not reward cheap passes.

These run without Aurora: they pin the proposal budget and decision rule, the
arithmetic the proposal grader uses, the committed cache's coverage, and the
flex grader's statement checks and tiers.
"""

import json
from pathlib import Path

import pytest

from scripts import flex_exercise, lab2_proposal
from scripts.lab_exercise import ExerciseError

ROOT = Path(__file__).resolve().parents[1]
VALID = {
    "change": {"fused_limit": 75},
    "criterion": {"min_exact_gain": 10, "max_queries_worse": 0},
    "decision": "adopt",
    "reason": "More Exact products reach the reranker within one billed unit.",
}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"fused_limit": 75, "rrf_k": 120}, "exactly one setting"),
        ({"fused_limit": 150}, "outside the budget"),
        ({"semantic_limit": 1000}, "outside the budget"),
        ({"weight_lexical": 2}, "change one of"),
        ({"rrf_k": "120"}, "change one of"),
    ],
)
def test_a_proposal_changes_one_setting_within_budget(change, message):
    with pytest.raises(lab2_proposal.ProposalError, match=message):
        lab2_proposal.validate({**VALID, "change": change})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("criterion", {"min_exact_gain": 1}, "criterion must state"),
        ("decision", "maybe", "adopt"),
        ("reason", " ", "reason"),
    ],
)
def test_a_proposal_states_its_rule_decision_and_reason(field, value, message):
    with pytest.raises(lab2_proposal.ProposalError, match=message):
        lab2_proposal.validate({**VALID, field: value})


def test_the_budget_is_one_billed_rerank_unit():
    assert lab2_proposal.SETTINGS["fused_limit"][1] == 100
    assert lab2_proposal.PRODUCTS_PER_SEARCH_UNIT == 100


def comparison(baseline: int, proposed: int, worse: int) -> dict:
    return {
        "exact_in_cutoff": {"baseline": baseline, "proposed": proposed},
        "queries_worse": worse,
    }


def test_the_decision_follows_the_stated_rule_in_both_directions():
    rule = {"min_exact_gain": 10, "max_queries_worse": 0}

    assert lab2_proposal.expected_decision(comparison(168, 192, 0), rule) == "adopt"
    assert lab2_proposal.expected_decision(comparison(168, 173, 0), rule) == "reject"
    assert lab2_proposal.expected_decision(comparison(168, 192, 1), rule) == "reject"


def test_fusion_reads_only_the_prefix_a_smaller_limit_allows():
    lists = {"fts": [[5, 1], [3, 2]], "trigram": [], "vector": [[3, 1], [9, 2]]}

    full = lab2_proposal.fuse(lists, 60, {"fts": 2, "trigram": 1, "vector": 2})
    trimmed = lab2_proposal.fuse(lists, 60, {"fts": 1, "trigram": 1, "vector": 1})

    assert full == [3, 5, 9]
    assert trimmed == [3, 5]


def test_sign_test_is_two_sided_and_capped():
    assert lab2_proposal.sign_test(0, 0) == 1.0
    assert lab2_proposal.sign_test(4, 0) == pytest.approx(0.125)
    assert lab2_proposal.sign_test(3, 3) == 1.0


def test_cache_covers_every_judged_query_at_the_largest_allowed_limits():
    cache = json.loads((ROOT / "data/evals/lab2_search_cache.json").read_text())
    subset = json.loads((ROOT / "data/evals/esci_judged_subset.json").read_text())

    assert set(cache["queries"]) == {str(q["query_id"]) for q in subset["queries"]}
    for setting, arm in lab2_proposal.ARM_OF.items():
        assert lab2_proposal.SETTINGS[setting][1] <= cache["limits"][arm]
    assert len(cache["chair_controls"]) == 4


HALFVEC_INDEX = (
    "CREATE INDEX alex_hp ON mosaic_catalog_search.product_document USING hnsw "
    "((embedding::halfvec(1024)) halfvec_cosine_ops) WHERE category_key = 'headphones';"
    "\nSET hnsw.ef_search = 400;"
)


def test_flex_accepts_an_expression_index_and_a_search_setting():
    create, name, ef_search = flex_exercise.parse_index(HALFVEC_INDEX)

    assert name == "alex_hp"
    assert ef_search == 400
    assert create.startswith("CREATE INDEX alex_hp")


@pytest.mark.parametrize(
    "text",
    [
        "DROP TABLE mosaic.product;",
        (
            "CREATE INDEX CONCURRENTLY x ON mosaic_catalog_search.product_document "
            "USING hnsw (embedding vector_cosine_ops) WHERE category_key = 'headphones';"
        ),
        (
            "CREATE INDEX x ON mosaic_catalog_search.product_document "
            "USING hnsw (embedding vector_cosine_ops);"
        ),
        "CREATE INDEX x ON mosaic.product USING btree (sku) WHERE true;",
        HALFVEC_INDEX + "\nSELECT 1;",
    ],
)
def test_flex_rejects_anything_but_one_partial_hnsw_index(text):
    with pytest.raises(ExerciseError):
        flex_exercise.parse_index(text)


def build(recall: float, ratio: float, size: int, uses: bool = True) -> dict:
    return {
        "recall": recall,
        "time_ratio": ratio,
        "index_bytes": size,
        "uses_index": uses,
    }


def test_flex_averages_builds_so_one_unlucky_build_does_not_fail():
    report = flex_exercise.summarize(
        "x", 400, [build(0.88, 0.1, 40), build(0.93, 0.1, 40)], 130
    )

    assert report["mean_recall"] == pytest.approx(0.905)
    assert report["fast"] and report["small"]


def test_flex_tiers_separate_fast_from_small_and_unused_indexes():
    fast_only = flex_exercise.summarize("x", None, [build(0.99, 0.1, 130)] * 2, 130)
    unused = flex_exercise.summarize("x", None, [build(1.0, 1.0, 40, False)] * 2, 130)

    assert fast_only["fast"] and not fast_only["small"]
    assert not unused["fast"]
    assert any("does not use x" in failure for failure in unused["failures"])
