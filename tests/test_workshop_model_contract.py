import math
from pathlib import Path

import pytest

from scripts.embed_catalog import (
    COHERE_EMBED_V4_DIMENSIONS,
    COHERE_EMBED_V4_MODEL_ID,
    DEVELOPMENT_HASH_MODEL_ID,
    embedding_function,
)

ROOT = Path(__file__).resolve().parents[1]


def test_workshop_model_space_is_cohere_embed_v4():
    assert COHERE_EMBED_V4_MODEL_ID == "us.cohere.embed-v4:0"
    assert COHERE_EMBED_V4_DIMENSIONS == 1024
    # Retargeted from the deleted `sql/` tree in Phase 2 Unit E.
    assert "vector(1024)" in (ROOT / "db/sql/06_retrieval_projection.sql").read_text()
    assert "vector(1024)" in (ROOT / "db/sql/09_search_functions.sql").read_text()
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
            allow_development_embeddings=False,
        )


def test_workshop_embedding_loader_rejects_another_dimension():
    with pytest.raises(SystemExit, match="1024-dimension"):
        embedding_function(
            "bedrock",
            model_id=COHERE_EMBED_V4_MODEL_ID,
            dimensions=512,
            region="us-east-1",
            allow_development_embeddings=False,
        )


def test_hash_embeddings_require_explicit_development_opt_in():
    with pytest.raises(SystemExit, match="development-only"):
        embedding_function(
            "hash",
            model_id=COHERE_EMBED_V4_MODEL_ID,
            dimensions=1024,
            region="us-east-1",
            allow_development_embeddings=False,
        )

    embed, model_id = embedding_function(
        "hash",
        model_id=COHERE_EMBED_V4_MODEL_ID,
        dimensions=1024,
        region="us-east-1",
        allow_development_embeddings=True,
    )
    vector = embed(["local mechanics only"])[0]
    assert model_id == DEVELOPMENT_HASH_MODEL_ID
    assert len(vector) == 1024
    assert math.isclose(sum(value * value for value in vector), 1.0)


def test_projection_upsert_invalidates_a_changed_embedding_text():
    """A vector computed from replaced text must not survive the replacement.

    Retargeted from the deleted `sql/02_upsert_from_stage.sql` in Phase 2 Unit E —
    and the port had dropped the behavior, so this restored it. A stale embedding is
    worse than a missing one: `scripts/embed_catalog.py` selects only rows where
    `embedding IS NULL` or the model key differs, so nothing would ever recompute it.
    """
    sql = (ROOT / "db/sql/06_retrieval_projection.sql").read_text()

    assert "embedding_text = EXCLUDED.embedding_text" in sql
    assert "IS DISTINCT FROM EXCLUDED.embedding_text" in sql
    # Both the vector and the model key must clear, or the row claims to have been
    # embedded by a model that never saw this text.
    assert sql.count("IS DISTINCT FROM EXCLUDED.embedding_text") >= 2
    assert "THEN NULL" in sql


def test_generated_reviews_are_honest_customer_review_evidence():
    types = (ROOT / "db/sql/01_schemas_and_types.sql").read_text()
    loader = (ROOT / "db/sql/18_load_evidence.sql").read_text()

    assert "'customer_review'" in types
    assert "'verified_review'" in types  # Legacy rows remain readable.
    assert "'customer_review'::mosaic.evidence_type" in loader
    assert "'Mosaic synthetic review corpus'" in loader
    assert "'Mosaic verified review corpus'" not in loader


def test_embedding_loader_uses_typed_binary_copy():
    source = (ROOT / "scripts/embed_catalog.py").read_text()

    assert "FROM STDIN (FORMAT BINARY)" in source
    # Two columns, not three: mosaic_search.product_document has no
    # embedding_content_hash, so re-embedding is gated on the model key instead.
    assert 'copy.set_types(["int8", "vector"])' in source


def test_embedding_loader_uses_bounded_parallel_batches():
    source = (ROOT / "scripts/embed_catalog.py").read_text()

    assert "ThreadPoolExecutor(max_workers=args.workers)" in source
    assert "--workers must be between 1 and 50" in source
    assert "--min-product-id" in source
    assert "--max-product-id" in source
    assert "executor.map(embed, text_batches)" in source
    assert "embedder.client.exceptions.ThrottlingException" in source


def test_embedding_loader_registers_the_model_before_writing_vectors():
    source = (ROOT / "scripts/embed_catalog.py").read_text()

    # product_document.embedding_model_key is a foreign key to
    # mosaic.embedding_model, so an unregistered model fails at the first UPDATE.
    assert "INSERT INTO mosaic.embedding_model" in source
    assert "is_active = EXCLUDED.is_active" in source
    assert "mosaic_search.product_document" in source
