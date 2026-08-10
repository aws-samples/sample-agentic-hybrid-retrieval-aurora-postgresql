#!/usr/bin/env python3
"""Run measured HNSW latency/recall experiments against Aurora PostgreSQL.

The script compares indexed ANN results with an exact baseline, captures p50/p95,
recall@k, and JSON EXPLAIN plans, and records all settings. It never labels
projected 1M-100M values as measured; use simulate_scale.py for projections.

Ported from `catalog.product` to `mosaic_search.product_document` in Phase 2
Unit E. **No predecessor comparison possible — both `catalog.*` databases dropped
2026-08; DDL survives in git, loaded state does not.** See SUBSTRATE-1 in
docs/rewrite-losses.md.

**Status: A-MINIMAL.** What is verified here is connectivity and shape — the
script runs against the live `mosaic_*` tree, reads real embeddings, and produces
its documented JSON. What is **deliberately NOT settled** is the output contract:

- the `mosaic_bench.run` / `mosaic_bench.measurement` shape it should write to
  rather than a loose JSON file (`db/sql/13_benchmark.sql` defines those tables and
  this script does not use them);
- the ground-truth definition for `recall_at_k`. The exact baseline here disables
  index scans per transaction, which is exact for the *filtered* pool it samples;
  whether that is the recall the advanced lane should display is a curriculum
  decision, not a porting one.

Both belong to Phase 3's advanced-lane spec. This is recorded so Phase 3 finds the
script **waiting rather than broken**: it runs today, and what it should emit is an
open question with a named owner.
"""
from __future__ import annotations
import argparse
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    xs = sorted(values)
    idx = min(len(xs)-1, max(0, round((len(xs)-1)*p)))
    return xs[idx]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    ap.add_argument("--queries", type=int, default=100)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--ef-search", type=int, nargs="+", default=[16, 32, 64, 128, 256])
    ap.add_argument("--iterative-scan", choices=["off", "strict_order", "relaxed_order"], default="strict_order")
    ap.add_argument("--filter-domain", choices=["consumer_electronics", "running_fitness", "home_office"])
    ap.add_argument("--output", type=Path, default=Path("benchmarks/results/hnsw.json"))
    args = ap.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL or --database-url is required")
    try:
        import psycopg
        from pgvector.psycopg import register_vector
    except ImportError as exc:
        raise SystemExit("Install config/requirements.txt first") from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(args.database_url) as conn:
        register_vector(conn)
        where = "AND domain = %s" if args.filter_domain else ""
        params = [args.filter_domain] if args.filter_domain else []
        pool = conn.execute(f"SELECT product_id, embedding FROM mosaic_search.product_document WHERE embedding IS NOT NULL {where} ORDER BY random() LIMIT %s", params + [args.queries]).fetchall()
        results = []
        for ef in args.ef_search:
            timings, recalls = [], []
            sample_plan = None
            for n, (_, query_vector) in enumerate(pool):
                # Exact baseline: disable index scans for this transaction.
                with conn.transaction():
                    conn.execute("SET LOCAL enable_indexscan = off")
                    exact = conn.execute(
                        f"SELECT product_id FROM mosaic_search.product_document WHERE embedding IS NOT NULL {where} ORDER BY embedding <=> %s LIMIT %s",
                        params + [query_vector, args.k],
                    ).fetchall()
                exact_ids = {row[0] for row in exact}

                with conn.transaction():
                    conn.execute("SELECT set_config('hnsw.ef_search', %s, true)", [str(ef)])
                    conn.execute(f"SET LOCAL hnsw.iterative_scan = '{args.iterative_scan}'")
                    started = time.perf_counter()
                    ann = conn.execute(
                        f"SELECT product_id FROM mosaic_search.product_document WHERE embedding IS NOT NULL {where} ORDER BY embedding <=> %s LIMIT %s",
                        params + [query_vector, args.k],
                    ).fetchall()
                    timings.append((time.perf_counter() - started) * 1000)
                    ann_ids = {row[0] for row in ann}
                    recalls.append(len(exact_ids & ann_ids) / max(1, len(exact_ids)))
                    if n == 0:
                        sample_plan = conn.execute(
                            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT product_id FROM mosaic_search.product_document WHERE embedding IS NOT NULL {where} ORDER BY embedding <=> %s LIMIT %s",
                            params + [query_vector, args.k],
                        ).fetchone()[0]
            results.append({
                "ef_search": ef, "iterative_scan": args.iterative_scan, "filter_domain": args.filter_domain,
                "queries": len(timings), "k": args.k,
                "latency_ms": {"p50": round(percentile(timings, .50), 3), "p95": round(percentile(timings, .95), 3), "mean": round(statistics.mean(timings), 3)},
                "recall_at_k": round(statistics.mean(recalls), 5), "sample_explain": sample_plan,
            })
    output = {"kind": "measured", "generated_at": datetime.now(timezone.utc).isoformat(), "results": results}
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))

if __name__ == "__main__":
    main()
