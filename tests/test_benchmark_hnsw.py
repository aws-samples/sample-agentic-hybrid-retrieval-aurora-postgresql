from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hnsw_benchmark_uses_the_production_configuration_and_persists_results():
    source = (ROOT / "scripts" / "benchmark_hnsw.py").read_text(encoding="utf-8")

    assert "mosaic_search.configure_hnsw" in source
    assert "INSERT INTO mosaic_bench.run" in source
    assert "INSERT INTO mosaic_bench.measurement" in source
    assert "dataset_manifest_sha256" in source
    assert "query_sample_sha256" in source


def test_hnsw_benchmark_schema_records_reproducibility_inputs():
    schema = (ROOT / "db" / "sql" / "13_benchmark.sql").read_text(encoding="utf-8")

    for column in (
        "database_instance_id",
        "source_revision",
        "source_worktree_dirty",
        "dataset_manifest_sha256",
        "index_size_bytes",
    ):
        assert column in schema


def test_recall_counts_only_ground_truth_overlap():
    from scripts.benchmark_hnsw import recall_against_truth

    truth = [11, 12, 13, 14, 15, 16, 17, 18, 19, 20]

    assert recall_against_truth([11, 12, 13, 99, 98], truth, k=10) == 0.3
    assert recall_against_truth([], truth, k=10) == 0.0
    assert recall_against_truth(truth, truth, k=10) == 1.0


def test_recall_divides_by_ground_truth_size_not_k():
    """The flagship preset has 6 exact neighbours, so 6 of 6 is recall 1.0.

    Dividing by k would report 0.6 and make the planner's correct decision to
    abandon HNSW at extreme selectivity look like a retrieval failure.
    """
    from scripts.benchmark_hnsw import recall_against_truth

    assert recall_against_truth([1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6], k=10) == 1.0


def test_recall_of_empty_ground_truth_is_zero_not_one():
    """No exact neighbours means nothing was found, not everything."""
    from scripts.benchmark_hnsw import recall_against_truth

    assert recall_against_truth([], [], k=10) == 0.0


def test_artifact_carries_provenance_and_derived_index_arithmetic():
    from scripts.benchmark_hnsw import artifact_from_results

    artifact = artifact_from_results(
        provenance={"source_revision": "abc", "queries": 25, "k": 10},
        index={
            "size_bytes": 4_094_296_064,
            "vector_count": 500_000,
            "dimensions": 1024,
        },
        exact_baseline={"p50_ms": 2355.2},
        missing_predicate={"server_ms": 2201.565},
        ef_sweep=[{"ef_search": 100, "server_ms": 2.369, "recall_at_k": 0.992}],
        filter_matrix=[],
        captured_at="2026-08-17T00:00:00+00:00",
    )

    assert artifact["kind"] == "measured"
    assert artifact["captured_at"] == "2026-08-17T00:00:00+00:00"
    assert artifact["index"]["bytes_per_vector"] == 8189
    assert artifact["index"]["fp32_payload_bytes"] == 4096
    assert artifact["index"]["overhead_factor"] == 2.0
    assert artifact["missing_predicate"]["slowdown_factor"] == 929.3
    assert artifact["missing_predicate"]["compared_at_ef_search"] == 100
    assert artifact["provenance"]["source_revision"] == "abc"


def test_artifact_slowdown_factor_is_none_without_the_served_ef_point():
    """No measurement at the served ef_search means no comparison to report.

    Falling back to the fastest point would price the index at a recall nobody
    runs: 3,875x at the cheapest sweep point where the served point gives 805x.
    """
    from scripts.benchmark_hnsw import artifact_from_results

    artifact = artifact_from_results(
        provenance={},
        index={"size_bytes": 1_000, "vector_count": 10, "dimensions": 1024},
        exact_baseline={},
        missing_predicate={"server_ms": 2201.565},
        ef_sweep=[],
        filter_matrix=[],
        captured_at="2026-08-17T00:00:00+00:00",
    )

    assert artifact["missing_predicate"]["slowdown_factor"] is None


def test_the_exact_baseline_resets_its_planner_settings():
    """`SET LOCAL` cannot be trusted to contain these, so they must be RESET.

    psycopg's `connection.transaction()` degrades to a SAVEPOINT when an implicit
    transaction is already open, and `SET LOCAL` survives `RELEASE SAVEPOINT`. A
    leaked `enable_indexscan = off` turns every later ANN query into the exact query,
    which reports recall 1.0 — the best possible number — with latency 1,000x wrong.
    That shape was captured twice before this assertion existed.
    """
    source = (ROOT / "scripts" / "benchmark_hnsw.py").read_text(encoding="utf-8")

    assert "SET LOCAL enable_indexscan" not in source
    assert "SET LOCAL enable_bitmapscan" not in source
    assert "RESET enable_indexscan" in source
    assert "RESET enable_bitmapscan" in source


def test_the_seed_script_also_resets_its_planner_settings():
    """Harmless here — this script only ever wants exact scans — but relying on that
    is how the benchmark silently recorded sequential scans as ANN measurements.
    """
    source = (ROOT / "scripts" / "seed_exact_neighbors.py").read_text(encoding="utf-8")

    assert 'connection.execute(f"SET LOCAL' not in source
    assert 'connection.execute(f"RESET {setting' in source


def test_an_ann_measurement_that_missed_the_index_is_refused():
    """A sequential scan wearing an ANN label must fail loudly, not be recorded."""
    import pytest

    from scripts.benchmark_hnsw import _assert_used_the_index

    with pytest.raises(SystemExit) as raised:
        _assert_used_the_index(
            {"node": "Seq Scan", "index_name": None, "shared_hit_blocks": 2_300_855},
            ef_search=10,
        )

    assert "Seq Scan" in str(raised.value)
    assert "fix:" in str(raised.value)


def test_an_ann_measurement_on_the_hnsw_index_is_accepted():
    from scripts.benchmark_hnsw import _assert_used_the_index

    _assert_used_the_index(
        {
            "node": "Index Scan",
            "index_name": "product_document_embedding_hnsw_cosine_idx",
            "shared_hit_blocks": 514,
        },
        ef_search=10,
    )


def test_an_ann_measurement_on_the_wrong_index_is_refused():
    """Using *an* index is not the same as using the HNSW index."""
    import pytest

    from scripts.benchmark_hnsw import _assert_used_the_index

    with pytest.raises(SystemExit):
        _assert_used_the_index(
            {
                "node": "Index Scan",
                "index_name": "product_document_pkey",
                "shared_hit_blocks": 12,
            },
            ef_search=10,
        )


def test_slowdown_is_measured_against_the_served_ef_not_the_fastest():
    """3,875x at the cheapest sweep point flatters the index; 805x served is real."""
    from scripts.benchmark_hnsw import artifact_from_results

    artifact = artifact_from_results(
        provenance={},
        index={
            "size_bytes": 4_094_296_064,
            "vector_count": 500_000,
            "dimensions": 1024,
        },
        exact_baseline={},
        missing_predicate={"server_ms": 2181.804},
        ef_sweep=[
            {"ef_search": 10, "server_ms": 0.563, "recall_at_k": 0.844},
            {"ef_search": 100, "server_ms": 2.711, "recall_at_k": 0.992},
        ],
        filter_matrix=[],
        captured_at="2026-08-17T00:00:00+00:00",
    )

    assert artifact["missing_predicate"]["slowdown_factor"] == 804.8
    assert artifact["missing_predicate"]["compared_at_ef_search"] == 100
