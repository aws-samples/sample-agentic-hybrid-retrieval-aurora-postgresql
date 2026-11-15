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
    arms = {"fts": {5: 1, 3: 2}, "semantic": {3: 1, 9: 2}}

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


@pytest.mark.parametrize("condition", ["planner's plan", "forced HNSW"])
def test_recall_grader_explains_an_exact_set_served_by_the_index(condition):
    # On the saved Headphones request the planner serves a plain
    # ORDER BY embedding <=> ... LIMIT from HNSW with default settings, so the
    # mistake shows under the planner's plan, not only with enable_sort off.
    truth = {"approximate_rows": 150, "exact_rows": 150, "recall": 0.467}
    mine = {"approximate_rows": 150, "exact_rows": 150, "recall": 1.0}

    message = lab_exercise._lab1_verdict(condition, mine, truth)
    assert message.startswith(f"{condition}: your query reports recall 1.0")
    assert "same HNSW index" in message
    assert (
        lab_exercise._lab1_verdict(condition, {**mine, "recall": 0.467}, truth) is None
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


def test_comparison_names_chair_requests_and_a_lost_right_answer(capsys):
    lab_exercise.print_comparison(
        {
            "baseline": {"exact_in_cutoff": 500, "billed_search_units_per_query": 1},
            "rows": [
                {
                    "label": "k = 120",
                    "exact_gain": -1,
                    "queries_better": 0,
                    "queries_worse": 1,
                    "sign_test_p": 1.0,
                    "billed_search_units_per_query": 1,
                    "chair_controls_moved": [
                        {"id": "C-2", "from": 87, "to": 89},
                        {"id": "C-3", "from": 40, "to": None},
                    ],
                }
            ],
            "scope": "scope line",
        }
    )
    out = capsys.readouterr().out
    assert "chair request C-2: right answer moves from #87 to #89" in out
    assert "chair request C-3: right answer moves from #40 to not found" in out
    assert "control" not in out


def _lab3_proof(monkeypatch, checks):
    from types import SimpleNamespace
    from uuid import uuid4

    monkeypatch.setattr(lab_exercise.lab_state, "lab3_problem", lambda: None)
    monkeypatch.setattr(
        "service.agentcore_transport.runtime_arn", lambda: "arn:runtime"
    )
    monkeypatch.setattr(
        lab_exercise, "load_context", lambda _lab: {"lab_agent_id": str(uuid4())}
    )
    proof = SimpleNamespace(
        status="fail",
        checks=[SimpleNamespace(name=n, passed=p, detail=d) for n, p, d in checks],
    )
    monkeypatch.setattr("service.lab_proof.completion_proof", lambda *_a, **_k: proof)
    return ROOT / lab_exercise.DEFAULT_WORK[3]


def test_lab3_run_that_asked_another_question_reports_only_that(monkeypatch):
    """The 100W follow-up's run fails most checks; the question is the one to fix."""
    work = _lab3_proof(
        monkeypatch,
        [
            ("canonical mission request answered", False, "found a different question"),
            ("canonical target classes covered", False, "found one target"),
            ("required claims supported", False, "found no chair claim"),
        ],
    )
    assert lab_exercise.grade_lab3(work)["failures"] == ["found a different question"]


def test_lab3_setup_run_reports_every_failing_check(monkeypatch):
    work = _lab3_proof(
        monkeypatch,
        [
            ("canonical mission request answered", True, "matches"),
            ("canonical target classes covered", False, "found one target"),
            ("managed_agent_deployed", False, "found no deploy"),
        ],
    )
    assert lab_exercise.grade_lab3(work)["failures"] == [
        "found one target",
        "found no deploy",
    ]


@pytest.mark.parametrize(
    ("checks", "due", "needs"),
    [
        (
            # A 100W run saved before the last deploy fails only the follow-up's checks.
            [
                ("canonical mission request answered", True, "matches"),
                ("managed_agent_deployed", True, "deployed"),
                ("changed requirement checked", False, "made by different code"),
                ("changed requirement deployment", False, "saved before your deploy"),
            ],
            False,
            {"deploy": False, "setup": False, "follow_up": True},
        ),
        (
            # A setup answer a check refused needs that request again, not the 100W one.
            [
                ("canonical mission request answered", True, "matches"),
                (
                    "finished answer support reviewed",
                    False,
                    "a claim no record supports",
                ),
                ("changed requirement checked", True, "read the specification"),
            ],
            False,
            {"deploy": False, "setup": True, "follow_up": False},
        ),
        (
            # Code changed after the deploy: both runs must come from the next one.
            [
                ("managed_agent_deployed", False, "code changed after your deploy"),
                ("changed requirement checked", True, "read the specification"),
            ],
            True,
            {"deploy": True, "setup": True, "follow_up": True},
        ),
    ],
)
def test_lab3_a_failed_grade_needs_only_the_runs_its_checks_fail(
    monkeypatch, checks, due, needs
):
    work = _lab3_proof(monkeypatch, checks)
    monkeypatch.setattr("service.agent_deploys.deploy_due", lambda *_a, **_k: due)

    assert lab_exercise.grade_lab3(work)["needs"] == needs


def test_lab3_names_the_contract_part_the_agent_misses(monkeypatch):
    clause = "Agent needs hooks=hooks, the supplied execution hooks"
    monkeypatch.setattr(lab_exercise.lab_state, "lab3_problem", lambda: clause)
    with pytest.raises(ExerciseError, match="hooks=hooks"):
        lab_exercise.grade_lab3(ROOT / lab_exercise.DEFAULT_WORK[3])


def test_a_missing_context_names_the_command_that_saves_one(monkeypatch, tmp_path):
    from service.participant_commands import repeat_request_command

    monkeypatch.setattr(lab_exercise, "REPO", tmp_path)

    for lab in (1, 2):
        with pytest.raises(ExerciseError) as refused:
            lab_exercise.load_context(lab)
        assert f"run `{repeat_request_command(lab)}` first" in str(refused.value)
        assert "--phase before" not in str(refused.value)


def test_a_saved_run_for_another_request_names_the_repeat_command():
    from service.participant_commands import repeat_request_command

    cur = MagicMock()
    cur.fetchone.return_value = None

    with pytest.raises(ExerciseError) as refused:
        lab_exercise._saved_run(
            cur, {"lab_search_id": "s", "lab_query": "q", "lab_filters": "{}"}
        )

    assert str(refused.value).endswith(f"rerun `{repeat_request_command(2)}`")


def test_the_graded_files_are_found_from_the_checkout_not_the_shells_folder(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    for lab in (1, 2, 3):
        assert lab_exercise.default_work(lab).is_relative_to(ROOT)
    assert lab_exercise.default_work(3) == ROOT / "labs/lab3_reason/agent.py"
    assert lab_exercise._shown(lab_exercise.default_work(2)) == (
        "labs/lab2_rank/rrf_contribution.sql"
    )


def test_lab_3_without_a_graded_run_points_at_the_completion_check(
    monkeypatch, tmp_path
):
    """The check finds the newest setup run and names any question still missing."""
    from service.participant_commands import ask_setup_command, grade_setup_run_command

    monkeypatch.setattr(lab_exercise, "REPO", tmp_path)

    with pytest.raises(ExerciseError) as refused:
        lab_exercise.load_context(3)

    message = str(refused.value)
    assert grade_setup_run_command() in message
    assert ask_setup_command() not in message
    assert "lab_request" not in message


def test_comparison_scope_wraps_at_word_boundaries(capsys):
    words = "judged shopper requests whose products are in this catalog " * 6
    lab_exercise.print_comparison(
        {
            "baseline": {"exact_in_cutoff": 1, "billed_search_units_per_query": 1},
            "rows": [],
            "scope": words.strip(),
        }
    )
    lines = capsys.readouterr().out.splitlines()
    scope_lines = [
        line
        for line in lines
        if line.startswith(("judged", "shopper")) or "catalog" in line
    ]
    assert len(scope_lines) >= 3
    assert all(len(line) <= 100 for line in scope_lines)
    assert all(not line.endswith("-") for line in scope_lines)
    assert " ".join(scope_lines) == words.strip()


def test_a_hyphenated_word_at_the_margin_moves_whole_to_the_next_line(capsys):
    scope = "judged " * 13 + "noise-cancelling headphones"
    assert len(scope[: scope.index("noise-") + 6]) == 97
    lab_exercise.print_comparison(
        {
            "baseline": {"exact_in_cutoff": 1, "billed_search_units_per_query": 1},
            "rows": [],
            "scope": scope,
        }
    )
    lines = capsys.readouterr().out.splitlines()
    assert any(line.startswith("noise-cancelling") for line in lines)
    assert all(not line.endswith("-") for line in lines)


def test_the_untouched_recall_starter_is_named_before_any_grading(
    monkeypatch, tmp_path
):
    """A reviewer ran the check on the starter and read a FAIL as a broken checker."""
    work = tmp_path / "recall.sql"
    work.write_text(
        "WITH exact AS (\n    -- The true nearest eligible products.\n"
        f"    {lab_exercise.RECALL_PLACEHOLDER}\n)\nSELECT 1;\n"
    )
    monkeypatch.setattr(lab_exercise, "load_context", lambda lab: {})

    def never(*args, **kwargs):
        raise AssertionError("grading must not run on the starter")

    monkeypatch.setattr(lab_exercise, "grade_lab1", never)
    with pytest.raises(
        lab_exercise.ExerciseError, match="still has the starting placeholder"
    ):
        lab_exercise.grade(1, work)


def test_the_recall_report_fits_the_terminal_without_breaking_a_word(capsys):
    """Code Editor wrapped the one-line report mid-word ("product_search_|vector_idx")."""
    truth = {
        "recall": 0.76,
        "approximate_rows": 150,
        "exact_rows": 150,
        "access_path": (
            "->  Index Scan using product_search_vector_idx on product_listing d "
            "(actual time=2.613..9.896 rows=164.00 loops=1)"
        ),
        "execution": "Execution Time: 13.000 ms",
    }
    lab_exercise._print_lab1(
        {
            "conditions": {
                "planner's plan": {"independent": truth},
                "forced HNSW": {"independent": truth},
            }
        }
    )

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 4 and all(len(line) <= 100 for line in lines)
    assert (
        lines[0].startswith("planner's plan")
        and "recall 0.760 (150 returned, 150 exact)" in lines[0]
    )
    assert lines[1].strip() == (
        "Index Scan using product_search_vector_idx on product_listing d; Execution Time: 13.000 ms"
    )
    assert lines[2].startswith("forced HNSW")


def test_a_failure_wraps_its_prose_and_keeps_each_command_whole():
    from service.lab_checks import reason_fix
    from service.participant_commands import ask_setup_command

    text = lab_exercise.failure_lines("no run ID was given; fix: " + reason_fix())

    lines = text.splitlines()
    assert lines[0].startswith("FAIL: ")
    assert ask_setup_command() in lines
    assert all(len(line) <= 100 for line in lines if not line.startswith("uv run "))
    assert all(not line.endswith("-") for line in lines)


@pytest.mark.parametrize("lab", [2, 3])
def test_a_deleted_lab_file_names_reset_not_save_your_work(
    lab, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(lab_exercise, "REPO", tmp_path)

    assert lab_exercise.main(["grade", "--lab", str(lab)]) == 2

    out = capsys.readouterr().out
    assert f"Lab {lab}: FILE MISSING" in out
    assert f"uv run python scripts/lab_state.py reset --lab {lab}" in out
    assert "save your work" not in out
    assert out.count("Next:") == 1


def test_a_missing_lab_1_recall_file_still_says_to_save_it(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(lab_exercise, "REPO", tmp_path)

    assert lab_exercise.main(["grade", "--lab", "1"]) == 2

    assert "save your work there first" in capsys.readouterr().out


@pytest.mark.parametrize(
    "reason", ["the saved run has no answer", "the agent is not built. Next: build it"]
)
def test_a_lab_3_cannot_grade_prints_one_next_naming_the_setup_run_command(
    reason, monkeypatch, capsys
):
    from service.participant_commands import grade_setup_run_command

    def refuse(lab, work, run_id=None):
        raise ExerciseError(reason)

    monkeypatch.setattr(lab_exercise, "grade", refuse)
    monkeypatch.setattr(lab_exercise.lab_state, "missing_file_problem", lambda *a: None)

    assert lab_exercise.main(["grade", "--lab", "3"]) == 2

    out = capsys.readouterr().out
    assert out.count("Next:") == 1
    assert "grade --lab 3" not in out
    if "Next: build it" not in out:
        assert grade_setup_run_command() in out


def test_compare_names_an_unreachable_aurora_in_words_and_the_same_comparison(
    monkeypatch, capsys
):
    import psycopg

    from service.participant_commands import COMPARE_SETTINGS

    def unreachable(lab):
        raise psycopg.errors.ConnectionTimeout("connection timeout expired")

    monkeypatch.setattr(lab_exercise, "compare", unreachable)

    assert lab_exercise.main(["compare", "--lab", "2"]) == 2

    out = capsys.readouterr().out
    assert "Lab 2 comparison: CANNOT MEASURE - Aurora did not answer (timed out)" in out
    assert "OperationalError" not in out and "Traceback" not in out
    assert out.count("Next:") == 1 and out.endswith(COMPARE_SETTINGS + "\n")


class _RecordingConnection:
    def __init__(self):
        self.inserted = []

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, sql, params=None):
        if params:
            self.inserted.append(params)


@pytest.mark.parametrize(
    ("report_run", "values", "expected"),
    [
        (
            "agent-run",
            {"lab_search_id": "search", "lab_agent_id": "saved"},
            "agent-run",
        ),
        (None, {"lab_search_id": "search", "lab_agent_id": "saved"}, "search"),
        (None, {"lab_agent_id": "saved"}, "saved"),
    ],
    ids=["the graded run wins", "then the saved search", "then the saved agent run"],
)
def test_the_recorded_decision_names_the_run_in_that_order(
    monkeypatch, report_run, values, expected
):
    connection = _RecordingConnection()
    monkeypatch.setattr(lab_exercise, "_connect", lambda: connection)
    report = {"exercise": "managed_agent", "work_sha256": "w", "verdict": "PASS"}
    if report_run:
        report["agent_run_id"] = report_run

    lab_exercise.record_decision(3, report, values)

    assert [row[2] for row in connection.inserted] == [expected]


def test_a_cannot_grade_with_its_own_next_is_laid_out_in_paragraphs(
    monkeypatch, capsys
):
    from service.agent_setup import AGENT_STARTER_MESSAGE
    from service.participant_commands import DEPLOY_AGENT

    def refuse(lab, work, run_id=None):
        raise ExerciseError(AGENT_STARTER_MESSAGE)

    monkeypatch.setattr(lab_exercise, "grade", refuse)

    assert lab_exercise.main(["grade", "--lab", "3"]) == 2

    out = capsys.readouterr().out
    lines = out.splitlines()
    assert max(map(len, lines)) <= 100
    next_line = next(i for i, line in enumerate(lines) if line.startswith("Next:"))
    assert lines[next_line - 1] == ""
    assert DEPLOY_AGENT in lines
    assert out.count("Next:") == 1


def test_a_passing_lab_2_grade_with_a_damaged_lab_3_record_says_so_in_words(
    monkeypatch, capsys
):
    from scripts.lab_entry import StartRecordError

    def damaged(lab):
        raise StartRecordError(3, "it is cut off or is not JSON")

    monkeypatch.setattr(lab_exercise.lab_state, "handed_off", damaged)

    lab_exercise._grade_next(2, True, None)

    out = capsys.readouterr().out
    assert "Lab 3 start record rule" in out and "reset --lab 3" in out
    assert out.count("Next:") == 1
