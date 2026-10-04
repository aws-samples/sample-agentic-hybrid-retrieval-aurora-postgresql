#!/usr/bin/env python3
"""Embed the held-out ESCI queries and their eligible products with a small model.

`scripts/evals/hybrid_payoff.py --small-vectors DIR` reads the output: one
`<category>.npz` per held-out filter and `queries.npz`. Products are embedded
from the same `embedding_text` Cohere Embed v4 embedded, so only the model
differs. The model runs locally (Apple GPU when available) and needs packages
the service does not ship:

    uv run --with sentence-transformers python scripts/evals/embed_small_model.py \
        --out .local/hybrid-payoff

The export reads Aurora inside a read-only transaction and writes nothing there.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

MODEL_ID = "BAAI/bge-small-en-v1.5"
# bge-small-en-v1.5's documented retrieval instruction, applied to queries only.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
QUERIES = REPO / "data/evals/esci_held_out_queries.jsonl"


def held_out_queries() -> list[dict]:
    return [json.loads(line) for line in QUERIES.open() if line.strip()]


def export_texts(filters: dict) -> list[dict]:
    """Every product the filter admits, with the text its stored vector came from."""
    import psycopg
    from psycopg.rows import dict_row

    from service.catalog_runtime import search_schema

    schema = search_schema()
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = 0")
            cursor.execute(
                f"SELECT product_id, embedding_text FROM {schema}.product_document d "
                f"WHERE {schema}.matches_filters(d, %s::jsonb) ORDER BY product_id",
                (json.dumps(filters),),
            )
            rows = cursor.fetchall()
        conn.rollback()
    return rows


def device() -> str:
    import torch

    return "mps" if torch.backends.mps.is_available() else "cpu"


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    import numpy as np
    from sentence_transformers import SentenceTransformer

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    queries = held_out_queries()
    filter_sets = {q["filters"]["category_key"]: q["filters"] for q in queries}
    model = SentenceTransformer(MODEL_ID, device=device())
    model.max_seq_length = 512
    for category, filters in sorted(filter_sets.items()):
        started = time.monotonic()
        rows = export_texts(filters)
        vectors = model.encode(
            [row["embedding_text"] for row in rows],
            batch_size=64,
            normalize_embeddings=True,
        ).astype(np.float32)
        ids = np.array([row["product_id"] for row in rows])
        np.savez(args.out / f"{category}.npz", ids=ids, vecs=vectors)
        print(f"{category}: {len(rows)} products in {time.monotonic() - started:.0f}s")
    query_vectors = model.encode(
        [QUERY_INSTRUCTION + q["query"] for q in queries],
        batch_size=64,
        normalize_embeddings=True,
    ).astype(np.float32)
    np.savez(
        args.out / "queries.npz",
        ids=np.array([q["query_id"] for q in queries]),
        vecs=query_vectors,
    )
    (args.out / "model.json").write_text(json.dumps({"model_id": MODEL_ID}) + "\n")
    print(f"queries: {len(queries)}")


if __name__ == "__main__":
    main()
