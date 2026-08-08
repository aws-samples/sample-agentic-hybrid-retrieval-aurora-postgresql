"""FastAPI surface for catalog browsing, retrieval labs, and agent tools."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from service.agent import get_product_discovery_agent
from service.catalog import catalog_summary, get_product, list_products
from service.config import get_settings
from service.db import connect, readiness
from service.models import (
    AgentRequest,
    AgentResponse,
    CatalogPage,
    ProductDetail,
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
    if isinstance(error, ClientError):
        code = error.response.get("Error", {}).get("Code", "BedrockError")
        return HTTPException(503, f"Amazon Bedrock request failed: {code}")
    return HTTPException(503, f"Model service unavailable: {type(error).__name__}")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "catalog-hybrid-retrieval",
        "models": {
            "embedding": settings.embedding_model_id,
            "rerank": settings.rerank_model_id,
            "agent": settings.chat_model_id,
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
    return {
        "status": "ready" if database["schema_ready"] and model_space_ready else "blocked",
        "database": database,
        "configured_models": {
            "embedding": configured_model,
            "rerank": settings.rerank_model_id,
            "agent": settings.chat_model_id,
        },
        "model_space_ready": model_space_ready,
    }


@app.get("/api/catalog/summary")
def get_catalog_summary() -> dict[str, Any]:
    return catalog_summary()


@app.get("/api/catalog/products", response_model=CatalogPage)
def get_catalog_products(
    domain: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    brand: str | None = None,
    availability: str | None = None,
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    min_rating: float | None = Query(default=None, ge=0, le=5),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=24, ge=1, le=60),
    sort: str = "featured",
) -> CatalogPage:
    try:
        filters = SearchFilters(
            domain=domain,
            category=category,
            subcategory=subcategory,
            brand=brand,
            availability=availability,
            min_price=min_price,
            max_price=max_price,
            min_rating=min_rating,
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


@app.post("/api/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    try:
        return get_retrieval_service().search(request)
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


@app.get("/api/retrieval/runs/{run_id}", response_model=RetrievalRunResponse)
def retrieval_run(run_id: UUID) -> RetrievalRunResponse:
    with connect() as connection:
        run = connection.execute(
            "SELECT * FROM catalog.retrieval_run WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        if run is None:
            raise HTTPException(404, "Retrieval run not found")
        candidates = connection.execute(
            """
            SELECT *
            FROM catalog.retrieval_candidate
            WHERE run_id = %s
            ORDER BY final_rank NULLS LAST, pre_rerank_rank
            """,
            (run_id,),
        ).fetchall()
    return RetrievalRunResponse(
        run=dict(run),
        candidates=[dict(row) for row in candidates],
    )


@app.get("/api/tools")
def tool_contracts() -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": "search_products",
                "description": (
                    "Run filtered lexical, fuzzy, semantic, weighted-RRF, "
                    "and reranked product retrieval."
                ),
                "input_schema": SearchRequest.model_json_schema(),
                "read_only": True,
            },
            {
                "name": "get_product_evidence",
                "description": (
                    "Read one product, its structured specifications, media, "
                    "source revision, and review evidence."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"product_id": {"type": "integer"}},
                    "required": ["product_id"],
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
