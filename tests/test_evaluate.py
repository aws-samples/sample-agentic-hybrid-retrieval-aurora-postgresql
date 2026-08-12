from scripts.evaluate import evaluate


def test_graded_metrics_use_relevance_threshold_and_gain():
    truth = {
        "G-001": {10: 3, 20: 2, 30: 0},
        "G-002": {40: 3, 50: 1},
    }
    ranked = {
        "G-001": [(1, 20), (2, 30), (3, 10)],
        "G-002": [(1, 50), (2, 40)],
    }

    metrics = evaluate(truth, ranked, 3)

    assert metrics["query_count"] == 2
    assert metrics["recall@3"] == 1.0
    assert metrics["mrr"] == 0.75
    assert 0 < metrics["ndcg@3"] < 1
