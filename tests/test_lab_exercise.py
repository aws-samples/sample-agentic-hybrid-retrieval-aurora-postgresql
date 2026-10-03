"""The exercise grader must grade participant work, not agree with it.

Each grader compares written work with an independently computed answer. These
tests pin the parts that run without Aurora: psql variable expansion, the RRF
reference and its diagnostics, the Lab 1 index trap message, and the managed agent completion path.
"""

from pathlib import Path
from unittest.mock import MagicMock

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


class _ContributionCursor:
    """Answers the grader's generate_series query with a chosen contribution formula."""

    def __init__(self, formula):
        self.formula = formula
        self.rows = []

    def execute(self, sql, args):
        k, ranks = args
        self.rows = [{"r": r, "c": self.formula(r, k)} for r in range(1, ranks + 1)]

    def fetchall(self):
        return self.rows


def test_contribution_grader_names_the_first_position_that_shares_a_value():
    collapsed = _ContributionCursor(lambda rank, k: 1.0 / (k + 1))
    failure = lab_exercise._lab2_contribution_mismatch(collapsed, "s", 60, 150)
    assert failure is not None
    assert failure.startswith("k=60: position 2 earns")
    assert "1 / (60 + 2)" in failure


def test_contribution_grader_accepts_reciprocal_rank_at_every_k():
    correct = _ContributionCursor(lambda rank, k: 1.0 / (k + rank))
    for k in (1, 10, 30, 60, 120):
        assert lab_exercise._lab2_contribution_mismatch(correct, "s", k, 150) is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), None])
def test_contribution_grader_rejects_missing_or_nonfinite_values(value):
    cursor = _ContributionCursor(lambda rank, k: value)
    assert lab_exercise._lab2_contribution_mismatch(cursor, "s", 60, 150)


@pytest.mark.parametrize(
    ("saved", "failure"),
    [
        ({1: 0.123, 2: 1 / 62}, "disagree"),
        ({}, "no saved rows"),
        ({1: 1 / 61}, "target 2"),
        ({1: 1 / 61, 2: 1 / 62, 999: 0.123}, "disagree"),
        ({1: float("nan"), 2: 1 / 62}, "disagree"),
        ({1: float("inf"), 2: 1 / 62}, "disagree"),
        ({1: None, 2: 1 / 62}, "disagree"),
    ],
)
def test_lab2_grader_fails_saved_results_that_do_not_prove_the_repair(
    monkeypatch, saved, failure
):
    report = _grade_lab2_saved_run(monkeypatch, saved)
    assert any(failure in message for message in report["failures"])
    assert all("--phase after" in message for message in report["failures"])


def test_lab2_grader_accepts_matching_saved_results(monkeypatch):
    report = _grade_lab2_saved_run(monkeypatch, {1: 1 / 61, 2: 1 / 62})
    assert report["failures"] == []
    assert report["saved_run"]["rows_disagreeing_with_correct_fusion"] == 0
    assert report["saved_run"]["target_saved"]


def _grade_lab2_saved_run(monkeypatch, saved):
    connection = MagicMock()
    cursor = (
        connection.__enter__.return_value.cursor.return_value.__enter__.return_value
    )
    cursor.fetchall.side_effect = lambda: [
        {"r": rank, "c": 1 / (cursor.execute.call_args.args[1][0] + rank)}
        for rank in range(1, lab_exercise.LAB2_RANKS_CHECKED + 1)
    ]
    monkeypatch.setattr(lab_exercise, "_connect", lambda: connection)
    monkeypatch.setattr(lab_exercise, "_configure", lambda *a, **kw: None)
    monkeypatch.setattr(lab_exercise, "_lab2_arms", lambda *a: {"fts": {1: 1, 2: 2}})
    monkeypatch.setattr(lab_exercise, "_saved_run", lambda *a: saved)
    return lab_exercise.grade_lab2(
        {"lab_rrf_k": "60", "lab_target": "2", "lab_fused_limit": "2"}
    )


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
