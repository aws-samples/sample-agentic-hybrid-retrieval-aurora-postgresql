#!/usr/bin/env python3
"""Measure filtered HNSW latency and recall on the production Aurora path.

The exact baseline forces a sequential scan inside its transaction. The ANN
path configures every HNSW session through `mosaic_search.configure_hnsw`, the
same function used by served retrieval. Each run is persisted to
`mosaic_bench` with its source, dataset, Aurora, index, filter, and query-sample
identity; the JSON output is a portable copy of the same measured record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.retrieval_profile import load_profile
from service.config import get_settings
from service.models import RetrievalProfile

INDEX_NAME = "mosaic_search.product_document_embedding_hnsw_cosine_idx"
EXACT_BASELINE = (
    "filtered cosine top-k with enable_indexscan=off and enable_bitmapscan=off"
)


def percentile(values: list[float], p: float) -> float:
    """Return the nearest-rank percentile for a non-empty measurement list."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * p)))
    return ordered[index]


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _configure_hnsw(
    connection: Any,
    *,
    ef_search: int,
    profile: Any,
    mode: str,
) -> None:
    connection.execute(
        """
        SELECT mosaic_search.configure_hnsw(
            %s::integer, %s::text, %s::integer, %s::real
        )
        """,
        (
            ef_search,
            mode,
            profile.hnsw_max_scan_tuples,
            profile.hnsw_scan_mem_multiplier,
        ),
    )


