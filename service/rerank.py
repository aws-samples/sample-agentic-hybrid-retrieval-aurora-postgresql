"""Managed reranking that preserves PostgreSQL RRF provenance."""
from __future__ import annotations

from typing import Protocol, Sequence

from service.bedrock import get_bedrock_client
from service.config import Settings, get_settings


class Reranker(Protocol):
    model_id: str

    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        top_n: int,
    ) -> list[tuple[int, float]]: ...


class BedrockReranker:
    def __init__(self, settings: Settings | None = None):
        settings = settings or get_settings()
        self.model_id = settings.rerank_model_id
        self.region = settings.aws_region
        self.client = get_bedrock_client("bedrock-agent-runtime", self.region)
        self.model_arn = (
            self.model_id
            if self.model_id.startswith("arn:")
            else (
                f"arn:aws:bedrock:{self.region}::foundation-model/"
                f"{self.model_id}"
            )
        )

    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        top_n: int,
    ) -> list[tuple[int, float]]:
        if not query.strip() or not documents or top_n <= 0:
            return []
        sources = [
            {
                "type": "INLINE",
                "inlineDocumentSource": {
                    "type": "TEXT",
                    "textDocument": {"text": document},
                },
            }
            for document in documents
        ]
        response = self.client.rerank(
            queries=[{"type": "TEXT", "textQuery": {"text": query}}],
            sources=sources,
            rerankingConfiguration={
                "type": "BEDROCK_RERANKING_MODEL",
                "bedrockRerankingConfiguration": {
                    "modelConfiguration": {"modelArn": self.model_arn},
                    "numberOfResults": min(top_n, len(documents)),
                },
            },
        )
        results: list[tuple[int, float]] = []
        for item in response.get("results", []):
            index = item.get("index")
            if not isinstance(index, int) or not 0 <= index < len(documents):
                continue
            score = item.get("relevanceScore", item.get("relevance_score", 0.0))
            results.append((index, float(score or 0.0)))
        return results


def get_reranker() -> Reranker:
    settings = get_settings()
    if settings.rerank_provider != "bedrock":
        raise RuntimeError("The runtime requires the Bedrock managed reranker")
    return BedrockReranker(settings)
