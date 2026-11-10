"""Lab 2's tuning comparison and the HNSW exercise check must measure, not reward cheap passes.

These run without Aurora: they pin the derived comparison and its budget, the
arithmetic it uses, the committed cache's coverage, and the HNSW exercise check's statement
checks and tiers.
"""

import io
import json
from pathlib import Path

import pytest

from scripts import cache_lab2_arms, hnsw_exercise, lab2_tuning
from scripts.lab_exercise import ExerciseError
from service.models import RetrievalProfile
from service.participant_commands import HNSW_GRADE

ROOT = Path(__file__).resolve().parents[1]


def served_baseline() -> dict[str, int]:
    profile = RetrievalProfile()
    return {
        key: getattr(profile, key)
        for key in (
            "rrf_k",
            "fused_limit",
            "fts_limit",
            "fuzzy_limit",
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
    lists = {"fts": [[5, 1], [3, 2]], "fuzzy": [], "semantic": [[3, 1], [9, 2]]}

    full = lab2_tuning.fuse(lists, 60, {"fts": 2, "fuzzy": 1, "semantic": 2})
    trimmed = lab2_tuning.fuse(lists, 60, {"fts": 1, "fuzzy": 1, "semantic": 1})

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
    assert table["scope"].startswith(
        "141 shopper requests whose judged products are in this catalog "
        "(82 headphones, 58 monitors, 1 chair)"
    )
    assert "ESCI" not in table["scope"]
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
        assert baseline[setting] == cache["limits"][arm]
    assert len(cache["chair_controls"]) == 4


def test_the_cache_source_ignores_comments_but_not_sql(monkeypatch):
    """A reworded comment must not ask for a rebuild against Aurora; changed SQL must."""
    sql = (
        "CREATE FUNCTION f() RETURNS int LANGUAGE sql AS $$\n"
        "-- why this returns one\nSELECT 1\n$$;\n"
    )
    renders = iter(
        [
            sql,
            sql.replace("why this returns one", "the same reason, reworded"),
            sql.replace("SELECT 1", "SELECT 2"),
        ]
    )
    monkeypatch.setattr(
        "service.search_sql.search_sql", lambda *_args, **_kwargs: next(renders)
    )

    original, reworded, changed = (
        cache_lab2_arms.cache_source_sha256() for _ in range(3)
    )

    assert original == reworded
    assert changed != original


def test_bundled_cache_matches_the_rendered_reference_search():
    cache = json.loads((ROOT / "data/evals/lab2_search_cache.json").read_text())
    assert cache.get("source_sha256") == cache_lab2_arms.cache_source_sha256(), (
        "Lab 2 cache source drift: rebuild scripts/cache_lab2_arms.py against "
        "the release's Aurora database before publishing"
    )


def test_cache_source_identity_includes_source_price_filtering(tmp_path):
    from shutil import copy2

    from service.lab_files import solution_path
    from service.search_sql import SEARCH_SQL_FILES

    for path in SEARCH_SQL_FILES:
        for relative in {path, solution_path(path)}:
            if (ROOT / relative).is_file():
                (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
                copy2(ROOT / relative, tmp_path / relative)
    current = cache_lab2_arms.cache_source_sha256(tmp_path)
    assert current == cache_lab2_arms.cache_source_sha256()
    channels = tmp_path / "db/sql/08_search_channels.sql"
    channels.write_text(
        channels.read_text().replace(
            "coalesce(d.price_cents, d.historical_price_cents)", "d.price_cents"
        )
    )
    assert cache_lab2_arms.cache_source_sha256(tmp_path) != current
    with pytest.raises(lab2_tuning.TuningError, match="cached source_sha256"):
        lab2_tuning.verify_cache(None, {"source_sha256": current + "0"}, {})


def test_comparison_refuses_a_cache_from_another_source_before_querying_aurora():
    with pytest.raises(lab2_tuning.TuningError, match="cached source_sha256"):
        lab2_tuning.verify_cache(None, {"source_sha256": "old"}, {})


@pytest.mark.parametrize("fault", ["larger_pool", "threshold"])
def test_comparison_refuses_different_candidate_generation_before_querying_aurora(
    fault,
):
    from scripts.checks.retrieval_profile import load_profile

    cache = {
        "source_sha256": cache_lab2_arms.cache_source_sha256(),
        "limits": cache_lab2_arms.served_limits(),
        "fuzzy_threshold": load_profile().fuzzy_threshold,
    }
    if fault == "larger_pool":
        cache["limits"]["semantic"] *= 2
    else:
        cache["fuzzy_threshold"] /= 2
    with pytest.raises(
        lab2_tuning.TuningError, match="cached (channel limits|fuzzy threshold)"
    ):
        lab2_tuning.verify_cache(None, cache, {})


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
    assert [args[2] for _, args in connection.calls[1:]] == [
        profile.fts_limit,
        profile.fuzzy_limit,
        profile.semantic_limit,
    ]


def test_the_proposed_shortlist_is_a_supported_configuration(monkeypatch):
    from scripts.checks.retrieval_profile import load_profile

    monkeypatch.setenv("RERANK_CANDIDATE_LIMIT", "75")
    assert load_profile().fused_limit == 75


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
    "CREATE INDEX alex_hp ON mosaic_search.product_listing USING hnsw "
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
            "CREATE INDEX CONCURRENTLY x ON mosaic_search.product_listing "
            "USING hnsw (embedding vector_cosine_ops) WHERE category_key = 'headphones';"
        ),
        (
            "CREATE INDEX x ON mosaic_search.product_listing "
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


@pytest.mark.parametrize(
    ("line", "used"),
    [
        ("  ->  Index Scan using shrink_hp on product_listing", True),
        ("  ->  Index Only Scan using shrink_hp on product_listing", True),
        ("  ->  Index Scan Backward using shrink_hp on product_listing", True),
        ("        ->  Bitmap Index Scan on shrink_hp", True),
        ("  ->  Index Scan using shrink_hp_old on product_listing", False),
        ("  ->  Index Scan using old_shrink_hp on product_listing", False),
        ("  ->  Seq Scan on shrink_hp", False),
        ("        Filter: (category_key = 'shrink_hp'::text)", False),
    ],
)
def test_hnsw_exercise_credits_only_a_scan_node_that_names_the_index(line, used):
    plan = [
        "Limit (actual time=0.1..0.2 rows=150 loops=1)",
        line,
        "Execution Time: 1.0 ms",
    ]

    assert ("shrink_hp" in hnsw_exercise.plan_indexes(plan)) is used


def test_hnsw_exercise_does_not_credit_another_index_whose_name_contains_yours(
    monkeypatch,
):
    """Index `product` must not take credit for `product_search_vector_idx`'s scan.

    Recall, timing and size are stand-ins chosen to pass, so only the plan's
    index identity can fail the grade.
    """
    from unittest.mock import MagicMock

    connection, cursor = MagicMock(), MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchall.return_value = [{"product_id": 1}]
    cursor.fetchone.side_effect = [{"b": 1000}, {"b": 100}, {"b": 100}]
    plan = [
        "Limit",
        "  ->  Index Scan using product_search_vector_idx on product_listing",
        "Execution Time: 1.0 ms",
    ]
    monkeypatch.setattr(hnsw_exercise, "_connect", lambda: connection)
    monkeypatch.setattr(hnsw_exercise, "query_vectors", lambda: ["[0]"])
    monkeypatch.setattr(
        hnsw_exercise,
        "measure_build",
        lambda *_args: ({"recall": 1.0, "time_ratio": 0.2}, [plan]),
    )

    result = hnsw_exercise.grade(
        "CREATE INDEX product ON mosaic_search.product_listing USING hnsw "
        "((embedding::halfvec(1024)) halfvec_cosine_ops) "
        "WHERE category_key = 'headphones';",
        "SELECT product_id FROM mosaic_search.product_listing "
        "WHERE category_key = 'headphones' "
        "ORDER BY embedding <=> :'hnsw_vector'::vector LIMIT :hnsw_limit;",
    )

    assert not result["fast"] and not result["small"]
    assert any("does not use product" in failure for failure in result["failures"])


def test_hnsw_exercise_names_an_empty_index_file():
    """The page creates both files empty; checking them first said only the contract."""
    with pytest.raises(
        ExerciseError, match=r"index\.sql is empty; write one CREATE INDEX"
    ):
        hnsw_exercise.parse_index("")
    with pytest.raises(
        ExerciseError, match=r"holds \d+ statements; it takes one CREATE INDEX"
    ):
        hnsw_exercise.parse_index(
            HALFVEC_INDEX + "\nSET hnsw.ef_search = 40;\nSELECT 1;"
        )


def test_hnsw_exercise_names_an_empty_search_file(monkeypatch, tmp_path, capsys):
    (tmp_path / ".local/hnsw").mkdir(parents=True)
    (tmp_path / ".local/hnsw/index.sql").write_text(HALFVEC_INDEX)
    (tmp_path / ".local/hnsw/search.sql").write_text("")
    monkeypatch.setattr(hnsw_exercise, "REPO", tmp_path)
    monkeypatch.setattr("sys.argv", ["hnsw_exercise.py", "grade"])
    assert hnsw_exercise.main() == 2
    assert "search.sql is empty; write one SELECT" in capsys.readouterr().out


# ---------------------------------------------------------------- progress, layout, Next, colour


def _report(*, fast: bool, small: bool) -> dict:
    build = {
        "recall": 0.98,
        "time_ratio": 0.02,
        "index_bytes": 121_900_000,
        "uses_index": True,
    }
    return {
        "builds": [build, build],
        "reference_index_bytes": 370_000_000,
        "size_ratio_vs_full_precision": 0.33,
        "fast": fast,
        "small": small,
        "failures": [] if fast else ["mean recall 0.5 over 2 builds; the bar is 0.9"],
    }


def _graded_main(monkeypatch, tmp_path, report, stream):
    (tmp_path / ".local/hnsw").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".local/hnsw/index.sql").write_text(HALFVEC_INDEX)
    (tmp_path / ".local/hnsw/search.sql").write_text("SELECT product_id")
    monkeypatch.setattr(hnsw_exercise, "REPO", tmp_path)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_: None)

    def grade(_index, _search, progress=None):
        for number in range(1, len(hnsw_exercise.GRADE_STEPS) + 1):
            hnsw_exercise.start_step(progress, number)
        return report

    monkeypatch.setattr(hnsw_exercise, "grade", grade)
    monkeypatch.setattr("sys.argv", ["hnsw_exercise.py", "grade"])
    monkeypatch.setattr("sys.stdout", stream)
    code = hnsw_exercise.main()
    return code, stream.getvalue()


def test_the_grader_shows_each_step_with_the_time_waited_not_an_invented_usual_time(
    monkeypatch, tmp_path
):
    code, out = _graded_main(
        monkeypatch, tmp_path, _report(fast=True, small=True), io.StringIO()
    )

    steps = [line for line in out.splitlines() if line.startswith("  - ")]
    assert code == 0
    assert out.startswith("Grading your index\n")
    assert steps == [
        "  - 1/4  Run the exact plan for the five queries",
        "  - 2/4  Build a full-precision reference index to measure its size",
        "  - 3/4  Build your index (1 of 2) and run its five queries",
        "  - 4/4  Build your index (2 of 2) and run its five queries",
    ]
    assert "usually" not in out
    assert "  1/4  Ran the exact plan for the five queries" in out
    assert "  4/4  Built your index (2 of 2) and ran its five queries" in out


def test_the_grader_redraws_one_line_with_the_time_waited_on_a_terminal(
    monkeypatch, tmp_path
):
    from scripts import progress as progress_module

    class Terminal(io.StringIO):
        encoding = "utf-8"

        def isatty(self):
            return True

    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(progress_module, "columns", lambda: 100)
    shown = []
    real = progress_module.Progress._render

    def spy(self, width):
        line = real(self, width)
        shown.append(line)
        return line

    monkeypatch.setattr(progress_module.Progress, "_render", spy)
    stream = Terminal()

    def grade(_index, _search, progress=None):
        hnsw_exercise.start_step(progress, 3)
        progress._live.draw()
        return _report(fast=True, small=True)

    (tmp_path / ".local/hnsw").mkdir(parents=True)
    (tmp_path / ".local/hnsw/index.sql").write_text(HALFVEC_INDEX)
    (tmp_path / ".local/hnsw/search.sql").write_text("SELECT product_id")
    monkeypatch.setattr(hnsw_exercise, "REPO", tmp_path)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_: None)
    monkeypatch.setattr(hnsw_exercise, "grade", grade)
    monkeypatch.setattr("sys.argv", ["hnsw_exercise.py", "grade"])
    monkeypatch.setattr("sys.stdout", stream)

    hnsw_exercise.main()

    assert (
        shown[-1].strip()
        == "[3/4] Build your index (1 of 2) and run its five queries  0:00"
    )


