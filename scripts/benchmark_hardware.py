#!/usr/bin/env python3
"""Compare two Aurora instance classes on the same Mosaic catalog and workload.

Two clusters restored from the same source hold byte-identical rows, vectors,
indexes and exact ground truth. Each is driven from the same in-VPC client
with the same anchors, presets, retrieval settings, query sequence,
concurrency levels and durations, so the only variable is the instance. The
runner records what it can verify about cache state instead of asserting a
cache condition: buffer statistics before and after every phase, the
Optimized Reads cache size and hit fields where the engine reports them, and
a labelled warm-up that is never counted as a measurement.

The runner makes no embedding or reranking call. Query vectors are the
anchors' stored embeddings; recall is scored against the exact neighbours
seeded in each cluster, joined on the same catalog, anchor-set and predicate
identities the served instrument uses.

Usage
-----
    CONTROL_DATABASE_URL=... TEST_DATABASE_URL=... \\
    uv run python scripts/benchmark_hardware.py \\
        --control-label db.r8g.2xlarge --test-label db.r8gd.2xlarge \\
        --control-instance mosaic-hw-r8g-w --test-instance mosaic-hw-r8gd-w \\
        --concurrency 1 4 8 16 --duration 60 --warmup 45 --trials 2 \\
        --price-control 1.436 --price-test 1.6224 \\
        --output data/benchmarks/hardware_comparison.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.benchmark_hnsw import _sha256_json, percentile, recall_against_truth
from scripts.benchmark_index_build import build_once
from scripts.retrieval_profile import explain, load_profile
from scripts.seed_exact_neighbors import load_ground_truth
from service.catalog_runtime import (
    active_dataset,
    catalog_indexes,
    product_document,
    search_schema,
)
from service.config import get_settings
from service.hnsw import _plan_index_names, probe_parameters, probe_sql
from service.hnsw_anchors import require_anchor_set_for_served_catalog
from service.hnsw_corpus import corpus_manifest
from service.hnsw_presets import FILTER_PRESETS, presets_sha256

SETTINGS_TO_RECORD = (
    "shared_buffers",
    "effective_cache_size",
    "work_mem",
    "maintenance_work_mem",
    "max_parallel_workers_per_gather",
    "max_connections",
    "server_version",
)


def connect(dsn: str):
    import psycopg
    from pgvector.psycopg import register_vector
    from psycopg.rows import dict_row

    connection = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
    register_vector(connection)
    connection.execute("SET statement_timeout = '120s'")
    connection.execute("SET application_name = 'mosaic-hardware-benchmark'")
    return connection


def environment(connection: Any) -> dict[str, Any]:
    """Everything about a cluster the comparison has to hold constant or disclose."""
    indexes = catalog_indexes()
    row = dict(
        connection.execute(
            "SELECT aurora_db_instance_identifier() AS database_instance_id, "
            "aurora_version() AS aurora_version, "
            "(SELECT extversion FROM pg_extension WHERE extname = 'vector') AS vector_extension_version, "
            "current_database() AS database_name"
        ).fetchone()
    )
    row["settings"] = {
        r["name"]: r["setting"] + (r["unit"] or "")
        for r in connection.execute(
            "SELECT name, setting, unit FROM pg_settings WHERE name = ANY(%s)",
            (list(SETTINGS_TO_RECORD),),
        ).fetchall()
    }
    sizes = connection.execute(
        "SELECT pg_relation_size(%s::regclass) AS heap_bytes, "
        "pg_total_relation_size(%s::regclass) AS table_total_bytes, "
        "pg_relation_size(%s::regclass) AS hnsw_bytes, "
        "pg_get_indexdef(%s::regclass) AS index_definition",
        (
            indexes.qualified_table,
            indexes.qualified_table,
            indexes.qualified(indexes.fp32),
            indexes.qualified(indexes.fp32),
        ),
    ).fetchone()
    row["sizes"] = dict(sizes)
    row["vector_count"] = connection.execute(
        f"SELECT count(*) AS n FROM {product_document()} WHERE embedding IS NOT NULL"
    ).fetchone()["n"]
    row["optimized_reads_cache"] = optimized_reads_cache(connection)
    return row


def optimized_reads_cache(connection: Any) -> dict[str, Any] | None:
    """`aurora_stat_optimized_reads_cache()` where the engine offers it, else None.

    The function exists only on Optimized Reads instances, and only a non-zero
    total size proves the tiered cache is present. Its absence is recorded as
    the reason a cluster cannot claim NVMe participation.
    """
    try:
        row = connection.execute(
            "SELECT total_size, used_size FROM aurora_stat_optimized_reads_cache()"
        ).fetchone()
    except Exception as error:  # noqa: BLE001 - the function's absence is the answer
        return {"available": False, "reason": type(error).__name__}
    return {
        "available": True,
        "total_size_bytes": int(row["total_size"] or 0),
        "used_size_bytes": int(row["used_size"] or 0),
    }


def buffer_statistics(connection: Any) -> dict[str, Any]:
    """Cumulative buffer and block counters for the connected database."""
    row = connection.execute(
        "SELECT blks_hit, blks_read, tup_returned, tup_fetched, xact_commit, "
        "stats_reset FROM pg_stat_database WHERE datname = current_database()"
    ).fetchone()
    return {
        key: (str(value) if key == "stats_reset" else value)
        for key, value in dict(row).items()
    }


def explain_sample(connection: Any, sql: str, parameters: list[Any]) -> dict[str, Any]:
    """One EXPLAIN in text and JSON, keeping any Aurora cache fields it prints.

    Aurora prints `aurora_orcache_hit` and `aurora_storage_read` in the
    `Buffers:` line of an Optimized Reads instance when they are non-zero. The
    text form is kept verbatim because those fields have no JSON key.
    """
    text_rows = connection.execute(
        f"EXPLAIN (ANALYZE, BUFFERS) {sql}", parameters
    ).fetchall()
    text = "\n".join(row["QUERY PLAN"] for row in text_rows)
    plan = connection.execute(
        f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}", parameters
    ).fetchone()["QUERY PLAN"][0]
    node = plan["Plan"]
    return {
        "text": text,
        "server_ms": round(plan["Execution Time"], 3),
        "shared_hit_blocks": node.get("Shared Hit Blocks"),
        "shared_read_blocks": node.get("Shared Read Blocks"),
        "indexes_used": _plan_index_names(node),
        "aurora_orcache_hit_mentioned": "aurora_orcache_hit" in text,
        "aurora_storage_read_mentioned": "aurora_storage_read" in text,
    }


class Workload:
    """A deterministic sequence of (anchor, preset) pairs shared by every worker."""

    def __init__(self, pool: list[dict[str, Any]]):
        self.pairs = [(anchor, preset) for anchor in pool for preset in FILTER_PRESETS]
        self.position = 0
        self.lock = threading.Lock()

    def next(self):
        with self.lock:
            pair = self.pairs[self.position % len(self.pairs)]
            self.position += 1
            return pair

    @property
    def sha256(self) -> str:
        return _sha256_json(
            [(int(anchor["product_id"]), preset.key) for anchor, preset in self.pairs]
        )


def run_phase(
    dsn: str,
    *,
    workload: Workload,
    truth: dict[tuple[int, str], list[int]],
    request: Any,
    concurrency: int,
    seconds: float,
) -> dict[str, Any]:
    """Drive `concurrency` connections for `seconds`; return per-query records."""
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    lock = threading.Lock()
    stop_at = time.perf_counter() + seconds
    configure = f"SELECT {search_schema()}.configure_hnsw(%s::integer, %s::text, %s::integer, %s::real)"

    def worker(worker_id: int) -> None:
        try:
            connection = connect(dsn)
        except Exception as error:  # noqa: BLE001 - counted, never hidden
            with lock:
                errors.append(
                    {
                        "worker": worker_id,
                        "stage": "connect",
                        "error": type(error).__name__,
                    }
                )
            return
        with connection:
            while time.perf_counter() < stop_at:
                anchor, preset = workload.next()
                sql = probe_sql(preset)
                parameters = probe_parameters(request, anchor["embedding"])
                started = time.perf_counter()
                try:
                    with connection.transaction():
                        connection.execute(
                            configure,
                            (
                                request.ef_search,
                                request.iterative_scan,
                                request.max_scan_tuples,
                                request.scan_mem_multiplier,
                            ),
                        )
                        rows = connection.execute(sql, parameters).fetchall()
                except Exception as error:  # noqa: BLE001 - counted, never hidden
                    with lock:
                        errors.append(
                            {
                                "worker": worker_id,
                                "stage": "query",
                                "error": type(error).__name__,
                                "preset": preset.key,
                            }
                        )
                    continue
                elapsed_ms = (time.perf_counter() - started) * 1000
                ids = [int(row["product_id"]) for row in rows]
                expected = truth.get((int(anchor["product_id"]), preset.key), [])
                with lock:
                    records.append(
                        {
                            "worker": worker_id,
                            "anchor": int(anchor["product_id"]),
                            "preset": preset.key,
                            "client_ms": round(elapsed_ms, 3),
                            "returned": len(ids),
                            "truth_count": len(expected[: request.k]),
                            "recall": recall_against_truth(ids, expected, k=request.k),
                        }
                    )

    threads = [
        threading.Thread(target=worker, args=(i,), daemon=True)
        for i in range(concurrency)
    ]
    started_at = datetime.now(UTC)
    wall_started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    wall = time.perf_counter() - wall_started
    return {
        "started_at": started_at.isoformat(),
        "ended_at": datetime.now(UTC).isoformat(),
        "wall_seconds": round(wall, 3),
        "records": records,
        "errors": errors,
    }


def summarize_phase(phase: dict[str, Any], *, concurrency: int) -> dict[str, Any]:
    latencies = [r["client_ms"] for r in phase["records"]]
    completed = len(latencies)
    return {
        "concurrency": concurrency,
        "queries_completed": completed,
        "errors": len(phase["errors"]),
        "wall_seconds": phase["wall_seconds"],
        "throughput_qps": round(completed / phase["wall_seconds"], 2)
        if phase["wall_seconds"]
        else None,
        "client_p50_ms": round(percentile(latencies, 0.50), 3) if latencies else None,
        "client_p95_ms": round(percentile(latencies, 0.95), 3) if latencies else None,
        "client_p99_ms": round(percentile(latencies, 0.99), 3) if latencies else None,
        "client_mean_ms": round(statistics.mean(latencies), 3) if latencies else None,
        "recall_at_k": round(statistics.mean(r["recall"] for r in phase["records"]), 4)
        if completed
        else None,
        "rows_returned_mean": round(
            statistics.mean(r["returned"] for r in phase["records"]), 2
        )
        if completed
        else None,
        "recall_by_preset": {
            key: round(
                statistics.mean(
                    r["recall"] for r in phase["records"] if r["preset"] == key
                ),
                4,
            )
            for key in sorted({r["preset"] for r in phase["records"]})
        },
        "started_at": phase["started_at"],
        "ended_at": phase["ended_at"],
    }


def cloudwatch_metrics(
    instance_id: str, start: datetime, end: datetime, region: str
) -> dict[str, Any]:
    """Per-instance CloudWatch metrics for a phase window, averaged per minute."""
    try:
        import boto3
    except ImportError:
        return {"available": False, "reason": "boto3 not installed"}
    client = boto3.client("cloudwatch", region_name=region)
    names = [
        "CPUUtilization",
        "BufferCacheHitRatio",
        "AuroraOptimizedReadsCacheHitRatio",
        "ReadIOPS",
        "ReadLatency",
        "ReadThroughput",
        "StorageNetworkReceiveThroughput",
        "DatabaseConnections",
        "FreeableMemory",
    ]
    queries = [
        {
            "Id": f"m{index}",
            "MetricStat": {
                "Metric": {
                    "Namespace": "AWS/RDS",
                    "MetricName": name,
                    "Dimensions": [
                        {"Name": "DBInstanceIdentifier", "Value": instance_id}
                    ],
                },
                "Period": 60,
                "Stat": "Average",
            },
            "ReturnData": True,
        }
        for index, name in enumerate(names)
    ]
    window_start = start - timedelta(minutes=1)
    window_end = end + timedelta(minutes=2)
    response = client.get_metric_data(
        MetricDataQueries=queries,
        StartTime=window_start,
        EndTime=window_end,
        ScanBy="TimestampAscending",
    )
    out: dict[str, Any] = {
        "available": True,
        "window": [window_start.isoformat(), window_end.isoformat()],
    }
    for index, name in enumerate(names):
        series = next(
            (r for r in response["MetricDataResults"] if r["Id"] == f"m{index}"), None
        )
        values = series["Values"] if series else []
        out[name] = {
            "samples": len(values),
            "mean": round(statistics.mean(values), 4) if values else None,
            "max": round(max(values), 4) if values else None,
            "values": [round(v, 4) for v in values],
        }
    return out


def describe_instance(instance_id: str, region: str) -> dict[str, Any]:
    try:
        import boto3

        client = boto3.client("rds", region_name=region)
        instance = client.describe_db_instances(DBInstanceIdentifier=instance_id)[
            "DBInstances"
        ][0]
        cluster = client.describe_db_clusters(
            DBClusterIdentifier=instance["DBClusterIdentifier"]
        )["DBClusters"][0]
        return {
            "instance_id": instance_id,
            "instance_class": instance["DBInstanceClass"],
            "availability_zone": instance.get("AvailabilityZone"),
            "cluster_id": instance["DBClusterIdentifier"],
            "storage_type": cluster.get("StorageType") or "aurora",
            "engine_version": cluster.get("EngineVersion"),
            "cluster_parameter_group": cluster.get("DBClusterParameterGroup"),
            "instance_parameter_groups": [
                p["DBParameterGroupName"] for p in instance.get("DBParameterGroups", [])
            ],
        }
    except Exception as error:  # noqa: BLE001 - disclosed, not fatal
        return {
            "instance_id": instance_id,
            "available": False,
            "reason": type(error).__name__,
        }


def measure_side(
    label: str,
    dsn: str,
    *,
    instance_id: str,
    region: str,
    pool: list[dict[str, Any]],
    anchor_set_sha256: str,
    request: Any,
    concurrency_levels: list[int],
    duration: float,
    warmup: float,
    trials: int,
    build_workers: int | None,
    build_memory: str | None,
    build_repeat: int,
) -> dict[str, Any]:
    """Everything for one instance: environment, warm-up, trials, build, metrics."""
    with connect(dsn) as connection:
        env = environment(connection)
        manifest = corpus_manifest(connection)
        truth = load_ground_truth(
            connection,
            manifest_sha256=manifest,
            k=request.k,
            anchor_set_sha256=anchor_set_sha256,
        )
        if len(truth) != len(pool) * len(FILTER_PRESETS):
            raise SystemExit(
                explain(
                    f"{label}: ground truth covers {len(truth)} of {len(pool) * len(FILTER_PRESETS)} anchor/preset pairs",
                    "seed exact neighbours on this cluster before comparing hardware",
                )
            )
        before_warmup = buffer_statistics(connection)
    workload = Workload(pool)
    print(
        f"[{label}] warm-up {warmup}s at concurrency {concurrency_levels[0]} …",
        flush=True,
    )
    warm = run_phase(
        dsn,
        workload=workload,
        truth=truth,
        request=request,
        concurrency=concurrency_levels[0],
        seconds=warmup,
    )
    with connect(dsn) as connection:
        after_warmup = buffer_statistics(connection)
        sample = pool[0]
        warm_plan = explain_sample(
            connection,
            probe_sql(FILTER_PRESETS[0]),
            probe_parameters(request, sample["embedding"]),
        )
    trials_out = []
    for level in concurrency_levels:
        for trial in range(trials):
            print(
                f"[{label}] concurrency {level}, trial {trial + 1}/{trials} …",
                flush=True,
            )
            with connect(dsn) as connection:
                before = buffer_statistics(connection)
            phase = run_phase(
                dsn,
                workload=workload,
                truth=truth,
                request=request,
                concurrency=level,
                seconds=duration,
            )
            with connect(dsn) as connection:
                after = buffer_statistics(connection)
                plan = explain_sample(
                    connection,
                    probe_sql(FILTER_PRESETS[0]),
                    probe_parameters(request, sample["embedding"]),
                )
                cache = optimized_reads_cache(connection)
            summary = summarize_phase(phase, concurrency=level)
            summary["trial"] = trial + 1
            summary["buffer_delta"] = {
                "blks_hit": int(after["blks_hit"]) - int(before["blks_hit"]),
                "blks_read": int(after["blks_read"]) - int(before["blks_read"]),
            }
            summary["explain_after"] = plan
            summary["optimized_reads_cache_after"] = cache
            summary["cloudwatch"] = cloudwatch_metrics(
                instance_id,
                datetime.fromisoformat(phase["started_at"]),
                datetime.fromisoformat(phase["ended_at"]),
                region,
            )
            summary["records"] = phase["records"]
            summary["error_records"] = phase["errors"]
            trials_out.append(summary)
            print(
                f"[{label}]   {summary['queries_completed']} queries, {summary['throughput_qps']} q/s, "
                f"p50 {summary['client_p50_ms']} ms, p99 {summary['client_p99_ms']} ms, recall {summary['recall_at_k']}",
                flush=True,
            )
    builds = []
    if build_repeat > 0:
        with connect(dsn) as connection:
            connection.execute("SET statement_timeout = 0")
            for attempt in range(build_repeat):
                print(
                    f"[{label}] index build {attempt + 1}/{build_repeat} …", flush=True
                )
                builds.append(
                    build_once(
                        connection,
                        workers=build_workers,
                        maintenance_work_mem=build_memory,
                        keep=False,
                    )
                )
    return {
        "label": label,
        "rds": describe_instance(instance_id, region),
        "environment": env,
        "corpus_manifest": manifest,
        "workload_sha256": workload.sha256,
        "buffers": {"before_warmup": before_warmup, "after_warmup": after_warmup},
        "warmup": {
            **summarize_phase(warm, concurrency=concurrency_levels[0]),
            "explain_after": warm_plan,
            "counted": False,
        },
        "trials": trials_out,
        "index_builds": builds,
    }


def cost_rows(side: dict[str, Any], price_per_hour: float) -> list[dict[str, Any]]:
    rows = []
    for trial in side["trials"]:
        qps = trial["throughput_qps"] or 0
        rows.append(
            {
                "concurrency": trial["concurrency"],
                "trial": trial["trial"],
                "throughput_qps": qps,
                "recall_at_k": trial["recall_at_k"],
                "usd_per_hour": price_per_hour,
                "usd_per_million_queries": round(
                    price_per_hour / (qps * 3600) * 1_000_000, 4
                )
                if qps
                else None,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-label", required=True)
    parser.add_argument("--test-label", required=True)
    parser.add_argument(
        "--control-instance", required=True, help="RDS DB instance identifier"
    )
    parser.add_argument("--test-instance", required=True)
    parser.add_argument("--control-dsn-env", default="CONTROL_DATABASE_URL")
    parser.add_argument("--test-dsn-env", default="TEST_DATABASE_URL")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--concurrency", nargs="+", type=int, default=[1, 4, 8, 16])
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--warmup", type=float, default=45.0)
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument(
        "--price-control", type=float, required=True, help="USD per hour"
    )
    parser.add_argument("--price-test", type=float, required=True, help="USD per hour")
    parser.add_argument(
        "--price-source",
        default="AWS Price List API, AmazonRDS, us-east-1, Aurora PostgreSQL, InstanceUsageIOOptimized on-demand",
    )
    parser.add_argument("--build-workers", type=int)
    parser.add_argument("--build-memory")
    parser.add_argument("--build-repeat", type=int, default=1)
    parser.add_argument("--label", default="")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "data" / "benchmarks" / "hardware_comparison.json",
    )
    args = parser.parse_args()
    if (
        min([*args.concurrency, args.trials, args.k]) < 1
        or args.duration <= 0
        or args.warmup < 0
    ):
        raise SystemExit(
            explain(
                "non-positive size", "pass positive concurrency, trials, k and duration"
            )
        )
    control_dsn = os.environ.get(args.control_dsn_env, "")
    test_dsn = os.environ.get(args.test_dsn_env, "")
    if not control_dsn or not test_dsn:
        raise SystemExit(
            explain(
                f"{args.control_dsn_env} or {args.test_dsn_env} is empty",
                "export both DSNs",
            )
        )
    settings = get_settings()
    if settings.source_worktree_dirty:
        raise SystemExit(
            "Benchmark source rule: checkout has uncommitted work; commit before measuring."
        )
    anchor_set = require_anchor_set_for_served_catalog()
    profile = load_profile()
    request = SimpleNamespace(
        k=args.k,
        ef_search=profile.hnsw_ef_search,
        iterative_scan="relaxed_order",
        max_scan_tuples=profile.hnsw_max_scan_tuples,
        scan_mem_multiplier=profile.hnsw_scan_mem_multiplier,
        representation="fp32",
        overfetch=args.k,
    )
    with connect(control_dsn) as connection:
        pool = connection.execute(
            f"SELECT product_id, category_key, embedding FROM {product_document()} WHERE embedding IS NOT NULL AND product_id = ANY(%s) ORDER BY product_id",
            (list(anchor_set.product_ids),),
        ).fetchall()
        control_manifest = corpus_manifest(connection)
    with connect(test_dsn) as connection:
        test_manifest = corpus_manifest(connection)
    if control_manifest != test_manifest:
        raise SystemExit(
            explain(
                f"catalog hashes differ ({control_manifest[:12]} vs {test_manifest[:12]})",
                "restore both clusters from the same source",
            )
        )
    if len(pool) != len(anchor_set.product_ids):
        raise SystemExit(
            explain(
                "an anchor lacks a vector on the control cluster", "reselect anchors"
            )
        )
    started = datetime.now(UTC).isoformat()
    common = {
        "pool": [dict(row) for row in pool],
        "anchor_set_sha256": anchor_set.sha256,
        "request": request,
        "concurrency_levels": args.concurrency,
        "duration": args.duration,
        "warmup": args.warmup,
        "trials": args.trials,
        "build_workers": args.build_workers,
        "build_memory": args.build_memory,
        "build_repeat": args.build_repeat,
        "region": args.region,
    }
    control = measure_side(
        args.control_label, control_dsn, instance_id=args.control_instance, **common
    )
    test = measure_side(
        args.test_label, test_dsn, instance_id=args.test_instance, **common
    )
    sizes = control["environment"]["sizes"]
    working_set = int(sizes["table_total_bytes"])
    shared_buffers = control["environment"]["settings"].get("shared_buffers", "")
    artifact = {
        "kind": "measured",
        "claim_class": "controlled instance comparison on restored copies of the served catalog, not the workshop cluster",
        "label": args.label,
        "started_at": started,
        "completed_at": datetime.now(UTC).isoformat(),
        "provenance": {
            "source_revision": settings.source_revision,
            "source_worktree_dirty": settings.source_worktree_dirty,
            "dataset_id": active_dataset() or "synthetic-legacy",
            "dataset_manifest_sha256": control_manifest,
            "anchor_set_sha256": anchor_set.sha256,
            "presets_sha256": presets_sha256(),
            "anchors": len(pool),
            "k": args.k,
            "retrieval_settings": {
                "ef_search": request.ef_search,
                "iterative_scan": request.iterative_scan,
                "max_scan_tuples": request.max_scan_tuples,
                "scan_mem_multiplier": request.scan_mem_multiplier,
                "m": profile.hnsw_m,
                "ef_construction": profile.hnsw_ef_construction,
            },
            "client": {
                "placement": "in-VPC EC2 client, same availability zone as both writers",
                "duration_seconds": args.duration,
                "warmup_seconds": args.warmup,
                "trials": args.trials,
                "concurrency_levels": args.concurrency,
                "query_sequence": "anchors x presets, round-robin, shared position across workers",
            },
            "price_source": args.price_source,
            "command": " ".join(sys.argv),
            "method": (
                "same query text, parameters and configure_hnsw settings as the served probe; "
                "client latency is wall clock per query including the in-VPC network; recall is "
                "scored against exact neighbours seeded in each cluster; warm-up is recorded and "
                "not counted; cache state is reported from pg_stat_database deltas, "
                "aurora_stat_optimized_reads_cache() and EXPLAIN (ANALYZE, BUFFERS) text, never assumed"
            ),
        },
        "working_set": {
            "table_total_bytes": working_set,
            "hnsw_bytes": int(sizes["hnsw_bytes"]),
            "shared_buffers": shared_buffers,
            "note": "if the table and index fit in shared_buffers on both instances, the tiered cache has nothing to serve and a null result is expected",
        },
        "control": control,
        "test": test,
        "cost": {
            "control": cost_rows(control, args.price_control),
            "test": cost_rows(test, args.price_test),
        },
    }
    raw: dict[str, Any] = {}
    for side_name in ("control", "test"):
        side = artifact[side_name]
        for trial in side["trials"]:
            raw[f"{side_name}/c{trial['concurrency']}/t{trial['trial']}"] = {
                "records": trial.pop("records"),
                "errors": trial.pop("error_records"),
            }
    samples_path = args.output.with_suffix(".samples.json")
    artifact["provenance"]["samples_file"] = samples_path.name
    artifact["provenance"]["samples_sha256"] = _sha256_json(raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    samples_path.write_text(json.dumps(raw, indent=2, default=str) + "\n")
    args.output.write_text(json.dumps(artifact, indent=2, default=str) + "\n")
    print(f"Wrote {args.output}", flush=True)


if __name__ == "__main__":
    main()
