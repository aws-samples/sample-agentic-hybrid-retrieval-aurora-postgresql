"""Search orchestration over `mosaic_search` and managed reranking.

Reads the denormalized retrieval projection (`mosaic_search.product_document`)
rather than joining the normalized catalog, and records each query in
`mosaic.search_event` / `mosaic.search_result_event` so a participant can inspect
exactly which arm contributed which candidate.
"""

from __future__ import annotations

import json
import re
import time
from collections import OrderedDict
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
    RetrievalPlanResponse,
    RetrievalProfile,
    SearchRequest,
    SearchResponse,
    SourceAttribution,
)
from service.rerank import Reranker, get_reranker

# The served fusion method, named so the UI can label what actually ran instead
# of hardcoding a claim. `search_hybrid_rrf` is unweighted; if the default is ever
# flipped to `search_hybrid_rrf_weighted` this string changes with it and every
# label follows, because no surface spells the method out for itself.
STRATEGY = "rrf_fusion+rerank+exact_sku_preservation"
WEIGHTED_STRATEGY = "weighted_rrf_fusion+rerank+exact_sku_preservation"

# The served fusion function. `use_weighted_fusion` selects the other one for a
# single service instance, so the mission gate and the eval harness can be run
# under both modes and compared. It is NOT request-controlled and NOT a setting:
# flipping the default is a recorded decision, and an environment variable would
# be exactly the drift the spec forbids.
_FUSION_FUNCTION = {
    False: "mosaic_search.search_hybrid_rrf",
    True: "mosaic_search.search_hybrid_rrf_weighted",
}


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip()


def _identity_key(value: str) -> str:
    """Return the punctuation-insensitive representation of a catalog identity."""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _is_exact_sku_match(query: str, sku: str) -> bool:
    """Return whether the request contains this complete, unambiguous catalog SKU."""
    query_key = _identity_key(query)
    sku_key = _identity_key(sku)
    return len(sku_key) >= 8 and sku_key in query_key


def _final_candidate_sort_key(
    row: dict[str, Any],
    rerank_scores: dict[int, float],
) -> tuple[bool, bool, float, int, int]:
    """Order final results without allowing a reranker to override a full SKU."""
    return (
        not row["exact_sku_match"],
        row["product_id"] not in rerank_scores,
        -rerank_scores.get(row["product_id"], 0.0),
        row["pre_rerank_rank"],
        row["product_id"],
    )


def _rerank_document(row: dict[str, Any]) -> str:
    """Text handed to the reranker.

    The projection already stores a purpose-built `rerank_text` that includes
    decisive filters and commerce context. Rebuilding a document here would
    diverge from what the SQL layer considers the rerank representation, so the
    stored column is preferred and the fallback is only for rows loaded before
    the projection was refreshed.
    """
    text = row.get("rerank_text")
    if text:
        return text
    return (
        f"{row['title']}. {row['short_description']} "
        f"Category: {row['category_path']}. "
        f"Brand and model: {row['brand_name']} {row['model_name']}."
    )


