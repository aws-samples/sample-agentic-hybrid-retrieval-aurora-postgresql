"""Anchor selection is deterministic, complete, and refuses a catalog it does not fit."""

from __future__ import annotations

import pytest

from scripts import select_hnsw_anchors as selector
from service.hnsw_anchors import anchor_ids_sha256


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _Connection:
    """Answers the lab lookup with `lab_rows` and each category query with `samples[key]`."""

    def __init__(self, lab_rows, samples):
        self.lab_rows = lab_rows
        self.samples = samples
        self.queries: list[tuple[str, tuple]] = []

    def execute(self, sql, parameters=None):
        self.queries.append((sql, parameters))
        if "product_id = ANY(%s) AND embedding IS NOT NULL" in sql:
            return _Cursor(self.lab_rows)
        category, _lab_ids, _seed, size = parameters
        return _Cursor(self.samples.get(category, [])[:size])


def _row(product_id, category="monitor"):
    return {
        "product_id": product_id,
        "parent_asin": f"B{product_id:09d}",
        "category_key": category,
        "domain": "consumer_electronics",
        "brand_name": "Acme",
        "title": f"Product {product_id}",
    }


def test_lab_products_come_first_then_the_sample_in_category_order():
    connection = _Connection(
        lab_rows=[_row(2), _row(1)],
        samples={"monitor": [_row(10), _row(11)], "chair": [_row(20, "chair")]},
    )

    anchors = selector.select_anchors(
        connection, seed="s", sample={"monitor": 2, "chair": 1}, lab_ids=[1, 2]
    )

    assert [item["product_id"] for item in anchors] == [1, 2, 10, 11, 20]
    assert [item["source"] for item in anchors] == [
        "lab",
        "lab",
        "sample",
        "sample",
        "sample",
    ]
    ordering = [sql for sql, _ in connection.queries if "md5(" in sql]
    assert len(ordering) == 2
    assert "ORDER BY md5(%s || ':' || parent_asin), product_id" in ordering[0]


def test_a_lab_product_missing_from_the_catalog_is_refused():
    connection = _Connection(lab_rows=[_row(1)], samples={})

    with pytest.raises(SystemExit) as raised:
        selector.select_anchors(connection, seed="s", sample={}, lab_ids=[1, 2])

    assert "[2]" in str(raised.value)
    assert "fix:" in str(raised.value)


def test_a_category_with_too_few_products_is_refused():
    connection = _Connection(
        lab_rows=[], samples={"chair_mat": [_row(30, "chair_mat")]}
    )

    with pytest.raises(SystemExit, match="chair_mat"):
        selector.select_anchors(
            connection, seed="s", sample={"chair_mat": 5}, lab_ids=[]
        )


def test_the_payload_restates_the_hash_of_its_ids_and_its_inputs():
    anchors = [_row(3), _row(1), _row(2)]

    payload = selector.anchor_set_payload(
        anchors,
        dataset_id="reviews-2023-v2",
        catalog_sha256="c" * 64,
        seed="seed",
        sample={"monitor": 3},
        lab_ids=[],
        revision="abc",
    )

    assert payload["sha256"] == anchor_ids_sha256([1, 2, 3])
    assert payload["selection"]["seed"] == "seed"
    assert payload["selection"]["sample_per_category"] == {"monitor": 3}
    assert payload["selection"]["anchor_count"] == 3
    assert "md5(seed" in payload["selection"]["algorithm"]


@pytest.mark.parametrize("value", ["monitor=0", "monitor", "=3", "monitor=x"])
def test_malformed_sample_sizes_are_refused(value):
    with pytest.raises(SystemExit, match="fix:"):
        selector.parse_sample(value)


def test_the_default_sample_covers_the_lab_categories():
    sample = selector.parse_sample(None)

    assert {"headphones", "chair", "monitor"} <= set(sample)
    assert all(size >= 1 for size in sample.values())
