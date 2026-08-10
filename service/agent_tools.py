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
    # A question is one turn of one session. The schema models the session so a
    # follow-up can be tied to what came before it; a single-turn ask still
    # creates both rows rather than a special flat case.
    agent_session_id = uuid4()
    agent_turn_id = uuid4()
    state: dict[str, Any] = {
        "agent_session_id": agent_session_id,
        "agent_turn_id": agent_turn_id,
        # Public API compatibility: one request is one persisted agent turn.
        "agent_run_id": agent_turn_id,
        "question": question,
        "base_filters": base_filters,
        "result_limit": result_limit,
        "trace": [],
        "search_event_ids": [],
        "products": {},
        "searches": [],
        "answer_of_record": None,
    }
    _RUN.set(state)
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO mosaic.agent_session (agent_session_id, metadata)
            VALUES (%s, %s::jsonb)
            """,
            (
                agent_session_id,
                json.dumps({"model_id": get_settings().chat_model_id}),
            ),
        )
        connection.execute(
            """
            INSERT INTO mosaic.agent_turn (
                agent_turn_id, agent_session_id, turn_number, user_message
            )
            VALUES (%s, %s, 1, %s)
            """,
            (agent_turn_id, agent_session_id, question),
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
    search_event_id: UUID | None = None,
    result_count: int | None = None,
    detail: str,
) -> None:
    state = _state()
    state["trace"].append(
        {
            "sequence": len(state["trace"]) + 1,
            "tool": name,
            "detail": detail,
            "search_event_id": search_event_id,
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
        "price_cents": product.price_cents,
        "price_display": f"${product.price_cents / 100:,.2f}",
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
                "fts_rank": signals.fts.rank,
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
    category_key: str | None = None,
    brand: str | None = None,
    availability: str | None = None,
    in_stock_only: bool = False,
    min_price_cents: int | None = None,
    max_price_cents: int | None = None,
    min_rating: float | None = None,
    attributes: dict[str, Any] | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    """Search products with PostgreSQL hybrid retrieval and managed reranking.

    Use this for one focused part of a shopping question. Use no more than two
    searches in one agent turn. PostgreSQL
    applies hard filters inside full-text, trigram, and semantic retrieval,
    fuses arm positions with reciprocal rank fusion, and persists candidate
    signals before the reranker orders the bounded candidate pool.

    Args:
        query: Targeted product intent or exact model/SKU text.
        domain: Optional consumer_electronics, running_fitness, or home_office.
        category_key: Optional exact category key such as over-ear-headphones.
        brand: Optional exact brand name.
        availability: Optional in_stock, low_stock, out_of_stock, preorder, or
            discontinued constraint.
        in_stock_only: Restrict to in_stock and low_stock when true.
        min_price_cents: Optional minimum price in integer cents, so $200 is 20000.
        max_price_cents: Optional maximum price in integer cents, so $200 is 20000.
        min_rating: Optional minimum rating from 0 to 5.
        attributes: Optional exact JSON attribute constraints.
        limit: Number of products to return, from 1 to 12.

    Returns:
        A search event ID and compact source-attributed products.
    """
    started = perf_counter()
    arguments = {
        "query": query,
        "domain": domain,
        "category_key": category_key,
        "brand": brand,
        "availability": availability,
        "in_stock_only": in_stock_only,
        "min_price_cents": min_price_cents,
        "max_price_cents": max_price_cents,
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
            category_key=category_key,
            brand=brand,
            availability=availability,
            in_stock_only=in_stock_only,
            min_price_cents=min_price_cents,
            max_price_cents=max_price_cents,
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
                limit=max(1, min(int(limit), state["result_limit"], 4)),
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

    state["search_event_ids"].append(response.search_event_id)
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
        search_event_id=response.search_event_id,
        result_count=len(response.results),
        detail=f"Retrieved {len(response.results)} source-attributed products.",
    )
    return {
        "ok": True,
        "search_event_id": str(response.search_event_id),
        "products": [_product_for_model(product) for product in response.results],
        "diagnostics": (
            {
                "strategy": response.diagnostics.strategy,
                "rerank_status": response.diagnostics.rerank_status,
                "candidate_counts": response.diagnostics.candidate_counts,
                "warnings": response.diagnostics.warnings,
            }
            if response.diagnostics
            else None
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
def explain_retrieval(search_event_id: str) -> dict[str, Any]:
    """Replay candidate-level ranking signals for one search event.

    Args:
        search_event_id: A UUID returned by search_products.

    Returns:
        Persisted arm ranks, raw scores, RRF contributions, reranker scores,
        final order, and stage timings.
    """
    started = perf_counter()
    state = _state()
    try:
        parsed = UUID(search_event_id)
    except ValueError:
        return _failure(
            "search_event_id is not a UUID",
            "use the search_event_id returned by search_products.",
        )
    # Scoped to this run on purpose: the tool is read-only, but replaying an
    # arbitrary event would let one session read another session's telemetry.
    if parsed not in state["search_event_ids"]:
        return _failure(
            "search_event_id was not created by this agent run",
            "use a search_event_id returned by search_products in this run.",
        )
    with connect() as connection:
        event = connection.execute(
            """
            SELECT query_text, normalized_query, filters, retrieval_profile,
                   candidate_counts, total_latency_ms, diagnostics
            FROM mosaic.search_event
            WHERE search_event_id = %s
            """,
            (parsed,),
        ).fetchone()
        candidates = connection.execute(
            """
            SELECT product_id, result_rank, fts_rank, trigram_rank,
                   semantic_rank, fused_rank, rerank_rank, scores, provenance
            FROM mosaic.search_result_event
            WHERE search_event_id = %s
            ORDER BY result_rank
            LIMIT 12
            """,
            (parsed,),
        ).fetchall()
    _record(
        "explain_retrieval",
        {"search_event_id": search_event_id},
        started,
        result_count=len(candidates),
        detail=f"Replayed {len(candidates)} persisted candidate receipts.",
    )
    return {
        "ok": True,
        "search_event": dict(event) if event else None,
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


def finalize_retrieved_answer(question: str) -> None:
    """Create the validated answer if orchestration stopped after retrieval."""
    started = perf_counter()
    state = _state()
    if state["answer_of_record"] is not None:
        return
    products = list(state["products"].values())[: min(state["result_limit"], 4)]
    if not products:
        raise RuntimeError("No retrieved products are available for synthesis")

    answer, citations, usage = synthesize_answer(question, products)
    state["answer_of_record"] = {
        "answer": answer,
        "citations": citations,
        "recommendations": products,
        "usage": usage,
    }
    _record(
        "synthesize_cited_answer",
        {
            "question": question,
            "product_ids": [product.product_id for product in products],
            "orchestration_fallback": True,
        },
        started,
        result_count=len(citations),
        detail=(
            "Validated cited synthesis after orchestration completed without "
            "calling its required final tool."
        ),
    )


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
        # The turn carries the assistant's answer and the plan that produced it.
        connection.execute(
            """
            UPDATE mosaic.agent_turn
            SET assistant_message = %s,
                extracted_intent = %s::jsonb
            WHERE agent_turn_id = %s
            """,
            (
                record["answer"] if record else None,
                json.dumps(
                    {
                        "plan": plan,
                        "search_event_ids": [
                            str(value) for value in state["search_event_ids"]
                        ],
                        "usage": persisted_usage,
                    },
                    default=str,
                ),
                state["agent_turn_id"],
            ),
        )
        # Every tool call is audited against its registered contract. Citations
        # ride along on the synthesis event rather than a separate table: they
        # are that tool's output, and duplicating them would allow the audit and
        # the answer to disagree.
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO mosaic.agent_tool_event (
                    agent_turn_id, search_event_id, tool_name, tool_version,
                    outcome, input_payload, output_payload, duration_ms
                )
                VALUES (
                    %(agent_turn_id)s, %(search_event_id)s, %(tool_name)s, '1.0',
                    %(outcome)s, %(input_payload)s::jsonb,
                    %(output_payload)s::jsonb, %(duration_ms)s
                )
                """,
                [
                    {
                        "agent_turn_id": state["agent_turn_id"],
                        "search_event_id": step.get("search_event_id"),
                        "tool_name": step["tool"],
                        "outcome": "success",
                        "input_payload": json.dumps(
                            step.get("arguments") or {}, default=str
                        ),
                        "output_payload": json.dumps(
                            {
                                "detail": step["detail"],
                                "result_count": step.get("result_count"),
                                "citations": (
                                    [
                                        citation.model_dump()
                                        for citation in record["citations"]
                                    ]
                                    if record and step["tool"] == "synthesize_cited_answer"
                                    else None
                                ),
                            },
                            default=str,
                        ),
                        "duration_ms": round(step.get("latency_ms") or 0),
                    }
                    for step in state["trace"]
                ],
            )
        connection.commit()
