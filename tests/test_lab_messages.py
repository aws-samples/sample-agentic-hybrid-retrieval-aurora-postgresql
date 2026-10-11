"""What a participant reads when a Lab 1 or Lab 2 command stops, and what to run next.

The live-check details are shared by the terminal and the Playground's Prove
panel, which splits each on "; fix: ". They name what was found in Shop's terms
and end in a command or the facilitator, never in an internal function name.
The terminal's start and before/after steps report an already working search
instead of stopping, and an apply error names the participant's own file line.
"""

from __future__ import annotations

import json
from pathlib import Path
from shutil import copy2
from types import SimpleNamespace

import pytest

from scripts import lab_entry, lab_terminal, validate_lab
from scripts.apply_search_functions import (
    _apply_fix,
    describe_apply_failure,
    locate_error,
    rendered_sql,
)
from scripts.investigate_lab import paired_searches
from scripts.lab_state import (
    LABS,
    REPO,
    LabDatabaseState,
    _replace_block,
    set_lab_state,
)
from scripts.validate_lab import LabValidationError
from service import lab_checks
from service.lab_files import LAB1_SQL, LAB2_SQL
from service.participant_commands import (
    APPLY_SQL,
    complete_lab_3,
    prove,
    repeat_request,
    validate,
    validate_applied,
)
from service.participant_commands import start as start_command
from service.search_sql import SEARCH_SQL_FILES, search_sql

INTERNAL_NAMES = (
    "CTE",
    "search_hybrid_rrf",
    "mosaic_search.",
    "signals.",
    "diagnostics.",
    "rrf_contribution=",
    "trigram_in_pool",
    "restore the",
)

RETRIEVE = lab_checks.load_mission("retrieve")
RANK = lab_checks.load_mission("rank")


def _row(product_id: int, **signals) -> dict:
    return {"product_id": product_id, "domain": "elsewhere", "signals": signals}


def _failing_checks() -> list[lab_checks.LabCheck]:
    retrieve_target = RETRIEVE["target_product_ids"][0]
    rank_target = RANK["target_product_ids"][0]
    empty = {"results": [], "diagnostics": {}}
    wrong = {
        "results": [
            _row(
                rank_target,
                fts={"rank": 1, "rrf_contribution": 0.5},
                trigram={},
                semantic={},
                rrf_score=0.5,
                pre_rerank_rank=3,
                final_rank=9,
            )
        ],
        "diagnostics": {"retrieval_profile": {"rrf_k": 60}, "rerank_status": "applied"},
    }
    checks = [
        *lab_checks.lab_1_checks(RETRIEVE, empty),
        *lab_checks.lab_1_checks(
            RETRIEVE, {"results": [_row(retrieve_target, fts={"rank": 1})]}
        ),
        *lab_checks.lab_2_checks(RANK, empty, empty),
        *lab_checks.lab_2_checks(RANK, wrong, wrong),
    ]
    for lab_id in (1, 2):
        for control in lab_checks.supporting_checks_for_lab(lab_id):
            checks += lab_checks.retrieval_control_checks(control, empty, [])
    return [check for check in checks if not check.passed]


def test_every_lab_1_and_2_failure_names_its_finding_and_a_next_step():
    failures = _failing_checks()
    assert {check.name for check in failures} >= {
        "expected retrieval anchor present",
        "trigram provenance present",
        "hard filters hold",
        "trigram candidate pool non-empty",
        "RRF arithmetic correct",
        "pre-rerank order repeatable",
        "reranking bounded and applied",
        "rank provenance present",
        "required product reaches the declared final shortlist",
    }
    for check in failures:
        found, separator, fix = check.detail.partition("; fix: ")
        assert separator, f"{check.name}: no fix in {check.detail!r}"
        assert found.startswith("found "), check.detail
        assert "uv run python scripts/" in fix or "facilitator" in fix, check.detail
        named = [name for name in INTERNAL_NAMES if name in check.detail]
        assert not named, f"{check.name} uses {named}: {check.detail!r}"


def test_a_missing_close_spelling_result_points_at_the_lab_1_file_and_its_check():
    anchor = lab_checks.lab_1_checks(RETRIEVE, {"results": []})[0]

    assert "Fuzzy matching candidates are not reaching the combined results" in (
        anchor.detail
    )
    assert validate_applied(1) in anchor.detail
    assert str(LAB1_SQL) in anchor.detail


