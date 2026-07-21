from __future__ import annotations
import json
import logging
from time import perf_counter
from typing import Any

from .config import get_settings
from .db import get_dict_conn
from .embeddings import embed_text, to_pgvector
from .models import SearchRequest
from .rerank import get_cohere_rerank_service

logger = logging.getLogger(__name__)

# The single-signal modes route to one ops.* function each. Every entry names the
# SQL function and whether that arm needs the query embedding (vector) or the raw
# query text (lexical/fuzzy). 'hybrid' is handled separately by ops.hybrid_search.
_SINGLE_SIGNAL_MODES = {"semantic", "lexical", "fuzzy"}


def _principal_json(req: SearchRequest) -> str | None:
    """Serialize the request principal for the SQL p_principal parameter.

    Returns None when no principal is set, so `%(principal)s::jsonb` binds
    NULL::jsonb and ops.acl_visible short-circuits to "no ACL filtering" — the
    default workshop audience sees every object. When a principal is present it is
    passed through verbatim as a jsonb object (e.g. {"clearances": [...]}).
    """
    return json.dumps(req.principal) if req.principal is not None else None


def _rerank_enabled(req: SearchRequest) -> bool:
    """Whether to run Cohere Rerank for this request.

    The per-request `rerank` toggle wins when set; otherwise fall back to the
    deployment default (COHERE_RERANK_ENABLED). Single-signal modes are meant to
    show ONE arm in isolation, so reranking is off for them unless a caller opts
    in explicitly — a reranked "semantic-only" result would muddy the teaching
    point that the vector arm alone misses the exact ORION-1489 lexical hit.
    """
    settings = get_settings()
    if req.rerank is not None:
        return req.rerank
    if req.mode in _SINGLE_SIGNAL_MODES:
        return False
    return settings.cohere_rerank_enabled


def _candidate_pool_limit(limit: int, rerank_on: bool) -> int:
    settings = get_settings()
    if not rerank_on:
        return limit
    expanded = limit * 3
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


def _apply_cohere_rerank(
    query: str, rows: list[dict[str, Any]], limit: int, rerank_on: bool
) -> tuple[list[dict[str, Any]], bool]:
    if not rerank_on or not rows:
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


def _normalize_single_signal(rows: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    """Lift compact single-signal rows into the shared candidate shape.

    ops.{vector,full_text,fuzzy}_search return one `score` column; the candidate
    persistence, the API contract, and the frontend all expect the fused shape
    (text_rank / vector_score / trigram_score / metadata_score / recency_score /
    rrf_score / final_score / explanation). Map the single arm's score into its own
    slot, zero the others, and use the score itself as final_score so ordering is
    preserved. This keeps ONE renderer for every mode.
    """
    signal_key = {"semantic": "vector_score", "lexical": "text_rank", "fuzzy": "trigram_score"}[mode]
    arm_label = {"semantic": "semantic", "lexical": "full_text", "fuzzy": "fuzzy"}[mode]
    normalized: list[dict[str, Any]] = []
    for r in rows:
        raw = r.get("score")
        score = float(raw) if raw is not None else 0.0
        row = dict(r)
        row.pop("score", None)
        for field in ("text_rank", "vector_score", "trigram_score", "metadata_score", "recency_score", "rrf_score"):
            row[field] = 0
        row[signal_key] = score
        row["final_score"] = score
        row["explanation"] = {
            "signals": {arm_label: score},
            "why": [f"Single-signal retrieval: {mode}-only arm, ranked by {arm_label} score alone"],
        }
        normalized.append(row)
    return normalized


def _run_single_signal(cur, req: SearchRequest, emb: str | None, limit: int) -> list[dict[str, Any]]:
    """Execute one ops.* single-signal function for the requested mode."""
    common = {
        "source_systems": req.source_systems,
        "source_types": req.source_types,
        "statuses": req.statuses,
        "priorities": req.priorities,
        "project_key": req.project_key,
        "account_name": req.account_name,
        "component": req.component,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "limit": limit,
        "principal": _principal_json(req),
    }
    filter_sql = """
        p_source_systems => %(source_systems)s,
        p_source_types => %(source_types)s,
        p_statuses => %(statuses)s,
        p_priorities => %(priorities)s,
        p_project_key => %(project_key)s,
        p_account_name => %(account_name)s,
        p_component => %(component)s,
        p_start_date => %(start_date)s::timestamptz,
        p_end_date => %(end_date)s::timestamptz,
        p_limit => %(limit)s::int,
        p_principal => %(principal)s::jsonb
    """
    if req.mode == "semantic":
        if emb is None:
            raise ValueError("semantic retrieval requires a query embedding")
        cur.execute(
            f"SELECT * FROM ops.vector_search(p_query_embedding => %(embedding)s::vector, {filter_sql})",
            {**common, "embedding": emb},
        )
    elif req.mode == "lexical":
        cur.execute(
            f"SELECT * FROM ops.full_text_search(p_query => %(query)s, {filter_sql})",
            {**common, "query": req.query},
        )
    else:  # fuzzy
        cur.execute(
            f"SELECT * FROM ops.fuzzy_match(p_query => %(query)s, p_threshold => %(threshold)s::numeric, {filter_sql})",
            {**common, "query": req.query, "threshold": req.fuzzy_threshold},
        )
    return _normalize_single_signal(cur.fetchall(), req.mode)


def _run_hybrid(cur, req: SearchRequest, emb: str, limit: int) -> list[dict[str, Any]]:
    """Execute the fused ops.hybrid_search with live RRF knobs."""
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
          p_limit => %(limit)s::int,
          p_rrf_k => %(rrf_k)s::int,
          p_w_text => %(w_text)s::numeric,
          p_w_vector => %(w_vector)s::numeric,
          p_w_trgm => %(w_trgm)s::numeric,
          p_principal => %(principal)s::jsonb
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
        "limit": limit,
        "rrf_k": req.rrf_k,
        "w_text": req.w_text,
        "w_vector": req.w_vector,
        "w_trgm": req.w_trgm,
        "principal": _principal_json(req),
    })
    return cur.fetchall()


