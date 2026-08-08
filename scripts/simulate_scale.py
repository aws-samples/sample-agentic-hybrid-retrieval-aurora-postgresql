#!/usr/bin/env python3
"""Create explicitly labeled HNSW scale projections from a measured baseline.

This is a teaching/capacity model, not an AWS benchmark. Calibrate it with a
measured 500K result from benchmark_hnsw.py before presenting projections.
"""
from __future__ import annotations
import argparse, csv, json, math
from pathlib import Path

SCALES = [500_000, 1_000_000, 5_000_000, 10_000_000, 100_000_000]

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-latency-p95-ms", type=float, default=38.0)
    ap.add_argument("--baseline-build-min", type=float, default=22.0)
    ap.add_argument("--baseline-index-gb", type=float, default=14.2)
    ap.add_argument("--baseline-recall", type=float, default=0.952)
    ap.add_argument("--dimensions", type=int, default=1024)
    ap.add_argument("--m", type=int, default=16)
    ap.add_argument("--ef-search", type=int, default=128)
    ap.add_argument("--output", type=Path, default=Path("data/benchmarks/scale_projection.csv"))
    args = ap.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for n in SCALES:
        ratio = n / SCALES[0]
        log_penalty = math.log2(n) / math.log2(SCALES[0])
        latency = args.baseline_latency_p95_ms * log_penalty * (1 + 0.055 * math.log10(max(1, ratio)))
        build = args.baseline_build_min * ratio ** 1.08
        index = (
            args.baseline_index_gb
            * ratio
            * (args.dimensions / 1024)
            * (0.72 + 0.28 * args.m / 16)
        )
        recall = max(0.75, args.baseline_recall - 0.008 * math.log10(max(1, ratio)))
        rows.append({
            "scale": n, "projection_kind": "simulated_calibrated", "p95_latency_ms": round(latency, 2),
            "recall_at_10": round(recall, 4), "build_time_min": round(build, 1),
            "index_size_gb": round(index, 2), "dimensions": args.dimensions, "m": args.m,
            "ef_search": args.ef_search,
        })
    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    metadata = args.output.with_suffix(".json")
    metadata.write_text(json.dumps({
        "warning": "SIMULATED PROJECTION. Replace baseline defaults with measured results from your Aurora environment.",
        "assumptions": vars(args) | {"output": str(args.output)}, "rows": rows
    }, indent=2), encoding="utf-8")
    print(f"Wrote explicitly labeled projections to {args.output}")

if __name__ == "__main__":
    main()
