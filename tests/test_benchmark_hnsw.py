from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hnsw_benchmark_uses_the_production_configuration_and_persists_results():
    source = (ROOT / "scripts" / "benchmark_hnsw.py").read_text(encoding="utf-8")

    assert "mosaic_search.configure_hnsw" in source
    assert "SET LOCAL enable_indexscan = off" in source
    assert "SET LOCAL enable_bitmapscan = off" in source
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
