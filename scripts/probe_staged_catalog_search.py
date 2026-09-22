#!/usr/bin/env python3
"""Inspect real-catalog retrieval using the shipped SQL and managed models.

Broken lab functions are visible only inside rollback-only transactions in the
isolated search schema. Results are observations, not replacement mission
assertions or a production performance benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lab_state import LABS, _replace_block
from scripts.prepare_staged_catalog_search import search_functions
from scripts.retrieval_profile import load_profile
from scripts.stage_real_catalog import require_aurora_writer, validate_dsn
from service.embeddings import get_embedding_provider
from service.models import RetrievalProfile
from service.rerank import get_reranker
from service.source_catalog import rerank_document


def probe(conn, requests: list[dict], output: Path) -> dict:
    """Record paired searches against one fixed catalog and embedding per request.

    Args:
        conn: Aurora connection to the prepared replacement catalog.
        requests: Explicit query, optional category and comparison purpose.
        output: Local report path, also used for the query-vector cache.

    Returns:
        Search observations with original product identities and source hashes.
    """
    functions = search_functions((ROOT / "db/sql/09_search_functions.sql").read_text())
    register_vector(conn)
    receipt = conn.execute("SELECT * FROM mosaic_catalog_search.receipt").fetchone()
    if (
        receipt is None
        or receipt["functions_sha256"] != hashlib.sha256(functions.encode()).hexdigest()
        or receipt["prepared_at"] is None
    ):
        raise ValueError(
            "Search receipt rule: prepared functions are missing or stale; prepare the staged catalog with this source before probing."
        )
    invalid = conn.execute(
        "SELECT count(*) AS n FROM pg_index WHERE indrelid='mosaic_catalog_search.product_document'::regclass AND NOT indisvalid"
    ).fetchone()["n"]
    if invalid:
        raise ValueError(
            f"Search index rule: {invalid} invalid indexes; finish index preparation before probing."
        )
    conn.commit()
    profile = RetrievalProfile()
    gates = load_profile()
    embedder = get_embedding_provider()
    reranker = get_reranker()
    cache_path = output.with_suffix(".query-vectors.json")
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    inputs = []
    for request in requests:
        query = request["query"]
        key = hashlib.sha256(
            (embedder.model_id + "\nsearch_query\n" + query).encode()
        ).hexdigest()
        vector = cache.get(key)
        if vector is None:
            vector = embedder.embed_query(query)
            cache[key] = vector
            cache_path.write_text(json.dumps(cache) + "\n")
        if (
            len(vector) != gates.vector_dimension
            or not all(math.isfinite(v) for v in vector)
            or not any(vector)
        ):
            raise ValueError(
                "Query vector rule: invalid cached dimensions or values; regenerate this query vector."
            )
        inputs.append((request, np.asarray(vector, dtype=np.float32)))
    report = {
        "dataset_id": receipt["dataset_id"],
        "catalog_sha256": receipt["catalog_sha256"],
        "projection_sha256": receipt["projection_sha256"],
        "functions_sha256": receipt["functions_sha256"],
        "query_embedding_model": embedder.model_id,
        "rerank_model": reranker.model_id,
        "rerank_input": "Preserved parent ASIN followed by unchanged source text.",
        "profile": profile.model_dump(),
        "observations": [],
        "live_catalog_promoted": False,
        "lab_example_acceptance": "not_assessed",
        "scope": "Shipped retrieval SQL over isolated source-faithful projection; does not exercise Shop, agent tools, coverage policy or workshop assertions.",
        "unknown_commerce_policy": "No price or availability filter. Include unspecified condition and sponsorship without asserting either is known.",
    }
    for state, lab in (("repaired", None), ("lab1_broken", 1), ("lab2_broken", 2)):
        current_functions = functions
        if lab is not None:
            for start, end, _, broken in LABS[lab][1]:
                current_functions = _replace_block(
                    current_functions, start, end, broken
                )
        with conn.transaction(force_rollback=True):
            conn.execute(current_functions, prepare=False)
            conn.execute("SET LOCAL statement_timeout='120s'")
            conn.execute(
                "SELECT set_config('pg_trgm.similarity_threshold',%s,true),set_config('pg_trgm.word_similarity_threshold',%s,true)",
                (
                    str(gates.trigram_similarity_gate),
                    str(gates.trigram_word_similarity_gate),
                ),
            )
            for request, vector in inputs:
                filters = {"include_refurbished": True, "include_sponsored": True}
                if request.get("category"):
                    filters["category_key"] = request["category"]
                conn.execute(
                    "SELECT mosaic_catalog_search.configure_hnsw(%s::int,%s::text,%s::int,%s::real)",
                    (
                        profile.ef_search,
                        profile.iterative_scan,
                        profile.max_scan_tuples,
                        profile.scan_mem_multiplier,
                    ),
                )
                start = time.monotonic()
                rows = conn.execute(
                    """SELECT r.*,d.parent_asin,d.category_key,
                    d.source_record_sha256,d.rerank_text
                    FROM mosaic_catalog_search.search_hybrid_rrf(
                        %s::text,%s::vector,%s::jsonb,%s::int,%s::int,%s::int,%s::int,%s::int,%s::real
                    ) r JOIN mosaic_catalog_search.product_document d USING(product_id)
                    ORDER BY r.rrf_score DESC,r.product_id""",
                    (
                        request["query"],
                        vector,
                        Jsonb(filters),
                        profile.rrf_k,
                        profile.fts_limit,
                        profile.trigram_limit,
                        profile.semantic_limit,
                        profile.fused_limit,
                        profile.trigram_threshold,
                    ),
                ).fetchall()
                elapsed = round((time.monotonic() - start) * 1000, 2)
                ranking = (
                    reranker.rerank(
                        request["query"],
                        [
                            rerank_document(row["parent_asin"], row["rerank_text"])
                            for row in rows
                        ],
                        profile.result_limit,
                    )
                    if rows
                    else []
                )
                summary = []
                for row in rows:
                    expected = sum(
                        1 / (profile.rrf_k + row[key])
                        for key in ("fts_rank", "trigram_rank", "semantic_rank")
                        if row[key] is not None
                    )
                    summary.append(
                        {
                            key: row[key]
                            for key in (
                                "parent_asin",
                                "title",
                                "category_key",
                                "source_record_sha256",
                                "fts_rank",
                                "trigram_rank",
                                "semantic_rank",
                                "rrf_score",
                            )
                        }
                    )
                    summary[-1]["rrf_arithmetic_valid"] = math.isclose(
                        row["rrf_score"], expected, rel_tol=0, abs_tol=1e-12
                    )
                item = {
                    **request,
                    "state": state,
                    "filters": filters,
                    "postgresql_single_run_ms": elapsed,
                    "result_count": len(rows),
                    "before_rerank": summary,
                    "after_rerank": [
                        {"rank": n, "score": score, **summary[index]}
                        for n, (index, score) in enumerate(ranking, 1)
                    ],
                }
                report["observations"].append(item)
                output.write_text(json.dumps(report, indent=2, default=str) + "\n")
                print(
                    json.dumps(
                        {
                            "state": state,
                            "query": request["query"],
                            "rows": len(rows),
                            "ms": elapsed,
                            "top": [r["parent_asin"] for r in item["after_rerank"][:3]],
                        }
                    ),
                    flush=True,
                )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    requests = json.loads(args.requests.read_text())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    dsn = os.getenv("DATABASE_URL", "")
    validate_dsn(dsn)
    with psycopg.connect(
        dsn,
        connect_timeout=10,
        application_name="mosaic-real-catalog-search-probe",
    ) as conn:
        # The preparation lock also excludes concurrent function experiments.
        dataset = conn.execute(
            "SELECT dataset_id FROM mosaic_catalog_search.receipt"
        ).fetchone()
        require_aurora_writer(conn, dataset[0])
        conn.row_factory = dict_row
        report = probe(conn, requests, args.report)
    report["complete"] = True
    args.report.write_text(json.dumps(report, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