def _persist_measurements(
    connection: Any,
    *,
    benchmark_run_id: Any,
    result: dict[str, Any],
    filter_profile: dict[str, Any],
) -> None:
    rows = (
        (
            "latency_ms",
            result["latency_ms"]["p50"],
            "ms",
            50,
            result["sample_explain"],
        ),
        ("latency_ms", result["latency_ms"]["p95"], "ms", 95, None),
        ("latency_ms", result["latency_ms"]["mean"], "ms", None, None),
        ("recall_at_k", result["recall_at_k"], "ratio", None, None),
    )
    for name, value, unit, percentile_value, plan in rows:
        connection.execute(
            """
            INSERT INTO mosaic_bench.measurement (
                benchmark_run_id, measurement_name, measurement_value,
                unit, percentile, filter_profile, plan_json
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
            """,
            (
                benchmark_run_id,
                name,
                value,
                unit,
                percentile_value,
                json.dumps(filter_profile),
                json.dumps(plan) if plan is not None else None,
            ),
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--ef-search", type=int, nargs="+")
    parser.add_argument(
        "--iterative-scan",
        choices=["off", "strict_order", "relaxed_order"],
    )
    parser.add_argument(
        "--filter-domain",
        choices=["consumer_electronics", "running_fitness", "home_office"],
    )
    parser.add_argument(
        "--instance-class",
        default=os.getenv("AURORA_INSTANCE_CLASS"),
    )
    parser.add_argument("--run-label")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/results/hnsw.json"),
    )
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit(
            "Aurora rule: DATABASE_URL or --database-url is required; "
            "point it at the workshop Aurora PostgreSQL writer."
        )
    if not args.instance_class:
        raise SystemExit(
            "Benchmark provenance is incomplete: instance class is empty; "
            "set AURORA_INSTANCE_CLASS or pass --instance-class."
        )
    if args.queries < 1 or args.k < 1:
        raise SystemExit(
            "Benchmark sizes must be positive; "
            f"found queries={args.queries}, k={args.k}; "
            "pass positive --queries and --k values."
        )

    try:
        import psycopg
        from pgvector.psycopg import register_vector
        from psycopg.rows import dict_row
    except ImportError as error:
        raise SystemExit(
            "Benchmark dependencies are missing; run `uv sync --frozen`."
        ) from error

    profile = load_profile()
    runtime_profile = RetrievalProfile()
    ef_search_values = args.ef_search or [profile.hnsw_ef_search]
    iterative_scan = args.iterative_scan or runtime_profile.iterative_scan
    settings = get_settings()
    run_label = args.run_label or (
        f"hnsw-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)

    where_sql = "AND domain = %s" if args.filter_domain else ""
    filter_parameters = [args.filter_domain] if args.filter_domain else []
    with psycopg.connect(
        args.database_url,
        row_factory=dict_row,
    ) as connection:
        register_vector(connection)
        environment = dict(
            connection.execute(
                f"""
                SELECT aurora_db_instance_identifier() AS database_instance_id,
                       current_setting('server_version') AS database_version,
                       (
                           SELECT extversion FROM pg_extension
                           WHERE extname = 'vector'
                       ) AS vector_extension_version,
                       pg_relation_size(%s::regclass) AS index_size_bytes,
                       pg_get_indexdef(%s::regclass) AS index_definition,
                       count(*) FILTER (WHERE embedding IS NOT NULL) AS vector_count,
                       count(*) FILTER (
                           WHERE embedding IS NOT NULL
                           {where_sql}
                       ) AS filtered_vector_count
                FROM mosaic_search.product_document
                """,
                [INDEX_NAME, INDEX_NAME, *filter_parameters],
            ).fetchone()
        )
        vector_count = int(environment["vector_count"])
        filtered_vector_count = int(environment["filtered_vector_count"])
        if filtered_vector_count < args.queries:
            raise SystemExit(
                "Benchmark query pool is too small: "
                f"found {filtered_vector_count} eligible vectors for "
                f"--queries {args.queries}; reduce --queries or broaden the filter."
            )
        filter_selectivity = filtered_vector_count / vector_count
        pool = connection.execute(
            f"""
            SELECT product_id, embedding
            FROM mosaic_search.product_document
            WHERE embedding IS NOT NULL {where_sql}
            ORDER BY product_id
            LIMIT %s
            """,
            [*filter_parameters, args.queries],
        ).fetchall()
        query_sample_ids = [int(row["product_id"]) for row in pool]
        query_sample_sha256 = _sha256_json(query_sample_ids)

        profile_record = {
            "dimensions": profile.vector_dimension,
            "distance_metric": "cosine",
            "hnsw_m": profile.hnsw_m,
            "hnsw_ef_construction": profile.hnsw_ef_construction,
            "iterative_scan": iterative_scan,
            "max_scan_tuples": profile.hnsw_max_scan_tuples,
            "scan_mem_multiplier": profile.hnsw_scan_mem_multiplier,
            "filter_domain": args.filter_domain,
            "filter_selectivity": filter_selectivity,
        }
        profile_key = f"hnsw-{_sha256_json(profile_record)[:20]}"
        connection.execute(
            """
            INSERT INTO mosaic_bench.profile (
                profile_key, description, vector_count, dimensions,
                distance_metric, hnsw_m, hnsw_ef_construction, hnsw_ef_search,
                iterative_scan, max_scan_tuples, scan_mem_multiplier,
                filter_selectivity, result_kind, environment_label, metadata
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                'measured', 'aurora-postgresql', %s::jsonb
            )
            ON CONFLICT (profile_key) DO UPDATE
            SET vector_count = EXCLUDED.vector_count,
                filter_selectivity = EXCLUDED.filter_selectivity,
                metadata = EXCLUDED.metadata
            """,
            (
                profile_key,
                "Filtered HNSW recall and latency against an exact Aurora baseline",
                vector_count,
                profile.vector_dimension,
                "cosine",
                profile.hnsw_m,
                profile.hnsw_ef_construction,
                profile.hnsw_ef_search,
                iterative_scan,
                profile.hnsw_max_scan_tuples,
                profile.hnsw_scan_mem_multiplier,
                filter_selectivity,
                json.dumps(
                    {
                        "filter_domain": args.filter_domain,
                        "index_definition": environment["index_definition"],
                    }
                ),
            ),
        )
        benchmark_run_id = connection.execute(
            """
            INSERT INTO mosaic_bench.run (
                profile_key, run_label, database_instance_id, database_version,
                vector_extension_version, instance_class, dataset_manifest,
                source_revision, source_worktree_dirty,
                dataset_manifest_sha256, index_size_bytes, metadata
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
            )
            RETURNING benchmark_run_id
            """,
            (
                profile_key,
                run_label,
                environment["database_instance_id"],
                environment["database_version"],
                environment["vector_extension_version"],
                args.instance_class,
                "data/full/manifest.json",
                settings.source_revision,
                settings.source_worktree_dirty,
                settings.dataset_manifest_sha256,
                environment["index_size_bytes"],
                json.dumps(
                    {
                        "exact_baseline": EXACT_BASELINE,
                        "query_sample_product_ids": query_sample_ids,
                        "query_sample_sha256": query_sample_sha256,
                        "filter_domain": args.filter_domain,
                        "filter_selectivity": filter_selectivity,
                        "ef_search_values": ef_search_values,
                        "k": args.k,
                    }
                ),
            ),
        ).fetchone()["benchmark_run_id"]
        connection.commit()

        results = []
        for ef_search in ef_search_values:
            timings: list[float] = []
            recalls: list[float] = []
            sample_plan = None
            for index, row in enumerate(pool):
                query_vector = row["embedding"]
                with connection.transaction():
                    connection.execute("SET LOCAL enable_indexscan = off")
                    connection.execute("SET LOCAL enable_bitmapscan = off")
                    exact = connection.execute(
                        f"""
                        SELECT product_id
                        FROM mosaic_search.product_document
                        WHERE embedding IS NOT NULL {where_sql}
                        ORDER BY embedding <=> %s
                        LIMIT %s
                        """,
                        [*filter_parameters, query_vector, args.k],
                    ).fetchall()
                exact_ids = {result["product_id"] for result in exact}

                with connection.transaction():
                    _configure_hnsw(
                        connection,
                        ef_search=ef_search,
                        profile=profile,
                        mode=iterative_scan,
                    )
                    started = time.perf_counter()
                    ann = connection.execute(
                        f"""
                        SELECT product_id
                        FROM mosaic_search.product_document
                        WHERE embedding IS NOT NULL {where_sql}
                        ORDER BY embedding <=> %s
                        LIMIT %s
                        """,
                        [*filter_parameters, query_vector, args.k],
                    ).fetchall()
                    timings.append((time.perf_counter() - started) * 1000)
                    ann_ids = {result["product_id"] for result in ann}
                    recalls.append(len(exact_ids & ann_ids) / max(1, len(exact_ids)))
                    if index == 0:
                        sample_plan = connection.execute(
                            f"""
                            EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON)
                            SELECT product_id
                            FROM mosaic_search.product_document
                            WHERE embedding IS NOT NULL {where_sql}
                            ORDER BY embedding <=> %s
                            LIMIT %s
                            """,
                            [*filter_parameters, query_vector, args.k],
                        ).fetchone()["QUERY PLAN"]

            result = {
                "ef_search": ef_search,
                "iterative_scan": iterative_scan,
                "filter_domain": args.filter_domain,
                "filter_selectivity": filter_selectivity,
                "queries": len(timings),
                "k": args.k,
                "latency_ms": {
                    "p50": round(percentile(timings, 0.50), 3),
                    "p95": round(percentile(timings, 0.95), 3),
                    "mean": round(statistics.mean(timings), 3),
                },
                "recall_at_k": round(statistics.mean(recalls), 5),
                "sample_explain": sample_plan,
            }
            _persist_measurements(
                connection,
                benchmark_run_id=benchmark_run_id,
                result=result,
                filter_profile={
                    "domain": args.filter_domain,
                    "selectivity": filter_selectivity,
                    "ef_search": ef_search,
                    "iterative_scan": iterative_scan,
                    "exact_baseline": EXACT_BASELINE,
                },
            )
            connection.commit()
            results.append(result)

        completed_at = datetime.now(UTC)
        connection.execute(
            """
            UPDATE mosaic_bench.run
            SET completed_at = %s
            WHERE benchmark_run_id = %s
            """,
            (completed_at, benchmark_run_id),
        )
        connection.commit()

    output = {
        "kind": "measured",
        "benchmark_run_id": str(benchmark_run_id),
        "generated_at": completed_at.isoformat(),
        "source": {
            "revision": settings.source_revision,
            "worktree_dirty": settings.source_worktree_dirty,
        },
        "dataset_manifest_sha256": settings.dataset_manifest_sha256,
        "aurora": {
            "database_instance_id": environment["database_instance_id"],
            "database_version": environment["database_version"],
            "vector_extension_version": environment["vector_extension_version"],
            "instance_class": args.instance_class,
        },
        "index": {
            "name": INDEX_NAME,
            "size_bytes": environment["index_size_bytes"],
            "definition": environment["index_definition"],
        },
        "query_sample_sha256": query_sample_sha256,
        "exact_baseline": EXACT_BASELINE,
        "results": results,
    }
    args.output.write_text(
        json.dumps(output, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
