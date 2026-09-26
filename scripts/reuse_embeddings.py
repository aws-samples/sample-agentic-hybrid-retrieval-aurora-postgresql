#!/usr/bin/env python3
"""Write verified embedding batches for products whose vectors already exist in a staged dataset.

A version-2 selection carries an earlier dataset's products unchanged. Their
vectors are already in `mosaic_catalog_stage.product`, so this tool writes the
same `.npz` batch files `embed_real_catalog.py` would produce for them, from
the database instead of the model, and only for batches whose every product
matches by parent ASIN and embedding-text hash. Every other batch is left for
the embedding run. No model is invoked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import psycopg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.embed_real_catalog import (
    COHERE_EMBED_V4_MODEL_ID,
    batch_identity,
    iter_batches,
    validate_vectors,
    verified_selection,
)
from scripts.prepare_real_catalog import canonical, sha256
from scripts.stage_real_catalog import validate_dsn


def reuse(selection: Path, dsn: str, dataset: str) -> dict:
    verified_selection(selection)
    output = selection / "embeddings"
    output.mkdir(exist_ok=True)
    written = reused = skipped = 0
    started = time.monotonic()
    with psycopg.connect(
        dsn, connect_timeout=10, application_name="mosaic-embedding-reuse"
    ) as conn:
        for rows in iter_batches(selection):
            identity = batch_identity(rows)
            key = sha256(canonical(identity))
            path = output / f"{key}.npz"
            if path.exists():
                reused += 1
                continue
            found = conn.execute(
                """SELECT parent_asin, embedding::text FROM mosaic_catalog_stage.product
                   WHERE dataset_id=%s AND parent_asin=ANY(%s) AND embedding IS NOT NULL
                     AND embedding_model_key=%s AND embedded_input_sha256=embedding_text_sha256
                     AND embedding_text_sha256=ANY(%s)""",
                (
                    dataset,
                    identity["products"],
                    COHERE_EMBED_V4_MODEL_ID,
                    identity["text_sha256"],
                ),
            ).fetchall()
            vectors_by_asin = {asin: json.loads(vector) for asin, vector in found}
            if any(asin not in vectors_by_asin for asin in identity["products"]):
                skipped += 1
                continue
            vectors = validate_vectors(
                [vectors_by_asin[asin] for asin in identity["products"]], len(rows)
            )
            characters = sum(len(row["embedding_text"]) for row in rows)
            metadata = {
                "identity": identity,
                "vector_sha256": hashlib.sha256(vectors.tobytes()).hexdigest(),
                "input_tokens": None,
                "input_characters": characters,
                "request_started_at": None,
                "request_completed_at": None,
                "retry_attempts": 0,
                "request_id": None,
                "elapsed_seconds": 0.0,
                "reused_from_dataset": dataset,
            }
            temporary = path.with_suffix(".partial")
            with temporary.open("wb") as stream:
                np.savez_compressed(
                    stream, vectors=vectors, metadata=canonical(metadata)
                )
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
            written += 1
            if written % 200 == 0:
                print(
                    json.dumps(
                        {
                            "written": written,
                            "skipped": skipped,
                            "elapsed_seconds": round(time.monotonic() - started),
                        }
                    ),
                    flush=True,
                )
    report = {
        "batches_written": written,
        "batches_already_present": reused,
        "batches_left_for_embedding": skipped,
        "seconds": round(time.monotonic() - started, 1),
    }
    print(json.dumps(report), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument(
        "--dataset-id",
        required=True,
        help="staged dataset holding the reusable vectors",
    )
    args = parser.parse_args()
    dsn = os.getenv("DATABASE_URL", "")
    validate_dsn(dsn)
    reuse(args.selection, dsn, args.dataset_id)


if __name__ == "__main__":
    main()
