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
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.retrieval_profile import load_profile
from service.config import get_settings
from service.hnsw_presets import (
    ANCHOR_PREDICATE,
    EXACT_BASELINE_SETTINGS,
    FILTER_PRESETS,
)
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


def recall_against_truth(found: list[int], truth: list[int], *, k: int) -> float:
    """Fraction of the exact neighbours the ANN scan returned.

    Divides by the number of exact neighbours that *exist*, not by `k`. The flagship
    preset matches only 6 rows in the whole corpus, so returning all 6 is recall
    1.0 — dividing by k would report 0.6 and misrepresent the planner's correct
    decision to abandon HNSW at extreme selectivity as a retrieval failure.

    Args:
        found: Product ids the ANN scan returned.
        truth: Exact neighbour product ids, in rank order.
        k: Top-k the measurement was taken at.

    Returns:
        Recall in [0, 1]. Zero when no exact neighbours exist, because finding
        nothing among nothing is not perfect recall.
    """
    expected = truth[:k]
    if not expected:
        return 0.0
    return len(set(found) & set(expected)) / len(expected)


def artifact_from_results(
    *,
    provenance: dict[str, Any],
    index: dict[str, Any],
    exact_baseline: dict[str, Any],
    missing_predicate: dict[str, Any],
    ef_sweep: list[dict[str, Any]],
    filter_matrix: list[dict[str, Any]],
    captured_at: str,
    served_ef_search: int = 100,
) -> dict[str, Any]:
    """Assemble the artifact the HNSW instrument replays, deriving nothing silently.

    Every derived value is computed here rather than in the page, so the arithmetic
    lives beside the measurement it came from: bytes per vector, the fp32 overhead
    factor, and the sequential-scan slowdown the partial-index predicate avoids.

    `slowdown_factor` is measured against the **served** `ef_search`, not against the
    fastest point in the sweep. Comparing a 2,182 ms sequential scan to the
    cheapest sweep point yields 3,875x, which flatters the index by pricing it at a
    recall nobody runs; against the served operating point it is 805x, which is the
    comparison a reader can act on.
    """
    vectors = max(1, int(index["vector_count"]))
    payload_bytes = int(index.get("dimensions") or 0) * 4
    per_vector = round(int(index["size_bytes"]) / vectors)
    reference = next(
        (row for row in ef_sweep if row["ef_search"] == served_ef_search), None
    )
    baseline_ms = reference["server_ms"] if reference else None
    return {
        "kind": "measured",
        "captured_at": captured_at,
        "provenance": provenance,
        "index": index
        | {
            "bytes_per_vector": per_vector,
            "fp32_payload_bytes": payload_bytes,
            "overhead_factor": (
                round(per_vector / payload_bytes, 2) if payload_bytes else None
            ),
        },
        "exact_baseline": exact_baseline,
        "missing_predicate": missing_predicate
        | {
            "compared_at_ef_search": served_ef_search if baseline_ms else None,
            "slowdown_factor": (
                round(missing_predicate["server_ms"] / baseline_ms, 1)
                if baseline_ms
                else None
            ),
        },
        "ef_sweep": ef_sweep,
        "filter_matrix": filter_matrix,
    }


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


def _ann_sql(predicate: str) -> str:
    """The measured query. `embedding IS NOT NULL` repeats the partial index predicate.

    Dropping it costs three orders of magnitude for identical rows, because a
    partial index is only usable when the query restates its predicate. The
    committed figure is `missing_predicate.slowdown_factor` in
    `data/benchmarks/hnsw_measured.json`: 804.8x at the served `ef_search`,
    2,181.8 ms Sort over Seq Scan reading 2,300,855 blocks. The block count is
    stable across runs; the ratio is not, because the fast side is a few
    milliseconds and moves with cache state. Independent runs have measured 767x
    and 929x, so quote the artifact rather than a remembered number.
    """
    extra = f" AND {predicate}" if predicate else ""
    return f"""
        SELECT product_id
        FROM mosaic_search.product_document
        WHERE embedding IS NOT NULL{extra}
        ORDER BY embedding <=> %s
        LIMIT %s
    """


def _explain(connection: Any, sql: str, parameters: list[Any]) -> dict[str, Any]:
    """Return the server's own view of one execution: time, buffers, plan shape."""
    plan = connection.execute(
        f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}", parameters
    ).fetchone()["QUERY PLAN"][0]
    node = plan["Plan"]
    inner = node.get("Plans", [{}])[0] if node.get("Plans") else node
    return {
        "server_ms": round(plan["Execution Time"], 3),
        "shared_hit_blocks": node["Shared Hit Blocks"],
        "shared_read_blocks": node["Shared Read Blocks"],
        "node": inner.get("Node Type", node["Node Type"]),
        "index_name": inner.get("Index Name"),
        "estimated_total_cost": node["Total Cost"],
        "estimated_rows": node["Plan Rows"],
    }


