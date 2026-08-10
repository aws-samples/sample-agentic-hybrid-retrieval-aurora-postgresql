"""The census must fail when a superseded function signature stays live.

House bar: a green check is not evidence on its own. The overload proven red
against Aurora — a second `search_fts` with an extra parameter — is kept here as a
permanent fixture, driven through a stub connection so it runs without a database.

The live-path proof is the recorded red/green run; this guards the logic against an
edit that would make it unable to fail.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import scripts.function_census as census

REPO = Path(__file__).resolve().parents[1]

SINGLE = [
    ("mosaic_search", "search_fts", 1, ["q text, f jsonb, candidate_limit integer"]),
    ("mosaic_search", "search_hybrid_rrf", 1, ["q text, query_embedding vector"]),
]
DUPLICATE = [
    (
        "mosaic_search",
        "search_hybrid_rrf",
        2,
        [
            "q text, ..., business_weight real",
            "q text, ..., business_weight real, trigram_threshold real",
        ],
    ),
]


class StubConnection:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.read_only = False

    def execute(self, sql: str, params: Any = None) -> StubConnection:
        return self

    def fetchall(self) -> list[tuple]:
        return self.rows

    def __enter__(self) -> StubConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def stub_psycopg(monkeypatch):
    """Return a factory that installs a fake psycopg yielding the given rows."""

    def install(rows: list[tuple]):
        module = type(
            "FakePsycopg",
            (),
            {"connect": staticmethod(lambda *a, **k: StubConnection(rows))},
        )
        monkeypatch.setitem(__import__("sys").modules, "psycopg", module)

    return install


def test_one_signature_per_function_passes(monkeypatch, stub_psycopg, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://stub/db")
    stub_psycopg(SINGLE)
    assert census.main() == 0
    assert "exactly one live signature" in capsys.readouterr().out


def test_a_duplicate_signature_fails(monkeypatch, stub_psycopg, capsys):
    """The exact Unit D hazard: CREATE OR REPLACE left the old body callable."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://stub/db")
    stub_psycopg(DUPLICATE)
    assert census.main() == 1
    error = capsys.readouterr().err
    assert "2 live signatures" in error
    assert "found " in error and "fix: " in error


def test_cannot_verify_is_a_loud_failure_in_ci(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("FUNCTION_CENSUS_REQUIRE_DB", "1")
    assert census.main() == 1
    assert "CANNOT VERIFY" in capsys.readouterr().err


def test_a_missing_dsn_is_a_warning_locally(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("FUNCTION_CENSUS_REQUIRE_DB", raising=False)
    assert census.main() == 0
    assert "CANNOT VERIFY" in capsys.readouterr().err


def test_the_sql_file_drops_the_superseded_signature():
    """The cluster fix is not enough; a re-run of the schema must not recreate it."""
    source = (REPO / "db" / "sql" / "09_search_functions.sql").read_text(
        encoding="utf-8"
    )
    assert "DROP FUNCTION IF EXISTS mosaic_search.search_hybrid_rrf(" in source
    drop_at = source.index("DROP FUNCTION IF EXISTS mosaic_search.search_hybrid_rrf(")
    create_at = source.index(
        "CREATE OR REPLACE FUNCTION mosaic_search.search_hybrid_rrf("
    )
    assert drop_at < create_at, "the DROP must precede the CREATE OR REPLACE"
