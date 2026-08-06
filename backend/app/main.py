from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .agent import (
    answer_question,
    compare_sources_impl,
    decompose_question_impl,
    explain_ranking_impl,
    follow_evidence_links_impl,
    get_agent_coverage_impl,
    get_agent_run_impl,
    stream_answer,
    synthesize_cited_answer_from_runs_impl,
)
from .agent_tools import tool_specifications
from .config import get_settings
from .contracts import (
    InvocationContext,
    invoke_contract,
    new_request_id,
    record_transport_invocation,
)
from .db import close_pool, get_dict_conn, open_pool
from .evaluation import run_evaluation
from .insights import (
    fusion_sql,
    index_usage,
    latest_cited_run,
    latest_live_run,
    observability_ref,
    search_index_diagnostics,
    search_index_health,
    query_plan,
    run_graph,
    run_timeline,
    slow_queries,
)
from .lab_routes import router as lab_router
from .models import (
    AgentAnswerRequest,
    CompareRequest,
    DecomposeRequest,
    DEFAULT_ROLE,
    EvaluationRequest,
    ExplainRankingRequest,
    Persona,
    QueryPlanRequest,
    SearchRequest,
    SynthesisRequest,
    TraverseRequest,
)
from .search import run_hybrid_search
from .strands_agent import (
    answer_question_with_strands,
    stream_answer_with_strands,
    strands_agent_metadata,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        open_pool()
    except Exception as error:
        logger.warning("PostgreSQL pool did not open at startup: %s", error)
    try:
        yield
    finally:
        close_pool()


settings = get_settings()
app = FastAPI(
    title="Hybrid Retrieval Workbench API",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins(),
    allow_origin_regex=settings.cors_allow_origin_regex or None,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(lab_router)


def _unavailable(area: str, error: Exception) -> HTTPException:
    logger.warning("%s unavailable: %s", area, error)
    return HTTPException(
        503,
        f"{area} unavailable; run `make doctor` and verify the search index",
    )


def _require_retrieval_ready() -> None:
    readiness = search_index_health()
    if readiness["status"] != "ready" or not readiness.get("run"):
        raise HTTPException(
            409,
            "retrieval is awaiting the participant-induced incident and indexing receipt",
        )


def _invocation_context(request: Request) -> InvocationContext:
    transport = request.headers.get("x-workbench-transport", "http")
    return InvocationContext(
        transport=transport,
        request_id=request.headers.get("x-request-id") or new_request_id(),
        transport_trace_id=(
            request.headers.get("x-workbench-transport-trace-id")
            or request.headers.get("x-amzn-trace-id")
        ),
    )


@app.get("/health")
def health():
    return {"ok": True, "service": "workbench-incident-evidence"}


@app.get("/ready")
def ready():
    try:
        return search_index_health()
    except Exception as error:
        raise _unavailable("search index", error)


@app.post("/v1/search")
def search(request: SearchRequest, http_request: Request):
    try:
        _require_retrieval_ready()
        return invoke_contract(
            _invocation_context(http_request),
            "search_evidence",
            request.model_dump(mode="json"),
            lambda: run_hybrid_search(request),
        )
    except Exception as error:
        raise _unavailable("search", error)


@app.post("/v1/search/vector")
def search_vector(request: SearchRequest, http_request: Request):
    return search(
        request.model_copy(update={"mode": "semantic"}),
        http_request,
    )


@app.post("/v1/search/fts")
def search_fts(request: SearchRequest, http_request: Request):
    return search(
        request.model_copy(update={"mode": "lexical"}),
        http_request,
    )


@app.post("/v1/search/fuzzy")
def search_fuzzy(request: SearchRequest, http_request: Request):
    return search(
        request.model_copy(update={"mode": "fuzzy"}),
        http_request,
    )


@app.post("/v1/agent/answer")
def agent_answer(request: AgentAnswerRequest, http_request: Request):
    try:
        _require_retrieval_ready()
        return invoke_contract(
            _invocation_context(http_request),
            "answer_with_citations",
            request.model_dump(mode="json"),
            lambda: answer_question(request),
        )
    except Exception as error:
        raise _unavailable("cited answer", error)


@app.post("/v1/agent/strands/answer")
def strands_answer(request: AgentAnswerRequest, http_request: Request):
    """Answer by letting the model choose and sequence the tools itself."""
    try:
        _require_retrieval_ready()
        return invoke_contract(
            _invocation_context(http_request),
            "strands_agent_answer",
            request.model_dump(mode="json"),
            lambda: answer_question_with_strands(request),
        )
    except Exception as error:
        raise _unavailable("strands agent answer", error)


@app.post("/v1/agent/strands/answer/stream")
async def strands_answer_stream(request: AgentAnswerRequest, http_request: Request):
    """Stream each tool the model selects, then the cited answer, as they happen."""
    _require_retrieval_ready()
    context = _invocation_context(http_request)
    payload_in = request.model_dump(mode="json")

    async def events():
        final: dict | None = None
        async for event in stream_answer_with_strands(request):
            if event["type"] in {"done", "error"}:
                final = event
            payload = json.dumps(event, default=str)
            yield f"event: {event['type']}\ndata: {payload}\n\n"
        # The receipt is written after the stream drains, so a streamed run is
        # auditable on the same terms as a buffered one.
        try:
            record_transport_invocation(
                context,
                "strands_agent_answer",
                payload_in,
                response_payload=final,
                status="succeeded" if final and final["type"] == "done" else "failed",
                error=(final or {}).get("error"),
            )
        except Exception as error:
            logger.warning("Could not persist streamed agent receipt: %s", error)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/v1/agent/strands/tools")
def strands_tools():
    """Return the tool schemas the model sees, read from the decorators."""
    return {
        "agent": strands_agent_metadata(),
        "tools": tool_specifications(),
    }


@app.post("/v1/tools/decompose")
def tool_decompose(request: DecomposeRequest, http_request: Request):
    try:
        return invoke_contract(
            _invocation_context(http_request),
            "decompose_question",
            request.model_dump(mode="json"),
            lambda: decompose_question_impl(request.question, role=request.role),
        )
    except Exception as error:
        raise _unavailable("question decomposition", error)


@app.post("/v1/tools/traverse")
def tool_traverse(request: TraverseRequest, http_request: Request):
    try:
        return invoke_contract(
            _invocation_context(http_request),
            "follow_evidence_links",
            request.model_dump(mode="json"),
            lambda: follow_evidence_links_impl(
                request.seed_external_keys,
                role=request.role,
                max_depth=request.max_depth,
            ),
        )
    except Exception as error:
        raise _unavailable("evidence traversal", error)


@app.post("/v1/tools/compare")
def tool_compare(request: CompareRequest, http_request: Request):
    try:
        return invoke_contract(
            _invocation_context(http_request),
            "compare_sources",
            request.model_dump(mode="json"),
            lambda: compare_sources_impl(
                request.external_keys,
                role=request.role,
            ),
        )
    except Exception as error:
        raise _unavailable("source comparison", error)


@app.post("/v1/tools/explain-ranking")
def tool_explain_ranking(
    request: ExplainRankingRequest,
    http_request: Request,
):
    try:
        return invoke_contract(
            _invocation_context(http_request),
            "explain_ranking",
            request.model_dump(mode="json"),
            lambda: explain_ranking_impl(request.run_id, role=request.role),
        )
    except ValueError as error:
        raise HTTPException(404, str(error))
    except Exception as error:
        raise _unavailable("ranking explanation", error)


@app.post("/v1/tools/synthesize")
def tool_synthesize(request: SynthesisRequest, http_request: Request):
    try:
        return invoke_contract(
            _invocation_context(http_request),
            "synthesize_cited_answer",
            request.model_dump(mode="json"),
            lambda: synthesize_cited_answer_from_runs_impl(
                request.question,
                request.run_ids,
                limit=request.limit,
                role=request.role,
            ),
        )
    except ValueError as error:
        raise HTTPException(404, str(error))
    except Exception as error:
        raise _unavailable("cited synthesis", error)


@app.post("/v1/agent/answer/stream")
def agent_answer_stream(request: AgentAnswerRequest, http_request: Request):
    _require_retrieval_ready()
    response = invoke_contract(
        _invocation_context(http_request),
        "answer_with_citations",
        request.model_dump(mode="json"),
        lambda: answer_question(request),
    )

    def events():
        meta = {
            key: response[key]
            for key in (
                "question",
                "agent_run_id",
                "run_id",
                "agent",
                "plan",
                "citations",
            )
            if key in response
        }
        yield f"event: meta\ndata: {json.dumps(meta, default=str)}\n\n"
        answer = response["answer"]
        for offset in range(0, len(answer), 32):
            data = {"text": answer[offset : offset + 32]}
            yield f"event: token\ndata: {json.dumps(data)}\n\n"
        yield f"event: done\ndata: {json.dumps(response, default=str)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/v1/agent-runs/{agent_run_id}")
def agent_run(agent_run_id: str, role: Persona = DEFAULT_ROLE):
    try:
        return get_agent_run_impl(agent_run_id, role=role)
    except ValueError as error:
        raise HTTPException(404, str(error))
    except Exception as error:
        raise _unavailable("agent run", error)


@app.get("/v1/agent-runs/{agent_run_id}/coverage")
def agent_coverage(agent_run_id: str, role: Persona = DEFAULT_ROLE):
    try:
        return get_agent_coverage_impl(agent_run_id, role=role)
    except ValueError as error:
        raise HTTPException(404, str(error))
    except Exception as error:
        raise _unavailable("agent coverage", error)


@app.get("/v1/evidence/{evidence_id}")
def evidence_detail(evidence_id: str, role: Persona = DEFAULT_ROLE):
    # Enforce the same ACL every retrieval arm and traversal hop applies, so a
    # direct by-ID read cannot bypass visibility. Evidence outside the caller's
    # scope is reported as not found rather than acknowledged as restricted.
    try:
        with get_dict_conn(role) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT source.*, document.*
                    FROM casework.v_evidence_documents source
                    LEFT JOIN retrieval.documents document
                      ON document.evidence_id = source.evidence_id
                     AND document.is_current
                    WHERE source.evidence_id = %s
                      AND retrieval.acl_visible(source.acl)
                    """,
                    (evidence_id,),
                )
                evidence = cursor.fetchone()
                if not evidence:
                    raise HTTPException(404, "evidence not found")
                cursor.execute(
                    """
                    SELECT
                      chunk_version_id,
                      chunk_ordinal,
                      section_title,
                      chunk_text,
                      chunk_hash,
                      embedding_model,
                      embedding_state
                    FROM retrieval.chunks
                    WHERE document_version_id = %s
                    ORDER BY chunk_ordinal
                    """,
                    (evidence["document_version_id"],),
                )
                chunks = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT *
                    FROM retrieval.evidence_edges
                    WHERE from_evidence_id = %s OR to_evidence_id = %s
                    ORDER BY origin, relation, edge_key
                    """,
                    (evidence_id, evidence_id),
                )
                edges = cursor.fetchall()
        return {"evidence": evidence, "chunks": chunks, "edges": edges}
    except HTTPException:
        raise
    except Exception as error:
        raise _unavailable("evidence detail", error)


