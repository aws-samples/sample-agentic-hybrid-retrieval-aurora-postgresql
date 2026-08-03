from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator, Literal

import psycopg
from psycopg import sql as pgsql
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


PERSONAS: tuple[str, ...] = ("app_engineer", "auditor", "dba")
Persona = Literal["app_engineer", "auditor", "dba"]


def validate_persona(persona: str) -> None:
    """Validate receipt metadata without treating it as authentication."""
    if persona not in PERSONAS:
        raise ValueError(
            f"unknown persona {persona!r}; expected one of {', '.join(PERSONAS)}"
        )


def persona_role(persona: str) -> str:
    """Map a persona name to its database role.

    Args:
        persona: One of PERSONAS.

    Returns:
        The NOLOGIN role name to ``SET LOCAL ROLE`` to.

    Raises:
        ValueError: The persona is not one of the three bound values. Raised
            rather than defaulted: guessing an identity is how a fail-open bug
            gets shipped.
    """
    validate_persona(persona)
    return f"persona_{persona}"


def _pool_conninfo() -> str:
    """Return the participant database DSN used by the request pool.

    Core mode uses DATABASE_URL and assumes no persona role. The optional
    security module requires WORKSHOP_APP_DATABASE_URL so that a missing
    ``SET LOCAL ROLE`` fails closed rather than inheriting owner privileges: the
    ``workshop_app`` login holds its persona grants ``WITH INHERIT FALSE`` and so
    can read nothing until a persona is assumed.
    """
    settings = get_settings()
    if settings.workbench_security_enabled:
        if settings.workshop_app_database_url:
            return settings.workshop_app_database_url
        raise RuntimeError(
            "WORKBENCH_SECURITY_ENABLED=1 requires WORKSHOP_APP_DATABASE_URL. "
            "Apply `make security-schema`, provision the workshop_app login, and "
            "set its DSN before enabling persona enforcement."
        )
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. For local "
            "development use postgresql://localhost:55432/retrieval?sslmode=disable"
        )
    return settings.database_url


def _build_pool() -> ConnectionPool:
    settings = get_settings()
    pool = ConnectionPool(
        conninfo=_pool_conninfo(),
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
def get_conn(persona: Persona, *, row_factory=None) -> Iterator[psycopg.Connection]:
    """Check out a request-path connection for the `with` block.

    The persona is positional because receipts retain it either way. In core mode
    it is validated and recorded but does not change database identity: every
    request uses the fixed workshop visibility predicate in the canonical SQL
    functions. With WORKBENCH_SECURITY_ENABLED=1 the checkout assumes the matching
    NOLOGIN role for the transaction, and the same SELECT returns different rows.

    The checkout owns a transaction because SET LOCAL is transaction-scoped: the
    pool is autocommit, so outside an explicit transaction the role would apply to
    the SET statement alone. Callers may still open their own nested
    `conn.transaction()` — psycopg maps that to a SAVEPOINT.

    Args:
        persona: One of PERSONAS. Recorded with retrieval and agent proof, and in
            the optional security module it selects the database role.
        row_factory: Applied per checkout so a dict_row caller does not mutate the
            pooled connection's default for the next borrower.

    Yields:
        A pooled connection inside an open transaction.
    """
    role = persona_role(persona)
    security_enabled = get_settings().workbench_security_enabled
    pool = get_pool()
    with pool.connection() as conn:
        if row_factory is not None:
            conn.row_factory = row_factory
        try:
            with conn.transaction():
                if security_enabled:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            pgsql.SQL("SET LOCAL ROLE {}").format(
                                pgsql.Identifier(role)
                            )
                        )
                yield conn
        finally:
            if row_factory is not None:
                conn.row_factory = tuple_row


def get_dict_conn(persona: Persona):
    return get_conn(persona, row_factory=dict_row)


@contextmanager
def get_owner_conn(*, row_factory=None) -> Iterator[psycopg.Connection]:
    """Check out a connection with NO persona, for owner-privileged work.

    The search index build writes retrieval.* and the bootstrap scripts run DDL;
    neither is a persona operation. Named distinctly so a request-path caller
    cannot reach it by leaving an argument off get_conn().

    Connects with DATABASE_URL (the owner DSN) rather than the pool's app login,
    because the pool identity deliberately holds no write grants on retrieval.*.
    """
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set; owner operations need it")
    with psycopg.connect(
        settings.database_url,
        autocommit=True,
        connect_timeout=settings.database_connect_timeout_seconds,
    ) as conn:
        if row_factory is not None:
            conn.row_factory = row_factory
        yield conn
