"""Readiness must show the one thing bootstrap deliberately does not build.

`mosaic_bench.exact_neighbor` is filled by `make db-seed-exact-neighbors`, which
takes roughly 7 minutes and is not a bootstrap phase. Nothing in the three
required labs needs it, so that stays out; what did not exist was any way to see
the gap before the HNSW neighbourhood and probe endpoints answered 503 on a fresh
account. This reports it, and must never gate `database_ready`.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import psycopg

from service import db
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

    The assignment is parsed with `ast` rather than sliced with `str.split`: the
    conjunction spans several lines and its first nested call is `bool(...)`, so a
    split on the first `)` captured only that call's 31 characters and never saw
    the remaining conjuncts at all -- a clause could be added to the real gate and
    this test would keep passing. `ast.get_source_segment` returns the exact text
    of the assigned expression regardless of how it wraps, and a positive witness
    (a conjunct this test does not otherwise mention) proves the capture is not
    accidentally empty or truncated the same way again.
    """
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "service" / "main.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    assignment = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "database_ready"
            for target in node.targets
        )
    )
    block = ast.get_source_segment(source, assignment.value)
    assert block is not None

    assert "missing_retrieval_indexes" in block
    assert "exact_neighbor_ground_truth" not in block


# --- `readiness()` end to end, against a fake connection ---------------------


class _FakeRowsCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _FakeReadinessConnection:
    """Answers every query `service.db.readiness()` issues on one connection.

    Extends `_FakeConnection`'s dispatch-by-SQL-substring shape with the two
    queries `exact_neighbor_ground_truth` does not cover -- the status SELECT and
    the index-state catalog read -- so `readiness()` can be bound to
    `exact_neighbor_ground_truth` end to end without a cluster.
    """

    def __init__(
        self,
        *,
        index_states: dict[str, str],
        ground_truth_rows_for: dict[str, int] | None = None,
        ground_truth_error: Exception | None = None,
    ) -> None:
        self._index_states = index_states
        self._ground_truth_error = ground_truth_error
        self._ground_truth = _FakeConnection(
            table_present=True, rows_for=ground_truth_rows_for or {}
        )

    def execute(self, sql: str, parameters: tuple[Any, ...] | None = None) -> Any:
        if "current_database()" in sql:
            return _FakeCursor(
                {
                    "database_name": "mosaic",
                    "server_version": "16.4",
                    "schema_ready": True,
                    "vector_version": "0.8.0",
                    "product_count": 500000,
                    "embedded_product_count": 500000,
                    "embedding_dimensions": 1024,
                    "embedding_model_ids": ["cohere.embed-v4"],
                    "premium_product_count": 120,
                    "evidence_product_count": 500000,
                    "missing_retrieval_functions": None,
                }
            )
        if "index_state.indexrelid" in sql:
            names = parameters[0]
            return _FakeRowsCursor(
                [{"name": name, "state": self._index_states[name]} for name in names]
            )
        if self._ground_truth_error is not None:
            raise self._ground_truth_error
        # The ground-truth count query, the only remaining caller: assert it
        # targets what it claims to, not the whole table or some other join.
        if parameters is not None:
            assert "mosaic_bench.exact_neighbor" in sql
            assert "dataset_manifest_sha256" in sql
        return self._ground_truth.execute(sql, parameters)


def _stub_connect(monkeypatch, connection: _FakeReadinessConnection) -> None:
    @contextmanager
    def _fake_connect():
        yield connection

    monkeypatch.setattr(db, "connect", _fake_connect)
    monkeypatch.setattr(
        db, "get_settings", lambda: SimpleNamespace(dataset_manifest_sha256=MANIFEST)
    )


def test_readiness_reports_ground_truth_status(monkeypatch) -> None:
    """Nothing else binds `readiness()` to `exact_neighbor_ground_truth`."""
    connection = _FakeReadinessConnection(
        index_states={name: "valid" for name in db.REQUIRED_RETRIEVAL_INDEXES},
        ground_truth_rows_for={MANIFEST: 1680},
    )
    _stub_connect(monkeypatch, connection)

    result = db.readiness()

    assert result["exact_neighbor_ground_truth"] == "seeded"
    assert result["exact_neighbor_ground_truth_detail"] is None
    assert result["missing_retrieval_indexes"] is None


def test_readiness_reports_unknown_ground_truth_when_the_query_errors(
    monkeypatch,
) -> None:
    """A privilege or connectivity error against the optional table must not 503

    the whole endpoint: `database_ready` does not depend on this key, so the rest
    of the readiness payload should still be served.
    """
    connection = _FakeReadinessConnection(
        index_states={name: "valid" for name in db.REQUIRED_RETRIEVAL_INDEXES},
        ground_truth_error=psycopg.OperationalError("permission denied"),
    )
    _stub_connect(monkeypatch, connection)

    result = db.readiness()

    assert result["exact_neighbor_ground_truth"] == "unknown"
    assert result["exact_neighbor_ground_truth_detail"] == "OperationalError"
    assert "permission denied" not in str(result["exact_neighbor_ground_truth_detail"])
    assert result["schema_ready"] is True
