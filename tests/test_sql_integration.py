import json
import os

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("pgvector")

from pgvector.psycopg import register_vector

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL integration tests",
)


@pytest.fixture
def connection():
    with psycopg.connect(DATABASE_URL) as database:
        register_vector(database)
        yield database


def test_schema_uses_the_cohere_embed_v4_model_space(connection):
    row = connection.execute(
        """
        SELECT
            count(*) AS products,
            count(*) FILTER (
                WHERE embedding_model_id = 'us.cohere.embed-v4:0'
                  AND vector_dims(embedding) = 1024
            ) AS cohere_products,
            count(*) FILTER (
                WHERE embedding_content_hash =
                      encode(digest(embedding_text, 'sha256'), 'hex')
            ) AS matching_hashes
        FROM catalog.product
        """
    ).fetchone()

    assert row[0] > 0
    assert row[1] == row[0]
    assert row[2] == row[0]


def test_long_natural_language_query_has_lexical_candidates(connection):
    rows = connection.execute(
        """
        SELECT product_id, lexical_rank
        FROM catalog.search_lexical(%s, %s::jsonb, 20)
        """,
        (
            (
                "Find wireless noise-cancelling over-ear headphones under "
                "$200 with at least 40 hours of battery life"
            ),
            json.dumps(
                {
                    "domain": "consumer_electronics",
                    "subcategory": "Over-Ear Headphones",
                    "max_price": 200,
                }
            ),
        ),
    ).fetchall()

    assert rows
    assert rows[0][1] == 1


def test_typo_query_recovers_curated_alias_at_rank_one(connection):
    row = connection.execute(
        """
        SELECT product_id, trigram_rank
        FROM catalog.search_trigram(%s, %s::jsonb, 20, 0.24)
        ORDER BY trigram_rank
        LIMIT 1
        """,
        (
            "noice canceling hedphones for long fligts under 200",
            json.dumps(
                {
                    "domain": "consumer_electronics",
                    "subcategory": "Over-Ear Headphones",
                    "max_price": 200,
                }
            ),
        ),
    ).fetchone()

    assert row == (2, 1)


def test_weighted_rrf_preserves_arm_signals(connection):
    query_embedding = connection.execute(
        "SELECT embedding FROM catalog.product WHERE product_id = 3"
    ).fetchone()[0]
    row = connection.execute(
        """
        SELECT *
        FROM catalog.search_hybrid_rrf(
            %s,
            %s,
            %s::jsonb,
            60,
            100,
            75,
            100,
            20,
            0.30,
            0.10,
            0.45
        )
        LIMIT 1
        """,
        (
            "Northstar Space Q45",
            query_embedding,
            json.dumps({"domain": "consumer_electronics"}),
        ),
    ).fetchone()

    assert row is not None
    assert row[0] == 3
