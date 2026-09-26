#!/usr/bin/env python3
"""Measure Mosaic's HNSW index on the served catalog with the production probe SQL.

Existing indexes are measured without rebuilding. Exact fp32 neighbours are
recomputed on Aurora for every anchor and filter with the planner's index and
bitmap paths disabled inside SET/RESET pairs, so no exact setting can leak into
an approximate query. Each approximate sample executes once for product ids and
again under EXPLAIN (ANALYZE, BUFFERS); server percentiles describe that warmed
second execution, client times the first, and both are kept apart. Historical
representation, build and hardware comparisons are never merged in.

Anchors come from the committed anchor set; the runner refuses to measure when
that set belongs to another catalog, when the tree is dirty, when a required
index is missing, or when any exact result set is empty where it should not be.

Self-match and ties: every anchor is a catalog product, so its exact top-k
contains itself at rank 1 with distance 0 whenever it passes the filter, and
recall counts it like any other neighbour. Exact ordering breaks equal
distances by `product_id`; approximate scans do not, so a tie at the k
boundary can legitimately cost one recall point and is not corrected for.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.benchmark_hnsw import (
    _sha256_json,
    artifact_from_results,
    percentile,
    recall_against_truth,
)
from scripts.retrieval_profile import explain, load_profile
from scripts.seed_exact_neighbors import exact_neighbors
from service.catalog_runtime import (
    active_dataset,
    catalog_indexes,
    product_document,
    search_schema,
)
from service.config import get_settings
from service.db import index_states_on
from service.hnsw import (
    _explain_probe,
    _plan_index_names,
    probe_parameters,
    probe_sql,
    representation_index,
    require_representation_index,
)
from service.hnsw_anchors import require_anchor_set_for_served_catalog
from service.hnsw_corpus import corpus_manifest
from service.hnsw_presets import (
    EXACT_BASELINE_SETTINGS,
    FILTER_PRESETS,
    FilterPreset,
    presets_sha256,
)

SCAN_MODES = ("off", "strict_order", "relaxed_order")
TRUTH_METHOD = (
    "exact cosine top-k per anchor and filter with enable_indexscan and "
    "enable_bitmapscan set off inside SET/RESET pairs; ordered by distance then "
    "product_id so ties are deterministic; the anchor itself is included when it "
    "passes the filter; recall is id overlap divided by the exact rows that exist, "
    "so a filter matching fewer than k rows is scored against those rows"
)
TIMING_METHOD = (
    "server_ms is the p50 across all anchors of EXPLAIN (ANALYZE, BUFFERS) on a "
    "second warmed execution; client_ms is the wall clock of the first execution "
    "from the benchmark host and includes the network; one sequential "
    "connection; no cold-cache, concurrency or end-to-end application claim"
)


def summarize(samples: list[dict]) -> dict:
    """Aggregate every sample; refuse an empty measurement.

    A sample whose exact neighbourhood is empty is kept and scored zero rather
    than refused: a preset that matches nothing near an anchor is a measured
    fact about that filter. `truth_empty` counts them so a reader can see how
    much of a level's recall figure is made of them.
    """
    if not samples:
        raise ValueError(
            "Benchmark truth rule: no samples; fix the anchor set before reporting recall."
        )
    server = [sample["server_ms"] for sample in samples]
    client = [sample["client_ms"] for sample in samples]
    return {
        "server_ms": round(percentile(server, 0.5), 3),
        "server_p95_ms": round(percentile(server, 0.95), 3),
        "server_p99_ms": round(percentile(server, 0.99), 3),
        "client_p50_ms": round(percentile(client, 0.5), 3),
        "client_p95_ms": round(percentile(client, 0.95), 3),
        "recall_at_k": round(
            statistics.mean(sample["recall"] for sample in samples), 4
        ),
        "rows_returned": round(
            statistics.mean(sample["returned"] for sample in samples), 2
        ),
        "min_rows_returned": min(sample["returned"] for sample in samples),
        "truth_empty": sum(1 for sample in samples if sample["truth_count"] == 0),
        "truth_below_k": sum(
            1
            for sample in samples
            if 0 < sample["truth_count"] < sample.get("k", sample["truth_count"] + 1)
        ),
        "shared_hit_blocks": round(
            statistics.mean(sample["shared_hit_blocks"] for sample in samples)
        ),
        "shared_read_blocks": round(
            statistics.mean(sample["shared_read_blocks"] for sample in samples)
        ),
        "node": ", ".join(sorted({sample["node"] for sample in samples})),
        "indexes_used": sorted(
            {name for sample in samples for name in sample["indexes_used"]}
        ),
        "samples": samples,
    }


def exact_truth(
    connection: Any, pool: list[Any], *, preset: FilterPreset, k: int
) -> tuple[dict[int, list[int]], list[float]]:
    """Exact top-k per anchor for one preset, and the client time of each scan."""
    truth: dict[int, list[int]] = {}
    timings: list[float] = []
    for anchor in pool:
        started = time.perf_counter()
        rows = exact_neighbors(
            connection, embedding=anchor["embedding"], preset=preset, k=k
        )
        timings.append((time.perf_counter() - started) * 1000)
        truth[int(anchor["product_id"])] = [product_id for _, product_id, _ in rows]
    return truth, timings


def explain_json(connection: Any, sql: str, parameters: list[Any]) -> dict[str, Any]:
    """The full EXPLAIN (ANALYZE, BUFFERS, SETTINGS) tree of a warmed execution."""
    return connection.execute(
        f"EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON) {sql}", parameters
    ).fetchone()["QUERY PLAN"][0]


def measure(
    connection, pool, truth, preset, request, *, keep_plan: bool = True
) -> dict:
    """Use the served probe's query, parameters and HNSW configuration."""
    sql = probe_sql(preset, request.representation)
    expected_index = representation_index(request.representation)
    samples = []
    plan_json = None
    for position, anchor in enumerate(pool):
        with connection.transaction():
            connection.execute(
                f"SELECT {search_schema()}.configure_hnsw(%s::integer, %s::text, %s::integer, %s::real)",
                (
                    request.ef_search,
                    request.iterative_scan,
                    request.max_scan_tuples,
                    request.scan_mem_multiplier,
                ),
            )
            parameters = probe_parameters(request, anchor["embedding"])
            start = time.perf_counter()
            found = connection.execute(sql, parameters).fetchall()
            client_ms = (time.perf_counter() - start) * 1000
            plan = _explain_probe(connection, sql, parameters)
            if keep_plan and position == 0:
                plan_json = explain_json(connection, sql, parameters)
        ids = [int(row["product_id"]) for row in found]
        exact = truth[int(anchor["product_id"])]
        if preset.key == "none" and expected_index not in plan["indexes_used"]:
            raise ValueError(
                f"Benchmark index rule: expected {expected_index}, found {plan['indexes_used']}; fix the index or query before publishing."
            )
        samples.append(
            {
                "product_id": int(anchor["product_id"]),
                "category_key": str(anchor["category_key"]),
                "k": request.k,
                "returned": len(ids),
                "returned_ids": ids,
                "exact_ids": exact,
                "truth_count": len(exact),
                "recall": recall_against_truth(ids, exact, k=request.k),
                "client_ms": round(client_ms, 3),
                **plan,
            }
        )
    return {
        "ef_search": request.ef_search,
        "iterative_scan": request.iterative_scan,
        "scan_mem_multiplier": request.scan_mem_multiplier,
        "max_scan_tuples": request.max_scan_tuples,
        "plan_json": plan_json,
        **summarize(samples),
    }


