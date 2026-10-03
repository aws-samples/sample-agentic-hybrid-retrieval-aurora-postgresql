"""Integration checks against the served and historical catalogs on Aurora.

Retargeted from `catalog.*` in Phase 2 Unit E. **No predecessor comparison
possible — both `catalog.*` databases dropped 2026-08; DDL survives in git, loaded
state does not.** See SUBSTRATE-1 in docs/rewrite-losses.md.

Three things were wrong with the predecessor beyond the schema name, so this is a
rewrite rather than a rename:

- it read `TEST_DATABASE_URL`, a separate database that the Aurora-only policy
  says does not exist (`ARTIFACTS.md`). It now reads `DATABASE_URL` and is
  read-only except for the memory retry test, whose transaction is rolled back;
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
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("pgvector")

from pgvector.psycopg import register_vector

from scripts.checks.retrieval_profile import load_profile
from service.catalog_runtime import active_dataset, search_schema
from service.config import get_settings
from service.models import SearchRequest
from service.retrieval import RetrievalService

DATABASE_URL = get_settings().database_url
pytestmark = [
    pytest.mark.aurora,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="DATABASE_URL is required for Aurora integration tests",
    ),
]


@pytest.fixture
def connection():
    with psycopg.connect(DATABASE_URL, connect_timeout=20) as database:
        database.read_only = True
        register_vector(database)
        yield database


@pytest.fixture
def profile():
    return load_profile()


@pytest.fixture
def served_probe(connection):
    """Vector checks follow the served catalog; historical rows can lack vectors."""
    if active_dataset():
        contract = json.loads(
            (
                Path(__file__).parents[1] / "data/evals/mosaic_labs_missions.json"
            ).read_text()
        )
        mission = next(
            check
            for check in contract["supporting_checks"]
            if check["id"] == "semantic-eligibility"
        )
        product_id = mission["target_product_ids"][0]
        query, filters = mission["query"], mission["filters"]
    else:
        product_id = 2
        query = "wireless noise cancelling headphones"
        filters = {"domain": "consumer_electronics"}
    schema = search_schema()
    embedding = connection.execute(
        f"SELECT embedding FROM {schema}.product_document WHERE product_id = %s",
        (product_id,),
    ).fetchone()[0]
    assert embedding is not None, f"served product {product_id} has no saved vector"
    service = RetrievalService()
    runtime_profile = service._profile(SearchRequest(query=query, filters=filters))
    service._configure_hnsw(connection, runtime_profile)
    return {
        "schema": schema,
        "embedding": embedding,
        "query": query,
        "filters": json.dumps(filters),
    }


def test_the_projection_is_fully_embedded_in_one_model_space(connection):
    row = connection.execute(
        f"""
        SELECT count(*) AS products,
               count(embedding) AS embedded,
               count(*) FILTER (WHERE vector_dims(embedding) = 1024) AS at_1024
        FROM {search_schema()}.product_document
        """
    ).fetchone()
    products, embedded, at_1024 = row
    assert products > 0
    # A partially loaded embedding column is the measured failure behind
    # `semantic_signal_present`; assert coverage rather than presence.
    assert embedded == products
    assert at_1024 == products


def test_batched_counts_match_shop_with_empty_and_combined_filters():
    from fastapi.testclient import TestClient

    from service.main import app

    filters = [
        {"max_price_cents": 20000},
        {"in_stock_only": True},
        {"min_rating": 4},
        {"brand": "no-such-mosaic-brand"},
        {"domain": "home_office", "in_stock_only": True, "max_price_cents": 30000},
        {"include_refurbished": False, "include_sponsored": False},
    ]
    client = TestClient(app)
    response = client.post("/api/catalog/counts", json=filters)
    assert response.status_code == 200
    counts = response.json()
    assert counts == [
        client.get("/api/catalog/products", params={**item, "limit": 1}).json()["total"]
        for item in filters
    ]
    assert counts[2] > 0  # Ratings are available even when current prices are not.
    assert counts[3] == 0


def test_database_level_trigram_gates_match_the_profile(connection, profile):
    """Every new Aurora session must inherit deterministic pg_trgm index gates."""
    connection.execute("SELECT similarity('mosaic', 'mosaic')").fetchone()
    similarity_gate, word_similarity_gate = connection.execute(
        """
        SELECT current_setting('pg_trgm.similarity_threshold')::real,
               current_setting('pg_trgm.word_similarity_threshold')::real
        """
    ).fetchone()
    function_config = connection.execute(
        """
        SELECT p.proconfig
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'mosaic_search'
          AND p.proname = 'search_trigram'
          AND pg_get_function_identity_arguments(p.oid) =
              'q text, f jsonb, candidate_limit integer, minimum_similarity real'
        """
    ).fetchone()[0]

    assert similarity_gate == pytest.approx(profile.trigram_similarity_gate)
    assert word_similarity_gate == pytest.approx(profile.trigram_word_similarity_gate)
    assert function_config is None


def test_hybrid_fusion_preserves_every_arm_signal(connection, profile, served_probe):
    """Fusion must not erase provenance: the three arm ranks stay separable."""
    rows = connection.execute(
        f"""
        SELECT product_id, fts_rank, trigram_rank, semantic_rank, rrf_score,
               provenance
        FROM {served_probe["schema"]}.search_hybrid_rrf(
            %(query)s, %(embedding)s::vector, %(filters)s::jsonb,
            %(rrf_k)s::integer, %(fts_limit)s::integer,
            %(trigram_limit)s::integer, %(semantic_limit)s::integer,
            %(result_limit)s::integer, %(trigram_threshold)s::real
        )
        LIMIT 10
        """,
        {
            "query": served_probe["query"],
            "embedding": served_probe["embedding"],
            "filters": served_probe["filters"],
            "rrf_k": profile.rrf_k,
            "fts_limit": profile.fts_limit,
            "trigram_limit": profile.trigram_limit,
            "semantic_limit": profile.semantic_limit,
            "result_limit": profile.fused_limit,
            "trigram_threshold": profile.trigram_threshold,
        },
    ).fetchall()

    assert rows
    assert any(row[1] is not None for row in rows), "no lexical arm contribution"
    assert any(row[3] is not None for row in rows), "no semantic arm contribution"
    for row in rows:
        assert row[4] > 0
        assert "channels" in row[5]


def test_pre_rerank_order_is_repeatable(connection, profile, served_probe):
    """Stable tie-breaking makes the visible fused order reproducible."""
    params = {
        "query": served_probe["query"],
        "embedding": served_probe["embedding"],
        "filters": served_probe["filters"],
        "rrf_k": profile.rrf_k,
        "fts_limit": profile.fts_limit,
        "trigram_limit": profile.trigram_limit,
        "semantic_limit": profile.semantic_limit,
        "result_limit": profile.fused_limit,
        "trigram_threshold": profile.trigram_threshold,
    }
    sql = f"""
        SELECT product_id, rrf_score
        FROM {served_probe["schema"]}.search_hybrid_rrf(
            %(query)s, %(embedding)s::vector, %(filters)s::jsonb,
            %(rrf_k)s::integer, %(fts_limit)s::integer,
            %(trigram_limit)s::integer, %(semantic_limit)s::integer,
            %(result_limit)s::integer, %(trigram_threshold)s::real
        )
        ORDER BY pre_rerank_score DESC, product_id
    """
    first = connection.execute(sql, params).fetchall()
    second = connection.execute(sql, params).fetchall()
    assert first == second


def test_common_shop_query_stays_inside_the_sql_latency_guard(
    connection, profile, served_probe
):
    """A broad shopper query must not score six figures of lexical candidates.

    The former OR-combined FTS query plus unconditional whole-string trigram
    gate took roughly ten seconds on the 500K workshop corpus. Five seconds is
    deliberately a guardrail rather than a benchmark claim: the query either
    follows the selective GIN/HNSW paths or PostgreSQL cancels it loudly.
    """
    with connection.transaction():
        connection.execute("SET LOCAL statement_timeout = '5s'")
        rows = connection.execute(
            f"""
            SELECT product_id, fts_rank, trigram_rank, semantic_rank
            FROM {served_probe["schema"]}.search_hybrid_rrf(
                %(query)s, %(embedding)s::vector, '{{}}'::jsonb,
                %(rrf_k)s::integer, %(fts_limit)s::integer,
                %(trigram_limit)s::integer, %(semantic_limit)s::integer,
                %(result_limit)s::integer, %(trigram_threshold)s::real
            )
            """,
            {
                "query": "quiet wireless keyboard for a shared office",
                "embedding": served_probe["embedding"],
                "rrf_k": profile.rrf_k,
                "fts_limit": profile.fts_limit,
                "trigram_limit": profile.trigram_limit,
                "semantic_limit": profile.semantic_limit,
                "result_limit": profile.fused_limit,
                "trigram_threshold": profile.trigram_threshold,
            },
        ).fetchall()

    assert rows
    assert any(row[1] is not None for row in rows), "selective FTS path is empty"
    assert any(row[2] is not None for row in rows), "selective trigram path is empty"
    assert any(row[3] is not None for row in rows), "HNSW path is empty"


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


# --- Lab 1 determinism: the same result on every account, every deployment -----
#
# These four checks are pure SQL. No embedding model, no reranker, no HNSW, so
# nothing here can vary between accounts, between Bedrock model versions, or
# between runs: the same seeded corpus produces the same answer or the gate is
# red. That is deliberate. The Lab 1 lesson previously depended on facts nobody
# asserted anywhere, and a release shipped in which the anchor was recoverable
# without pg_trgm on every account, not just some.
#
# They live in this file because `make test-aurora-contracts` runs it in the
# non-billed release job. The served-path equivalents need Bedrock and run from
# `make test-aurora-invariants`.

LAB1_ANCHOR = "noice cancelng hedfones"
LAB1_FILTERS = {
    "domain": "consumer_electronics",
    "max_price_cents": 20000,
    "in_stock_only": True,
}
EXACT_IDENTITY_CONTROL = "Sonora WH-C720"


def test_memory_event_retry_reuses_session_and_provider_payload(monkeypatch):
    """Real Aurora transaction, fake provider: a retry must not create a new session."""
    from contextlib import contextmanager
    from unittest.mock import MagicMock
    from uuid import uuid4

    from fastapi import HTTPException, Request
    from psycopg.rows import dict_row

    from service import session_memory as memory

    provider = MagicMock()
    provider.create_event.return_value = {"event": {"eventId": "test-event"}}
    monkeypatch.setattr(memory, "memory_client", lambda: provider)
    monkeypatch.setattr(memory, "_memory_id", lambda: "test-memory")
    actor = uuid4().hex + uuid4().hex
    monkeypatch.setattr(memory, "_actor", lambda request: actor)
    with (
        psycopg.connect(DATABASE_URL, row_factory=dict_row) as database,
        database.transaction(force_rollback=True),
    ):

        @contextmanager
        def connection():
            yield database

        monkeypatch.setattr(memory, "connect", connection)
        event = memory.ConversationEvent(
            text="Test office preference", request_id=uuid4()
        )
        request = Request({"type": "http", "headers": []})
        first = memory.add_event(event, request)
        first_payload = provider.create_event.call_args.kwargs
        second = memory.add_event(event, request)
        assert first == second
        assert provider.create_event.call_args.kwargs == first_payload
        assert (
            database.execute(
                "SELECT count(*) AS n FROM mosaic.agent_session WHERE user_context->>'shopper_id' = %s",
                (actor,),
            ).fetchone()["n"]
            == 1
        )
        with pytest.raises(HTTPException) as rejected:
            memory.add_event(
                event.model_copy(update={"text": "A different message"}), request
            )
        assert rejected.value.status_code == 409
        assert provider.create_event.call_count == 2