class RetrievalService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        reranker: Reranker | None = None,
        connection_factory: Callable = connect,
        use_weighted_fusion: bool = False,
    ):
        self.settings = settings or get_settings()
        self.embedding_provider = embedding_provider
        self.reranker = reranker
        self.connection_factory = connection_factory
        # Default False: the served path is unweighted until an explicit ruling.
        self.use_weighted_fusion = use_weighted_fusion
        self._query_embedding_cache: OrderedDict[str, tuple[float, ...]] = OrderedDict()

    def _embedder(self) -> EmbeddingProvider:
        if self.embedding_provider is None:
            self.embedding_provider = get_embedding_provider()
        return self.embedding_provider

    def _reranker(self) -> Reranker:
        if self.reranker is None:
            self.reranker = get_reranker()
        return self.reranker

    def _strategy(self) -> str:
        """Name the fusion method that actually ran.

        Persisted with the run and returned in diagnostics, so every surface
        labels what happened instead of asserting what it assumes. `ui/src/fusion.ts`
        derives its copy from this string.
        """
        return WEIGHTED_STRATEGY if self.use_weighted_fusion else STRATEGY

    def _embed_query(self, normalized_query: str) -> tuple[float, ...]:
        """Return one stable vector for repeated normalized queries.

        Managed embedding inference can vary at floating-point precision across
        otherwise identical calls. Reusing the first vector keeps workshop
        ranking fixtures repeatable without changing SQL ranking semantics.
        """
        cached = self._query_embedding_cache.get(normalized_query)
        if cached is not None:
            self._query_embedding_cache.move_to_end(normalized_query)
            return cached

        embedded = tuple(self._embedder().embed_query(normalized_query))
        self._query_embedding_cache[normalized_query] = embedded
        if len(self._query_embedding_cache) > 256:
            self._query_embedding_cache.popitem(last=False)
        return embedded

    def embed_query(self, query: str) -> list[float]:
        """Embed one normalized query through the production retrieval provider."""
        return list(self._embed_query(normalize_query(query)))

    def _profile(self, request: SearchRequest) -> RetrievalProfile:
        settings = self.settings
        return RetrievalProfile(
            fts_limit=settings.lexical_candidate_limit,
            trigram_limit=settings.trigram_candidate_limit,
            semantic_limit=settings.semantic_candidate_limit,
            fused_limit=settings.rerank_candidate_limit,
            result_limit=request.limit,
            authorized_limit=request.authorized_limit,
            rrf_k=settings.rrf_k,
            ef_search=settings.hnsw_ef_search,
        )

    @staticmethod
    def _configure_hnsw(connection: Any, profile: RetrievalProfile) -> None:
        connection.execute(
            """
            SELECT mosaic_search.configure_hnsw(
                %s::integer, %s::text, %s::integer, %s::real
            )
            """,
            (
                profile.ef_search,
                profile.iterative_scan,
                profile.max_scan_tuples,
                profile.scan_mem_multiplier,
            ),
        )

    def _fusion_parameters(
        self,
        normalized_query: str,
        query_embedding: tuple[float, ...],
        filters: dict[str, Any],
        profile: RetrievalProfile,
        *,
        weighted: bool | None = None,
    ) -> dict[str, Any]:
        use_weighted = self.use_weighted_fusion if weighted is None else weighted
        parameters: dict[str, Any] = {
            "query": normalized_query,
            "embedding": np.asarray(query_embedding, dtype=np.float32),
            "filters": json.dumps(filters),
            "rrf_k": profile.rrf_k,
            "fts_limit": profile.fts_limit,
            "trigram_limit": profile.trigram_limit,
            "semantic_limit": profile.semantic_limit,
            "fused_limit": profile.fused_limit,
            "trigram_threshold": profile.trigram_threshold,
        }
        if use_weighted:
            parameters.update(
                weight_lexical=profile.weight_lexical,
                weight_semantic=profile.weight_semantic,
                weight_trigram=profile.weight_trigram,
            )
        return parameters

    def _fusion_sql(self, *, weighted: bool | None = None) -> str:
        use_weighted = self.use_weighted_fusion if weighted is None else weighted
        weight_args = ""
        if use_weighted:
            weight_args = (
                ",\n                %(weight_lexical)s::real,"
                "\n                %(weight_semantic)s::real,"
                "\n                %(weight_trigram)s::real"
            )
        return f"""
            SELECT h.*, d.sku, d.short_description, d.inventory_count,
                   d.review_count, d.attributes, d.tags, d.domain,
                   d.category_key, d.model_name, d.media_tier,
                   d.is_flagship, d.is_retrieval_anchor, d.rerank_text,
                   d.list_price_cents, d.currency, d.updated_at
            FROM {_FUSION_FUNCTION[use_weighted]}(
                %(query)s,
                %(embedding)s::vector,
                %(filters)s::jsonb,
                %(rrf_k)s::integer,
                %(fts_limit)s::integer,
                %(trigram_limit)s::integer,
                %(semantic_limit)s::integer,
                %(fused_limit)s::integer,
                %(trigram_threshold)s::real{weight_args}
            ) AS h
            JOIN mosaic_search.product_document d USING (product_id)
            ORDER BY h.pre_rerank_score DESC, h.product_id
        """

    def search(self, request: SearchRequest) -> SearchResponse:
        normalized = normalize_query(request.query)
        filters = request.filters.as_sql_json()
        profile = self._profile(request)
        search_event_id = uuid4()
        started = time.perf_counter()
        stage_timings: dict[str, float] = {}
        warnings: list[str] = []

        with self.connection_factory() as connection:
            connection.execute(
                """
                INSERT INTO mosaic.search_event (
                    search_event_id, session_id, query_text, normalized_query,
                    filters, retrieval_profile, source_revision,
                    source_worktree_dirty, dataset_manifest_sha256,
                    embedding_model_id, rerank_model_id, retrieval_strategy,
                    database_instance_id, database_version,
                    vector_extension_version, aurora_instance_class,
                    hnsw_settings
                )
                VALUES (
                    %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s,
                    %s, %s, aurora_db_instance_identifier(),
                    current_setting('server_version'),
                    (SELECT extversion FROM pg_extension WHERE extname = 'vector'),
                    %s, %s::jsonb
                )
                """,
                (
                    search_event_id,
                    request.session_id,
                    request.query,
                    normalized,
                    json.dumps(filters),
                    profile.model_dump_json(),
                    self.settings.source_revision,
                    self.settings.source_worktree_dirty,
                    self.settings.dataset_manifest_sha256,
                    self._embedder().model_id,
                    self._reranker().model_id if request.rerank else None,
                    self._strategy(),
                    self.settings.aurora_instance_class,
                    json.dumps(
                        {
                            "ef_search": profile.ef_search,
                            "iterative_scan": profile.iterative_scan,
                            "max_scan_tuples": profile.max_scan_tuples,
                            "scan_mem_multiplier": profile.scan_mem_multiplier,
                        }
                    ),
                ),
            )
            connection.commit()

        try:
            embedding_started = time.perf_counter()
            query_embedding = self._embed_query(normalized)
            stage_timings["embedding"] = round(
                (time.perf_counter() - embedding_started) * 1000, 3
            )

            sql_started = time.perf_counter()
            with self.connection_factory() as connection:
                # Per-session HNSW controls. These are SET LOCAL inside the
                # function's transaction, so one tuned query cannot leak its
                # ef_search into the next.
                # Every argument is cast explicitly. psycopg infers the SQL type
                # from the Python type, so an integral float arriving as `1.0`
                # rather than `1` resolves the `real` parameter to `double
                # precision`, no overload matches, and every search fails with
                # UndefinedFunction. Naming the types here makes the call
                # independent of how the profile happens to be stored.
                self._configure_hnsw(connection, profile)
                rows = connection.execute(
                    self._fusion_sql(),
                    self._fusion_parameters(
                        normalized,
                        query_embedding,
                        filters,
                        profile,
                    ),
                ).fetchall()
            candidates = [dict(row) for row in rows]
            stage_timings["postgresql_retrieval"] = round(
                (time.perf_counter() - sql_started) * 1000, 3
            )

            # The SQL orders by pre_rerank_score; capture that as the fused rank
            # before the reranker is allowed to reorder anything.
            for fused_rank, row in enumerate(candidates, 1):
                row["pre_rerank_rank"] = fused_rank
                row["exact_sku_match"] = _is_exact_sku_match(normalized, row["sku"])

            rerank_status = "disabled"
            rerank_scores: dict[int, float] = {}
            if request.rerank and candidates:
                rerank_started = time.perf_counter()
                try:
                    reranked = self._reranker().rerank(
                        normalized,
                        [_rerank_document(row) for row in candidates],
                        min(len(candidates), profile.fused_limit),
                    )
                    rerank_scores = {
                        candidates[index]["product_id"]: score
                        for index, score in reranked
                    }
                    if not rerank_scores and self.settings.rerank_required:
                        raise RuntimeError("The reranker returned no valid results")
                    rerank_status = "applied" if rerank_scores else "unavailable"
                    if not rerank_scores:
                        warnings.append(
                            "Reranking returned no scores; fused order kept."
                        )
                except Exception:
                    if self.settings.rerank_required:
                        raise
                    rerank_status = "unavailable"
                    warnings.append("Reranker unavailable; results are in fused order.")
                stage_timings["rerank"] = round(
                    (time.perf_counter() - rerank_started) * 1000, 3
                )

            rerank_order = sorted(
                candidates,
                key=lambda row: (
                    row["product_id"] not in rerank_scores,
                    -rerank_scores.get(row["product_id"], 0.0),
                    row["pre_rerank_rank"],
                    row["product_id"],
                ),
            )
            for rerank_rank, row in enumerate(rerank_order, 1):
                row["rerank_rank"] = rerank_rank if rerank_scores else None

            candidates.sort(
                key=lambda row: _final_candidate_sort_key(row, rerank_scores)
            )
            for final_rank, row in enumerate(candidates, 1):
                row["rerank_score"] = rerank_scores.get(row["product_id"])
                row["final_rank"] = final_rank

            candidate_counts = {
                "fused_pool": len(candidates),
                "fts_in_pool": sum(row["fts_rank"] is not None for row in candidates),
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
                        INSERT INTO mosaic.search_result_event (
                            search_event_id, product_id, result_rank, fts_rank,
                            trigram_rank, semantic_rank, fused_rank, rerank_rank,
                            scores, provenance
                        )
                        VALUES (
                            %(search_event_id)s, %(product_id)s, %(result_rank)s,
                            %(fts_rank)s, %(trigram_rank)s, %(semantic_rank)s,
                            %(fused_rank)s, %(rerank_rank)s,
                            %(scores)s::jsonb, %(provenance)s::jsonb
                        )
                        ON CONFLICT (search_event_id, product_id) DO NOTHING
                        """,
                        [
                            {
                                "search_event_id": search_event_id,
                                "product_id": row["product_id"],
                                "result_rank": row["final_rank"],
                                "fts_rank": row["fts_rank"],
                                "trigram_rank": row["trigram_rank"],
                                "semantic_rank": row["semantic_rank"],
                                "fused_rank": row["pre_rerank_rank"],
                                "rerank_rank": row["rerank_rank"],
                                "scores": json.dumps(
                                    {
                                        "fts": _as_float(row["fts_score"]),
                                        "trigram": _as_float(row["trigram_score"]),
                                        "semantic": _as_float(row["semantic_score"]),
                                        "rrf": _as_float(row["rrf_score"]),
                                        "pre_rerank": _as_float(
                                            row["pre_rerank_score"]
                                        ),
                                        "rerank": _as_float(row["rerank_score"]),
                                        "exact_sku_match": row["exact_sku_match"],
                                    }
                                ),
                                "provenance": json.dumps(row["provenance"]),
                            }
                            for row in candidates
                        ],
                    )
                connection.execute(
                    """
                    UPDATE mosaic.search_event
                    SET candidate_counts = %s::jsonb,
                        total_latency_ms = %s,
                        diagnostics = %s::jsonb
                    WHERE search_event_id = %s
                    """,
                    (
                        json.dumps(candidate_counts),
                        total_latency_ms,
                        json.dumps(
                            {
                                "status": "ok",
                                "strategy": self._strategy(),
                                "rerank_status": rerank_status,
                                "ranking_policy": [
                                    "RRF candidate fusion",
                                    "managed reranking",
                                    "exact SKU preservation",
                                ],
                                "stage_timings_ms": stage_timings,
                                "warnings": warnings,
                            }
                        ),
                        search_event_id,
                    ),
                )
                connection.commit()
        except Exception as error:
            with self.connection_factory() as connection:
                connection.execute(
                    """
                    UPDATE mosaic.search_event
                    SET total_latency_ms = %s,
                        diagnostics = jsonb_build_object(
                            'status', 'failed',
                            'error_type', %s::text
                        )
                    WHERE search_event_id = %s
                    """,
                    (
                        round((time.perf_counter() - started) * 1000),
                        type(error).__name__,
                        search_event_id,
                    ),
                )
                connection.commit()
            raise

        diagnostics = None
        if request.include_diagnostics:
            diagnostics = RetrievalDiagnostics(
                strategy=self._strategy(),
                embedding_model_id=self._embedder().model_id,
                embedding_dimensions=self.settings.embedding_dimensions,
                rerank_model_id=(self._reranker().model_id if request.rerank else None),
                rerank_status=rerank_status,
                ranking_policy=[
                    "RRF candidate fusion",
                    "managed reranking",
                    "exact SKU preservation",
                ],
                retrieval_profile=profile,
                candidate_counts=candidate_counts,
                stage_timings_ms=stage_timings,
                total_latency_ms=total_latency_ms,
                warnings=warnings,
            )
        return SearchResponse(
            search_event_id=search_event_id,
            query=request.query,
            normalized_query=normalized,
            applied_filters=filters,
            results=[self._result(row) for row in selected],
            diagnostics=diagnostics,
        )

    def capture_plan(self, search_event_id: UUID) -> RetrievalPlanResponse:
        """Capture the production fusion query plan for one persisted event."""
        with self.connection_factory() as connection:
            event = connection.execute(
                """
                SELECT normalized_query, filters, retrieval_profile,
                       retrieval_strategy
                FROM mosaic.search_event
                WHERE search_event_id = %s
                """,
                (search_event_id,),
            ).fetchone()
        if event is None:
            raise KeyError(f"Retrieval event {search_event_id} was not found")

        normalized = event["normalized_query"]
        filters = event["filters"]
        profile = RetrievalProfile.model_validate(event["retrieval_profile"])
        weighted = event["retrieval_strategy"] == WEIGHTED_STRATEGY
        embedding = self._embed_query(normalized)
        started = time.perf_counter()
        with self.connection_factory() as connection:
            self._configure_hnsw(connection, profile)
            plan_row = connection.execute(
                "EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON) "
                + self._fusion_sql(weighted=weighted),
                self._fusion_parameters(
                    normalized,
                    embedding,
                    filters,
                    profile,
                    weighted=weighted,
                ),
            ).fetchone()
            plan = plan_row["QUERY PLAN"] if isinstance(plan_row, dict) else plan_row[0]
            connection.execute(
                """
                UPDATE mosaic.search_event
                SET plan_json = %s::jsonb,
                    diagnostics = diagnostics || jsonb_build_object(
                        'plan_capture_ms', %s::numeric
                    )
                WHERE search_event_id = %s
                """,
                (
                    json.dumps(plan),
                    round((time.perf_counter() - started) * 1000, 3),
                    search_event_id,
                ),
            )
            connection.commit()
        return RetrievalPlanResponse(search_event_id=search_event_id, plan=plan)

    @staticmethod
    def _result(row: dict[str, Any]) -> ProductSummary:
        updated_at = row.get("updated_at")
        revision = updated_at.isoformat() if updated_at else "unversioned"
        return ProductSummary(
            product_id=row["product_id"],
            sku=row["sku"],
            title=row["title"],
            short_description=row["short_description"],
            domain=row["domain"],
            category_key=row["category_key"],
            category_path=row["category_path"],
            brand=row["brand_name"],
            model=row["model_name"],
            price_cents=row["price_cents"],
            list_price_cents=row["list_price_cents"],
            currency=row.get("currency") or "USD",
            rating=_as_float(row.get("rating")),
            review_count=row["review_count"],
            availability=row["availability"],
            inventory_count=row["inventory_count"],
            attributes=row["attributes"],
            tags=list(row["tags"] or []),
            catalog_asset_key=row.get("catalog_asset_key"),
            canonical_group_id=row.get("canonical_group_id"),
            media_tier=row.get("media_tier"),
            is_flagship=bool(row.get("is_flagship")),
            is_retrieval_anchor=bool(row.get("is_retrieval_anchor")),
            signals=ResultSignals(
                fts=RankSignal(
                    rank=row["fts_rank"],
                    raw_score=_as_float(row["fts_score"]),
                    rrf_contribution=_contribution(row, "fts"),
                ),
                trigram=RankSignal(
                    rank=row["trigram_rank"],
                    raw_score=_as_float(row["trigram_score"]),
                    rrf_contribution=_contribution(row, "trigram"),
                ),
                semantic=RankSignal(
                    rank=row["semantic_rank"],
                    raw_score=_as_float(row["semantic_score"]),
                    rrf_contribution=_contribution(row, "vector"),
                ),
                rrf_score=float(row["rrf_score"]),
                pre_rerank_rank=row["pre_rerank_rank"],
                pre_rerank_score=float(row["pre_rerank_score"]),
                rerank_score=_as_float(row.get("rerank_score")),
                rerank_rank=row.get("rerank_rank"),
                exact_sku_match=bool(row["exact_sku_match"]),
                final_rank=row["final_rank"],
            ),
            sources=[
                SourceAttribution(
                    source_uri=f"mosaic://product/{row['product_id']}",
                    revision=revision,
                    title=row["title"],
                    quote=row["short_description"],
                )
            ],
        )


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _contribution(row: dict[str, Any], channel: str) -> float | None:
    """Pull one arm's RRF contribution out of the SQL-built provenance.

    The database computes each contribution as part of fusion; recomputing it in
    Python from the rank would be a second implementation of the same formula
    and could disagree with what was actually fused.
    """
    channels = (row.get("provenance") or {}).get("channels") or {}
    entry = channels.get(channel) or {}
    return _as_float(entry.get("rrf_contribution"))


_service: RetrievalService | None = None


def get_retrieval_service() -> RetrievalService:
    global _service
    if _service is None:
        _service = RetrievalService()
    return _service
