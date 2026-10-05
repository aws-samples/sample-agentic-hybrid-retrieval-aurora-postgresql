"""Lab 2's tuning comparison and the HNSW exercise check must measure, not reward cheap passes.

These run without Aurora: they pin the derived comparison and its budget, the
arithmetic it uses, the committed cache's coverage, and the HNSW exercise check's statement
checks and tiers.
"""

import json
from pathlib import Path

import pytest

from scripts import cache_lab2_arms, hnsw_exercise, lab2_tuning
from scripts.lab_exercise import ExerciseError
from service.models import RetrievalProfile

ROOT = Path(__file__).resolve().parents[1]


def served_baseline() -> dict[str, int]:
    profile = RetrievalProfile()
    return {
        key: getattr(profile, key)
        for key in (
            "rrf_k",
            "fused_limit",
            "fts_limit",
            "trigram_limit",
            "semantic_limit",
        )
    }


def test_comparison_changes_are_derived_from_the_served_profile():
    baseline = served_baseline()
    changes = {
        (setting, value) for _, setting, value in lab2_tuning.candidates(baseline)
    }

    assert ("rrf_k", baseline["rrf_k"] * 2) in changes
    assert ("rrf_k", baseline["rrf_k"] // 2) in changes
    longer = round(baseline["fused_limit"] * 3 / 2)
    assert ("fused_limit", min(longer, lab2_tuning.MAX_RERANK_PRODUCTS)) in changes


def test_the_longer_shortlist_stays_within_one_billed_rerank_unit():
    assert lab2_tuning.MAX_RERANK_PRODUCTS == 100
    assert lab2_tuning.PRODUCTS_PER_SEARCH_UNIT == 100
    for _, setting, value in lab2_tuning.candidates(served_baseline()):
        if setting == "fused_limit":
            assert value <= lab2_tuning.MAX_RERANK_PRODUCTS


def test_fusion_reads_only_the_prefix_a_smaller_limit_allows():
    lists = {"fts": [[5, 1], [3, 2]], "trigram": [], "vector": [[3, 1], [9, 2]]}

    full = lab2_tuning.fuse(lists, 60, {"fts": 2, "trigram": 1, "vector": 2})
    trimmed = lab2_tuning.fuse(lists, 60, {"fts": 1, "trigram": 1, "vector": 1})

    assert full == [3, 5, 9]
    assert trimmed == [3, 5]


def test_sign_test_is_two_sided_and_capped():
    assert lab2_tuning.sign_test(0, 0) == 1.0
    assert lab2_tuning.sign_test(4, 0) == pytest.approx(0.125)
    assert lab2_tuning.sign_test(3, 3) == 1.0


def test_comparison_measures_every_change_on_the_judged_queries(monkeypatch):
    monkeypatch.setattr(lab2_tuning, "verify_cache", lambda *_: {"live_spot_checks": 0})
    table = lab2_tuning.comparison_table(None, served_baseline())

    assert [row["label"] for row in table["rows"]] == [
        label for label, _, _ in lab2_tuning.candidates(served_baseline())
    ]
    shortlist = next(row for row in table["rows"] if "fused_limit" in row["change"])
    # A longer cutoff over the same fused order can only add exact matches.
    assert shortlist["exact_gain"] >= 0
    assert shortlist["queries_worse"] == 0
    for row in table["rows"]:
        assert row["billed_search_units_per_query"] == 1
        assert 0 <= row["sign_test_p"] <= 1


def test_cache_covers_every_judged_query_at_the_served_limits():
    cache = json.loads((ROOT / "data/evals/lab2_search_cache.json").read_text())
    subset = json.loads((ROOT / "data/evals/esci_judged_subset.json").read_text())
    baseline = served_baseline()

    assert set(cache["queries"]) == {str(q["query_id"]) for q in subset["queries"]}
    for setting, arm in lab2_tuning.ARM_OF.items():
        assert baseline[setting] <= cache["limits"][arm]
    assert len(cache["chair_controls"]) == 4


def test_bundled_cache_matches_the_rendered_reference_search():
    cache = json.loads((ROOT / "data/evals/lab2_search_cache.json").read_text())
    assert cache.get("source_sha256") == cache_lab2_arms.cache_source_sha256(), (
        "Lab 2 cache source drift: rebuild scripts/cache_lab2_arms.py against "
        "the release's Aurora database before publishing"
    )


def test_cache_source_identity_includes_live_price_filtering(monkeypatch):
    from scripts.catalog import prepare_live_catalog

    current = cache_lab2_arms.cache_source_sha256()
    monkeypatch.setattr(
        prepare_live_catalog,
        "_FILTER_PRICE",
        {key: key for key in prepare_live_catalog._FILTER_PRICE},
    )
    assert cache_lab2_arms.cache_source_sha256() != current
    with pytest.raises(lab2_tuning.TuningError, match="cached source_sha256"):
        lab2_tuning.verify_cache(None, {"source_sha256": current}, {})


def test_comparison_refuses_a_cache_from_another_source_before_querying_aurora():
    with pytest.raises(lab2_tuning.TuningError, match="cached source_sha256"):
        lab2_tuning.verify_cache(None, {"source_sha256": "old"}, {})


def test_cached_search_lists_use_the_production_hnsw_configuration():
    from service.models import RetrievalProfile

    class Connection:
        def __init__(self):
            self.calls = []

        def execute(self, sql, args):
            self.calls.append((sql, args))
            return self

        def fetchall(self):
            return []

    connection = Connection()
    cache_lab2_arms.search_lists(connection, "headphones", {}, "[]")
    sql, args = connection.calls[0]
    profile = RetrievalProfile()
    assert ".configure_hnsw(" in sql
    assert args == (
        profile.ef_search,
        profile.iterative_scan,
        profile.max_scan_tuples,
        profile.scan_mem_multiplier,
    )


def test_grading_prefers_the_workshop_database_cache(tmp_path):
    reference = tmp_path / cache_lab2_arms.REFERENCE_CACHE
    reference.parent.mkdir(parents=True)
    reference.write_text("{}")
    assert cache_lab2_arms.cache_path(tmp_path) == reference
    prepared = tmp_path / cache_lab2_arms.WORKSHOP_CACHE
    prepared.parent.mkdir(parents=True)
    prepared.write_text("{}")
    assert cache_lab2_arms.cache_path(tmp_path) == prepared


HALFVEC_INDEX = (
    "CREATE INDEX alex_hp ON mosaic_catalog_search.product_document USING hnsw "
    "((embedding::halfvec(1024)) halfvec_cosine_ops) WHERE category_key = 'headphones';"
    "\nSET hnsw.ef_search = 400;"
)


def test_hnsw_exercise_accepts_an_expression_index_and_a_search_setting():
    create, name, ef_search = hnsw_exercise.parse_index(HALFVEC_INDEX)

    assert name == "alex_hp"
    assert ef_search == 400
    assert create.startswith("CREATE INDEX alex_hp")


@pytest.mark.parametrize(
    "text",
    [
        "DROP TABLE mosaic.product;",
        (
            "CREATE INDEX CONCURRENTLY x ON mosaic_catalog_search.product_document "
            "USING hnsw (embedding vector_cosine_ops) WHERE category_key = 'headphones';"
        ),
        (
            "CREATE INDEX x ON mosaic_catalog_search.product_document "
            "USING hnsw (embedding vector_cosine_ops);"
        ),
        "CREATE INDEX x ON mosaic.product USING btree (sku) WHERE true;",
        HALFVEC_INDEX + "\nSELECT 1;",
    ],
)
def test_hnsw_exercise_rejects_anything_but_one_partial_hnsw_index(text):
    with pytest.raises(ExerciseError):
        hnsw_exercise.parse_index(text)


def build(recall: float, ratio: float, size: int, uses: bool = True) -> dict:
    return {
        "recall": recall,
        "time_ratio": ratio,
        "index_bytes": size,
        "uses_index": uses,
    }


def test_hnsw_exercise_averages_builds_so_one_unlucky_build_does_not_fail():
    report = hnsw_exercise.summarize(
        "x", 400, [build(0.88, 0.1, 40), build(0.93, 0.1, 40)], 130
    )

    assert report["mean_recall"] == pytest.approx(0.905)
    assert report["fast"] and report["small"]


def test_hnsw_exercise_tiers_separate_fast_from_small_and_unused_indexes():
    fast_only = hnsw_exercise.summarize("x", None, [build(0.99, 0.1, 130)] * 2, 130)
    unused = hnsw_exercise.summarize("x", None, [build(1.0, 1.0, 40, False)] * 2, 130)

    assert fast_only["fast"] and not fast_only["small"]
    assert not unused["fast"]
    assert any("does not use x" in failure for failure in unused["failures"])
