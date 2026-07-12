from __future__ import annotations
import json
import logging
from typing import Any, Dict

from .config import get_settings
from .db import get_dict_conn
from .embeddings import embed_text, to_pgvector
from .models import SearchRequest
from .rerank import get_cohere_rerank_service

logger = logging.getLogger(__name__)


def _candidate_pool_limit(limit: int) -> int:
    settings = get_settings()
    if not settings.cohere_rerank_enabled:
        return limit
    expanded = max(limit, limit * 3)
    bounded = min(expanded, settings.cohere_rerank_max_documents)
    return max(limit, bounded)


def _candidate_document(row: dict[str, Any]) -> str:
    parts = [
        f"Source: {row.get('source_system')} {row.get('source_type') or ''}".strip(),
        f"External ID: {row.get('external_id')}",
        f"Title: {row.get('title')}",
        f"Status: {row.get('status')}" if row.get("status") else "",
        f"Priority: {row.get('priority')}" if row.get("priority") else "",
        f"Account: {row.get('account_name')}" if row.get("account_name") else "",
        f"Project: {row.get('project_key')}" if row.get("project_key") else "",
        f"Component: {row.get('component')}" if row.get("component") else "",
        f"Evidence: {row.get('snippet')}",
    ]
    return "\n".join(part for part in parts if part)[:4000]


def _with_rerank_signal(row: dict[str, Any], rerank_score: float) -> dict[str, Any]:
    updated = dict(row)
    updated["rerank_score"] = rerank_score
    explanation = dict(updated.get("explanation") or {})
    signals = dict(explanation.get("signals") or {})
    signals["rerank"] = rerank_score
    why = list(explanation.get("why") or [])
    note = "Reranked by Cohere Rerank v3.5 via Amazon Bedrock after Aurora SQL fusion."
    if note not in why:
        why.append(note)
    explanation["signals"] = signals
    explanation["why"] = why
    updated["explanation"] = explanation
    return updated


def _apply_cohere_rerank(query: str, rows: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], bool]:
    settings = get_settings()
    if not settings.cohere_rerank_enabled or not rows:
        return rows[:limit], False

    documents = [_candidate_document(row) for row in rows]
    try:
        reranked = get_cohere_rerank_service().rerank(query, documents, top_n=limit)
    except Exception as exc:
        logger.warning("Cohere Rerank client unavailable; falling back to Aurora SQL order: %s", exc)
        return rows[:limit], False
    if not reranked:
        return rows[:limit], False

    selected_indexes: set[int] = set()
    ordered: list[dict[str, Any]] = []
    for item in reranked:
        index = item.get("index")
        if not isinstance(index, int) or index < 0 or index >= len(rows) or index in selected_indexes:
            continue
        selected_indexes.add(index)
        ordered.append(_with_rerank_signal(rows[index], float(item.get("relevance_score") or 0.0)))

    if not ordered:
        return rows[:limit], False

    # If Cohere returns fewer than requested, fill the tail in Aurora SQL order.
    ordered.extend(row for index, row in enumerate(rows) if index not in selected_indexes)
    return ordered[:limit], True


def run_hybrid_search(req: SearchRequest) -> dict[str, Any]:
    settings = get_settings()
    emb = to_pgvector(embed_text(req.query, provider=settings.embed_provider, dim=settings.embed_dim, input_type="search_query"))
    filters = req.model_dump(exclude={"query"})
    candidate_limit = _candidate_pool_limit(req.limit)
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
                "limit": candidate_limit,
            })
            rows = cur.fetchall()
    rows, rerank_applied = _apply_cohere_rerank(req.query, rows, req.limit)
    retrieval_mode = (
        "hybrid+cohere-rerank"
        if rerank_applied
        else "hybrid+cohere-rerank-fallback"
        if settings.cohere_rerank_enabled
        else "hybrid"
    )
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ops.retrieval_runs SET retrieval_mode = %s WHERE run_id = %s",
                (retrieval_mode, run_id),
            )
            for r in rows:
                cur.execute("""
                    INSERT INTO ops.retrieval_candidates(
                      run_id, chunk_id, object_id, text_rank, vector_score, trigram_score, metadata_score,
                      recency_score, rrf_score, rerank_score, final_score, explanation
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT(run_id, chunk_id) DO NOTHING
                """, (
                    run_id, r["chunk_id"], r["object_id"], r["text_rank"], r["vector_score"],
                    r["trigram_score"], r["metadata_score"], r["recency_score"], r["rrf_score"],
                    r.get("rerank_score"), r["final_score"], json.dumps(r["explanation"]),
                ))
    return {"run_id": str(run_id), "query": req.query, "retrieval_mode": retrieval_mode, "results": rows}
