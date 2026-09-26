"""The build benchmark owns its index and never touches the serving one."""

from __future__ import annotations

import pytest

from scripts import benchmark_index_build as build


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Connection:
    """Records every statement; answers settings and size reads with canned rows."""

    def __init__(self):
        self.statements: list[str] = []

    def execute(self, statement, parameters=None):
        text = statement if isinstance(statement, str) else statement.as_string(None)
        self.statements.append(text)
        if "FROM pg_settings" in text:
            return _Cursor(
                [
                    {
                        "name": "maintenance_work_mem",
                        "setting": "8388608",
                        "unit": "kB",
                    },
                    {
                        "name": "max_parallel_maintenance_workers",
                        "setting": "7",
                        "unit": None,
                    },
                ]
            )
        if "pg_relation_size" in text:
            return _Cursor([{"bytes": 4_536_000_000}])
        return _Cursor([])


def test_the_build_targets_a_benchmark_owned_name_and_drops_it(monkeypatch):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    connection = _Connection()

    record = build.build_once(
        connection, workers=7, maintenance_work_mem="8GB", keep=False
    )

    creates = [s for s in connection.statements if s.startswith("CREATE INDEX")]
    drops = [s for s in connection.statements if s.startswith("DROP INDEX")]
    assert len(creates) == 1
    assert '"real_search_vector_idx_bench"' in creates[0]
    assert '"mosaic_catalog_search"."product_document"' in creates[0]
    assert "vector_cosine_ops" in creates[0]
    assert all("_bench" in s for s in drops), drops
    assert not any('"real_search_vector_idx"' in s for s in connection.statements)
    assert record["index"] == "mosaic_catalog_search.real_search_vector_idx_bench"
    assert record["size_bytes"] == 4_536_000_000
    assert record["settings"]["max_parallel_maintenance_workers"] == "7"
    assert record["settings"]["maintenance_work_mem"] == "8388608kB"
    assert record["seconds"] >= 0
    assert record["kept"] is False


def test_the_session_settings_are_applied_before_the_build(monkeypatch):
    monkeypatch.delenv("MOSAIC_CATALOG_DATASET", raising=False)
    connection = _Connection()

    build.build_once(connection, workers=3, maintenance_work_mem="2GB", keep=True)

    joined = "\n".join(connection.statements)
    assert "SET max_parallel_maintenance_workers = 3" in joined
    assert "SET maintenance_work_mem = '2GB'" in joined
    assert joined.index("SET maintenance_work_mem") < joined.index("CREATE INDEX")
    assert '"product_document_embedding_hnsw_cosine_idx_bench"' in joined
    assert not any(
        s.startswith("DROP INDEX ") and "IF EXISTS" not in s
        for s in connection.statements
    )


def test_the_bench_name_is_derived_from_the_served_index(monkeypatch):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    assert build.bench_index_name() == "real_search_vector_idx_bench"
    monkeypatch.delenv("MOSAIC_CATALOG_DATASET")
    assert (
        build.bench_index_name() == "product_document_embedding_hnsw_cosine_idx_bench"
    )


@pytest.mark.parametrize("argument", ["--repeat 0", "--workers -1"])
def test_non_positive_sizes_are_refused(monkeypatch, argument):
    monkeypatch.setattr("sys.argv", ["benchmark_index_build.py", *argument.split()])

    with pytest.raises(SystemExit, match="fix:"):
        build.main()
