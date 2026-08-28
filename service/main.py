"""FastAPI surface for catalog browsing, retrieval labs, and agent tools."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg_pool import PoolTimeout

from scripts.seed_exact_neighbors import StaleGroundTruth
from scripts.tool_contracts import contracts_for_surface
from service import hnsw
from service.agent import get_product_discovery_agent
from service.catalog import (
    catalog_suggestions,
    catalog_summary,
    get_evidence_record,
    get_product,
    get_product_evidence_records,
    get_product_summaries,
    list_products,
    review_highlights,
)
from service.config import get_settings
from service.db import close_pool, connect, get_pool, readiness
from service.fusion_comparison import SubstrateError, get_fusion_comparison_service
from service.model_runtime import (
    bedrock_credentials_status,
    safe_model_runtime_message,
)
from service.models import (
    AgentRequest,
    AgentResponse,
    CatalogPage,
    CatalogSuggestionsResponse,
    EvidenceRecord,
    FusionComparisonResponse,
    HnswProbeRequest,
    ProductComparisonRequest,
    ProductComparisonResponse,
    ProductDetail,
    ProductEvidenceRequest,
    ProductEvidenceResponse,
    RetrievalPlanResponse,
    RetrievalRunResponse,
    RetrievalScorecardResponse,
    ReviewHighlightsResponse,
    SearchFilters,
    SearchRequest,
    SearchResponse,
)
from service.retrieval import get_retrieval_service, signals_from_receipt
from service.retrieval_scope import (
    SCOPE_DENIED_DETAIL,
    ScopeViolation,
    assert_products_in_retrieval_scope,
)
from service.scorecard import retrieval_scorecard

ROOT = Path(__file__).resolve().parents[1]
settings = get_settings()


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Own the connection pool for the life of the process.

    Opening it here means the first participant request does not pay for pool
    construction, and closing it lets uvicorn shut down without leaving Aurora
    sessions to time out. A missing `DATABASE_URL` still has to surface per
    request rather than at boot, because `/api/health` answers without a database
    and the readiness endpoint exists to report exactly that failure.
    """
    try:
        get_pool()
    except RuntimeError:
        pass
    try:
        yield
    finally:
        close_pool()


app = FastAPI(
    title="Catalog Hybrid Retrieval API",
    description=(
        "Inspectable lexical, fuzzy, semantic, filtered, fused, reranked, "
        "and agentic product discovery on Aurora PostgreSQL."
    ),
    version="0.2.0",
    lifespan=_lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.exception_handler(PoolTimeout)
async def _pool_saturated(_: Request, __: PoolTimeout) -> JSONResponse:
    """Say the pool is busy rather than returning a bare 500.

    `PoolTimeout` subclasses `psycopg.OperationalError`, not `RuntimeError`, so the
    `except RuntimeError` in each route does not catch it and Starlette answers
    "Internal Server Error" with no explanation. Under a full workshop room that is
    the most likely failure, and it is the one a participant can act on.
    """
    settings = get_settings()
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "Every database connection is busy. Retry in a moment. If this "
                f"persists, raise DB_POOL_MAX_SIZE (currently "
                f"{settings.db_pool_max_size}) or DB_POOL_TIMEOUT_SECONDS "
                f"(currently {settings.db_pool_timeout:g}s)."
            )
        },
    )


def _model_error(error: Exception) -> HTTPException:
    return HTTPException(
        503,
        safe_model_runtime_message(
            error,
            fallback="Model service unavailable. Retry after checking the runtime.",
        ),
    )


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


#: Words per `answer_delta`, and the pause between them.
#:
#: Delivery only. The answer is complete and citation-checked before the first
#: chunk leaves, because it cannot be shown until it has been, so this is the pace
#: it is read out at rather than the pace it was produced at. Seven words every
#: 12ms replayed a 250-word recommendation in 0.43 seconds, which arrived as a
#: single repaint after the wait for synthesis: three words every 40ms puts the
#: same answer on screen over about three seconds, which is a delivery a reader can
#: follow. Both numbers are presentation; neither touches retrieval.
_ANSWER_CHUNK_WORDS = 3
_ANSWER_CHUNK_DELAY_SECONDS = 0.04