def test_grade_starts_its_steps_in_the_order_it_does_the_work(monkeypatch):
    from unittest.mock import MagicMock

    connection, cursor = MagicMock(), MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchall.return_value = [{"product_id": 1}]
    cursor.fetchone.side_effect = [{"b": 1000}, {"b": 100}, {"b": 100}]
    monkeypatch.setattr(hnsw_exercise, "_connect", lambda: connection)
    monkeypatch.setattr(hnsw_exercise, "query_vectors", lambda: ["[0]"])
    monkeypatch.setattr(
        hnsw_exercise,
        "measure_build",
        lambda *_args: (
            {"recall": 1.0, "time_ratio": 0.2},
            [["Index Scan using product"]],
        ),
    )
    progress = MagicMock()

    hnsw_exercise.grade(
        HALFVEC_INDEX,
        "SELECT product_id FROM mosaic_search.product_listing "
        "ORDER BY embedding <=> :'hnsw_vector'::vector LIMIT :hnsw_limit;",
        progress,
    )

    assert [
        (call.args[0], call.kwargs["done"]) for call in progress.begin.call_args_list
    ] == list(hnsw_exercise.GRADE_STEPS)


def test_a_failed_grade_names_the_step_that_failed_before_the_verdict(
    monkeypatch, tmp_path, capsys
):
    (tmp_path / ".local/hnsw").mkdir(parents=True)
    (tmp_path / ".local/hnsw/index.sql").write_text(HALFVEC_INDEX)
    (tmp_path / ".local/hnsw/search.sql").write_text("SELECT product_id")
    monkeypatch.setattr(hnsw_exercise, "REPO", tmp_path)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_: None)

    def grade(_index, _search, progress=None):
        hnsw_exercise.start_step(progress, 3)
        raise ExerciseError("PostgreSQL rejected the index: nope")

    monkeypatch.setattr(hnsw_exercise, "grade", grade)
    monkeypatch.setattr("sys.argv", ["hnsw_exercise.py", "grade"])

    assert hnsw_exercise.main() == 2

    out = capsys.readouterr().out
    assert "3/4  Build your index (1 of 2) and run its five queries: failed" in out
    assert "Shrink it: CANNOT GRADE - PostgreSQL rejected the index: nope" in out
    assert out.endswith(f"then grade again:\n{HNSW_GRADE}\n")
    assert "\n\n\n" not in out


