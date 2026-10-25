from pathlib import Path
from shutil import copy2

import pytest

from scripts.lab_state import (
    LABS,
    REPO,
    lab_diff,
    lab_is_solved,
    set_lab_state,
)
from service.participant_commands import DIFF_ANSWER, solution

PARTICIPANT_CHANNEL = """    UNION ALL
    SELECT product_id, 'trigram'::text AS channel, trigram_rank AS source_rank,
           trigram_score AS raw_score,
           mosaic_search.reciprocal_rank_contribution(trigram_rank, rrf_k)
               AS contribution
    FROM typo"""


@pytest.fixture
def lab_repo(tmp_path: Path) -> Path:
    for relative_path in {definition[0] for definition in LABS.values()}:
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy2(REPO / relative_path, destination)
    return tmp_path


def _lab_bytes(repo: Path) -> dict[str, bytes]:
    return {
        relative_path: (repo / relative_path).read_bytes()
        for relative_path in {definition[0] for definition in LABS.values()}
    }


def participant_lab1(repo: Path) -> str:
    from scripts.lab_state import _replace_block

    path = repo / LABS[1][0]
    source = path.read_text()
    for (start, end, _, _), replacement in zip(
        LABS[1][1], (PARTICIPANT_CHANNEL,), strict=True
    ):
        source = _replace_block(source, start, end, replacement)
    path.write_text(source)
    return source


def test_lab1_accepts_the_participant_repair_that_passed_live_retrieval(lab_repo):
    participant_lab1(lab_repo)
    assert lab_is_solved(1, repo=lab_repo)


def test_applied_lab1_accepts_the_participant_repair(lab_repo, monkeypatch):
    from unittest.mock import MagicMock

    from scripts.lab_state import validate_database

    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    connection = MagicMock()
    source = participant_lab1(lab_repo)
    definition = source.split(
        "CREATE OR REPLACE FUNCTION mosaic_search.search_hybrid_rrf(", 1
    )[1].split("CREATE OR REPLACE FUNCTION", 1)[0]
    connection.execute.return_value.fetchone.return_value = {
        "definition": definition.replace("mosaic_search.", "mosaic_search.")
    }
    assert validate_database(1, connection, repo=lab_repo).state == "applied"


def test_applied_lab1_does_not_accept_disconnected_name_mentions():
    from unittest.mock import MagicMock

    from scripts.lab_state import validate_database

    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = {
        "definition": "-- search_trigram is missing\nSELECT product_id FROM typo"
    }
    assert validate_database(1, connection).state == "stale"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("q, f, trigram_limit", "q, '{}'::jsonb, trigram_limit"),
        ("trigram_limit, trigram_threshold\n", "trigram_limit, 0.0\n"),
        ("UNION ALL", "UNION"),
        ("'trigram'::text", "'vector'::text"),
        ("trigram_rank AS source_rank", "1 AS source_rank"),
        ("trigram_score AS raw_score", "trigram_rank AS raw_score"),
        ("(trigram_rank, rrf_k)", "(1, rrf_k)"),
        ("FROM typo", "FROM semantic"),
    ],
)
def test_lab1_contract_rejects_changed_data_flow_and_restores(lab_repo, old, new):
    participant_lab1(lab_repo)
    path = lab_repo / LABS[1][0]
    original = path.read_bytes()
    assert old in original.decode()
    path.write_text(original.decode().replace(old, new))
    assert not lab_is_solved(1, repo=lab_repo)
    path.write_bytes(original)
    assert path.read_bytes() == original
    assert lab_is_solved(1, repo=lab_repo)


def test_lab1_contract_ignores_local_names_comments_and_projection_order(lab_repo):
    source = participant_lab1(lab_repo)
    source = source.replace("typo AS (", "recovered /* still named */ AS (")
    source = source.replace("FROM typo", "FROM recovered")
    source = source.replace("AS raw_score", "AS ignored_union_alias -- output name\n")
    (lab_repo / LABS[1][0]).write_text(source)
    assert lab_is_solved(1, repo=lab_repo)


