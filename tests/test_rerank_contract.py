"""Managed reranking is all-or-nothing over the requested candidate window."""

from __future__ import annotations

from dataclasses import replace
from math import nan
from typing import Any, Self

import pytest

from service.config import get_settings
from service.models import SearchRequest
from service.rerank import BedrockReranker
from service.retrieval import RetrievalService


class _BedrockClient:
    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.results = results

    def rerank(self, **_kwargs: Any) -> dict[str, Any]:
        return {"results": self.results}


@pytest.mark.parametrize(
    "results",
    [
        [
            {"index": 0, "relevanceScore": 0.9},
            {"index": 0, "relevanceScore": 0.8},
        ],
        [
            {"index": 0, "relevanceScore": 0.9},
            {"index": 2, "relevanceScore": 0.8},
        ],
        [
            {"index": 0, "relevanceScore": nan},
            {"index": 1, "relevanceScore": 0.8},
        ],
        [{"index": 0, "relevanceScore": 0.9}],
    ],
    ids=["duplicate-index", "out-of-range-index", "non-finite-score", "partial"],
)
def test_bedrock_reranker_rejects_malformed_results(monkeypatch, results):
    """Red-at-birth: the adapter currently skips or accepts malformed entries."""
    monkeypatch.setattr(
        "service.rerank.get_bedrock_client",
        lambda *_args, **_kwargs: _BedrockClient(results),
    )

    with pytest.raises(ValueError, match="rerank response"):
        BedrockReranker(get_settings()).rerank(
            "quiet travel headphones",
            ["first candidate", "second candidate"],
            2,
        )


class _Embedder:
    model_id = "test-embed"

    def embed_query(self, _query: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]


class _Reranker:
    model_id = "test-rerank"

    def __init__(self, results: list[tuple[int, float]]) -> None:
        self.results = results

    def rerank(
        self,
        _query: str,
        _documents: list[str],
        _top_n: int,
    ) -> list[tuple[int, float]]:
        return self.results


class _Cursor:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def executemany(self, _sql: str, rows: list[dict[str, Any]]) -> None:
        self.rows = list(rows)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _Connection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.cursor_instance = _Cursor()
        self._pending: list[dict[str, Any]] = []

    def execute(self, sql: str, _params: Any = None) -> Self:
        if "FROM mosaic_search.search_hybrid_rrf(" in sql:
            self._pending = self.rows
        return self

    def fetchall(self) -> list[dict[str, Any]]:
        return self._pending

    def cursor(self) -> _Cursor:
        return self.cursor_instance

    def commit(self) -> None:
        return None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _candidate(product_id: int, fused_score: float) -> dict[str, Any]:
    return {
        "product_id": product_id,
        "sku": f"CE-AUDIO-{product_id:07d}",
        "title": f"Candidate {product_id}",
        "short_description": "A candidate document.",
        "domain": "consumer_electronics",
        "category_key": "over-ear-headphones",
        "category_path": "Audio > Over-Ear Headphones",
        "brand_name": "AuriLogic",
        "model_name": f"MODEL-{product_id}",
        "price_cents": 10_000 + product_id,
        "list_price_cents": 12_000 + product_id,
        "currency": "USD",
        "rating": 4.5,
        "review_count": 10,
        "availability": "in_stock",
        "inventory_count": 5,
        "attributes": {},
        "tags": [],
        "catalog_asset_key": None,
        "canonical_group_id": None,
        "media_tier": None,
        "is_flagship": False,
        "is_retrieval_anchor": False,
        "rerank_text": f"Candidate {product_id}.",
        "updated_at": None,
        "fts_score": fused_score,
        "trigram_score": None,
        "semantic_score": fused_score,
        "fts_rank": product_id,
        "trigram_rank": None,
        "semantic_rank": product_id,
        "rrf_score": fused_score,
        "pre_rerank_score": fused_score,
        "provenance": {"channels": {}},
    }


def _retrieval(*, rerank_required: bool) -> RetrievalService:
    connection = _Connection([_candidate(1, 0.9), _candidate(2, 0.8)])
    return RetrievalService(
        settings=replace(get_settings(), rerank_required=rerank_required),
        embedding_provider=_Embedder(),
        reranker=_Reranker([(0, 0.9), (0, 0.8)]),
        connection_factory=lambda: connection,
    )


def test_required_reranking_rejects_a_duplicate_index():
    """The protocol boundary must defend against non-Bedrock reranker adapters."""
    with pytest.raises(ValueError, match="duplicate"):
        _retrieval(rerank_required=True).search(
            SearchRequest(query="quiet headphones", limit=2)
        )


def test_optional_reranking_discards_the_entire_malformed_response():
    response = _retrieval(rerank_required=False).search(
        SearchRequest(query="quiet headphones", limit=2)
    )

    assert response.diagnostics is not None
    assert response.diagnostics.rerank_status == "unavailable"
    assert response.diagnostics.warnings == [
        "Reranker unavailable; results are in fused order."
    ]
    assert [product.product_id for product in response.results] == [1, 2]
    assert all(product.signals.rerank_score is None for product in response.results)
