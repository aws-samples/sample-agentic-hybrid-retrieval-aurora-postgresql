#!/usr/bin/env python3
"""Measure what hybrid retrieval adds over vector search on held-out ESCI queries.

For each held-out query with at least one Exact or Substitute label, this reads
the production full-text, close-spelling and vector lists from Aurora with the
served limits and HNSW settings, plus the served fusion order, and scores:

- `keyword`: full-text search alone;
- `vector_embed_v4` and `hybrid_embed_v4`: the served Cohere Embed v4 vector
  search, and the served reciprocal rank fusion of all three lists;
- `vector_small` and `hybrid_small`, when `--small-vectors` names the output of
  `scripts/evals/embed_small_model.py`: exact cosine search over the small
  model's vectors, fused with the same full-text and close-spelling lists;
- `*_rerank`, unless `--no-rerank`: the top `fused_limit` of each Embed v4 list
  reordered by the served Cohere reranker, by score alone.

nDCG@10 uses the human ESCI grades in `data/evals/esci_held_out_queries.jsonl`.
Labels are sparse, so absolute values are low: compare arms with the paired
bootstrap intervals. The Python fusion used for the small model is checked
against the production fusion SQL on every query. Aurora is read inside
read-only transactions and no search events are written; query embeddings and
reranking call Amazon Bedrock.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

QUERIES = REPO / "data/evals/esci_held_out_queries.jsonl"
OUTPUT = REPO / "data/evals/hybrid_payoff.json"
DEPTH = 10
RELEVANT_GRADE = 2
DRAWS = 10_000
SEED = 7

COMPARISONS = (
    ("hybrid_embed_v4", "vector_embed_v4"),
    ("hybrid_small", "vector_small"),
    ("keyword", "vector_embed_v4"),
    ("hybrid_embed_v4", "keyword"),
    ("vector_small", "vector_embed_v4"),
    ("hybrid_small", "hybrid_embed_v4"),
    ("hybrid_embed_v4_rerank", "hybrid_embed_v4"),
    ("vector_embed_v4_rerank", "vector_embed_v4"),
    ("hybrid_embed_v4_rerank", "vector_embed_v4_rerank"),
    ("hybrid_embed_v4_rerank", "vector_embed_v4"),
)


def load_queries() -> list[dict]:
    """Held-out queries with at least one Exact or Substitute label.

    Refuses a corpus that reuses a query already spent on RRF-k tuning or on the
    release scorecard, as the held-out file contract requires.
    """
    from scripts.evals.independent_relevance_eval import (
        require_disjoint_from_tuning_sources,
    )

    queries = [json.loads(line) for line in QUERIES.open() if line.strip()]
    require_disjoint_from_tuning_sources(queries)
    return [
        q for q in queries if any(j["grade"] >= RELEVANT_GRADE for j in q["judgments"])
    ]


def rrf(lists: list[list[int]], k: int, size: int) -> list[int]:
    """Unweighted reciprocal rank fusion, ties broken by product ID as served."""
    scores: dict[int, float] = {}
    for ranked in lists:
        for rank, product_id in enumerate(ranked, 1):
            scores[product_id] = scores.get(product_id, 0.0) + 1.0 / (k + rank)
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [product_id for product_id, _ in ordered][:size]


def read_lists(conn, service, profile, filters: dict, normalized: str, vector):
    """The three channel lists and the served fusion order, in one read-only pass."""
    from service.catalog_runtime import search_schema

    schema = search_schema()
    encoded = json.dumps(filters)
    statements = {
        "fts": (
            (
                f"SELECT product_id FROM {schema}.search_fts(%s, %s::jsonb, %s) "
                "ORDER BY fts_rank"
            ),
            (normalized, encoded, profile.fts_limit),
        ),
        "trigram": (
            (
                f"SELECT product_id FROM {schema}.search_trigram("
                "%s, %s::jsonb, %s, %s::real) ORDER BY trigram_rank"
            ),
            (normalized, encoded, profile.trigram_limit, profile.trigram_threshold),
        ),
        "vector": (
            (
                f"SELECT product_id FROM {schema}.search_vector("
                "%s::vector, %s::jsonb, %s) ORDER BY semantic_rank"
            ),
            (str(list(vector)), encoded, profile.semantic_limit),
        ),
    }
    lists: dict[str, list[int]] = {}
    with conn.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        service._configure_hnsw(cursor, profile)
        for name, (sql, args) in statements.items():
            cursor.execute(sql, args)
            lists[name] = [row["product_id"] for row in cursor.fetchall()]
        cursor.execute(
            service._fusion_sql(),
            service._fusion_parameters(normalized, tuple(vector), filters, profile),
        )
        lists["served"] = [row["product_id"] for row in cursor.fetchall()]
        pool = set(lists["served"]) | set(lists["vector"][: profile.fused_limit])
        cursor.execute(
            f"SELECT product_id, rerank_text, title, short_description, category_path, "
            f"brand_name, model_name FROM {schema}.product_document "
            "WHERE product_id = ANY(%s)",
            (sorted(pool),),
        )
        documents = {row["product_id"]: row for row in cursor.fetchall()}
    conn.rollback()
    return lists, documents


def rerank(service, normalized: str, ids: list[int], documents: dict) -> list[int]:
    from service.rerank import validate_rerank_results
    from service.retrieval import _rerank_document

    if not ids:
        return []
    scored = service._reranker().rerank(
        normalized, [_rerank_document(documents[i]) for i in ids], len(ids)
    )
    scored = validate_rerank_results(
        scored, document_count=len(ids), expected_count=len(ids)
    )
    return [ids[index] for index, _ in sorted(scored, key=lambda s: (-s[1], s[0]))]


def load_small(directory: Path) -> tuple[dict, dict, str]:
    import numpy as np

    queries = np.load(directory / "queries.npz")
    query_vectors = {str(q): queries["vecs"][i] for i, q in enumerate(queries["ids"])}
    products = {
        path.stem: np.load(path)
        for path in sorted(directory.glob("*.npz"))
        if path.stem != "queries"
    }
    model = json.loads((directory / "model.json").read_text())["model_id"]
    return products, query_vectors, model


def small_vector_list(products, category: str, query_vector, size: int) -> list[int]:
    import numpy as np

    catalog = products[category]
    similarity = catalog["vecs"] @ query_vector
    top = np.argsort(-similarity, kind="stable")[:size]
    return [int(catalog["ids"][i]) for i in top]


def measure_query(context: dict, query: dict) -> dict[str, list[int]]:
    """Every arm's ranking for one query; raises if Python fusion leaves production."""
    from service.models import SearchFilters
    from service.retrieval import normalize_query

    service, profile = context["service"], context["profile"]
    normalized = normalize_query(query["query"])
    filters = SearchFilters(**query["filters"]).as_sql_json()
    vector = service.embed_query(query["query"])
    lists, documents = read_lists(
        context["conn"], service, profile, filters, normalized, vector
    )
    channels = [lists["fts"], lists["trigram"]]
    fused = rrf([*channels, lists["vector"]], profile.rrf_k, profile.fused_limit)
    if fused != lists["served"][: profile.fused_limit]:
        raise RuntimeError(
            f"found Python RRF differing from the production fusion SQL for "
            f"{query['query_id']}; fix: align rrf() with the served fusion function"
        )
    arms = {
        "keyword": lists["fts"],
        "vector_embed_v4": lists["vector"],
        "hybrid_embed_v4": lists["served"],
    }
    if context["small"]:
        products, query_vectors, _ = context["small"]
        small = small_vector_list(
            products,
            filters["category_key"],
            query_vectors[query["query_id"]],
            profile.semantic_limit,
        )
        arms["vector_small"] = small
        arms["hybrid_small"] = rrf(
            [*channels, small], profile.rrf_k, profile.fused_limit
        )
    if context["rerank"]:
        for arm in ("vector_embed_v4", "hybrid_embed_v4"):
            pool = arms[arm][: profile.fused_limit]
            arms[f"{arm}_rerank"] = rerank(service, normalized, pool, documents)
    return {arm: ids[:DEPTH] for arm, ids in arms.items()}


