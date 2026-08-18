"""The projection's baseline must be the measured 500K row, not a guess.

This is the gate that would have caught the shipped state. `scale_projection.json`
claimed p95 38.0 ms, index 14.2 GB, recall 0.952 and ef_search 128 at 500K, where the
cluster measures 2.7 ms, 4.09 GB, 0.992 and serves ef_search 100 — all four wrong,
and the page rendered them as the anchor of a 100M-row extrapolation.

At `scale = 500_000` every growth factor in the model collapses to 1, so the 500K row
*is* the baseline. That is why pinning it to the measurement is sufficient.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEASURED = json.loads(
    (ROOT / "data" / "benchmarks" / "hnsw_measured.json").read_text(encoding="utf-8")
)
PROJECTION = json.loads(
    (ROOT / "data" / "benchmarks" / "scale_projection.json").read_text(encoding="utf-8")
)
SERVED_EF_SEARCH = 100
BASELINE_SCALE = 500_000


def measured_operating_point() -> dict:
    for row in MEASURED["ef_sweep"]:
        if row["ef_search"] == SERVED_EF_SEARCH:
            return row
    raise AssertionError(
        f"the measured sweep has no ef_search {SERVED_EF_SEARCH} row; "
        f"fix: re-run `make benchmark-hnsw` including the served ef_search"
    )


def baseline_row() -> dict:
    return next(row for row in PROJECTION["rows"] if row["scale"] == BASELINE_SCALE)


def test_the_baseline_row_is_the_measured_operating_point():
    baseline = baseline_row()
    point = measured_operating_point()

    assert baseline["p95_latency_ms"] == round(point["server_ms"], 2)
    assert baseline["recall_at_10"] == round(point["recall_at_k"], 4)
    assert baseline["ef_search"] == SERVED_EF_SEARCH


def test_the_baseline_index_size_is_the_measured_index_size():
    expected_gb = round(MEASURED["index"]["size_bytes"] / 1_000_000_000, 2)

    assert baseline_row()["index_size_gb"] == expected_gb


def test_index_size_extrapolates_at_the_measured_bytes_per_vector():
    """Linear in vector count, at the measured 8,189 bytes each. Stated arithmetic."""
    per_vector = MEASURED["index"]["bytes_per_vector"]

    for row in PROJECTION["rows"]:
        expected_gb = round(row["scale"] * per_vector / 1_000_000_000, 2)
        assert row["index_size_gb"] == expected_gb, row["scale"]


def test_latency_and_recall_are_monotonic_across_the_envelope():
    """A projection may be wrong, but it may not be incoherent."""
    rows = sorted(PROJECTION["rows"], key=lambda row: row["scale"])

    latencies = [row["p95_latency_ms"] for row in rows]
    recalls = [row["recall_at_10"] for row in rows]

    assert latencies == sorted(latencies), latencies
    assert recalls == sorted(recalls, reverse=True), recalls


def test_every_row_is_labelled_projected():
    for row in PROJECTION["rows"]:
        assert row["projection_kind"] == "simulated_calibrated", row["scale"]


def test_the_warning_names_where_the_baseline_came_from():
    """The old warning told the reader to replace the baseline. It now has one."""
    warning = PROJECTION["warning"]

    assert "hnsw_measured.json" in warning
    assert "PROJECTED" in warning.upper()


def test_build_time_is_absent_because_it_was_never_measured():
    """`baseline_build_min: 22.0` was unmeasured and cannot be recovered read-only.

    Restoring the column needs a 500,000-row HNSW rebuild, which the spec excludes.
    `build/bootstrap-timings.tsv` is the designated sink for a real `index_creation`
    timing and is absent, so no value exists to use. A projected number derived from
    an invented baseline is the defect this change removes.
    """
    assert "baseline_build_min" not in PROJECTION["assumptions"]
    for row in PROJECTION["rows"]:
        assert "build_time_min" not in row


def test_the_projection_records_the_measurement_it_derives_from():
    """Provenance, so a stale projection is identifiable rather than merely wrong."""
    assumptions = PROJECTION["assumptions"]

    assert assumptions["measured_source"].endswith("hnsw_measured.json")
    assert assumptions["measured_captured_at"] == MEASURED["captured_at"]
    assert assumptions["bytes_per_vector"] == MEASURED["index"]["bytes_per_vector"]