@pytest.mark.parametrize("lab", [1, 2, 3])
def test_source_gate_ignores_layout_but_preserves_the_repair(lab_repo, lab):
    from scripts.lab_state import _replace_block

    set_lab_state(lab, solved=True, repo=lab_repo)
    path = lab_repo / LABS[lab][0]
    original = path.read_bytes()
    source = original.decode()
    for start, end, fixed, _ in LABS[lab][1]:
        formatted = (
            fixed.replace("tools=tools,", "tools = tools,")
            if lab == 3
            else " ".join(fixed.split())
        )
        source = _replace_block(source, start, end, formatted)
    assert source.encode() != original
    path.write_text(source)
    assert lab_is_solved(lab, repo=lab_repo)
    set_lab_state(lab, solved=False, repo=lab_repo)
    assert not lab_is_solved(lab, repo=lab_repo)
    path.write_bytes(original)
    assert path.read_bytes() == original
    assert lab_is_solved(lab, repo=lab_repo)


def test_source_gate_preserves_string_contents(lab_repo):
    set_lab_state(1, solved=True, repo=lab_repo)
    path = lab_repo / LABS[1][0]
    path.write_text(path.read_text().replace("'trigram'", "'tri gram'"))
    assert not lab_is_solved(1, repo=lab_repo)


@pytest.mark.parametrize("later_lab", [2, 3])
def test_a_later_reset_keeps_the_participants_valid_lab1_repair(
    lab_repo: Path, later_lab: int
) -> None:
    participant_lab1(lab_repo)

    set_lab_state(later_lab, solved=False, repo=lab_repo)

    source = (lab_repo / LABS[1][0]).read_text()
    assert PARTICIPANT_CHANNEL in source
    assert lab_is_solved(1, repo=lab_repo)
    assert not lab_is_solved(later_lab, repo=lab_repo)


@pytest.mark.parametrize(
    "formula",
    [
        "SELECT 1.0 / (rrf_k + source_rank)",
        "select 1::float8 / (source_rank + rrf_k);",
        "SELECT 1 / (rrf_k::double precision + /* keep ranks */ source_rank)",
    ],
)
def test_lab3_reset_preserves_participant_lab2_formula(lab_repo, formula):
    from scripts.lab_state import _replace_block

    path = lab_repo / LABS[2][0]
    start, end, _, _ = LABS[2][1][0]
    path.write_text(_replace_block(path.read_text(), start, end, formula))
    original = path.read_bytes()
    assert lab_is_solved(2, repo=lab_repo)

    changed = set_lab_state(3, solved=False, repo=lab_repo)

    assert changed == lab_repo / LABS[3][0]
    assert not lab_is_solved(3, repo=lab_repo)
    assert path.read_bytes() == original
    assert lab_is_solved(2, repo=lab_repo)


@pytest.mark.parametrize(
    "formula",
    [
        "SELECT 1.0 / (rrf_k + 1)",
        "SELECT 1.0 / (source_rank + source_rank)",
        "SELECT 1 / (rrf_k + source_rank)",
        "SELECT 1.0 / (rrf_k + source_rank) + 1",
        "SELECT 1.0 / (rrf_k + source_rank); SELECT 1",
    ],
)
def test_lab2_contract_rejects_wrong_formula_and_restores(lab_repo, formula):
    from scripts.lab_state import _replace_block

    path = lab_repo / LABS[2][0]
    original = path.read_bytes()
    assert lab_is_solved(2, repo=lab_repo)
    start, end, _, _ = LABS[2][1][0]
    path.write_text(_replace_block(path.read_text(), start, end, formula))
    assert not lab_is_solved(2, repo=lab_repo)
    path.write_bytes(original)
    assert path.read_bytes() == original
    assert lab_is_solved(2, repo=lab_repo)


@pytest.mark.parametrize("lab", sorted(LABS))
def test_reset_and_solution_are_idempotent(lab_repo: Path, lab: int) -> None:
    set_lab_state(lab, solved=False, repo=lab_repo)
    first_reset = _lab_bytes(lab_repo)
    set_lab_state(lab, solved=False, repo=lab_repo)

    assert _lab_bytes(lab_repo) == first_reset
    assert not lab_is_solved(lab, repo=lab_repo)
    assert all(
        lab_is_solved(candidate, repo=lab_repo)
        for candidate in LABS
        if candidate != lab
    )

    set_lab_state(lab, solved=True, repo=lab_repo)
    first_solution = _lab_bytes(lab_repo)
    set_lab_state(lab, solved=True, repo=lab_repo)

    assert _lab_bytes(lab_repo) == first_solution
    assert all(lab_is_solved(candidate, repo=lab_repo) for candidate in LABS)