def test_the_terminal_skips_the_step_it_has_already_taken():
    generic = f"found no result; fix: {lab_checks.repair_next_step(2)}"
    environment = f"found no reranking; fix: {lab_checks.FACILITATOR}"

    in_place = validate_lab._with_block_in_place(generic, 2)

    assert validate_applied(2) not in in_place
    assert f"your saved block in {LAB2_SQL} is repaired and Aurora runs it" in in_place
    assert f"run {validate(2)} again" in in_place
    assert validate_lab._with_block_in_place(environment, 2) == environment


def _start_record(output: Path, evidence: dict) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "start.json").write_text(
        json.dumps(
            {
                "completed_at": "2026-10-10T12:00:00+00:00",
                "steps": {"evidence": evidence},
            }
        )
    )


def test_an_after_run_without_a_start_names_the_start_command(tmp_path):
    with pytest.raises(LabValidationError) as refused:
        lab_terminal._without_before(1, tmp_path)

    assert str(refused.value) == (
        "Lab 1 has not started, so there is no saved failing request to compare with.\n"
        f"Next: {start_command(1)}\nThen: {repeat_request(1)}"
    )


def test_an_after_run_of_a_lab_started_repaired_shows_the_search_alone(tmp_path):
    _start_record(tmp_path, {"state": "done", "note": "repair already applied"})

    note = lab_terminal._without_before(1, tmp_path)

    assert note.startswith("Lab 1 started with its repair already working")
    assert "shows the search as it is now" in note


def test_an_after_run_with_a_lost_before_file_says_which_file(tmp_path):
    _start_record(tmp_path, {"state": "done", "search_event_id": "run-1"})

    note = lab_terminal._without_before(2, tmp_path)

    assert str(tmp_path / "before-state.json") in note


def test_lab_3_has_no_before_and_after_pair(tmp_path):
    with pytest.raises(LabValidationError, match=complete_lab_3().replace("<", ".")):
        lab_terminal._without_before(3, tmp_path)


def test_the_terminal_exits_with_the_lab_and_no_traceback(monkeypatch, tmp_path):
    def refuse(*_args):
        raise LabValidationError("the search returned no candidates")

    monkeypatch.setattr(lab_terminal, "prepare", refuse)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_: None)
    monkeypatch.setattr(
        "sys.argv", ["lab_terminal.py", "run", "--lab", "2", "--phase", "after"]
    )

    with pytest.raises(SystemExit) as stopped:
        lab_terminal.main()

    assert str(stopped.value) == "Lab 2: the search returned no candidates"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for relative_path in {definition[0] for definition in LABS.values()}:
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy2(REPO / relative_path, destination)
    return tmp_path


def test_a_start_whose_search_already_works_finishes_and_says_why(repo, monkeypatch):
    said: list[str] = []
    detail = "Aurora runs a different LAB1_CHANNEL block from the one saved."

    def already_working(*_args):
        raise lab_terminal.AlreadyRepaired(
            "the search already finds product 1 among its 50 candidates, so there "
            "is no failing request to save"
        )

    monkeypatch.setattr(lab_terminal, "prepare", already_working)

    saved = lab_entry._failing_search_evidence(
        1, LabDatabaseState("stale", detail), "http://api", repo, said.append
    )

    assert saved == {
        "state": "done",
        "note": "search already finds the target; no failing run saved",
    }
    assert said == [
        (
            "Lab 1: the search already finds product 1 among its 50 candidates, so "
            f"there is no failing request to save. {detail}\n"
            f"Next: {validate_applied(1)} names what to change or run."
        )
    ]


def _pair() -> tuple[dict, dict, dict]:
    run = {
        "search_event_id": "before",
        "query_text": RANK["query"],
        "filters": RANK["filters"],
        "dataset_manifest_sha256": "catalog",
        "retrieval_profile": {"rrf_k": 60},
        "embedding_model_id": "embedding",
        "rerank_model_id": "rerank",
        "retrieval_strategy": "hybrid",
    }
    before = {"run": run, "candidates": [{"product_id": 1}]}
    after = {"run": {**run, "search_event_id": "after"}, "candidates": []}
    return before, after, RANK


