from types import SimpleNamespace
from unittest.mock import MagicMock

import psycopg
import pytest

from scripts import apply_search_functions
from scripts.apply_search_functions import (
    apply,
    describe_apply_failure,
    locate_error,
    rendered_sql,
)
from scripts.configure_retrieval_database import DatabaseConfigurationError
from scripts.lab_state import LABS, _replace_block
from service.participant_commands import APPLY_SQL
from service.search_sql import APPLIED_SQL_LABEL, applied_sql_digest, search_sql

SOURCE = search_sql()


@pytest.mark.parametrize("lab", [1, 2])
def test_applying_participant_sql_does_not_silently_solve_the_lab(monkeypatch, lab):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = ("reviews-2023-v2",)
    broken = SOURCE
    for start, end, _, replacement in LABS[lab][1]:
        broken = _replace_block(broken, start, end, replacement)
    apply(connection, broken)
    statement = next(
        call.args[0]
        for call in connection.execute.call_args_list
        if isinstance(call.args[0], str) and "CREATE OR REPLACE" in call.args[0]
    )
    assert "CREATE OR REPLACE FUNCTION mosaic_search.search_hybrid_rrf(" in statement
    assert "mosaic_live_search" not in statement
    for start, end, _, replacement in LABS[lab][1]:
        assert statement.split(start)[1].split(end)[0].strip() == replacement.strip()


def test_catalog_mismatch_prevents_any_function_change(monkeypatch):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = ("different-dataset",)
    with pytest.raises(ValueError, match="Lab catalog rule"):
        apply(connection, SOURCE)
    assert connection.execute.call_count == 1
    assert "SELECT dataset_id" in connection.execute.call_args.args[0]


def test_applying_records_which_participant_sql_aurora_runs(monkeypatch):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = ("reviews-2023-v2",)

    apply(connection, SOURCE, "b" * 64)

    comment = connection.execute.call_args_list[-1].args[0].as_string(None)
    assert comment.startswith("COMMENT ON FUNCTION mosaic_search.search_hybrid_rrf(")
    assert comment.endswith(f"'{APPLIED_SQL_LABEL}{'b' * 64}'")


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        (f"{APPLIED_SQL_LABEL}{'c' * 64}", "c" * 64),
        (None, None),
        ("a comment someone else wrote", None),
    ],
)
def test_the_applied_record_is_read_back_or_reported_missing(
    monkeypatch, note, expected
):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = {"note": note}

    assert applied_sql_digest(connection) == expected


class PositionedSyntaxError(psycopg.errors.SyntaxError):
    """A server error carrying the diagnostics Aurora sends with a real one."""

    @property
    def diag(self):
        return SimpleNamespace(
            sqlstate="42601",
            message_primary='syntax error at or near "FROM"',
            statement_position="1234",
            message_hint="Check the commas in the select list.",
        )


@pytest.fixture
def apply_command(monkeypatch):
    """`main()` with Aurora's connection and the reset guard replaced."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://redacted")
    monkeypatch.setattr(
        apply_search_functions, "assert_workshop_database", lambda _dsn: None
    )
    monkeypatch.setattr(psycopg, "connect", lambda *_, **__: MagicMock())
    monkeypatch.setattr(
        "scripts.configure_retrieval_database.configure", lambda _dsn: None
    )
    return monkeypatch


def test_a_sql_error_names_the_sqlstate_the_block_and_that_nothing_applied(
    apply_command,
):
    def fail(*_args, **_kwargs):
        raise PositionedSyntaxError("syntax error")

    apply_command.setattr(apply_search_functions, "apply", fail)

    with pytest.raises(SystemExit) as exit_info:
        apply_search_functions.main()

    message = str(exit_info.value)
    path, line, text = locate_error(rendered_sql(SOURCE), 1234)
    assert exit_info.value.code != 0
    assert "SQLSTATE 42601" in message
    assert 'syntax error at or near "FROM"' in message
    assert f"Where: {path} line {line}: {text}" in message
    assert "character" not in message
    assert "Check the commas" in message
    assert "Nothing was applied" in message
    assert APPLY_SQL in message


def test_a_dataset_mismatch_exits_cleanly_and_says_nothing_applied(apply_command):
    def mismatch(*_args, **_kwargs):
        raise ValueError(
            "Lab catalog rule: prepared dataset 'a' differs from 'b'; fix: x."
        )

    apply_command.setattr(apply_search_functions, "apply", mismatch)

    with pytest.raises(SystemExit) as exit_info:
        apply_search_functions.main()

    message = str(exit_info.value)
    assert "Lab catalog rule" in message
    assert "Nothing was applied" in message


def test_a_gate_configuration_failure_says_the_sql_was_applied(apply_command):
    apply_command.setattr(apply_search_functions, "apply", lambda *_a, **_k: None)

    def fail(_dsn):
        raise DatabaseConfigurationError(
            "D2 database owner mismatch; fix: use the owner"
        )

    apply_command.setattr("scripts.configure_retrieval_database.configure", fail)

    with pytest.raises(SystemExit) as exit_info:
        apply_search_functions.main()

    message = str(exit_info.value)
    assert "D2 database owner mismatch" in message
    assert "was applied" in message
    assert "Nothing was applied" not in message


def test_a_failure_without_server_diagnostics_still_reports_the_error():
    message = describe_apply_failure(
        psycopg.OperationalError("connection refused"), rolled_back=True
    )

    assert "SQLSTATE none" in message
    assert "connection refused" in message
    assert "character" not in message


def _server_error(sqlstate: str | None, message: str = "boom") -> psycopg.Error:
    error = psycopg.Error(message)
    error.sqlstate = sqlstate  # type: ignore[misc]
    return error


@pytest.mark.parametrize("sqlstate", [None, "08006", "53300", "57P01", "42501"])
def test_environment_faults_go_to_the_facilitator_not_the_lab_blocks(sqlstate):
    message = describe_apply_failure(_server_error(sqlstate), rolled_back=True)

    assert "facilitator" in message
    assert "LAB1_EDIT" not in message
    assert "LAB2_EDIT" not in message
    assert "Nothing was applied" in message


class UndefinedFunctionCall(psycopg.errors.UndefinedFunction):
    """Aurora's 42883 diagnostics for a call whose argument types match nothing."""

    def __init__(self, primary: str):
        super().__init__(primary)
        self._primary = primary

    @property
    def diag(self):
        return SimpleNamespace(
            sqlstate="42883",
            message_primary=self._primary,
            statement_position="5120",
            message_hint=(
                "No function matches the given name and argument types. You might "
                "need to add explicit type casts."
            ),
        )


