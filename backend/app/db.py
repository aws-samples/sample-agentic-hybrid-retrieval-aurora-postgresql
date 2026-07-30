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


PERSONAS: tuple[str, ...] = ("analyst", "admin", "auditor")
Persona = Literal["analyst", "admin", "auditor"]


def persona_role(persona: str) -> str:
    """Map a persona name to its database role.

    Args:
        persona: One of PERSONAS.

    Returns:
        The role name to SET LOCAL ROLE to.

    Raises:
        ValueError: The persona is not one of the three bound values. Raised
            rather than defaulted: guessing an identity is how a fail-open bug
            gets shipped.
    """
    if persona not in PERSONAS:
        raise ValueError(
            f"unknown persona {persona!r}; expected one of {', '.join(PERSONAS)}"
        )
    return f"persona_{persona}"


def _pool_conninfo() -> str:
    """The DSN the request pool connects with.

    Prefers WORKSHOP_APP_DATABASE_URL (workshop_app, which holds no clearance) and
    falls back to DATABASE_URL so a local developer with one DSN still runs. The
    fallback is logged at WARNING because under it row filtering does not hold: the
    bootstrap identity is granted can_see_restricted by sql/11 so that the seed and
    the index build can project the whole corpus, and the clearance disjunct in every
    policy is therefore true for it on every row.
    """
    settings = get_settings()
    if settings.workshop_app_database_url:
        return settings.workshop_app_database_url
    if not settings.database_url:
        raise RuntimeError(
            "Neither WORKSHOP_APP_DATABASE_URL nor DATABASE_URL is set. For local "
            "development use postgresql://localhost:55432/retrieval?sslmode=disable"
        )
    logger.warning(
        "WORKSHOP_APP_DATABASE_URL is not set; the request pool is falling back to "
        "DATABASE_URL. That identity holds can_see_restricted, so every RLS policy's "
        "clearance disjunct is true for it and persona row filtering is not enforced."
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
    """Check out a connection running as `persona` for the `with` block.

    The persona is positional and required. A caller that forgets it raises
    TypeError here rather than reaching the database as workshop_app, which holds
    no read-path grants and would raise permission denied at the first SELECT.

    The checkout owns a transaction because SET LOCAL is transaction-scoped: the
    pool is autocommit, so outside an explicit transaction the role would apply to
    the SET statement alone. Callers may still open their own nested
    `conn.transaction()` — psycopg maps that to a SAVEPOINT.

    Args:
        persona: One of PERSONAS. Selects the database role.
        row_factory: Applied per checkout so a dict_row caller does not mutate the
            pooled connection's default for the next borrower.

    Yields:
        A pooled connection inside an open transaction, running as the persona.
    """
    role = persona_role(persona)
    pool = get_pool()
    with pool.connection() as conn:
        if row_factory is not None:
            conn.row_factory = row_factory
        try:
            with conn.transaction():
                with conn.cursor() as cursor:
                    # sql.Identifier, not an f-string: the role name is derived from
                    # a validated persona, but SET ROLE takes no parameter markers
                    # and this is the one place a literal would be interpolated.
                    cursor.execute(
                        pgsql.SQL("SET LOCAL ROLE {}").format(pgsql.Identifier(role))
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
