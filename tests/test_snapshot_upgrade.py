"""Snapshot upgrades and lab resets apply one current retrieval implementation."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEARCH_SQL = ROOT / "db" / "sql" / "09_search_functions.sql"
UPGRADE_SQL = ROOT / "db" / "sql" / "upgrade_snapshot.sql"


def test_search_trigram_has_no_function_local_guc_or_preservation_branch():
    source = SEARCH_SQL.read_text(encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION mosaic_search.search_trigram" in source
    assert "preserve_search_trigram" not in source
    assert "SET pg_trgm.similarity_threshold" not in source
    assert "SET pg_trgm.word_similarity_threshold" not in source


def test_snapshot_upgrade_replays_the_current_core_without_preserving_old_code():
    source = UPGRADE_SQL.read_text(encoding="utf-8")
    assert r"\ir install.sql" in source
    assert "preserve_search_trigram" not in source


def test_make_targets_configure_database_defaults_and_apply_current_functions():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    apply_target = makefile.split("db-apply-search-functions:", 1)[1].split(
        "\n\n", 1
    )[0]
    assert "preserve_search_trigram" not in apply_target
    assert "db-configure-retrieval" in apply_target
    assert "09_search_functions.sql" in apply_target