def bootstrap(diffs: list[float]) -> dict:
    rng = random.Random(SEED)
    means = sorted(
        sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(DRAWS)
    )
    better = sum(d > 1e-12 for d in diffs)
    worse = sum(d < -1e-12 for d in diffs)
    return {
        "mean_diff": round(sum(diffs) / len(diffs), 4),
        "ci95": [
            round(means[int(0.025 * DRAWS)], 4),
            round(means[int(0.975 * DRAWS) - 1], 4),
        ],
        "better": better,
        "worse": worse,
        "tied": len(diffs) - better - worse,
    }


def score(queries: list[dict], rankings: dict[str, dict[str, list[int]]]) -> dict:
    from scripts.evals.evaluate import evaluate

    truth = {
        q["query_id"]: {int(j["product_id"]): int(j["grade"]) for j in q["judgments"]}
        for q in queries
    }
    arms, per_query = {}, {}
    for arm, ranked in rankings.items():
        report = evaluate(
            truth, {qid: list(enumerate(ids, 1)) for qid, ids in ranked.items()}, DEPTH
        )
        arms[arm] = {
            key: round(report[key], 4)
            for key in (f"ndcg@{DEPTH}", f"recall@{DEPTH}", "mrr")
        }
        per_query[arm] = {
            row["query_id"]: row[f"ndcg@{DEPTH}"] for row in report["per_query"]
        }
    ids = sorted(truth)

    def diffs(a: str, b: str, subset=ids) -> list[float]:
        return [per_query[a][i] - per_query[b][i] for i in subset]

    comparisons = {
        f"{a} - {b}": bootstrap(diffs(a, b))
        for a, b in COMPARISONS
        if a in per_query and b in per_query
    }
    if "hybrid_small" in per_query:
        small, frontier = (
            diffs("hybrid_small", "vector_small"),
            diffs("hybrid_embed_v4", "vector_embed_v4"),
        )
        comparisons["payoff difference (small - embed_v4)"] = bootstrap(
            [s - f for s, f in zip(small, frontier, strict=True)]
        )
    by_category = {}
    for category in sorted({q["filters"]["category_key"] for q in queries}):
        subset = [
            q["query_id"] for q in queries if q["filters"]["category_key"] == category
        ]
        by_category[category] = {
            "queries": len(subset),
            "hybrid_embed_v4 - vector_embed_v4": bootstrap(
                diffs("hybrid_embed_v4", "vector_embed_v4", subset)
            ),
        }
    labels = [len(truth[i]) for i in ids]
    return {
        "arms": arms,
        "comparisons": comparisons,
        "by_category": by_category,
        "labels_per_query_mean": round(sum(labels) / len(labels), 1),
        "per_query_ndcg@10": {
            arm: {i: round(v[i], 6) for i in ids} for arm, v in per_query.items()
        },
    }


