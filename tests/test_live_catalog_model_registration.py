"""Fresh catalog preparation must register the model used by evidence FKs."""

from unittest.mock import MagicMock

import pytest

from scripts import prepare_live_catalog as live
from scripts.embed_catalog import COHERE_EMBED_V4_MODEL_ID
from scripts.retrieval_profile import load_profile


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
        live.prepare(connection, "reviews-2023-500k-v1")
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
