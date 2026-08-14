"""Small PostgreSQL boundary shared by API services and scripts."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

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
