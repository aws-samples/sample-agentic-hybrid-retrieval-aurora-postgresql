"""Exact catalog identities must survive model reranking."""

from service.retrieval import _final_candidate_sort_key, _is_exact_sku_match


def test_exact_sku_match_is_punctuation_insensitive_and_requires_full_identity():
    assert _is_exact_sku_match(
        "Find CO-TRUEW-0017001 charging case", "CO-TRUEW-0017001"
    )
    assert _is_exact_sku_match("Find cotruew0017001 charging case", "CO-TRUEW-0017001")
    assert not _is_exact_sku_match("Find TRUEW charging case", "CO-TRUEW-0017001")


def test_exact_sku_preservation_keeps_identity_ahead_of_a_higher_model_score():
    target = {
        "product_id": 17001,
        "exact_sku_match": True,
        "pre_rerank_rank": 1,
    }
    false_match = {
        "product_id": 17002,
        "exact_sku_match": False,
        "pre_rerank_rank": 2,
    }
    scores = {17001: 0.10, 17002: 0.12}

    ordered = sorted(
        [false_match, target],
        key=lambda row: _final_candidate_sort_key(row, scores),
    )

    assert [row["product_id"] for row in ordered] == [17001, 17002]
