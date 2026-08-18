"""Small PostgreSQL boundary shared by API services and scripts."""

from __future__ import annotations

import atexit
import threading
from collections.abc import Iterator
from contextlib import contextmanager

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
                            ('product_document_fts_gin_idx'),
                            ('product_document_trigram_gin_idx'),
                            ('product_document_embedding_hnsw_cosine_idx')
                    ) AS required(name)
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM pg_class index_relation
                        JOIN pg_namespace index_schema
                          ON index_schema.oid = index_relation.relnamespace
                        JOIN pg_index index_state
                          ON index_state.indexrelid = index_relation.oid
                        WHERE index_schema.nspname = 'mosaic_search'
                          AND index_relation.relname = required.name
                          AND index_relation.relkind = 'i'
                          AND index_state.indisvalid
                          AND index_state.indisready
                    )
                ) AS missing_retrieval_indexes,
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
        return dict(row)
