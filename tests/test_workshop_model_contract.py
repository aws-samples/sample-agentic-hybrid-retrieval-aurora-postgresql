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


def test_projection_upsert_invalidates_a_changed_embedding_text():
    """A vector computed from replaced text must not survive the replacement.

    Retargeted from the deleted `sql/02_upsert_from_stage.sql` in Phase 2 Unit E —
    and the port had dropped the behavior, so this restored it. A stale embedding is
    worse than a missing one; clearing it forces the importer to supply a matching vector.
    """
    sql = (ROOT / "db/sql/06_retrieval_projection.sql").read_text()

    assert "embedding_text = EXCLUDED.embedding_text" in sql
    assert "IS DISTINCT FROM EXCLUDED.embedding_text" in sql
    # Both the vector and the model key must clear, or the row claims to have been
    # embedded by a model that never saw this text.
    assert sql.count("IS DISTINCT FROM EXCLUDED.embedding_text") >= 2
    assert "THEN NULL" in sql