@app.get("/v1/runs/latest")
def latest_run(role: Persona = DEFAULT_ROLE):
    try:
        run = latest_cited_run(role)
        if not run:
            raise HTTPException(404, "no completed cited run found")
        return run
    except HTTPException:
        raise
    except Exception as error:
        raise _unavailable("latest cited run", error)


@app.get("/v1/workshop/run")
def workshop_run():
    try:
        run = latest_live_run()
        if not run:
            return {"status": "awaiting_incident", "run": None}
        readiness = search_index_health()
        return {
            "status": readiness["status"],
            "run": run,
            "indexing_receipt": {
                "documents": readiness["current_documents"],
                "chunks": readiness["current_chunks"],
                "ready_embeddings": readiness["ready_embeddings"],
                "drift_issues": readiness["drift_issues"],
                "last_indexed_at": readiness["last_indexed_at"],
                "embedding_spaces": readiness["embedding_spaces"],
            },
        }
    except Exception as error:
        raise _unavailable("workshop run", error)


@app.get("/v1/runs/{run_id}")
def run_receipt(run_id: str, role: Persona = DEFAULT_ROLE):
    try:
        receipt = explain_ranking_impl(run_id, role=role)
        # The observed window and optional lock-analysis link belong to the Proof
        # HTTP surface, not the agent's explain_ranking tool.
        receipt["observability_ref"] = observability_ref(run_id, role=role)
        return receipt
    except ValueError as error:
        raise HTTPException(404, str(error))
    except Exception as error:
        raise _unavailable("run receipt", error)


