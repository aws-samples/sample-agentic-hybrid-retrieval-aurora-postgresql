from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg_pool import ConnectionPool

from .config import get_settings

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None


def _configure_connection(conn: psycopg.Connection) -> None:
    """Match the per-request behavior the app relied on before pooling.

    Every checkout runs autocommit so bare statements commit immediately, exactly
    as the old psycopg.connect(autocommit=True) did. Code that needs a multi-
    statement unit opens `with conn.transaction()`, which psycopg honors under
    autocommit by issuing an explicit BEGIN/COMMIT around the block.
    """
    conn.autocommit = True


def _build_pool() -> ConnectionPool:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. For local development use "
            "postgresql://localhost:55432/retrieval?sslmode=disable"
        )
    pool = ConnectionPool(
        conninfo=settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        max_idle=settings.db_pool_max_idle_seconds,
        kwargs={"connect_timeout": settings.database_connect_timeout_seconds},
        configure=_configure_connection,
        open=False,
        name="workbench-pg",
    )
    return pool


def get_pool() -> ConnectionPool:
    """Return the process-wide connection pool, opening it on first use.

    open_pool() during app startup is the normal path; this lazy fallback keeps
    scripts and tests that touch the DB without a FastAPI lifespan working.
    """
    global _pool
    if _pool is None:
        _pool = _build_pool()
    if _pool.closed:
        _pool.open()
    return _pool


def open_pool() -> None:
    """Open the pool and block until min_size connections are established."""
    pool = get_pool()
    pool.wait(timeout=get_settings().database_connect_timeout_seconds)
    logger.info(
        "Opened Postgres pool (min=%s max=%s)",
        get_settings().db_pool_min_size,
        get_settings().db_pool_max_size,
    )


def close_pool() -> None:
    """Close the pool and drain its connections. Safe to call more than once."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_conn(row_factory=None) -> Iterator[psycopg.Connection]:
    """Check a connection out of the pool for the duration of the `with` block.

    Yields a pooled connection and returns it to the pool on exit. `row_factory`
    is applied per checkout so a dict_row caller does not mutate the pooled
    connection's default for the next borrower.
    """
    pool = get_pool()
    with pool.connection() as conn:
        if row_factory is not None:
            conn.row_factory = row_factory
        try:
            yield conn
        finally:
            if row_factory is not None:
                conn.row_factory = tuple_row


def get_dict_conn():
    return get_conn(row_factory=dict_row)
