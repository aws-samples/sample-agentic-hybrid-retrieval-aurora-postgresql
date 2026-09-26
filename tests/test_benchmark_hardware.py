"""The instance comparison holds its workload constant and discloses what it measured."""

from __future__ import annotations

from scripts import benchmark_hardware as hardware
from service.hnsw_presets import FILTER_PRESETS


def _pool(ids):
    return [
        {"product_id": item, "category_key": "monitor", "embedding": [0.0]}
        for item in ids
    ]


def test_the_workload_cycles_every_anchor_under_every_preset_deterministically():
    first = hardware.Workload(_pool([3, 1]))
    second = hardware.Workload(_pool([3, 1]))

    assert len(first.pairs) == 2 * len(FILTER_PRESETS)
    assert first.sha256 == second.sha256
    keys = [
        (anchor["product_id"], preset.key)
        for anchor, preset in (first.next() for _ in range(3))
    ]
    assert keys == [(3, "none"), (3, "rating"), (3, "domain")]
    assert hardware.Workload(_pool([1, 3])).sha256 != first.sha256


def test_a_phase_summary_reports_percentiles_throughput_recall_and_errors():
    phase = {
        "started_at": "2026-09-26T00:00:00+00:00",
        "ended_at": "2026-09-26T00:01:00+00:00",
        "wall_seconds": 60.0,
        "records": [
            {
                "worker": 0,
                "anchor": 1,
                "preset": "none",
                "client_ms": 2.0,
                "returned": 10,
                "truth_count": 10,
                "recall": 1.0,
            },
            {
                "worker": 1,
                "anchor": 1,
                "preset": "brand",
                "client_ms": 8.0,
                "returned": 4,
                "truth_count": 10,
                "recall": 0.4,
            },
            {
                "worker": 0,
                "anchor": 2,
                "preset": "none",
                "client_ms": 4.0,
                "returned": 10,
                "truth_count": 10,
                "recall": 0.9,
            },
        ],
        "errors": [
            {
                "worker": 1,
                "stage": "query",
                "error": "OperationalError",
                "preset": "brand",
            }
        ],
    }

    summary = hardware.summarize_phase(phase, concurrency=2)

    assert summary["queries_completed"] == 3
    assert summary["errors"] == 1
    assert summary["throughput_qps"] == 0.05
    assert summary["client_p50_ms"] == 4.0
    assert summary["client_p99_ms"] == 8.0
    assert summary["recall_at_k"] == round((1.0 + 0.4 + 0.9) / 3, 4)
    assert summary["recall_by_preset"] == {"brand": 0.4, "none": 0.95}


def test_cost_per_query_follows_throughput_and_the_stated_hourly_price():
    side = {
        "trials": [
            {"concurrency": 4, "trial": 1, "throughput_qps": 100.0, "recall_at_k": 0.98}
        ]
    }

    rows = hardware.cost_rows(side, 1.436)

    assert rows[0]["usd_per_hour"] == 1.436
    assert rows[0]["usd_per_million_queries"] == round(
        1.436 / (100.0 * 3600) * 1_000_000, 4
    )
    assert (
        hardware.cost_rows(
            {
                "trials": [
                    {
                        "concurrency": 1,
                        "trial": 1,
                        "throughput_qps": 0,
                        "recall_at_k": 0,
                    }
                ]
            },
            1.0,
        )[0]["usd_per_million_queries"]
        is None
    )


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0]


class _Connection:
    def __init__(self, text_lines, orcache_function_exists):
        self.text_lines = text_lines
        self.orcache = orcache_function_exists

    def execute(self, sql, parameters=None):
        if sql.startswith("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)"):
            return _Cursor(
                [
                    {
                        "QUERY PLAN": [
                            {
                                "Execution Time": 1.5,
                                "Plan": {
                                    "Node Type": "Index Scan",
                                    "Index Name": "real_search_vector_idx",
                                    "Shared Hit Blocks": 500,
                                    "Shared Read Blocks": 12,
                                },
                            }
                        ]
                    }
                ]
            )
        if sql.startswith("EXPLAIN (ANALYZE, BUFFERS)"):
            return _Cursor([{"QUERY PLAN": line} for line in self.text_lines])
        if "aurora_stat_optimized_reads_cache" in sql:
            if not self.orcache:
                raise RuntimeError(
                    "function aurora_stat_optimized_reads_cache() does not exist"
                )
            return _Cursor([{"total_size": 1_000, "used_size": 10}])
        raise AssertionError(sql)


def test_explain_sample_keeps_the_aurora_cache_fields_only_when_the_engine_prints_them():
    printed = hardware.explain_sample(
        _Connection(
            [
                "Index Scan using real_search_vector_idx",
                "  Buffers: shared hit=500 read=12 aurora_orcache_hit=12",
            ],
            True,
        ),
        "SELECT 1",
        [],
    )
    silent = hardware.explain_sample(
        _Connection(["Index Scan", "  Buffers: shared hit=500"], False), "SELECT 1", []
    )

    assert printed["aurora_orcache_hit_mentioned"] is True
    assert printed["indexes_used"] == ["real_search_vector_idx"]
    assert silent["aurora_orcache_hit_mentioned"] is False
    assert silent["aurora_storage_read_mentioned"] is False


def test_optimized_reads_cache_is_reported_absent_rather_than_assumed():
    absent = hardware.optimized_reads_cache(_Connection([], False))
    present = hardware.optimized_reads_cache(_Connection([], True))

    assert absent == {"available": False, "reason": "RuntimeError"}
    assert present == {
        "available": True,
        "total_size_bytes": 1_000,
        "used_size_bytes": 10,
    }
