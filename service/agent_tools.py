"""Model-facing Strands tools over the canonical catalog API contracts."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from time import perf_counter
from typing import Any, Literal
from uuid import UUID, uuid4

from strands import tool

from service.catalog import get_product_evidence_records, get_product_summaries
from service.config import get_settings
from service.coverage import decline_note, decline_reason
from service.db import connect
from service.model_runtime import model_runtime_error
from service.models import (
    AgentConversationContext,
    ProductSummary,
    QueryCoverage,
    SearchFilters,
    SearchRequest,
)
from service.retrieval import get_retrieval_service, signals_from_receipt
from service.synthesis import synthesize_cited_answer as synthesize_answer
from service.telemetry import search_with_telemetry

logger = logging.getLogger(__name__)
SEARCH_SLOTS = ("primary", "follow_up")


def _min_length(field_name: str) -> int:
    """Read a `SearchRequest` field's `min_length` constraint without copying it.

    Args:
        field_name: A field name on `service.models.SearchRequest`.

    Returns:
        The field's `annotated_types.MinLen` constraint value.
    """
    for constraint in SearchRequest.model_fields[field_name].metadata:
        candidate = getattr(constraint, "min_length", None)
        if candidate is not None:
            return candidate
    raise ValueError(f"SearchRequest.{field_name} declares no min_length constraint")


#: Agent-surface bounds mirrored in `db/config/agent_tool_contracts.json`. Kept
#: as module constants rather than repeated literals, so the JSON schema and
#: the runtime check are two readings of one value instead of two copies that
#: can drift, per `docs/house-standards.md` rule 5.
COMPARE_PRODUCT_COUNT = (2, 5)
SYNTHESIS_PRODUCT_COUNT = (1, 6)
SEARCH_QUERY_MIN_LENGTH = _min_length("query")

_RUN: ContextVar[dict[str, Any] | None] = ContextVar(
    "catalog_agent_tool_run",
    default=None,
)
_TRACE_ORIGIN: ContextVar[Literal["model", "controller_fallback"]] = ContextVar(
    "catalog_agent_trace_origin",
    default="model",
)


class ConversationContextError(RuntimeError):
    """A follow-up failed server-side prior-answer authorization."""


def _uuid_list(values: Any, field: str) -> list[UUID]:
    """Parse server-persisted UUID lists and fail closed on malformed state."""
    if values is None:
        return []
    if not isinstance(values, list):
        raise ConversationContextError(
            f"Prior agent turn has an invalid {field} record"
        )
    try:
        return list(dict.fromkeys(UUID(str(value)) for value in values))
    except (TypeError, ValueError) as error:
        raise ConversationContextError(
            f"Prior agent turn has an invalid {field} record"
        ) from error


def _load_conversation_context(
    context: AgentConversationContext,
) -> tuple[UUID, list[ProductSummary], list[UUID]]:
    """Authorize a follow-up against the previous answer of record."""
    with connect() as connection:
        row = connection.execute(
            """
            SELECT turn.agent_session_id, turn.user_message,
                   turn.extracted_intent, synthesis.input_payload
            FROM mosaic.agent_turn AS turn
            JOIN LATERAL (
                SELECT input_payload
                FROM mosaic.agent_tool_event
                WHERE agent_turn_id = turn.agent_turn_id
                  AND tool_name = 'synthesize_cited_answer'
                  AND outcome = 'success'
                ORDER BY occurred_at DESC
                LIMIT 1
            ) AS synthesis ON true
            WHERE turn.agent_turn_id = %s
              AND turn.assistant_message IS NOT NULL
            """,
            (context.previous_agent_run_id,),
        ).fetchone()
        if row is None:
            raise ConversationContextError(
                "The previous Ask Mosaic answer is unavailable or was not grounded"
            )

        if context.previous_question != row["user_message"]:
            raise ConversationContextError(
                "The previous Ask Mosaic question does not match its run"
            )

        input_payload = row["input_payload"] or {}
        if not isinstance(input_payload, dict):
            raise ConversationContextError(
                "The previous Ask Mosaic answer has an invalid product scope"
            )
        persisted_ids = input_payload.get("product_ids")
        if not isinstance(persisted_ids, list) or not persisted_ids:
            raise ConversationContextError(
                "The previous Ask Mosaic answer has no product scope"
            )
        try:
            selected_ids = [int(value) for value in persisted_ids]
        except (TypeError, ValueError) as error:
            raise ConversationContextError(
                "The previous Ask Mosaic answer has an invalid product scope"
            ) from error
        supplied_products = [
            recommendation.model_dump() for recommendation in context.recommendations
        ]
        if [item["product_id"] for item in supplied_products] != selected_ids:
            raise ConversationContextError(
                "The follow-up products do not match the previous answer of record"
            )

        intent = row["extracted_intent"] or {}
        if not isinstance(intent, dict):
            raise ConversationContextError(
                "The previous Ask Mosaic answer has invalid persisted context"
            )
        persisted_products = intent.get("selected_products")
        if persisted_products is not None and (
            not isinstance(persisted_products, list)
            or supplied_products != persisted_products
        ):
            raise ConversationContextError(
                "The follow-up product identities do not match the previous answer"
            )

        context_event_ids = _uuid_list(
            [
                *(intent.get("search_event_ids") or []),
                *(intent.get("context_search_event_ids") or []),
            ],
            "search event",
        )
        if not context_event_ids:
            raise ConversationContextError(
                "The previous Ask Mosaic answer has no authorized ranking scope"
            )
        authorized_rows = connection.execute(
            """
            SELECT event.search_event_id
            FROM mosaic.search_event AS event
            JOIN mosaic.agent_turn AS source_turn
              ON source_turn.agent_turn_id = event.agent_turn_id
            WHERE source_turn.agent_session_id = %s
              AND event.search_event_id = ANY(%s::uuid[])
            """,
            (row["agent_session_id"], context_event_ids),
        ).fetchall()
        authorized_ids = {item["search_event_id"] for item in authorized_rows}
        if authorized_ids != set(context_event_ids):
            raise ConversationContextError(
                "The previous Ask Mosaic ranking scope is no longer valid"
            )
        receipt_rows = connection.execute(
            """
            SELECT receipt.product_id, receipt.result_rank,
                   receipt.fts_rank, receipt.trigram_rank,
                   receipt.semantic_rank, receipt.fused_rank,
                   receipt.rerank_rank, receipt.scores,
                   receipt.provenance
            FROM unnest(%s::uuid[]) WITH ORDINALITY
                 AS authorized(search_event_id, position)
            JOIN mosaic.search_result_event AS receipt
              USING (search_event_id)
            WHERE receipt.product_id = ANY(%s::bigint[])
            ORDER BY authorized.position, receipt.result_rank
            """,
            (context_event_ids, selected_ids),
        ).fetchall()
        receipts_by_product: dict[int, dict[str, Any]] = {}
        for receipt in receipt_rows:
            receipts_by_product.setdefault(
                receipt["product_id"],
                dict(receipt),
            )
        missing_receipts = [
            product_id
            for product_id in selected_ids
            if product_id not in receipts_by_product
        ]
        if missing_receipts:
            raise ConversationContextError(
                "The previous Ask Mosaic product scope has no ranking receipt"
            )

    products = get_product_summaries(selected_ids)
    try:
        products = [
            product.model_copy(
                update={
                    "signals": signals_from_receipt(
                        receipts_by_product[product.product_id]
                    )
                }
            )
            for product in products
        ]
    except (KeyError, TypeError, ValueError) as error:
        raise ConversationContextError(
            "The previous Ask Mosaic ranking receipt is invalid"
        ) from error
    if persisted_products is None:
        current_products = [
            {
                "product_id": product.product_id,
                "title": product.title,
                "model": product.model,
            }
            for product in products
        ]
        if supplied_products != current_products:
            raise ConversationContextError(
                "The follow-up product identities do not match the catalog"
            )
    return row["agent_session_id"], products, context_event_ids


def start_run(
    question: str,
    base_filters: SearchFilters,
    result_limit: int,
    context: AgentConversationContext | None = None,
) -> dict[str, Any]:
    # A question is one turn of one session. The schema models the session so a
    # follow-up can be tied to what came before it; a single-turn ask still
    # creates both rows rather than a special flat case.
    if context is None:
        agent_session_id = uuid4()
        context_products: list[ProductSummary] = []
        context_search_event_ids: list[UUID] = []
    else:
        (
            agent_session_id,
            context_products,
            context_search_event_ids,
        ) = _load_conversation_context(context)
    agent_turn_id = uuid4()
    state: dict[str, Any] = {
        "agent_session_id": agent_session_id,
        "agent_turn_id": agent_turn_id,
        # Public API compatibility: one request is one persisted agent turn.
        "agent_run_id": agent_turn_id,
        "question": question,
        "base_filters": base_filters,
        "result_limit": result_limit,
        "execution_path": (
            "focused_follow_up" if context is not None else "full_retrieval"
        ),
        "trace": [],
        "search_event_ids": [],
        "context_search_event_ids": context_search_event_ids,
        "context_product_ids": [product.product_id for product in context_products],
        "products": {product.product_id: product for product in context_products},
        "evidence": {},
        "evidence_by_product": {},
        "searches": [],
        # One coverage verdict per issued search, in issue order. The run-level
        # refusal is a property of the whole turn, not of any single search, so
        # the verdicts are kept rather than reduced as they arrive.
        "search_coverage": [],
        "answer_of_record": None,
    }
    with connect() as connection:
        if context is None:
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
            turn_number = 1
        else:
            locked = connection.execute(
                """
                SELECT agent_session_id
                FROM mosaic.agent_session
                WHERE agent_session_id = %s
                FOR UPDATE
                """,
                (agent_session_id,),
            ).fetchone()
            if locked is None:
                raise ConversationContextError(
                    "The previous Ask Mosaic session is unavailable"
                )
            turn_number = connection.execute(
                """
                SELECT COALESCE(max(turn_number), 0) + 1 AS turn_number
                FROM mosaic.agent_turn
                WHERE agent_session_id = %s
                """,
                (agent_session_id,),
            ).fetchone()["turn_number"]
        connection.execute(
            """
            INSERT INTO mosaic.agent_turn (
                agent_turn_id, agent_session_id, turn_number, user_message
            )
            VALUES (%s, %s, %s, %s)
            """,
            (agent_turn_id, agent_session_id, turn_number, question),
        )
        connection.commit()
    _RUN.set(state)
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
    origin: Literal["model", "controller_fallback"] | None = None,
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
            "origin": origin or _TRACE_ORIGIN.get(),
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
    limit: int = 2,
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
    state["execution_path"] = "full_retrieval"
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
        response = _search_with_telemetry(
            SearchRequest(
                query=query,
                filters=filters,
                # The agent receives the complete bounded rerank window so it can
                # inspect the pool, but it grants the model only the top slice.
                # `authorized_limit` is that grant: without it the receipt would
                # record 50 while `_RUN` registered 2, and the service boundary
                # would authorize 48 products the model never saw.
                limit=get_settings().rerank_candidate_limit,
                authorized_limit=requested_limit,
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
    state.setdefault("search_coverage", []).append(response.coverage)
    if not state["searches"] and state.get("context_product_ids"):
        # A request for alternatives or changed constraints starts a new
        # candidate pool. The prior answer remains conversational context, but
        # its products do not inherit eligibility into this retrieval.
        state["products"].clear()
        state["evidence"].clear()
        state["evidence_by_product"].clear()
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
        # `results`, not `products`: one canonical payload field name across
        # agent, MCP, and skill. The value is still the compact
        # `_product_for_model` projection the model reads.
        "results": [_product_for_model(product) for product in ranked_results],
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
        # Declared on this tool's payload_schema, so the model reads the same
        # verdict the audit record claims the tool returns. The per-term rows
        # stay out: the model needs the decision, not the vocabulary probe.
        "coverage": (
            {
                "confidence": response.coverage.confidence,
                "unmatched_terms": response.coverage.unmatched_terms,
                "note": response.coverage.note,
            }
            if response.coverage
            else None
        ),
    }


@tool
def get_product_evidence(product_id: int, evidence_query: str) -> dict[str, Any]:
    """Retrieve fresh question-ranked evidence for one authorized product.

    Args:
        product_id: A product ID returned by search_products or authorized by
            the previous grounded answer.
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
            "product_id is outside this agent turn's authorized product scope",
            "use a product from the current retrieval or previous grounded answer.",
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
    """Compare products in this turn's authorized product scope.

    Args:
        product_ids: Two to five product IDs from the current retrieval or
            previous grounded answer.

    Returns:
        A side-by-side comparison of constraints, attributes, source revisions,
        and ranking signals.
    """
    started = perf_counter()
    state = _state()
    unique_ids = list(dict.fromkeys(product_ids))
    if not COMPARE_PRODUCT_COUNT[0] <= len(unique_ids) <= COMPARE_PRODUCT_COUNT[1]:
        return _failure(
            "comparison requires two to five distinct products",
            "pass product IDs returned by search_products.",
        )
    unknown = [item for item in unique_ids if item not in state["products"]]
    if unknown:
        return _failure(
            f"products are outside this turn's authorized scope: {unknown}",
            "compare products from the current retrieval or previous grounded answer.",
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
    # Scoped to the current retrieval or a server-validated prior answer.
    # Replaying an arbitrary event would let one session read another
    # session's telemetry.
    authorized_event_ids = (
        state["search_event_ids"]
        if state["searches"]
        else [
            *state["search_event_ids"],
            *state.get("context_search_event_ids", []),
        ]
    )
    if parsed not in authorized_event_ids:
        return _failure(
            "search_event_id is outside this turn's authorized ranking scope",
            "use an event from the current retrieval or previous grounded answer.",
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
        "run": dict(event) if event else None,
        "candidates": [dict(row) for row in candidates],
    }


def coverage_refusal(state: dict[str, Any]) -> tuple[str, str] | None:
    """The answer and reason a run owes when it may not recommend.

    A turn declines only when it issued at least one search and every one of
    them came back `unanchored`. Three cases deliberately stay on the grounded
    path:

    - no search at all, which is a closed-world follow-up over an already
      authorized shortlist and has no coverage verdict of its own;
    - any search that came back `grounded`, because one anchored search is a
      product the catalog does carry;
    - `unavailable`, or no verdict at all, which is the documented fail-safe.
      An unseeded vocabulary makes every term look absent, and refusing on it
      would turn one skipped seed step into a total outage that presents as a
      working guardrail.

    Args:
        state: The active run state.

    Returns:
        The declining answer of record and the reason behind it, or `None` when
        the run may recommend.
    """
    verdicts: list[QueryCoverage | None] = state.get("search_coverage") or []
    if not verdicts:
        return None
    if any(item is None or item.confidence != "unanchored" for item in verdicts):
        return None
    unmatched = list(
        dict.fromkeys(term for item in verdicts for term in item.unmatched_terms)
    )
    if not unmatched:
        return None
    return decline_note(unmatched), decline_reason(unmatched)


def record_declined_answer(state: dict[str, Any]) -> bool:
    """Write the declining answer of record, if this run declines.

    The answer of record still exists; it just recommends nothing. Leaving it
    unset would raise out of `ProductDiscoveryAgent._response` as a 503, which
    is the fail-closed pipeline signal Lab 3 teaches and a different fact from
    a request the catalog cannot anchor.

    Args:
        state: The active run state.

    Returns:
        Whether the declining answer was written.
    """
    refusal = coverage_refusal(state)
    if refusal is None:
        return False
    answer, reason = refusal
    state["answer_of_record"] = {
        "answer": answer,
        "citations": [],
        "recommendations": [],
        "usage": {},
        "outcome": "declined",
        "decline_reason": reason,
    }
    return True


@tool
def synthesize_cited_answer(
    question: str,
    product_ids: list[int],
) -> dict[str, Any]:
    """Create the answer of record from authorized products and fresh evidence.

    Call this last. It invokes the configured citation model with only the
    selected product revisions, rejects citations outside that set, applies
    deterministic claim checks, and persists the answer and citation links.

    Args:
        question: The user's product question.
        product_ids: One to six product IDs from the current retrieval or
            previous grounded answer.

    Returns:
        The citation-bounded answer of record.
    """
    started = perf_counter()
    state = _state()
    unique_ids = list(dict.fromkeys(product_ids))
    if record_declined_answer(state):
        # Checked before the product bounds, because which products the model
        # chose cannot matter: every search this turn named something the
        # catalog does not carry, so no selection of them is grounded.
        record = state["answer_of_record"]
        _record(
            "synthesize_cited_answer",
            {"question": question, "product_ids": unique_ids},
            started,
            result_count=0,
            detail=(
                "Recommendation refused; every search this turn came back "
                f"unanchored ({record['decline_reason']})."
            ),
            outcome="denied",
        )
        return {"ok": True, "answer": record["answer"], "citations": []}
    if not SYNTHESIS_PRODUCT_COUNT[0] <= len(unique_ids) <= SYNTHESIS_PRODUCT_COUNT[1]:
        return _failure(
            "synthesis requires one to six distinct products",
            "select the strongest products returned by search_products.",
        )
    unknown = [item for item in unique_ids if item not in state["products"]]
    if unknown:
        return _failure(
            f"products are outside this turn's authorized scope: {unknown}",
            "synthesize from the current retrieval or previous grounded answer.",
        )
    products = [state["products"][item] for item in unique_ids]
    explanations = [
        step
        for step in state["trace"]
        if step["tool"] == "explain_retrieval"
        and step.get("outcome", "success") == "success"
    ]
    if state["searches"] and len(explanations) != 1:
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
            "newly retrieved products do not have exactly one ranking explanation",
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
    """Complete missing grounded steps and label them as controller-owned."""
    token = _TRACE_ORIGIN.set("controller_fallback")
    try:
        _complete_grounded_answer(question)
    finally:
        _TRACE_ORIGIN.reset(token)


def _complete_grounded_answer(question: str) -> None:
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
    if state["searches"] and not any(
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
    """Create the citation-bounded answer after model orchestration stops."""
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
        },
        started,
        result_count=len(citations),
        detail=(
            "Citation-bounded synthesis after model orchestration completed without "
            "calling its required final tool."
        ),
        origin="controller_fallback",
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


def _search_with_telemetry(request: SearchRequest):
    """Use the injected retrieval-service seam, then append telemetry."""
    return search_with_telemetry(
        request,
        search=get_retrieval_service().search,
    )


TOOL_FUNCTIONS = (
    search_products,
    get_product_evidence,
    compare_products,
    explain_retrieval,
    synthesize_cited_answer,
)


def _persisted_intent(
    state: dict[str, Any],
    record: dict[str, Any] | None,
    plan: list[dict[str, Any]],
    usage: dict[str, Any],
) -> dict[str, Any]:
    """Build the server-owned scope needed to authorize a later follow-up."""
    return {
        "plan": plan,
        "search_event_ids": [str(value) for value in state["search_event_ids"]],
        "context_search_event_ids": [
            str(value) for value in state.get("context_search_event_ids", [])
        ],
        "context_product_ids": state.get("context_product_ids", []),
        "execution_path": state.get("execution_path", "full_retrieval"),
        # Read by the Lab 3 completion proof and the telemetry contract. A run
        # with no answer of record has no outcome to report, which is a third
        # state and not a quiet "grounded".
        "outcome": record.get("outcome", "grounded") if record else None,
        "decline_reason": record.get("decline_reason") if record else None,
        "selected_products": (
            [
                {
                    "product_id": product.product_id,
                    "title": product.title,
                    "model": product.model,
                }
                for product in record["recommendations"]
            ]
            if record
            else []
        ),
        "usage": usage,
        "telemetry": state.get("telemetry", {}),
    }


def persist_completed_run(
    state: dict[str, Any],
    *,
    usage: dict[str, Any],
    error_type: str | None = None,
) -> None:
    from datetime import UTC, datetime

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
    status = "completed" if record is not None else "failed"
    duration_ms = round(
        (perf_counter() - state.get("_started_monotonic", perf_counter())) * 1_000
    )
    state["telemetry"] = {
        "status": status,
        "completed_at": datetime.now(UTC).isoformat(),
        "duration_ms": duration_ms,
        "trace_id": state.get("trace_id"),
        "span_id": state.get("span_id"),
    }
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
                    _persisted_intent(
                        state,
                        record,
                        plan,
                        persisted_usage,
                    ),
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
                    outcome, execution_origin, input_payload, output_payload,
                    duration_ms
                )
                VALUES (
                    %(agent_turn_id)s, %(search_event_id)s, %(tool_name)s, '1.0',
                    %(outcome)s, %(execution_origin)s, %(input_payload)s::jsonb,
                    %(output_payload)s::jsonb, %(duration_ms)s
                )
                """,
                [
                    {
                        "agent_turn_id": state["agent_turn_id"],
                        "search_event_id": step.get("search_event_id"),
                        "tool_name": step["tool"],
                        "outcome": step.get("outcome", "success"),
                        "execution_origin": step.get("origin", "model"),
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
