"""The independent relevance corpus must stay separate, graded, and honest.

This corpus (`data/evals/independent_relevance_queries.jsonl`) exists to probe
relevance beyond the canonical 21-query teaching set and beyond the ESCI
k-tuning sweep. These tests pin its coverage design, its judgment-status
vocabulary, and its grounding in a citable catalog source, so it cannot quietly
regress into an unreviewed or a duplicated fixture.
"""

import json
from pathlib import Path

from scripts.independent_relevance_eval import (
    COHORT_INTENTS,
    JUDGMENT_STATUSES,
    load_independent_relevance_queries,
)

ROOT = Path(__file__).resolve().parents[1]
QUERY_PATH = ROOT / "data" / "evals" / "independent_relevance_queries.jsonl"
QUERIES = load_independent_relevance_queries(QUERY_PATH)

CANONICAL_QUERIES = [
    json.loads(line)
    for line in (ROOT / "data/evals/canonical_queries.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
]
ESCI_SUBSET = json.loads(
    (ROOT / "data/evals/esci_judged_subset.json").read_text(encoding="utf-8")
)
REAL_CATALOG_PRODUCTS = {
    product["product_id"]
    for product in json.loads(
        (ROOT / "data/evals/real_catalog_lab_products.json").read_text(encoding="utf-8")
    )["products"]
}


def test_corpus_is_disjoint_from_the_canonical_and_esci_query_sets():
    """No shared query text with the release scorecard or the k-tuning sweep.

    Overlap here would mean this corpus quietly re-scores queries that already
    gate a release or that already picked `rrf_k`, rather than adding new
    coverage.
    """
    irc_text = {query["query"].strip().lower() for query in QUERIES}
    canonical_text = {
        query["query"].strip().lower()
        for query in CANONICAL_QUERIES
        if "query" in query
    }
    esci_text = {case["query"].strip().lower() for case in ESCI_SUBSET["queries"]}
    assert not (irc_text & canonical_text)
    assert not (irc_text & esci_text)
    assert {query["query_id"] for query in QUERIES}.isdisjoint(
        query["query_id"] for query in CANONICAL_QUERIES
    )


def test_coverage_design_is_a_full_four_by_six_grid():
    """One query per (cohort_category x cohort_intent) cell, no more, no fewer.

    This is a coverage probe, not a statistically powered sample: see the
    module docstring in `scripts/independent_relevance_eval.py` for why 24 is
    the deliberate size rather than a convenient one.
    """
    categories = {"headphones", "monitor", "chair", "general"}
    assert {query["cohort_category"] for query in QUERIES} == categories
    assert {query["cohort_intent"] for query in QUERIES} == COHORT_INTENTS
    cells = {(query["cohort_category"], query["cohort_intent"]) for query in QUERIES}
    assert len(cells) == len(categories) * len(COHORT_INTENTS) == 24
    assert len(QUERIES) == 24


def test_query_ids_are_unique_and_namespaced():
    ids = [query["query_id"] for query in QUERIES]
    assert len(set(ids)) == len(ids)
    assert all(query_id.startswith("IRC-") for query_id in ids)


def test_every_judgment_cites_a_status_and_a_grounded_source():
    """Every judgment declares reviewed-vs-provisional; reviewed ones cite the
    real-catalog source file this corpus was built from."""
    for query in QUERIES:
        for judgment in query["judgments"]:
            assert judgment["status"] in JUDGMENT_STATUSES
            assert judgment["product_id"] in REAL_CATALOG_PRODUCTS
            assert len(judgment["rationale"]) >= 20
            if judgment["status"] == "reviewed":
                assert judgment["source"].startswith(
                    "data/evals/real_catalog_lab_products.json#"
                )


def test_provisional_judgments_are_a_real_minority_not_the_whole_corpus():
    """At least some relevance grades are load-bearing on reviewed evidence.

    A corpus that was entirely provisional would not support any relevance
    claim at all; docs/evaluation-plan.md requires a reviewed-only measurement
    for that. This does not require every judgment to be reviewed -- the report
    is explicit about which tier it is showing.
    """
    statuses = [
        judgment["status"] for query in QUERIES for judgment in query["judgments"]
    ]
    reviewed = statuses.count("reviewed")
    provisional = statuses.count("provisional")
    assert reviewed > provisional
    assert provisional > 0


def test_hard_negatives_are_graded_zero_and_judged():
    for query in QUERIES:
        grades = {j["product_id"]: j["grade"] for j in query["judgments"]}
        for product_id in query["hard_negative_ids"]:
            assert grades[product_id] == 0


def test_unsatisfiable_queries_carry_no_relevant_judgment():
    for query in QUERIES:
        grades = [j["grade"] for j in query["judgments"]]
        if query["expect_no_relevant_results"]:
            assert all(grade == 0 for grade in grades)
        else:
            assert any(grade >= 2 for grade in grades)


def test_selective_filters_queries_use_only_verifiable_categorical_fields():
    """Filters here must be things a maintainer can check without guessing.

    `domain` and `category_key` are read straight from
    `real_catalog_lab_products.json`'s own fields, so they are hard facts. No
    query in this corpus asserts a numeric price bound or an `attributes` key,
    since this checkout cannot verify either against the live schema -- see the
    `selective_filters` design note in the module docstring.
    """
    for query in QUERIES:
        if query["cohort_intent"] != "selective_filters":
            continue
        assert "attributes" not in query["filters"]
        assert "min_price_cents" not in query["filters"]
        assert "max_price_cents" not in query["filters"]


def test_dataset_id_is_the_real_catalog_for_every_query():
    """This corpus is scoped to `reviews-2023-500k-v1`, never a hardcoded
    literal inside the runner -- see `require_single_served_catalog` reuse."""
    assert {query["dataset_id"] for query in QUERIES} == {"reviews-2023-500k-v1"}
