#!/usr/bin/env python3
"""Measure what each retrieval stage contributes, without spending rerank calls.

Lab 2 teaches Retrieve -> Rank -> Reason. `data/evals/canonical_scorecard.json`
proves the served path (RRF fusion + managed reranking) meets a quality floor,
but a single number cannot show a participant *why*: how much of that quality
came from fusing three retrievers versus from reranking the fused pool.

Three arms, over the same 20 scored canonical queries and the same judgments
`scripts/score_evals.py` already uses:

    1. semantic_only       -- `mosaic_search.search_vector`, no fusion, no rerank
    2. rrf_fused_no_rerank -- the served fusion function, reranking off
    3. rrf_fused_reranked  -- the current production path

Arm 3 is never re-served. Managed reranking costs money per call, and
`benchmarks/results/canonical_served_results.csv` already carries the exact
ranked output of the last reviewed production run. This script loads that CSV,
recomputes its metrics with the same `scripts.evaluate.evaluate`, and asserts
the result equals `data/evals/canonical_scorecard.json.metrics` to full float
precision. A mismatch means the CSV or the committed scorecard no longer
describes the same measurement, and this script stops rather than publish a
number it cannot back.

Arms 1 and 2 call Aurora directly through `mosaic_search.search_vector` and
the same fusion SQL `service.retrieval.RetrievalService` serves, bypassing
`RetrievalService.search()` so no `mosaic.search_event` row is written --
this script only ever issues `SELECT`s. Each query is embedded once (cached by
`RetrievalService._embed_query`) and shared between arms 1 and 2.

`candidate_recall_ceiling` answers a different question than any arm's
Recall@10: of the judged-relevant products, how many did the *fused* pool
(arm 2's full candidate list, before it is cut to the top 10 shown to a
participant) contain at all? Reranking only ever reorders that pool -- it
never adds a candidate -- so this is the ceiling reranking could reach. Both
arm 2 and arm 3's top-10 are drawn from this same pool, so the ceiling bounds
their Recall@10 by construction. It does not bound arm 1, which retrieves
independently of fusion; the assembled artifact records where arm 1 sits
against the ceiling rather than assuming the relationship.
"""

from __future__ import annotations

import csv
import json
import re
import statistics
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.eval_contract import load_evaluation_queries
from scripts.evaluate import evaluate, load_judgments
from scripts.retrieval_profile import explain
from scripts.score_evals import (
    product_retrieval_queries,
    query_set_sha256,
    scored_query_set_sha256,
)
from service.config import get_settings
from service.models import SearchFilters, SearchRequest
from service.retrieval import RetrievalService, get_retrieval_service, normalize_query
from service.retrieval_fingerprint import compute_retrieval_fingerprint

K = 10
CANONICAL_QUERIES_PATH = REPO / "data" / "evals" / "canonical_queries.jsonl"
SERVED_RESULTS_PATH = REPO / "benchmarks" / "results" / "canonical_served_results.csv"
CANONICAL_SCORECARD_PATH = REPO / "data" / "evals" / "canonical_scorecard.json"
ABLATION_PATH = REPO / "data" / "evals" / "canonical_stage_ablation.json"

ARM_SEMANTIC_ONLY = "semantic_only"
ARM_RRF_FUSED = "rrf_fused_no_rerank"
ARM_RRF_RERANKED = "rrf_fused_reranked"

ARM_LABELS: dict[str, str] = {
    ARM_SEMANTIC_ONLY: "Semantic only",
    ARM_RRF_FUSED: "RRF fused, reranking off",
    ARM_RRF_RERANKED: "RRF fused + managed reranking (served path)",
}

ARM_DESCRIPTIONS: dict[str, str] = {
    ARM_SEMANTIC_ONLY: (
        "mosaic_search.search_vector alone: dense cosine ranking over the "
        "product embedding, with no lexical or trigram arm and no fusion."
    ),
    ARM_RRF_FUSED: (
        "The served fusion function (unweighted reciprocal rank fusion over "
        "FTS, trigram, and semantic candidates), with managed reranking "
        "disabled so the fused order is returned unchanged."
    ),
    ARM_RRF_RERANKED: (
        "The production path: the same fused pool as rrf_fused_no_rerank, "
        "reordered by managed reranking. Recomputed from "
        "benchmarks/results/canonical_served_results.csv rather than "
        "re-served, so this measurement spends no reranker calls."
    ),
}

