from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.apply_search_functions import APPLIED_SQL_LABEL, applied_sql_digest, apply
from scripts.lab_state import LABS, _replace_block

SOURCE = Path("db/sql/09_search_functions.sql").read_text()


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
    assert (
        "CREATE OR REPLACE FUNCTION mosaic_live_search.search_hybrid_rrf(" in statement
    )
    assert "CREATE OR REPLACE FUNCTION mosaic_search." not in statement
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
    assert comment.startswith(
        "COMMENT ON FUNCTION mosaic_live_search.search_hybrid_rrf("
    )
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
