#!/usr/bin/env python3
"""Cache the three search lists for Lab 2's judged queries and chair controls.

Grading a Lab 2 proposal replays fusion over 141 ESCI queries and four reviewed
chair controls. Running the three installed search functions live for all of
them takes minutes, so this saves each query's lists once, at limits at least as
large as any proposal may request. A proposal with smaller limits reads a prefix
of each list: every search function orders by its own rank before applying its
limit. The cache records the catalog hash and a hash of the installed function
definitions, and the grader refuses it when either has changed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import struct
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

MAX_LIMITS = {"fts": 240, "trigram": 160, "vector": 300}
CHAIR_CONTROLS = (
    ("requirements-4", 1490476),
    ("requirements-5", 1389794),
    ("requirements-6", 1379290),
)
LAB3_CHAIR_CONTROL = {
    "id": "lab-3-chair-search",
    "query": "Steelcase Gesture adjustable lumbar movable arms ergonomic chair",
    "filters": {"domain": "home_office", "category_key": "chair"},
    "target": 1540761,
}
ARM_SQL = {
    "fts": "SELECT product_id, fts_rank AS r FROM {s}.search_fts(%s, %s::jsonb, %s)",
    "trigram": (
        "SELECT product_id, trigram_rank AS r FROM {s}.search_trigram("
        "%s, %s::jsonb, %s, %s::real)"
    ),
    "vector": (
        "SELECT product_id, semantic_rank AS r FROM {s}.search_vector("
        "%s::vector, %s::jsonb, %s)"
    ),
}


def decode_vector(encoded: str) -> str:
    """Render a cached little-endian float32 vector as pgvector text."""
    values = struct.unpack("<1024f", base64.b64decode(encoded))
    return "[" + ",".join(repr(value) for value in values) + "]"


def encode_vector(values: list[float]) -> str:
    return base64.b64encode(struct.pack(f"<{len(values)}f", *values)).decode()


def search_identity(connection) -> dict[str, str]:
    """The catalog and function definitions these lists depend on."""
    from service.catalog_runtime import search_schema

    schema = search_schema()
    catalog = connection.execute(
        f"SELECT catalog_sha256 FROM {schema}.receipt WHERE singleton"
    ).fetchone()["catalog_sha256"]
    definitions = connection.execute(
        "SELECT string_agg(pg_get_functiondef(p.oid), E'\\n' ORDER BY p.proname) AS d "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = %s AND p.proname IN "
        "('search_fts', 'search_trigram', 'search_vector', 'matches_filter_values')",
        (schema,),
    ).fetchone()["d"]
    return {
        "catalog_sha256": catalog,
        "functions_sha256": hashlib.sha256(definitions.encode()).hexdigest(),
    }


def search_lists(connection, query: str, filters: dict, vector: str) -> dict:
    """Run the three installed searches at the cache limits; rows are [id, rank]."""
    from scripts.retrieval_profile import load_profile
    from service.catalog_runtime import search_schema

    schema = search_schema()
    encoded = json.dumps(filters)
    threshold = load_profile().trigram_threshold
    arguments = {
        "fts": (query, encoded, MAX_LIMITS["fts"]),
        "trigram": (query, encoded, MAX_LIMITS["trigram"], threshold),
        "vector": (vector, encoded, MAX_LIMITS["vector"]),
    }
    lists = {}
    for name, sql in ARM_SQL.items():
        rows = connection.execute(sql.format(s=schema), arguments[name]).fetchall()
        lists[name] = [[row["product_id"], row["r"]] for row in rows]
    return lists


def controls(service) -> list[dict]:
    verification = json.loads(
        (REPO / "data/evals/real_catalog_exercise_verification.json").read_text()
    )
    cases = {case["id"]: case for case in verification["cases"]}
    chosen = [
        {
            "id": case_id,
            "query": cases[case_id]["query"],
            "filters": cases[case_id]["filters"],
            "target": target,
        }
        for case_id, target in CHAIR_CONTROLS
    ]
    chosen.append(dict(LAB3_CHAIR_CONTROL))
    for control in chosen:
        control["vector"] = encode_vector(service.embed_query(control["query"]))
    return chosen


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    import psycopg
    from psycopg.rows import dict_row

    from scripts.retrieval_profile import load_profile
    from service.retrieval import RetrievalService

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output", type=Path, default=REPO / "data/evals/lab2_search_cache.json"
    )
    args = parser.parse_args()
    subset = json.loads((REPO / "data/evals/esci_judged_subset.json").read_text())
    vectors = json.loads((REPO / "data/evals/esci_query_vectors.json").read_text())
    service = RetrievalService()
    started = time.perf_counter()
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        identity = search_identity(conn)
        queries = {
            str(case["query_id"]): search_lists(
                conn,
                case["query"],
                case["filters"],
                decode_vector(vectors["vectors"][str(case["query_id"])]),
            )
            for case in subset["queries"]
        }
        chair = controls(service)
        for control in chair:
            control["lists"] = search_lists(
                conn,
                control["query"],
                control["filters"],
                decode_vector(control["vector"]),
            )
        conn.rollback()
    args.output.write_text(
        json.dumps(
            {
                **identity,
                "dataset_id": subset["dataset_id"],
                "embedding_model_id": vectors["embedding_model_id"],
                "limits": MAX_LIMITS,
                "trigram_threshold": load_profile().trigram_threshold,
                "queries": queries,
                "chair_controls": chair,
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    print(
        f"{len(queries)} queries and {len(chair)} chair controls cached in "
        f"{time.perf_counter() - started:.0f}s -> {args.output}"
    )


if __name__ == "__main__":
    main()
