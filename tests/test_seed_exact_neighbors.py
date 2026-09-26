"""Ground truth is refused when it does not belong to the connected corpus.

Recall computed against another corpus is not recall. These are the falsifier
fixtures for that refusal.
"""

from __future__ import annotations

import pytest

from scripts.seed_exact_neighbors import StaleGroundTruth, assert_manifest_matches


def test_matching_manifest_is_accepted():
    assert_manifest_matches(stored="abc123", connected="abc123")


def test_a_mismatched_manifest_is_refused_with_both_values():
    with pytest.raises(StaleGroundTruth) as raised:
        assert_manifest_matches(stored="abc123", connected="def456")

    message = str(raised.value)
    assert "abc123" in message
    assert "def456" in message
    assert "fix:" in message


def test_an_empty_connected_manifest_is_refused():
    with pytest.raises(StaleGroundTruth):
        assert_manifest_matches(stored="abc123", connected="")


def test_an_unknown_connected_manifest_is_refused():
    """`unknown` is service.config's default when nothing resolved the manifest.

    Accepting it would pin ground truth to a sentinel, which then matches any other
    unresolved run regardless of what corpus produced it.
    """
    with pytest.raises(StaleGroundTruth):
        assert_manifest_matches(stored="unknown", connected="unknown")


# --- Ground truth is keyed by anchor set and predicate, not only by corpus -----


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Connection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.queries: list[tuple[str, tuple]] = []

    def execute(self, sql, parameters=None):
        self.queries.append((sql, parameters))
        return _Cursor(self.rows)


def test_ground_truth_is_joined_on_the_current_predicates_and_anchor_set():
    from scripts.seed_exact_neighbors import SEEDED_K, load_ground_truth
    from service.hnsw_presets import FILTER_PRESETS

    connection = _Connection(
        [
            {"anchor_product_id": 1, "filter_preset": "none", "neighbor_product_id": 1},
            {"anchor_product_id": 1, "filter_preset": "none", "neighbor_product_id": 7},
        ]
    )

    truth = load_ground_truth(
        connection, manifest_sha256="m" * 64, k=2, anchor_set_sha256="a" * 64
    )

    assert truth == {(1, "none"): [1, 7]}
    sql, parameters = connection.queries[0]
    assert "predicate_sha256 = neighbor.predicate_sha256" in sql
    assert "anchor_set_sha256 = %s" in sql
    assert parameters[0] == [preset.key for preset in FILTER_PRESETS]
    assert parameters[1] == [preset.predicate_sha256 for preset in FILTER_PRESETS]
    assert parameters[2:] == ("m" * 64, "a" * 64, SEEDED_K, 2)


def test_a_request_deeper_than_the_seeded_depth_is_refused():
    from scripts.seed_exact_neighbors import SEEDED_K, load_ground_truth

    with pytest.raises(StaleGroundTruth, match=str(SEEDED_K)):
        load_ground_truth(
            _Connection(), manifest_sha256="m", k=SEEDED_K + 1, anchor_set_sha256="a"
        )


def test_a_changed_predicate_makes_stored_rows_invisible():
    """The stale-truth gate: rows carrying another predicate hash never join."""
    from dataclasses import replace

    from scripts.seed_exact_neighbors import load_ground_truth
    from service.hnsw_presets import PRESETS_BY_KEY

    changed = replace(PRESETS_BY_KEY["rating"], predicate_sql="rating >= 4.9")
    connection = _Connection()
    load_ground_truth(
        connection,
        manifest_sha256="m",
        k=5,
        anchor_set_sha256="a",
        presets=(changed,),
    )

    _, parameters = connection.queries[0]
    assert parameters[1] == [changed.predicate_sha256]
    assert parameters[1] != [PRESETS_BY_KEY["rating"].predicate_sha256]