@pytest.mark.parametrize(
    ("fast", "small", "tier", "next_words"),
    [
        (True, True, "FAST AND SMALL", "Session & Memory"),
        (True, False, "FAST", "to reach FAST AND SMALL"),
        (False, False, "NOT YET", "as the FAIL lines say"),
    ],
)
def test_the_result_is_its_own_part_and_the_next_step_fits_it(
    monkeypatch, tmp_path, fast, small, tier, next_words
):
    code, out = _graded_main(
        monkeypatch, tmp_path, _report(fast=fast, small=small), io.StringIO()
    )

    parts = out.rstrip("\n").split("\n\n")
    assert code == (0 if fast else 1)
    assert not out.startswith("\n") and "\n\n\n" not in out
    assert parts[-2] == f"Shrink it: {tier}"
    assert parts[-1].startswith("Next: ") and next_words in parts[-1]
    assert parts[-3].splitlines()[0].startswith(("build 1:", "FAIL:"))
    if not fast:
        assert HNSW_GRADE in parts[-1]


@pytest.mark.parametrize(
    ("fast", "small", "tier", "code"),
    [
        (True, True, "FAST AND SMALL", "1;32"),
        (True, False, "FAST", "1;32"),
        (False, False, "NOT YET", "1;33"),
    ],
)
def test_the_result_word_is_coloured_on_a_terminal_and_plain_when_piped(
    monkeypatch, tmp_path, fast, small, tier, code
):
    class Terminal(io.StringIO):
        encoding = "utf-8"

        def isatty(self):
            return True

    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("MOSAIC_RUN_BY", raising=False)
    report = _report(fast=fast, small=small)

    _, painted = _graded_main(monkeypatch, tmp_path, report, Terminal())
    _, plain = _graded_main(monkeypatch, tmp_path, report, io.StringIO())

    assert f"Shrink it: \033[{code}m{tier}\033[0m" in painted
    assert "\033" not in plain and f"Shrink it: {tier}\n" in plain
