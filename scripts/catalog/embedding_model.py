"""Shared Cohere model contract and Bedrock embedding adapter for catalog tooling."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import replace

COHERE_EMBED_V4_MODEL_ID = "us.cohere.embed-v4:0"
COHERE_EMBED_V4_DIMENSIONS = 1024


def embedding_function(
    provider: str,
    *,
    model_id: str,
    dimensions: int,
    region: str,
) -> tuple[Callable[[list[str]], list[list[float]]], str]:
    """Create a document embedder after validating the workshop model space."""
    if provider in {"bedrock", "bedrock-cohere-v4"}:
        if model_id != COHERE_EMBED_V4_MODEL_ID:
            raise SystemExit(
                "This workshop requires Cohere Embed v4 through Amazon Bedrock: "
                f"{COHERE_EMBED_V4_MODEL_ID}"
            )
        if dimensions != COHERE_EMBED_V4_DIMENSIONS:
            raise SystemExit(
                "Cohere Embed v4 must use the workshop's canonical "
                f"{COHERE_EMBED_V4_DIMENSIONS}-dimension model space"
            )
        from service.config import get_settings
        from service.embeddings import BedrockEmbeddingProvider

        settings = replace(
            get_settings(),
            aws_region=region,
            vector_dimension=dimensions,
            embedding_provider="bedrock",
            embedding_model_id=model_id,
        )
        embedder = BedrockEmbeddingProvider(settings)

        def embed_documents(texts: list[str]) -> list[list[float]]:
            for attempt in range(1, 9):
                try:
                    return embedder.embed_documents(texts)
                except embedder.client.exceptions.ThrottlingException:
                    if attempt == 8:
                        raise
                    time.sleep(random.uniform(1.0, min(30.0, 2.0**attempt)))
            raise AssertionError("unreachable")

        return embed_documents, model_id

    raise SystemExit(
        "Embedding provider rule: unsupported provider; use bedrock-cohere-v4."
    )
