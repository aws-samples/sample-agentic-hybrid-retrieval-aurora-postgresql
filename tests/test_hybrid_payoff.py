import json

import pytest

from scripts.evals import hybrid_payoff
from scripts.evals.hybrid_payoff import bootstrap, load_queries, rrf


def test_rrf_sums_reciprocal_ranks_and_breaks_ties_by_product_id():
    # 7: 1/61 + 1/62; 9: 1/63 + 1/61; 3: 1/62 + 1/63.
    lists = [[7, 3, 9], [9, 7, 3]]
    assert rrf(lists, k=60, size=3) == [7, 9, 3]
    assert rrf(lists, k=60, size=1) == [7]
    assert rrf([[5, 4], [4, 5]], k=60, size=2) == [4, 5]


def test_rrf_counts_a_product_once_per_list_it_appears_in():
    assert rrf([[1], [2], [2]], k=60, size=2) == [2, 1]
    assert rrf([], k=60, size=5) == []


def test_bootstrap_is_seeded_and_reports_direction_counts():
    diffs = [0.2, -0.1, 0.0, 0.3, 0.1]
    first, second = bootstrap(diffs), bootstrap(diffs)
    assert first == second
    assert first["mean_diff"] == pytest.approx(0.1)
    assert (first["better"], first["worse"], first["tied"]) == (3, 1, 1)
    low, high = first["ci95"]
    assert low <= first["mean_diff"] <= high


def test_load_queries_keeps_only_queries_with_a_relevant_label():
    queries = load_queries()
    assert queries
    assert all(
        any(j["grade"] >= hybrid_payoff.RELEVANT_GRADE for j in q["judgments"])
        for q in queries
    )


def test_load_queries_refuses_a_query_spent_on_tuning(tmp_path, monkeypatch):
    subset = hybrid_payoff.REPO / "data/evals/esci_judged_subset.json"
    spent_id = json.loads(subset.read_text())["queries"][0]["query_id"]
    record = {
        "query_id": "ESCI-REUSED",
        "esci_query_id": spent_id,
        "judgments": [{"product_id": 1, "grade": 3}],
    }
    corpus = tmp_path / "queries.jsonl"
    corpus.write_text(json.dumps(record) + "\n")
    monkeypatch.setattr(hybrid_payoff, "QUERIES", corpus)
    with pytest.raises(ValueError, match="collide"):
        load_queries()


def test_committed_artifact_describes_the_current_query_set():
    artifact = hybrid_payoff.OUTPUT
    if not artifact.exists():
        pytest.skip("hybrid payoff has not been measured on this checkout")
    report = json.loads(artifact.read_text())
    provenance = report["provenance"]
    current = hybrid_payoff.hashlib.sha256(hybrid_payoff.QUERIES.read_bytes())
    assert provenance["query_set_sha256"] == current.hexdigest(), (
        "found a hybrid payoff artifact measured on another query set; fix: re-run "
        "scripts/evals/hybrid_payoff.py"
    )
    assert provenance["source_worktree_dirty"] is False
    assert report["queries"] == len(load_queries())
    assert report["fusion_check"].startswith("Python RRF equals")
