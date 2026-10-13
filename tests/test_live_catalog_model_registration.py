"""Fresh catalog preparation must register the model used by evidence FKs
and leave the planner the statistics its search indexes need."""

from unittest.mock import MagicMock

import pytest

from scripts.catalog import prepare_live_catalog as live
from scripts.catalog.embedding_model import COHERE_EMBED_V4_MODEL_ID
from scripts.checks.retrieval_profile import load_profile


def test_verified_preparation_registers_the_evidence_model_before_publication(
    monkeypatch,
):
    connection = MagicMock()
    connection.execute.return_value.fetchone.side_effect = [
        (500000, True, True, "catalog-hash"),
        (500000,),
        AssertionError("model registration was skipped"),
    ]
    witnessed = []

    def register(actual):
        assert actual is connection
        witnessed.append(True)
        raise RuntimeError("registration witness")

    monkeypatch.setattr(live, "register_embedding_model", register, raising=False)
    with pytest.raises(RuntimeError, match="registration witness"):
        live.prepare(connection, "reviews-2023-v2")
    assert witnessed == [True]


def test_model_registration_uses_the_verified_cache_identity():
    connection = MagicMock()
    live.register_embedding_model(connection)
    calls = connection.execute.call_args_list
    assert len(calls) == 2
    assert "UPDATE mosaic.embedding_model" in calls[0].args[0]
    assert calls[0].args[1] == (COHERE_EMBED_V4_MODEL_ID,)
    statement, values = calls[1].args
    assert "INSERT INTO mosaic.embedding_model" in statement
    assert "ON CONFLICT (model_key) DO UPDATE" in statement
    assert values == (
        COHERE_EMBED_V4_MODEL_ID,
        COHERE_EMBED_V4_MODEL_ID,
        load_profile().vector_dimension,
    )
    connection.commit.assert_not_called()


def test_preparation_analyses_the_catalog_after_creating_the_public_id_index(
    monkeypatch,
):
    """The restore analysed the table before this index existed, so ANALYZE follows it."""
    statements: list[str] = []
    rows = iter(
        [
            (500000, True, True, "catalog-hash"),
            (500000,),
            ("reviews-2023-v2", "catalog-hash"),
            None,
            None,
        ]
    )

    def execute(statement, *_args, **_kwargs):
        statements.append(" ".join(str(statement).split()))
        if "INSERT INTO mosaic.brand" in statements[-1]:
            raise RuntimeError("stopped after the index step")
        result = MagicMock()
        result.fetchone.side_effect = lambda: next(rows)
        return result

    connection = MagicMock()
    connection.execute.side_effect = execute
    monkeypatch.setattr(live, "register_embedding_model", lambda _connection: None)
    monkeypatch.setattr(live, "load_source_prices", lambda _connection: None)

    with pytest.raises(RuntimeError, match="stopped after the index step"):
        live.prepare(connection, "reviews-2023-v2")

    created = next(
        index
        for index, statement in enumerate(statements)
        if "CREATE INDEX IF NOT EXISTS product_search_public_id_idx" in statement
    )
    analysed = [
        index
        for index, statement in enumerate(statements)
        if statement == "ANALYZE mosaic_catalog_search.product_document"
    ]
    assert analysed and analysed[0] > created
