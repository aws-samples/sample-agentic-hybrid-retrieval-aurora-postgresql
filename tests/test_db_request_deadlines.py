"""`service.db.connect()` must bound one checkout's SQL time, freshly, every time.

No local database exists (Aurora only), so this exercises the boundary with a
fake pool rather than a real connection: the property under test is which SQL
`connect()` issues and in what order, not what Postgres does with it. The
`aurora`-marked tests already prove the production statement/lock timeouts
against a live cluster when one is configured.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from service import db
from service.config import get_settings


class _FakeConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: str, *args, **kwargs) -> None:
        self.statements.append(sql)


class _FakePool:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    @contextmanager
    def connection(self):
        yield self._connection


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def fake_connection(monkeypatch) -> _FakeConnection:
    connection = _FakeConnection()
    monkeypatch.setattr(db, "get_pool", lambda: _FakePool(connection))
    return connection


def test_connect_sets_statement_and_lock_timeouts_from_settings(
    fake_connection, monkeypatch
):
    monkeypatch.setenv("MOSAIC_DB_STATEMENT_TIMEOUT_MS", "12345")
    monkeypatch.setenv("MOSAIC_DB_LOCK_TIMEOUT_MS", "678")

    with db.connect():
        pass

    assert fake_connection.statements == [
        "SET LOCAL statement_timeout = 12345",
        "SET LOCAL lock_timeout = 678",
    ]


def test_connect_default_deadlines_match_the_documented_bounds(fake_connection):
    with db.connect():
        pass

    assert fake_connection.statements == [
        "SET LOCAL statement_timeout = 30000",
        "SET LOCAL lock_timeout = 5000",
    ]


def test_connect_override_replaces_only_the_argument_given(fake_connection):
    with db.connect(statement_timeout_ms=1000):
        pass

    assert fake_connection.statements == [
        "SET LOCAL statement_timeout = 1000",
        "SET LOCAL lock_timeout = 5000",
    ]


def test_connect_zero_disables_a_deadline_for_a_long_running_caller(fake_connection):
    with db.connect(statement_timeout_ms=0, lock_timeout_ms=0):
        pass

    assert fake_connection.statements == []


def test_a_reused_connection_never_inherits_the_previous_checkout_settings(
    fake_connection, monkeypatch
):
    """The exact regression this gate exists for: one physical connection, two
    checkouts, two different configured deadlines -- the second must reflect its
    own request's settings, not whatever the first checkout used.
    """
    monkeypatch.setenv("MOSAIC_DB_STATEMENT_TIMEOUT_MS", "1000")
    with db.connect():
        pass
    assert fake_connection.statements[-1] == "SET LOCAL lock_timeout = 5000"
    assert fake_connection.statements[-2] == "SET LOCAL statement_timeout = 1000"

    get_settings.cache_clear()
    monkeypatch.setenv("MOSAIC_DB_STATEMENT_TIMEOUT_MS", "9999")
    with db.connect():
        pass

    # Same fake connection object both times -- this is one pooled connection
    # handed to two different callers -- yet the second checkout's statement
    # reflects only the second call's own configured deadline.
    assert fake_connection.statements[-2:] == [
        "SET LOCAL statement_timeout = 9999",
        "SET LOCAL lock_timeout = 5000",
    ]
