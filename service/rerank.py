"""Managed reranking that preserves PostgreSQL RRF provenance."""

from __future__ import annotations

from collections.abc import Sequence
from math import isfinite
from numbers import Real
from typing import Any, Protocol

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


class RerankResponseError(ValueError):
    """The managed reranker returned a response that cannot be applied safely."""


def validate_rerank_results(
    results: Sequence[tuple[int, float]],
    *,
    document_count: int,
    expected_count: int,
) -> list[tuple[int, float]]:
    """Validate one complete reranker response before any score is applied."""
    if len(results) != expected_count:
        raise RerankResponseError(
            f"rerank response returned {len(results)} results for "
            f"expected_count {expected_count}; fix: return exactly one unique, "
            "finite score for every requested result"
        )

    validated: list[tuple[int, float]] = []
    seen: set[int] = set()
    for position, result in enumerate(results):
        if not isinstance(result, (tuple, list)) or len(result) != 2:
            raise RerankResponseError(
                f"rerank response result {position} is {result!r}; fix: return "
                "(document_index, relevance_score) pairs"
            )
        index, raw_score = result
        if isinstance(index, bool) or not isinstance(index, int):
            raise RerankResponseError(
                f"rerank response result {position} has index {index!r}; fix: "
                f"use an integer from 0 through {document_count - 1}"
            )
        if not 0 <= index < document_count:
            raise RerankResponseError(
                f"rerank response result {position} has index {index}, outside "
                f"0 through {document_count - 1}; fix: return an index for one "
                "of the submitted documents"
            )
        if index in seen:
            raise RerankResponseError(
                f"rerank response contains duplicate index {index}; fix: return "
                "each requested document index at most once"
            )
        if isinstance(raw_score, bool) or not isinstance(raw_score, Real):
            raise RerankResponseError(
                f"rerank response result {position} has score {raw_score!r}; "
                "fix: return a finite numeric relevance score"
            )
        score = float(raw_score)
        if not isfinite(score):
            raise RerankResponseError(
                f"rerank response result {position} has non-finite score "
                f"{score!r}; fix: return a finite numeric relevance score"
            )
        seen.add(index)
        validated.append((index, score))
    return validated


class BedrockReranker:
    def __init__(self, settings: Settings | None = None):
        settings = settings or get_settings()
        self.model_id = settings.rerank_model_id
        self.region = settings.aws_region
        self.client = get_bedrock_client("bedrock-agent-runtime", self.region)
        self.model_arn = (
            self.model_id
            if self.model_id.startswith("arn:")
            else (f"arn:aws:bedrock:{self.region}::foundation-model/{self.model_id}")
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
        raw_results = response.get("results")
        if not isinstance(raw_results, list):
            raise RerankResponseError(
                f"rerank response results is {type(raw_results).__name__}; fix: "
                "return a list of indexed relevance scores"
            )

        results: list[tuple[int, float]] = []
        for position, item in enumerate(raw_results):
            if not isinstance(item, dict):
                raise RerankResponseError(
                    f"rerank response result {position} is {item!r}; fix: return "
                    "an object with index and relevanceScore"
                )
            index = item.get("index")
            score: Any
            if "relevanceScore" in item:
                score = item["relevanceScore"]
            elif "relevance_score" in item:
                score = item["relevance_score"]
            else:
                raise RerankResponseError(
                    f"rerank response result {position} has no relevance score; "
                    "fix: return relevanceScore for every result"
                )
            results.append((index, score))
        return validate_rerank_results(
            results,
            document_count=len(documents),
            expected_count=min(top_n, len(documents)),
        )


def get_reranker() -> Reranker:
    settings = get_settings()
    if settings.rerank_provider != "bedrock":
        raise RuntimeError("The runtime requires the Bedrock managed reranker")
    return BedrockReranker(settings)
