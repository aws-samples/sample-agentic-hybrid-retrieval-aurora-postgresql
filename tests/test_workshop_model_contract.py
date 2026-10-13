from pathlib import Path

import pytest

from scripts.catalog.embedding_model import (
    COHERE_EMBED_V4_DIMENSIONS,
    COHERE_EMBED_V4_MODEL_ID,
    embedding_function,
)
from service.search_sql import search_sql

ROOT = Path(__file__).resolve().parents[1]


def test_workshop_model_space_is_cohere_embed_v4():
    assert COHERE_EMBED_V4_MODEL_ID == "us.cohere.embed-v4:0"
    assert COHERE_EMBED_V4_DIMENSIONS == 1024
    # Retargeted from the deleted `sql/` tree in Phase 2 Unit E.
    assert "vector(1024)" in (ROOT / "db/sql/06_retrieval_projection.sql").read_text()
    assert "vector(1024)" in search_sql(ROOT)
    assert (
        "BEDROCK_EMBED_MODEL_ID=us.cohere.embed-v4:0"
        in (ROOT / "config/.env.example").read_text()
    )


def test_workshop_embedding_loader_rejects_another_bedrock_model():
    with pytest.raises(SystemExit, match="requires Cohere Embed v4"):
        embedding_function(
            "bedrock",
            model_id="amazon.titan-embed-text-v2:0",
            dimensions=1024,
            region="us-east-1",
        )


def test_workshop_embedding_loader_rejects_another_dimension():
    with pytest.raises(SystemExit, match="1024-dimension"):
        embedding_function(
            "bedrock",
            model_id=COHERE_EMBED_V4_MODEL_ID,
            dimensions=512,
            region="us-east-1",
        )


def test_a_vector_never_enters_search_without_the_text_it_embedded():
    """A vector computed from replaced text must not survive the replacement.

    A stale embedding is worse than a missing one. The restore refuses a load in
    which any listing's embedded input differs from its text, or its vector or
    model from the verified source record.
    """
    from scripts.catalog import prepare_staged_catalog_search as staged

    source = Path(staged.__file__).read_text()
    for check in (
        "d.embedding_text_sha256 IS DISTINCT FROM p.embedded_input_sha256",
        "d.embedding IS DISTINCT FROM p.embedding",
        "d.embedding_model_key IS DISTINCT FROM p.embedding_model_key",
    ):
        assert check in source
    assert "source/vector mismatches" in source
