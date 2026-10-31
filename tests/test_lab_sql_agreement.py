"""Every command that judges Lab 1 or Lab 2 reads the saved block the same way.

A tester saw `validate_lab.py --lab 1` pass and `advance --lab 1` refuse the
same state. The file check accepted names that apply did not rewrite, rejected
aliases the live search ran correctly, and the Aurora check re-ran a text
contract instead of asking whether Aurora runs the block saved in the file.
Aurora's definition here is the saved file as apply sends it.
"""

from __future__ import annotations

from pathlib import Path
from shutil import copy2
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scripts import lab_state
from scripts.apply_search_functions import rendered_sql
from scripts.lab_state import (
    LAB1_STARTER,
    LAB2_STARTER,
    LABS,
    REPO,
    LabProblem,
    _replace_block,
    applied_problem,
    database_fault_exit,
    lab2_contract_problem,
    source_problem,
    validate_database,
)
from service.participant_commands import APPLY_SQL, validate_applied
from service.search_sql import search_sql

REFERENCE = """    UNION ALL
    SELECT product_id, 'fuzzy', fuzzy_rank,
           fuzzy_score,
           mosaic_search.reciprocal_rank_contribution(fuzzy_rank, rrf_k)
    FROM fuzzy"""
ALIASED = """    UNION ALL
    SELECT t.product_id, 'fuzzy', t.fuzzy_rank, t.fuzzy_score,
           mosaic_search.reciprocal_rank_contribution(t.fuzzy_rank, rrf_k)
    FROM fuzzy t"""

WORKING_BRANCHES = {
    "reference": REFERENCE,
    "column aliases": REFERENCE.replace("'fuzzy',", "'fuzzy'::text AS channel,"),
    "table alias": ALIASED,
    "table alias with AS": ALIASED.replace("FROM fuzzy t", "FROM fuzzy AS t"),
    "columns named by step": ALIASED.replace("t.", "fuzzy.").replace(
        "FROM fuzzy t", "FROM fuzzy"
    ),
    "upper-case schema name": REFERENCE.replace("mosaic_search.", "MOSAIC_SEARCH."),
    "comment inside": REFERENCE.replace("FROM fuzzy", "FROM fuzzy  -- fuzzy matching"),
}
BROKEN_BRANCHES = {
    "starter": (LAB1_STARTER, "holds only comments"),
    "UNION": (
        REFERENCE.replace("UNION ALL", "UNION"),
        "must start with UNION ALL SELECT",
    ),
    "another search": (
        REFERENCE.replace("FROM fuzzy", "FROM semantic"),
        "reads FROM semantic; it must read the search results that no other",
    ),
    "score as position": (
        REFERENCE.replace("fuzzy_rank,\n", "fuzzy_score,\n", 1),
        "column 3 is fuzzy_score; it must be the fuzzy matching position",
    ),
    "four columns": (
        REFERENCE.replace("           fuzzy_score,\n", ""),
        "returns 4 columns; every branch returns five",
    ),
    "inline contribution": (
        REFERENCE.replace(
            "mosaic_search.reciprocal_rank_contribution(fuzzy_rank, rrf_k)",
            "1.0 / (rrf_k + fuzzy_rank)",
        ),
        "column 5 is 1.0 / (rrf_k + fuzzy_rank); it must be the RRF contribution",
    ),
    "a WHERE clause": (
        REFERENCE + "\n    WHERE fuzzy_rank <= 10",
        "must end with FROM and the results it reads",
    ),
}


