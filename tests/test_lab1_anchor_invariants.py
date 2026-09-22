"""The current spelling exercise must need pg_trgm under production filters.

The exact-identity control witnesses a working FTS path. The complete semantic
pool witnesses a working vector path. Neither may recover the misspelled target;
otherwise disconnecting pg_trgm would no longer demonstrate the intended loss.
These read-only checks never install a broken function on the shared cluster.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.retrieval_profile import load_profile
from service.catalog_runtime import active_dataset, search_schema
from service.db import connect
from service.models import SearchFilters, SearchRequest
from service.retrieval import get_retrieval_service

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "data/evals/mosaic_labs_missions.json").read_text())
MISSION = next(m for m in CONTRACT["missions"] if m["id"] == "typo-recovery")
CONTROL = next(m for m in CONTRACT["supporting_checks"] if m["id"] == "exact-identity")
ANCHOR_QUERY = MISSION["query"]
ANCHOR_FILTERS = MISSION["filters"]
TARGET_PRODUCT_ID = MISSION["target_product_ids"][0]


@pytest.fixture(autouse=True)
def served_catalog():
    assert active_dataset() == CONTRACT["corpus"]["dataset_id"], (
        "Lab fixture dataset differs from the served catalog; set MOSAIC_CATALOG_DATASET "
        "to the mission corpus before running the live release lane."
    )


def _configure_hnsw(connection, profile):
    connection.execute(
        f"SELECT {search_schema()}.configure_hnsw(%s::integer, %s::text, %s::integer, %s::real)",
        (
            profile.hnsw_ef_search,
            "relaxed_order",
            profile.hnsw_max_scan_tuples,
            profile.hnsw_scan_mem_multiplier,
        ),
    )


def _fts(connection, query):
    return connection.execute(
        f"SELECT product_id FROM {search_schema()}.search_fts(%s, %s::jsonb, %s::integer)",
        (query, json.dumps(ANCHOR_FILTERS), load_profile().fts_limit),
    ).fetchall()


def _semantic(connection):
    profile = load_profile()
    _configure_hnsw(connection, profile)
    return connection.execute(
        f"SELECT product_id FROM {search_schema()}.search_vector(%s::vector, %s::jsonb, %s::integer)",
        (
            get_retrieval_service().embed_query(ANCHOR_QUERY),
            json.dumps(ANCHOR_FILTERS),
            profile.semantic_limit,
        ),
    ).fetchall()


@pytest.mark.aurora
def test_repaired_target_enters_only_through_trigram():
    response = get_retrieval_service().search(
        SearchRequest(
            query=ANCHOR_QUERY,
            filters=SearchFilters(**ANCHOR_FILTERS),
            limit=MISSION["top_k"],
            rerank=True,
        )
    )
    assert response.results
    target = next(
        (row for row in response.results if row.product_id == TARGET_PRODUCT_ID), None
    )
    assert target is not None, "Spelling repair did not recover the mission target"
    assert target.signals.fts.rank is None
    assert target.signals.semantic.rank is None
    assert target.signals.trigram.rank is not None
    assert target.signals.trigram.rrf_contribution > 0
    for row in response.results:
        assert row.domain == ANCHOR_FILTERS["domain"]
        assert row.category_key == ANCHOR_FILTERS["category_key"]


@pytest.mark.aurora
def test_target_is_not_a_candidate_in_either_remaining_arm():
    with connect() as connection:
        assert not any(
            row["product_id"] == TARGET_PRODUCT_ID
            for row in _fts(connection, ANCHOR_QUERY)
        )
        rows = _semantic(connection)
        assert rows, "The vector control is empty; absence would not prove the lesson"
        assert not any(row["product_id"] == TARGET_PRODUCT_ID for row in rows)


@pytest.mark.aurora
def test_fts_cannot_independently_recover_the_target():
    with connect() as connection:
        control = _fts(connection, CONTROL["query"])
        assert any(row["product_id"] == TARGET_PRODUCT_ID for row in control)
        assert not any(
            row["product_id"] == TARGET_PRODUCT_ID
            for row in _fts(connection, ANCHOR_QUERY)
        )


@pytest.mark.aurora
def test_semantic_arm_does_not_make_the_fixture_trivial():
    with connect() as connection:
        rows = _semantic(connection)
    assert len(rows) == load_profile().semantic_limit, (
        "A starved vector pool cannot prove absence"
    )
    assert not any(row["product_id"] == TARGET_PRODUCT_ID for row in rows)


@pytest.mark.aurora
def test_eligibility_filters_gate_the_trigram_arm_itself():
    profile = load_profile()
    with connect() as connection:

        def search(filters):
            return connection.execute(
                f"SELECT product_id FROM {search_schema()}.search_trigram(%s, %s::jsonb, %s::integer, %s::real)",
                (
                    ANCHOR_QUERY,
                    json.dumps(filters),
                    profile.trigram_limit,
                    profile.trigram_threshold,
                ),
            ).fetchall()

        assert any(
            row["product_id"] == TARGET_PRODUCT_ID for row in search(ANCHOR_FILTERS)
        )
        for wrong in (
            {"domain": "home_office"},
            {"category_key": "monitor"},
            {"brand": "Sony"},
        ):
            assert not any(
                row["product_id"] == TARGET_PRODUCT_ID
                for row in search({**ANCHOR_FILTERS, **wrong})
            )
