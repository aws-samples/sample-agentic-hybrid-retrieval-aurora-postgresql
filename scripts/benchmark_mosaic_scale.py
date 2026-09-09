#!/usr/bin/env python3
"""Refresh Mosaic's scale results using all current anchors and production probe SQL.

Existing indexes are measured without rebuilding. Exact fp32 neighbours are
recomputed on Aurora for each filter. Each sample executes once for product IDs
and again under EXPLAIN; server percentiles describe the warmed second execution.
Historical representation, build and hardware comparisons are never merged in.
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

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.benchmark_hnsw import (
    EXACT_BASELINE_SETTINGS,
    INDEX_NAME,
    _exact_truth,
    _sha256_json,
    artifact_from_results,
    percentile,
    recall_against_truth,
)
from scripts.retrieval_profile import load_profile
from service.config import get_settings
from service.hnsw import (
    _explain_probe,
    probe_parameters,
    probe_sql,
    require_representation_index,
)
from service.hnsw_presets import ANCHOR_PREDICATE, FILTER_PRESETS


def summarize(samples: list[dict]) -> dict:
    """Aggregate every sample; refuse missing truth or an empty measurement."""
    if not samples or any(sample["truth_count"] < 1 for sample in samples):
        raise ValueError(
            "Benchmark truth rule: empty samples or exact neighbours; fix the query pool before reporting recall."
        )
    server = [sample["server_ms"] for sample in samples]
    client = [sample["client_ms"] for sample in samples]
    return {
        "server_ms": round(percentile(server, 0.5), 3),
        "server_p95_ms": round(percentile(server, 0.95), 3),
        "client_p50_ms": round(percentile(client, 0.5), 3),
        "client_p95_ms": round(percentile(client, 0.95), 3),
        "recall_at_k": round(
            statistics.mean(sample["recall"] for sample in samples), 4
        ),
        "rows_returned": round(
            statistics.mean(sample["returned"] for sample in samples), 2
        ),
        "min_rows_returned": min(sample["returned"] for sample in samples),
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


def measure(connection, pool, truth, preset, request) -> dict:
    """Use the served probe's query, parameters and HNSW configuration."""
    sql = probe_sql(preset, request.representation)
    samples = []
    for anchor in pool:
        with connection.transaction():
            connection.execute(
                "SELECT mosaic_search.configure_hnsw(%s::integer, %s::text, %s::integer, %s::real)",
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
        ids = [int(row["product_id"]) for row in found]
        exact = truth[int(anchor["product_id"])]
        if preset.key == "none":
            expected = {
                "fp32": "product_document_embedding_hnsw_cosine_idx",
                "halfvec": "product_document_embedding_hnsw_halfvec_idx",
                "binary": "product_document_embedding_hnsw_binary_idx",
            }[request.representation]
            if expected not in plan["indexes_used"]:
                raise ValueError(
                    f"Benchmark index rule: expected {expected}, found {plan['indexes_used']}; fix the expression index or query before publishing."
                )
        samples.append(
            {
                "product_id": int(anchor["product_id"]),
                "domain": str(anchor["domain"]),
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
        **summarize(samples),
    }


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
    import psycopg
    from psycopg.rows import dict_row
    from pgvector.psycopg import register_vector

    profile = load_profile()
    started = datetime.now(UTC).isoformat()
    with psycopg.connect(
        settings.database_url, autocommit=True, row_factory=dict_row
    ) as connection:
        register_vector(connection)
        connection.execute("SET statement_timeout = '120s'")
        connection.execute("SET application_name = 'mosaic-scale-benchmark'")
        environment = dict(
            connection.execute(
                "SELECT aurora_db_instance_identifier() AS database_instance_id, current_setting('server_version') AS database_version, (SELECT extversion FROM pg_extension WHERE extname = 'vector') AS vector_extension_version, current_setting('work_mem') AS work_mem"
            ).fetchone()
        )
        pool = connection.execute(
            f"SELECT product_id, domain, embedding FROM mosaic_search.product_document WHERE embedding IS NOT NULL AND {ANCHOR_PREDICATE} ORDER BY product_id"
        ).fetchall()
        if not pool:
            raise SystemExit(
                "Benchmark anchor rule: found no current anchors; inspect the Aurora catalog before measuring."
            )
        count = connection.execute(
            "SELECT count(*) AS n FROM mosaic_search.product_document WHERE embedding IS NOT NULL"
        ).fetchone()["n"]
        memory = connection.execute(
            "SELECT setting::bigint / 1024 AS mb FROM pg_settings WHERE name = 'work_mem'"
        ).fetchone()["mb"]
        index = connection.execute(
            "SELECT pg_get_indexdef(%s::regclass) AS definition, pg_relation_size(%s::regclass) AS size_bytes",
            (INDEX_NAME, INDEX_NAME),
        ).fetchone()
        for representation in ["fp32", "halfvec", "binary"]:
            require_representation_index(connection, representation)
        request = SimpleNamespace(
            k=args.k,
            ef_search=profile.hnsw_ef_search,
            iterative_scan="relaxed_order",
            max_scan_tuples=profile.hnsw_max_scan_tuples,
            scan_mem_multiplier=profile.hnsw_scan_mem_multiplier,
            representation="fp32",
            overfetch=args.k,
        )
        preset = FILTER_PRESETS[0]
        print(
            f"Measuring {len(pool)} anchors across {len({row['domain'] for row in pool})} domains, {count} vectors",
            flush=True,
        )
        print("Exact fp32 ground truth…", flush=True)
        truth, exact_times = _exact_truth(connection, pool, predicate="", k=args.k)
        baseline_samples = []
        with connection.transaction():
            for setting in EXACT_BASELINE_SETTINGS:
                connection.execute(f"SET LOCAL {setting}")
            for row in pool:
                baseline_samples.append(
                    _explain_probe(
                        connection,
                        probe_sql(preset),
                        probe_parameters(request, row["embedding"]),
                    )
                )
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
        sweep = []
        for ef in args.ef_search:
            request.ef_search = ef
            row = measure(connection, pool, truth, preset, request)
            sweep.append(row)
            print(
                f"ef_search {ef}: {row['recall_at_k']} recall, {row['server_ms']} ms server p50",
                flush=True,
            )
        request.ef_search = profile.hnsw_ef_search
        matrix = []
        for preset in FILTER_PRESETS:
            print(f"Filter {preset.key}…", flush=True)
            filtered_truth = (
                truth
                if preset.key == "none"
                else _exact_truth(
                    connection, pool, predicate=preset.predicate_sql, k=args.k
                )[0]
            )
            where = f" AND {preset.predicate_sql}" if preset.predicate_sql else ""
            matching = connection.execute(
                f"SELECT count(*) AS n FROM mosaic_search.product_document WHERE embedding IS NOT NULL{where}"
            ).fetchone()["n"]
            modes = []
            for mode in ["off", "strict_order", "relaxed_order"]:
                for multiplier in sorted({1, profile.hnsw_scan_mem_multiplier}):
                    request.iterative_scan = mode
                    request.scan_mem_multiplier = multiplier
                    row = measure(connection, pool, filtered_truth, preset, request)
                    modes.append({**row, "scan_mem_mb": memory * multiplier})
            matrix.append(
                {
                    "preset": preset.key,
                    "label": preset.label,
                    "character": preset.character,
                    "predicate_sql": preset.predicate_sql,
                    "matching_rows": matching,
                    "selectivity": matching / count,
                    "exact_rows_found": statistics.mean(
                        len(ids) for ids in filtered_truth.values()
                    ),
                    "modes": modes,
                }
            )
        preset = FILTER_PRESETS[0]
        request.iterative_scan = "relaxed_order"
        request.scan_mem_multiplier = profile.hnsw_scan_mem_multiplier
        rows = []
        payload = dict(
            connection.execute(
                "SELECT pg_column_size(embedding) AS fp32, pg_column_size(embedding::halfvec) AS halfvec, pg_column_size(binary_quantize(embedding)) AS binary FROM mosaic_search.product_document WHERE embedding IS NOT NULL LIMIT 1"
            ).fetchone()
        )
        for representation in ["fp32", "halfvec", "binary"]:
            request.representation = representation
            index_name = {
                "fp32": INDEX_NAME,
                "halfvec": "mosaic_search.product_document_embedding_hnsw_halfvec_idx",
                "binary": "mosaic_search.product_document_embedding_hnsw_binary_idx",
            }[representation]
            size = connection.execute(
                "SELECT pg_relation_size(%s::regclass) AS bytes", (index_name,)
            ).fetchone()["bytes"]
            for depth in args.binary_depth if representation == "binary" else [args.k]:
                request.overfetch = depth
                row = measure(connection, pool, truth, preset, request)
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
                row = measure(connection, pool, truth, preset, request)
                deep.append(
                    {
                        **row,
                        "config": f"{representation}, ef_search {request.ef_search}"
                        + (f", rescore {depth}" if representation == "binary" else ""),
                    }
                )
                print(
                    f"Deep {deep[-1]['config']}: {row['recall_at_k']} recall, {row['server_ms']} ms",
                    flush=True,
                )
        request.representation = "fp32"
        request.ef_search = profile.hnsw_ef_search
        with connection.transaction():
            connection.execute(
                "SELECT mosaic_search.configure_hnsw(%s::integer, %s::text, %s::integer, %s::real)",
                (
                    request.ef_search,
                    request.iterative_scan,
                    request.max_scan_tuples,
                    request.scan_mem_multiplier,
                ),
            )
            missing = _explain_probe(
                connection,
                "SELECT product_id FROM mosaic_search.product_document ORDER BY embedding <=> %s LIMIT %s",
                [pool[0]["embedding"], args.k],
            )
    artifact = artifact_from_results(
        provenance={
            "source_revision": settings.source_revision,
            "source_worktree_dirty": False,
            "dataset_manifest_sha256": settings.dataset_manifest_sha256,
            **environment,
            "instance_class": args.instance_class,
            "started_at": started,
            "queries": len(pool),
            "query_sample_product_ids": [int(row["product_id"]) for row in pool],
            "query_sample_sha256": _sha256_json(
                [int(row["product_id"]) for row in pool]
            ),
            "query_domains": {
                str(domain): sum(row["domain"] == domain for row in pool)
                for domain in {row["domain"] for row in pool}
            },
            "k": args.k,
            "work_mem_mb": memory,
            "max_scan_tuples": profile.hnsw_max_scan_tuples,
            "scan_mem_multiplier": profile.hnsw_scan_mem_multiplier,
            "timing_method": "server_ms is p50 across all anchors, EXPLAIN on a second warmed execution; client times are separate; one sequential connection; no cold-cache or concurrent-load claim",
            "command": " ".join(sys.argv),
        },
        index={
            "name": INDEX_NAME,
            **index,
            "vector_count": count,
            "dimensions": profile.vector_dimension,
            "m": profile.hnsw_m,
            "ef_construction": profile.hnsw_ef_construction,
        },
        exact_baseline=exact_baseline,
        missing_predicate=missing,
        ef_sweep=sweep,
        filter_matrix=matrix,
        captured_at=datetime.now(UTC).isoformat(),
        served_ef_search=profile.hnsw_ef_search,
    )
    artifact["representations"] = {
        "ef_search": profile.hnsw_ef_search,
        "k": args.k,
        "anchors": len(pool),
        "payload_bytes": payload,
        "note": "Same current embeddings and exact fp32 ground truth. Existing indexes; build time not measured.",
        "rows": rows,
        "blog_operating_point": {
            "anchors": len(pool),
            "k": args.k,
            "rows": deep,
            "correction": "Fresh deeper-search comparison on the same anchors.",
            "reference": "pgvector binary quantization",
            "reference_url": "https://github.com/pgvector/pgvector#binary-quantization",
            "tradeoff": "These settings use different search effort. Compare recall with both time and index size.",
        },
    }
    raw_samples = {}

    def separate_samples(value, path=""):
        if isinstance(value, dict):
            if "samples" in value:
                raw_samples[path] = value.pop("samples")
            for key, child in value.items():
                separate_samples(child, f"{path}/{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                separate_samples(child, f"{path}/{index}")

    separate_samples(artifact)
    samples_path = args.output.with_suffix(".samples.json")
    artifact["provenance"]["samples_file"] = samples_path.name
    artifact["provenance"]["samples_sha256"] = _sha256_json(raw_samples)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    samples_path.write_text(json.dumps(raw_samples, indent=2, default=str) + "\n")
    args.output.write_text(json.dumps(artifact, indent=2, default=str) + "\n")
    print(f"Wrote {args.output}", flush=True)


if __name__ == "__main__":
    main()