@pytest.mark.parametrize(
    "identity",
    [
        {
            "name": "unrelated",
            "aurora": "18.3.0",
            "catalog": "mosaic_search.product_listing_view",
        },
        {"name": "mosaic_catalog", "aurora": "18.3.0", "catalog": None},
        {
            "name": "mosaic_catalog",
            "aurora": None,
            "catalog": "mosaic_search.product_listing_view",
        },
    ],
)
def test_reset_guard_rejects_wrong_environment(monkeypatch, identity):
    from unittest.mock import MagicMock

    from scripts.lab_state import assert_reset_database

    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchone.return_value = identity
    monkeypatch.setattr("psycopg.connect", lambda *a, **kw: connection)
    monkeypatch.delenv("MOSAIC_WORKSHOP_DATABASE", raising=False)
    with pytest.raises(SystemExit, match="Lab reset rule"):
        assert_reset_database("test-only")


def test_reset_guard_accepts_named_aurora_and_rejects_missing_dsn(monkeypatch):
    from unittest.mock import MagicMock

    from scripts.lab_state import assert_reset_database

    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchone.return_value = {
        "name": "named_workshop",
        "aurora": "18.3.0",
        "catalog": "mosaic_search.product_listing_view",
    }
    monkeypatch.setattr("psycopg.connect", lambda *a, **kw: connection)
    monkeypatch.setenv("MOSAIC_WORKSHOP_DATABASE", "named_workshop")
    assert_reset_database("test-only")
    with pytest.raises(SystemExit, match="DATABASE_URL is missing"):
        assert_reset_database(None)


def test_reset_checks_identity_before_editing_files(monkeypatch):
    from scripts import lab_state

    monkeypatch.setattr(
        "sys.argv", ["lab_state.py", "reset", "--lab", "1", "--source-only"]
    )

    def refuse(_):
        raise SystemExit("wrong database")

    monkeypatch.setattr(lab_state, "assert_reset_database", refuse)
    monkeypatch.setattr(
        lab_state,
        "set_lab_state",
        lambda *_, **__: pytest.fail("edited before identity check"),
    )
    with pytest.raises(SystemExit, match="wrong database"):
        lab_state.main()


@pytest.mark.parametrize("lab", [1, 2])
def test_applied_state_reads_the_catalog_served_by_the_api(monkeypatch, lab):
    from unittest.mock import MagicMock

    from scripts.checks.retrieval_profile import load_profile
    from scripts.lab_state import validate_database

    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    k = load_profile().rrf_k
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = {
        "definition": (REPO / LABS[1][0]).read_text(),
        "first_contribution": 1 / (k + 1),
        "second_contribution": 1 / (k + 2),
    }
    assert validate_database(lab, connection).state == "applied"
    statement = connection.execute.call_args.args[0]
    assert "mosaic_search." in statement
    assert "mosaic_live_search" not in statement


PARTICIPANT_LAB3 = """    prompt = instructions + "\\nKeep the answer concise."
    result = Agent(model=model, tools=tools, system_prompt=prompt, hooks=hooks)
    return result"""


def test_lab3_accepts_extra_instructions_and_local_variable_names(lab_repo):
    from scripts.lab_state import _replace_block

    path = lab_repo / LABS[3][0]
    start, end, _, _ = LABS[3][1][0]
    path.write_text(_replace_block(path.read_text(), start, end, PARTICIPANT_LAB3))
    assert lab_is_solved(3, repo=lab_repo)