def provenance(
    conn, service, profile, small_model: str | None, rerank_used: bool
) -> dict:
    from service.catalog_runtime import search_schema

    with conn.cursor() as cursor:
        cursor.execute(
            f"SELECT dataset_id, catalog_sha256 FROM {search_schema()}.receipt WHERE singleton"
        )
        receipt = cursor.fetchone()
    conn.rollback()
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    return {
        "measured_at": datetime.now(UTC).isoformat(),
        "source_revision": revision,
        "source_worktree_dirty": dirty,
        "dataset_id": receipt["dataset_id"],
        "catalog_sha256": receipt["catalog_sha256"],
        "query_set": str(QUERIES.relative_to(REPO)),
        "query_set_sha256": hashlib.sha256(QUERIES.read_bytes()).hexdigest(),
        "embedding_model_id": service.settings.embedding_model_id,
        "rerank_model_id": service.settings.rerank_model_id if rerank_used else None,
        "small_model_id": small_model,
        "rrf_k": profile.rrf_k,
        "limits": {
            "fts": profile.fts_limit,
            "trigram": profile.trigram_limit,
            "semantic": profile.semantic_limit,
            "fused": profile.fused_limit,
        },
        "ef_search": profile.ef_search,
        "bootstrap": {"draws": DRAWS, "seed": SEED},
    }


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    import psycopg
    from pgvector.psycopg import register_vector
    from psycopg.rows import dict_row

    from service.models import SearchRequest
    from service.retrieval import RetrievalService

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--small-vectors", type=Path)
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    queries = load_queries()
    service = RetrievalService()
    profile = service._profile(SearchRequest(query="profile", limit=DEPTH))
    small = load_small(args.small_vectors) if args.small_vectors else None
    started = time.monotonic()
    rankings: dict[str, dict[str, list[int]]] = {}
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        register_vector(conn)
        context = {
            "conn": conn,
            "service": service,
            "profile": profile,
            "small": small,
            "rerank": not args.no_rerank,
        }
        for n, query in enumerate(queries, 1):
            for arm, ids in measure_query(context, query).items():
                rankings.setdefault(arm, {})[query["query_id"]] = ids
            if n % 50 == 0:
                print(
                    f"{n}/{len(queries)} in {time.monotonic() - started:.0f}s",
                    flush=True,
                )
        report = {
            "provenance": provenance(
                conn, service, profile, small[2] if small else None, not args.no_rerank
            ),
            "queries": len(queries),
            "fusion_check": "Python RRF equals the production fusion SQL on every query",
            **score(queries, rankings),
            "seconds": round(time.monotonic() - started),
        }
    args.output.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "per_query_ndcg@10"}, indent=1
        )
    )


if __name__ == "__main__":
    main()
