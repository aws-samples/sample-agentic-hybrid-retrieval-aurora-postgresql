"""Snapshot upgrades preserve the one function Aurora cannot safely replace."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEARCH_SQL = ROOT / "db" / "sql" / "09_search_functions.sql"
UPGRADE_SQL = ROOT / "db" / "sql" / "upgrade_snapshot.sql"


def test_search_trigram_is_guarded_for_snapshot_upgrades():
    source = SEARCH_SQL.read_text(encoding="utf-8")
    start = source.index(r"\if :{?preserve_search_trigram}")
    end = source.index(r"\endif", start)
    guarded = source[start:end]
    assert "CREATE OR REPLACE FUNCTION mosaic_search.search_trigram" in guarded
    assert "SET pg_trgm.similarity_threshold = 0.18" in guarded
    assert "SET pg_trgm.word_similarity_threshold = 0.5" in guarded


def test_snapshot_upgrade_replays_core_and_validates_the_preserved_function():
    source = UPGRADE_SQL.read_text(encoding="utf-8")
    assert r"\set preserve_search_trigram true" in source
    assert r"\ir install.sql" in source
    assert "to_regprocedure(" in source
    assert "pg_trgm.similarity_threshold=0.18" in source
    assert "pg_trgm.word_similarity_threshold=0.5" in source
