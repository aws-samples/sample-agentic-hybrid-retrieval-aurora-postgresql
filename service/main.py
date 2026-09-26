"""FastAPI surface for catalog browsing, retrieval labs, and agent tools."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import threading
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from psycopg import OperationalError
from psycopg_pool import PoolTimeout

from scripts.seed_exact_neighbors import StaleGroundTruth
from scripts.tool_contracts import contracts_for_surface
from service import hnsw
from service.access_control import (
    acquire_model_admission_slot,
    assert_bootable,
    release_model_admission_slot,
    require_model_admission,
    verify_origin_access,
)
from service.agent import (
    AgentTurnDeadlineExceeded,
    GroundingContractError,
    get_product_discovery_agent,
)
from service.agent_tools import ConversationContextError
from service.builder_package import build_package
from service.catalog import (
    catalog_suggestions,
    catalog_summary,
    count_products,
    get_evidence_record,
    get_product,
    get_product_evidence_records,
    get_product_summaries,
    list_products,
    review_highlights,
    similar_products,
)
from service.config import get_settings
from service.db import close_pool, connect, get_pool, readiness
from service.fusion_comparison import (
    LabStateError,
    SubstrateError,
    get_fusion_comparison_service,
)
from service.hnsw import RepresentationUnavailable
from service.lab_proof import UnknownLab, completion_proof, lab_states
from service.model_runtime import (
    bedrock_credentials_status,
    safe_model_runtime_message,
)
from service.models import (
    AgentRequest,
    AgentResponse,
    CatalogFilters,
    CatalogPage,
    CatalogSuggestionsResponse,
    CompletionProofRequest,
    CompletionProofResponse,
    EvidenceRecord,
    FusionComparisonResponse,
    HnswProbeRequest,
    LabStateResponse,
    ProductComparisonRequest,
    ProductComparisonResponse,
    ProductDetail,
    ProductEvidenceRequest,
    ProductEvidenceResponse,
    ProductSummary,
    RetrievalPlanResponse,
    RetrievalRunResponse,
    RetrievalScorecardResponse,
    ReviewHighlightsResponse,
    SearchRequest,
    SearchResponse,
)
from service.retrieval import get_retrieval_service, signals_from_receipt
from service.retrieval_replay import (
    UnknownSearchEvent,
    load_candidate_receipts,
    replay_search_response,
)
from service.retrieval_scope import (
    SCOPE_DENIED_DETAIL,
    ScopeViolation,
    assert_products_in_retrieval_scope,
)
from service.scorecard import retrieval_scorecard
from service.session_memory import prepare_request
from service.session_memory import router as session_memory_router
from service.staged_catalog import router as staged_catalog_router
from service.telemetry import search_with_telemetry
from service.telemetry_contract import (
    AgentTelemetryResponse,
    build_agent_telemetry_contract,
    load_agent_turn_rows,
)

ROOT = Path(__file__).resolve().parents[1]
settings = get_settings()
logger = logging.getLogger(__name__)
_GROUNDING_ERROR_DETAIL = (
    "Mosaic could not attach the supporting sources needed for this answer. "
    "In Lab 3, repair the marked evidence-registration block and restart the "
    "lab API, then ask again. Outside the lab, inspect the source checks."
)
_CONVERSATION_ERROR_DETAIL = "Mosaic could not reopen the previous answer. Start a new conversation and try again."


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Own the connection pool for the life of the process.

    Opening it here means the first participant request does not pay for pool
    construction, and closing it lets uvicorn shut down without leaving Aurora
    sessions to time out. A missing `DATABASE_URL` still has to surface per
    request rather than at boot, because `/api/health` answers without a database
    and the readiness endpoint exists to report exactly that failure.

    The access-control settings are judged differently: a deployment that
    required the shared origin secret and configured none must fail here,
    before uvicorn ever accepts a connection, rather than serving every caller
    a 401 forever while looking like a healthy process.
    """
    assert_bootable(get_settings())
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
    # One shared access policy for every route on this app, including ones
    # registered below through `include_router` and the manual session-memory
    # loop: the workshop's shared origin secret, verified per request. See
    # service/access_control.py. `/api/health` is the one documented exception.
    dependencies=[Depends(verify_origin_access)],
)
app.include_router(staged_catalog_router)
# The tool census inspects concrete APIRoutes, including these non-tool routes.
for memory_route in session_memory_router.routes:
    app.add_api_route(
        memory_route.path,
        memory_route.endpoint,
        methods=memory_route.methods,
        status_code=memory_route.status_code,
        tags=["session-memory"],
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.exception_handler(PoolTimeout)
async def _connection_timeout(_: Request, __: PoolTimeout) -> JSONResponse:
    """Report the wait without diagnosing saturation from a timeout alone.

    An unreachable Aurora cluster also exhausts this wait while the pool has no
    usable connections. Increasing pool limits cannot repair that failure.
    """
    settings = get_settings()
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "Mosaic could not get a catalog connection within "
                f"{settings.db_pool_timeout:g} seconds. Retry in a moment. If this "
                "continues, ask your facilitator to check Aurora connectivity "
                "and database capacity."
            )
        },
    )


