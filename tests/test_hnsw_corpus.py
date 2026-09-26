"""The corpus identity comes from the served catalog's receipt, never a sentinel."""

from __future__ import annotations

import pytest

from service.hnsw_corpus import StaleGroundTruth, corpus_manifest


class _Cursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, row):
        self.row = row
        self.statements: list[str] = []

    def execute(self, sql, parameters=None):
        self.statements.append(sql)
        return _Cursor(self.row)


def test_a_prepared_catalog_reports_its_receipt_hash(monkeypatch):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    connection = _Connection(
        {"dataset_id": "reviews-2023-v2", "catalog_sha256": "c" * 64}
    )

    assert corpus_manifest(connection) == "c" * 64
    assert "mosaic_live_search.receipt" in connection.statements[0]


def test_a_receipt_for_another_dataset_is_refused(monkeypatch):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    connection = _Connection(
        {"dataset_id": "reviews-2023-500k-v1", "catalog_sha256": "c" * 64}
    )

    with pytest.raises(StaleGroundTruth) as raised:
        corpus_manifest(connection)

    assert "reviews-2023-v2" in str(raised.value)
    assert "fix:" in str(raised.value)


def test_a_missing_receipt_is_refused(monkeypatch):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")

    with pytest.raises(StaleGroundTruth):
        corpus_manifest(_Connection(None))


def test_the_legacy_catalog_uses_the_checked_in_manifest(monkeypatch):
    monkeypatch.delenv("MOSAIC_CATALOG_DATASET", raising=False)

    class Settings:
        dataset_manifest_sha256 = "d" * 64

    monkeypatch.setattr("service.hnsw_corpus.get_settings", lambda: Settings())
    connection = _Connection(None)

    assert corpus_manifest(connection) == "d" * 64
    assert connection.statements == []
