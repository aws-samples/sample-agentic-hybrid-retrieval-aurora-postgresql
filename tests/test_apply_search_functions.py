from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.apply_search_functions import apply
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
    statement = connection.execute.call_args.args[0]
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
