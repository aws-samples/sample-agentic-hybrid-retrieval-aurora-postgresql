"""Snapshot upgrades and lab resets apply one current retrieval implementation."""

from pathlib import Path

from service.search_sql import search_sql

ROOT = Path(__file__).resolve().parents[1]


def test_search_trigram_has_no_function_local_guc_or_preservation_branch():
    source = search_sql(ROOT)
    assert "CREATE OR REPLACE FUNCTION mosaic_search.search_trigram" in source
    assert "preserve_search_trigram" not in source
    assert "SET pg_trgm.similarity_threshold" not in source
    assert "SET pg_trgm.word_similarity_threshold" not in source


def test_make_targets_configure_database_defaults_and_apply_current_functions():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    apply_target = makefile.split("db-apply-search-functions:", 1)[1].split("\n\n", 1)[
        0
    ]
    assert "preserve_search_trigram" not in apply_target
    # The participant's one apply command re-proves the stored pg_trgm gates.
    assert "configure(dsn)" in (ROOT / "scripts/apply_search_functions.py").read_text()
    assert "scripts/apply_search_functions.py" in apply_target
    assert (
        "search_sql(ROOT)" in (ROOT / "scripts/apply_search_functions.py").read_text()
    )
