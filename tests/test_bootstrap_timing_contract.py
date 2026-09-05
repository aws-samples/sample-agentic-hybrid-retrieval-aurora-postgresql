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
        ("index_creation", "db-index-recover-and-create"),
        ("premium_cohort_load", "db-load-cohort"),
        ("evidence_load", "db-load-evidence"),
        ("corpus_lexeme_seed", "db-seed-corpus-lexeme"),
        ("smoke_test", "db-smoke"),
        ("bootstrap_acceptance", "db-verify-bootstrap"),
    ]
    for phase, target in expected:
        assert f"$(call bootstrap-phase,{phase},{target})" in MAKEFILE


def test_cached_bootstrap_persists_a_total_without_masking_phase_failures() -> None:
    assert "BOOTSTRAP_TIMINGS_FILE ?= build/bootstrap-timings.tsv" in MAKEFILE
    assert "set -e;" in MAKEFILE
    assert '"total\\t" total' in MAKEFILE


def test_index_creation_drops_invalid_indexes_before_it_creates_any() -> None:
    """`IF NOT EXISTS` skips an invalid index, so creation alone cannot recover.

    An interrupted CREATE INDEX CONCURRENTLY leaves the relation with
    indisvalid = false. The planner refuses it and the create statement skips it,
    which is why 98_bootstrap_acceptance.sql's advice to re-run the create target
    was a no-op. The recovery target must run first, in the same phase, in order.
    """
    recipe = MAKEFILE.split("db-index-recover-and-create:")[1].split("\n\n")[0]
    drop = recipe.index("db-drop-invalid-indexes")
    create = recipe.index("db-index-concurrent")

    assert drop < create, "recovery must precede creation"
    assert (
        "$(call bootstrap-phase,index_creation,db-index-recover-and-create)" in MAKEFILE
    )


def test_the_acceptance_failure_names_a_command_that_can_actually_recover() -> None:
    acceptance = (ROOT / "db" / "sql" / "98_bootstrap_acceptance.sql").read_text(
        encoding="utf-8"
    )

    assert (
        "Run make db-drop-invalid-indexes then make db-index-concurrent." in acceptance
    )


def test_the_optional_quantized_indexes_have_a_target_and_stay_out_of_bootstrap() -> (
    None
):
    """9 minutes of index builds for one optional panel must not be a phase."""
    assert "db-index-quantized:" in MAKEFILE
    assert "19_indexes_quantized.sql" in MAKEFILE
    assert "bootstrap-phase,index_quantized" not in MAKEFILE