@pytest.fixture
def lab_repo(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    for relative_path in {definition[0] for definition in LABS.values()}:
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy2(REPO / relative_path, destination)
    return tmp_path


def _save(repo: Path, branch: str) -> str:
    path = repo / LABS[1][0]
    start, end, _, _ = LABS[1][1][0]
    path.write_text(_replace_block(path.read_text(), start, end, branch))
    return path.read_text()


def _applied(saved_lab_1: str) -> MagicMock:
    """A connection whose Aurora runs the search function apply makes of this file."""
    source = search_sql().replace((REPO / LABS[1][0]).read_text(), saved_lab_1)
    head = "CREATE OR REPLACE FUNCTION mosaic_search.search_hybrid_rrf("
    definition = (
        head
        + rendered_sql(source)
        .split(head, 1)[1]
        .split("CREATE OR REPLACE FUNCTION", 1)[0]
    )
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = {"definition": definition}
    return connection


@pytest.mark.parametrize("branch", WORKING_BRANCHES.values(), ids=WORKING_BRANCHES)
def test_a_working_branch_passes_in_the_file_and_in_aurora(lab_repo, branch):
    connection = _applied(_save(lab_repo, branch))

    assert source_problem(1, repo=lab_repo) is None
    assert validate_database(1, connection, repo=lab_repo).state == "applied"


@pytest.mark.parametrize(
    ("branch", "reason"), BROKEN_BRANCHES.values(), ids=BROKEN_BRANCHES
)
def test_a_broken_branch_fails_for_the_same_reason_in_the_file_and_in_aurora(
    lab_repo, branch, reason
):
    connection = _applied(_save(lab_repo, branch))

    problem = source_problem(1, repo=lab_repo)
    assert problem is not None
    assert problem.finding.startswith(f"Lab 1 is not repaired: in {LABS[1][0]}, ")
    assert reason in problem.finding
    applied = validate_database(1, connection, repo=lab_repo)
    assert applied.state == "stale"
    assert reason in applied.detail


def test_a_block_changed_after_apply_is_reported_as_not_in_aurora(lab_repo):
    connection = _applied(_save(lab_repo, ALIASED))
    _save(lab_repo, REFERENCE)

    assert source_problem(1, repo=lab_repo) is None
    problem = applied_problem(1, validate_database(1, connection, repo=lab_repo))
    assert problem == LabProblem(
        "Lab 1's saved repair is not in Aurora. Aurora runs a different LAB1_EDIT "
        f"block from the one saved in {LABS[1][0]}. Saving changes only the file; "
        "applying it updates Aurora.",
        APPLY_SQL,
    )


def test_a_comment_added_after_apply_still_counts_as_applied(lab_repo):
    connection = _applied(_save(lab_repo, REFERENCE))
    _save(lab_repo, "    -- reconnect fuzzy matching\n" + REFERENCE)

    assert validate_database(1, connection, repo=lab_repo).state == "applied"


@pytest.mark.parametrize(
    "formula",
    [
        "SELECT 1.0 / (rrf_k + source_rank)",
        "SELECT (1.0 / (rrf_k + source_rank))::double precision",
        "SELECT 1.0 / (source_rank + rrf_k) AS contribution",
        "SELECT 1::float / (rrf_k + source_rank)",
        "SELECT 1 / (rrf_k + source_rank)::double precision",
    ],
)
def test_lab2_accepts_floating_reciprocal_rank_in_its_common_forms(formula):
    assert lab2_contract_problem(_lab2_file(formula)) is None


@pytest.mark.parametrize(
    ("formula", "reason"),
    [
        ("SELECT 1 / (rrf_k + source_rank)", "divides whole numbers"),
        (
            "SELECT (1 / (rrf_k + source_rank))::double precision",
            "divides whole numbers",
        ),
        (LAB2_STARTER, "never reads source_rank"),
        ("SELECT 1.0 / (rrf_k * source_rank)", "not in the form the check recognizes"),
    ],
)
def test_lab2_names_why_a_formula_is_not_repaired(formula, reason):
    problem = lab2_contract_problem(_lab2_file(formula))
    assert problem is not None and reason in problem


def _lab2_file(formula: str) -> str:
    start, end, _, _ = LABS[2][1][0]
    return _replace_block((REPO / LABS[2][0]).read_text(), start, end, formula)


def test_validate_lays_out_the_problem_the_fix_and_the_rerun(monkeypatch):
    problem = LabProblem(
        "Lab 1's saved repair is not in Aurora. Saved differs.", APPLY_SQL
    )
    monkeypatch.setattr(lab_state, "source_problem", lambda _lab: None)
    monkeypatch.setattr(lab_state, "_applied_problem_in", lambda *_: problem)

    with pytest.raises(SystemExit) as refused:
        lab_state._validate_command(1, "postgresql://aurora")

    assert str(refused.value) == (
        "Lab 1: FAIL\n"
        "- Lab 1's saved repair is not in Aurora. Saved differs.\n"
        f"  Next: {APPLY_SQL}\n"
        f"Then: {validate_applied(1)}"
    )


def test_validate_without_a_database_url_says_how_to_get_one(monkeypatch):
    monkeypatch.setattr(lab_state, "source_problem", lambda _lab: None)
    monkeypatch.setattr(
        lab_state,
        "_applied_problem_in",
        lambda *_: pytest.fail("read Aurora without a DATABASE_URL"),
    )

    with pytest.raises(SystemExit, match="DATABASE_URL is empty") as refused:
        lab_state._validate_command(2, "")

    assert str(refused.value).endswith(f"Then: {validate_applied(2)}")


def test_validate_passes_only_when_aurora_runs_the_saved_repair(monkeypatch, capsys):
    monkeypatch.setattr(lab_state, "source_problem", lambda _lab: None)
    monkeypatch.setattr(lab_state, "_applied_problem_in", lambda *_: None)

    assert lab_state._validate_command(1, "postgresql://aurora") == 0

    assert capsys.readouterr().out.startswith("Lab 1: PASS. ")


def _database_error(sqlstate: str) -> SimpleNamespace:
    return SimpleNamespace(
        sqlstate=sqlstate,
        diag=SimpleNamespace(
            sqlstate=sqlstate, message_primary="function does not exist"
        ),
    )


def test_a_rejected_statement_is_not_blamed_on_the_environment():
    message = str(database_fault_exit(_database_error("42883"), "advance Lab 1"))

    assert "environment problem" not in message
    assert "SQLSTATE 42883: function does not exist" in message
    assert "outside the marked LAB blocks" in message


def test_a_dropped_connection_is_still_the_facilitators():
    message = str(database_fault_exit(_database_error("08006"), "advance Lab 1"))

    assert "environment problem, not a mistake in your SQL" in message