@pytest.mark.parametrize(
    "body",
    [
        "    pass",
        "    raise NotImplementedError()",
        "    return {}",
        "    return Agent(model=model, tools=[], system_prompt=instructions, hooks=hooks)",
        "    return Agent(model=None, tools=tools, system_prompt=instructions, hooks=hooks)",
        "    return Agent(model=model, tools=tools, system_prompt='Invent products', hooks=hooks)",
        "    return Agent(model=model, tools=tools, system_prompt=instructions, hooks=[])",
        "    raise SystemExit(0)",
    ],
)
def test_lab3_rejects_missing_agent_parts_and_accepts_byte_identical_restore(
    lab_repo, body
):
    from scripts.lab_state import _replace_block

    path = lab_repo / LABS[3][0]
    original = path.read_bytes()
    start, end, _, _ = LABS[3][1][0]
    path.write_text(_replace_block(original.decode(), start, end, body))
    assert not lab_is_solved(3, repo=lab_repo)
    path.write_bytes(original)
    assert path.read_bytes() == original
    assert lab_is_solved(3, repo=lab_repo)


def test_lab3_probe_does_not_import_module_startup_code(lab_repo):
    path = lab_repo / LABS[3][0]
    path.write_text(path.read_text() + '\nraise RuntimeError("unrelated startup")\n')
    assert lab_is_solved(3, repo=lab_repo)


def test_lab3_probe_bounds_a_nonterminating_edit(lab_repo):
    from scripts.lab_state import _replace_block

    path = lab_repo / LABS[3][0]
    start, end, _, _ = LABS[3][1][0]
    path.write_text(
        _replace_block(path.read_text(), start, end, "    while True:\n        pass")
    )
    assert not lab_is_solved(3, repo=lab_repo)


def test_status_reports_the_participants_lab_not_the_shipped_seam(lab_repo) -> None:
    """Labs 2 and 3 ship repaired; before a start that is nobody's work."""
    import json

    from scripts.lab_state import status_line
    from service.participant_commands import start as start_command

    assert status_line(1, repo=lab_repo) == "Lab 1: SOLVED"
    assert status_line(2, repo=lab_repo) == "Lab 2: NOT STARTED"
    record = lab_repo / ".local" / "lab-2" / "start.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"version": 1, "lab": 2, "steps": {}}))
    assert status_line(2, repo=lab_repo) == (
        f"Lab 2: START INTERRUPTED. Next: run {start_command(2)} again; it "
        "finishes the missing step and keeps your edits."
    )
    set_lab_state(2, solved=False, repo=lab_repo)
    record.write_text(
        json.dumps({"version": 1, "lab": 2, "steps": {}, "completed_at": "now"})
    )
    assert status_line(2, repo=lab_repo) == "Lab 2: BROKEN"


@pytest.mark.parametrize("action", ["start", "reset"])
def test_a_failed_lab_check_during_entry_is_a_clean_exit_not_a_traceback(
    monkeypatch, action
):
    from scripts import lab_entry, lab_state
    from scripts.validate_lab import LabValidationError

    def fail(*_args, **_kwargs):
        raise LabValidationError(
            "/api/search is unavailable; fix: tell your facilitator"
        )

    monkeypatch.setattr("sys.argv", ["lab_state.py", action, "--lab", "1"])
    monkeypatch.setattr(lab_entry, "start", fail)
    monkeypatch.setattr(lab_entry, "restart", fail)

    with pytest.raises(SystemExit) as exit_info:
        lab_state.main()

    assert (
        str(exit_info.value) == "/api/search is unavailable; fix: tell your facilitator"
    )


def test_lab3_source_check_names_the_next_commands_instead_of_passing(
    monkeypatch, capsys
):
    from scripts import lab_state
    from service.participant_commands import DEPLOY_AGENT, complete_lab_3

    monkeypatch.setattr(
        "sys.argv", ["lab_state.py", "validate", "--lab", "3", "--database-url", ""]
    )
    monkeypatch.setattr(lab_state, "lab_is_solved", lambda *_a, **_k: True)

    assert lab_state.main() == 0

    output = capsys.readouterr().out
    assert "PASS" not in output
    assert "assembled" in output
    assert DEPLOY_AGENT in output
    assert complete_lab_3() in output


def test_an_unreachable_aurora_exits_with_facilitator_advice_not_a_traceback(
    monkeypatch,
):
    import psycopg

    from scripts.lab_state import assert_reset_database

    def refuse(*_args, **_kwargs):
        raise psycopg.OperationalError("connection to server failed")

    monkeypatch.setattr("psycopg.connect", refuse)
    with pytest.raises(SystemExit) as exit_info:
        assert_reset_database("postgresql://redacted")

    message = str(exit_info.value)
    assert "facilitator" in message
    assert "OperationalError" in message
    assert "redacted" not in message
    assert "LAB1_EDIT" not in message