def _exact_truth(
    connection: Any, pool: list[Any], *, predicate: str, k: int
) -> tuple[dict[int, list[int]], list[float]]:
    """Exact top-k per query vector, computed once.

    The previous shape recomputed this inside the ef_search loop, paying the 2.4-second
    sequential scan once per (query, ef) pair — seven times the necessary cost for a
    seven-value sweep, and the reason a sweep took minutes rather than seconds.
    """
    sql = _ann_sql(predicate)
    truth: dict[int, list[int]] = {}
    timings: list[float] = []
    for row in pool:
        started = time.perf_counter()
        # SET/RESET rather than SET LOCAL. psycopg's `connection.transaction()`
        # degrades to a SAVEPOINT when an implicit transaction is already open, and
        # SET LOCAL survives RELEASE SAVEPOINT — so `enable_indexscan = off` leaks
        # into every later query and the ANN measurements silently become sequential
        # scans reporting recall 1.0. Measured: 2,255 ms and 2,300,855 blocks at
        # ef_search 10, against 0.568 ms and 514 blocks when the index is used.
        # RESET in a finally block cannot leak regardless of transaction nesting.
        try:
            for setting in EXACT_BASELINE_SETTINGS:
                connection.execute(f"SET {setting}")
            found = connection.execute(sql, [row["embedding"], k]).fetchall()
        finally:
            for setting in EXACT_BASELINE_SETTINGS:
                connection.execute(f"RESET {setting.split(' =')[0]}")
        timings.append((time.perf_counter() - started) * 1000)
        truth[int(row["product_id"])] = [int(r["product_id"]) for r in found]
    return truth, timings


def _measure_point(
    connection: Any,
    *,
    pool: list[Any],
    truth: dict[int, list[int]],
    predicate: str,
    k: int,
    ef_search: int,
    profile: Any,
    mode: str,
    scan_mem_multiplier: float | None = None,
) -> dict[str, Any]:
    """One operating point: rows returned, recall, client timings, server timings."""
    sql = _ann_sql(predicate)
    multiplier = (
        profile.hnsw_scan_mem_multiplier
        if scan_mem_multiplier is None
        else scan_mem_multiplier
    )
    timings: list[float] = []
    recalls: list[float] = []
    returned: list[int] = []
    explained: dict[str, Any] = {}
    for index, row in enumerate(pool):
        with connection.transaction():
            connection.execute(
                """
                SELECT mosaic_search.configure_hnsw(
                    %s::integer, %s::text, %s::integer, %s::real
                )
                """,
                (ef_search, mode, profile.hnsw_max_scan_tuples, multiplier),
            )
            started = time.perf_counter()
            found = connection.execute(sql, [row["embedding"], k]).fetchall()
            timings.append((time.perf_counter() - started) * 1000)
            ids = [int(r["product_id"]) for r in found]
            if index == 0:
                explained = _explain(connection, sql, [row["embedding"], k])
        returned.append(len(ids))
        recalls.append(recall_against_truth(ids, truth[int(row["product_id"])], k=k))
    return {
        "ef_search": ef_search,
        "iterative_scan": mode,
        "scan_mem_multiplier": multiplier,
        "rows_returned": round(statistics.mean(returned), 2),
        "min_rows_returned": min(returned),
        "recall_at_k": round(statistics.mean(recalls), 4),
        "client_p50_ms": round(percentile(timings, 0.50), 3),
        "client_p95_ms": round(percentile(timings, 0.95), 3),
        "client_mean_ms": round(statistics.mean(timings), 3),
        **explained,
    }


def _assert_used_the_index(point: dict[str, Any], *, ef_search: int) -> None:
    """An unfiltered ANN measurement that did not use the HNSW index is not a measurement.

    This exists because the failure is silent and plausible: a leaked
    `enable_indexscan = off` turns every ANN query into the exact query, so recall
    comes back 1.0 — the best possible number — while the latency is 1,000x wrong.
    A sweep in this shape was captured twice before the guard was added.
    """
    if (
        "Index Scan" not in point["node"]
        or point["index_name"] != INDEX_NAME.split(".")[-1]
    ):
        raise SystemExit(
            f"benchmark refuses to record ef_search={ef_search}: "
            f"found plan node {point['node']!r} on index {point['index_name']!r} "
            f"with {point['shared_hit_blocks']} shared hits; "
            f"fix: the HNSW index was not used, so this is the exact query wearing an "
            f"ANN label — check for a leaked `enable_indexscan = off` and that the "
            f"query repeats the partial-index predicate `embedding IS NOT NULL`"
        )