FULL_GIT_SHA = re.compile(r"[0-9a-f]{40}")

#: Owner-specified honesty framing for the UI: 20 queries and 74 judgments
#: cannot separate small differences between arms. Carried on the artifact
#: itself, not typed fresh into the UI, so the caveat travels with the numbers
#: it qualifies rather than living only in a component that could drift from
#: the measurement it describes.
SPREAD_NOTE = (
    "20 queries and 74 judgments cannot separate small differences between "
    "arms. Read every mean alongside its own per-query minimum, maximum, and "
    "standard deviation, and treat a mean difference smaller than that "
    "spread as within noise rather than as a proven improvement."
)


class AblationMeasurementError(RuntimeError):
    """Refuses to publish an ablation artifact that cannot be trusted."""


def _require_clean_source(settings: Any) -> None:
    """Fail before any Aurora or model work when source provenance is not
    immutable. Deliberately duplicated from
    `scripts.score_evals._validate_measurement_source` rather than imported:
    that name is private to its module, and this measurement's provenance
    contract should not depend on that module's internals staying stable."""
    if settings.source_worktree_dirty:
        raise AblationMeasurementError(
            explain(
                "the worktree is dirty",
                "commit or remove the current worktree changes before "
                "measuring the stage ablation",
            )
        )
    if not FULL_GIT_SHA.fullmatch(settings.source_revision):
        raise AblationMeasurementError(
            explain(
                f"source revision {settings.source_revision!r} is not a full "
                "40-character Git SHA",
                "set MOSAIC_SOURCE_REVISION or run from a Git checkout",
            )
        )


def relevant_ids(judgments: dict[int, int]) -> set[int]:
    """Judged-relevant product ids for one query, grade >= 2, matching the
    threshold `scripts.evaluate.evaluate` uses for Recall."""
    return {product_id for product_id, grade in judgments.items() if grade >= 2}


