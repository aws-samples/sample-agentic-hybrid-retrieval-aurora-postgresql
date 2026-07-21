from __future__ import annotations
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .agent import (
    answer_question,
    agent_metadata,
    attach_object_ids,
    derive_commitments,
    lookup_canonical_answer,
    persisted_run_results,
    stream_answer,
)
from .db import close_pool, get_dict_conn, open_pool
from .evaluation import run_evaluation
from .ingest import create_job, upsert_objects
from .insights import fusion_sql, index_usage, query_plan, run_graph, run_timeline, slow_queries
from .models import (
    AgentAnswerRequest,
    EvaluationRequest,
    IngestObjectsRequest,
    QueryPlanRequest,
    SearchRequest,
    SourceCreateRequest,
)
from .search import run_hybrid_search
from .config import get_settings

logger = logging.getLogger(__name__)
HERO_PREVIEW_PATH = Path(__file__).resolve().parents[2] / "seed" / "artifacts" / "hero_preview.json"
SEARCH_UNAVAILABLE = (
    "search unavailable — run `make doctor` to verify Aurora schema, "
    "connectivity, embeddings, and reranking"
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Open the Postgres connection pool on startup, drain it on shutdown.

    Opening the pool eagerly surfaces a bad DATABASE_URL at boot instead of on the
    first request. A pool failure is logged rather than fatal so the health check
    and the schema-not-provisioned 503s still respond; the per-request 503 handlers
    already cover a database that never comes up.
    """
    try:
        open_pool()
    except Exception as exc:  # pragma: no cover - startup diagnostics only
        logger.warning("Postgres pool did not open at startup: %s", exc)
    try:
        yield
    finally:
        close_pool()


app = FastAPI(title="Agentic Hybrid Retrieval API", version="0.1.0", lifespan=lifespan)
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins(),
    allow_origin_regex=settings.cors_allow_origin_regex or None,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"ok": True}


@app.get("/v1/diagnostics/hero-preview")
def hero_preview():
    """Seed-backed landing preview for an API whose evidence index is not ready.

    This endpoint never claims to be live diagnostics. The frontend labels it as
    a preview and still requires /v1/diagnostics/canonical before enabling the
    guided proof flow.
    """
    try:
        return json.loads(HERO_PREVIEW_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(503, "seed-backed hero preview unavailable")


@app.post("/v1/sources")
def create_source(req: SourceCreateRequest):
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ops.source_connectors(source_system, source_name, auth_mode, config)
                VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT(source_system, source_name) DO UPDATE SET auth_mode = EXCLUDED.auth_mode, config = EXCLUDED.config
                RETURNING source_id, source_system, source_name, auth_mode, status;
            """, (req.source_system, req.source_name, req.auth_mode, req.config.model_dump_json() if hasattr(req.config, 'model_dump_json') else __import__('json').dumps(req.config)))
            return cur.fetchone()

@app.post("/v1/ingest/objects")
def ingest_objects(req: IngestObjectsRequest):
    source_id, job_id = create_job(
        req.source_system,
        req.source_name,
        len(req.objects),
        sync_mode=req.sync_mode,
        sync_cursor=req.sync_cursor,
    )
    return upsert_objects(
        source_id,
        job_id,
        req.objects,
        sync_mode=req.sync_mode,
        sync_cursor=req.sync_cursor,
    )

@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str):
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM ops.ingest_jobs WHERE job_id = %s", (job_id,))
            job = cur.fetchone()
            if not job:
                raise HTTPException(404, "job not found")
            cur.execute("SELECT step_name, status, message, metadata, created_at FROM ops.ingest_job_events WHERE job_id = %s ORDER BY created_at", (job_id,))
            events = cur.fetchall()
            return {"job": job, "events": events}

@app.get("/v1/sources/{source_id}/status")
def source_status(source_id: str):
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM ops.source_connectors WHERE source_id = %s", (source_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "source not found")
            return row

@app.get("/v1/objects/{object_id}")
def source_object_detail(object_id: str):
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM ops.source_objects WHERE object_id = %s", (object_id,))
            obj = cur.fetchone()
            if not obj:
                raise HTTPException(404, "source object not found")
            cur.execute("""
                SELECT chunk_id, chunk_index, section_title, chunk_text, chunk_summary, metadata
                FROM ops.object_chunks
                WHERE object_id = %s
                ORDER BY chunk_index
            """, (object_id,))
            chunks = cur.fetchall()
            cur.execute("""
                SELECT citation_id, chunk_id, source_label, source_url, locator, quote_text, metadata
                FROM ops.citations
                WHERE object_id = %s
                ORDER BY locator
            """, (object_id,))
            citations = cur.fetchall()
            cur.execute("""
                SELECT l.link_id, l.link_type, l.confidence, l.metadata,
                       o.object_id, o.source_system, o.source_type, o.external_id, o.title, o.url
                FROM ops.object_links l
                JOIN ops.source_objects o ON o.object_id = l.to_object_id
                WHERE l.from_object_id = %s
                ORDER BY l.confidence DESC, o.updated_at DESC NULLS LAST
            """, (object_id,))
            links = cur.fetchall()
            return {"object": obj, "chunks": chunks, "citations": citations, "links": links}

