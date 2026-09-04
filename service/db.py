"""Small PostgreSQL boundary shared by API services and scripts."""

from __future__ import annotations

import atexit
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from service.config import get_settings

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _configure(connection: psycopg.Connection) -> None:
    """Per-connection setup, run once on checkout into the pool, not per query."""
    register_vector(connection)


def get_pool() -> ConnectionPool:
    """The process-wide pool, opened on first use.

    Every request used to call `psycopg.connect()` and pay a full TCP, TLS, and
    authentication handshake before doing any work. Measured against the workshop
    cluster that was ~430 ms per connection against a ~40 ms warm round trip, and
    one agent turn checks a connection out eight times, so roughly 3.4 s of a 35 s
    turn was handshakes. Scripts import this module for one-shot work, so the pool
    opens lazily and starts empty instead of connecting at import time.
    """
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            settings = get_settings()
            if not settings.database_url:
                raise RuntimeError("DATABASE_URL is not configured")
            _pool = ConnectionPool(
                settings.database_url,
                min_size=0,
                max_size=settings.db_pool_max_size,
                timeout=settings.db_pool_timeout,
                kwargs={"row_factory": dict_row},
                configure=_configure,
                open=True,
            )
            atexit.register(close_pool)
    return _pool


def close_pool() -> None:
    """Release every pooled connection. Idempotent, so atexit and a FastAPI
    shutdown can both call it."""
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.close()


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    """Check a connection out of the pool for the duration of the block.

    Same contract as before: the block commits on a clean exit and rolls back on
    an exception. No caller nests one of these inside another, which is what makes
    a bounded pool safe here; if that ever changes, exhaustion raises `PoolTimeout`
    after `DB_POOL_TIMEOUT_SECONDS` rather than hanging.
    """
    with get_pool().connection() as connection:
        yield connection


def exact_neighbor_ground_truth(connection: psycopg.Connection, manifest: str) -> str:
    """Whether HNSW ground truth exists for the corpus this service is connected to.

    Seeding is deliberately outside the bootstrap: `make db-seed-exact-neighbors`
    runs 30 anchors across 6 presets as exact sequential scans, roughly 7 minutes,
    for one optional Labs surface. That decision stands, and this reports the
    resulting gap instead of leaving a fresh account to discover it as a 503 from
    the neighbourhood and probe endpoints.

    It never gates `database_ready`, for the same reason: nothing required by the
    three labs depends on it.

    Args:
        connection: An open connection to the workshop cluster.
        manifest: The dataset manifest the running service reports.

    Returns:
        `"seeded"` when at least one neighbour row is stored for `manifest`,
        otherwise `"missing"` -- including when the table itself is absent.
    """
    present = connection.execute(
        "SELECT to_regclass('mosaic_bench.exact_neighbor') IS NOT NULL AS present"
    ).fetchone()["present"]
    if not present:
        return "missing"
    stored = connection.execute(
        """
        SELECT count(*) AS neighbor_rows
        FROM mosaic_bench.exact_neighbor
        WHERE dataset_manifest_sha256 = %s
        """,
        (manifest,),
    ).fetchone()["neighbor_rows"]
    return "seeded" if stored else "missing"


# The one definition of "usable index" in this codebase. `indisvalid` alone is not
# enough: an interrupted CREATE INDEX CONCURRENTLY leaves a relation that exists, is
# skipped by IF NOT EXISTS, and cannot serve a scan; the planner ignores it while
# `to_regclass` still finds it. Both `readiness()` below and the HNSW representation
# gate in `service.hnsw` read their answer from here, so the rule cannot drift between
# the two surfaces that report it.
INDEX_STATE_SQL = """
SELECT required.name AS name,
       CASE
           WHEN index_state.indexrelid IS NULL THEN 'missing'
           WHEN index_state.indisvalid AND index_state.indisready THEN 'valid'
           ELSE 'invalid'
       END AS state
FROM unnest(%s::text[]) AS required(name)
LEFT JOIN pg_index AS index_state
  ON index_state.indexrelid = (
      SELECT index_relation.oid
      FROM pg_class AS index_relation
      JOIN pg_namespace AS index_schema
        ON index_schema.oid = index_relation.relnamespace
      WHERE index_schema.nspname = 'mosaic_search'
        AND index_relation.relname = required.name
        AND index_relation.relkind = 'i'
  )
"""

