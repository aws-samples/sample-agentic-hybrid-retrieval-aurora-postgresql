from __future__ import annotations

import json
import logging
from typing import Any

from .db import get_dict_conn
from .models import RetrievalMode, SearchRequest
from .search import run_hybrid_search

logger = logging.getLogger(__name__)

DEFAULT_MODES: list[RetrievalMode] = [
    "hybrid",
    "semantic",
    "lexical",
    "fuzzy",
]


def _queries(evaluation_type: str) -> list[dict[str, Any]]:
    with get_dict_conn("analyst") as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT query_id, query_text, evaluation_type, filters, notes
                FROM proof.evaluation_queries
                WHERE evaluation_type = %s
                ORDER BY query_id
                """,
                (evaluation_type,),
            )
            return cursor.fetchall()


def _retrieval_run(
    query: dict[str, Any],
    mode: RetrievalMode,
    limit: int,
) -> str:
    filters = query["filters"] or {}
    result = run_hybrid_search(
        SearchRequest(
            query=query["query_text"],
            mode=mode,
            limit=limit,
            kinds=filters.get("kinds"),
            cluster_id=filters.get("cluster_id"),
            incident_id=filters.get("incident_id"),
            account_name=filters.get("account_name"),
            severities=filters.get("severities"),
            environment=filters.get("environment"),
            start_date=filters.get("start_date"),
            end_date=filters.get("end_date"),
            role="analyst",
            rerank=False,
        )
    )
    with get_dict_conn("analyst") as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE proof.retrieval_runs
                SET filters = filters || jsonb_build_object(
                  'evaluation_query_id', %s::text,
                  'evaluation_type', 'retrieval'
                )
                WHERE run_id = %s
                """,
                (query["query_id"], result["run_id"]),
            )
    return result["run_id"]


def _retrieval_metrics(query_id: str, run_id: str) -> dict[str, float]:
    with get_dict_conn("analyst") as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  proof.recall_at_k(%(query_id)s, %(run_id)s, 5) AS recall_at_5,
                  proof.recall_at_k(%(query_id)s, %(run_id)s, 10) AS recall_at_10,
                  proof.precision_at_k(%(query_id)s, %(run_id)s, 10) AS precision_at_10,
                  proof.mrr(%(query_id)s, %(run_id)s) AS mrr,
                  proof.ndcg_at_k(%(query_id)s, %(run_id)s, 10) AS ndcg_at_10
                """,
                {"query_id": query_id, "run_id": run_id},
            )
            row = cursor.fetchone()
    return {name: float(value or 0) for name, value in (row or {}).items()}


def _traversal_run(query: dict[str, Any], limit: int) -> tuple[str, int]:
    from .agent import follow_evidence_links_impl

    filters = query["filters"] or {}
    anchor = run_hybrid_search(
        SearchRequest(
            query=query["query_text"],
            mode="lexical",
            limit=min(limit, 10),
            role="analyst",
            rerank=False,
        )
    )
    run_id = anchor["run_id"]
    seed_keys = filters.get("seed_external_keys") or [
        row["external_key"] for row in anchor["results"][:1]
    ]
    traversal = follow_evidence_links_impl(
        seed_keys,
        role="analyst",
        max_depth=int(filters.get("max_depth") or 2),
    )

    with get_dict_conn("analyst") as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE proof.retrieval_runs
                    SET filters = filters || jsonb_build_object(
                      'evaluation_query_id', %s::text,
                      'evaluation_type', 'traversal',
                      'seed_external_keys', %s::jsonb
                    )
                    WHERE run_id = %s
                    """,
                    (query["query_id"], json.dumps(seed_keys), run_id),
                )
                cursor.executemany(
                    """
                    INSERT INTO proof.traversal_results(
                      run_id,
                      query_id,
                      evidence_id,
                      depth,
                      path,
                      via_edge_key,
                      via_relation,
                      via_origin,
                      via_confidence
                    )
                    VALUES (%s, %s, %s, %s, %s::uuid[], %s, %s, %s, %s)
                    ON CONFLICT (run_id, query_id, evidence_id) DO UPDATE SET
                      depth = EXCLUDED.depth,
                      path = EXCLUDED.path,
                      via_edge_key = EXCLUDED.via_edge_key,
                      via_relation = EXCLUDED.via_relation,
                      via_origin = EXCLUDED.via_origin,
                      via_confidence = EXCLUDED.via_confidence
                    """,
                    [
                        (
                            run_id,
                            query["query_id"],
                            row["evidence_id"],
                            row["depth"],
                            row["path"],
                            row.get("via_edge_key"),
                            row.get("via_relation"),
                            row.get("via_origin"),
                            row.get("via_confidence"),
                        )
                        for row in traversal["reached"]
                    ],
                )
                cursor.execute(
                    """
                    INSERT INTO proof.run_stages(
                      run_id, stage_ordinal, stage_name, duration_ms, details
                    )
                    SELECT
                      %s,
                      coalesce(max(stage_ordinal), 0) + 1,
                      'evaluate relationship traversal',
                      0,
                      %s::jsonb
                    FROM proof.run_stages
                    WHERE run_id = %s
                    """,
                    (
                        run_id,
                        json.dumps(
                            {
                                "query_id": query["query_id"],
                                "seed_external_keys": seed_keys,
                                "reached_count": len(traversal["reached"]),
                            }
                        ),
                        run_id,
                    ),
                )
    return run_id, len(traversal["reached"])


