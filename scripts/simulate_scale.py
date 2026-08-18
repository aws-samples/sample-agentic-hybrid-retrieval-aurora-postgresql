#!/usr/bin/env python3
"""Extrapolate the HNSW scale envelope from the measured 500K baseline.

This is a capacity model, not a benchmark. What makes it honest is where its baseline
comes from: `data/benchmarks/hnsw_measured.json`, written by `make benchmark-hnsw`
against the live cluster. There is deliberately **no hardcoded fallback** — a default
here is exactly the fabricated baseline this script used to ship, which claimed
p95 38.0 ms, index 14.2 GB and recall 0.952 at 500K where the cluster measures
2.7 ms, 4.09 GB and 0.992.

At `scale = 500_000` every growth factor below collapses to 1, so the 500K row is the
baseline verbatim. That is why fixing the baseline was sufficient and no growth term
needed to change.

Index size is the one extrapolation that is plain arithmetic rather than a model:
linear in vector count at the measured bytes per vector. Latency and recall use stated
growth assumptions and are labelled projected.

`build_time_min` is absent on purpose. Its old baseline (22.0 minutes) was unmeasured,
and unlike the other three it cannot be recovered read-only — it needs a 500,000-row
HNSW rebuild. `build/bootstrap-timings.tsv` is the designated sink for a real
`index_creation` timing; when one exists, the column can return as measured.

Usage
-----
    make simulate
    uv run python scripts/simulate_scale.py --output data/benchmarks/scale_projection.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
MEASURED = REPO / "data" / "benchmarks" / "hnsw_measured.json"
SCALES = [500_000, 1_000_000, 5_000_000, 10_000_000, 100_000_000]

# The operating point the workshop serves. The projection extrapolates from the
# measurement taken here rather than from the cheapest point in the sweep, because a
# capacity plan should price the configuration that actually runs.
SERVED_EF_SEARCH = 100


def measured_baseline(
    path: Path = MEASURED, *, ef_search: int = SERVED_EF_SEARCH
) -> dict[str, Any]:
    """Read the 500K operating point the projection extrapolates from.

    Args:
        path: The measured artifact written by `make benchmark-hnsw`.
        ef_search: The served operating point to extrapolate from.

    Returns:
        The measured latency, recall, bytes per vector, and index build parameters.

    Raises:
        SystemExit: The artifact is missing, is not measured, or has no row at the
            served `ef_search`. Each names the command that produces it.
    """
    if not path.exists():
        raise SystemExit(
            f"found no measured baseline at {path.relative_to(REPO)}; "
            f"fix: run `make benchmark-hnsw` before `make simulate`"
        )
    measured = json.loads(path.read_text(encoding="utf-8"))
    if measured.get("kind") != "measured":
        raise SystemExit(
            f"found artifact kind {measured.get('kind')!r} at "
            f"{path.relative_to(REPO)}; fix: regenerate with `make benchmark-hnsw` — "
            f"a projection cannot be its own baseline"
        )
    row = next((r for r in measured["ef_sweep"] if r["ef_search"] == ef_search), None)
    if row is None:
        available = [r["ef_search"] for r in measured["ef_sweep"]]
        raise SystemExit(
            f"found no measured row at the served ef_search {ef_search} "
            f"(have {available}); fix: re-run `make benchmark-hnsw` including it"
        )
    index = measured["index"]
    return {
        "latency_p95_ms": row["server_ms"],
        "recall": row["recall_at_k"],
        "bytes_per_vector": index["bytes_per_vector"],
        "dimensions": index["dimensions"],
        "m": index["m"],
        "ef_construction": index["ef_construction"],
        "ef_search": ef_search,
        "captured_at": measured["captured_at"],
        "source_revision": measured["provenance"].get("source_revision"),
        "instance_class": measured["provenance"].get("instance_class"),
    }


def project(baseline: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrapolate the envelope. Every row is projected except the 500K baseline."""
    rows = []
    for scale in SCALES:
        ratio = scale / SCALES[0]
        log_penalty = math.log2(scale) / math.log2(SCALES[0])
        latency = (
            baseline["latency_p95_ms"]
            * log_penalty
            * (1 + 0.055 * math.log10(max(1, ratio)))
        )
        recall = max(0.75, baseline["recall"] - 0.008 * math.log10(max(1, ratio)))
        rows.append(
            {
                "scale": scale,
                "projection_kind": "simulated_calibrated",
                "p95_latency_ms": round(latency, 2),
                "recall_at_10": round(recall, 4),
                # Plain arithmetic, not a model: linear in vector count at the
                # measured bytes per vector. 100M x 8,189 B is about 819 GB.
                "index_size_gb": round(
                    scale * baseline["bytes_per_vector"] / 1_000_000_000, 2
                ),
                "dimensions": baseline["dimensions"],
                "m": baseline["m"],
                "ef_search": baseline["ef_search"],
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("data/benchmarks/scale_projection.csv")
    )
    parser.add_argument("--measured", type=Path, default=MEASURED)
    arguments = parser.parse_args()

    baseline = measured_baseline(arguments.measured)
    rows = project(baseline)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)

    with arguments.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    metadata = arguments.output.with_suffix(".json")
    metadata.write_text(
        json.dumps(
            {
                "warning": (
                    "PROJECTED beyond 500K. The 500K row is measured; every larger "
                    "row is extrapolated from it by the stated growth assumptions. "
                    "Baseline read from data/benchmarks/hnsw_measured.json."
                ),
                "assumptions": {
                    "measured_source": str(
                        arguments.measured.relative_to(REPO)
                        if arguments.measured.is_absolute()
                        else arguments.measured
                    ),
                    "measured_captured_at": baseline["captured_at"],
                    "measured_source_revision": baseline["source_revision"],
                    "measured_instance_class": baseline["instance_class"],
                    "baseline_latency_p95_ms": baseline["latency_p95_ms"],
                    "baseline_recall": baseline["recall"],
                    "bytes_per_vector": baseline["bytes_per_vector"],
                    "dimensions": baseline["dimensions"],
                    "m": baseline["m"],
                    "ef_construction": baseline["ef_construction"],
                    "ef_search": baseline["ef_search"],
                    "index_size_growth": "linear in vector count",
                    "latency_growth": "log2(n) with a 5.5% per-decade penalty",
                    "recall_decay": "0.008 per decade, floored at 0.75",
                    "output": str(arguments.output),
                },
                "rows": rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote a projection from the measured {SCALES[0]:,}-row baseline "
        f"({baseline['latency_p95_ms']} ms, {baseline['bytes_per_vector']} B/vector) "
        f"to {arguments.output}"
    )


if __name__ == "__main__":
    main()
