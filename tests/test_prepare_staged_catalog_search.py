"""The replacement corpus must be complete and isolated from served search."""

import re

import pytest

from scripts.prepare_staged_catalog_search import (
    ROOT,
    require_complete,
    search_functions,
)


@pytest.mark.parametrize(
    ("dataset", "actual"),
    [
        (None, 0),
        ((0, True, True, "hash"), 0),
        ((500000, True, True, "hash"), 499999),
        ((500000, False, True, "hash"), 500000),
        ((500000, True, False, "hash"), 500000),
    ],
)
def test_empty_partial_or_unverified_source_cannot_enter_search(dataset, actual):
    with pytest.raises(ValueError, match="Search input rule"):
        require_complete(dataset, actual)


def test_complete_verified_source_can_enter_search():
    require_complete((500000, True, True, "hash"), 500000)


def test_function_installation_cannot_replace_served_functions():
    source = (ROOT / "db/sql/09_search_functions.sql").read_text()
    scoped = search_functions(source)
    targets = re.findall(
        r"(?:FUNCTION|TABLE|PROCEDURE)\s+(?:IF EXISTS\s+)?([\w.]+)\(", scoped
    )
    assert targets
    assert all(name.startswith("mosaic_catalog_search.") for name in targets)
    assert "mosaic_search." not in scoped
    assert "mosaic.product_evidence" not in scoped
    assert "mosaic_catalog_search.search_hybrid_rrf(" in scoped
    assert "mosaic_catalog_search.search_vector(" in scoped


def test_changed_sql_boundary_requires_review_before_installation():
    with pytest.raises(ValueError, match="unique evidence boundary"):
        search_functions("CREATE OR REPLACE FUNCTION mosaic_search.something_new();")


@pytest.mark.parametrize(("capacity", "expected"), [(0, 0), (1, 0), (2, 1), (8, 7)])
def test_index_build_workers_respect_aurora_capacity(capacity, expected):
    from unittest.mock import MagicMock

    from scripts.prepare_staged_catalog_search import configure_index_build_workers

    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = (str(capacity),)
    assert configure_index_build_workers(connection) == expected
    statement = connection.execute.call_args.args[0].as_string()
    assert statement == f"SET max_parallel_maintenance_workers = {expected}"
