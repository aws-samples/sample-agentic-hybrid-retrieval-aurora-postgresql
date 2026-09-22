from pathlib import Path
from shutil import copy2

import pytest

from scripts.lab_state import (
    LABS,
    REPO,
    lab_is_solved,
    set_isolated_lab_state,
    set_lab_state,
)


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


@pytest.mark.parametrize("lab", sorted(LABS))
def test_reset_and_solution_are_idempotent(lab_repo: Path, lab: int) -> None:
    set_isolated_lab_state(lab, repo=lab_repo)
    first_reset = _lab_bytes(lab_repo)
    set_isolated_lab_state(lab, repo=lab_repo)

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
            "catalog": "mosaic_search.product_document",
        },
        {"name": "mosaic_catalog", "aurora": "18.3.0", "catalog": None},
        {
            "name": "mosaic_catalog",
            "aurora": None,
            "catalog": "mosaic_search.product_document",
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
        "catalog": "mosaic_search.product_document",
    }
    monkeypatch.setattr("psycopg.connect", lambda *a, **kw: connection)
    monkeypatch.setenv("MOSAIC_WORKSHOP_DATABASE", "named_workshop")
    assert_reset_database("test-only")
    with pytest.raises(SystemExit, match="DATABASE_URL is missing"):
        assert_reset_database(None)


def test_reset_checks_identity_before_editing_files(monkeypatch):
    from scripts import lab_state

    monkeypatch.setattr("sys.argv", ["lab_state.py", "reset", "--lab", "1"])

    def refuse(_):
        raise SystemExit("wrong database")

    monkeypatch.setattr(lab_state, "assert_reset_database", refuse)
    monkeypatch.setattr(
        lab_state,
        "set_isolated_lab_state",
        lambda *_: pytest.fail("edited before identity check"),
    )
    with pytest.raises(SystemExit, match="wrong database"):
        lab_state.main()


@pytest.mark.parametrize("lab", [1, 2])
def test_applied_state_reads_the_catalog_served_by_the_api(monkeypatch, lab):
    from unittest.mock import MagicMock

    from scripts.lab_state import validate_database
    from scripts.retrieval_profile import load_profile

    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-500k-v1")
    k = load_profile().rrf_k
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = {
        "definition": "SELECT * FROM typo JOIN mosaic_live_search.search_trigram()",
        "first_contribution": 1 / (k + 1),
        "second_contribution": 1 / (k + 2),
    }
    assert validate_database(lab, connection).state == "applied"
    statement = connection.execute.call_args.args[0]
    assert "mosaic_live_search." in statement
    assert "mosaic_search." not in statement