def test_start_reports_a_database_failure_after_the_guard_the_same_way(monkeypatch):
    import psycopg

    from scripts import lab_entry, lab_state

    def refuse(*_args, **_kwargs):
        raise psycopg.OperationalError("server closed the connection")

    monkeypatch.setattr("sys.argv", ["lab_state.py", "start", "--lab", "2"])
    monkeypatch.setattr(lab_entry, "start", refuse)
    with pytest.raises(SystemExit) as exit_info:
        lab_state.main()

    assert "facilitator" in str(exit_info.value)


@pytest.mark.parametrize(
    "lab,expected",
    [(1, "apply_search_functions"), (2, "apply_search_functions"), (3, "deploy")],
)
def test_solution_says_what_it_overwrote_and_the_next_commands(
    monkeypatch, capsys, tmp_path, lab, expected
):
    from scripts import lab_state
    from service.participant_commands import DEPLOY_AGENT, complete_lab_3, prove

    monkeypatch.setattr("sys.argv", ["lab_state.py", "solution", "--lab", str(lab)])
    monkeypatch.delenv(lab_state.RUN_BY, raising=False)
    monkeypatch.setattr(
        lab_state, "set_lab_state", lambda *_a, **_k: lab_state.REPO / "x.sql"
    )

    assert lab_state.main() == 0

    output = capsys.readouterr().out
    assert f"LAB{lab}_" in output and "overwrote" in output
    assert "git diff" not in output
    assert expected in output
    if lab == 3:
        assert DEPLOY_AGENT in output and complete_lab_3() in output
    else:
        assert prove(lab) in output


@pytest.mark.parametrize("lab", sorted(LABS))
def test_solution_run_by_finish_leaves_the_next_commands_to_it(
    monkeypatch, capsys, lab
):
    """`finish` applies and proves the answer itself, so its `solution` step names no
    command to run next; the step lines that follow show them running."""
    from scripts import lab_state

    monkeypatch.setattr("sys.argv", ["lab_state.py", "solution", "--lab", str(lab)])
    monkeypatch.setenv(lab_state.RUN_BY, f"Finish Lab {lab}")
    monkeypatch.setattr(
        lab_state, "set_lab_state", lambda *_a, **_k: lab_state.REPO / "x.sql"
    )

    assert lab_state.main() == 0

    output = capsys.readouterr().out
    assert f"LAB{lab}_" in output and "overwrote" in output
    assert "Next:" not in output


@pytest.mark.parametrize("action", ["start", "reset", "solution", "validate"])
def test_a_missing_lab_names_the_valid_values(monkeypatch, action):
    from scripts import lab_state

    monkeypatch.setattr("sys.argv", ["lab_state.py", action])
    with pytest.raises(SystemExit) as raised:
        lab_state.main()
    message = str(raised.value)
    assert action in message and "1, 2, 3" in message
    assert f"lab_state.py {action} --lab" in message


@pytest.mark.parametrize("lab", sorted(LABS))
def test_diff_reports_a_match_for_the_shipped_repair(lab_repo: Path, lab: int) -> None:
    report, differs = lab_diff(lab, repo=lab_repo)

    assert not differs
    assert report == (
        f"Lab {lab}: {LABS[lab][0]} matches the reference answer, inside and "
        "outside the markers."
    )


@pytest.mark.parametrize("lab", sorted(LABS))
def test_diff_hides_the_answer_unless_asked(lab_repo: Path, lab: int) -> None:
    set_lab_state(lab, solved=False, repo=lab_repo)
    _relative_path, blocks = LABS[lab]

    report, differs = lab_diff(lab, repo=lab_repo)

    assert differs
    lines = report.splitlines()
    assert (
        lines[1]
        == "Only those lines are shown, without the answer; nothing was changed."
    )
    assert "  Your file:" in lines and "  Reference answer:" not in lines
    answer_lines = {
        line.strip()
        for block in blocks
        for line in block.fixed.splitlines()
        if line.strip() and not line.lstrip().startswith(("--", "#"))
    }
    assert not answer_lines & {line.strip() for line in lines}, (
        "the hint printed the answer"
    )
    assert f"      {DIFF_ANSWER}" in lines
    assert lines[-1].endswith(solution(lab))


