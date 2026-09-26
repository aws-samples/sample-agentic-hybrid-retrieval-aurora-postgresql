"""The exercise grader must grade participant work, not agree with it.

Each grader compares written work with an independently computed answer. These
tests pin the parts that run without Aurora: psql variable expansion, the RRF
reference and its diagnostics, the Lab 1 index trap message, and the managed agent completion path.
"""

from pathlib import Path

import pytest

from scripts import lab_exercise
from scripts.lab_exercise import ExerciseError, interpolate

ROOT = Path(__file__).resolve().parents[1]
VALUES = {"lab_query": "B07G95T3JP", "lab_rrf_k": "60", "lab_filters": '{"a": 1}'}


def test_interpolation_expands_variables_and_drops_the_final_semicolon():
    sql = (
        "SELECT :'lab_query' AS q, :lab_rrf_k AS k, :'lab_filters'::jsonb AS f, "
        "':lab_query' AS literal -- :lab_rrf_k in a comment\n;"
    )

    assert interpolate(sql, VALUES) == (
        "SELECT 'B07G95T3JP' AS q, 60 AS k, '{\"a\": 1}'::jsonb AS f, "
        "':lab_query' AS literal -- :lab_rrf_k in a comment"
    )


def test_interpolation_escapes_quotes_in_values():
    assert interpolate("SELECT :'lab_query'", {"lab_query": "it's"}) == "SELECT 'it''s'"


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("SELECT 1; SELECT 2", "more than one statement"),
        ("\\set x 1\nSELECT 1", "psql command"),
        ("SELECT :lab_missing", "unknown variable :lab_missing"),
        ("SET enable_sort = off", "single SELECT or WITH"),
    ],
)
def test_interpolation_rejects_what_the_grader_cannot_run(sql, message):
    with pytest.raises(ExerciseError, match=message):
        interpolate(sql, VALUES)


def test_reference_fusion_decays_with_rank_and_breaks_ties_by_product_id():
    arms = {"fts": {5: 1, 3: 2}, "vector": {3: 1, 9: 2}}

    fused = lab_exercise._fuse(arms, 60)

    assert [product for product, _ in fused] == [3, 5, 9]
    assert fused[0][1] == pytest.approx(1 / 62 + 1 / 61)
    assert fused[1][1] == pytest.approx(1 / 61)


def test_fusion_grader_names_the_first_wrong_score_and_position():
    truth = lab_exercise._fuse({"fts": {5: 1, 3: 2}}, 60)
    rows = [
        {"product_id": 5, "rrf_score": 1 / 61, "combined_position": 1},
        {"product_id": 3, "rrf_score": 1 / 61, "combined_position": 2},
    ]
    assert "product 3 scores" in lab_exercise._lab2_mismatch(rows, truth, 60)

    rows[1]["rrf_score"] = 1 / 62
    rows[0]["combined_position"], rows[1]["combined_position"] = 2, 1
    assert "combined position" in lab_exercise._lab2_mismatch(rows, truth, 60)

    rows[0]["combined_position"], rows[1]["combined_position"] = 1, 2
    assert lab_exercise._lab2_mismatch(rows, truth, 60) is None
    assert "must appear once" in lab_exercise._lab2_mismatch(rows[:1], truth, 60)


def test_recall_grader_explains_an_exact_set_served_by_the_index():
    truth = {"approximate_rows": 150, "exact_rows": 150, "recall": 0.467}
    mine = {"approximate_rows": 150, "exact_rows": 150, "recall": 1.0}

    assert "same HNSW index" in lab_exercise._lab1_verdict("forced HNSW", mine, truth)
    assert (
        lab_exercise._lab1_verdict("forced HNSW", {**mine, "recall": 0.467}, truth)
        is None
    )


def test_recall_grader_explains_the_untouched_skeleton():
    truth = {"approximate_rows": 150, "exact_rows": 150, "recall": 1.0}
    mine = {"approximate_rows": 150, "exact_rows": 0, "recall": None}

    assert "returned no rows" in lab_exercise._lab1_verdict(
        "planner's plan", mine, truth
    )


def test_recall_truth_narrows_by_indexed_columns_for_each_filter_present():
    narrowing, params = lab_exercise._indexable_filter_sql(
        {
            "domain": "consumer_electronics",
            "category_key": "headphones",
            "brand": "Bose",
        }
    )

    assert narrowing == (
        " AND d.domain = %s::mosaic.product_domain AND d.category_key = %s"
    )
    assert params == ["consumer_electronics", "headphones"]
    assert lab_exercise._indexable_filter_sql({"brand": "Bose"}) == ("", [])