@app.get("/v1/runs/{run_id}/candidates")
def run_candidates(run_id: str, role: Persona = DEFAULT_ROLE):
    receipt = run_receipt(run_id, role=role)
    return {
        "run_id": run_id,
        "candidates": receipt["candidates"],
        "_verify_sql": receipt["_verify_sql"]["candidates"],
    }


@app.get("/v1/runs/{run_id}/timeline")
def timeline(run_id: str, role: Persona = DEFAULT_ROLE):
    try:
        return run_timeline(run_id, role=role)
    except ValueError as error:
        raise HTTPException(404, str(error))
    except Exception as error:
        raise _unavailable("run timeline", error)


@app.get("/v1/runs/{run_id}/graph")
def graph(run_id: str, role: Persona = DEFAULT_ROLE):
    try:
        return run_graph(run_id, role=role)
    except ValueError as error:
        raise HTTPException(404, str(error))
    except Exception as error:
        raise _unavailable("run graph", error)


@app.get("/v1/diagnostics/search-index")
def diagnostics_search_index():
    try:
        return search_index_diagnostics()
    except Exception as error:
        raise _unavailable("search index diagnostics", error)


@app.get("/v1/diagnostics/corpus")
def diagnostics_corpus():
    return diagnostics_search_index()


@app.get("/v1/diagnostics/fusion-sql")
def diagnostics_fusion_sql():
    try:
        return fusion_sql()
    except Exception as error:
        raise _unavailable("fusion SQL", error)


@app.post("/v1/diagnostics/plan")
def diagnostics_plan(request: QueryPlanRequest):
    try:
        return query_plan(request)
    except Exception as error:
        raise _unavailable("query plan", error)


@app.get("/v1/diagnostics/index-usage")
def diagnostics_indexes():
    try:
        return index_usage()
    except Exception as error:
        raise _unavailable("index diagnostics", error)


@app.get("/v1/diagnostics/slow-queries")
def diagnostics_slow_queries():
    try:
        return slow_queries()
    except Exception as error:
        raise _unavailable("pg_stat_statements diagnostics", error)


@app.post("/v1/evaluation")
def evaluation(request: EvaluationRequest):
    try:
        return run_evaluation(request.modes, request.limit)
    except Exception as error:
        raise _unavailable("retrieval evaluation", error)