def run_hybrid_search(req: SearchRequest) -> dict[str, Any]:
    """Run a retrieval and persist the run, its knobs, and its candidates.

    Routes by `req.mode`: 'hybrid' runs the fused weighted-RRF ranker; the
    single-signal modes ('semantic', 'lexical', 'fuzzy') run one ops.* arm so a
    builder can watch each signal in isolation. When `req.ef_search` is set, it is
    applied for the query via set_config inside an explicit transaction — SET LOCAL
    is a no-op under the autocommit connection this app uses.
    """
    settings = get_settings()
    timings: list[dict[str, Any]] = []

    emb: str | None = None
    if req.mode in {"hybrid", "semantic"}:
        embed_start = perf_counter()
        emb = to_pgvector(
            embed_text(req.query, provider=settings.embed_provider, dim=settings.embed_dim, input_type="search_query")
        )
        timings.append({"stage": "embed query", "ms": _elapsed_ms(embed_start)})

    rerank_on = _rerank_enabled(req)
    filters = req.model_dump(exclude={"query"})
    candidate_limit = _candidate_pool_limit(req.limit, rerank_on)

    # Read only. The ops.* search functions do not take a run_id, so the run row is
    # not created yet — deferring it to the write transaction lets the run,
    # candidates, and metrics commit as one atomic unit. ef_search is set with
    # set_config(is_local=true) inside a transaction so it scopes to this query;
    # the pooled connection is autocommit, where a bare SET LOCAL would be lost.
    search_start = perf_counter()
    with get_dict_conn() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                if req.ef_search is not None:
                    cur.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(req.ef_search),))
                if req.mode in _SINGLE_SIGNAL_MODES:
                    rows = _run_single_signal(cur, req, emb, candidate_limit)
                    search_label = f"{req.mode} retrieval"
                else:
                    if emb is None:
                        raise ValueError("hybrid retrieval requires a query embedding")
                    rows = _run_hybrid(cur, req, emb, candidate_limit)
                    search_label = "hybrid fusion · SQL"
    timings.append({"stage": search_label, "ms": _elapsed_ms(search_start)})

    # Rerank calls Bedrock over the network — done with no connection checked out
    # so a slow or throttled rerank never holds a pooled connection idle.
    fused_count = len(rows)
    rerank_start = perf_counter()
    rows, rerank_applied = _apply_cohere_rerank(req.query, rows, req.limit, rerank_on)
    if rerank_on:
        timings.append({"stage": "rerank · Cohere", "ms": _elapsed_ms(rerank_start)})
    retrieval_mode = _retrieval_mode_label(req.mode, rerank_applied, rerank_on)
    funnel = _build_funnel(req, fused_count, candidate_limit, rows)

    # Single write transaction: the run row, its candidates, and its metrics commit
    # together or not at all. A half-run (run row with no candidates, or candidates
    # with no metrics) can no longer be left behind by a mid-write failure. Metrics
    # persist under a nested SAVEPOINT, so a not-yet-provisioned metrics table rolls
    # back only that statement while run + candidates still commit.
    persist_start = perf_counter()
    run_id = _persist_run(
        req,
        rows,
        emb=emb,
        filters=filters,
        retrieval_mode=retrieval_mode,
        rerank_applied=rerank_applied,
        funnel=funnel,
        timings=timings,
        persist_start=persist_start,
    )

    total_latency_ms = sum(int(t["ms"]) for t in timings)
    return {
        "run_id": str(run_id),
        "query": req.query,
        "mode": req.mode,
        "retrieval_mode": retrieval_mode,
        "knobs": {
            "rrf_k": req.rrf_k,
            "weights": {"text": req.w_text, "vector": req.w_vector, "trgm": req.w_trgm},
            "ef_search": req.ef_search,
            "rerank": rerank_applied,
        },
        "funnel": funnel,
        "stage_timings": timings,
        "total_latency_ms": total_latency_ms,
        "results": rows,
    }


