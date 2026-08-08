"""Model-facing Strands tools over the canonical catalog API contracts."""
from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from strands import tool

from service.catalog import get_product
from service.config import get_settings
from service.db import connect
from service.models import (
    AgentCitation,
    ProductSummary,
    SearchFilters,
    SearchRequest,
)
from service.retrieval import get_retrieval_service
from service.synthesis import synthesize_cited_answer as synthesize_answer

logger = logging.getLogger(__name__)

_RUN: ContextVar[dict[str, Any] | None] = ContextVar(
    "catalog_agent_tool_run",
    default=None,
)


def start_run(
    question: str,
    base_filters: SearchFilters,
    result_limit: int,
) -> dict[str, Any]:
    agent_run_id = uuid4()
    state: dict[str, Any] = {
        "agent_run_id": agent_run_id,
        "question": question,
        "base_filters": base_filters,
        "result_limit": result_limit,
        "trace": [],
        "retrieval_run_ids": [],
        "products": {},
        "searches": [],
        "answer_of_record": None,
    }
    _RUN.set(state)
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO catalog.agent_run (agent_run_id, question, model_id)
            VALUES (%s, %s, %s)
            """,
            (agent_run_id, question, get_settings().chat_model_id),
        )
        connection.commit()
    return state


def _state() -> dict[str, Any]:
    state = _RUN.get()
    if state is None:
        raise RuntimeError("No Strands agent run is active")
    return state


def _record(
    name: str,
    arguments: dict[str, Any],
    started: float,
    *,
    run_id: UUID | None = None,
    result_count: int | None = None,
    detail: str,
) -> None:
    state = _state()
    state["trace"].append(
        {
            "sequence": len(state["trace"]) + 1,
            "tool": name,
            "detail": detail,
            "retrieval_run_id": run_id,
            "result_count": result_count,
            "arguments": arguments,
            "latency_ms": round((perf_counter() - started) * 1_000, 2),
        }
    )


def _failure(message: str, recovery: str) -> dict[str, Any]:
    return {"ok": False, "error": message, "recovery": recovery}


def _product_for_model(product: ProductSummary) -> dict[str, Any]:
    signals = product.signals
    return {
        "product_id": product.product_id,
        "title": product.title,
        "brand": product.brand,
        "model": product.model,
        "price_usd": product.price_usd,
        "rating": product.rating,
        "availability": product.availability,
        "description": product.short_description,
        "attributes": product.attributes,
        "source_uri": product.sources[0].source_uri,
        "source_revision": product.sources[0].revision,
        "ranking": (
            {
                "final_rank": signals.final_rank,
                "pre_rerank_rank": signals.pre_rerank_rank,
                "rerank_score": signals.rerank_score,
                "rrf_score": signals.rrf_score,
                "lexical_rank": signals.lexical.rank,
                "trigram_rank": signals.trigram.rank,
                "semantic_rank": signals.semantic.rank,
            }
            if signals
            else None
        ),
    }


@tool
def search_products(
    query: str,
    domain: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    brand: str | None = None,
    availability: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_rating: float | None = None,
    attributes: dict[str, Any] | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    """Search products with PostgreSQL hybrid retrieval and managed reranking.

    Use this for each distinct part of a complex shopping question. PostgreSQL
    applies hard filters inside full-text, trigram, and semantic retrieval,
    combines arm positions with weighted RRF, and persists candidate signals
    before Cohere Rerank orders the bounded candidate pool.

    Args:
        query: Targeted product intent or exact model/SKU text.
        domain: Optional catalog domain.
        category: Optional exact category.
        subcategory: Optional exact subcategory.
        brand: Optional exact synthetic brand.
        availability: Optional In Stock, Low Stock, or Out of Stock constraint.
        min_price: Optional minimum price in USD.
        max_price: Optional maximum price in USD.
        min_rating: Optional minimum rating from 0 to 5.
        attributes: Optional exact JSON attribute constraints.
        limit: Number of products to return, from 1 to 12.

    Returns:
        A retrieval run ID and compact source-attributed products.
    """
    started = perf_counter()
    arguments = {
        "query": query,
        "domain": domain,
        "category": category,
        "subcategory": subcategory,
        "brand": brand,
        "availability": availability,
        "min_price": min_price,
        "max_price": max_price,
        "min_rating": min_rating,
        "attributes": attributes,
        "limit": limit,
    }
    state = _state()
    if not query.strip():
        return _failure(
            "query was empty",
            "retry with a targeted shopping intent or exact product identifier.",
        )
    try:
        tool_filters = SearchFilters(
            domain=domain,
            category=category,
            subcategory=subcategory,
            brand=brand,
            availability=availability,
            min_price=min_price,
            max_price=max_price,
            min_rating=min_rating,
            attributes=attributes or {},
        )
        merged = state["base_filters"].as_sql_json()
        supplied = tool_filters.as_sql_json()
        merged_attributes = dict(merged.get("attributes", {}))
        merged_attributes.update(supplied.pop("attributes", {}))
        merged.update(supplied)
        if merged_attributes:
            merged["attributes"] = merged_attributes
        filters = SearchFilters.model_validate(merged)
        response = get_retrieval_service().search(
            SearchRequest(
                query=query,
                filters=filters,
                limit=max(1, min(int(limit), state["result_limit"], 12)),
                include_diagnostics=True,
                rerank=True,
            )
        )
    except Exception as error:
        logger.warning("search_products failed: %s", error)
        _record(
            "search_products",
            arguments,
            started,
            detail=f"Search failed with {type(error).__name__}.",
        )
        return _failure(
            f"retrieval failed with {type(error).__name__}",
            "retry with a narrower query or fewer filters.",
        )

    state["retrieval_run_ids"].append(response.run_id)
    state["searches"].append(
        {
            "query": query,
            "filters": filters,
            "purpose": f"Retrieve products for: {query}",
        }
    )
    for product in response.results:
        state["products"].setdefault(product.product_id, product)
    _record(
        "search_products",
        arguments,
        started,
        run_id=response.run_id,
        result_count=len(response.results),
        detail=f"Retrieved {len(response.results)} source-attributed products.",
    )
    return {
        "ok": True,
        "run_id": str(response.run_id),
        "products": [_product_for_model(product) for product in response.results],
        "diagnostics": (
            response.diagnostics.model_dump() if response.diagnostics else None
        ),
    }


@tool
def get_product_evidence(product_id: int) -> dict[str, Any]:
    """Read one retrieved product's specifications and review evidence.

    Args:
        product_id: A product ID returned by search_products.

    Returns:
        Current product revision, structured attributes, media, and review
        evidence with source URIs.
    """
    started = perf_counter()
    state = _state()
    if product_id not in state["products"]:
        return _failure(
            "product_id was not returned by this agent run",
            "call search_products first and use a product_id from its results.",
        )
    product = get_product(product_id)
    _record(
        "get_product_evidence",
        {"product_id": product_id},
        started,
        result_count=1,
        detail=f"Read product revision and {len(product.reviews)} review sources.",
    )
    return {
        "ok": True,
        "product": {
            **_product_for_model(product),
            "long_description": product.long_description,
            "media": [item.model_dump() for item in product.media],
            "reviews": [item.model_dump() for item in product.reviews],
        },
    }


@tool
def compare_products(product_ids: list[int]) -> dict[str, Any]:
    """Compare products already retrieved in this agent run.

    Args:
        product_ids: Two to five product IDs returned by search_products.

    Returns:
        A side-by-side comparison of constraints, attributes, source revisions,
        and ranking signals.
    """
    started = perf_counter()
    state = _state()
    unique_ids = list(dict.fromkeys(product_ids))
    if not 2 <= len(unique_ids) <= 5:
        return _failure(
            "comparison requires two to five distinct products",
            "pass product IDs returned by search_products.",
        )
    unknown = [item for item in unique_ids if item not in state["products"]]
    if unknown:
        return _failure(
            f"products were not retrieved in this run: {unknown}",
            "compare only product IDs returned by search_products.",
        )
    products = [state["products"][item] for item in unique_ids]
    _record(
        "compare_products",
        {"product_ids": unique_ids},
        started,
        result_count=len(products),
        detail=f"Compared {len(products)} retrieved product sources.",
    )
    return {
        "ok": True,
        "products": [_product_for_model(product) for product in products],
    }


@tool
def explain_retrieval(run_id: str) -> dict[str, Any]:
    """Replay candidate-level ranking signals for one retrieval run.

    Args:
        run_id: A UUID returned by search_products.

    Returns:
        Persisted arm ranks, raw scores, RRF contributions, reranker scores,
        final order, and stage timings.
    """
    started = perf_counter()
    state = _state()
    try:
        parsed = UUID(run_id)
    except ValueError:
        return _failure(
            "run_id is not a UUID",
            "use the run_id returned by search_products.",
        )
    if parsed not in state["retrieval_run_ids"]:
        return _failure(
            "run_id was not created by this agent run",
            "use a run_id returned by search_products in this run.",
        )
    with connect() as connection:
        run = connection.execute(
            """
            SELECT strategy, embedding_model_id, rerank_model_id, rrf_k,
                   arm_weights, candidate_counts, stage_timings_ms,
                   total_latency_ms
            FROM catalog.retrieval_run
            WHERE run_id = %s
            """,
            (parsed,),
        ).fetchone()
        candidates = connection.execute(
            """
            SELECT product_id, lexical_rank, lexical_score,
                   lexical_contribution, trigram_rank, trigram_score,
                   trigram_contribution, semantic_rank, semantic_score,
                   semantic_contribution, rrf_score, pre_rerank_rank,
                   rerank_score, final_rank, business_score
            FROM catalog.retrieval_candidate
            WHERE run_id = %s
            ORDER BY final_rank NULLS LAST, pre_rerank_rank
            LIMIT 12
            """,
            (parsed,),
        ).fetchall()
    _record(
        "explain_retrieval",
        {"run_id": run_id},
        started,
        result_count=len(candidates),
        detail=f"Replayed {len(candidates)} persisted candidate receipts.",
    )
    return {
        "ok": True,
        "run": dict(run),
        "candidates": [dict(row) for row in candidates],
    }


@tool
def synthesize_cited_answer(
    question: str,
    product_ids: list[int],
) -> dict[str, Any]:
    """Create the answer of record from products retrieved in this run.

    Call this last. It invokes global Sonnet 5 with only the selected product
    revisions, rejects citations outside that set, and persists the validated
    answer and citation links.

    Args:
        question: The user's product question.
        product_ids: Two to six product IDs returned by search_products.

    Returns:
        The citation-validated answer of record.
    """
    started = perf_counter()
    state = _state()
    unique_ids = list(dict.fromkeys(product_ids))
    if not 1 <= len(unique_ids) <= 6:
        return _failure(
            "synthesis requires one to six distinct products",
            "select the strongest products returned by search_products.",
        )
    unknown = [item for item in unique_ids if item not in state["products"]]
    if unknown:
        return _failure(
            f"products were not retrieved in this run: {unknown}",
            "synthesize only from product IDs returned by search_products.",
        )
    products = [state["products"][item] for item in unique_ids]
    try:
        answer, citations, usage = synthesize_answer(question, products)
    except Exception as error:
        logger.warning("synthesize_cited_answer failed: %s", error)
        _record(
            "synthesize_cited_answer",
            {"question": question, "product_ids": unique_ids},
            started,
            detail=f"Synthesis failed with {type(error).__name__}.",
        )
        return _failure(
            f"synthesis failed with {type(error).__name__}",
            "retry with product IDs from the strongest retrieval result.",
        )

    state["answer_of_record"] = {
        "answer": answer,
        "citations": citations,
        "recommendations": products,
        "usage": usage,
    }
    _record(
        "synthesize_cited_answer",
        {"question": question, "product_ids": unique_ids},
        started,
        result_count=len(citations),
        detail=f"Validated and persisted {len(citations)} source citation(s).",
    )
    return {
        "ok": True,
        "answer": answer,
        "citations": [citation.model_dump() for citation in citations],
    }


TOOL_FUNCTIONS = (
    search_products,
    get_product_evidence,
    compare_products,
    explain_retrieval,
    synthesize_cited_answer,
)


def persist_completed_run(
    state: dict[str, Any],
    *,
    usage: dict[str, Any],
    error_type: str | None = None,
) -> None:
    record = state["answer_of_record"]
    plan = [
        {
            "query": item["query"],
            "filters": item["filters"].model_dump(),
            "purpose": item["purpose"],
        }
        for item in state["searches"]
    ]
    persisted_usage = {"strands": usage}
    if record:
        persisted_usage["synthesis"] = record["usage"]
    if error_type:
        persisted_usage["error_type"] = error_type
    with connect() as connection:
        connection.execute(
            """
            UPDATE catalog.agent_run
            SET completed_at = clock_timestamp(),
                plan = %s::jsonb,
                retrieval_run_ids = %s,
                answer = %s,
                tool_trace = %s::jsonb,
                usage = %s::jsonb
            WHERE agent_run_id = %s
            """,
            (
                json.dumps(plan),
                state["retrieval_run_ids"],
                record["answer"] if record else None,
                json.dumps(state["trace"], default=str),
                json.dumps(persisted_usage),
                state["agent_run_id"],
            ),
        )
        if record:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO catalog.agent_citation (
                        agent_run_id, citation_number, product_id,
                        source_uri, source_revision, quote
                    )
                    VALUES (
                        %(agent_run_id)s, %(number)s, %(product_id)s,
                        %(source_uri)s, %(revision)s, %(quote)s
                    )
                    """,
                    [
                        {
                            "agent_run_id": state["agent_run_id"],
                            **citation.model_dump(),
                        }
                        for citation in record["citations"]
                    ],
                )
        connection.commit()
