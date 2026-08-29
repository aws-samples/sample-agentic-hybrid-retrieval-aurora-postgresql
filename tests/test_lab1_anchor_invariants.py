"""Dataset invariants for the Lab 1 `typo-recovery` anchor.

`data/evals/mosaic_labs_missions.json`'s `typo-recovery` mission pins the query
`noice cancelng hedfones` against product 2 (Sonora WH-C720) under the mission's
own filters. These tests prove the fixture naturally produces the lesson -- that
`pg_trgm` is the target's only path in -- rather than proving that any UI
surface displays it.

Two anchors have been retired here, each red for a different reason, and both
falsifiers still work by editing `ANCHOR_QUERY` alone with no code change:

* `wirless noice canceling hedphones under $200 with long batery life` returned
  product 2 at `fts_rank == 1` because its one correctly-spelled term matched.
* `Sonorra WHC720` named the model number, so the *semantic* arm ranked product 2
  first -- measured exact rank 1 of 119,266 eligible rows, cosine 0.492, with
  HNSW out of the path. It was returned at final rank 1 even with `pg_trgm`
  disconnected, so the broken state lost nothing. `test_semantic_arm_does_not_
  make_the_fixture_trivial` is the test that goes red for it.

Neither retirement was enough on its own. Aliases carry a product's own
misspellings, and `db/sql/06_retrieval_projection.sql` fed them into
`feature_text`, hence into `search_document`. Measured: the lexeme `hedphon`
reached exactly one row's tsvector corpus-wide, making product 2 a unique FTS
beacon for any typo an anchor could use. Removing aliases from `feature_text`
is what makes `test_fts_cannot_independently_recover_the_target` provable at all;
restoring them there turns it red while every other test stays green.

Each test calls the production arm functions directly (`search_fts`,
`search_trigram`, `search_vector`) or the served `RetrievalService`, never a
reimplementation of the fusion arithmetic, per house-standards.md rule 3.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.retrieval_profile import load_profile
from service.db import connect
from service.models import SearchFilters, SearchRequest
from service.retrieval import get_retrieval_service

ROOT = Path(__file__).resolve().parents[1]
_CONTRACT = json.loads(
    (ROOT / "data" / "evals" / "mosaic_labs_missions.json").read_text(encoding="utf-8")
)
_MISSION = next(
    mission for mission in _CONTRACT["missions"] if mission["id"] == "typo-recovery"
)
ANCHOR_QUERY = _MISSION["query"]
ANCHOR_FILTERS = _MISSION["filters"]
TARGET_PRODUCT_ID = _MISSION["target_product_ids"][0]

# `Sonora WH-C720` is G-002's own exact-identity query. It is only used here as
# an independent witness that `search_fts` can find the target when the text
# genuinely matches -- never as the anchor under test.
EXACT_IDENTITY_CONTROL_QUERY = "Sonora WH-C720"


def _configure_hnsw(connection, profile) -> None:
    connection.execute(
        "SELECT mosaic_search.configure_hnsw(%s::integer, %s::text, %s::integer, %s::real)",
        (
            profile.hnsw_ef_search,
            "relaxed_order",
            profile.hnsw_max_scan_tuples,
            profile.hnsw_scan_mem_multiplier,
        ),
    )


@pytest.mark.aurora
def test_repaired_target_enters_only_through_trigram():
    """The lesson's positive case: with the arm connected, trigram is the only path.

    Asserts Recall@10 plus provenance, deliberately not `final_rank == 1`. The
    reranker decides the final order, and its margin here is far narrower than
    under the retired identity anchor, so pinning rank 1 would make this test a
    hostage to the reranker's model version. Measured on Aurora with the arm
    restored: trigram rank 1, `pre_rerank_rank` 1, `final_rank` 1,
    `rerank_score` 0.846 -- comfortably inside the top 10, which is the claim the
    lab actually makes.

    Falsifier: swap `ANCHOR_QUERY` for either retired anchor and the provenance
    assertions break -- `signals.fts.rank` stops being `None` for the descriptive
    anchor, `signals.semantic.rank` stops being `None` for `Sonorra WHC720`.
    """
    response = get_retrieval_service().search(
        SearchRequest(
            query=ANCHOR_QUERY,
            filters=SearchFilters(**ANCHOR_FILTERS),
            limit=10,
            rerank=True,
        )
    )

    assert response.results, "the fused pool returned no candidates at all"
    target = next(
        (row for row in response.results if row.product_id == TARGET_PRODUCT_ID), None
    )
    assert target is not None, (
        f"product {TARGET_PRODUCT_ID} did not reach the top "
        f"{len(response.results)}; Recall@10 fails"
    )

    signals = target.signals
    assert signals.fts.rank is None
    assert signals.semantic.rank is None
    assert signals.trigram.rank == 1
    assert signals.trigram.rrf_contribution is not None

    for row in response.results:
        assert row.price_cents <= ANCHOR_FILTERS["max_price_cents"]
        assert row.domain == ANCHOR_FILTERS["domain"]
        if ANCHOR_FILTERS.get("in_stock_only"):
            assert row.availability in {"in_stock", "low_stock"}


@pytest.mark.aurora
def test_target_is_not_a_candidate_in_either_remaining_arm():
    """With `pg_trgm` disconnected, the union of the other two arms omits it.

    `search_hybrid_rrf` fuses three independently-queryable arm functions.
    This calls the other two directly rather than deploying a broken function
    definition to the shared cluster the owner is using for review, and checks
    both raw candidate pools rather than reimplementing RRF: if the target is
    in neither arm's own candidate set, it cannot appear in any fusion built
    only from their union, which is strictly stronger than "outside the top 10."

    Falsifier: swap `ANCHOR_QUERY` for the retired anchor and the FTS row count
    assertion below fails (measured: 1 row, product 2 at rank 1).
    """
    profile = load_profile()
    with connect() as connection:
        fts_rows = connection.execute(
            "SELECT product_id FROM mosaic_search.search_fts(%s, %s::jsonb, %s::integer)",
            (ANCHOR_QUERY, json.dumps(ANCHOR_FILTERS), profile.fts_limit),
        ).fetchall()
        assert fts_rows == [], "FTS recovered the target on its own"

        embedding = get_retrieval_service().embed_query(ANCHOR_QUERY)
        _configure_hnsw(connection, profile)
        semantic_rows = connection.execute(
            "SELECT product_id FROM mosaic_search.search_vector"
            "(%s::vector, %s::jsonb, %s::integer)",
            (embedding, json.dumps(ANCHOR_FILTERS), profile.semantic_limit),
        ).fetchall()
        assert semantic_rows, "the semantic arm returned no candidates to check"
        assert not any(row["product_id"] == TARGET_PRODUCT_ID for row in semantic_rows)


@pytest.mark.aurora
def test_fts_cannot_independently_recover_the_target():
    """FTS finds nothing for this query, under the mission's filters, at all.

    Witness, independent of the absence under test: the same `search_fts`
    call recovers the target at rank 1 for `EXACT_IDENTITY_CONTROL_QUERY`
    under the identical filters, proving the function and connection are not
    simply returning nothing for every input.

    Falsifier: swap `ANCHOR_QUERY` for the retired anchor and the empty-result
    assertion fails (measured: 1 row, product 2 at rank 1).
    """
    profile = load_profile()
    with connect() as connection:
        control_rows = connection.execute(
            "SELECT product_id, fts_rank FROM mosaic_search.search_fts"
            "(%s, %s::jsonb, %s::integer)",
            (
                EXACT_IDENTITY_CONTROL_QUERY,
                json.dumps(ANCHOR_FILTERS),
                profile.fts_limit,
            ),
        ).fetchall()
        assert control_rows == [{"product_id": TARGET_PRODUCT_ID, "fts_rank": 1}], (
            "the control query no longer proves search_fts can find the target"
        )

        anchor_rows = connection.execute(
            "SELECT product_id FROM mosaic_search.search_fts(%s, %s::jsonb, %s::integer)",
            (ANCHOR_QUERY, json.dumps(ANCHOR_FILTERS), profile.fts_limit),
        ).fetchall()
        assert anchor_rows == []


@pytest.mark.aurora
def test_semantic_arm_does_not_make_the_fixture_trivial():
    """The vector arm's own candidate pool is full, real, and still misses it.

    Witness, independent of the absence under test: the ANN search fills its
    entire production `candidate_limit` under the mission's filters, so the
    absence below is not an artifact of a starved or misconfigured filter.

    This is the test that the `Sonorra WHC720` anchor broke, and the reason it
    shipped broken is that this file has never run in a gate. Naming the model
    number put the target at semantic rank 1 -- exact rank 1 of 119,266 eligible
    rows, cosine 0.492, verified with index scans disabled so HNSW's
    approximation was not in the path. The current anchor names no identity, so
    the target competes with every eligible pair of headphones and sits well
    outside the 150-candidate budget.

    Falsifier: swap `ANCHOR_QUERY` for `Sonorra WHC720` and the final assertion
    fails, because the semantic arm returns the target at rank 1.
    """
    profile = load_profile()
    embedding = get_retrieval_service().embed_query(ANCHOR_QUERY)
    with connect() as connection:
        _configure_hnsw(connection, profile)
        rows = connection.execute(
            "SELECT product_id FROM mosaic_search.search_vector"
            "(%s::vector, %s::jsonb, %s::integer)",
            (embedding, json.dumps(ANCHOR_FILTERS), profile.semantic_limit),
        ).fetchall()

    assert len(rows) == profile.semantic_limit, (
        f"expected the full {profile.semantic_limit}-candidate pool; got "
        f"{len(rows)}, so the filter may be starving the arm rather than the "
        "arm genuinely ranking the target outside it"
    )
    assert not any(row["product_id"] == TARGET_PRODUCT_ID for row in rows)


@pytest.mark.aurora
def test_eligibility_filters_gate_the_trigram_arm_itself():
    """Hard filters apply inside `search_trigram`'s own predicate, not after.

    Witness, independent of the absence under test: under the mission's own
    filters the arm returns the target at rank 1 first -- a positive result
    proving the query and connection work -- before either violating variant
    is tried.

    Falsifier: remove `matches_filter_values` from `search_trigram`'s WHERE
    clause and both violating variants below stop excluding the target.
    """
    with connect() as connection:
        price_cents = connection.execute(
            "SELECT price_cents FROM mosaic_search.product_document "
            "WHERE product_id = %s",
            (TARGET_PRODUCT_ID,),
        ).fetchone()["price_cents"]
        assert price_cents < ANCHOR_FILTERS["max_price_cents"], (
            "the target's own price no longer sits inside the mission's ceiling"
        )

        baseline = connection.execute(
            "SELECT product_id, trigram_rank FROM mosaic_search.search_trigram"
            "(%s, %s::jsonb, 80, 0.20)",
            (ANCHOR_QUERY, json.dumps(ANCHOR_FILTERS)),
        ).fetchall()
        assert baseline == [{"product_id": TARGET_PRODUCT_ID, "trigram_rank": 1}]

        wrong_domain = {**ANCHOR_FILTERS, "domain": "home_office"}
        excluded_by_domain = connection.execute(
            "SELECT product_id FROM mosaic_search.search_trigram(%s, %s::jsonb, 80, 0.20)",
            (ANCHOR_QUERY, json.dumps(wrong_domain)),
        ).fetchall()
        assert excluded_by_domain == []

        below_price = {**ANCHOR_FILTERS, "max_price_cents": price_cents - 1}
        excluded_by_price = connection.execute(
            "SELECT product_id FROM mosaic_search.search_trigram(%s, %s::jsonb, 80, 0.20)",
            (ANCHOR_QUERY, json.dumps(below_price)),
        ).fetchall()
        assert excluded_by_price == []
