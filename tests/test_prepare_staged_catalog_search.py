"""Only a complete source enters search, loaded into the table install.sql declares."""

import re

import pytest

from scripts.catalog.prepare_staged_catalog_search import (
    PROJECTION_COLUMNS,
    PROJECTION_SQL,
    ROOT,
    index_statements,
    require_complete,
)
from service.catalog_runtime import LIVE_INDEXES


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


def test_the_load_fills_every_declared_column_in_order():
    declared = (ROOT / "db/sql/06_retrieval_projection.sql").read_text()
    table = declared.split(
        "CREATE TABLE IF NOT EXISTS mosaic_search.product_listing (", 1
    )[1]
    columns = re.findall(r"(?m)^    (\w+)\s", table.split("\n);", 1)[0])
    assert columns == [name.strip() for name in PROJECTION_COLUMNS.split(",")]
    assert PROJECTION_SQL.startswith("INSERT INTO mosaic_search.product_listing (")


def test_the_restore_builds_every_search_index_on_the_listings_table():
    statements = index_statements()
    names = [name for name, _ in statements]
    assert names == [
        LIVE_INDEXES[key] for key in ("fts", "trigram", "kind", "public_id", "vector")
    ]
    assert all("ON mosaic_search.product_listing" in sql for _, sql in statements)


@pytest.mark.parametrize(("capacity", "expected"), [(0, 0), (1, 0), (2, 1), (8, 7)])
def test_index_build_workers_respect_aurora_capacity(capacity, expected):
    from unittest.mock import MagicMock

    from scripts.catalog.prepare_staged_catalog_search import (
        configure_index_build_workers,
    )

    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = (str(capacity),)
    assert configure_index_build_workers(connection) == expected
    statement = connection.execute.call_args.args[0].as_string()
    assert statement == f"SET max_parallel_maintenance_workers = {expected}"


def test_the_planner_gets_statistics_after_the_public_id_index_exists():
    """An expression index has no statistics until the table is analysed after it.

    Without them the planner expects 0.5% of the catalog per product ID and
    scans every listing to fetch each search's shortlist.
    """
    from unittest.mock import MagicMock

    from scripts.catalog import prepare_staged_catalog_search as staged

    answers = {
        "mosaic_catalog_stage.dataset": (553911, True, True, "catalog-hash"),
        "FROM mosaic_catalog_stage.product": (553911,),
        "max_parallel_workers": ("4",),
        "SELECT EXISTS (SELECT 1 FROM mosaic_search.product_listing)": (True,),
    }
    statements: list[str] = []

    def execute(statement, params=None, **_kwargs):
        text = " ".join(str(statement).split())
        statements.append(text)
        if "count(*) FILTER" in text:
            raise RuntimeError("stopped after ANALYZE")
        result = MagicMock()
        if text.startswith("SELECT to_regclass"):
            result.fetchone.return_value = (
                params[0] == "mosaic_search.product_listing",
            )
        else:
            result.fetchone.return_value = next(
                (row for key, row in answers.items() if key in text), None
            )
        return result

    connection = MagicMock()
    connection.execute.side_effect = execute
    with pytest.raises(RuntimeError, match="stopped after ANALYZE"):
        staged.prepare(connection, "reviews-2023-v2")

    created = next(
        number
        for number, text in enumerate(statements)
        if "IF NOT EXISTS product_search_public_id_idx" in text
    )
    analysed = statements.index("ANALYZE mosaic_search.product_listing")
    assert analysed > created
