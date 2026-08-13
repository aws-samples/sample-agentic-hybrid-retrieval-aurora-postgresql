import json
from pathlib import Path

import pytest

from scripts.eval_contract import load_evaluation_queries

ROOT = Path(__file__).resolve().parents[1]
QUERY_PATH = ROOT / "data/evals/canonical_queries.jsonl"
QUERIES = [
    json.loads(line)
    for line in QUERY_PATH
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
]
RESOLVED_QUERIES = load_evaluation_queries(QUERY_PATH)


def test_canonical_set_is_small_curated_and_unique():
    assert 20 <= len(QUERIES) <= 30
    assert len({query["query_id"] for query in QUERIES}) == len(QUERIES)
    assert all(query["query_id"].startswith("G-") for query in QUERIES)


def test_participant_queries_resolve_from_the_lab_authority():
    mission_backed = [query for query in QUERIES if query.get("mission_id")]
    contract = json.loads(
        (ROOT / "data" / "evals" / "mosaic_labs_missions.json").read_text(
            encoding="utf-8"
        )
    )
    core_mission_ids = {
        item["id"]
        for item in contract["missions"] + contract["supporting_checks"]
        if item["core"]
    }
    assert {
        (query["query_id"], query["mission_id"])
        for query in mission_backed
        if query["mission_id"] in core_mission_ids
    } == {
        ("G-001", "exact-identity"),
        ("G-003", "typo-recovery"),
        ("G-007", "compare-cheaper-alternative"),
        ("G-008", "rank-with-evidence"),
        ("G-009", "ranking-filter-control"),
        ("G-010", "agentic-research"),
        ("G-013", "semantic-eligibility"),
        ("G-020", "evidence-grounding"),
    }
    assert {
        (query["query_id"], query["mission_id"])
        for query in mission_backed
        if query["mission_id"] not in core_mission_ids
    } == {
        ("G-004", "semantic-intent-contrast"),
    }
    assert all("query" not in query and "filters" not in query for query in mission_backed)
    resolved = {
        query["query_id"]: query
        for query in RESOLVED_QUERIES
        if query.get("mission_id")
    }
    assert all(query["query"] and query["filters"] for query in resolved.values())


def test_mission_backed_eval_rejects_a_second_query_copy(tmp_path):
    path = tmp_path / "queries.jsonl"
    duplicated = {
        **next(query for query in QUERIES if query.get("mission_id")),
        "query": "drifted copy",
    }
    path.write_text(json.dumps(duplicated) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicates query or filters"):
        load_evaluation_queries(path)


def test_canonical_judgments_are_graded_and_explained():
    for query in QUERIES:
        judgments = query["judgments"]
        assert judgments
        assert any(item["grade"] == 3 for item in judgments)
        assert all(item["grade"] in {0, 1, 2, 3} for item in judgments)
        assert all(len(item["rationale"]) >= 20 for item in judgments)
        assert len({item["product_id"] for item in judgments}) == len(judgments)
        grades = {item["product_id"]: item["grade"] for item in judgments}
        assert all(grades[product_id] == 0 for product_id in query["hard_negative_ids"])


def test_canonical_products_are_in_the_curated_cohort():
    curated = {
        product["product_id"]
        for product in json.loads(
            (ROOT / "data/curated/demo_products.json").read_text(encoding="utf-8")
        )
    }
    for query in QUERIES:
        assert {item["product_id"] for item in query["judgments"]} <= curated


def test_canonical_set_covers_the_workshop_failure_modes():
    concepts = {query["teaching_concept"] for query in QUERIES}
    assert {
        "exact_identity",
        "typo_recovery",
        "semantic_intent_and_filters",
        "hard_price_negative",
        "rrf_and_reranking",
        "agent_orchestration",
        "evidence_retrieval_and_citation",
    } <= concepts


def test_agent_orchestration_is_not_scored_as_single_request_retrieval():
    agent_case = next(query for query in QUERIES if query["query_id"] == "G-010")
    assert agent_case["evaluation_scope"] == "agent_contract"


def test_repaired_fixture_release_checks_are_machine_verifiable():
    by_id = {query["query_id"]: query for query in QUERIES}
    assert by_id["G-001"]["release_checks"] == [
        {"type": "top_rank", "product_id": 17001}
    ]
    assert by_id["G-015"]["release_checks"] == [
        {"type": "top_rank", "product_id": 210001},
        {"type": "present_top_k", "product_id": 210002, "k": 3},
    ]
    assert by_id["G-019"]["release_checks"] == [
        {"type": "top_rank", "product_id": 30001}
    ]


def test_lab_2_judgment_matches_the_explicit_adjustable_lumbar_intent():
    query = next(item for item in QUERIES if item["query_id"] == "G-008")
    grades = {
        judgment["product_id"]: judgment["grade"]
        for judgment in query["judgments"]
    }

    assert grades[370002] == 3
    assert grades[370001] == 2
