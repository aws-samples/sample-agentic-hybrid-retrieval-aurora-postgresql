"""Admission-contract tests (D21). Require a disposable TEST_DATABASE_URL."""
from __future__ import annotations

import json
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


FIXTURE = REPO_ROOT / "admission" / "fixture_payload.json"


def _seed_incident(conn) -> None:
    """Minimal INC-2047 + CHG-1842 rows so the lock FK and link resolve.

    Kept intentionally small: the admission tests need the two referenced
    evidence rows to exist, not the full corpus.
    """
    conn.execute(
        """
        INSERT INTO casework.database_clusters
          (cluster_id, engine, engine_version, aws_region, environment,
           service_name, writer_endpoint_alias, instance_class)
        VALUES
          ('orion-prod', 'aurora-postgresql', '18.3', 'us-east-1', 'production',
           'orion', 'orion-prod.cluster.local', 'db.r8g.xlarge')
        ON CONFLICT (cluster_id) DO NOTHING
        """
    )
    for kind, key, title in [("incident", "INC-2047", "checkout lock incident"),
                             ("change", "CHG-1842", "index build change")]:
        conn.execute(
            """
            INSERT INTO casework.evidence_items
              (evidence_kind, external_key, title, source_system, source_uri, source_revision, source_updated_at)
            VALUES (%s, %s, %s, 'seed', %s, 'r1', now())
            ON CONFLICT (evidence_kind, external_key) DO NOTHING
            """,
            (kind, key, title, f"seed://{key}"),
        )
    inc = conn.execute("SELECT evidence_id FROM casework.evidence_items WHERE external_key='INC-2047'").fetchone()[0]
    conn.execute(
        """
        INSERT INTO casework.incidents (evidence_id, incident_id, cluster_id, severity, status, started_at, summary, customer_impact)
        VALUES (%s, 'INC-2047', 'orion-prod', 'SEV-2', 'resolved', now(), 's', 'i')
        ON CONFLICT (evidence_id) DO NOTHING
        """,
        (inc,),
    )


@unittest.skipUnless(TEST_DSN and RESET_OK, "needs TEST_DATABASE_URL + ALLOW_TEST_DATABASE_RESET=1")
class AdmitEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = psycopg.connect(TEST_DSN, autocommit=True)
        _apply_schema(self.conn)
        self._clean_admitted()  # isolation: methods share one physical DB
        _seed_incident(self.conn)
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def _clean_admitted(self) -> None:
        """Remove LOCK-LIVE-* rows so each test starts from a clean slate.

        Order honors the FKs: receipts, the queue projection, inferred edges,
        and lock detail all reference evidence_items (ON DELETE RESTRICT), so
        they must go before the header row.
        """
        self.conn.execute(
            """
            DELETE FROM retrieval.search_index_queue
            WHERE evidence_id IN (
              SELECT evidence_id FROM casework.evidence_items WHERE external_key LIKE 'LOCK-LIVE-%'
            )
            """
        )
        self.conn.execute(
            """
            DELETE FROM retrieval.inferred_edges
            WHERE from_evidence_id IN (
              SELECT evidence_id FROM casework.evidence_items WHERE external_key LIKE 'LOCK-LIVE-%'
            )
            """
        )
        for tbl, col in [
            ("casework.ingest_receipts", "external_key"),
            ("casework.lock_evidence", "observation_id"),
            ("casework.evidence_items", "external_key"),
        ]:
            self.conn.execute(f"DELETE FROM {tbl} WHERE {col} LIKE 'LOCK-LIVE-%'")

    def tearDown(self) -> None:
        self.conn.close()

    def _admit(self, payload: dict):
        return self.conn.execute(
            "SELECT casework.admit_evidence(%s::jsonb)", (json.dumps(payload),)
        ).fetchone()[0]

    def test_admits_lock_evidence_and_returns_receipt(self) -> None:
        receipt = self._admit(self.payload)
        self.assertEqual(receipt["external_key"], "LOCK-LIVE-001")
        self.assertEqual(receipt["evidence_kind"], "lock_evidence")
        self.assertFalse(receipt["idempotent_replay"])
        self.assertGreaterEqual(receipt["rows_written"], 2)  # header + detail
        self.assertEqual(receipt["queued"], 1)
        row = self.conn.execute(
            "SELECT evidence_kind, available_at FROM casework.evidence_items WHERE external_key='LOCK-LIVE-001'"
        ).fetchone()
        self.assertEqual(row[0], "lock_evidence")
        self.assertIsNotNone(row[1])

    def test_second_admit_is_idempotent_one_receipt(self) -> None:
        first = self._admit(self.payload)
        second = self._admit(self.payload)
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(first["ingest_id"], second["ingest_id"])
        n_receipts = self.conn.execute(
            "SELECT count(*) FROM casework.ingest_receipts WHERE external_key='LOCK-LIVE-001'"
        ).fetchone()[0]
        self.assertEqual(n_receipts, 1)
        n_items = self.conn.execute(
            "SELECT count(*) FROM casework.evidence_items WHERE external_key='LOCK-LIVE-001'"
        ).fetchone()[0]
        self.assertEqual(n_items, 1)

    def test_invalid_schema_string_rejected_and_writes_nothing(self) -> None:
        bad = dict(self.payload, schema="wrong")
        with self.assertRaises(psycopg.errors.Error):
            self._admit(bad)
        n = self.conn.execute(
            "SELECT count(*) FROM casework.evidence_items WHERE external_key='LOCK-LIVE-001'"
        ).fetchone()[0]
        self.assertEqual(n, 0, "rejected payload must write nothing")

    def test_missing_incident_rejected(self) -> None:
        self.conn.execute("DELETE FROM casework.incidents")
        self.conn.execute("DELETE FROM casework.evidence_items WHERE external_key='INC-2047'")
        with self.assertRaises(psycopg.errors.Error):
            self._admit(self.payload)

    def test_temporal_gate(self) -> None:
        receipt = self._admit(self.payload)
        avail = receipt["available_at"]
        before = self.conn.execute(
            "SELECT count(*) FROM casework.evidence_items WHERE external_key='LOCK-LIVE-001' AND available_at <= %s",
            ("2000-01-01T00:00:00+00:00",),
        ).fetchone()[0]
        self.assertEqual(before, 0, "row must be excluded as-of a time before available_at")
        after = self.conn.execute(
            "SELECT count(*) FROM casework.evidence_items WHERE external_key='LOCK-LIVE-001' AND available_at <= %s",
            (avail,),
        ).fetchone()[0]
        self.assertEqual(after, 1, "row must be included as-of available_at")
