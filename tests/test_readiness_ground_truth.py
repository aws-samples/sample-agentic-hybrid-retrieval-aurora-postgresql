"""Readiness must show the one thing bootstrap deliberately does not build.

`mosaic_bench.exact_neighbor` is filled by `make db-seed-exact-neighbors`, which
takes roughly 7 minutes and is not a bootstrap phase. Nothing in the three
required labs needs it, so that stays out; what did not exist was any way to see
the gap before the HNSW neighbourhood and probe endpoints answered 503 on a fresh
account. This reports it, and must never gate `database_ready`.
"""

from __future__ import annotations

from typing import Any

from service.db import exact_neighbor_ground_truth

MANIFEST = "d5abc2c047f73726926260bb6a5364b50295acc4c6b2a3e9e35d47e93eb5c464"


class _FakeCursor:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    def fetchone(self) -> dict[str, Any]:
        return self.row


class _FakeConnection:
    """Answers the two catalog reads the check makes, and records its parameters."""

    def __init__(self, *, table_present: bool, rows_for: dict[str, int]) -> None:
        self.table_present = table_present
        self.rows_for = rows_for
        self.asked_for: list[Any] = []

    def execute(self, sql: str, parameters: tuple[Any, ...] | None = None) -> Any:
        if "to_regclass" in sql:
            return _FakeCursor({"present": self.table_present})
        assert parameters is not None, sql
        self.asked_for.append(parameters[0])
        return _FakeCursor({"neighbor_rows": self.rows_for.get(parameters[0], 0)})


def test_ground_truth_is_missing_when_the_table_was_never_installed() -> None:
    connection = _FakeConnection(table_present=False, rows_for={})

    assert exact_neighbor_ground_truth(connection, MANIFEST) == "missing"


def test_ground_truth_is_missing_when_the_table_is_empty() -> None:
    """The table ships with `install_labs.sql`; the rows do not ship at all."""
    connection = _FakeConnection(table_present=True, rows_for={})

    assert exact_neighbor_ground_truth(connection, MANIFEST) == "missing"


def test_ground_truth_is_missing_when_it_belongs_to_another_corpus() -> None:
    """Rows seeded against a different manifest are not ground truth for this one.

    This is the falsifier that matters: counting the whole table would report
    `seeded` while every recall figure the instrument computes still refuses,
    because the join is pinned to the connected manifest.
    """
    connection = _FakeConnection(table_present=True, rows_for={"7cd7a5ae": 1680})

    assert exact_neighbor_ground_truth(connection, MANIFEST) == "missing"
    assert connection.asked_for == [MANIFEST]


def test_ground_truth_is_seeded_when_rows_exist_for_the_connected_manifest() -> None:
    connection = _FakeConnection(table_present=True, rows_for={MANIFEST: 1680})

    assert exact_neighbor_ground_truth(connection, MANIFEST) == "seeded"


def test_ground_truth_does_not_gate_database_ready() -> None:
    """An unseeded cluster still runs all three required labs.

    Adding it to the conjunction would block every fresh account on a 7-minute
    optional step, which is the opposite of what reporting it is for.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "service" / "main.py").read_text(
        encoding="utf-8"
    )
    readiness_block = source.split("database_ready = (")[1].split(")")[0]

    assert "exact_neighbor_ground_truth" not in readiness_block