@app.exception_handler(OperationalError)
async def _database_unavailable(_: Request, __: OperationalError) -> JSONResponse:
    """Return an actionable outage response without exposing connection details."""
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "Database operation failed with OperationalError; fix: retry in "
                "a moment, then verify Aurora connectivity and the configured "
                "DATABASE_URL in service logs if the failure persists."
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


def _agent_error(error: Exception) -> HTTPException:
    if isinstance(error, GroundingContractError):
        return HTTPException(503, _GROUNDING_ERROR_DETAIL)
    if isinstance(error, AgentTurnDeadlineExceeded):
        return HTTPException(503, str(error))
    return HTTPException(
        503,
        safe_model_runtime_message(
            error,
            fallback=(
                "Agent response failed. Check Aurora connectivity and the model "
                "runtime, then retry."
            ),
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
    """Report the service identity, its model IDs, and the Code Editor link.

    `code_editor_url` is null wherever no editor was provisioned, which is every
    environment outside Workshop Studio, and the storefront hides its link rather
    than offering one that cannot resolve. It never carries the editor token;
    `service.config` refuses to start on a value that does.
    """
    current = get_settings()
    return {
        "status": "ok",
        "service": "catalog-hybrid-retrieval",
        "code_editor_url": current.code_editor_url,
        "models": {
            "embedding": current.embedding_model_id,
            "rerank": current.rerank_model_id,
            "agent": current.agent_model_id,
            "synthesis": current.synthesis_model_id,
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
    if "catalog_ready" in database:
        database_ready = bool(database["catalog_ready"])
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
        "source": {
            "revision": settings.source_revision,
            "worktree_dirty": settings.source_worktree_dirty,
            "dataset_manifest_sha256": database.get(
                "dataset_manifest_sha256", settings.dataset_manifest_sha256
            ),
        },
    }


@app.get("/api/catalog/source")
def get_catalog_source() -> dict[str, Any]:
    from service.catalog_runtime import active_dataset

    return {
        "dataset_id": active_dataset(),
        "current_offers_available": not bool(active_dataset()),
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
    brands: Annotated[list[str] | None, Query()] = None,
    attributes: str | None = Query(default=None, max_length=4096),
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
    collection: str = "all",
) -> CatalogPage:
    try:
        filters = CatalogFilters(
            domain=domain,
            category_key=category_key,
            brand=brand,
            brands=brands or [],
            attributes=json.loads(attributes) if attributes is not None else {},
            availability=availability,
            in_stock_only=in_stock_only,
            min_price_cents=min_price_cents,
            max_price_cents=max_price_cents,
            min_rating=min_rating,
            include_refurbished=include_refurbished,
            include_sponsored=include_sponsored,
        )
    # json.loads raises RecursionError, not ValueError, on deeply nested
    # input, and the 4096-character bound above still admits ~2000 levels.
    except RecursionError as error:
        raise HTTPException(
            422, "attributes is nested too deeply to be a catalog attribute filter"
        ) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return list_products(
        filters,
        offset=offset,
        limit=limit,
        sort=sort,
        collection=collection,
    )


@app.post("/api/catalog/counts", response_model=list[int])
def get_catalog_counts(
    filters: Annotated[list[CatalogFilters], Body(min_length=1, max_length=12)],
) -> list[int]:
    """Return one Shop count per filter group, preserving the requested order."""
    return count_products(filters)


@app.get("/api/products/{product_id}", response_model=ProductDetail)
def get_product_detail(product_id: int) -> ProductDetail:
    return get_product(product_id)


@app.get("/api/products/{product_id}/similar", response_model=list[ProductSummary])
def get_similar_products(product_id: int) -> list[ProductSummary]:
    return similar_products(product_id)


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
    dependencies=[Depends(require_model_admission)],
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


@app.post(
    "/api/search",
    response_model=SearchResponse,
    dependencies=[Depends(require_model_admission)],
)
def search(request: SearchRequest) -> SearchResponse:
    try:
        return search_with_telemetry(request)
    except (ClientError, BotoCoreError) as error:
        raise _model_error(error) from error
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error


@app.post(
    "/api/retrieval/fusion-comparison",
    response_model=FusionComparisonResponse,
    dependencies=[Depends(require_model_admission)],
)
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
    except LabStateError as error:
        # 409: the deployment is in Lab 1's deliberate broken state, which the
        # participant resolves by finishing the repair. Not a defect.
        raise HTTPException(409, str(error)) from error
    except SubstrateError as error:
        # 500, not 400: the caller did nothing wrong. The two functions have
        # drifted apart, which is a defect in this deployment.
        raise HTTPException(500, str(error)) from error
    except (ClientError, BotoCoreError) as error:
        raise _model_error(error) from error
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error


@app.post(
    "/api/agent/answer",
    response_model=AgentResponse,
    dependencies=[Depends(require_model_admission)],
)
def agent_answer(request: AgentRequest, http_request: Request = None) -> AgentResponse:
    try:
        request = prepare_request(request, http_request)
        return get_product_discovery_agent().answer(request)
    except ConversationContextError as error:
        raise HTTPException(409, _CONVERSATION_ERROR_DETAIL) from error
    except (ClientError, BotoCoreError, RuntimeError) as error:
        raise _agent_error(error) from error


def _stream_error_payload(error: Exception) -> dict[str, Any]:
    """Classify one stream-ending exception into its SSE `error` payload.

    Each branch is a distinct, already-established failure surface. Kept as
    one small pure function rather than inline in `events()` so classifying a
    new failure type never grows that generator's already-long body.
    """
    if isinstance(error, ConversationContextError):
        return {"code": "conversation_context", "detail": _CONVERSATION_ERROR_DETAIL}
    # Session-ownership refusals raise HTTPException from inside the stream;
    # the non-streaming route lets them through as their own status, so the
    # stream reports the same detail instead of the generic runtime-failure
    # message.
    if isinstance(error, HTTPException):
        return {
            "code": "request_rejected",
            "status": error.status_code,
            "detail": str(error.detail),
        }
    if isinstance(error, GroundingContractError):
        return {"code": "supporting_sources", "detail": _GROUNDING_ERROR_DETAIL}
    if isinstance(error, AgentTurnDeadlineExceeded):
        return {"code": "agent_turn_deadline", "detail": str(error)}
    return {
        "detail": safe_model_runtime_message(
            error,
            fallback=(
                "Agent response failed. Retry after checking the runtime and "
                "retrieval service."
            ),
        )
    }


async def _admit_and_prepare_stream(
    request: AgentRequest, http_request: Request
) -> tuple[AgentRequest, threading.BoundedSemaphore]:
    """Reserve an admission slot, then prepare the request.

    The slot is released if `prepare_request` fails for any reason before the
    stream can start, so a rejected or invalid request never leaks one. On
    success, the caller owns releasing it -- see `stream_agent_answer`.

    Raises:
        HTTPException: 429 from admission exhaustion, before this does
            anything else; 409 for an invalid or unowned conversation
            context; a mapped agent-runtime status for a Bedrock failure.
    """
    slot = acquire_model_admission_slot()
    try:
        try:
            request = await asyncio.to_thread(prepare_request, request, http_request)
        except ConversationContextError as error:
            raise HTTPException(409, _CONVERSATION_ERROR_DETAIL) from error
        except (ClientError, BotoCoreError, RuntimeError) as error:
            raise _agent_error(error) from error
    except BaseException:
        release_model_admission_slot(slot)
        raise
    return request, slot


@app.post("/api/agent/answer/stream")
async def stream_agent_answer(
    request: AgentRequest, http_request: Request = None
) -> StreamingResponse:
    """Stream safe retrieval progress and a paced cited-answer delivery.

    The transport reports application-owned retrieval milestones, not private
    model reasoning. Agent execution remains bounded by the same typed,
    read-only tool contract as the completed-response endpoint.

    Admission control is acquired in `_admit_and_prepare_stream` rather than
    through a route dependency: a dependency releases its slot as soon as
    this function returns the `StreamingResponse` object, before the stream
    itself has sent a single byte. The slot is held instead for the life of
    the `events()` generator below, which releases it in its own `finally` --
    covering a failure before the stream starts, a failure mid-stream, and a
    client disconnect, which Starlette surfaces as the generator being closed.
    """
    request, slot = await _admit_and_prepare_stream(request, http_request)

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
                failure = event.get("agent_failure")
                if failure is not None:
                    yield _sse(
                        "error",
                        {
                            **failure,
                            "detail": "Grounded synthesis refused the answer. Inspect the recorded evidence and citations, repair the evidence contract, then run again."
                            if failure.get("code") == "grounding_contract"
                            else failure["detail"],
                        },
                    )
                    return

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
                        "Preparing an answer with sources.",
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
            logger.warning(
                "Agent response stream failed: error_type=%s previous_run_id=%s",
                type(error).__name__,
                request.context.previous_agent_run_id if request.context else None,
            )
            yield _sse("error", _stream_error_payload(error))
        finally:
            release_model_admission_slot(slot)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get(
    "/api/telemetry/agent-turns/{agent_turn_id}",
    response_model=AgentTelemetryResponse,
)
def agent_turn_telemetry(agent_turn_id: UUID) -> AgentTelemetryResponse:
    """Return the canonical Retrieve -> Rank -> Reason timeline.

    Like retrieval-event inspection, this is a single-attendee workshop
    capability surface rather than a tenancy boundary. AgentCore receives only
    the aggregate projection emitted by `service.telemetry`, never these
    candidate-level ranking receipts.
    """
    with connect() as connection:
        rows = load_agent_turn_rows(connection, agent_turn_id)
    if rows is None:
        raise HTTPException(404, "Agent turn not found")
    return build_agent_telemetry_contract(
        turn=rows.turn,
        session=rows.session,
        searches=rows.searches,
        candidates=rows.candidates,
        tools=rows.tools,
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
        candidates = load_candidate_receipts(connection, search_event_id)
    return RetrievalRunResponse(
        run=dict(event),
        candidates=[dict(row) for row in candidates],
    )


@app.get(
    "/api/retrieval/events/{search_event_id}/response",
    response_model=SearchResponse,
)
def retrieval_event_response(search_event_id: UUID) -> SearchResponse:
    """Serve one persisted retrieval as the response it originally returned.

    The sibling route above answers "what did the receipt record"; this one
    answers "what did the participant see", in the shape `POST /api/search`
    returns. That is what lets a run carried out of Shop fill the retrieval lab's
    stages with the rows Shop actually served instead of the rows a second search
    would produce for the same words.

    Nothing is re-executed: no embedding call, no fusion SQL, no reranker. The
    served rows and their ranking signals come from
    `mosaic.search_result_event`, and the products are hydrated by the catalog
    loader the compare route already uses.

    `coverage` is always absent, because term coverage is computed per request
    and never persisted. Same scoping caveat as the route above: an event id is a
    retrieval capability handle, not an identity boundary.
    """
    try:
        return replay_search_response(search_event_id)
    except UnknownSearchEvent as error:
        raise HTTPException(404, str(error)) from error
    except KeyError as error:
        # The event exists and cannot be replayed faithfully: its profile is
        # missing a field, or its products outlived the receipt. That is a
        # conflict with what is stored, not a server fault, and it arrived as a
        # 500 with the reason swallowed. `error.args[0]` because `str()` on a
        # `KeyError` quotes the whole message.
        raise HTTPException(409, str(error.args[0])) from error


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
    try:
        summaries = get_product_summaries(unique_ids)
    except KeyError as error:
        raise HTTPException(
            409,
            "These results use a previous catalog. Run a new search before comparing products.",
        ) from error
    products = [
        product.model_copy(
            update={"signals": signals_from_receipt(by_product[product.product_id])}
        )
        for product in summaries
    ]
    return ProductComparisonResponse(
        retrieval_scope_id=search_event_id,
        products=products,
    )


@app.post(
    "/api/retrieval/events/{search_event_id}/plan",
    response_model=RetrievalPlanResponse,
    dependencies=[Depends(require_model_admission)],
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


@app.get("/api/skill-package")
def download_skill_package() -> Response:
    """Download the canonical skill and its references as one portable folder."""
    package = ROOT / "skills" / "mosaic-hybrid-retrieval"
    files = [package / "SKILL.md", *sorted((package / "references").rglob("*.md"))]
    if not files[0].is_file():
        raise HTTPException(
            status_code=503,
            detail="The skill package is missing; restore skills/mosaic-hybrid-retrieval.",
        )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            if path.is_file() and path.resolve().is_relative_to(package.resolve()):
                archive.writestr(
                    str(path.relative_to(package.parent)), path.read_bytes()
                )
    return Response(
        content=output.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="mosaic-hybrid-retrieval.zip"'
        },
    )


@app.get("/api/builder-package")
def builder_package_route() -> Response:
    """Download the participant exercise and its reference SQL without local state."""
    try:
        content = build_package(ROOT)
    except (OSError, ValueError) as error:
        raise HTTPException(
            503,
            "Builder files are unavailable; restore the files listed in service/builder_package.py from the Mosaic checkout.",
        ) from error
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="mosaic-builder.zip"'},
    )


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
    """The committed measured benchmark artifact, with its provenance.

    `attribution` says whether the artifact describes the connected cluster, and
    the representation comparison is withheld when the quantized indexes it
    compares do not exist here.
    """
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


@app.post("/api/hnsw/probe", dependencies=[Depends(require_model_admission)])
def hnsw_probe_route(request: HnswProbeRequest) -> dict[str, Any]:
    """Run the same ANN query twice and report what the server actually did.

    The first execution returns the rows recall is computed from; the second runs
    under EXPLAIN (ANALYZE, BUFFERS) and supplies the plan, timing, and buffer
    counts. `plan.execution` carries which is which onto every response.

    Recall is computed against precomputed ground truth, never by re-running the
    exact scan, so this endpoint's cost ceiling is two filtered HNSW scans rather
    than a sequential scan over 3,870 MB of TOASTed vectors.
    """
    try:
        return hnsw.probe(request)
    except RepresentationUnavailable as error:
        raise HTTPException(404, str(error)) from error
    except KeyError as error:
        raise HTTPException(404, str(error.args[0])) from error
    except StaleGroundTruth as error:
        raise HTTPException(503, str(error)) from error


#: What a lab route says when the cluster itself is unreachable. Deliberately
#: generic: `OperationalError` messages carry the host, port, and user psycopg
#: tried, and a lab page is the surface most likely to be screen-shared.
LAB_DATABASE_UNAVAILABLE = (
    "found the workshop database unreachable while reading lab state; fix: "
    "retry in a moment, then confirm the Aurora cluster is available before "
    "grading a lab"
)


@app.get("/api/labs/state", response_model=LabStateResponse)
def lab_state() -> LabStateResponse:
    """Where each lab stands, in both places a lab can be broken.

    Cheap and side-effect free: it reads three marker blocks off disk and asks
    Aurora what two functions currently contain. It runs no retrieval, so a
    participant can poll it while working without spending anything.

    A missing SQL function is a lab verdict (`database_state = "stale"`), not
    an error. An unreachable cluster is the opposite, and `OperationalError` --
    which `PoolTimeout` subclasses -- becomes a 503 that names no connection.
    """
    try:
        return lab_states()
    except OperationalError as error:
        raise HTTPException(503, LAB_DATABASE_UNAVAILABLE) from error
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error


@app.post(
    "/api/labs/{lab_id}/proof",
    response_model=CompletionProofResponse,
    dependencies=[Depends(require_model_admission)],
)
def lab_completion_proof(
    lab_id: int,
    request: CompletionProofRequest,
) -> CompletionProofResponse:
    """Prove one lab is finished, against Aurora, right now.

    Labs 1 and 2 re-run their mission through the production search path and
    report the receipts. Lab 3 grades the persisted turn named by
    `agent_run_id` and spends no agent turn of its own, so pressing this button
    costs no model call and grades the run the participant is looking at rather
    than a fresh one.
    """
    try:
        return completion_proof(lab_id, agent_run_id=request.agent_run_id)
    except UnknownLab as error:
        raise HTTPException(404, str(error)) from error
    except (ClientError, BotoCoreError) as error:
        raise _model_error(error) from error
    except OperationalError as error:
        raise HTTPException(503, LAB_DATABASE_UNAVAILABLE) from error
    except (FileNotFoundError, RuntimeError) as error:
        raise HTTPException(503, str(error)) from error