# Without all three, the three required labs cannot run. Reported by `readiness()` as
# `missing_retrieval_indexes` and gated on by `service.main`.
REQUIRED_RETRIEVAL_INDEXES = (
    "product_document_fts_gin_idx",
    "product_document_trigram_gin_idx",
    "product_document_embedding_hnsw_cosine_idx",
)


def index_states_on(connection: Any, names: Sequence[str]) -> dict[str, str]:
    """Catalog state of each named index on an already-open connection.

    Args:
        connection: An open connection to the workshop cluster.
        names: Bare index relation names in `mosaic_search`, without the schema
            qualifier. A same-named index in another schema is not this index and
            is reported as `missing`.

    Returns:
        One entry per requested name: `valid`, `invalid`, or `missing`.
    """
    rows = connection.execute(INDEX_STATE_SQL, ([str(name) for name in names],))
    return {row["name"]: row["state"] for row in rows.fetchall()}


def index_states(names: Sequence[str]) -> dict[str, str]:
    """`index_states_on` for a caller that has no connection of its own."""
    with connect() as connection:
        return index_states_on(connection, names)


def readiness() -> dict[str, object]:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT
                current_database() AS database_name,
                current_setting('server_version') AS server_version,
                to_regclass('mosaic_search.product_document') IS NOT NULL
                    AS schema_ready,
                (SELECT extversion FROM pg_extension WHERE extname = 'vector')
                    AS vector_version,
                (SELECT count(*) FROM mosaic_search.product_document)
                    AS product_count,
                (
                    SELECT count(*) FROM mosaic_search.product_document
                    WHERE embedding IS NOT NULL
                ) AS embedded_product_count,
                (
                    SELECT vector_dims(embedding)
                    FROM mosaic_search.product_document
                    WHERE embedding IS NOT NULL
                    LIMIT 1
                ) AS embedding_dimensions,
                (
                    SELECT array_agg(DISTINCT embedding_model_key)
                    FILTER (WHERE embedding_model_key IS NOT NULL)
                    FROM mosaic_search.product_document
                ) AS embedding_model_ids,
                (
                    SELECT count(*)
                    FROM mosaic.merchandising_assignment
                    WHERE media_tier IN ('flagship', 'premium')
                ) AS premium_product_count,
                (
                    SELECT count(DISTINCT product_id)
                    FROM mosaic.product_evidence
                    WHERE evidence_type = 'product_spec'
                      AND source_name = 'Mosaic catalog specification'
                ) AS evidence_product_count,
                (
                    SELECT array_agg(required.name ORDER BY required.name)
                    FROM (
                        VALUES
                            ('search_hybrid_rrf'),
                            ('search_product_evidence'),
                            ('matches_filters')
                    ) AS required(name)
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM pg_proc function
                        JOIN pg_namespace namespace
                          ON namespace.oid = function.pronamespace
                        WHERE namespace.nspname = 'mosaic_search'
                          AND function.proname = required.name
                    )
                ) AS missing_retrieval_functions
            """
        ).fetchone()
        # `None` rather than `[]` when nothing is missing, which is what the
        # `array_agg` this replaced returned over zero rows.
        missing_indexes = sorted(
            name
            for name, state in index_states_on(
                connection, REQUIRED_RETRIEVAL_INDEXES
            ).items()
            if state != "valid"
        )
        # `mosaic_bench.exact_neighbor` is optional (see `exact_neighbor_ground_truth`'s
        # docstring) and reached over the same connection as the required checks
        # above, so a privilege or other database error against it must not 503 the
        # whole endpoint. Caught here rather than left to `service.main`'s broader
        # `except Exception`, which would report it indistinguishably from a real
        # readiness failure. No connection detail is carried into the response, only
        # the exception's type name.
        try:
            ground_truth = exact_neighbor_ground_truth(
                connection, get_settings().dataset_manifest_sha256 or ""
            )
            ground_truth_detail = None
        except psycopg.Error as error:
            ground_truth = "unknown"
            ground_truth_detail = type(error).__name__
        return dict(row) | {
            "missing_retrieval_indexes": missing_indexes or None,
            "exact_neighbor_ground_truth": ground_truth,
            "exact_neighbor_ground_truth_detail": ground_truth_detail,
        }
