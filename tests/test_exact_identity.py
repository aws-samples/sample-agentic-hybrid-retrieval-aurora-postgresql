"""Whole catalog identities narrow the served window without hiding the pool."""

import pytest

from service import retrieval
from service.models import SearchRequest
from service.retrieval_replay import served_window

IDENTITY = {
    "title": "Mosaic Atelier 32 Premium Workspace Display",
    "brand_name": "Mosaic",
    "model_name": "Atelier 32",
    "sku": "HO-420001-MOSAIC",
}


@pytest.mark.parametrize(
    "query",
    ["Mosaic Atelier 32", "mosaic atelier-32", IDENTITY["title"], IDENTITY["sku"]],
)
def test_complete_identity_is_recognized(query):
    assert retrieval._is_exact_identity_query(query, IDENTITY)


@pytest.mark.parametrize(
    "query",
    [
        "Mosaic",
        "Atelier",
        "Atelier 32",
        "Mosaic Atelier 320",
        "alternatives to Mosaic Atelier 32",
        "Mosaic Atelier 32 with a monitor arm",
    ],
)
def test_requests_about_an_identity_keep_their_broader_intent(query):
    assert not retrieval._is_exact_identity_query(query, IDENTITY)


def test_exact_identity_grant_matches_replay_and_retains_candidate_audit():
    candidates = [
        {"product_id": 420001, "exact_identity_match": True, "result_rank": 1},
        {"product_id": 495432, "exact_identity_match": False, "result_rank": 2},
    ]
    request = SearchRequest(query="Mosaic Atelier 32")
    profile = retrieval.RetrievalService()._profile(request)
    selected = retrieval._served_candidates(candidates, request, profile)
    assert selected == candidates[:1]
    assert len(candidates) == 2
    assert profile.authorized_limit == 1
    assert (
        served_window({"retrieval_profile": profile.model_dump()}, candidates)
        == selected
    )


def test_exact_identity_is_promoted_even_when_the_reranker_prefers_a_distractor():
    rows = [
        {
            "product_id": 1,
            "exact_identity_match": False,
            "exact_sku_match": False,
            "pre_rerank_rank": 1,
        },
        {
            "product_id": 2,
            "exact_identity_match": True,
            "exact_sku_match": False,
            "pre_rerank_rank": 2,
        },
    ]
    ordered = sorted(
        rows, key=lambda row: retrieval._final_candidate_sort_key(row, {1: 0.9, 2: 0.1})
    )
    assert [row["product_id"] for row in ordered] == [2, 1]
