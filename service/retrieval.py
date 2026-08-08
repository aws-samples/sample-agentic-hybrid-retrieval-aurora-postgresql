"""Canonical search orchestration over PostgreSQL retrieval and managed reranking."""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import numpy as np

from service.config import Settings, get_settings
from service.db import connect
from service.embeddings import EmbeddingProvider, get_embedding_provider
from service.models import (
    ProductSummary,
    RankSignal,
    ResultSignals,
    RetrievalDiagnostics,
    SearchRequest,
    SearchResponse,
    SourceAttribution,
)
from service.rerank import Reranker, get_reranker


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip()


def _document(row: dict[str, Any]) -> str:
    return (
        f"{row['title']}. {row['short_description']} "
        f"Category: {row['category']} / {row['subcategory']}. "
        f"Brand and model: {row['brand']} {row['model']}. "
        f"Price: ${row['price_usd']}. Availability: {row['availability']}. "
        f"Specifications: {json.dumps(row['attributes'], sort_keys=True)}"
    )


class RetrievalService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        reranker: Reranker | None = None,
        connection_factory: Callable = connect,
    ):
        self.settings = settings or get_settings()
        self.embedding_provider = embedding_provider
        self.reranker = reranker
        self.connection_factory = connection_factory

    def _embedder(self) -> EmbeddingProvider:
        if self.embedding_provider is None:
            self.embedding_provider = get_embedding_provider()
        return self.embedding_provider

    def _reranker(self) -> Reranker:
        if self.reranker is None:
            self.reranker = get_reranker()
        return self.reranker

    def search(self, request: SearchRequest) -> SearchResponse:
        settings = self.settings
        normalized = normalize_query(request.query)
        filters = request.filters.as_sql_json()
        run_id = uuid4()
        started = time.perf_counter()
        stage_timings: dict[str, float] = {}
        arm_weights = {
            "lexical": settings.lexical_weight,
            "trigram": settings.trigram_weight,
            "semantic": settings.semantic_weight,
        }
        with self.connection_factory() as connection:
            connection.execute(
                """
                INSERT INTO catalog.retrieval_run (
                    run_id, query_text, normalized_query, filters, strategy,
                    embedding_model_id, rerank_model_id, rrf_k, arm_weights
                )
                VALUES (%s, %s, %s, %s::jsonb, 'weighted_rrf+rerank',
                        %s, %s, %s, %s::jsonb)
                """,
                (
                    run_id,
                    request.query,
                    normalized,
                    json.dumps(filters),
                    self._embedder().model_id,
                    self._reranker().model_id if request.rerank else None,
                    settings.rrf_k,
                    json.dumps(arm_weights),
                ),
            )
            connection.commit()

        try:
            embedding_started = time.perf_counter()
            query_embedding = self._embedder().embed_query(normalized)
            stage_timings["embedding"] = round(
                (time.perf_counter() - embedding_started) * 1000,
                3,
            )

            sql_started = time.perf_counter()
            with self.connection_factory() as connection:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM catalog.search_hybrid_rrf(
                        %(query)s,
                        %(embedding)s::vector(1024),
                        %(filters)s::jsonb,
                        %(rrf_k)s::integer,
                        %(lexical_limit)s::integer,
                        %(trigram_limit)s::integer,
                        %(semantic_limit)s::integer,
                        %(result_limit)s::integer,
                        %(lexical_weight)s::real,
                        %(trigram_weight)s::real,
                        %(semantic_weight)s::real
                    )
                    """,
                    {
                        "query": normalized,
                        "embedding": np.asarray(
                            query_embedding,
                            dtype=np.float32,
                        ),
                        "filters": json.dumps(filters),
                        "rrf_k": settings.rrf_k,
                        "lexical_limit": settings.lexical_candidate_limit,
                        "trigram_limit": settings.trigram_candidate_limit,
                        "semantic_limit": settings.semantic_candidate_limit,
                        "result_limit": settings.rerank_candidate_limit,
                        "lexical_weight": settings.lexical_weight,
                        "trigram_weight": settings.trigram_weight,
                        "semantic_weight": settings.semantic_weight,
                    },
                ).fetchall()
            candidates = [dict(row) for row in rows]
            stage_timings["postgresql_retrieval"] = round(
                (time.perf_counter() - sql_started) * 1000,
                3,
            )

            rerank_status = "disabled"
            rerank_scores: dict[int, float] = {}
            if request.rerank and candidates:
                rerank_started = time.perf_counter()
                try:
                    reranked = self._reranker().rerank(
                        normalized,
                        [_document(row) for row in candidates],
                        min(len(candidates), settings.rerank_candidate_limit),
                    )
                    rerank_scores = {
                        candidates[index]["product_id"]: score
                        for index, score in reranked
                    }
                    if not rerank_scores and settings.rerank_required:
                        raise RuntimeError("The reranker returned no valid results")
                    rerank_status = "applied" if rerank_scores else "unavailable"
                except Exception:
                    if settings.rerank_required:
                        raise
                    rerank_status = "unavailable"
                stage_timings["rerank"] = round(
                    (time.perf_counter() - rerank_started) * 1000,
                    3,
                )

            if rerank_scores:
                candidates.sort(
                    key=lambda row: (
                        row["product_id"] not in rerank_scores,
                        -rerank_scores.get(row["product_id"], 0.0),
                        row["pre_rerank_rank"],
                    )
                )
            for final_rank, row in enumerate(candidates, 1):
                row["rerank_score"] = rerank_scores.get(row["product_id"])
                row["final_rank"] = final_rank

            candidate_counts = {
                "fused_pool": len(candidates),
                "lexical_in_pool": sum(
                    row["lexical_rank"] is not None for row in candidates
                ),
                "trigram_in_pool": sum(
                    row["trigram_rank"] is not None for row in candidates
                ),
                "semantic_in_pool": sum(
                    row["semantic_rank"] is not None for row in candidates
                ),
            }
            total_latency_ms = round((time.perf_counter() - started) * 1000)
            selected = candidates[: request.limit]
            with self.connection_factory() as connection:
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO catalog.retrieval_candidate (
                            run_id, product_id, lexical_rank, lexical_score,
                            lexical_contribution, trigram_rank, trigram_score,
                            trigram_contribution, semantic_rank, semantic_score,
                            semantic_contribution, rrf_score, pre_rerank_rank,
                            rerank_score, final_rank, business_score
                        )
                        VALUES (
                            %(run_id)s, %(product_id)s, %(lexical_rank)s,
                            %(lexical_score)s, %(lexical_contribution)s,
                            %(trigram_rank)s, %(trigram_score)s,
                            %(trigram_contribution)s, %(semantic_rank)s,
                            %(semantic_score)s, %(semantic_contribution)s,
                            %(rrf_score)s, %(pre_rerank_rank)s,
                            %(rerank_score)s, %(final_rank)s, %(business_score)s
                        )
                        ON CONFLICT (run_id, product_id) DO NOTHING
                        """,
                        [{"run_id": run_id, **row} for row in candidates],
                    )
                connection.execute(
                    """
                    UPDATE catalog.retrieval_run
                    SET completed_at = clock_timestamp(),
                        candidate_counts = %s::jsonb,
                        stage_timings_ms = %s::jsonb,
                        total_latency_ms = %s,
                        result_product_ids = %s
                    WHERE run_id = %s
                    """,
                    (
                        json.dumps(candidate_counts),
                        json.dumps(stage_timings),
                        total_latency_ms,
                        [row["product_id"] for row in selected],
                        run_id,
                    ),
                )
                connection.commit()
        except Exception as error:
            with self.connection_factory() as connection:
                connection.execute(
                    """
                    UPDATE catalog.retrieval_run
                    SET completed_at = clock_timestamp(),
                        total_latency_ms = %s,
                        diagnostics = jsonb_build_object(
                            'status', 'failed',
                            'error_type', %s::text
                        )
                    WHERE run_id = %s
                    """,
                    (
                        round((time.perf_counter() - started) * 1000),
                        type(error).__name__,
                        run_id,
                    ),
                )
                connection.commit()
            raise

        results = [self._result(row) for row in selected]
        diagnostics = None
        if request.include_diagnostics:
            diagnostics = RetrievalDiagnostics(
                strategy="weighted_rrf+rerank",
                embedding_model_id=self._embedder().model_id,
                rerank_model_id=(
                    self._reranker().model_id if request.rerank else None
                ),
                rerank_status=rerank_status,
                rrf_k=settings.rrf_k,
                arm_weights=arm_weights,
                candidate_counts=candidate_counts,
                stage_timings_ms=stage_timings,
                total_latency_ms=total_latency_ms,
            )
        return SearchResponse(
            run_id=run_id,
            query=request.query,
            normalized_query=normalized,
            applied_filters=filters,
            results=results,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _result(row: dict[str, Any]) -> ProductSummary:
        revision = row["updated_at"].isoformat()
        return ProductSummary(
            product_id=row["product_id"],
            sku=row["sku"],
            title=row["title"],
            short_description=row["short_description"],
            domain=row["domain"],
            category=row["category"],
            subcategory=row["subcategory"],
            brand=row["brand"],
            model=row["model"],
            price_usd=float(row["price_usd"]),
            list_price_usd=float(row["list_price_usd"]),
            rating=float(row["rating"]),
            review_count=row["review_count"],
            availability=row["availability"],
            inventory_count=row["inventory_count"],
            attributes=row["attributes"],
            tags=row["tags"],
            image_url=row.get("image_url"),
            image_source=row.get("image_source"),
            signals=ResultSignals(
                lexical=RankSignal(
                    rank=row["lexical_rank"],
                    raw_score=row["lexical_score"],
                    rrf_contribution=row["lexical_contribution"],
                ),
                trigram=RankSignal(
                    rank=row["trigram_rank"],
                    raw_score=row["trigram_score"],
                    rrf_contribution=row["trigram_contribution"],
                ),
                semantic=RankSignal(
                    rank=row["semantic_rank"],
                    raw_score=row["semantic_score"],
                    rrf_contribution=row["semantic_contribution"],
                ),
                rrf_score=float(row["rrf_score"]),
                pre_rerank_rank=row["pre_rerank_rank"],
                rerank_score=row["rerank_score"],
                final_rank=row["final_rank"],
                business_score=float(row["business_score"]),
            ),
            sources=[
                SourceAttribution(
                    source_uri=f"catalog://product/{row['product_id']}",
                    revision=revision,
                    title=row["title"],
                    quote=row["short_description"],
                )
            ],
        )


_service: RetrievalService | None = None


def get_retrieval_service() -> RetrievalService:
    global _service
    if _service is None:
        _service = RetrievalService()
    return _service


def reset_retrieval_service() -> None:
    global _service
    _service = None
