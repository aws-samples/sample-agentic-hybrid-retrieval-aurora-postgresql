"""Model-facing Strands tools over the canonical catalog API contracts."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from strands import tool

from service.catalog import get_product_evidence_records
from service.config import get_settings
from service.db import connect
from service.model_runtime import model_runtime_error
from service.models import (
    ProductSummary,
    SearchFilters,
    SearchRequest,
)
from service.retrieval import get_retrieval_service
from service.synthesis import synthesize_cited_answer as synthesize_answer

logger = logging.getLogger(__name__)

SEARCH_SLOTS = ("primary", "follow_up")

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
        "evidence": {},
        "evidence_by_product": {},
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
                json.dumps(
                    {
                        # Existing telemetry readers used model_id before model
                        # routing split into two explicit phases.
                        "model_id": get_settings().agent_model_id,
                        "agent_model_id": get_settings().agent_model_id,
                        "synthesis_model_id": get_settings().synthesis_model_id,
                    }
                ),
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
    outcome: str = "success",
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
            "outcome": outcome,
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


def _evidence_for_model(item: Any) -> dict[str, Any]:
    """Return the source fields the orchestrator needs without duplicate state."""
    return {
        "evidence_id": item.evidence_id,
        "product_id": item.product_id,
        "evidence_type": item.evidence_type,
        "source_name": item.source_name,
        "source_uri": item.source_uri,
        "revision": item.revision,
        "title": item.title,
        "text": item.text,
        "rating": item.rating,
        "is_verified": item.is_verified,
    }


def _comparison_for_model(product: ProductSummary) -> dict[str, Any]:
    """Return only fields that change a side-by-side product decision."""
    context = _product_for_model(product)
    return {
        key: context[key]
        for key in (
            "product_id",
            "title",
            "price_cents",
            "price_display",
            "rating",
            "availability",
            "attributes",
            "ranking",
        )
    }


def _merge_search_filters(
    base: SearchFilters,
    supplied: SearchFilters,
) -> SearchFilters:
    """Intersect model-proposed filters with request-level constraints."""

    def exact(field: str) -> Any:
        base_value = getattr(base, field)
        return base_value if base_value is not None else getattr(supplied, field)

    def lower_bound(field: str) -> int | float | None:
        values = [
            value
            for value in (getattr(base, field), getattr(supplied, field))
            if value is not None
        ]
        return max(values) if values else None

    def upper_bound(field: str) -> int | None:
        values = [
            value
            for value in (getattr(base, field), getattr(supplied, field))
            if value is not None
        ]
        return min(values) if values else None

    return SearchFilters(
        domain=exact("domain"),
        category_key=exact("category_key"),
        brand=exact("brand"),
        brands=base.brands or supplied.brands,
        availability=exact("availability"),
        in_stock_only=base.in_stock_only or supplied.in_stock_only,
        min_price_cents=lower_bound("min_price_cents"),
        max_price_cents=upper_bound("max_price_cents"),
        min_rating=lower_bound("min_rating"),
        attributes={**supplied.attributes, **base.attributes},
        include_refurbished=base.include_refurbished,
        include_sponsored=base.include_sponsored,
    )


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

    Use this for one focused part of a shopping question. Run a primary search
    and, only when needed, one follow-up search. PostgreSQL
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
        attributes: Optional exact JSON attribute constraints. For explicit
            home-office requirements, use quiet_typing=true for
            quiet-keyboards and seat_depth_adjustable=true for
            ergonomic-office-chairs.
        limit: Number of products to return, from 1 to 2. The per-search
            response cap keeps the agent's comparison and evidence work
            inspectable within one workshop turn.

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
    search_budget = len(SEARCH_SLOTS)
    if len(state["searches"]) >= search_budget:
        return _failure(
            (
                f"search_products allows {search_budget} searches per agent "
                f"turn; found {len(state['searches'])}"
            ),
            (
                "use the products already retrieved and call "
                "synthesize_cited_answer, or state the evidence gap."
            ),
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
        filters = _merge_search_filters(state["base_filters"], tool_filters)
        arguments["applied_filters"] = filters.as_sql_json()
        requested_limit = max(
            1,
            min(int(limit), state["result_limit"], len(SEARCH_SLOTS)),
        )
        response = get_retrieval_service().search(
            SearchRequest(
                query=query,
                filters=filters,
                # The agent receives the complete bounded rerank window. Evidence
                # is retrieved later for its selected products; it never changes
                # product eligibility or retrieval order.
                limit=get_settings().rerank_candidate_limit,
                include_diagnostics=True,
                rerank=True,
            )
        )
    except Exception as error:
        classified = model_runtime_error(error)
        if classified is not None:
            raise classified from error
        logger.warning("search_products failed: %s", error)
        _record(
            "search_products",
            arguments,
            started,
            detail=f"Search failed with {type(error).__name__}.",
            outcome="error",
        )
        return _failure(
            f"retrieval failed with {type(error).__name__}",
            "retry with a narrower query or fewer filters.",
        )

    ranked_results = response.results[:requested_limit]
    if not ranked_results:
        _record(
            "search_products",
            arguments,
            started,
            search_event_id=response.search_event_id,
            result_count=0,
            detail="Retrieval completed, but no eligible product was returned.",
            outcome="error",
        )
        return _failure(
            "no eligible products were available in the ranked window",
            "retry with a broader query or fewer filters.",
        )

    state["search_event_ids"].append(response.search_event_id)
    state["searches"].append(
        {
            "query": query,
            "filters": filters,
            "purpose": f"Retrieve products for: {query}",
            "product_ids": [product.product_id for product in ranked_results],
        }
    )
    for product in ranked_results:
        state["products"].setdefault(product.product_id, product)
    _record(
        "search_products",
        arguments,
        started,
        search_event_id=response.search_event_id,
        result_count=len(ranked_results),
        detail=(
            f"Retrieved {len(ranked_results)} ranked products from the bounded "
            f"rerank window; evidence remains a separate query-grounded step."
        ),
    )
    return {
        "ok": True,
        "search_event_id": str(response.search_event_id),
        "products": [_product_for_model(product) for product in ranked_results],
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
def get_product_evidence(product_id: int, evidence_query: str) -> dict[str, Any]:
    """Retrieve question-ranked evidence for one retrieved product.

    Args:
        product_id: A product ID returned by search_products.
        evidence_query: The shopper question or focused subquestion that the
            evidence must support.

    Returns:
        Compact retrieved-product context and bounded source-addressable
        specification and review evidence.
    """
    started = perf_counter()
    state = _state()
    if product_id not in state["products"]:
        return _failure(
            "product_id was not returned by this agent run",
            "call search_products first and use a product_id from its results.",
        )
    if not evidence_query.strip():
        return _failure(
            "evidence_query was empty",
            "pass the shopper question or a focused subquestion to rank evidence.",
        )
    arguments = {"product_id": product_id, "evidence_query": evidence_query}
    try:
        query_embedding = get_retrieval_service().embed_query(evidence_query)
        evidence = get_product_evidence_records(
            product_id,
            evidence_query,
            query_embedding,
            limit=len(SEARCH_SLOTS),
        )
    except Exception as error:
        classified = model_runtime_error(error)
        if classified is not None:
            raise classified from error
        logger.warning("get_product_evidence failed: %s", error)
        _record(
            "get_product_evidence",
            arguments,
            started,
            result_count=0,
            detail=f"Evidence retrieval failed with {type(error).__name__}.",
            outcome="error",
        )
        return _failure(
            f"evidence retrieval failed with {type(error).__name__}",
            "retry with a focused evidence question or another retrieved product.",
        )
    if not evidence:
        _record(
            "get_product_evidence",
            arguments,
            started,
            result_count=0,
            detail="No evidence records were available for the retrieved product.",
            outcome="error",
        )
        return _failure(
            "no evidence records were available for this product",
            "choose another retrieved product or state the evidence gap.",
        )
    # LAB3_EVIDENCE_STATE_START
    for item in evidence:
        state["evidence"][item.evidence_id] = item
        product_evidence = state["evidence_by_product"].setdefault(product_id, [])
        if item.evidence_id not in product_evidence:
            product_evidence.append(item.evidence_id)
    # LAB3_EVIDENCE_STATE_END
    _record(
        "get_product_evidence",
        arguments,
        started,
        result_count=len(evidence),
        detail=(
            f"Retrieved {len(evidence)} source-addressable evidence record(s) "
            "ranked against the supplied evidence query."
        ),
    )
    return {
        "ok": True,
        "product_id": product_id,
        "evidence": [_evidence_for_model(item) for item in evidence],
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
        "products": [_comparison_for_model(product) for product in products],
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
    if any(
        step["tool"] == "explain_retrieval"
        and step.get("outcome", "success") == "success"
        for step in state["trace"]
    ):
        return _failure(
            "ranking was already explained in this run",
            "continue to grounded synthesis with the existing ranking receipt.",
        )
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

    Call this last. It invokes the configured citation model with only the
    selected product revisions, rejects citations outside that set, and
    persists the validated answer and citation links.

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
    explanations = [
        step
        for step in state["trace"]
        if step["tool"] == "explain_retrieval"
        and step.get("outcome", "success") == "success"
    ]
    if len(explanations) != 1:
        _record(
            "synthesize_cited_answer",
            {"question": question, "product_ids": unique_ids},
            started,
            result_count=0,
            detail=(
                "Grounded synthesis blocked; exactly one ranking explanation "
                f"is required, found {len(explanations)}."
            ),
            outcome="error",
        )
        return _failure(
            "selected products do not have exactly one ranking explanation",
            "call explain_retrieval once with the strongest search_event_id "
            "before synthesis.",
        )
    if len(unique_ids) > 1 and not _comparison_covers(state, unique_ids):
        _record(
            "synthesize_cited_answer",
            {"question": question, "product_ids": unique_ids},
            started,
            result_count=0,
            detail="Grounded synthesis blocked; products were not compared.",
            outcome="error",
        )
        return _failure(
            "selected products were not compared in this run",
            "call compare_products with every selected product before synthesis.",
        )
    evidence = _evidence_for_products(state, unique_ids)
    missing_evidence = [
        product_id
        for product_id in unique_ids
        if not state["evidence_by_product"].get(product_id)
    ]
    if missing_evidence:
        _record(
            "synthesize_cited_answer",
            {"question": question, "product_ids": unique_ids},
            started,
            result_count=0,
            detail=f"Grounded synthesis blocked; missing evidence for {missing_evidence}.",
            outcome="error",
        )
        return _failure(
            f"products lack retrieved evidence: {missing_evidence}",
            "call get_product_evidence for every product before synthesis.",
        )
    try:
        answer, citations, usage = synthesize_answer(question, products, evidence)
    except Exception as error:
        classified = model_runtime_error(error)
        if classified is not None:
            raise classified from error
        logger.warning("synthesize_cited_answer failed: %s", error)
        _record(
            "synthesize_cited_answer",
            {"question": question, "product_ids": unique_ids},
            started,
            detail=f"Synthesis failed with {type(error).__name__}.",
            outcome="error",
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


def _fallback_product_ids(state: dict[str, Any]) -> list[int]:
    """Choose a bounded shortlist from explicit comparison or search order."""
    for step in reversed(state["trace"]):
        compared = list((step.get("arguments") or {}).get("product_ids", []))
        if (
            step["tool"] == "compare_products"
            and step.get("outcome", "success") == "success"
            and 2 <= len(compared) <= 4
            and all(product_id in state["products"] for product_id in compared)
        ):
            return compared

    selected: list[int] = []
    for search in state["searches"]:
        for product_id in search.get("product_ids", [])[:2]:
            if product_id not in selected:
                selected.append(product_id)
    if not selected:
        selected.extend(state["products"])
    limit = max(1, min(state["result_limit"], 4))
    return selected[:limit]


def complete_grounded_answer(question: str) -> None:
    """Complete missing compare/evidence steps over retrieved products only."""
    state = _state()
    product_ids = _fallback_product_ids(state)
    if not product_ids:
        raise RuntimeError("No retrieved products are available for synthesis")

    if len(product_ids) > 1 and not _comparison_covers(state, product_ids):
        result = compare_products(product_ids)
        if not result.get("ok"):
            raise RuntimeError(result["error"])
    for product_id in product_ids:
        if state["evidence_by_product"].get(product_id):
            continue
        result = get_product_evidence(product_id, question)
        if not result.get("ok"):
            raise RuntimeError(result["error"])
    if any(
        not state["evidence_by_product"].get(product_id) for product_id in product_ids
    ):
        raise RuntimeError(
            "No retrieved evidence is available for every selected product"
        )
    if not any(
        step["tool"] == "explain_retrieval"
        and step.get("outcome", "success") == "success"
        for step in state["trace"]
    ):
        search_event_ids = state.get("search_event_ids") or []
        if not search_event_ids:
            raise RuntimeError(
                "No retrieval event is available for ranking explanation"
            )
        result = explain_retrieval(str(search_event_ids[0]))
        if not result.get("ok"):
            raise RuntimeError(result["error"])
    finalize_retrieved_answer(question, product_ids=product_ids)


def finalize_retrieved_answer(
    question: str,
    *,
    product_ids: list[int] | None = None,
) -> None:
    """Create the validated answer if orchestration stopped after retrieval."""
    started = perf_counter()
    state = _state()
    if state["answer_of_record"] is not None:
        return
    selected_ids = (
        product_ids
        or [
            product_id
            for product_id in state["evidence_by_product"]
            if product_id in state["products"]
        ][: min(state["result_limit"], 4)]
    )
    products = [state["products"][product_id] for product_id in selected_ids]
    if not products:
        raise RuntimeError("No retrieved products are available for synthesis")
    selected_ids = [product.product_id for product in products]
    if len(selected_ids) > 1 and not _comparison_covers(state, selected_ids):
        raise RuntimeError(
            "Retrieved products were not compared before grounded synthesis"
        )
    evidence = _evidence_for_products(state, selected_ids)
    if not evidence:
        raise RuntimeError("No retrieved evidence is available for grounded synthesis")

    answer, citations, usage = synthesize_answer(question, products, evidence)
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
            "product_ids": selected_ids,
            "orchestration_fallback": True,
        },
        started,
        result_count=len(citations),
        detail=(
            "Validated cited synthesis after orchestration completed without "
            "calling its required final tool."
        ),
    )


def _evidence_for_products(
    state: dict[str, Any],
    product_ids: list[int],
) -> list[Any]:
    """Return evidence in product order with stable evidence-ID ordering."""
    return [
        state["evidence"][evidence_id]
        for product_id in product_ids
        for evidence_id in sorted(state["evidence_by_product"].get(product_id, []))
    ]


def _comparison_covers(state: dict[str, Any], product_ids: list[int]) -> bool:
    """True when one successful comparison contains every selected product."""
    selected = set(product_ids)
    return any(
        step["tool"] == "compare_products"
        and step.get("outcome", "success") == "success"
        and selected <= set((step.get("arguments") or {}).get("product_ids", []))
        for step in state["trace"]
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
        if state["search_event_ids"]:
            connection.execute(
                """
                UPDATE mosaic.search_event
                SET agent_turn_id = %s
                WHERE search_event_id = ANY (%s::uuid[])
                """,
                (state["agent_turn_id"], state["search_event_ids"]),
            )
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
                        "outcome": step.get("outcome", "success"),
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
                                    if record
                                    and step["tool"] == "synthesize_cited_answer"
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
