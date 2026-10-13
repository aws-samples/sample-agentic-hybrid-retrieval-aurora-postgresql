"""The served catalog's indexes carry names an attendee can read in psql.

They were `real_search_*` until 13 October 2026, when `real_` marked the real
catalog beside a synthetic one. A cluster restored before then is renamed in
place, so the build step's `CREATE INDEX IF NOT EXISTS` never builds a second
copy of an index that already exists under its old name.
"""

from unittest.mock import MagicMock

from scripts.catalog.prepare_staged_catalog_search import rename_legacy_search_indexes
from service.catalog_runtime import LEGACY_INDEX_NAMES, LIVE_INDEXES, catalog_indexes

OLD_NAMES = {
    "real_search_fts_idx",
    "real_search_trigram_idx",
    "real_search_vector_idx",
    "real_search_vector_halfvec_idx",
    "real_search_vector_binary_idx",
    "real_search_kind_idx",
    "real_search_public_id_idx",
}


def test_every_old_name_maps_to_its_product_search_name():
    assert set(LEGACY_INDEX_NAMES) == OLD_NAMES
    assert set(LEGACY_INDEX_NAMES.values()) == set(LIVE_INDEXES.values())
    assert LEGACY_INDEX_NAMES["real_search_vector_idx"] == "product_search_vector_idx"
    assert all(name.startswith("product_search_") for name in LIVE_INDEXES.values())


def test_the_live_catalog_resolves_the_new_vector_index_names(monkeypatch):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    indexes = catalog_indexes()
    assert (indexes.fp32, indexes.halfvec, indexes.binary) == (
        "product_search_vector_idx",
        "product_search_vector_halfvec_idx",
        "product_search_vector_binary_idx",
    )


def test_legacy_indexes_are_renamed_and_absent_ones_skipped():
    present = {"real_search_fts_idx", "real_search_vector_idx"}
    statements = []

    def execute(query, params=None):
        statements.append((query, params))
        result = MagicMock()
        name = params[0].split(".", 1)[1] if params else None
        result.fetchone.return_value = {"present": name in present}
        return result

    connection = MagicMock()
    connection.execute.side_effect = execute

    renamed = rename_legacy_search_indexes(connection)

    assert set(renamed) == present
    alters = [q.as_string(None) for q, _ in statements if not isinstance(q, str)]
    assert alters == [
        (
            'ALTER INDEX mosaic_catalog_search."real_search_fts_idx" '
            'RENAME TO "product_search_fts_idx"'
        ),
        (
            'ALTER INDEX mosaic_catalog_search."real_search_vector_idx" '
            'RENAME TO "product_search_vector_idx"'
        ),
    ]


def test_a_cluster_built_with_the_new_names_is_left_alone():
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = {"present": False}
    assert rename_legacy_search_indexes(connection) == []
    assert all(
        isinstance(call.args[0], str) for call in connection.execute.call_args_list
    )
