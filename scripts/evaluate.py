#!/usr/bin/env python3
"""Compute Recall@K, MRR, and nDCG@K from graded judgments."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from collections import defaultdict
from pathlib import Path


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def dcg(grades: list[int]) -> float:
    return sum(
        (2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades)
    )


def load_judgments(path: Path) -> dict[str, dict[int, int]]:
    truth: dict[str, dict[int, int]] = defaultdict(dict)
    if path.suffix == ".jsonl":
        with open_text(path) as handle:
            for line in handle:
                if not line.strip():
                    continue
                query = json.loads(line)
                for judgment in query["judgments"]:
                    truth[query["query_id"]][int(judgment["product_id"])] = int(
                        judgment["grade"]
                    )
        return truth
    with open_text(path) as handle:
        for row in csv.DictReader(handle):
            truth[row["query_id"]][int(row["product_id"])] = int(row["relevance_grade"])
    return truth


def evaluate(
    truth: dict[str, dict[int, int]],
    ranked: dict[str, list[tuple[int, int]]],
    k: int,
) -> dict[str, object]:
    per_query: list[dict[str, float | str]] = []
    for query_id, judgments in truth.items():
        got = [product_id for _, product_id in sorted(ranked.get(query_id, []))[:k]]
        relevant = {product_id for product_id, grade in judgments.items() if grade >= 2}
        recall = len(relevant & set(got)) / max(1, len(relevant))
        first = next(
            (
                index + 1
                for index, product_id in enumerate(got)
                if product_id in relevant
            ),
            None,
        )
        reciprocal_rank = 0.0 if first is None else 1 / first
        grades = [judgments.get(product_id, 0) for product_id in got]
        ideal = sorted(judgments.values(), reverse=True)[:k]
        ndcg = dcg(grades) / (dcg(ideal) or 1)
        per_query.append(
            {
                "query_id": query_id,
                f"recall@{k}": recall,
                "reciprocal_rank": reciprocal_rank,
                f"ndcg@{k}": ndcg,
            }
        )
    if not per_query:
        raise ValueError("No judgments were loaded")
    return {
        "query_count": len(per_query),
        f"recall@{k}": sum(row[f"recall@{k}"] for row in per_query) / len(per_query),
        "mrr": sum(row["reciprocal_rank"] for row in per_query) / len(per_query),
        f"ndcg@{k}": sum(row[f"ndcg@{k}"] for row in per_query) / len(per_query),
        "per_query": per_query,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--judgments",
        type=Path,
        default=Path("data/evals/canonical_queries.jsonl"),
    )
    parser.add_argument(
        "--results",
        type=Path,
        required=True,
        help="CSV with query_id, product_id, and rank columns.",
    )
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    truth = load_judgments(args.judgments)
    ranked: dict[str, list[tuple[int, int]]] = defaultdict(list)
    with open_text(args.results) as handle:
        for row in csv.DictReader(handle):
            ranked[row["query_id"]].append((int(row["rank"]), int(row["product_id"])))
    metrics = evaluate(truth, ranked, args.k)
    print(
        f"queries={metrics['query_count']} "
        f"recall@{args.k}={metrics[f'recall@{args.k}']:.4f} "
        f"MRR={metrics['mrr']:.4f} "
        f"nDCG@{args.k}={metrics[f'ndcg@{args.k}']:.4f}"
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(metrics, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
