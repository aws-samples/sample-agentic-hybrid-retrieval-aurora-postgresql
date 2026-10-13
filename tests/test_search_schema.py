"""Search lives in one schema whose names an attendee can read in psql.

Until 14 October 2026 the listings table sat in `mosaic_catalog_search` and the
view and functions Aurora ran in `mosaic_live_search`, while the lab files named
`mosaic_search`. The indexes were `real_search_*` until 13 October. A cluster
prepared before then is moved and renamed in place, never rebuilt.
"""

from unittest.mock import MagicMock

import pytest

from scripts.catalog.migrate_search_schema import (
    LEGACY_INDEX_NAMES,
    migrate,
    rename_legacy_indexes,
    require_migrated,
)
from service.catalog_runtime import LIVE_INDEXES, catalog_indexes, listing_view

OLD_NAMES = {
    "real_search_fts_idx",
    "real_search_trigram_idx",
    "real_search_vector_idx",
    "real_search_vector_halfvec_idx",
    "real_search_vector_binary_idx",
    "real_search_kind_idx",
    "real_search_public_id_idx",
}


def connection_with(relations: set[str]) -> tuple[MagicMock, list[str]]:
    """A connection whose catalog holds exactly `relations`, recording DDL."""
    statements: list[str] = []

    def execute(query, params=None):
        result = MagicMock()
        if params and query.startswith("SELECT to_regclass"):
            result.fetchone.return_value = (params[0] in relations,)
        else:
            statements.append(query)
        return result

    connection = MagicMock()
    connection.execute.side_effect = execute
    return connection, statements


def test_every_old_index_name_maps_to_its_product_search_name():
    assert set(LEGACY_INDEX_NAMES) == OLD_NAMES
    assert set(LEGACY_INDEX_NAMES.values()) == set(LIVE_INDEXES.values())
    assert all(name.startswith("product_search_") for name in LIVE_INDEXES.values())


def test_searches_read_the_view_and_indexes_live_on_the_table():
    indexes = catalog_indexes()
    assert indexes.qualified_table == "mosaic_search.product_listing"
    assert (indexes.fp32, indexes.halfvec, indexes.binary) == (
        "product_search_vector_idx",
        "product_search_vector_halfvec_idx",
        "product_search_vector_binary_idx",
    )
    assert listing_view() == "mosaic_search.product_listing_view"


def test_legacy_indexes_are_renamed_and_absent_ones_skipped():
    connection, statements = connection_with(
        {"mosaic_search.real_search_fts_idx", "mosaic_search.real_search_vector_idx"}
    )
    renamed = rename_legacy_indexes(connection)
    assert renamed == [
        "index real_search_fts_idx -> product_search_fts_idx",
        "index real_search_vector_idx -> product_search_vector_idx",
    ]
    assert statements == [
        "ALTER INDEX mosaic_search.real_search_fts_idx RENAME TO product_search_fts_idx",
        (
            "ALTER INDEX mosaic_search.real_search_vector_idx "
            "RENAME TO product_search_vector_idx"
        ),
    ]


def test_a_migrated_cluster_is_left_alone():
    connection, statements = connection_with({"mosaic_search.product_listing"})
    assert migrate(connection) == []
    assert statements == ["SET LOCAL lock_timeout = '10s'"]


def test_preparing_a_cluster_on_the_old_schemas_is_refused():
    connection, _ = connection_with({"mosaic_catalog_search.product_document"})
    with pytest.raises(ValueError, match="migrate_search_schema.py"):
        require_migrated(connection)
    require_migrated(connection_with({"mosaic_search.product_listing"})[0])
