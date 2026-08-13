"""FastAPI surface for catalog browsing, retrieval labs, and agent tools."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
from typing import Any
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from service.agent import get_product_discovery_agent
from service.catalog import (
    catalog_summary,
    get_evidence_record,
    get_product,
    get_product_evidence_records,
    list_products,
)
from service.config import get_settings
from service.db import connect, readiness
from service.fusion_comparison import SubstrateError, get_fusion_comparison_service
from service.model_runtime import bedrock_credentials_status, model_runtime_error
from service.models import (
    AgentRequest,
    AgentResponse,
    CatalogPage,
    FusionComparisonResponse,
    EvidenceRecord,
    ProductDetail,
    ProductEvidenceRequest,
    ProductEvidenceResponse,
    RetrievalRunResponse,
    SearchFilters,
    SearchRequest,
    SearchResponse,
)
from service.retrieval import get_retrieval_service

ROOT = Path(__file__).resolve().parents[1]
settings = get_settings()

app = FastAPI(
    title="Catalog Hybrid Retrieval API",
    description=(
        "Inspectable lexical, fuzzy, semantic, filtered, fused, reranked, "
        "and agentic product discovery on Aurora PostgreSQL."
    ),
    version="0.2.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


def _model_error(error: Exception) -> HTTPException:
    classified = model_runtime_error(error)
    return HTTPException(
        503,
        str(classified or f"Model service unavailable: {type(error).__name__}"),
    )


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


def _answer_chunks(answer: str) -> list[str]:
    """Keep streamed delivery readable rather than emitting one character at a time."""
    words = re.findall(r"\S+\s*", answer)
    return [
        "".join(words[index:index + 7])
        for index in range(0, len(words), 7)
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
    """Return source-addressable evidence ranked for the supplied question."""
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
            yield _sse(
                "stage",
                {
                    "id": "understand",
                    "title": "Interpret request",
                    "detail": "Separating preferences from hard catalog constraints.",
                },
            )
            current_stage = "understand"
            async for event in get_product_discovery_agent().stream(request):
                tool = event.get("current_tool_use")
                tool_name = tool.get("name") if isinstance(tool, dict) else None
                if tool_name == "search_products":
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
                        "Compare ranks",
                        "Retaining candidate provenance and eligibility checks.",
                    )
                elif tool_name == "synthesize_cited_answer":
                    stage = (
                        "answer",
                        "Compose cited answer",
                        "Preparing the validated answer of record.",
                    )
                else:
                    stage = None
                if stage and stage[0] != current_stage:
                    current_stage = stage[0]
                    yield _sse(
                        "stage",
                        {"id": stage[0], "title": stage[1], "detail": stage[2]},
                    )

                result = event.get("agent_response")
                if not isinstance(result, AgentResponse):
                    continue
                payload = result.model_dump(mode="json")
                yield _sse(
                    "stage",
                    {
                        "id": "answer",
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
                    await asyncio.sleep(0.012)
                yield _sse("complete", {"response": payload})
        except Exception as error:
            classified = model_runtime_error(error)
            yield _sse(
                "error",
                {
                    "detail": str(
                        classified
                        or f"Agent response failed: {type(error).__name__}"
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


@app.get(
    "/api/retrieval/events/{search_event_id}",
    response_model=RetrievalRunResponse,
)
def retrieval_event(search_event_id: UUID) -> RetrievalRunResponse:
    """Replay the persisted provenance for one search.

    This is the endpoint behind the retrieval lab: the receipts come out of
    `mosaic.search_result_event` rather than being recomputed, so what the UI
    shows is what was actually fused.
    """
    with connect() as connection:
        event = connection.execute(
            """
            SELECT search_event_id, occurred_at, session_id, query_text,
                   normalized_query, filters, retrieval_profile,
                   candidate_counts, total_latency_ms, diagnostics
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


@app.get("/api/tools")
def tool_contracts() -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": "search_products",
                "description": (
                    "Run filtered lexical, fuzzy, semantic, unweighted RRF, "
                    "and reranked product retrieval."
                ),
                "input_schema": SearchRequest.model_json_schema(),
                "read_only": True,
            },
            {
                "name": "get_product_evidence",
                "description": (
                    "Retrieve question-ranked specification and review evidence "
                    "with stable source IDs for one retrieved product."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "integer"},
                        "evidence_query": {"type": "string", "minLength": 1},
                    },
                    "required": ["product_id", "evidence_query"],
                    "additionalProperties": False,
                },
                "read_only": True,
            },
            {
                "name": "inspect_retrieval_run",
                "description": (
                    "Replay candidate-level ranks, raw scores, RRF "
                    "contributions, reranker scores, and final order."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"run_id": {"type": "string", "format": "uuid"}},
                    "required": ["run_id"],
                    "additionalProperties": False,
                },
                "read_only": True,
            },
        ]
    }