def test_a_repair_that_has_not_reached_aurora_says_what_to_check_and_repeat():
    with pytest.raises(LabValidationError) as refused:
        paired_searches(*_pair())

    message = str(refused.value)
    assert message.startswith(
        f"product {RANK['target_product_ids'][0]} is still missing from the candidates"
    )
    assert "so the repair has not reached the search Aurora runs" in message
    assert f"Next: {validate_applied(2)}" in message
    assert message.endswith(f"Then: {repeat_request(2)}")


def test_a_loosened_filter_is_named_with_the_products_outside_it():
    before, after, mission = _pair()
    target = mission["target_product_ids"][0]
    after["candidates"] = [
        {"product_id": target, "eligible": True, "fused_rank": 1, "result_rank": 1},
        {"product_id": 7, "eligible": False},
    ]

    with pytest.raises(LabValidationError, match=r"product\(s\) \[7\]") as refused:
        paired_searches(before, after, mission)

    assert "must not loosen any filter" in str(refused.value)


def _score_as_position(repo: Path) -> str:
    path = repo / LABS[1][0]
    start, end, fixed, _ = LABS[1][1][0]
    broken = fixed.replace(
        "reciprocal_rank_contribution(trigram_rank",
        ("reciprocal_rank_contribution(trigram_score"),
    )
    path.write_text(_replace_block(path.read_text(), start, end, broken))
    return search_sql(repo)


@pytest.mark.parametrize("dataset", ["reviews-2023-v2", ""])
def test_an_apply_error_names_the_participants_own_line(repo, monkeypatch, dataset):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", dataset)
    for relative in (
        "db/sql/08_search_channels.sql",
        "db/sql/09_weighted_fusion.sql",
        "db/sql/10_evidence_search.sql",
    ):
        (repo / relative).parent.mkdir(parents=True, exist_ok=True)
        copy2(REPO / relative, repo / relative)
    statement = rendered_sql(_score_as_position(repo))
    position = statement.index("reciprocal_rank_contribution(trigram_score") + 1

    path, line, text = locate_error(statement, position, repo)

    assert path == LAB1_SQL
    assert "reciprocal_rank_contribution(trigram_score, rrf_k)" in text
    assert (repo / LAB1_SQL).read_text().splitlines()[line - 1].strip() == text


def test_a_repeated_line_is_found_in_the_file_it_came_from():
    statement = rendered_sql(search_sql())
    lines = statement.splitlines()
    third = [i for i, line in enumerate(lines) if line.strip() == "UNION ALL"][2]
    position = sum(len(line) + 1 for line in lines[:third]) + 1
    in_files = [
        (path, number)
        for path in SEARCH_SQL_FILES
        for number, text in enumerate((REPO / path).read_text().splitlines(), start=1)
        if text.strip() == "UNION ALL"
    ]

    assert locate_error(statement, position)[:2] == in_files[2]


def test_a_position_past_the_statement_is_not_guessed():
    assert locate_error("SELECT 1", 500) is None


def test_the_fix_names_only_the_file_the_error_is_in():
    in_lab_2 = _apply_fix((LAB2_SQL, 22, "+ source_rank"))
    shipped = _apply_fix((Path("db/sql/08_search_channels.sql"), 36, "OR x"))

    assert str(LAB2_SQL) in in_lab_2 and str(LAB1_SQL) not in in_lab_2
    assert "outside the marked blocks" in shipped and "git diff" in shipped


def test_a_rejected_apply_with_no_statement_keeps_the_general_fix():
    error = SimpleNamespace(
        sqlstate="42601",
        diag=SimpleNamespace(
            sqlstate="42601",
            message_primary="syntax error",
            statement_position="12",
            message_hint=None,
        ),
    )

    message = describe_apply_failure(error, rolled_back=True)

    assert "Where:" not in message and "character" not in message
    assert f"{LAB1_SQL} and {LAB2_SQL}" in message and APPLY_SQL in message


def test_the_playground_names_what_is_wrong_in_an_unrepaired_block(repo):
    from service.lab_proof import _state_detail

    set_lab_state(1, solved=False, repo=repo)

    detail = _state_detail(
        1, solved=False, database=LabDatabaseState("stale", ""), repo=repo
    )

    assert detail.startswith(
        f"Lab 1 is not repaired: in {LAB1_SQL}, the marked block holds only comments"
    )
    assert detail.endswith(f"then prove it with {prove(1)}.")
