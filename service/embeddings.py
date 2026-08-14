"""Real embedding adapters used by both catalog indexing and live queries."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Protocol

from service.bedrock import get_bedrock_client
from service.config import Settings, get_settings


class EmbeddingProvider(Protocol):
    model_id: str
    dimensions: int

    def embed_query(self, text: str) -> list[float]: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...


def _cohere_request(
    texts: Sequence[str],
    dimensions: int,
    input_type: str,
) -> dict[str, object]:
    return {
        "texts": list(texts),
        "input_type": input_type,
        "embedding_types": ["float"],
        "output_dimension": dimensions,
        "truncate": "END",
    }


def _extract_embeddings(payload: dict[str, object]) -> list[list[float]]:
    embeddings = payload.get("embeddings")
    if isinstance(embeddings, dict):
        values = embeddings.get("float") or embeddings.get("floats")
        if isinstance(values, list):
            return [[float(item) for item in vector] for vector in values]
    if isinstance(embeddings, list):
        return [[float(item) for item in vector] for vector in embeddings]
    embedding = payload.get("embedding")
    if isinstance(embedding, list):
        return [[float(item) for item in embedding]]
    raise ValueError("Bedrock response did not contain supported embedding output")


class BedrockEmbeddingProvider:
    def __init__(self, settings: Settings | None = None):
        settings = settings or get_settings()
        self.model_id = settings.embedding_model_id
        self.dimensions = settings.vector_dimension
        self.client = get_bedrock_client("bedrock-runtime", settings.aws_region)

    def _embed(self, texts: Sequence[str], input_type: str) -> list[list[float]]:
        if not texts:
            return []
        if "cohere.embed" in self.model_id:
            body = _cohere_request(texts, self.dimensions, input_type)
            response = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(body),
                accept="application/json",
                contentType="application/json",
            )
            vectors = _extract_embeddings(json.loads(response["body"].read()))
        else:
            vectors = []
            for text in texts:
                response = self.client.invoke_model(
                    modelId=self.model_id,
                    body=json.dumps(
                        {
                            "inputText": text,
                            "dimensions": self.dimensions,
                            "normalize": True,
                        }
                    ),
                    accept="application/json",
                    contentType="application/json",
                )
                vectors.extend(_extract_embeddings(json.loads(response["body"].read())))
        if len(vectors) != len(texts):
            raise ValueError(
                f"Embedding model returned {len(vectors)} vectors for "
                f"{len(texts)} texts"
            )
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise ValueError(
                    f"Embedding model returned {len(vector)} dimensions; "
                    f"expected {self.dimensions}"
                )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "search_query")[0]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts, "search_document")


def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    if settings.embedding_provider != "bedrock":
        raise RuntimeError(
            "The runtime requires a real Bedrock embedding provider. "
            "Development embeddings are available only through explicit test injection."
        )
    return BedrockEmbeddingProvider(settings)
