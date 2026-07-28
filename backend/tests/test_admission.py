"""Admission-contract tests (D21). Require a disposable TEST_DATABASE_URL."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[2]
SQL_FILES = [
    "sql/00_extensions.sql", "sql/01_schema.sql", "sql/02_indexes.sql",
    "sql/03_search_functions.sql", "sql/09_traverse_evidence.sql",
    "sql/10_admission.sql",
]

TEST_DSN = os.environ.get("TEST_DATABASE_URL")
RESET_OK = os.environ.get("ALLOW_TEST_DATABASE_RESET") == "1"


def _apply_schema(conn) -> None:
    for rel in SQL_FILES:
        conn.execute((REPO_ROOT / rel).read_text(encoding="utf-8"))


@unittest.skipUnless(TEST_DSN and RESET_OK, "needs TEST_DATABASE_URL + ALLOW_TEST_DATABASE_RESET=1")
class AdmissionSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = psycopg.connect(TEST_DSN, autocommit=True)
        _apply_schema(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_columns_and_receipts_table_exist(self) -> None:
        cols = self.conn.execute(
            """
            SELECT column_name, is_nullable FROM information_schema.columns
            WHERE table_schema = 'casework' AND table_name = 'evidence_items'
              AND column_name IN ('content_hash', 'available_at')
            ORDER BY column_name
            """
        ).fetchall()
        self.assertEqual(cols, [("available_at", "YES"), ("content_hash", "YES")])

        receipt_cols = self.conn.execute(
            """
            SELECT count(*) FROM information_schema.columns
            WHERE table_schema = 'casework' AND table_name = 'ingest_receipts'
            """
        ).fetchone()[0]
        self.assertGreaterEqual(receipt_cols, 12)

    def test_idempotency_index_exists(self) -> None:
        idx = self.conn.execute(
            """
            SELECT indexdef FROM pg_indexes
            WHERE schemaname = 'casework' AND tablename = 'evidence_items'
              AND indexdef ILIKE '%source_uri%content_hash%'
            """
        ).fetchall()
        self.assertTrue(idx, "partial unique index on (source_uri, content_hash) missing")