def test_a_score_passed_as_the_position_names_the_argument_to_change():
    message = describe_apply_failure(
        UndefinedFunctionCall(
            "function mosaic_search.reciprocal_rank_contribution(real, integer) "
            "does not exist"
        ),
        rolled_back=True,
    )

    assert "takes a channel's position (bigint), got real" in message
    assert "fuzzy_rank" in message
    assert "fuzzy_score" in message
    assert "LAB1_EDIT" in message


def test_an_unrelated_missing_function_gets_no_position_advice():
    message = describe_apply_failure(
        UndefinedFunctionCall(
            "function mosaic_search.search_trigrams(text, jsonb) does not exist"
        ),
        rolled_back=True,
    )

    assert "takes a channel's position" not in message


@pytest.mark.parametrize("sqlstate", ["42601", "42703", "22012"])
def test_a_sql_fault_still_points_at_the_lab_blocks(sqlstate):
    message = describe_apply_failure(_server_error(sqlstate), rolled_back=True)

    assert "LAB1_EDIT" in message
    assert "facilitator" not in message


def test_an_unreachable_database_before_the_apply_exits_cleanly(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://redacted")

    def refuse(_dsn):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(apply_search_functions, "assert_workshop_database", refuse)
    monkeypatch.setattr(
        apply_search_functions, "apply", lambda *_a, **_k: pytest.fail("applied")
    )

    with pytest.raises(SystemExit) as exit_info:
        apply_search_functions.main()

    assert "facilitator" in str(exit_info.value)


@pytest.mark.parametrize("lab", [1, 2])
def test_applying_with_a_lab_file_deleted_names_the_way_back_not_a_traceback(
    monkeypatch, tmp_path, lab
):
    for other in (1, 2):
        if other != lab:
            target = tmp_path / LABS[other].exercise
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("-- present\n", encoding="utf-8")
    monkeypatch.setattr(apply_search_functions, "ROOT", tmp_path)
    monkeypatch.setattr(
        apply_search_functions,
        "assert_workshop_database",
        lambda _dsn: pytest.fail("reached Aurora with a lab file missing"),
    )

    with pytest.raises(SystemExit) as refused:
        apply_search_functions.main()

    assert str(refused.value).startswith(
        f"Lab {lab}: FILE MISSING ({LABS[lab].exercise})"
    )
    assert f"lab_state.py reset --lab {lab}" in str(refused.value)


@pytest.mark.parametrize("lab", [1, 2])
def test_applying_an_unedited_exercise_says_the_exercise_is_still_there(
    apply_command, capsys, tmp_path, lab
):
    from shutil import copy2

    from service.lab_files import LAB_FILES

    for path in (LAB_FILES[1], LAB_FILES[2]):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        copy2(apply_search_functions.ROOT / path, tmp_path / path)
    exercise = tmp_path / LAB_FILES[lab]
    source = exercise.read_text()
    for start, end, _, broken in LABS[lab][1]:
        source = _replace_block(source, start, end, broken)
    exercise.write_text(source)
    real = apply_search_functions.fault_untouched
    apply_command.setattr(
        apply_search_functions,
        "fault_untouched",
        lambda lab, repo: real(lab, repo=tmp_path),
    )
    apply_command.setattr(apply_search_functions, "apply", lambda *_a, **_k: None)

    apply_search_functions.main()

    out = capsys.readouterr().out
    assert (
        f"Note: {LAB_FILES[lab]} is unchanged since Lab {lab} started, so the "
        "exercise is still there. Edit the highlighted lines, then apply again."
    ) in out


def test_applying_an_edited_or_repaired_exercise_adds_no_note(apply_command, capsys):
    apply_command.setattr(apply_search_functions, "apply", lambda *_a, **_k: None)

    apply_search_functions.main()

    out = capsys.readouterr().out
    assert "Applied participant SQL" in out
    assert "Note:" not in out