@pytest.mark.parametrize("lab", sorted(LABS))
def test_diff_shows_the_reference_against_the_participants_block(
    lab_repo: Path, lab: int
) -> None:
    set_lab_state(lab, solved=False, repo=lab_repo)

    report, differs = lab_diff(lab, repo=lab_repo, answer=True)

    assert differs
    lines = report.splitlines()
    assert lines[:2] == [
        f"Lab {lab}: where your {LABS[lab][0]} differs from the reference answer.",
        "Only those lines are shown; nothing was changed.",
    ]
    # The tool's own text stays short; indented lines are code or a command, kept whole.
    prose = [line for line in lines if not line.startswith(" ")]
    assert max(len(line) for line in prose) <= 110, "a line would wrap in the terminal"
    assert not any(line.startswith("Outside the markers") for line in lines)
    assert "  Reference answer:" in lines and "  Your file:" in lines
    assert any("TODO(Lab" in line for line in lines)
    assert not any(line.startswith(("---", "+++", "@@")) for line in lines)
    assert DIFF_ANSWER not in report
    assert lines[-1].endswith(solution(lab))
    assert "\033[" not in report


def test_diff_names_one_changed_line_in_plain_words(lab_repo: Path) -> None:
    set_lab_state(1, solved=True, repo=lab_repo)
    path = lab_repo / LABS[1][0]
    source = path.read_text()
    assert source.count("    FROM typo\n") == 1
    path.write_text(source.replace("    FROM typo\n", "    FROM semantic\n"))
    line = source.split("    FROM typo\n", 1)[0].count("\n") + 1

    hint, differs = lab_diff(1, repo=lab_repo)
    report, _ = lab_diff(1, repo=lab_repo, answer=True)

    assert differs
    assert f"At line {line} of your file:\n  Your file:\n      FROM semantic\n" in hint
    assert "FROM typo" not in hint
    assert (
        f"At line {line} of your file:\n"
        "  Reference answer:\n      FROM typo\n"
        "  Your file:\n      FROM semantic\n"
    ) in report


def test_diff_shows_a_line_deleted_outside_the_markers(lab_repo: Path) -> None:
    set_lab_state(1, solved=True, repo=lab_repo)
    path = lab_repo / LABS[1][0]
    source = path.read_text()
    stray = "-- LAB1_EDIT_END\n    UNION ALL\n"
    assert source.count(stray) == 1
    path.write_text(source.replace(stray, "-- LAB1_EDIT_END\n"))
    end_line = source.split("-- LAB1_EDIT_END", 1)[0].count("\n") + 1

    report, differs = lab_diff(1, repo=lab_repo)

    assert differs
    assert (
        f"Outside the markers, missing from your file, after line {end_line}:\n"
        "  Original file:\n      UNION ALL\n"
        "  Your file: (nothing here)\n"
    ) in report
    assert "reset --lab 1" in report
    assert "To use the reference answer instead" not in report


def test_diff_points_at_the_participants_own_lines(lab_repo: Path) -> None:
    set_lab_state(2, solved=False, repo=lab_repo)
    report, _ = lab_diff(2, repo=lab_repo)
    lines = report.splitlines()
    header = next(
        index for index, line in enumerate(lines) if line.startswith("At line")
    )
    first = int(lines[header].split()[2].split("-")[0])
    yours_label = lines.index("  Your file:", header)
    shown = lines[yours_label + 1].strip()
    yours_file = (lab_repo / LABS[2][0]).read_text().splitlines()

    assert yours_file[first - 1].strip() == shown


def test_diff_colours_only_when_asked(lab_repo: Path) -> None:
    set_lab_state(1, solved=False, repo=lab_repo)

    hint, _ = lab_diff(1, repo=lab_repo, color=True)
    coloured, _ = lab_diff(1, repo=lab_repo, color=True, answer=True)

    assert "\033[33m" in hint and "\033[32m" not in hint
    assert "\033[32m" in coloured and "\033[33m" in coloured


