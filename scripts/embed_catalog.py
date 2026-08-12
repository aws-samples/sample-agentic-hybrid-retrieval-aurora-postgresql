#!/usr/bin/env python3
"""Populate catalog embeddings with Cohere Embed v4 through Amazon Bedrock.

Deterministic hash vectors remain available only for explicit local mechanics
tests. They are not valid workshop data or relevance evidence.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import math
import os
import random
import re
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

COHERE_EMBED_V4_MODEL_ID = "us.cohere.embed-v4:0"
COHERE_EMBED_V4_DIMENSIONS = 1024
DEVELOPMENT_HASH_MODEL_ID = "local-hash-development-v1"


def hash_embed(text: str, dimensions: int) -> list[float]:
    vec = [0.0] * dimensions
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    for i, token in enumerate(tokens):
        for feature, weight in ((token, 1.0), (" ".join(tokens[i:i+2]), 0.6), (" ".join(tokens[i:i+3]), 0.25)):
            if not feature:
                continue
            digest = hashlib.blake2b(feature.encode(), digest_size=16).digest()
            idx = int.from_bytes(digest[:8], "big") % dimensions
            sign = 1.0 if digest[8] & 1 else -1.0
            vec[idx] += sign * weight
    norm = math.sqrt(sum(x*x for x in vec)) or 1.0
    return [x / norm for x in vec]


def embedding_function(
    provider: str,
    *,
    model_id: str,
    dimensions: int,
    region: str,
    allow_development_embeddings: bool,
) -> tuple[Callable[[list[str]], list[list[float]]], str]:
    if provider in {"bedrock", "bedrock-cohere-v4"}:
        if model_id != COHERE_EMBED_V4_MODEL_ID:
            raise SystemExit(
                "This workshop requires Cohere Embed v4 through Amazon Bedrock: "
                f"{COHERE_EMBED_V4_MODEL_ID}"
            )
        if dimensions != COHERE_EMBED_V4_DIMENSIONS:
            raise SystemExit(
                "Cohere Embed v4 must use the workshop's canonical "
                f"{COHERE_EMBED_V4_DIMENSIONS}-dimension model space"
            )
        from service.config import get_settings
        from service.embeddings import BedrockEmbeddingProvider

        settings = replace(
            get_settings(),
            aws_region=region,
            vector_dimension=dimensions,
            embedding_provider="bedrock",
            embedding_model_id=model_id,
        )
        embedder = BedrockEmbeddingProvider(settings)

        def embed_documents(texts: list[str]) -> list[list[float]]:
            for attempt in range(1, 9):
                try:
                    return embedder.embed_documents(texts)
                except embedder.client.exceptions.ThrottlingException:
                    if attempt == 8:
                        raise
                    time.sleep(random.uniform(1.0, min(30.0, 2.0**attempt)))
            raise AssertionError("unreachable")

        return embed_documents, model_id

    if not allow_development_embeddings:
        raise SystemExit(
            "Hash embeddings are development-only. Pass "
            "--allow-development-embeddings to use them explicitly."
        )
    return (
        lambda texts: [hash_embed(text, dimensions) for text in texts],
        DEVELOPMENT_HASH_MODEL_ID,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    ap.add_argument(
        "--provider",
        choices=["bedrock", "bedrock-cohere-v4", "hash"],
        default=os.getenv("EMBEDDING_PROVIDER", "bedrock"),
    )
    ap.add_argument(
        "--dimensions",
        type=int,
        default=int(os.getenv("VECTOR_DIM", str(COHERE_EMBED_V4_DIMENSIONS))),
    )
    ap.add_argument(
        "--bedrock-model-id",
        default=os.getenv("BEDROCK_EMBED_MODEL_ID", COHERE_EMBED_V4_MODEL_ID),
    )
    ap.add_argument("--region", default=os.getenv("BEDROCK_REGION", "us-east-1"))
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument(
        "--workers",
        type=int,
        default=int(os.getenv("EMBEDDING_WORKERS", "1")),
    )
    ap.add_argument("--limit", type=int)
    ap.add_argument("--min-product-id", type=int, default=1)
    ap.add_argument("--max-product-id", type=int)
    ap.add_argument("--allow-development-embeddings", action="store_true")
    args = ap.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL or --database-url is required")
    if args.dimensions <= 0:
        raise SystemExit("--dimensions must be positive")
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be positive")
    if args.workers <= 0 or args.workers > 50:
        raise SystemExit("--workers must be between 1 and 50")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive")
    if args.min_product_id <= 0:
        raise SystemExit("--min-product-id must be positive")
    if (
        args.max_product_id is not None
        and args.max_product_id < args.min_product_id
    ):
        raise SystemExit("--max-product-id must be at least --min-product-id")

    try:
        import numpy as np
        import psycopg
        from pgvector.psycopg import register_vector
    except ImportError as exc:
        raise SystemExit("Run `uv sync --frozen` first") from exc

    embed, model_id = embedding_function(
        args.provider,
        model_id=args.bedrock_model_id,
        dimensions=args.dimensions,
        region=args.region,
        allow_development_embeddings=args.allow_development_embeddings,
    )

    with psycopg.connect(args.database_url) as conn:
        register_vector(conn)
        # `product_document.embedding_model_key` has a foreign key to
        # mosaic.embedding_model, so the model has to exist before any vector is
        # written. Registering it here means the loader cannot be run against an
        # unregistered model and silently fail at the first UPDATE.
        conn.execute(
            """
            UPDATE mosaic.embedding_model
            SET is_active = false
            WHERE is_active
              AND model_key <> %s
            """,
            (model_id,),
        )
        conn.execute(
            """
            INSERT INTO mosaic.embedding_model (
                model_key, provider, model_name, dimensions, distance_metric,
                is_active
            )
            VALUES (%s, %s, %s, %s, 'cosine', true)
            ON CONFLICT (model_key) DO UPDATE
            SET dimensions = EXCLUDED.dimensions,
                provider = EXCLUDED.provider,
                model_name = EXCLUDED.model_name,
                is_active = EXCLUDED.is_active
            """,
            (model_id, args.provider, model_id, args.dimensions),
        )
        conn.commit()
        conn.execute(
            "CREATE TEMP TABLE embedding_batch("
            "product_id bigint PRIMARY KEY, "
            f"embedding vector({args.dimensions})"
            ") ON COMMIT DELETE ROWS"
        )
        last_id = args.min_product_id - 1
        completed = 0
        committed_windows = 0
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            while True:
                if args.limit is not None and completed >= args.limit:
                    break
                page_size = min(
                    args.batch_size * args.workers,
                    (
                        args.limit - completed
                        if args.limit is not None
                        else args.batch_size * args.workers
                    ),
                )
                rows = conn.execute(
                    """
                    SELECT
                        product_id,
                        embedding_text,
                        encode(digest(embedding_text, 'sha256'), 'hex')
                    FROM mosaic_search.product_document
                    WHERE product_id > %s
                      AND (%s IS NULL OR product_id <= %s)
                      AND (
                          embedding IS NULL
                          OR embedding_model_key IS DISTINCT FROM %s
                      )
                    ORDER BY product_id
                    LIMIT %s
                    """,
                    (
                        last_id,
                        args.max_product_id,
                        args.max_product_id,
                        model_id,
                        page_size,
                    ),
                ).fetchall()
                if not rows:
                    break
                text_batches = [
                    [text for _, text, _ in rows[offset:offset + args.batch_size]]
                    for offset in range(0, len(rows), args.batch_size)
                ]
                vectors = [
                    vector
                    for vector_batch in executor.map(embed, text_batches)
                    for vector in vector_batch
                ]
                if len(vectors) != len(rows):
                    raise RuntimeError(
                        f"Embedding workers returned {len(vectors)} vectors "
                        f"for {len(rows)} products"
                    )
                with conn.cursor().copy(
                    "COPY embedding_batch(product_id, embedding) "
                    "FROM STDIN (FORMAT BINARY)"
                ) as copy:
                    copy.set_types(["int8", "vector"])
                    for (product_id, _, _), vector in zip(rows, vectors):
                        copy.write_row(
                            (product_id, np.asarray(vector, dtype=np.float32))
                        )
                conn.execute(
                    """
                    UPDATE mosaic_search.product_document AS document
                    SET embedding = batch.embedding,
                        embedding_model_key = %s,
                        embedding_updated_at = clock_timestamp()
                    FROM embedding_batch AS batch
                    WHERE document.product_id = batch.product_id
                    """,
                    (model_id,),
                )
                conn.commit()
                completed += len(rows)
                committed_windows += 1
                last_id = rows[-1][0]
                if committed_windows == 1 or committed_windows % 10 == 0:
                    print(
                        f"  committed {completed:,} products; "
                        f"last product_id={last_id:,}",
                        flush=True,
                    )
        print(
            f"Embedded {completed:,} products with model={model_id}, "
            f"dimensions={args.dimensions}, workers={args.workers}"
        )


if __name__ == "__main__":
    main()