@app.get("/v1/runs/{run_id}/candidates")
def retrieval_run_candidates(run_id: str):
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.*, o.source_system, o.source_type, o.external_id, o.title, o.url
                FROM ops.retrieval_candidates c
                JOIN ops.source_objects o ON o.object_id = c.object_id
                WHERE c.run_id = %s
                ORDER BY
                  CASE WHEN c.rerank_score IS NULL THEN 1 ELSE 0 END,
                  c.rerank_score DESC NULLS LAST,
                  c.final_score DESC NULLS LAST
            """, (run_id,))
            return {"run_id": run_id, "candidates": cur.fetchall()}

@app.get("/v1/runs/{run_id}/timeline")
def retrieval_run_timeline(run_id: str):
    """Time-ordered cross-system sequence of the run's cited objects + their links."""
    try:
        return run_timeline(run_id)
    except Exception:
        raise HTTPException(503, "timeline unavailable — run `make seed-load` to restore the seeded corpus")


@app.get("/v1/runs/{run_id}/graph")
def retrieval_run_graph(run_id: str):
    """The object_links among the run's cited objects — the evidence graph."""
    try:
        return run_graph(run_id)
    except Exception:
        raise HTTPException(503, "graph unavailable — run `make seed-load` to restore the seeded corpus")


@app.get("/v1/diagnostics/fusion-sql")
def diagnostics_fusion_sql():
    """The deployed ops.hybrid_search definition — the fusion query, verbatim."""
    try:
        return fusion_sql()
    except Exception:
        raise HTTPException(503, "fusion SQL unavailable — run `make schema` (applies sql/03_search_functions.sql)")


@app.post("/v1/diagnostics/plan")
def diagnostics_plan(req: QueryPlanRequest):
    """EXPLAIN (ANALYZE, BUFFERS) the retrieval arm(s) for a query on live Aurora.

    Plans the real arm query bodies (not the SQL function wrappers, which EXPLAIN to
    an opaque Function Scan), so a builder sees the actual GIN / HNSW / Seq Scan the
    planner chooses. 'hybrid' returns the plan of all three arms.
    """
    try:
        return query_plan(
            arm=req.arm,
            query=req.query,
            limit=req.limit,
            source_systems=req.source_systems,
            project_key=req.project_key,
        )
    except Exception:
        raise HTTPException(503, "query plan unavailable — run `make schema` (applies sql/10_query_plan.sql)")


@app.get("/v1/diagnostics/index-usage")
def diagnostics_index_usage():
    """Live index scan counts + sizes for the ops schema (GIN / HNSW / btree)."""
    try:
        return index_usage()
    except Exception:
        raise HTTPException(503, "index usage unavailable — run `make schema` (applies sql/10_query_plan.sql)")


@app.get("/v1/diagnostics/slow-queries")
def diagnostics_slow_queries():
    """Retrieval queries ranked by mean execution time, from pg_stat_statements."""
    try:
        return slow_queries()
    except Exception:
        raise HTTPException(
            503,
            "slow-query stats unavailable — ensure pg_stat_statements is preloaded and run `make schema`",
        )


@app.post("/v1/search")
def search(req: SearchRequest):
    """Retrieval over Aurora. `mode` selects the fused ranker or one signal arm."""
    return _search_or_503(req)


@app.post("/v1/search/vector")
def search_vector(req: SearchRequest):
    """Semantic-only: pgvector cosine over the HNSW index (ops.vector_search)."""
    return _search_or_503(req.model_copy(update={"mode": "semantic"}))


@app.post("/v1/search/fts")
def search_fts(req: SearchRequest):
    """Lexical-only: tsvector @@ tsquery ranked by ts_rank_cd (ops.full_text_search)."""
    return _search_or_503(req.model_copy(update={"mode": "lexical"}))


@app.post("/v1/search/fuzzy")
def search_fuzzy(req: SearchRequest):
    """Fuzzy-only: pg_trgm similarity over title + leading text (ops.fuzzy_match)."""
    return _search_or_503(req.model_copy(update={"mode": "fuzzy"}))


def _search_or_503(req: SearchRequest):
    try:
        return run_hybrid_search(req)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Search request unavailable: %s", exc)
        raise HTTPException(503, SEARCH_UNAVAILABLE)

@app.post("/v1/agent/answer")
def agent_answer(req: AgentAnswerRequest):
    return answer_question(req)


