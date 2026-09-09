from types import SimpleNamespace

import pytest

from scripts.benchmark_mosaic_scale import summarize
from service.hnsw import probe_parameters


def sample(time, recall, returned):
    return {
        "truth_count": 10,
        "server_ms": time,
        "client_ms": time + 20,
        "recall": recall,
        "returned": returned,
        "shared_hit_blocks": 100,
        "shared_read_blocks": 0,
        "node": "Index Scan",
        "indexes_used": ["hnsw"],
    }


def test_percentiles_cover_all_anchors_instead_of_the_first_query():
    result = summarize([sample(100, 1, 10), sample(2, 0.5, 5), sample(3, 0.6, 6)])
    assert result["server_ms"] == 3
    assert result["server_p95_ms"] == 100
    assert result["recall_at_k"] == 0.7
    assert result["rows_returned"] == 7
    assert len(result["samples"]) == 3


@pytest.mark.parametrize("samples", [[], [{**sample(1, 1, 0), "truth_count": 0}]])
def test_no_measurement_or_no_truth_cannot_be_published(samples):
    with pytest.raises(ValueError, match="Benchmark truth rule.*fix"):
        summarize(samples)


def test_binary_depth_reaches_the_production_probe_parameters():
    request = SimpleNamespace(representation="binary", k=10, overfetch=200)
    assert probe_parameters(request, "vector") == ["vector", 200, "vector", 10]