def _answer_chunks(answer: str) -> list[str]:
    """Keep streamed delivery readable rather than emitting one character at a time."""
    words = re.findall(r"\S+\s*", answer)
    return [
        "".join(words[index : index + _ANSWER_CHUNK_WORDS])
        for index in range(0, len(words), _ANSWER_CHUNK_WORDS)
    ]


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "catalog-hybrid-retrieval",
        "models": {
            "embedding": settings.embedding_model_id,
            "rerank": settings.rerank_model_id,
            "agent": settings.agent_model_id,
            "synthesis": settings.synthesis_model_id,
        },
    }


@app.get("/api/readiness")
def get_readiness() -> dict[str, Any]:
    try:
        database = readiness()
    except Exception as error:
        raise HTTPException(
            503,
            f"Database is not ready: {type(error).__name__}",
        ) from error
    configured_model = settings.embedding_model_id
    stored_models = database.get("embedding_model_ids") or []
    model_space_ready = not stored_models or stored_models == [configured_model]
    database_ready = (
        bool(database["schema_ready"])
        and database["product_count"] == 500000
        and database["embedded_product_count"] == 500000
        and database["premium_product_count"] == 120
        and database["evidence_product_count"] == 500000
        and not database["missing_retrieval_indexes"]
        and not database["missing_retrieval_functions"]
    )
    bedrock_credentials = bedrock_credentials_status(settings.aws_region)
    return {
        "status": (
            "ready"
            if database_ready and model_space_ready and bedrock_credentials["ready"]
            else "blocked"
        ),
        "database": database,
        "configured_models": {
            "embedding": configured_model,
            "rerank": settings.rerank_model_id,
            "agent": settings.agent_model_id,
            "synthesis": settings.synthesis_model_id,
        },
        "database_ready": database_ready,
        "model_space_ready": model_space_ready,
        "bedrock_credentials": bedrock_credentials,
    }


@app.get("/api/catalog/summary")
def get_catalog_summary() -> dict[str, Any]:
    return catalog_summary()


@app.get("/api/catalog/reviews/highlights", response_model=ReviewHighlightsResponse)
def get_review_highlights() -> ReviewHighlightsResponse:
    return review_highlights()


@app.get("/api/catalog/suggestions", response_model=CatalogSuggestionsResponse)
def get_catalog_suggestions(
    q: str = Query(min_length=2, max_length=120),
) -> CatalogSuggestionsResponse:
    normalized = " ".join(q.split())
    if len(normalized) < 2:
        raise HTTPException(
            422,
            "Catalog suggestions require at least two non-space characters.",
        )
    return catalog_suggestions(normalized)


