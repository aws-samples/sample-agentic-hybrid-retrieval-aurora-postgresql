#!/usr/bin/env python3
"""Measure how the RRF constant k changes what reaches reranking, on ESCI judgments.

For every query in `data/evals/esci_judged_subset.json`, this runs the three
installed search functions once with the configured limits, then fuses their
positions at several values of k. It reports, per k:

- how many ESCI Exact products land inside the reranking cutoff (`fused_limit`);
- condensed nDCG@10 of the fused order: judged products only, in fused order,
  with the ESCI gains E=1.0, S=0.1, C=0.01, I=0 (Reddy et al., 2022).

It measures fusion before reranking, which is the stage Lab 2 repairs. It does
not call the reranker, and it writes nothing to Aurora.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

K_VALUES = (1, 10, 30, 60, 120)
GAINS = {"E": 1.0, "S": 0.1, "C": 0.01, "I": 0.0}


def fuse(arms: dict[str, dict[int, int]], k: int) -> list[int]:
    """Product IDs in RRF order, ties broken by product ID as production does."""
    scores: dict[int, float] = {}
    for ranks in arms.values():
        for product_id, rank in ranks.items():
            scores[product_id] = scores.get(product_id, 0.0) + 1.0 / (k + rank)
    return [pid for pid, _ in sorted(scores.items(), key=lambda i: (-i[1], i[0]))]


def condensed_ndcg(order: list[int], labels: dict[int, str], depth: int = 10) -> float:
    """nDCG over judged products only, in the order fusion placed them."""
    judged = [labels[pid] for pid in order if pid in labels][:depth]
    ideal = sorted((GAINS[label] for label in labels.values()), reverse=True)[:depth]
    dcg = sum(GAINS[label] / math.log2(i + 2) for i, label in enumerate(judged))
    best = sum(gain / math.log2(i + 2) for i, gain in enumerate(ideal))
    return dcg / best if best else 0.0


def arms_for(cursor, case: dict, vector: list[float], profile) -> dict:
    from service.catalog_runtime import search_schema

    schema = search_schema()
    filters = json.dumps(case["filters"])
    statements = {
        "fts": (
            f"SELECT product_id, fts_rank AS r FROM {schema}.search_fts(%s, %s::jsonb, %s)",
            (case["query"], filters, profile.fts_limit),
        ),
        "trigram": (
            (
                f"SELECT product_id, trigram_rank AS r FROM {schema}.search_trigram("
                "%s, %s::jsonb, %s, %s::real)"
            ),
            (case["query"], filters, profile.trigram_limit, profile.trigram_threshold),
        ),
        "vector": (
            (
                f"SELECT product_id, semantic_rank AS r FROM {schema}.search_vector("
                "%s::vector, %s::jsonb, %s)"
            ),
            (str(vector), filters, profile.semantic_limit),
        ),
    }
    arms = {}
    for name, (sql, args) in statements.items():
        cursor.execute(sql, args)
        arms[name] = {row["product_id"]: row["r"] for row in cursor.fetchall()}
    return arms


def score_case(case: dict, arms: dict, cutoff: int) -> dict:
    labels = {j["product_id"]: j["esci_label"] for j in case["judgments"]}
    exact = {pid for pid, label in labels.items() if label == "E"}
    found = set().union(*arms.values())
    per_k = {}
    for k in K_VALUES:
        order = fuse(arms, k)
        per_k[str(k)] = {
            "exact_in_cutoff": len(exact & set(order[:cutoff])),
            "condensed_ndcg10": round(condensed_ndcg(order, labels), 6),
        }
    return {
        "query_id": case["query_id"],
        "query": case["query"],
        "category": case["filters"]["category_key"],
        "exact_judged": len(exact),
        "exact_found_by_any_method": len(exact & found),
        "per_k": per_k,
    }


def summarize(results: list[dict], baseline: int) -> dict:
    summary = {}
    for k in K_VALUES:
        key = str(k)
        ndcg = [r["per_k"][key]["condensed_ndcg10"] for r in results]
        delta = [
            r["per_k"][key]["condensed_ndcg10"]
            - r["per_k"][str(baseline)]["condensed_ndcg10"]
            for r in results
        ]
        summary[key] = {
            "exact_in_cutoff": sum(r["per_k"][key]["exact_in_cutoff"] for r in results),
            "mean_condensed_ndcg10": round(statistics.fmean(ndcg), 4),
            f"queries_better_than_k{baseline}": sum(d > 1e-12 for d in delta),
            f"queries_worse_than_k{baseline}": sum(d < -1e-12 for d in delta),
        }
    return summary


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    import psycopg
    from psycopg.rows import dict_row

    from scripts.retrieval_profile import load_profile
    from service.retrieval import RetrievalService

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--subset", type=Path, default=REPO / "data/evals/esci_judged_subset.json"
    )
    parser.add_argument(
        "--output", type=Path, default=REPO / "data/evals/esci_k_sweep.json"
    )
    args = parser.parse_args()
    subset = json.loads(args.subset.read_text())
    profile = load_profile()
    service = RetrievalService()
    results = []
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        for case in subset["queries"]:
            vector = service.embed_query(case["query"])
            with conn.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                arms = arms_for(cursor, case, vector, profile)
            conn.rollback()
            results.append(score_case(case, arms, profile.fused_limit))
    judged_exact = sum(r["exact_judged"] for r in results)
    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "dataset_id": subset["dataset_id"],
        "embedding_model_id": service.settings.embedding_model_id,
        "stage": "fusion before reranking",
        "configured_k": profile.rrf_k,
        "reranking_cutoff": profile.fused_limit,
        "limits": {
            "fts": profile.fts_limit,
            "trigram": profile.trigram_limit,
            "semantic": profile.semantic_limit,
        },
        "queries": len(results),
        "exact_judged": judged_exact,
        "exact_found_by_any_method": sum(
            r["exact_found_by_any_method"] for r in results
        ),
        "by_k": summarize(results, profile.rrf_k),
        "per_query": results,
    }
    args.output.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "per_query"}, indent=1))


if __name__ == "__main__":
    main()