def _elapsed_ms(start: float) -> int:
    """Whole milliseconds elapsed since `start` (perf_counter), floored at 0."""
    return max(0, round((perf_counter() - start) * 1000))


def _build_funnel(
    req: SearchRequest, fused_count: int, candidate_limit: int, final_rows: list[dict[str, Any]]
) -> dict[str, int]:
    """Derive an honest candidate funnel from real per-run counts.

    Every stage is a count this run actually produced, monotonically narrowing:
      fetched   — candidate pool the ranker was asked to fill (candidate_limit)
      deduped   — distinct chunks the retrieval returned (fused_count)
      fused     — same set after fusion/ordering (fused_count)
      above_cut — rows that survived the rerank/limit cut (len(final_rows))
      cited     — rows the answer will cite (min(limit, above_cut))
    No stage is fabricated. There is no separate dedup pass (one chunk per object
    in this corpus), so deduped == fused by construction — reported equal rather
    than invented. When fewer candidates match than the pool requested,
    deduped < fetched, which is the real narrowing, not a staged number.
    """
    above_cut = len(final_rows)
    cited = min(req.limit, above_cut)
    return {
        "fetched": max(fused_count, candidate_limit),
        "deduped": fused_count,
        "fused": fused_count,
        "above_cut": above_cut,
        "cited": cited,
    }


def _retrieval_mode_label(mode: str, rerank_applied: bool, rerank_on: bool) -> str:
    """The retrieval_mode string persisted on the run, e.g. 'hybrid+cohere-rerank'."""
    if rerank_applied:
        return f"{mode}+cohere-rerank"
    if rerank_on:
        return f"{mode}+cohere-rerank-fallback"
    return mode


_CANDIDATE_INSERT = """
    INSERT INTO ops.retrieval_candidates(
      run_id, chunk_id, object_id, text_rank, vector_score, trigram_score, metadata_score,
      recency_score, rrf_score, rerank_score, final_score, explanation
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
    ON CONFLICT(run_id, chunk_id) DO NOTHING
"""

_RUN_INSERT = """
    INSERT INTO ops.retrieval_runs(query_text, filters, query_embedding, principal, retrieval_mode)
    VALUES (%s, %s::jsonb, %s::vector, %s::jsonb, %s)
    RETURNING run_id;
"""