def load_served_arm(
    path: Path,
    query_ids: set[str],
) -> dict[str, list[tuple[int, int]]]:
    """Rebuild the production arm's ranked results from the persisted CSV.

    No Cohere rerank call: this is the exact ranked output of the last
    reviewed `scripts/score_evals.py` run, filtered to the scored
    product_retrieval population.
    """
    ranked: dict[str, list[tuple[int, int]]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["query_id"] not in query_ids:
                continue
            ranked[row["query_id"]].append((int(row["rank"]), int(row["product_id"])))
    missing = query_ids - set(ranked)
    if missing:
        raise AblationMeasurementError(
            explain(
                f"{path} has no served rows for {sorted(missing)}",
                "rerun scripts/score_evals.py --write-baseline so the served "
                "results cover every currently scored query before measuring "
                "the ablation",
            )
        )
    return dict(ranked)


def semantic_only_arm(
    retrieval: RetrievalService,
    queries: list[dict[str, Any]],
) -> dict[str, list[tuple[int, int]]]:
    """Rank every candidate `mosaic_search.search_vector` alone can find.

    Uses the same `semantic_limit` as the served semantic channel, so this is
    the identical dense ranking fusion draws from -- just never fused, never
    reranked. `evaluate()` trims to the top K itself, so the full ranked list
    is kept rather than pre-truncated.
    """
    profile = retrieval._profile(SearchRequest(query="ablation profile", limit=K))
    ranked: dict[str, list[tuple[int, int]]] = {}
    for query in queries:
        normalized = normalize_query(query["query"])
        embedding = retrieval._embed_query(normalized)
        filters = SearchFilters.model_validate(query.get("filters") or {}).as_sql_json()
        with retrieval.connection_factory() as connection:
            retrieval._configure_hnsw(connection, profile)
            rows = connection.execute(
                """
                SELECT product_id, semantic_rank
                FROM mosaic_search.search_vector(
                    %(embedding)s::vector, %(filters)s::jsonb, %(limit)s::integer
                )
                ORDER BY semantic_rank
                """,
                {
                    "embedding": np.asarray(embedding, dtype=np.float32),
                    "filters": json.dumps(filters),
                    "limit": profile.semantic_limit,
                },
            ).fetchall()
        ranked[query["query_id"]] = [
            (int(row["semantic_rank"]), int(row["product_id"])) for row in rows
        ]
    return ranked


def rrf_fused_arm(
    retrieval: RetrievalService,
    queries: list[dict[str, Any]],
) -> tuple[dict[str, list[tuple[int, int]]], dict[str, list[int]]]:
    """Rank the served fusion function's full candidate pool, reranking off.

    Returns the top-K ranked mapping `evaluate()` expects, plus every
    query's full fused pool (<= `fusion.fused_limit` product ids, in the
    fused order) for the candidate-recall ceiling. Calls the exact SQL
    `service.retrieval.RetrievalService.search` runs before reranking --
    `_fusion_sql`/`_fusion_parameters` -- against a bare connection, so no
    `mosaic.search_event` row is written and no reranker call happens.
    """
    profile = retrieval._profile(SearchRequest(query="ablation profile", limit=K))
    ranked: dict[str, list[tuple[int, int]]] = {}
    pools: dict[str, list[int]] = {}
    for query in queries:
        normalized = normalize_query(query["query"])
        embedding = retrieval._embed_query(normalized)
        filters = SearchFilters.model_validate(query.get("filters") or {}).as_sql_json()
        with retrieval.connection_factory() as connection:
            retrieval._configure_hnsw(connection, profile)
            rows = connection.execute(
                retrieval._fusion_sql(),
                retrieval._fusion_parameters(normalized, embedding, filters, profile),
            ).fetchall()
        pool_ids = [int(row["product_id"]) for row in rows]
        pools[query["query_id"]] = pool_ids
        ranked[query["query_id"]] = list(enumerate(pool_ids, 1))
    return ranked, pools


def candidate_recall_ceiling(
    pools: dict[str, list[int]],
    truth: dict[str, dict[int, int]],
) -> dict[str, Any]:
    """How many judged-relevant products the fused pool contained at all.

    The ceiling reranking could ever reach: reranking only reorders the fused
    pool, it never adds a candidate absent from it.
    """
    per_query: list[dict[str, Any]] = []
    for query_id, judgments in truth.items():
        relevant = relevant_ids(judgments)
        pool = set(pools.get(query_id, []))
        found = relevant & pool
        missed = sorted(relevant - pool)
        per_query.append(
            {
                "query_id": query_id,
                "relevant_count": len(relevant),
                "found_in_pool": len(found),
                "missed_product_ids": missed,
                "pool_recall": len(found) / max(1, len(relevant)),
            }
        )
    if not per_query:
        raise AblationMeasurementError(
            explain("no queries were scored for the ceiling", "check the query set")
        )
    return {
        "pool_recall_ceiling": (
            sum(row["pool_recall"] for row in per_query) / len(per_query)
        ),
        "judged_relevant_never_fetched": sum(
            len(row["missed_product_ids"]) for row in per_query
        ),
        "per_query": per_query,
    }


def _spread(values: list[float]) -> dict[str, float]:
    """Min, max, and **sample** standard deviation (n-1) across the 20 queries.

    Sample, not population: the 20 canonical queries are themselves a small
    sample drawn to exercise teaching concepts, not the full space of queries
    a participant might type, so the spread of *this* sample is reported with
    the usual n-1 correction rather than treated as the whole population.
    """
    return {
        "min": min(values),
        "max": max(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
    }


def _win_counts(
    per_query_ndcg: dict[str, dict[str, float]],
    query_ids: list[str],
) -> dict[str, int]:
    """How many of the 20 queries each arm wins on nDCG@10, ties counted for
    every arm that reaches the query's maximum."""
    wins = {arm: 0 for arm in ARM_LABELS}
    for query_id in query_ids:
        values = per_query_ndcg[query_id]
        best = max(values.values())
        for arm, value in values.items():
            if value == best:
                wins[arm] += 1
    return wins


def assert_reproduces_committed_metrics(
    measured: dict[str, float],
    committed: dict[str, float],
    *,
    served_results_path: Path = SERVED_RESULTS_PATH,
    scorecard_path: Path = CANONICAL_SCORECARD_PATH,
) -> None:
    """Stop rather than publish an arm 3 that disagrees with what shipped.

    `committed` is `data/evals/canonical_scorecard.json["metrics"]`; `measured`
    is the same three keys recomputed from
    `benchmarks/results/canonical_served_results.csv` by the identical
    `scripts.evaluate.evaluate`. Equality must be exact float-for-float: both
    sides run the same pure function over what should be the same inputs, so
    anything short of equality means the CSV and the committed scorecard no
    longer describe the same measurement.
    """
    if measured != committed:
        raise AblationMeasurementError(
            explain(
                f"arm 3 recomputed from {served_results_path} as {measured}",
                f"expected an exact match to {scorecard_path}'s {committed}; "
                "this means the served-results CSV or the committed "
                "scorecard no longer describes the same measurement -- stop "
                "and inspect before trusting any arm in this artifact",
            )
        )


def assert_ceiling_covers_every_arm(
    ceiling_recall: float,
    arm_recalls: dict[str, float],
) -> None:
    """A pool-recall ceiling below any arm's Recall@10 is a bug, not a finding.

    Every arm's top-K is drawn from a candidate set no larger than the fused
    pool this ceiling is computed over (`rrf_fused_no_rerank` and
    `rrf_fused_reranked` directly; `semantic_only` because it draws from the
    same `search_vector` call the fused pool's semantic channel makes, at the
    same candidate limit). A ceiling strictly below a measured Recall@10 is
    arithmetically impossible under that construction, so it signals the pool
    accounting -- not the retrieval quality -- is wrong.
    """
    violations = {
        arm: recall for arm, recall in arm_recalls.items() if recall > ceiling_recall
    }
    if violations:
        raise AblationMeasurementError(
            explain(
                f"candidate-recall ceiling {ceiling_recall} is below Recall@{K} "
                f"for {violations}",
                "the ceiling must be computed over a superset of every arm's "
                "candidate pool; fix the pool accounting rather than the "
                "measured recall",
            )
        )


def _display_path(path: Path) -> str:
    """Repo-relative path when possible, so the artifact stays portable
    across checkouts; falls back to the absolute path for a test fixture
    living outside the repository tree."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def _arm_metrics(
    ranked: dict[str, list[tuple[int, int]]],
    truth: dict[str, dict[int, int]],
) -> dict[str, Any]:
    metrics = evaluate(truth, ranked, K)
    ndcg_values = [row[f"ndcg@{K}"] for row in metrics["per_query"]]
    return {
        "metrics": metrics,
        "ndcg_spread": _spread(ndcg_values),
        "per_query_ndcg": {
            row["query_id"]: row[f"ndcg@{K}"] for row in metrics["per_query"]
        },
    }


def measured_ablation() -> dict[str, Any]:
    """Measure all three arms and assemble the ablation artifact."""
    settings = get_settings()
    _require_clean_source(settings)

    canonical_queries = load_evaluation_queries(CANONICAL_QUERIES_PATH)
    queries, _excluded = product_retrieval_queries(canonical_queries)
    query_ids = {query["query_id"] for query in queries}
    all_judgments = load_judgments(CANONICAL_QUERIES_PATH)
    truth = {
        query_id: all_judgments[query_id]
        for query_id in (q["query_id"] for q in queries)
    }

    committed_scorecard = json.loads(
        CANONICAL_SCORECARD_PATH.read_text(encoding="utf-8")
    )
    served_ranked = load_served_arm(SERVED_RESULTS_PATH, query_ids)
    served_result = _arm_metrics(served_ranked, truth)
    committed_metrics = committed_scorecard["metrics"]
    measured_metrics = {
        f"recall@{K}": served_result["metrics"][f"recall@{K}"],
        "mrr": served_result["metrics"]["mrr"],
        f"ndcg@{K}": served_result["metrics"][f"ndcg@{K}"],
    }
    assert_reproduces_committed_metrics(measured_metrics, committed_metrics)

    retrieval = get_retrieval_service()
    semantic_ranked = semantic_only_arm(retrieval, queries)
    semantic_result = _arm_metrics(semantic_ranked, truth)
    fused_ranked, fused_pools = rrf_fused_arm(retrieval, queries)
    fused_result = _arm_metrics(fused_ranked, truth)
    ceiling = candidate_recall_ceiling(fused_pools, truth)

    arm_results = {
        ARM_SEMANTIC_ONLY: semantic_result,
        ARM_RRF_FUSED: fused_result,
        ARM_RRF_RERANKED: served_result,
    }
    assert_ceiling_covers_every_arm(
        ceiling["pool_recall_ceiling"],
        {arm: result["metrics"][f"recall@{K}"] for arm, result in arm_results.items()},
    )
    per_query_ndcg = {
        query_id: {
            arm: result["per_query_ndcg"][query_id]
            for arm, result in arm_results.items()
        }
        for query_id in query_ids
    }
    wins = _win_counts(per_query_ndcg, sorted(query_ids))

    arms_payload = {
        arm: {
            "label": ARM_LABELS[arm],
            "description": ARM_DESCRIPTIONS[arm],
            f"recall@{K}": result["metrics"][f"recall@{K}"],
            "mrr": result["metrics"]["mrr"],
            f"ndcg@{K}": result["metrics"][f"ndcg@{K}"],
            f"ndcg@{K}_min": result["ndcg_spread"]["min"],
            f"ndcg@{K}_max": result["ndcg_spread"]["max"],
            f"ndcg@{K}_stdev": result["ndcg_spread"]["stdev"],
            f"ndcg@{K}_query_wins": wins[arm],
        }
        for arm, result in arm_results.items()
    }

    per_query_payload = []
    by_query_id = {query["query_id"]: query for query in canonical_queries}
    for query_id in sorted(query_ids):
        query = by_query_id[query_id]
        ceiling_row = next(
            row for row in ceiling["per_query"] if row["query_id"] == query_id
        )
        per_query_payload.append(
            {
                "query_id": query_id,
                "query_text": query["query"],
                f"ndcg@{K}": {arm: per_query_ndcg[query_id][arm] for arm in ARM_LABELS},
                "pool_recall": ceiling_row["pool_recall"],
                "relevant_count": ceiling_row["relevant_count"],
                "found_in_pool": ceiling_row["found_in_pool"],
                "missed_product_ids": ceiling_row["missed_product_ids"],
            }
        )

    return {
        "measured_at": datetime.now(UTC).isoformat(),
        "retrieval_fingerprint": compute_retrieval_fingerprint(),
        "source": {
            "revision": settings.source_revision,
            "worktree_dirty": settings.source_worktree_dirty,
        },
        "models": {
            "embedding": settings.embedding_model_id,
            "rerank": settings.rerank_model_id,
        },
        "k": K,
        "query_set": _display_path(CANONICAL_QUERIES_PATH),
        "query_set_sha256": query_set_sha256(CANONICAL_QUERIES_PATH),
        "scored_query_set_sha256": scored_query_set_sha256(queries),
        "scored_query_count": len(queries),
        "served_scorecard_reference": {
            "path": _display_path(CANONICAL_SCORECARD_PATH),
            "measured_at": committed_scorecard["measured_at"],
            "source_revision": committed_scorecard["source"]["revision"],
            "retrieval_fingerprint": committed_scorecard["retrieval_fingerprint"],
        },
        "spread_note": SPREAD_NOTE,
        "arms": arms_payload,
        "candidate_recall_ceiling": {
            "pool_recall_ceiling": ceiling["pool_recall_ceiling"],
            "judged_relevant_never_fetched": ceiling["judged_relevant_never_fetched"],
            "description": (
                "Share of judged-relevant products present anywhere in the "
                "fused candidate pool before reranking, averaged over the "
                "scored queries. The ceiling reranking could ever reach: "
                "reranking only reorders this pool, it never adds a "
                "candidate absent from it."
            ),
        },
        "per_query": per_query_payload,
    }


def main() -> None:
    measured = measured_ablation()
    ABLATION_PATH.write_text(
        json.dumps(measured, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {ABLATION_PATH}")
    print(json.dumps(measured, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
