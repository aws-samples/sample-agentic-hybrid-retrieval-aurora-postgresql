"""Run unweighted and weighted RRF over one identical candidate pool.

Weighted fusion ships as a runnable comparison, not a behavior change. Per-arm
weights tuned on three missions would be overfitting presented as improvement,
and the existing eval already shows lexical beating hybrid on a judged query. So
`mosaic_search.search_hybrid_rrf` stays the served path and this module answers
one question: given the *same* candidates, what does weighting change?

**The substrate assertion.** Both functions must consume identical arm candidate
lists — same caps, same per-arm ranks — and differ only in fusion arithmetic.
Every call checks it: same candidate ID set in, different order out. If the sets
differ the call fails rather than rendering a comparison of two different pools,
because that comparison would attribute to the weights what was actually a
difference in inputs.

The check reads the **untruncated** fused pool, not the served window. Both
functions apply `LIMIT result_limit` *after* fusion, so two different orderings
truncated at the same depth necessarily disagree about the tail — measured at 36
of 50 in common while the full pools were byte-identical at 250. Comparing the
truncated windows would have failed a healthy substrate on every call.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from scripts.retrieval_profile import load_profile
from service.db import connect
from service.embeddings import EmbeddingProvider, get_embedding_provider
from service.models import (
    FusionComparisonResponse,
    FusionCandidateComparison,
    RetrievalProfile,
    SearchFilters,
)

# Deep enough to hold the whole fused pool: the arm caps sum to
# 120 + 80 + 150 = 350, so no realistic union is truncated by this.
FULL_POOL_LIMIT = 10_000

_UNWEIGHTED_SQL = """
SELECT product_id, fts_rank, trigram_rank, semantic_rank, rrf_score, provenance
FROM mosaic_search.search_hybrid_rrf(
    %(query)s, %(embedding)s::vector, %(filters)s::jsonb, %(rrf_k)s::integer,
    %(fts_limit)s::integer, %(trigram_limit)s::integer,
    %(semantic_limit)s::integer, %(result_limit)s::integer,
    %(business_weight)s::real, %(trigram_threshold)s::real
)
"""

_WEIGHTED_SQL = """
SELECT product_id, fts_rank, trigram_rank, semantic_rank, rrf_score, provenance
FROM mosaic_search.search_hybrid_rrf_weighted(
    %(query)s, %(embedding)s::vector, %(filters)s::jsonb, %(rrf_k)s::integer,
    %(fts_limit)s::integer, %(trigram_limit)s::integer,
    %(semantic_limit)s::integer, %(result_limit)s::integer,
    %(business_weight)s::real, %(trigram_threshold)s::real,
    %(weight_lexical)s::real, %(weight_semantic)s::real,
    %(weight_trigram)s::real
)
"""


class SubstrateError(RuntimeError):
    """The two fusion functions did not receive the same candidate pool.

    Raised instead of returning a comparison, because a comparison over two
    different pools silently credits the weights with a difference in inputs.
    """


class FusionComparisonService:
    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        connection_factory: Callable = connect,
    ):
        self.embedding_provider = embedding_provider
        self.connection_factory = connection_factory

    def _embedder(self) -> EmbeddingProvider:
        if self.embedding_provider is None:
            self.embedding_provider = get_embedding_provider()
        return self.embedding_provider

    def compare(
        self,
        query: str,
        filters: SearchFilters | None = None,
        *,
        top_k: int = 10,
        search_event_id: UUID | None = None,
        persist: bool = True,
    ) -> FusionComparisonResponse:
        """Fuse one candidate pool both ways and record what changed.

        Args:
            query: The query text, embedded once and shared by both functions so
                the semantic arm cannot differ between them.
            filters: Eligibility filters, applied inside each arm.
            top_k: Display depth for the two returned orders.
            search_event_id: Optional link to a `mosaic.search_event` row.
            persist: Write the comparison to `mosaic.fusion_comparison`.

        Returns:
            Both orders, per-candidate rank movement, and the fusion inputs used.

        Raises:
            SubstrateError: the two functions received different candidate sets.
        """
        profile_config = load_profile()
        profile = RetrievalProfile()
        filter_json = json.dumps((filters or SearchFilters()).as_sql_json())
        embedding = self._embedder().embed_query(query)

        params: dict[str, Any] = {
            "query": query,
            "embedding": "[" + ",".join(str(x) for x in embedding) + "]",
            "filters": filter_json,
            "rrf_k": profile_config.rrf_k,
            "fts_limit": profile_config.fts_limit,
            "trigram_limit": profile_config.trigram_limit,
            "semantic_limit": profile_config.semantic_limit,
            # The whole pool, so the substrate check compares fusion inputs
            # rather than two truncations of different orderings.
            "result_limit": FULL_POOL_LIMIT,
            "business_weight": profile_config.business_weight,
            "trigram_threshold": profile_config.trigram_threshold,
            "weight_lexical": profile_config.weight_lexical,
            "weight_semantic": profile_config.weight_semantic,
            "weight_trigram": profile_config.weight_trigram,
        }

        with self.connection_factory() as connection:
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
            started = time.perf_counter()
            unweighted = connection.execute(_UNWEIGHTED_SQL, params).fetchall()
            unweighted_ms = round((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            weighted = connection.execute(_WEIGHTED_SQL, params).fetchall()
            weighted_ms = round((time.perf_counter() - started) * 1000)

        unweighted_ids = [row["product_id"] for row in unweighted]
        weighted_ids = [row["product_id"] for row in weighted]
        identical = set(unweighted_ids) == set(weighted_ids)
        if not identical:
            only_unweighted = sorted(set(unweighted_ids) - set(weighted_ids))[:5]
            only_weighted = sorted(set(weighted_ids) - set(unweighted_ids))[:5]
            raise SubstrateError(
                f"found the two fusion functions returned different candidate "
                f"sets ({len(unweighted_ids)} vs {len(weighted_ids)}; "
                f"unweighted-only {only_unweighted}, weighted-only "
                f"{only_weighted}); fix: both must call the same three arm "
                f"functions with the same caps and the same trigram threshold, "
                f"and differ only in fusion arithmetic — a comparison over "
                f"different pools credits the weights with a difference in inputs"
            )

        unweighted_positions = {pid: i + 1 for i, pid in enumerate(unweighted_ids)}
        weighted_positions = {pid: i + 1 for i, pid in enumerate(weighted_ids)}
        weighted_rows = {row["product_id"]: row for row in weighted}

        candidates = [
            FusionCandidateComparison(
                product_id=row["product_id"],
                fts_rank=row["fts_rank"],
                trigram_rank=row["trigram_rank"],
                semantic_rank=row["semantic_rank"],
                unweighted_rrf_score=row["rrf_score"],
                weighted_rrf_score=weighted_rows[row["product_id"]]["rrf_score"],
                unweighted_rank=unweighted_positions[row["product_id"]],
                weighted_rank=weighted_positions[row["product_id"]],
                # Negative means the weighted order moved it up.
                rank_delta=(
                    weighted_positions[row["product_id"]]
                    - unweighted_positions[row["product_id"]]
                ),
            )
            for row in unweighted
        ]

        response = FusionComparisonResponse(
            fusion_comparison_id=uuid4(),
            query=query,
            applied_filters=json.loads(filter_json),
            rrf_k=profile_config.rrf_k,
            weights={
                "lexical": profile_config.weight_lexical,
                "semantic": profile_config.weight_semantic,
                "trigram": profile_config.weight_trigram,
            },
            candidate_sets_identical=identical,
            candidate_count=len(unweighted_ids),
            unweighted_order=unweighted_ids[:top_k],
            weighted_order=weighted_ids[:top_k],
            orders_differ=unweighted_ids != weighted_ids,
            unweighted_latency_ms=unweighted_ms,
            weighted_latency_ms=weighted_ms,
            candidates=sorted(candidates, key=lambda c: c.weighted_rank)[:top_k],
            moved_count=sum(1 for c in candidates if c.rank_delta != 0),
        )

        if persist:
            self._persist(response, candidates, unweighted, search_event_id, profile)
        return response

    def _persist(
        self,
        response: FusionComparisonResponse,
        candidates: list[FusionCandidateComparison],
        unweighted: list[dict[str, Any]],
        search_event_id: UUID | None,
        profile: RetrievalProfile,
    ) -> None:
        """Write the run and every candidate in one transaction.

        Phase 4's `rrf_recomputes` reads exactly these columns, so it needs no
        schema change: arm ranks, both fused scores, and the `rrf_k` and weights
        this run used rather than whatever the yaml holds when the assertion runs.
        """
        provenance = {row["product_id"]: row["provenance"] for row in unweighted}
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO mosaic.fusion_comparison (
                        fusion_comparison_id, search_event_id, query_text,
                        normalized_query, filters, retrieval_profile, rrf_k,
                        weights, candidate_sets_identical, candidate_count,
                        unweighted_order, weighted_order, orders_differ,
                        unweighted_latency_ms, weighted_latency_ms
                    ) VALUES (
                        %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb,
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        response.fusion_comparison_id,
                        search_event_id,
                        response.query,
                        response.query.strip(),
                        json.dumps(response.applied_filters),
                        profile.model_dump_json(),
                        response.rrf_k,
                        json.dumps(response.weights),
                        response.candidate_sets_identical,
                        response.candidate_count,
                        response.unweighted_order,
                        response.weighted_order,
                        response.orders_differ,
                        response.unweighted_latency_ms,
                        response.weighted_latency_ms,
                    ),
                )
                cursor.executemany(
                    """
                    INSERT INTO mosaic.fusion_comparison_candidate (
                        fusion_comparison_id, product_id, fts_rank, trigram_rank,
                        semantic_rank, unweighted_rrf_score, weighted_rrf_score,
                        unweighted_rank, weighted_rank, rank_delta, provenance
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    [
                        (
                            response.fusion_comparison_id,
                            c.product_id,
                            c.fts_rank,
                            c.trigram_rank,
                            c.semantic_rank,
                            c.unweighted_rrf_score,
                            c.weighted_rrf_score,
                            c.unweighted_rank,
                            c.weighted_rank,
                            c.rank_delta,
                            json.dumps(provenance.get(c.product_id, {})),
                        )
                        for c in candidates
                    ],
                )
            connection.commit()


_service: FusionComparisonService | None = None


def get_fusion_comparison_service() -> FusionComparisonService:
    global _service
    if _service is None:
        _service = FusionComparisonService()
    return _service