def _capture_ef_sweep(
    connection: Any,
    *,
    pool: list[Any],
    k: int,
    ef_values: list[int],
    profile: Any,
    mode: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The unfiltered recall/latency curve, plus the exact baseline it is measured against."""
    print("  exact ground truth (unfiltered) ...", flush=True)
    truth, timings = _exact_truth(connection, pool, predicate="", k=k)
    # The baseline's own block count has to be taken with the planner settings still
    # applied, or it measures the ANN query instead. Same SET/RESET shape as above.
    try:
        for setting in EXACT_BASELINE_SETTINGS:
            connection.execute(f"SET {setting}")
        exact_plan = _explain(connection, _ann_sql(""), [pool[0]["embedding"], k])
    finally:
        for setting in EXACT_BASELINE_SETTINGS:
            connection.execute(f"RESET {setting.split(' =')[0]}")
    baseline = {
        "p50_ms": round(percentile(timings, 0.50), 1),
        "p95_ms": round(percentile(timings, 0.95), 1),
        "mean_ms": round(statistics.mean(timings), 1),
        "server_ms": exact_plan["server_ms"],
        "shared_hit_blocks": exact_plan["shared_hit_blocks"],
        "node": exact_plan["node"],
        "method": ", ".join(EXACT_BASELINE_SETTINGS),
    }
    sweep = []
    for ef_search in ef_values:
        point = _measure_point(
            connection,
            pool=pool,
            truth=truth,
            predicate="",
            k=k,
            ef_search=ef_search,
            profile=profile,
            mode=mode,
        )
        _assert_used_the_index(point, ef_search=ef_search)
        sweep.append(point)
        print(
            f"  ef_search {ef_search:>4}: {point['server_ms']:>8} ms server, "
            f"{point['shared_hit_blocks']:>7} blocks, recall {point['recall_at_k']}",
            flush=True,
        )
    return sweep, baseline


def _capture_missing_predicate(
    connection: Any, *, anchor: Any, k: int, profile: Any, mode: str
) -> dict[str, Any]:
    """The same query without the partial-index predicate: the 929x mistake."""
    sql = """
        SELECT product_id
        FROM mosaic_search.product_document
        ORDER BY embedding <=> %s
        LIMIT %s
    """
    with connection.transaction():
        connection.execute(
            "SELECT mosaic_search.configure_hnsw(%s::integer, %s::text)",
            (profile.hnsw_ef_search, mode),
        )
        measured = _explain(connection, sql, [anchor["embedding"], k])
    print(
        f"  no predicate: {measured['node']}, {measured['server_ms']} ms, "
        f"{measured['shared_hit_blocks']} blocks",
        flush=True,
    )
    return measured


def _capture_filter_matrix(
    connection: Any,
    *,
    pool: list[Any],
    k: int,
    profile: Any,
    work_mem_mb: int,
) -> list[dict[str, Any]]:
    """Every preset across the three scan modes and two memory budgets.

    The budget dimension exists because `max_scan_tuples` is the knob whose name
    suggests it should fix an empty filtered result and provably does not: measured 0
    rows at 20K, 100K, 500K and 1M alike, where doubling
    `work_mem x scan_mem_multiplier` returned all ten.
    """
    levels = []
    for preset in FILTER_PRESETS:
        print(f"  preset {preset.key} ...", flush=True)
        truth, _ = _exact_truth(connection, pool, predicate=preset.predicate_sql, k=k)
        exact_rows = round(statistics.mean([len(v) for v in truth.values()]), 2)
        modes = []
        for mode in ("off", "strict_order", "relaxed_order"):
            for multiplier in (1, profile.hnsw_scan_mem_multiplier):
                point = _measure_point(
                    connection,
                    pool=pool,
                    truth=truth,
                    predicate=preset.predicate_sql,
                    k=k,
                    ef_search=profile.hnsw_ef_search,
                    profile=profile,
                    mode=mode,
                    scan_mem_multiplier=multiplier,
                )
                point["scan_mem_mb"] = work_mem_mb * multiplier
                modes.append(point)
        levels.append(
            {
                "preset": preset.key,
                "label": preset.label,
                "character": preset.character,
                "predicate_sql": preset.predicate_sql,
                "matching_rows": preset.matching_rows,
                "selectivity": round(preset.matching_rows / 500_000, 6),
                "exact_rows_found": exact_rows,
                "modes": modes,
            }
        )
    return levels


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
    parser.add_argument(
        "--filter-preset-matrix",
        action="store_true",
        help=(
            "Also sweep the six filter presets across the three iterative_scan modes "
            "and two memory budgets, and emit the instrument artifact."
        ),
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("data/benchmarks/hnsw_measured.json"),
        help="Where the HNSW instrument reads its replayed measurements from.",
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

        # Exact ground truth is computed once per query vector, above the ef_search
        # loop. It used to be recomputed inside it, paying the 2.4-second sequential
        # scan once per (query, ef) pair — seven times the necessary cost for a
        # seven-value sweep, with an identical answer every time.
        exact_by_query: dict[Any, set[Any]] = {}
        exact_timings: list[float] = []
        for row in pool:
            started = time.perf_counter()
            # SET/RESET, not SET LOCAL: see _exact_truth for why transaction scope
            # cannot be trusted to contain these settings.
            try:
                connection.execute("SET enable_indexscan = off")
                connection.execute("SET enable_bitmapscan = off")
                exact = connection.execute(
                    f"""
                    SELECT product_id
                    FROM mosaic_search.product_document
                    WHERE embedding IS NOT NULL {where_sql}
                    ORDER BY embedding <=> %s
                    LIMIT %s
                    """,
                    [*filter_parameters, row["embedding"], args.k],
                ).fetchall()
            finally:
                connection.execute("RESET enable_indexscan")
                connection.execute("RESET enable_bitmapscan")
            exact_timings.append((time.perf_counter() - started) * 1000)
            exact_by_query[row["product_id"]] = {
                result["product_id"] for result in exact
            }

        results = []
        for ef_search in ef_search_values:
            timings: list[float] = []
            recalls: list[float] = []
            sample_plan = None
            for index, row in enumerate(pool):
                query_vector = row["embedding"]
                exact_ids = exact_by_query[row["product_id"]]

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

        ef_sweep: list[dict[str, Any]] = []
        missing_predicate: dict[str, Any] = {}
        filter_matrix: list[dict[str, Any]] = []
        if args.filter_preset_matrix:
            print("capturing the instrument artifact ...", flush=True)
            anchor_pool = connection.execute(
                f"""
                SELECT product_id, embedding
                FROM mosaic_search.product_document
                WHERE embedding IS NOT NULL AND {ANCHOR_PREDICATE}
                ORDER BY product_id
                LIMIT %s
                """,
                (args.queries,),
            ).fetchall()
            ef_sweep, artifact_baseline = _capture_ef_sweep(
                connection,
                pool=anchor_pool,
                k=args.k,
                ef_values=ef_search_values,
                profile=profile,
                mode=iterative_scan,
            )
            missing_predicate = _capture_missing_predicate(
                connection,
                anchor=anchor_pool[0],
                k=args.k,
                profile=profile,
                mode=iterative_scan,
            )
            work_mem_mb = int(
                connection.execute(
                    "SELECT (setting::bigint / 1024) AS mb FROM pg_settings "
                    "WHERE name = 'work_mem'"
                ).fetchone()["mb"]
            )
            filter_matrix = _capture_filter_matrix(
                connection,
                pool=anchor_pool,
                k=args.k,
                profile=profile,
                work_mem_mb=work_mem_mb,
            )

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

    if args.filter_preset_matrix:
        artifact = artifact_from_results(
            provenance={
                "benchmark_run_id": str(benchmark_run_id),
                "source_revision": settings.source_revision,
                "source_worktree_dirty": settings.source_worktree_dirty,
                "dataset_manifest_sha256": settings.dataset_manifest_sha256,
                "database_instance_id": environment["database_instance_id"],
                "database_version": environment["database_version"],
                "vector_extension_version": environment["vector_extension_version"],
                "instance_class": args.instance_class,
                "query_sample_sha256": query_sample_sha256,
                "query_sample_product_ids": query_sample_ids,
                "queries": args.queries,
                "k": args.k,
                "iterative_scan": iterative_scan,
                "work_mem_mb": work_mem_mb,
            },
            index={
                "name": INDEX_NAME,
                "definition": environment["index_definition"],
                "size_bytes": environment["index_size_bytes"],
                "vector_count": vector_count,
                "dimensions": profile.vector_dimension,
                "m": profile.hnsw_m,
                "ef_construction": profile.hnsw_ef_construction,
            },
            exact_baseline=artifact_baseline,
            missing_predicate=missing_predicate,
            ef_sweep=ef_sweep,
            filter_matrix=filter_matrix,
            captured_at=completed_at.isoformat(),
        )
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_text(
            json.dumps(artifact, indent=2, default=str) + "\n", encoding="utf-8"
        )
        print(f"wrote the instrument artifact to {args.artifact}")

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
