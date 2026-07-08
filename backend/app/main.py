from __future__ import annotations
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .agent import answer_question
from .db import get_dict_conn
from .ingest import create_job, upsert_objects
from .models import AgentAnswerRequest, IngestObjectsRequest, SearchRequest, SourceCreateRequest
from .search import run_hybrid_search

app = FastAPI(title="Agentic Hybrid Retrieval API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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

@app.post("/v1/search")
def search(req: SearchRequest):
    return run_hybrid_search(req)

@app.post("/v1/agent/answer")
def agent_answer(req: AgentAnswerRequest):
    return answer_question(req)

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
