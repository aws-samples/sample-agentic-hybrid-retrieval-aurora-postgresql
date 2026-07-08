from __future__ import annotations
import json
from typing import Any, Dict

from psycopg.rows import dict_row

from .config import get_settings
from .db import get_dict_conn
from .embeddings import embed_text, to_pgvector
from .models import SearchRequest


def run_hybrid_search(req: SearchRequest) -> dict[str, Any]:
    settings = get_settings()
    emb = to_pgvector(embed_text(req.query, provider=settings.embed_provider, dim=settings.embed_dim))
    filters = req.model_dump(exclude={"query"})
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ops.retrieval_runs(query_text, filters, query_embedding, retrieval_mode)
                VALUES (%s, %s::jsonb, %s::vector, 'hybrid')
                RETURNING run_id;
            """, (req.query, json.dumps(filters), emb))
            run_id = cur.fetchone()["run_id"]
            cur.execute("""
                SELECT * FROM ops.hybrid_search(
                  p_query => %(query)s,
                  p_query_embedding => %(embedding)s::vector,
                  p_source_systems => %(source_systems)s,
                  p_source_types => %(source_types)s,
                  p_statuses => %(statuses)s,
                  p_priorities => %(priorities)s,
                  p_project_key => %(project_key)s,
                  p_account_name => %(account_name)s,
                  p_component => %(component)s,
                  p_start_date => %(start_date)s::timestamptz,
                  p_end_date => %(end_date)s::timestamptz,
                  p_limit => %(limit)s
                )
            """, {
                "query": req.query,
                "embedding": emb,
                "source_systems": req.source_systems,
                "source_types": req.source_types,
                "statuses": req.statuses,
                "priorities": req.priorities,
                "project_key": req.project_key,
                "account_name": req.account_name,
                "component": req.component,
                "start_date": req.start_date,
                "end_date": req.end_date,
                "limit": req.limit,
            })
            rows = cur.fetchall()
            for r in rows:
                cur.execute("""
                    INSERT INTO ops.retrieval_candidates(
                      run_id, chunk_id, object_id, text_rank, vector_score, trigram_score, metadata_score,
                      recency_score, rrf_score, final_score, explanation
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT(run_id, chunk_id) DO NOTHING
                """, (
                    run_id, r["chunk_id"], r["object_id"], r["text_rank"], r["vector_score"],
                    r["trigram_score"], r["metadata_score"], r["recency_score"], r["rrf_score"],
                    r["final_score"], json.dumps(r["explanation"]),
                ))
    return {"run_id": str(run_id), "query": req.query, "results": rows}
