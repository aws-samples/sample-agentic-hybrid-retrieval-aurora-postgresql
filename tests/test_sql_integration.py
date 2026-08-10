"""Integration checks against the live `mosaic_search` tree on Aurora.

Retargeted from `catalog.*` in Phase 2 Unit E. **No predecessor comparison
possible — both `catalog.*` databases dropped 2026-08; DDL survives in git, loaded
state does not.** See SUBSTRATE-1 in docs/rewrite-losses.md.

Three things were wrong with the predecessor beyond the schema name, so this is a
rewrite rather than a rename:

- it read `TEST_DATABASE_URL`, a separate database that the Aurora-only policy
  says does not exist (`ARTIFACTS.md`). It now reads `DATABASE_URL` and is
  strictly read-only;
- its filters used `subcategory` and `max_price`, which `matches_filters` has
  never accepted — the real keys are `category_key` and `max_price_cents`, so
  those filters were silently ignored;
- it called a twelve-argument `search_hybrid_rrf` with three trailing weights.
  No such function exists here: unweighted fusion takes ten arguments, and the
  weighted comparison function is `search_hybrid_rrf_weighted`.

Skips without a DSN so the suite runs anywhere. `make validate-missions` and
`make validate-functions` are the CI-with-DSN gates that cannot be skipped.
"""

import json
import os

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("pgvector")

from pgvector.psycopg import register_vector  # noqa: E402  (after importorskip)

from scripts.retrieval_profile import load_profile  # noqa: E402  (same)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for Aurora integration tests",
)

CONSUMER_ELECTRONICS = json.dumps({"domain": "consumer_electronics"})


@pytest.fixture
def connection():
    with psycopg.connect(DATABASE_URL, connect_timeout=20) as database:
        database.read_only = True
        register_vector(database)
        yield database


@pytest.fixture
def profile():
    return load_profile()


def test_the_projection_is_fully_embedded_in_one_model_space(connection):
    row = connection.execute(
        """
        SELECT count(*) AS products,
               count(embedding) AS embedded,
               count(*) FILTER (WHERE vector_dims(embedding) = 1024) AS at_1024
        FROM mosaic_search.product_document
        """
    ).fetchone()
    products, embedded, at_1024 = row
    assert products > 0
    # A partially loaded embedding column is the measured failure behind
    # `semantic_signal_present`; assert coverage rather than presence.
    assert embedded == products
    assert at_1024 == products


def test_a_long_natural_language_query_has_lexical_candidates(connection, profile):
    rows = connection.execute(
        """
        SELECT product_id, fts_rank
        FROM mosaic_search.search_fts(%s, %s::jsonb, %s::integer)
        ORDER BY fts_rank
        """,
        (
            "wireless noise cancelling over-ear headphones under $200 with "
            "40 hours of battery life",
            json.dumps({"domain": "consumer_electronics", "max_price_cents": 20000}),
            profile.fts_limit,
        ),
    ).fetchall()

    assert rows, "the OR-combined tsquery must return candidates"
    assert rows[0][1] == 1


def test_a_typo_query_recovers_its_target_through_the_trigram_arm(connection, profile):
    """The Lab 1 lesson, asserted: fuzzy matching recovers what FTS cannot."""
    rows = connection.execute(
        """
        SELECT product_id, trigram_rank
        FROM mosaic_search.search_trigram(%s, %s::jsonb, %s::integer, %s::real)
        ORDER BY trigram_rank
        LIMIT 5
        """,
        (
            "wirless noice canceling hedphones under $200 with long batery life",
            json.dumps(
                {
                    "domain": "consumer_electronics",
                    "max_price_cents": 20000,
                    "in_stock_only": True,
                }
            ),
            profile.trigram_limit,
            profile.trigram_threshold,
        ),
    ).fetchall()

    assert rows
    # Product 2 is `typo-recovery`'s target; the gate's A2 checks validate that it
    # exists and satisfies these filters, which is what makes this assertable.
    assert rows[0] == (2, 1)


def test_hybrid_fusion_preserves_every_arm_signal(connection, profile):
    """Fusion must not erase provenance: the three arm ranks stay separable."""
    embedding = connection.execute(
        "SELECT embedding FROM mosaic_search.product_document WHERE product_id = 2"
    ).fetchone()[0]
    rows = connection.execute(
        """
        SELECT product_id, fts_rank, trigram_rank, semantic_rank, rrf_score,
               provenance
        FROM mosaic_search.search_hybrid_rrf(
            %(query)s, %(embedding)s::vector, %(filters)s::jsonb,
            %(rrf_k)s::integer, %(fts_limit)s::integer,
            %(trigram_limit)s::integer, %(semantic_limit)s::integer,
            %(result_limit)s::integer, %(business_weight)s::real,
            %(trigram_threshold)s::real
        )
        LIMIT 10
        """,
        {
            "query": "wireless noise cancelling headphones",
            "embedding": embedding,
            "filters": CONSUMER_ELECTRONICS,
            "rrf_k": profile.rrf_k,
            "fts_limit": profile.fts_limit,
            "trigram_limit": profile.trigram_limit,
            "semantic_limit": profile.semantic_limit,
            "result_limit": profile.fused_limit,
            "business_weight": profile.business_weight,
            "trigram_threshold": profile.trigram_threshold,
        },
    ).fetchall()

    assert rows
    assert any(row[1] is not None for row in rows), "no lexical arm contribution"
    assert any(row[3] is not None for row in rows), "no semantic arm contribution"
    for row in rows:
        assert row[4] > 0
        assert "channels" in row[5]


def test_the_weighted_function_takes_weights_and_the_unweighted_one_does_not(
    connection, profile
):
    """The two signatures must stay distinct, or a caller cannot choose fusion."""
    signatures = dict(
        connection.execute(
            """
            SELECT p.proname, pg_get_function_identity_arguments(p.oid)
            FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'mosaic_search'
              AND p.proname IN ('search_hybrid_rrf', 'search_hybrid_rrf_weighted')
            """
        ).fetchall()
    )
    assert "weight_lexical" not in signatures["search_hybrid_rrf"]
    assert "weight_lexical" in signatures["search_hybrid_rrf_weighted"]
    assert "trigram_threshold" in signatures["search_hybrid_rrf"]
