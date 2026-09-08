"""Related products must be alternatives, not domain-wide popularity picks."""

from contextlib import contextmanager

from service import catalog


def test_alternatives_use_the_stored_vector_with_a_bounded_category_pool(monkeypatch):
    calls = []

    class Connection:
        def execute(self, sql, parameters):
            calls.append((sql, parameters))
            return self

        def fetchone(self):
            return {"product_id": 420001}

        def fetchall(self):
            return []

    @contextmanager
    def connect():
        yield Connection()

    monkeypatch.setattr(catalog, "connect", connect)
    assert catalog.similar_products(420001) == []
    sql, parameters = calls[-1]
    assert "d.embedding <=> source.embedding" in sql
    assert "d.product_id <> source.product_id" in sql
    assert "d.canonical_group_id" in sql
    assert "d.category_key = source.category_key" in sql
    assert "d.domain = source.domain" in sql
    assert "in_stock" in sql
    assert "photographed" in sql
    assert list(catalog._PHOTOGRAPHED_PRODUCT_IDS) in parameters
