"""The quantized index builder targets the served catalog's names and expressions."""

from __future__ import annotations

from scripts import build_quantized_indexes as builder


def test_statements_name_the_served_catalog_indexes(monkeypatch):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")

    halfvec = builder.build_statement("halfvec", concurrently=False).as_string(None)
    binary = builder.build_statement("binary", concurrently=True).as_string(None)

    assert halfvec.startswith(
        'CREATE INDEX IF NOT EXISTS "real_search_vector_halfvec_idx"'
    )
    assert '"mosaic_catalog_search"."product_document"' in halfvec
    assert "(embedding::halfvec(1024)) halfvec_cosine_ops" in halfvec
    assert "m = 16" in halfvec and "ef_construction = 200" in halfvec
    assert binary.startswith(
        'CREATE INDEX CONCURRENTLY IF NOT EXISTS "real_search_vector_binary_idx"'
    )
    assert "(binary_quantize(embedding)::bit(1024)) bit_hamming_ops" in binary


def test_legacy_catalog_gets_the_legacy_names(monkeypatch):
    monkeypatch.delenv("MOSAIC_CATALOG_DATASET", raising=False)

    statement = builder.build_statement("halfvec", concurrently=False).as_string(None)

    assert '"product_document_embedding_hnsw_halfvec_idx"' in statement
    assert '"mosaic_search"."product_document"' in statement


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Connection:
    def __init__(self, states):
        self.states = states
        self.statements = []

    def execute(self, statement, parameters=None):
        text = statement if isinstance(statement, str) else statement.as_string(None)
        self.statements.append(text)
        if "unnest(%s::text[])" in text:
            return _Cursor(
                [
                    {"name": n, "state": self.states.get(n, "missing")}
                    for n in parameters[0]
                ]
            )
        if "pg_relation_size" in text:
            return _Cursor([{"bytes": 1_500_000_000}])
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
        return _Cursor([])


def test_a_valid_index_is_left_alone_and_an_invalid_one_is_rebuilt(monkeypatch):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    connection = _Connection(
        {
            "real_search_vector_halfvec_idx": "valid",
            "real_search_vector_binary_idx": "invalid",
        }
    )

    records = builder.build(
        connection,
        representations=["halfvec", "binary"],
        workers=7,
        maintenance_work_mem="8GB",
        concurrently=False,
    )

    assert records[0]["state"] == "already valid"
    assert records[1]["state"] == "built"
    assert records[1]["size_bytes"] == 1_500_000_000
    assert records[1]["settings"] == {
        "maintenance_work_mem": {"setting": "8388608", "unit": "kB"},
        "max_parallel_maintenance_workers": {"setting": "7", "unit": None},
    }
    joined = "\n".join(connection.statements)
    assert (
        'DROP INDEX "mosaic_catalog_search"."real_search_vector_binary_idx"' in joined
    )
    assert joined.count("CREATE INDEX") == 1
    assert "SET max_parallel_maintenance_workers = 7" in joined
