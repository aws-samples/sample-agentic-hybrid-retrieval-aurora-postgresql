from __future__ import annotations

import logging
from typing import Any

from .config import get_settings

logger = logging.getLogger(__name__)


class CohereRerankService:
    """Cohere Rerank v3.5 via Amazon Bedrock.

    AWS exposes Cohere Rerank through the Bedrock Agent Runtime rerank API. The
    model remains Cohere; Bedrock is the managed AWS transport and IAM boundary.
    """

    def __init__(self, region: str | None = None, model_id: str | None = None):
        from .bedrock import get_bedrock_client

        settings = get_settings()
        self.region = region or settings.aws_region
        self.model_id = model_id or settings.cohere_rerank_model
        self.model_arn = (
            self.model_id
            if self.model_id.startswith("arn:")
            else f"arn:aws:bedrock:{self.region}::foundation-model/{self.model_id}"
        )
        self.client = get_bedrock_client("bedrock-agent-runtime", region=self.region)

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int,
        *,
        raise_errors: bool = False,
    ) -> list[dict[str, Any]]:
        if not query.strip() or not documents or top_n <= 0:
            return []

        settings = get_settings()
        max_documents = settings.cohere_rerank_max_documents
        bounded_documents = documents[:max_documents]
        bounded_top_n = min(top_n, len(bounded_documents))
        sources = [
            {
                "type": "INLINE",
                "inlineDocumentSource": {
                    "type": "TEXT",
                    "textDocument": {"text": document},
                },
            }
            for document in bounded_documents
        ]

        try:
            response = self.client.rerank(
                queries=[{"type": "TEXT", "textQuery": {"text": query}}],
                sources=sources,
                rerankingConfiguration={
                    "type": "BEDROCK_RERANKING_MODEL",
                    "bedrockRerankingConfiguration": {
                        "modelConfiguration": {"modelArn": self.model_arn},
                        "numberOfResults": bounded_top_n,
                    },
                },
            )
        except Exception as exc:
            logger.warning("Cohere Rerank via Bedrock failed: %s", exc)
            if raise_errors:
                raise
            return []

        results: list[dict[str, Any]] = []
        for item in response.get("results", []):
            index = item.get("index")
            if not isinstance(index, int):
                continue
            score = item.get("relevanceScore", item.get("relevance_score", 0.0))
            results.append({"index": index, "relevance_score": float(score or 0.0)})
        return results


_service: CohereRerankService | None = None


def get_cohere_rerank_service() -> CohereRerankService:
    global _service
    if _service is None:
        _service = CohereRerankService()
    return _service