def _traversal_metrics(query_id: str, run_id: str) -> dict[str, float]:
    with get_dict_conn("analyst") as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  proof.traversal_recall(%s, %s) AS recall,
                  proof.traversal_precision(%s, %s) AS precision
                """,
                (query_id, run_id, query_id, run_id),
            )
            row = cursor.fetchone()
    return {name: float(value or 0) for name, value in (row or {}).items()}


def _run_retrieval_evaluation(
    selected: list[RetrievalMode],
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    queries = _queries("retrieval")
    per_query: list[dict[str, Any]] = []
    totals = {
        mode: {"ndcg_at_10": 0.0, "recall_at_10": 0.0, "mrr": 0.0}
        for mode in selected
    }
    successes = {mode: 0 for mode in selected}

    for query in queries:
        results: list[dict[str, Any]] = []
        for mode in selected:
            try:
                run_id = _retrieval_run(query, mode, limit)
                metrics = _retrieval_metrics(query["query_id"], run_id)
            except Exception as error:
                logger.warning(
                    "Evaluation failed query=%s mode=%s: %s",
                    query["query_id"],
                    mode,
                    error,
                )
                results.append({"mode": mode, "error": str(error)})
                continue
            successes[mode] += 1
            for key in totals[mode]:
                totals[mode][key] += metrics[key]
            results.append({"mode": mode, "run_id": run_id, "metrics": metrics})
        per_query.append(
            {
                "query_id": query["query_id"],
                "query_text": query["query_text"],
                "evaluation_type": "retrieval",
                "notes": query["notes"],
                "results": results,
            }
        )

    leaderboard = sorted(
        (
            {
                "mode": mode,
                "successful_runs": successes[mode],
                **{
                    key: round(value / successes[mode], 4)
                    if successes[mode]
                    else 0.0
                    for key, value in totals[mode].items()
                },
            }
            for mode in selected
        ),
        key=lambda row: (row["ndcg_at_10"], row["recall_at_10"]),
        reverse=True,
    )
    return per_query, leaderboard


def _run_traversal_evaluation(limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for query in _queries("traversal"):
        try:
            run_id, reached_count = _traversal_run(query, limit)
            metrics = _traversal_metrics(query["query_id"], run_id)
            result = {
                "run_id": run_id,
                "reached_count": reached_count,
                "metrics": metrics,
            }
        except Exception as error:
            logger.warning(
                "Traversal evaluation failed query=%s: %s",
                query["query_id"],
                error,
            )
            result = {"error": str(error)}
        results.append(
            {
                "query_id": query["query_id"],
                "query_text": query["query_text"],
                "evaluation_type": "traversal",
                "notes": query["notes"],
                "results": [result],
            }
        )
    return results


def run_evaluation(
    modes: list[RetrievalMode] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    selected = modes or DEFAULT_MODES
    retrieval_queries, leaderboard = _run_retrieval_evaluation(selected, limit)
    traversal_queries = _run_traversal_evaluation(limit)
    return {
        "query_count": len(retrieval_queries) + len(traversal_queries),
        "retrieval_query_count": len(retrieval_queries),
        "traversal_query_count": len(traversal_queries),
        "queries": [*retrieval_queries, *traversal_queries],
        "leaderboard": leaderboard,
        "metric_note": (
            "Top-k metrics score retrieval arms only. Relationship recall and "
            "precision score ACL-safe graph traversal separately."
        ),
        "_verify_sql": {
            "reproducible": False,
            "reason": (
                "harness aggregate, not run-bound: the leaderboard averages metric "
                "functions across a fresh run per query and mode, so it has no single "
                "run_id to replay. Re-run `make evaluate` (POST /v1/evaluation) to "
                "reproduce it; each per-query run_id is itself receipt-verifiable."
            ),
        },
    }