def _persist_run(
    req: SearchRequest,
    rows: list[dict[str, Any]],
    *,
    emb: str | None,
    filters: dict[str, Any],
    retrieval_mode: str,
    rerank_applied: bool,
    funnel: dict[str, int],
    timings: list[dict[str, Any]],
    persist_start: float,
) -> Any:
    """Persist the run row, its candidates, and its metrics in one transaction.

    Returns the new run_id. The run row and every candidate commit atomically, so a
    mid-write failure can never leave a run with no candidates. The metrics INSERT
    runs under a nested SAVEPOINT (see _persist_metrics): if that table is not
    provisioned yet, only the metrics statement rolls back while the run and its
    candidates still commit. The run row is written with the final retrieval_mode
    label directly, so no follow-up UPDATE is needed.
    """
    with get_dict_conn() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    _RUN_INSERT,
                    (req.query, json.dumps(filters), emb, json.dumps(req.principal or {}), retrieval_mode),
                )
                run_id = cur.fetchone()["run_id"]
                for r in rows:
                    cur.execute(_CANDIDATE_INSERT, (
                        run_id, r["chunk_id"], r["object_id"], r["text_rank"], r["vector_score"],
                        r["trigram_score"], r["metadata_score"], r["recency_score"], r["rrf_score"],
                        r.get("rerank_score"), r["final_score"], json.dumps(r["explanation"]),
                    ))
                timings.append({"stage": "persist run · candidates", "ms": _elapsed_ms(persist_start)})
                total_latency_ms = sum(int(t["ms"]) for t in timings)
                _persist_metrics(conn, cur, run_id, req, rerank_applied, funnel, timings, total_latency_ms)
    return run_id


def _persist_metrics(
    conn,
    cur,
    run_id,
    req: SearchRequest,
    rerank_applied: bool,
    funnel: dict[str, int],
    stage_timings: list[dict[str, Any]],
    total_latency_ms: int,
) -> None:
    """Persist the live knob values, funnel, and stage timings on retrieval_run_metrics.

    Records the RRF k, ranker weights, rerank flag, the measured per-stage latency,
    the total latency, and the real candidate funnel this run produced, so the
    Diagnostics view reports the live run instead of the seeded defaults or zeros.
    Metrics is additive: if the table is absent (schema not migrated), the write
    is wrapped in a SAVEPOINT so a failure rolls back only this statement and the
    candidate INSERTs in the same transaction still commit.
    """
    try:
        with conn.transaction():
            cur.execute("""
            INSERT INTO ops.retrieval_run_metrics(
              run_id, profile, embedding_model, embedding_dim, index_spec, fired_at,
              total_latency_ms, p50_latency_ms, rrf_k, ranker_weights, rerank_cut,
              reranked_count, funnel, stage_timings, metadata
            ) VALUES (
              %(run_id)s, %(profile)s, %(embedding_model)s, %(embedding_dim)s, %(index_spec)s, now(),
              %(total_latency_ms)s, %(p50_latency_ms)s, %(rrf_k)s, %(ranker_weights)s, %(rerank_cut)s,
              %(reranked_count)s, %(funnel)s::jsonb, %(stage_timings)s::jsonb, %(metadata)s::jsonb
            )
            ON CONFLICT (run_id) DO UPDATE SET
              total_latency_ms = EXCLUDED.total_latency_ms,
              p50_latency_ms = EXCLUDED.p50_latency_ms,
              rrf_k = EXCLUDED.rrf_k,
              ranker_weights = EXCLUDED.ranker_weights,
              reranked_count = EXCLUDED.reranked_count,
              funnel = EXCLUDED.funnel,
              stage_timings = EXCLUDED.stage_timings,
              metadata = EXCLUDED.metadata
        """, {
            "run_id": run_id,
            "profile": f"live-{req.mode}",
            "embedding_model": get_settings().bedrock_embedding_model,
            "embedding_dim": get_settings().embed_dim,
            "index_spec": _index_spec(req.ef_search),
            "total_latency_ms": total_latency_ms,
            "p50_latency_ms": total_latency_ms,
            "rrf_k": req.rrf_k,
            "ranker_weights": [req.w_text, req.w_vector, req.w_trgm],
            "rerank_cut": 0.0,
            "reranked_count": req.limit if rerank_applied else 0,
            "funnel": json.dumps(funnel),
            "stage_timings": json.dumps(stage_timings),
            "metadata": json.dumps({"mode": req.mode, "ef_search": req.ef_search, "live": True}),
        })
    except Exception as exc:
        logger.warning("Skipping run-metrics persistence (table unavailable?): %s", exc)


def _index_spec(ef_search: int | None) -> str:
    base = "HNSW m=16 ef_construction=64"
    return f"{base} ef_search={ef_search}" if ef_search is not None else base
