#!/usr/bin/env python3
"""Run the packaged evaluation queries against catalog.search_hybrid_rrf.

Output CSV is compatible with scripts/evaluate.py. Use the same embedding
provider/dimension used to populate product.embedding.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from pathlib import Path

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
        default=int(
            os.getenv("VECTOR_DIM", str(COHERE_EMBED_V4_DIMENSIONS))
        ),
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
        connection.execute(
            "SELECT set_config('pg_trgm.similarity_threshold', '0.24', false)"
        )
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
                FROM catalog.search_hybrid_rrf(
                    %s, %s, %s::jsonb, 60, 100, 75, 100, %s
                )
                """,
                (
                    query["query"],
                    vector,
                    json.dumps(query.get("filters") or {}),
                    max(args.k, 50),
                ),
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