def representation_states(connection) -> dict[str, str]:
    """Catalog state of every representation index on the served catalog."""
    indexes = catalog_indexes()
    return index_states_on(
        connection,
        [indexes.fp32, indexes.halfvec, indexes.binary],
        schema=indexes.schema,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--k", type=int, required=True)
    parser.add_argument("--ef-search", nargs="+", type=int, required=True)
    parser.add_argument("--binary-depth", nargs="+", type=int, required=True)
    parser.add_argument("--deep-ef-search", type=int, required=True)
    parser.add_argument("--deep-binary-depth", nargs="+", type=int, required=True)
    parser.add_argument("--instance-class", required=True)
    args = parser.parse_args()
    if (
        min(
            [
                args.k,
                args.deep_ef_search,
                *args.ef_search,
                *args.binary_depth,
                *args.deep_binary_depth,
            ]
        )
        < 1
    ):
        raise SystemExit(
            "Benchmark size rule: found a non-positive value; pass positive search sizes."
        )
    settings = get_settings()
    if settings.source_worktree_dirty:
        raise SystemExit(
            "Benchmark source rule: checkout has uncommitted work; commit the benchmark code in an isolated branch before measuring."
        )
    anchor_set = require_anchor_set_for_served_catalog()
    import psycopg
    from pgvector.psycopg import register_vector
    from psycopg.rows import dict_row

    profile = load_profile()
    indexes = catalog_indexes()
    started = datetime.now(UTC).isoformat()
    with psycopg.connect(
        settings.database_url, autocommit=True, row_factory=dict_row
    ) as connection:
        register_vector(connection)
        connection.execute("SET statement_timeout = '120s'")
        connection.execute("SET application_name = 'mosaic-scale-benchmark'")
        manifest = corpus_manifest(connection)
        if anchor_set.catalog_sha256 and anchor_set.catalog_sha256 != manifest:
            raise SystemExit(
                explain(
                    f"the anchor set was selected on catalog {anchor_set.catalog_sha256[:12]} "
                    f"but the connected catalog is {manifest[:12]}",
                    "run `make select-hnsw-anchors` against the connected catalog",
                )
            )
        environment = dict(
            connection.execute(
                "SELECT aurora_db_instance_identifier() AS database_instance_id, current_setting('server_version') AS database_version, (SELECT extversion FROM pg_extension WHERE extname = 'vector') AS vector_extension_version, current_setting('work_mem') AS work_mem, current_setting('shared_buffers') AS shared_buffers, current_setting('effective_cache_size') AS effective_cache_size"
            ).fetchone()
        )
        pool = connection.execute(
            f"SELECT product_id, category_key, domain::text AS domain, embedding FROM {product_document()} WHERE embedding IS NOT NULL AND product_id = ANY(%s) ORDER BY product_id",
            (list(anchor_set.product_ids),),
        ).fetchall()
        if len(pool) != len(anchor_set.product_ids):
            raise SystemExit(
                "Benchmark anchor rule: the served catalog lacks a vector for "
                f"{len(anchor_set.product_ids) - len(pool)} anchor(s); reselect anchors before measuring."
            )
        count = connection.execute(
            f"SELECT count(*) AS n FROM {product_document()} WHERE embedding IS NOT NULL"
        ).fetchone()["n"]
        memory = connection.execute(
            "SELECT setting::bigint / 1024 AS mb FROM pg_settings WHERE name = 'work_mem'"
        ).fetchone()["mb"]
        index = connection.execute(
            "SELECT pg_get_indexdef(%s::regclass) AS definition, pg_relation_size(%s::regclass) AS size_bytes",
            (indexes.qualified(indexes.fp32), indexes.qualified(indexes.fp32)),
        ).fetchone()
        require_representation_index(connection, "fp32")
        states = representation_states(connection)
        quantized_available = all(
            states.get(name) == "valid" for name in (indexes.halfvec, indexes.binary)
        )
        request = SimpleNamespace(
            k=args.k,
            ef_search=profile.hnsw_ef_search,
            iterative_scan="relaxed_order",
            max_scan_tuples=profile.hnsw_max_scan_tuples,
            scan_mem_multiplier=profile.hnsw_scan_mem_multiplier,
            representation="fp32",
            overfetch=args.k,
        )
        unfiltered = FILTER_PRESETS[0]
        print(
            f"Measuring {len(pool)} anchors across {len({row['category_key'] for row in pool})} categories, {count} vectors",
            flush=True,
        )
        print("Exact fp32 ground truth (unfiltered)…", flush=True)
        truth, exact_times = exact_truth(connection, pool, preset=unfiltered, k=args.k)
        baseline_samples = []
        try:
            for setting in EXACT_BASELINE_SETTINGS:
                connection.execute(f"SET {setting}")
            for row in pool:
                baseline_samples.append(
                    _explain_probe(
                        connection,
                        probe_sql(unfiltered),
                        probe_parameters(request, row["embedding"]),
                    )
                )
        finally:
            for setting in EXACT_BASELINE_SETTINGS:
                connection.execute(f"RESET {setting.split(' =')[0]}")
        exact_baseline = {
            "p50_ms": round(percentile(exact_times, 0.5), 3),
            "p95_ms": round(percentile(exact_times, 0.95), 3),
            "mean_ms": round(statistics.mean(exact_times), 3),
            "server_ms": round(
                statistics.median(row["server_ms"] for row in baseline_samples), 3
            ),
            "shared_hit_blocks": round(
                statistics.mean(row["shared_hit_blocks"] for row in baseline_samples)
            ),
            "node": baseline_samples[0]["node"],
            "method": ", ".join(EXACT_BASELINE_SETTINGS),
        }
        sweep_by_mode: dict[str, list[dict]] = {}
        for mode in SCAN_MODES:
            request.iterative_scan = mode
            sweep_by_mode[mode] = []
            for ef in args.ef_search:
                request.ef_search = ef
                row = measure(connection, pool, truth, unfiltered, request)
                sweep_by_mode[mode].append(row)
                print(
                    f"{mode} ef_search {ef}: {row['recall_at_k']} recall, {row['server_ms']} ms server p50, {row['rows_returned']} rows",
                    flush=True,
                )
        request.ef_search = profile.hnsw_ef_search
        request.iterative_scan = "relaxed_order"
        matrix = []
        for preset in FILTER_PRESETS:
            print(f"Filter {preset.key}…", flush=True)
            filtered_truth = (
                truth
                if preset.key == "none"
                else exact_truth(connection, pool, preset=preset, k=args.k)[0]
            )
            where = f" AND {preset.predicate_sql}" if preset.predicate_sql else ""
            matching = connection.execute(
                f"SELECT count(*) AS n FROM {product_document()} WHERE embedding IS NOT NULL{where}"
            ).fetchone()["n"]
            modes = []
            for mode in SCAN_MODES:
                for multiplier in sorted({1, profile.hnsw_scan_mem_multiplier}):
                    request.iterative_scan = mode
                    request.scan_mem_multiplier = multiplier
                    row = measure(connection, pool, filtered_truth, preset, request)
                    modes.append({**row, "scan_mem_mb": memory * multiplier})
            truth_sizes = [len(ids) for ids in filtered_truth.values()]
            matrix.append(
                {
                    "preset": preset.key,
                    "label": preset.label,
                    "character": preset.character,
                    "predicate_sql": preset.predicate_sql,
                    "predicate_sha256": preset.predicate_sha256,
                    "matching_rows": matching,
                    "selectivity": matching / count,
                    "exact_rows_found": statistics.mean(truth_sizes),
                    "exact_rows_min": min(truth_sizes),
                    "anchors_with_empty_truth": sum(1 for n in truth_sizes if n == 0),
                    "anchors_below_k": sum(1 for n in truth_sizes if 0 < n < args.k),
                    "modes": modes,
                }
            )
        request.iterative_scan = "relaxed_order"
        request.scan_mem_multiplier = profile.hnsw_scan_mem_multiplier
        representations: dict[str, Any] | None = None
        representations_unavailable_reason: str | None = None
        if quantized_available:
            rows = []
            payload = dict(
                connection.execute(
                    f"SELECT pg_column_size(embedding) AS fp32, pg_column_size(embedding::halfvec) AS halfvec, pg_column_size(binary_quantize(embedding)) AS binary FROM {product_document()} WHERE embedding IS NOT NULL LIMIT 1"
                ).fetchone()
            )
            for representation in ["fp32", "halfvec", "binary"]:
                request.representation = representation
                index_name = indexes.qualified(representation_index(representation))
                size = connection.execute(
                    "SELECT pg_relation_size(%s::regclass) AS bytes", (index_name,)
                ).fetchone()["bytes"]
                for depth in (
                    args.binary_depth if representation == "binary" else [args.k]
                ):
                    request.overfetch = depth
                    row = measure(connection, pool, truth, unfiltered, request)
                    rows.append(
                        {
                            **row,
                            "representation": "binary_two_pass"
                            if representation == "binary"
                            else representation,
                            "overfetch": depth if representation == "binary" else None,
                            "index_size_bytes": size,
                            "bytes_per_vector": round(size / count),
                            "build_seconds": None,
                        }
                    )
                    print(
                        f"{representation} depth {depth}: {row['recall_at_k']} recall, {row['server_ms']} ms",
                        flush=True,
                    )
            deep = []
            request.ef_search = args.deep_ef_search
            for representation in ["fp32", "binary"]:
                request.representation = representation
                for depth in (
                    args.deep_binary_depth if representation == "binary" else [args.k]
                ):
                    request.overfetch = depth
                    row = measure(connection, pool, truth, unfiltered, request)
                    deep.append(
                        {
                            **row,
                            "config": f"{representation}, ef_search {request.ef_search}"
                            + (
                                f", rescore {depth}"
                                if representation == "binary"
                                else ""
                            ),
                        }
                    )
            representations = {
                "ef_search": profile.hnsw_ef_search,
                "k": args.k,
                "anchors": len(pool),
                "payload_bytes": payload,
                "note": "Same current embeddings and exact fp32 ground truth. Existing indexes; build time not measured here.",
                "rows": rows,
                "blog_operating_point": {
                    "anchors": len(pool),
                    "k": args.k,
                    "rows": deep,
                    "correction": "Deeper-search comparison on the same anchors.",
                    "reference": "pgvector binary quantization",
                    "reference_url": "https://github.com/pgvector/pgvector#binary-quantization",
                    "tradeoff": "These settings use different search effort. Compare recall with both time and index size.",
                },
            }
        else:
            missing = {
                name: state for name, state in states.items() if state != "valid"
            }
            representations_unavailable_reason = (
                "No halfvec or binary index exists on the served catalog "
                f"({', '.join(f'{n} is {s}' for n, s in sorted(missing.items()))}), "
                "so the representation comparison was not measured rather than "
                "borrowed from another catalog."
            )
            print(representations_unavailable_reason, flush=True)
        request.representation = "fp32"
        request.ef_search = profile.hnsw_ef_search
        with connection.transaction():
            connection.execute(
                f"SELECT {search_schema()}.configure_hnsw(%s::integer, %s::text, %s::integer, %s::real)",
                (
                    request.ef_search,
                    request.iterative_scan,
                    request.max_scan_tuples,
                    request.scan_mem_multiplier,
                ),
            )
            missing_sql = f"SELECT product_id FROM {product_document()} ORDER BY embedding <=> %s LIMIT %s"
            missing_predicate = _explain_probe(
                connection, missing_sql, [pool[0]["embedding"], args.k]
            )
            missing_predicate["plan_json"] = explain_json(
                connection, missing_sql, [pool[0]["embedding"], args.k]
            )
    partial = " WHERE " in str(index["definition"])
    missing_predicate["applies"] = partial
    missing_predicate["note"] = (
        "the served index is partial on `embedding IS NOT NULL`, so a query without "
        "the predicate cannot use it"
        if partial
        else "the served index is total, so the predicate is not required to reach it; "
        "this row records that the query without it still used the index"
    )
    artifact = artifact_from_results(
        provenance={
            "source_revision": settings.source_revision,
            "source_worktree_dirty": False,
            "dataset_id": active_dataset() or "synthetic-legacy",
            "dataset_manifest_sha256": manifest,
            **environment,
            "instance_class": args.instance_class,
            "started_at": started,
            "queries": len(pool),
            "query_sample_product_ids": [int(row["product_id"]) for row in pool],
            "query_sample_sha256": _sha256_json(
                [int(row["product_id"]) for row in pool]
            ),
            "anchor_set_sha256": anchor_set.sha256,
            "anchor_selection": anchor_set.selection,
            "presets_sha256": presets_sha256(),
            "query_categories": {
                str(category): sum(row["category_key"] == category for row in pool)
                for category in sorted({row["category_key"] for row in pool})
            },
            "k": args.k,
            "work_mem_mb": memory,
            "max_scan_tuples": profile.hnsw_max_scan_tuples,
            "scan_mem_multiplier": profile.hnsw_scan_mem_multiplier,
            "scan_modes": list(SCAN_MODES),
            "ef_search_values": list(args.ef_search),
            "truth_method": TRUTH_METHOD,
            "timing_method": TIMING_METHOD,
            "command": " ".join(sys.argv),
        },
        index={
            "name": indexes.qualified(indexes.fp32),
            **index,
            "partial": partial,
            "vector_count": count,
            "dimensions": profile.vector_dimension,
            "m": profile.hnsw_m,
            "ef_construction": profile.hnsw_ef_construction,
        },
        exact_baseline=exact_baseline,
        missing_predicate=missing_predicate,
        ef_sweep=sweep_by_mode["relaxed_order"],
        filter_matrix=matrix,
        captured_at=datetime.now(UTC).isoformat(),
        served_ef_search=profile.hnsw_ef_search,
    )
    artifact["ef_sweep_by_mode"] = sweep_by_mode
    if representations is not None:
        artifact["representations"] = representations
    else:
        artifact["representations_unavailable_reason"] = (
            representations_unavailable_reason
        )
    raw_samples: dict[str, Any] = {}
    raw_plans: dict[str, Any] = {}

    def separate_samples(value, path=""):
        if isinstance(value, dict):
            if "samples" in value:
                raw_samples[path] = value.pop("samples")
            if "plan_json" in value:
                raw_plans[path] = value.pop("plan_json")
            for key, child in value.items():
                separate_samples(child, f"{path}/{key}")
        elif isinstance(value, list):
            for position, child in enumerate(value):
                separate_samples(child, f"{path}/{position}")

    separate_samples(artifact)
    samples_path = args.output.with_suffix(".samples.json")
    plans_path = args.output.with_suffix(".plans.json")
    artifact["provenance"]["samples_file"] = samples_path.name
    artifact["provenance"]["samples_sha256"] = _sha256_json(raw_samples)
    artifact["provenance"]["plans_file"] = plans_path.name
    artifact["provenance"]["plans_sha256"] = _sha256_json(raw_plans)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    samples_path.write_text(json.dumps(raw_samples, indent=2, default=str) + "\n")
    plans_path.write_text(json.dumps(raw_plans, indent=2, default=str) + "\n")
    args.output.write_text(json.dumps(artifact, indent=2, default=str) + "\n")
    print(f"Wrote {args.output}", flush=True)


__all__ = ["_plan_index_names", "main", "measure", "summarize"]


if __name__ == "__main__":
    main()
