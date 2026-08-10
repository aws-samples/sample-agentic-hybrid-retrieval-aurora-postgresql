#!/usr/bin/env python3
"""Run the packaged evaluation queries against mosaic_search.search_hybrid_rrf.

Output CSV is compatible with scripts/evaluate.py. Use the same embedding
provider/dimension used to populate the retrieval projection's embeddings.

Ported from `catalog.search_hybrid_rrf` in Phase 2 Unit E. **No predecessor
comparison possible — both `catalog.*` databases dropped 2026-08; DDL survives in
git, loaded state does not.** See SUBSTRATE-1 in docs/rewrite-losses.md.

**Correctness bar, since equivalence is unavailable: the golden missions'
expected targets.** The mission contract gate's A2 checks are the baseline that
*does* exist — they assert on the live cluster that every mission target resolves
and satisfies its own filters. A port that returns those targets for those queries
is right for a reason that can be re-checked, which "matches the old CSV" never
was: the old CSV cannot be produced.

Two defects were fixed in the port rather than carried across. The predecessor
hardcoded its candidate limits (`60, 100, 75, 100`) and set
`pg_trgm.similarity_threshold` to `0.24`. Both disagreed with the live system —
the limits are 120/80/150 and the threshold is 0.20 — so its numbers were not
merely un-comparable, they were wrong. Everything now comes from
`db/config/retrieval.yaml` through `scripts.retrieval_profile`, which is also
what stops `scripts/config_tripwire.py` failing this file.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.retrieval_profile import load_profile  # noqa: E402  (path set above)

if __package__:
    from scripts.embed_catalog import (
        COHERE_EMBED_V4_DIMENSIONS,
        COHERE_EMBED_V4_MODEL_ID,
        embedding_function,
    )
else:
    from embed_catalog import (
        COHERE_EMBED_V4_DIMENSIONS,
        COHERE_EMBED_V4_MODEL_ID,
        embedding_function,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    ap.add_argument(
        "--queries",
        type=Path,
        default=Path("data/evals/queries.jsonl"),
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/results/eval_results.csv"),
    )
    ap.add_argument(
        "--provider",
        choices=["bedrock", "bedrock-cohere-v4", "hash"],
        default=os.getenv("EMBEDDING_PROVIDER", "bedrock"),
    )
    ap.add_argument(
        "--model-id",
        default=os.getenv("BEDROCK_EMBED_MODEL_ID", COHERE_EMBED_V4_MODEL_ID),
    )
    ap.add_argument(
        "--dimensions",
        type=int,
        default=int(os.getenv("VECTOR_DIM", str(COHERE_EMBED_V4_DIMENSIONS))),
    )
    ap.add_argument("--region", default=os.getenv("BEDROCK_REGION", "us-east-1"))
    ap.add_argument("--allow-development-embeddings", action="store_true")
    ap.add_argument("--limit-queries", type=int)
    ap.add_argument("--k", type=int, default=10)
    args = ap.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL required")
    try:
        import psycopg
        from pgvector.psycopg import register_vector
    except ImportError as error:
        raise SystemExit("Install config/requirements.txt") from error
    profile = load_profile()
    embed, model_id = embedding_function(
        args.provider,
        model_id=args.model_id,
        dimensions=args.dimensions,
        region=args.region,
        allow_development_embeddings=args.allow_development_embeddings,
    )
    queries = [
        json.loads(line)
        for line in args.queries.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.limit_queries:
        queries = queries[: args.limit_queries]
    query_vectors: list[list[float]] = []
    for offset in range(0, len(queries), 64):
        batch = queries[offset : offset + 64]
        query_vectors.extend(embed([item["query"] for item in batch]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with (
        psycopg.connect(args.database_url) as connection,
        args.output.open("w", newline="", encoding="utf-8") as output,
    ):
        register_vector(connection)
        # The predecessor set this to 0.24, which never matched the live 0.20 and
        # is recorded as stale in LOSS-3. `mosaic_search.search_trigram` sets its
        # own thresholds per call via a function-level SET, so nothing is needed
        # here — the arm's gate travels with the arm.
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "query_id",
                "product_id",
                "rank",
                "latency_ms",
                "embedding_model_id",
            ],
        )
        writer.writeheader()
        for index, (query, vector) in enumerate(
            zip(queries, query_vectors),
            1,
        ):
            started = time.perf_counter()
            rows = connection.execute(
                """
                SELECT product_id
                FROM mosaic_search.search_hybrid_rrf(
                    %(query)s::text, %(embedding)s::vector, %(filters)s::jsonb,
                    %(rrf_k)s::integer, %(fts_limit)s::integer,
                    %(trigram_limit)s::integer, %(semantic_limit)s::integer,
                    %(result_limit)s::integer, %(business_weight)s::real,
                    %(trigram_threshold)s::real
                )
                """,
                {
                    "query": query["query"],
                    "embedding": vector,
                    "filters": json.dumps(query.get("filters") or {}),
                    "rrf_k": profile.rrf_k,
                    "fts_limit": profile.fts_limit,
                    "trigram_limit": profile.trigram_limit,
                    "semantic_limit": profile.semantic_limit,
                    "result_limit": max(args.k, profile.fused_limit),
                    "business_weight": profile.business_weight,
                    "trigram_threshold": profile.trigram_threshold,
                },
            ).fetchall()
            elapsed = (time.perf_counter() - started) * 1_000
            for rank, (product_id,) in enumerate(rows[: args.k], 1):
                writer.writerow(
                    {
                        "query_id": query["query_id"],
                        "product_id": product_id,
                        "rank": rank,
                        "latency_ms": round(elapsed, 3),
                        "embedding_model_id": model_id,
                    }
                )
            if index % 50 == 0 or index == len(queries):
                print(f"{index:,}/{len(queries):,}")
    print(f"Wrote {args.output} with embedding_model_id={model_id}")


if __name__ == "__main__":
    main()
