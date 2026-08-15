#!/usr/bin/env python3
"""Measure the served Mosaic retrieval path against graded canonical judgments."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.eval_contract import load_evaluation_queries
from scripts.evaluate import evaluate, load_judgments
from scripts.run_eval import validate_query_contract
from service.config import get_settings
from service.db import connect
from service.models import SearchFilters, SearchRequest
from service.retrieval import get_retrieval_service

PRODUCT_RETRIEVAL_SCOPE = "product_retrieval"
AGENT_CONTRACT_SCOPE = "agent_contract"


def query_set_sha256(path: Path) -> str:
    """Return the identity of the judgments used to establish a scorecard."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def product_retrieval_queries(
    queries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep tool-orchestration cases out of single-request retrieval metrics."""
    scored: list[dict[str, Any]] = []
    excluded: list[str] = []
    for query in queries:
        scope = query.get("evaluation_scope", PRODUCT_RETRIEVAL_SCOPE)
        if scope == PRODUCT_RETRIEVAL_SCOPE:
            scored.append(query)
        elif scope == AGENT_CONTRACT_SCOPE:
            excluded.append(query["query_id"])
        else:
            raise ValueError(
                f"{query['query_id']} has evaluation_scope={scope!r}; expected "
                f"{PRODUCT_RETRIEVAL_SCOPE!r} or {AGENT_CONTRACT_SCOPE!r}. "
                "Fix the canonical evaluation scope before scoring."
            )
    if not scored:
        raise ValueError(
            "Canonical scorecard has no product_retrieval queries; mark at least "
            "one query with evaluation_scope='product_retrieval'."
        )
    return scored, excluded


def scored_query_set_sha256(queries: list[dict[str, Any]]) -> str:
    """Hash the resolved records that actually contribute to retrieval metrics."""
    payload = "\n".join(
        json.dumps(query, sort_keys=True, separators=(",", ":")) for query in queries
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ranked_result_sha256(ranked: dict[str, list[tuple[int, int]]]) -> str:
    """Hash exact per-query ordering without volatile run or latency fields."""
    normalized = {
        query_id: [[rank, product_id] for rank, product_id in sorted(results)]
        for query_id, results in sorted(ranked.items())
    }
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_release_checks(
    queries: list[dict[str, Any]],
    ranked: dict[str, list[tuple[int, int]]],
) -> list[dict[str, Any]]:
    """Prove fixture-specific behavior that aggregate metrics can obscure."""
    passed: list[dict[str, Any]] = []
    for query in queries:
        ranked_ids = [
            product_id for _, product_id in sorted(ranked.get(query["query_id"], []))
        ]
        for check in query.get("release_checks", []):
            check_type = check.get("type")
            product_id = check.get("product_id")
            if not isinstance(product_id, int):
                raise TypeError(
                    f"{query['query_id']} release check has product_id={product_id!r}; "
                    "use an integer catalog product ID."
                )
            if check_type == "top_rank":
                if not ranked_ids or ranked_ids[0] != product_id:
                    raise ValueError(
                        f"{query['query_id']} requires product {product_id} at final "
                        f"rank 1; found top results {ranked_ids[:5]}. Fix the "
                        "retrieval representation or explicit ranking policy."
                    )
            elif check_type == "present_top_k":
                check_k = check.get("k")
                if not isinstance(check_k, int) or check_k < 1:
                    raise ValueError(
                        f"{query['query_id']} release check has k={check_k!r}; "
                        "use a positive integer."
                    )
                if product_id not in ranked_ids[:check_k]:
                    raise ValueError(
                        f"{query['query_id']} requires product {product_id} in the "
                        f"top {check_k}; found {ranked_ids[:check_k]}. Fix the "
                        "retrieval representation or candidate-generation path."
                    )
            else:
                raise ValueError(
                    f"{query['query_id']} release check type={check_type!r}; "
                    "use 'top_rank' or 'present_top_k'."
                )
            passed.append(
                {
                    "query_id": query["query_id"],
                    "type": check_type,
                    "product_id": product_id,
                    **({"k": check["k"]} if check_type == "present_top_k" else {}),
                }
            )
    return passed


def measured_scorecard(
    queries_path: Path,
    results_path: Path,
    *,
    k: int,
) -> dict[str, Any]:
    """Run the production retrieval and reranking service for every query."""
    canonical_queries = load_evaluation_queries(queries_path)
    queries, excluded_agent_contract_queries = product_retrieval_queries(
        canonical_queries
    )
    with connect() as connection:
        validate_query_contract(connection, queries)
        database_environment = dict(
            connection.execute(
                """
                SELECT aurora_db_instance_identifier() AS database_instance_id,
                       current_setting('server_version') AS database_version,
                       (
                           SELECT extversion
                           FROM pg_extension
                           WHERE extname = 'vector'
                       ) AS vector_extension_version
                """
            ).fetchone()
        )

    retrieval = get_retrieval_service()
    profile = retrieval._profile(SearchRequest(query="scorecard provenance", limit=k))
    ranked: dict[str, list[tuple[int, int]]] = {}
    with results_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "query_id",
                "product_id",
                "rank",
                "search_event_id",
                "strategy",
                "total_latency_ms",
            ],
        )
        writer.writeheader()
        for index, query in enumerate(queries, 1):
            response = retrieval.search(
                SearchRequest(
                    query=query["query"],
                    filters=SearchFilters.model_validate(query.get("filters") or {}),
                    limit=k,
                    include_diagnostics=True,
                    rerank=True,
                    session_id="canonical-release-eval",
                )
            )
            ranked[query["query_id"]] = [
                (result.signals.final_rank, result.product_id)
                for result in response.results
                if result.signals is not None
            ]
            for rank, product_id in ranked[query["query_id"]]:
                writer.writerow(
                    {
                        "query_id": query["query_id"],
                        "product_id": product_id,
                        "rank": rank,
                        "search_event_id": response.search_event_id,
                        "strategy": (
                            response.diagnostics.strategy
                            if response.diagnostics
                            else "unavailable"
                        ),
                        "total_latency_ms": (
                            response.diagnostics.total_latency_ms
                            if response.diagnostics
                            else None
                        ),
                    }
                )
            print(f"{index}/{len(queries)} {query['query_id']}")

    all_judgments = load_judgments(queries_path)
    release_checks = validate_release_checks(queries, ranked)
    metrics = evaluate(
        {query["query_id"]: all_judgments[query["query_id"]] for query in queries},
        ranked,
        k,
    )
    settings = get_settings()
    return {
        "query_set": str(queries_path),
        "query_set_sha256": query_set_sha256(queries_path),
        "scored_query_set_sha256": scored_query_set_sha256(queries),
        "canonical_query_count": len(canonical_queries),
        "product_retrieval_query_count": metrics["query_count"],
        "excluded_agent_contract_queries": excluded_agent_contract_queries,
        "deterministic_release_checks": release_checks,
        "ranked_result_sha256": ranked_result_sha256(ranked),
        "per_query_metrics": metrics["per_query"],
        "k": k,
        "models": {
            "embedding": settings.embedding_model_id,
            "rerank": settings.rerank_model_id,
        },
        "source": {
            "revision": settings.source_revision,
            "worktree_dirty": settings.source_worktree_dirty,
        },
        "dataset_manifest_sha256": settings.dataset_manifest_sha256,
        "retrieval_profile": profile.model_dump(),
        "hnsw_settings": {
            "ef_search": profile.ef_search,
            "iterative_scan": profile.iterative_scan,
            "max_scan_tuples": profile.max_scan_tuples,
            "scan_mem_multiplier": profile.scan_mem_multiplier,
        },
        "aurora_configuration": {
            "engine": "aurora-postgresql",
            "database_version": database_environment["database_version"],
            "vector_extension_version": database_environment[
                "vector_extension_version"
            ],
            "instance_class": settings.aurora_instance_class,
        },
        "database_instance_id": database_environment["database_instance_id"],
        "measured_at": datetime.now(UTC).isoformat(),
        "strategy": retrieval._strategy(),
        "metrics": {
            f"recall@{k}": metrics[f"recall@{k}"],
            "mrr": metrics["mrr"],
            f"ndcg@{k}": metrics[f"ndcg@{k}"],
        },
    }


def verify_scorecard(measured: dict[str, Any], baseline: dict[str, Any]) -> None:
    """Fail release validation when measured quality or provenance changes."""
    for field in (
        "query_set_sha256",
        "scored_query_set_sha256",
        "canonical_query_count",
        "product_retrieval_query_count",
        "excluded_agent_contract_queries",
        "deterministic_release_checks",
        "ranked_result_sha256",
        "k",
        "models",
        "dataset_manifest_sha256",
        "retrieval_profile",
        "hnsw_settings",
        "aurora_configuration",
        "database_instance_id",
        "strategy",
    ):
        if measured[field] != baseline.get(field):
            raise ValueError(
                f"Canonical scorecard {field} drifted: measured={measured[field]!r}; "
                f"baseline={baseline.get(field)!r}. Establish a new measured baseline "
                "only after reviewing the retrieval change."
            )
    source = measured.get("source") or {}
    if not source.get("revision") or not isinstance(source.get("worktree_dirty"), bool):
        raise ValueError(
            "Canonical scorecard source provenance is incomplete: "
            f"measured={source!r}. Record revision and worktree_dirty."
        )
    if source["worktree_dirty"]:
        raise ValueError(
            "Canonical scorecard source is dirty: "
            f"measured={source!r}; commit the reviewed source and rerun the "
            "production scorecard before release."
        )
    baseline_source = baseline.get("source") or {}
    if baseline_source.get("worktree_dirty") is not False:
        raise ValueError(
            "Canonical scorecard baseline was not captured from a clean source: "
            f"baseline={baseline_source!r}; establish it from a committed checkout."
        )
    for metric, expected in baseline["metrics"].items():
        actual = measured["metrics"].get(metric)
        if actual is None or actual < expected:
            raise ValueError(
                f"Canonical scorecard regressed for {metric}: measured={actual}; "
                f"baseline={expected}. Inspect per-query ranks before release."
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--queries",
        type=Path,
        default=Path("data/evals/canonical_queries.jsonl"),
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("benchmarks/results/canonical_served_results.csv"),
    )
    parser.add_argument(
        "--scorecard",
        type=Path,
        default=Path("data/evals/canonical_scorecard.json"),
    )
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Write the current measured scorecard after an explicit review.",
    )
    args = parser.parse_args()
    args.results.parent.mkdir(parents=True, exist_ok=True)
    measured = measured_scorecard(args.queries, args.results, k=args.k)
    if args.write_baseline:
        if measured["source"]["worktree_dirty"]:
            raise SystemExit(
                "Refusing to write a canonical baseline from a dirty source; "
                "commit the reviewed changes, rerun, inspect the ranks, then use "
                "--write-baseline."
            )
        args.scorecard.write_text(
            json.dumps(measured, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote measured baseline {args.scorecard}")
        return
    if not args.scorecard.exists():
        raise SystemExit(
            f"Canonical scorecard is missing: {args.scorecard}. Run with "
            "--write-baseline only after reviewing measured ranks."
        )
    verify_scorecard(
        measured,
        json.loads(args.scorecard.read_text(encoding="utf-8")),
    )
    print(json.dumps(measured, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
