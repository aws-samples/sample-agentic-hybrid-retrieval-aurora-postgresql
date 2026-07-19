"""Retrieval-quality evaluation: run each mode against judged queries and score.

For every evaluation query in ops.evaluation_queries, this fires one live retrieval
run per requested mode (hybrid / semantic / lexical / fuzzy) using the query's exact
text and stored filters, then reads back recall@k, precision@10, MRR, and nDCG@10
from the SQL metric functions (sql/09). Because each run persists with the eval
query's verbatim query_text, ops.v_eval_comparison links run to query and the modes
are scored side by side. Which mode wins depends on the query: lexical dominates
when the query names an exact identifier, semantic wins on paraphrase, and hybrid is
the robust default that never collapses on either. The point is to let a builder
read the tradeoff off real numbers, not to assert a fixed winner.
"""
from __future__ import annotations

import logging
from typing import Any

from .db import get_dict_conn
from .models import RetrievalMode, SearchRequest
from .search import run_hybrid_search

logger = logging.getLogger(__name__)

_DEFAULT_MODES: list[RetrievalMode] = ["hybrid", "semantic", "lexical", "fuzzy"]


def _evaluation_queries() -> list[dict[str, Any]]:
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT query_id, query_text, filters, notes FROM ops.evaluation_queries ORDER BY query_id"
            )
            return cur.fetchall()


def _run_for_mode(query_text: str, filters: dict[str, Any], mode: RetrievalMode, limit: int) -> str:
    """Fire one retrieval run for a mode and return its run_id.

    Uses the eval query's stored filters (source_systems / project_key / etc.) so
    the run matches how the query is meant to be answered. The run persists with the
    verbatim query_text, which is how ops.v_eval_comparison joins it to the query.
    """
    payload = {
        "query": query_text,
        "mode": mode,
        "limit": limit,
        "source_systems": filters.get("source_systems"),
        "source_types": filters.get("source_types"),
        "project_key": filters.get("project_key"),
        "account_name": filters.get("account_name"),
        "component": filters.get("component"),
    }
    req = SearchRequest(**{k: v for k, v in payload.items() if v is not None})
    result = run_hybrid_search(req)
    return result["run_id"]


def _metrics_for_run(query_id: str, run_id: str) -> dict[str, float]:
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  ops.recall_at_k(%(q)s, %(r)s, 5)    AS recall_at_5,
                  ops.recall_at_k(%(q)s, %(r)s, 10)   AS recall_at_10,
                  ops.precision_at_k(%(q)s, %(r)s, 10) AS precision_at_10,
                  ops.mrr(%(q)s, %(r)s)               AS mrr,
                  ops.ndcg_at_k(%(q)s, %(r)s, 10)     AS ndcg_at_10
                """,
                {"q": query_id, "r": run_id},
            )
            row = cur.fetchone() or {}
    return {k: (float(v) if v is not None else 0.0) for k, v in row.items()}


def run_evaluation(modes: list[RetrievalMode] | None = None, limit: int = 10) -> dict[str, Any]:
    """Evaluate each mode against every judged query and return per-mode metrics.

    Returns {queries: [{query_id, query_text, results: [{mode, run_id, metrics}]}],
    leaderboard: [{mode, ndcg_at_10, recall_at_10, mrr}]} where the leaderboard is
    the mean of each metric across queries, sorted by nDCG@10 descending.
    """
    modes = modes or _DEFAULT_MODES
    queries = _evaluation_queries()
    if not queries:
        return {"queries": [], "leaderboard": [], "note": "no evaluation queries seeded"}

    per_query: list[dict[str, Any]] = []
    mode_totals: dict[str, dict[str, float]] = {m: {"ndcg_at_10": 0.0, "recall_at_10": 0.0, "mrr": 0.0} for m in modes}

    for q in queries:
        filters = q.get("filters") or {}
        results: list[dict[str, Any]] = []
        for mode in modes:
            try:
                run_id = _run_for_mode(q["query_text"], filters, mode, limit)
                metrics = _metrics_for_run(q["query_id"], run_id)
            except Exception as exc:
                logger.warning("Evaluation run failed for query=%s mode=%s: %s", q["query_id"], mode, exc)
                continue
            results.append({"mode": mode, "run_id": run_id, "metrics": metrics})
            for key in mode_totals[mode]:
                mode_totals[mode][key] += metrics.get(key, 0.0)
        per_query.append({"query_id": q["query_id"], "query_text": q["query_text"], "results": results})

    n = len(queries)
    leaderboard = sorted(
        (
            {
                "mode": mode,
                "ndcg_at_10": round(totals["ndcg_at_10"] / n, 4),
                "recall_at_10": round(totals["recall_at_10"] / n, 4),
                "mrr": round(totals["mrr"] / n, 4),
            }
            for mode, totals in mode_totals.items()
        ),
        key=lambda row: row["ndcg_at_10"],
        reverse=True,
    )
    return {"queries": per_query, "leaderboard": leaderboard, "query_count": n}
