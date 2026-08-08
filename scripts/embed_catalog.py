#!/usr/bin/env python3
"""Populate catalog embeddings with Cohere Embed v4 through Amazon Bedrock.

Deterministic hash vectors remain available only for explicit local mechanics
tests. They are not valid workshop data or relevance evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import os
import re
import sys
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
        return lambda texts: embedder.embed_documents(texts), model_id

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
    ap.add_argument("--limit", type=int)
    ap.add_argument("--allow-development-embeddings", action="store_true")
    args = ap.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL or --database-url is required")
    if args.dimensions <= 0:
        raise SystemExit("--dimensions must be positive")
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be positive")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive")

    try:
        import numpy as np
        import psycopg
        from pgvector.psycopg import register_vector
    except ImportError as exc:
        raise SystemExit("Install config/requirements.txt first") from exc

    embed, model_id = embedding_function(
        args.provider,
        model_id=args.bedrock_model_id,
        dimensions=args.dimensions,
        region=args.region,
        allow_development_embeddings=args.allow_development_embeddings,
    )

    with psycopg.connect(args.database_url) as conn:
        register_vector(conn)
        conn.execute(
            "CREATE TEMP TABLE embedding_batch("
            "product_id bigint PRIMARY KEY, "
            f"embedding vector({args.dimensions}), "
            "embedding_content_hash text NOT NULL"
            ") ON COMMIT DELETE ROWS"
        )
        last_id = 0
        completed = 0
        while True:
            if args.limit is not None and completed >= args.limit:
                break
            page_size = min(
                args.batch_size,
                args.limit - completed if args.limit is not None else args.batch_size,
            )
            rows = conn.execute(
                """
                SELECT
                    product_id,
                    embedding_text,
                    encode(digest(embedding_text, 'sha256'), 'hex')
                FROM catalog.product
                WHERE product_id > %s
                  AND (
                      embedding IS NULL
                      OR embedding_model_id IS DISTINCT FROM %s
                      OR embedding_content_hash IS DISTINCT FROM
                         encode(digest(embedding_text, 'sha256'), 'hex')
                  )
                ORDER BY product_id
                LIMIT %s
                """,
                (last_id, model_id, page_size),
            ).fetchall()
            if not rows:
                break
            texts = [text for _, text, _ in rows]
            vectors = embed(texts)
            with conn.cursor().copy(
                "COPY embedding_batch("
                "product_id, embedding, embedding_content_hash"
                ") FROM STDIN (FORMAT BINARY)"
            ) as copy:
                copy.set_types(["int8", "vector", "text"])
                for (product_id, _, digest), vector in zip(rows, vectors):
                    copy.write_row(
                        (
                            product_id,
                            np.asarray(vector, dtype=np.float32),
                            digest,
                        )
                    )
            conn.execute(
                """
                UPDATE catalog.product AS product
                SET embedding = batch.embedding,
                    embedding_model_id = %s,
                    embedding_content_hash = batch.embedding_content_hash,
                    embedded_at = clock_timestamp()
                FROM embedding_batch AS batch
                WHERE product.product_id = batch.product_id
                """,
                (model_id,),
            )
            conn.commit()
            completed += len(rows)
            last_id = rows[-1][0]
            if completed == len(rows) or completed % max(args.batch_size * 20, 1) == 0:
                print(f"  committed {completed:,} products; last product_id={last_id:,}")
        print(
            f"Embedded {completed:,} products with model={model_id}, "
            f"dimensions={args.dimensions}"
        )


if __name__ == "__main__":
    main()
