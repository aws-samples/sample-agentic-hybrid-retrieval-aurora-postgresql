"""Cached Aurora bootstrap must leave measured phase timings for rehearsal."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")

WORKSHOP_PHASES = [
    ("schema_install", "db-install"),
    ("lab_schema_install", "db-install-labs"),
    ("index_creation", "db-index-recover-and-create"),
    ("smoke_test", "db-smoke"),
    ("bootstrap_acceptance", "db-verify-bootstrap"),
]

HISTORICAL_PHASES = [
    ("catalog_prepare", "db-prepare-mosaic"),
    ("catalog_load", "db-load-mosaic"),
    ("index_creation", "db-index-recover-and-create"),
    ("premium_cohort_load", "db-load-cohort"),
    ("evidence_load", "db-load-evidence"),
    ("corpus_lexeme_seed", "db-seed-corpus-lexeme"),
]


def recipe(target: str) -> str:
    return MAKEFILE.split(f"\n{target}:\n", 1)[1].split("\n\n", 1)[0]


def test_base_bootstrap_times_every_workshop_phase() -> None:
    base = recipe("db-bootstrap-base")
    for phase, target in WORKSHOP_PHASES:
        assert f"$(call bootstrap-phase,{phase},{target})" in base
    assert "bootstrap-phase,embedding_import" not in MAKEFILE


def test_the_historical_catalog_stays_off_the_workshop_bootstrap() -> None:
    """Seven measured minutes per deployment for rows no participant reads.

    The synthetic catalog is still the measurement substrate for the canonical
    scorecard, so it keeps a maintainer target with the same timed phases; it
    must not come back into db-bootstrap-base under any phase name.
    """
    base = recipe("db-bootstrap-base")
    historical = recipe("db-load-historical-catalog")
    for phase, target in HISTORICAL_PHASES:
        assert f"$(call bootstrap-phase,{phase},{target})" in historical
    for target in (
        "db-prepare-mosaic",
        "db-load-mosaic",
        "db-load-cohort",
        "db-load-evidence",
        "db-seed-corpus-lexeme",
    ):
        assert target not in base, f"{target} is back on the workshop path"


def test_base_bootstrap_persists_a_total_without_masking_phase_failures() -> None:
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
    recipe_text = MAKEFILE.split("db-index-recover-and-create:")[1].split("\n\n")[0]
    drop = recipe_text.index("db-drop-invalid-indexes")
    create = recipe_text.index("db-index-concurrent")

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


def test_the_acceptance_asserts_no_catalog_row_count() -> None:
    """The served catalog is counted after its restore, by readiness, not here."""
    acceptance = (ROOT / "db" / "sql" / "98_bootstrap_acceptance.sql").read_text(
        encoding="utf-8"
    )

    assert "500000" not in acceptance.split("DO $$", 1)[1]
    assert "agent_tool_contract" in acceptance


def test_the_optional_quantized_indexes_have_a_target_and_stay_out_of_bootstrap() -> (
    None
):
    """9 minutes of index builds for one optional panel must not be a phase."""
    assert "db-index-quantized:" in MAKEFILE
    assert "19_indexes_quantized.sql" in MAKEFILE
    assert "bootstrap-phase,index_quantized" not in MAKEFILE
