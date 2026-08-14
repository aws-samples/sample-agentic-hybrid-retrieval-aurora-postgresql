#!/usr/bin/env python3
"""Run the packaged evaluation queries against mosaic_search.search_hybrid_rrf.

Output CSV is compatible with scripts/evaluate.py. Use the same embedding
provider/dimension used to populate the retrieval projection's embeddings.

Ported from `catalog.search_hybrid_rrf` in Phase 2 Unit E. **No predecessor
comparison possible — both `catalog.*` databases dropped 2026-08; DDL survives in
git, loaded state does not.** See SUBSTRATE-1 in docs/rewrite-losses.md.

**Correctness bar, since equivalence is unavailable:** every packaged evaluation
target must exist and satisfy its own production Mosaic filters. This script
checks all query filters through `SearchFilters` and
`mosaic_search.matches_filters` before invoking the embedding model.

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
from typing import Any

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.eval_contract import load_evaluation_queries
from scripts.retrieval_profile import load_profile
from service.models import SearchFilters

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


def validate_query_contract(connection: Any, queries: list[dict[str, Any]]) -> None:
    """Fail before model calls when an eval target violates Mosaic filters."""
    if not queries:
        raise ValueError(
            "Evaluation contract requires at least one query; fix: provide a "
            "non-empty JSONL query set before publishing retrieval metrics."
        )
    query_ids: set[str] = set()
    cases: list[dict[str, Any]] = []
    for query in queries:
        query_id = str(query.get("query_id") or "")
        if not query_id:
            raise ValueError("Evaluation query is missing query_id")
        if query_id in query_ids:
            raise ValueError(f"Duplicate evaluation query_id: {query_id}")
        query_ids.add(query_id)
        supplied_filters = query.get("filters", {})
        try:
            filters = SearchFilters.model_validate(supplied_filters).as_sql_json()
        except ValidationError as error:
            raise ValueError(
                f"{query_id} filters violate the Mosaic SearchFilters contract: "
                f"found {supplied_filters!r}; fix: use category_key, integer "
                "min_price_cents/max_price_cents, and the typed fields in "
                "service.models.SearchFilters"
            ) from error
        if "judgments" in query:
            judgments = query.get("judgments")
            if not isinstance(judgments, list) or not judgments:
                raise ValueError(f"{query_id} must carry non-empty judgments")
            for judgment in judgments:
                try:
                    product_id = int(judgment["product_id"])
                    grade = int(judgment["grade"])
                except (KeyError, TypeError, ValueError) as error:
                    raise ValueError(
                        f"{query_id} has an invalid graded judgment"
                    ) from error
                if grade not in {0, 1, 2, 3}:
                    raise ValueError(f"{query_id}/{product_id} has grade {grade}")
                cases.append(
                    {
                        "query_id": query_id,
                        "target_product_id": product_id,
                        "filters": filters,
                        "require_filter_match": grade > 0,
                    }
                )
        else:
            try:
                target_product_id = int(query["target_product_id"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    f"{query_id} must name an integer target_product_id"
                ) from error
            cases.append(
                {
                    "query_id": query_id,
                    "target_product_id": target_product_id,
                    "filters": filters,
                    "require_filter_match": True,
                }
            )

    failures = connection.execute(
        """
        WITH cases AS (
            SELECT *
            FROM jsonb_to_recordset(%s::jsonb) AS c(
                query_id text,
                target_product_id bigint,
                filters jsonb,
                require_filter_match boolean
            )
        )
        SELECT c.query_id,
               c.target_product_id,
               CASE
                   WHEN d.product_id IS NULL THEN 'target does not exist'
                   ELSE 'positive judgment violates its Mosaic filters'
               END AS reason
        FROM cases c
        LEFT JOIN mosaic_search.product_document d
          ON d.product_id = c.target_product_id
        WHERE d.product_id IS NULL
           OR (
               c.require_filter_match
               AND NOT mosaic_search.matches_filters(d, c.filters)
           )
        ORDER BY c.query_id
        """,
        (json.dumps(cases),),
    ).fetchall()
    if failures:
        sample = "; ".join(
            f"{query_id}/{product_id}: {reason}"
            for query_id, product_id, reason in failures[:10]
        )
        suffix = "" if len(failures) <= 10 else f"; plus {len(failures) - 10} more"
        raise ValueError(
            "Evaluation contract failed against Aurora: "
            f"{sample}{suffix}. Fix the query filters or target IDs before "
            "publishing retrieval metrics."
        )
    print(
        f"Evaluation contract passed: {len(cases):,} judged targets exist and "
        "every positive judgment satisfies mosaic_search.matches_filters."
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
    ap.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate filter shape and live target eligibility without model calls.",
    )
    args = ap.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL required")
    try:
        import psycopg
        from pgvector.psycopg import register_vector
    except ImportError as error:
        raise SystemExit(
            "Run `uv sync --frozen` to install evaluation dependencies"
        ) from error
    queries = load_evaluation_queries(args.queries)
    if args.limit_queries:
        queries = queries[: args.limit_queries]
    with psycopg.connect(args.database_url) as connection:
        register_vector(connection)
        validate_query_contract(connection, queries)
        if args.validate_only:
            return

        profile = load_profile()
        embed, model_id = embedding_function(
            args.provider,
            model_id=args.model_id,
            dimensions=args.dimensions,
            region=args.region,
            allow_development_embeddings=args.allow_development_embeddings,
        )
        query_vectors: list[list[float]] = []
        for offset in range(0, len(queries), 64):
            batch = queries[offset : offset + 64]
            query_vectors.extend(embed([item["query"] for item in batch]))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as output:
            # The predecessor set this to 0.24, which never matched the live
            # 0.20 score floor. pg_trgm's index gates are database defaults
            # applied separately from the function by db-configure-retrieval.
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
                        %(result_limit)s::integer, %(trigram_threshold)s::real
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
