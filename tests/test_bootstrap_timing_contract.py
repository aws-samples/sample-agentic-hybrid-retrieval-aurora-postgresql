"""Cached Aurora bootstrap must leave measured phase timings for rehearsal."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")


def test_cached_bootstrap_times_every_existing_phase() -> None:
    expected = [
        ("schema_install", "db-install"),
        ("lab_schema_install", "db-install-labs"),
        ("catalog_prepare", "db-prepare-mosaic"),
        ("catalog_load", "db-load-mosaic"),
        ("embedding_import", "db-import-embeddings"),
        ("index_creation", "db-index-concurrent"),
        ("premium_cohort_load", "db-load-cohort"),
        ("evidence_load", "db-load-evidence"),
        ("smoke_test", "db-smoke"),
        ("bootstrap_acceptance", "db-verify-bootstrap"),
    ]
    for phase, target in expected:
        assert f"$(call bootstrap-phase,{phase},{target})" in MAKEFILE


def test_cached_bootstrap_persists_a_total_without_masking_phase_failures() -> None:
    assert "BOOTSTRAP_TIMINGS_FILE ?= build/bootstrap-timings.tsv" in MAKEFILE
    assert "set -e;" in MAKEFILE
    assert '"total\\t" total' in MAKEFILE