@app.post("/v1/agent/answer/stream")
def agent_answer_stream(req: AgentAnswerRequest):
    """Server-Sent Events stream of the agent answer.

    Emits a `meta` event (run_id, citations, canonical flag), then `token` events
    as the Strands agent streams synthesis over Bedrock, then a terminal `done`
    event carrying token usage. Canonical questions stream their stored answer.
    """

    def event_stream():
        for event in stream_answer(req):
            yield f"event: {event['type']}\ndata: {json.dumps(event['data'], default=str)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.get("/v1/runs/{run_id}/metrics")
def retrieval_run_metrics(run_id: str):
    try:
        with get_dict_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM ops.retrieval_run_metrics WHERE run_id = %s", (run_id,))
                metrics = cur.fetchone()
    except Exception:
        # Metrics table not provisioned yet (schema not migrated / dump not restored).
        raise HTTPException(503, "run metrics unavailable — run `make schema` (applies sql/06_agent_answers.sql) or `make seed-load`")
    if not metrics:
        raise HTTPException(404, "run metrics not found")
    return metrics

@app.post("/v1/evaluation")
def evaluation(req: EvaluationRequest):
    """Score each retrieval mode against the judged queries.

    Fires one live retrieval run per mode against every ops.evaluation_queries row,
    then returns recall@k / precision@10 / MRR / nDCG@10 per run plus a leaderboard
    of the mean nDCG@10 / recall@10 / MRR per mode. Lets a builder read the retrieval
    tradeoff off real numbers instead of taking the hybrid-wins claim on faith.
    """
    try:
        return run_evaluation(modes=req.modes, limit=req.limit)
    except Exception:
        raise HTTPException(
            503,
            "evaluation unavailable — run `make schema` (applies sql/09_evaluation_metrics.sql) or `make seed-load`",
        )


@app.get("/v1/diagnostics/canonical")
def canonical_diagnostics():
    """The canonical run's metrics + diagnostics rows + cited sources.

    Read-only: this creates no retrieval run, so the landing page can hydrate its
    hero nodes and the Diagnostics view from live rows without side effects.
    """
    try:
        with get_dict_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT m.*, a.question, a.answer, a.confidence,
                           a.source_count, a.system_count, a.citations
                    FROM ops.retrieval_run_metrics m
                    JOIN ops.agent_answers a ON a.run_id = m.run_id
                    ORDER BY m.fired_at DESC
                    LIMIT 1
                """)
                row = cur.fetchone()
    except Exception:
        # Canonical tables not provisioned yet (schema not migrated / dump not restored).
        raise HTTPException(503, "canonical diagnostics unavailable — run `make schema` (applies sql/06_agent_answers.sql) or `make seed-load`")
    if not row:
        raise HTTPException(404, "no canonical run recorded")
    citations = attach_object_ids(row.get("citations"))
    # Unpack the stored answer into the same {answer, plan} shape the agent
    # endpoint returns, so the frontend has one renderer for both paths.
    stored = row.pop("answer", None)
    body = stored.get("body") if isinstance(stored, dict) else stored
    plan = stored.get("plan") if isinstance(stored, dict) else None
    row["citations"] = citations
    row["answer"] = body
    row["plan"] = plan
    row["commitments"] = derive_commitments(citations)
    row["results"] = persisted_run_results(str(row["run_id"]))
    # Serve the agent/model metadata live so the frontend never hard-codes model
    # IDs — the routed models come from settings, which differ per environment.
    row["agent"] = agent_metadata()
    return row

@app.get("/v1/diagnostics/corpus")
def corpus_diagnostics():
    try:
        with get_dict_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM ops.v_corpus_profile")
                profile = cur.fetchone()
                cur.execute("SELECT * FROM ops.v_source_distribution")
                distribution = cur.fetchall()
                cur.execute("SELECT * FROM ops.v_embedding_progress")
                embeddings = cur.fetchone()
                index_sizes = _vector_index_sizes(cur)
                return {
                    "profile": profile,
                    "source_distribution": distribution,
                    "embedding_progress": embeddings,
                    "vector_index_sizes": index_sizes,
                }
    except Exception as exc:
        logger.warning("Corpus diagnostics unavailable: %s", exc)
        raise HTTPException(
            503,
            "corpus diagnostics unavailable — run `make schema` or `make seed-load`",
        )


def _vector_index_sizes(cur):
    """The measured on-disk size of each vector index (float32 / halfvec / binary).

    Returns [] when the pgvector-0.8 view is absent (sql/08 not applied yet) so an
    older schema still serves the corpus diagnostics rather than erroring.
    """
    try:
        cur.execute("SELECT * FROM ops.v_index_sizes")
        return cur.fetchall()
    except Exception:
        return []