def test_diff_names_the_participants_file_when_a_marker_is_gone(lab_repo: Path) -> None:
    path = lab_repo / LABS[2][0]
    end = LABS[2][1][0].end
    path.write_text(path.read_text().replace(end, ""))

    with pytest.raises(
        ValueError,
        match=r"Lab diff rule: in labs/lab2_rank/rrf_contribution.sql, "
        r"the line '-- LAB2_EDIT_END' is missing.*reset --lab 2",
    ):
        lab_diff(2, repo=lab_repo)


def _without_line(source: str, marker: str) -> str:
    return "".join(
        line for line in source.splitlines(keepends=True) if line.strip() != marker
    )


@pytest.mark.parametrize("lab", [1, 2])
def test_a_deleted_marker_is_named_with_its_place_and_a_way_out(lab: int) -> None:
    from scripts.lab_state import source_problem

    start = LABS[lab].blocks[0].start
    with_marker = (REPO / LABS[lab].exercise).read_text(encoding="utf-8")
    above = with_marker.split(start, 1)[0].rstrip().splitlines()[-1].strip()

    def problem_without(source: str) -> str:
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / LABS[lab].exercise
            path.parent.mkdir(parents=True)
            path.write_text(source, encoding="utf-8")
            problem = source_problem(lab, repo=Path(folder))
        assert problem is not None
        return problem.finding

    finding = problem_without(_without_line(with_marker, start))

    assert f"the line '{start}' is missing" in finding
    assert f"directly under '{above}'" in finding
    assert f"reset --lab {lab}" in finding
    assert "git diff" not in finding


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (
            lambda s, start, end: s.replace(start, f"{start}\n{start}"),
            "appears 2 times",
        ),
        (
            lambda s, start, end: (
                s.replace(start, "@@").replace(end, start).replace("@@", end)
            ),
            "comes before",
        ),
    ],
)
def test_a_repeated_or_swapped_marker_says_which(change, expected: str) -> None:
    from scripts.lab_state import lab1_contract_problem

    start, end = LABS[1].blocks[0].start, LABS[1].blocks[0].end
    source = (REPO / LABS[1].exercise).read_text(encoding="utf-8")

    problem = lab1_contract_problem(change(source, start, end))

    assert problem is not None and expected in problem


@pytest.mark.parametrize("lab", [1, 2, 3])
def test_reset_recovers_a_file_whose_marker_was_deleted(
    lab_repo: Path, lab: int
) -> None:
    path = lab_repo / LABS[lab].exercise
    start = LABS[lab].blocks[0].start
    path.write_text(
        _without_line(path.read_text(encoding="utf-8"), start), encoding="utf-8"
    )

    set_lab_state(lab, solved=False, repo=lab_repo)

    restored = path.read_text(encoding="utf-8")
    assert restored.count(start) == 1
    assert LABS[lab].blocks[0].broken.strip() in restored
    assert not lab_is_solved(lab, repo=lab_repo)


def test_diff_tool_shows_only_the_lab_files_that_differ(lab_repo: Path) -> None:
    from scripts import diff

    set_lab_state(1, solved=False, repo=lab_repo)

    text = diff.report(repo=lab_repo)
    answer = diff.report(repo=lab_repo, answer=True)

    assert text.startswith(f"Lab 1: where your {LABS[1][0]} differs")
    assert "Lab 2:" not in text and "Lab 3:" not in text
    assert "Reference answer:" not in text and "Reference answer:" in answer


def test_diff_tool_takes_a_lab_file_by_path_or_name(lab_repo: Path) -> None:
    from scripts import diff

    by_name = diff.report("hybrid_search.sql", repo=lab_repo)
    by_path = diff.report(LABS[1][0], repo=lab_repo)

    assert by_name == by_path
    assert by_name.startswith(f"Lab 1: {LABS[1][0]} matches the reference answer")


def test_diff_tool_says_when_every_file_matches(lab_repo: Path) -> None:
    from scripts import diff

    assert diff.report(repo=lab_repo) == (
        "Every lab file matches the reference answer, inside and outside the markers."
    )


def test_diff_tool_names_the_lab_files_for_an_unknown_file(lab_repo: Path) -> None:
    from scripts import diff

    with pytest.raises(
        ValueError, match=r"Diff rule: README.md is not a lab file.*hybrid_search"
    ):
        diff.report("README.md", repo=lab_repo)