@app.get("/api/catalog/products", response_model=CatalogPage)
def get_catalog_products(
    domain: str | None = None,
    category_key: str | None = None,
    brand: str | None = None,
    availability: str | None = None,
    in_stock_only: bool = False,
    min_price_cents: int | None = Query(default=None, ge=0),
    max_price_cents: int | None = Query(default=None, ge=0),
    min_rating: float | None = Query(default=None, ge=0, le=5),
    include_refurbished: bool = True,
    include_sponsored: bool = True,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=12, ge=1, le=60),
    sort: str = "featured",
) -> CatalogPage:
    try:
        filters = SearchFilters(
            domain=domain,
            category_key=category_key,
            brand=brand,
            availability=availability,
            in_stock_only=in_stock_only,
            min_price_cents=min_price_cents,
            max_price_cents=max_price_cents,
            min_rating=min_rating,
            include_refurbished=include_refurbished,
            include_sponsored=include_sponsored,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return list_products(
        filters,
        offset=offset,
        limit=limit,
        sort=sort,
    )


@app.get("/api/products/{product_id}", response_model=ProductDetail)
def get_product_detail(product_id: int) -> ProductDetail:
    return get_product(product_id)


@app.get("/api/evidence/{evidence_id}", response_model=EvidenceRecord)
def get_evidence(evidence_id: int) -> EvidenceRecord:
    """Resolve an agent citation to the evidence row that supports it."""
    try:
        return get_evidence_record(evidence_id)
    except KeyError as error:
        raise HTTPException(404, str(error)) from error


@app.post(
    "/api/products/{product_id}/evidence",
    response_model=ProductEvidenceResponse,
)
def get_question_ranked_product_evidence(
    product_id: int,
    request: ProductEvidenceRequest,
) -> ProductEvidenceResponse:
    """Return evidence for one product the supplied retrieval actually granted.

    The scope check runs before the embedding call, so an unauthorized request
    costs no model invocation. A refusal is a 404 carrying only the generic
    detail: the rich message stays server-side, because reporting which products
    fell outside the window would let a refusal enumerate the candidate pool.
    """
    try:
        assert_products_in_retrieval_scope(request.retrieval_scope_id, [product_id])
    except ScopeViolation as error:
        raise HTTPException(404, SCOPE_DENIED_DETAIL) from error
    try:
        query_embedding = get_retrieval_service().embed_query(request.evidence_query)
        evidence = get_product_evidence_records(
            product_id,
            request.evidence_query,
            query_embedding,
            limit=request.limit,
        )
        return ProductEvidenceResponse(product_id=product_id, evidence=evidence)
    except (ClientError, BotoCoreError) as error:
        raise _model_error(error) from error
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error


@app.post("/api/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    try:
        return get_retrieval_service().search(request)
    except (ClientError, BotoCoreError) as error:
        raise _model_error(error) from error
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error


@app.post("/api/retrieval/fusion-comparison", response_model=FusionComparisonResponse)
def fusion_comparison(request: SearchRequest) -> FusionComparisonResponse:
    """Fuse one candidate pool with unweighted and weighted RRF.

    A comparison, not a behavior change: `POST /api/search` is unaffected and
    still serves unweighted fusion. The substrate assertion runs on every call —
    identical candidate sets in, different order out — and a violation is a 500
    rather than a rendered comparison of two different pools.
    """
    try:
        return get_fusion_comparison_service().compare(
            request.query, request.filters, top_k=request.limit
        )
    except SubstrateError as error:
        # 500, not 400: the caller did nothing wrong. The two functions have
        # drifted apart, which is a defect in this deployment.
        raise HTTPException(500, str(error)) from error
    except (ClientError, BotoCoreError) as error:
        raise _model_error(error) from error
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error


@app.post("/api/agent/answer", response_model=AgentResponse)
def agent_answer(request: AgentRequest) -> AgentResponse:
    try:
        return get_product_discovery_agent().answer(request)
    except (ClientError, BotoCoreError) as error:
        raise _model_error(error) from error
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error


@app.post("/api/agent/answer/stream")
async def stream_agent_answer(request: AgentRequest) -> StreamingResponse:
    """Stream safe retrieval progress and a paced cited-answer delivery.

    The transport reports application-owned retrieval milestones, not private
    model reasoning. Agent execution remains bounded by the same typed,
    read-only tool contract as the completed-response endpoint.
    """

    async def events():
        try:
            execution_path = (
                "focused_follow_up" if request.context is not None else "full_retrieval"
            )
            yield _sse(
                "stage",
                {
                    "id": "understand",
                    "path": execution_path,
                    "title": (
                        "Resolve follow-up"
                        if execution_path == "focused_follow_up"
                        else "Interpret request"
                    ),
                    "detail": (
                        "Resolving references against the prior grounded shortlist."
                        if execution_path == "focused_follow_up"
                        else "Separating preferences from hard catalog constraints."
                    ),
                },
            )
            current_stage = "understand"
            async for event in get_product_discovery_agent().stream(request):
                # Retrieval that has already happened, forwarded as soon as it
                # lands. Without this the panel holds four collapsed stages for
                # the length of the run and reveals everything at the end.
                partial = event.get("agent_partial")
                if partial is not None:
                    yield _sse("partial", {"partial": partial.model_dump(mode="json")})
                    continue

                tool = event.get("current_tool_use")
                tool_name = tool.get("name") if isinstance(tool, dict) else None
                if tool_name == "search_products":
                    execution_path = "full_retrieval"
                    stage = (
                        "retrieve",
                        "Retrieve evidence",
                        "Gathering bounded catalog evidence through read-only tools.",
                    )
                elif tool_name in {
                    "get_product_evidence",
                    "compare_products",
                    "explain_retrieval",
                }:
                    stage = (
                        "rank",
                        (
                            "Inspect prior shortlist"
                            if execution_path == "focused_follow_up"
                            else "Compare ranks"
                        ),
                        (
                            "Reading only the records needed for this follow-up."
                            if execution_path == "focused_follow_up"
                            else "Retaining candidate provenance and eligibility checks."
                        ),
                    )
                elif tool_name == "synthesize_cited_answer":
                    stage = (
                        "answer",
                        "Compose cited answer",
                        "Preparing the citation-bounded answer of record.",
                    )
                else:
                    stage = None
                if stage and stage[0] != current_stage:
                    current_stage = stage[0]
                    yield _sse(
                        "stage",
                        {
                            "id": stage[0],
                            "path": execution_path,
                            "title": stage[1],
                            "detail": stage[2],
                        },
                    )

                result = event.get("agent_response")
                if not isinstance(result, AgentResponse):
                    continue
                payload = result.model_dump(mode="json")
                yield _sse(
                    "stage",
                    {
                        "id": "answer",
                        "path": execution_path,
                        "title": "Compose cited answer",
                        "detail": "Delivering only claims grounded in returned catalog sources.",
                    },
                )
                yield _sse(
                    "answer_start",
                    {"response": {**payload, "answer": ""}},
                )
                for delta in _answer_chunks(result.answer):
                    yield _sse("answer_delta", {"delta": delta})
                    await asyncio.sleep(_ANSWER_CHUNK_DELAY_SECONDS)
                yield _sse("complete", {"response": payload})
        # This is the terminal SSE boundary for model and plugin failures. It
        # must convert every failure into an allowlisted participant message.
        except Exception as error:  # noqa: BLE001
            yield _sse(
                "error",
                {
                    "detail": safe_model_runtime_message(
                        error,
                        fallback=(
                            "Agent response failed. Retry after checking the "
                            "runtime and retrieval service."
                        ),
                    )
                },
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/retrieval/examples")
def retrieval_examples() -> dict[str, Any]:
    rows = [
        json.loads(line)
        for line in (ROOT / "data" / "evals" / "demo_queries.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        unique.setdefault(row["query"], row)
    return {"examples": list(unique.values())}


@app.get("/api/benchmarks/projection")
def benchmark_projection() -> dict[str, Any]:
    return json.loads(
        (ROOT / "data" / "benchmarks" / "scale_projection.json").read_text(
            encoding="utf-8"
        )
    )


@app.get("/api/scorecard", response_model=RetrievalScorecardResponse)
def get_retrieval_scorecard() -> RetrievalScorecardResponse:
    """The Prove step: the committed canonical evaluation artifact, read-only.

    No DDL and no `eval_run` table -- ruling R7. This reads
    `data/evals/canonical_scorecard.json` plus the query set, the assertion
    vocabulary, and the tool-contract registry, and computes whether the
    artifact's measured revision matches what is currently running.
    """
    try:
        return retrieval_scorecard()
    except FileNotFoundError as error:
        raise HTTPException(503, str(error)) from error


@app.get(
    "/api/retrieval/events/{search_event_id}",
    response_model=RetrievalRunResponse,
)
def retrieval_event(search_event_id: UUID) -> RetrievalRunResponse:
    """Replay the persisted provenance for one search.

    This is the endpoint behind the retrieval lab: the receipts come out of
    `mosaic.search_result_event` rather than being recomputed, so what the UI
    shows is what was actually fused.

    Deliberately unscoped, unlike the agent's `explain_retrieval` tool, which
    refuses events outside its turn. This route is a lab inspection surface: a
    participant pastes an event ID and reads what the server actually fused.

    That is a real asymmetry, not an oversight. The row carries `session_id` and
    the raw `query_text` of whoever ran the search, so on a shared deployment
    this would need owner scoping. It is acceptable here only because the
    workshop is single-attendee and disposable, and because a v4 UUID is not
    enumerable. `search_event_id` is a retrieval capability handle, never an
    identity or tenancy boundary.
    """
    with connect() as connection:
        event = connection.execute(
            """
            SELECT search_event_id, occurred_at, session_id, query_text,
                   normalized_query, filters, retrieval_profile, source_revision,
                   source_worktree_dirty, dataset_manifest_sha256,
                   embedding_model_id, rerank_model_id, retrieval_strategy,
                   database_instance_id, database_version,
                   vector_extension_version, aurora_instance_class,
                   hnsw_settings, candidate_counts, total_latency_ms,
                   plan_json, diagnostics
            FROM mosaic.search_event
            WHERE search_event_id = %s
            """,
            (search_event_id,),
        ).fetchone()
        if event is None:
            raise HTTPException(404, "Search event not found")
        candidates = connection.execute(
            """
            SELECT product_id, result_rank, fts_rank, trigram_rank,
                   semantic_rank, fused_rank, rerank_rank, scores, provenance
            FROM mosaic.search_result_event
            WHERE search_event_id = %s
            ORDER BY result_rank
            """,
            (search_event_id,),
        ).fetchall()
    return RetrievalRunResponse(
        run=dict(event),
        candidates=[dict(row) for row in candidates],
    )


@app.post(
    "/api/retrieval/events/{search_event_id}/compare",
    response_model=ProductComparisonResponse,
)
def compare_scoped_products(
    search_event_id: UUID,
    request: ProductComparisonRequest,
) -> ProductComparisonResponse:
    """Compare products one retrieval granted, without retrieving anything.

    A deterministic projection: it reads the persisted receipt for its ranking
    signals and hydrates the catalog rows. It issues no fusion, no rerank, and no
    candidate generation, so it cannot widen the set it was given.
    """
    unique_ids = list(dict.fromkeys(request.product_ids))
    if not 2 <= len(unique_ids) <= 5:
        raise HTTPException(
            422,
            f"compare requires two to five distinct products, found "
            f"{len(unique_ids)}; fix: pass distinct product IDs from this "
            "retrieval's granted results.",
        )
    try:
        assert_products_in_retrieval_scope(search_event_id, unique_ids)
    except ScopeViolation as error:
        raise HTTPException(404, SCOPE_DENIED_DETAIL) from error

    with connect() as connection:
        receipts = connection.execute(
            """
            SELECT product_id, result_rank, fts_rank, trigram_rank,
                   semantic_rank, fused_rank, rerank_rank, scores, provenance
            FROM mosaic.search_result_event
            WHERE search_event_id = %s
              AND product_id = ANY(%s::bigint[])
            """,
            (search_event_id, unique_ids),
        ).fetchall()
    by_product = {row["product_id"]: dict(row) for row in receipts}
    products = [
        product.model_copy(
            update={"signals": signals_from_receipt(by_product[product.product_id])}
        )
        for product in get_product_summaries(unique_ids)
    ]
    return ProductComparisonResponse(
        retrieval_scope_id=search_event_id,
        products=products,
    )


@app.post(
    "/api/retrieval/events/{search_event_id}/plan",
    response_model=RetrievalPlanResponse,
)
def capture_retrieval_plan(search_event_id: UUID) -> RetrievalPlanResponse:
    """Capture and persist EXPLAIN ANALYZE for the event's production SQL path."""
    try:
        return get_retrieval_service().capture_plan(search_event_id)
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    except (ClientError, BotoCoreError) as error:
        raise _model_error(error) from error


@app.get("/api/tools")
def tool_contracts(
    surface: Literal["agent", "mcp", "skill"] = Query(default="agent"),
) -> dict[str, Any]:
    """Expose one explicitly scoped view of the canonical tool contracts."""
    return {"surface": surface, "tools": contracts_for_surface(surface)}


@app.get("/api/hnsw/substrate")
def hnsw_substrate_route() -> dict[str, Any]:
    """Live HNSW index anatomy and storage split from the connected cluster."""
    try:
        return hnsw.substrate()
    except Exception as error:
        raise HTTPException(
            503, f"HNSW substrate unavailable: {type(error).__name__}"
        ) from error


@app.get("/api/hnsw/measured")
def hnsw_measured_route() -> dict[str, Any]:
    """The committed measured benchmark artifact, with its provenance."""
    try:
        return hnsw.measured()
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error


@app.get("/api/hnsw/anchors")
def hnsw_anchors_route() -> dict[str, Any]:
    """The query anchors the instrument offers: the imaged retrieval anchors."""
    try:
        return {"anchors": hnsw.anchors()}
    except Exception as error:
        raise HTTPException(
            503, f"HNSW anchors unavailable: {type(error).__name__}"
        ) from error


@app.get("/api/hnsw/neighborhood/{anchor_product_id}")
def hnsw_neighborhood_route(
    anchor_product_id: int,
    preset: str = Query(default="none"),
    k: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    """Precomputed exact neighbours for one anchor, with their real distances."""
    try:
        return hnsw.neighborhood(anchor_product_id, preset=preset, k=k)
    except KeyError as error:
        raise HTTPException(404, str(error.args[0])) from error
    except StaleGroundTruth as error:
        raise HTTPException(503, str(error)) from error


@app.post("/api/hnsw/probe")
def hnsw_probe_route(request: HnswProbeRequest) -> dict[str, Any]:
    """Run one real ANN query and report what the server actually did.

    Recall is computed against precomputed ground truth, never by re-running the
    exact scan, so this endpoint's cost ceiling is a filtered HNSW scan rather than
    a sequential scan over 3,870 MB of TOASTed vectors.
    """
    try:
        return hnsw.probe(request)
    except KeyError as error:
        raise HTTPException(404, str(error.args[0])) from error
    except StaleGroundTruth as error:
        raise HTTPException(503, str(error)) from error
