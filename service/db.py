"""Small PostgreSQL boundary shared by API services and scripts."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from service.config import get_settings


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        register_vector(connection)
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
                    SELECT array_agg(DISTINCT embedding_model_key)
                    FILTER (WHERE embedding_model_key IS NOT NULL)
                    FROM mosaic_search.product_document
                ) AS embedding_model_ids
            """
        ).fetchone()
        return dict(row)
