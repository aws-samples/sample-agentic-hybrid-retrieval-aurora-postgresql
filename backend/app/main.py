from __future__ import annotations
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .agent import answer_question
from .db import get_dict_conn
from .ingest import create_job, upsert_objects
from .models import AgentAnswerRequest, IngestObjectsRequest, SearchRequest, SourceCreateRequest
from .search import run_hybrid_search
from .config import get_settings

app = FastAPI(title="Agentic Hybrid Retrieval API", version="0.1.0")
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
    source_id, job_id = create_job(req.source_system, req.source_name, len(req.objects))
    return upsert_objects(source_id, job_id, req.objects)

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
                ORDER BY c.final_score DESC NULLS LAST
            """, (run_id,))
            return {"run_id": run_id, "candidates": cur.fetchall()}

@app.post("/v1/search")
def search(req: SearchRequest):
    return run_hybrid_search(req)

@app.post("/v1/agent/answer")
def agent_answer(req: AgentAnswerRequest):
    return answer_question(req)

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

@app.get("/v1/diagnostics/canonical")
def canonical_diagnostics():
    """The canonical run's metrics + diagnostics rows for the demo Diagnostics view."""
    try:
        with get_dict_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT m.*, a.question, a.confidence, a.source_count, a.system_count
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
    return row

@app.get("/v1/diagnostics/corpus")
def corpus_diagnostics():
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM ops.v_corpus_profile")
            profile = cur.fetchone()
            cur.execute("SELECT * FROM ops.v_source_distribution")
            distribution = cur.fetchall()
            cur.execute("SELECT * FROM ops.v_embedding_progress")
            embeddings = cur.fetchone()
            return {"profile": profile, "source_distribution": distribution, "embedding_progress": embeddings}