def test_the_exact_query_orders_ties_deterministically_and_resets_settings():
    from scripts.seed_exact_neighbors import exact_neighbors
    from service.hnsw_presets import PRESETS_BY_KEY

    connection = _Connection([{"product_id": 5, "cosine_distance": 0.0}])

    rows = exact_neighbors(
        connection, embedding=[0.1], preset=PRESETS_BY_KEY["category"], k=3
    )

    assert rows == [(1, 5, 0.0)]
    statements = [sql for sql, _ in connection.queries]
    assert statements[0].startswith("SET enable_indexscan")
    assert "ORDER BY embedding <=> %s, product_id" in statements[2]
    assert "category_key = 'monitor'" in statements[2]
    assert statements[-1].startswith("RESET enable_bitmapscan")


def test_seeding_computes_one_distance_pass_per_batch_and_ranks_every_preset():
    from types import SimpleNamespace

    from scripts.seed_exact_neighbors import ANCHOR_BATCH, seed
    from service.hnsw_presets import FILTER_PRESETS

    class _SeedConnection(_Connection):
        def execute(self, sql, parameters=None):
            self.queries.append((sql, parameters))
            if "SELECT product_id, title, embedding" in sql:
                return _Cursor(
                    [
                        {"product_id": i, "title": "t", "embedding": [0.1]}
                        for i in (1, 2)
                    ]
                )
            if "count(*) AS n FROM pg_temp.hnsw_anchor_distance" in sql:
                return _Cursor([{"n": 4}])
            if "row_number() OVER" in sql:
                return _Cursor(
                    [
                        {
                            "anchor_product_id": 1,
                            "product_id": 1,
                            "cosine_distance": 0.0,
                            "rank": 1,
                        },
                        {
                            "anchor_product_id": 2,
                            "product_id": 2,
                            "cosine_distance": 0.0,
                            "rank": 1,
                        },
                    ]
                )
            return _Cursor([])

        def commit(self):
            pass

    connection = _SeedConnection()
    anchors = SimpleNamespace(product_ids=(1, 2), sha256="a" * 64)

    written = seed(
        connection, anchors=anchors, k=50, manifest_sha256="m" * 64, revision="r"
    )

    statements = [sql for sql, _ in connection.queries]
    passes = [
        sql for sql in statements if "CREATE TEMP TABLE hnsw_anchor_distance" in sql
    ]
    assert len(passes) == 1, "two anchors fit one batch, so one catalog pass"
    assert ANCHOR_BATCH >= 2
    assert "CROSS JOIN (VALUES" in passes[0]
    assert "(d.embedding <=> a.embedding)" in passes[0]
    ranked = [sql for sql in statements if "row_number() OVER" in sql]
    assert len(ranked) == len(FILTER_PRESETS)
    assert "ORDER BY cosine_distance, product_id" in ranked[0]
    assert "WHERE rating >= 4.5" in ranked[1]
    inserts = [p for sql, p in connection.queries if sql.strip().startswith("INSERT")]
    assert written == 2 * len(FILTER_PRESETS)
    assert {p[8] for p in inserts} == {"a" * 64}
    assert {p[9] for p in inserts} == {
        preset.predicate_sha256 for preset in FILTER_PRESETS
    }
    assert statements[-1].startswith(
        "DROP TABLE IF EXISTS pg_temp.hnsw_anchor_distance"
    )


def test_the_batch_pass_keeps_the_filter_columns_the_presets_name():
    from scripts.seed_exact_neighbors import compute_distances

    class _PassConnection(_Connection):
        def execute(self, sql, parameters=None):
            self.queries.append((sql, parameters))
            return _Cursor([{"n": 3}])

    connection = _PassConnection()
    rows = compute_distances(connection, [{"product_id": 7, "embedding": [0.2]}])

    assert rows == 3
    create = next(sql for sql, _ in connection.queries if "CREATE TEMP TABLE" in sql)
    for column in ("d.domain", "d.category_key", "d.brand_name", "d.rating"):
        assert column in create


def test_seeding_refuses_an_anchor_the_catalog_lacks():
    from types import SimpleNamespace

    from scripts.seed_exact_neighbors import anchor_vectors

    with pytest.raises(StaleGroundTruth, match="select-hnsw-anchors"):
        anchor_vectors(_Connection(), SimpleNamespace(product_ids=(1, 2), sha256="a"))
