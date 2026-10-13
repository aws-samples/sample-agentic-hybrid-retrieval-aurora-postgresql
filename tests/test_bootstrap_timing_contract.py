"""Cached Aurora bootstrap must leave measured phase timings for rehearsal."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")


def test_base_bootstrap_times_every_existing_phase() -> None:
    expected = [
        ("schema_install", "db-install MOSAIC_CATALOG_DATASET="),
        ("lab_schema_install", "db-install-labs"),
        ("smoke_test", "db-smoke"),
    ]
    for phase, target in expected:
        assert f"$(call bootstrap-phase,{phase},{target})" in MAKEFILE
    assert "bootstrap-phase,embedding_import" not in MAKEFILE


def test_base_bootstrap_persists_a_total_without_masking_phase_failures() -> None:
    assert "BOOTSTRAP_TIMINGS_FILE ?= build/bootstrap-timings.tsv" in MAKEFILE
    assert "set -e;" in MAKEFILE
    assert '"total\\t" total' in MAKEFILE


def test_the_optional_quantized_indexes_have_a_target_and_stay_out_of_bootstrap() -> (
    None
):
    """Minutes of index builds for one optional panel must not be a phase."""
    assert "db-index-quantized-catalog:" in MAKEFILE
    assert "bootstrap-phase,index_quantized" not in MAKEFILE
