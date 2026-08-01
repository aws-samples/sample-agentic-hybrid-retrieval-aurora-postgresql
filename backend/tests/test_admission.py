"""Admission-contract tests (D21). Require a disposable TEST_DATABASE_URL."""
from __future__ import annotations

import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier

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


def _assert_disposable_database(conn) -> None:
    database_name = conn.execute("SELECT current_database()").fetchone()[0]
    if not database_name.endswith("_test"):
        raise RuntimeError(
            f"refusing admission tests against {database_name!r}; "
            "the server-reported database name must end in '_test'"
        )


@unittest.skipUnless(TEST_DSN and RESET_OK, "needs TEST_DATABASE_URL + ALLOW_TEST_DATABASE_RESET=1")
class AdmissionSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = psycopg.connect(TEST_DSN, autocommit=True)
        _assert_disposable_database(self.conn)
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

    def test_admission_function_keeps_its_definer_boundary_on_reapply(self) -> None:
        row = self.conn.execute(
            """
            SELECT p.prosecdef,
                   p.proconfig,
                   NOT EXISTS (
                     SELECT 1
                       FROM aclexplode(
                         coalesce(p.proacl, acldefault('f', p.proowner))
                       ) acl
                      WHERE acl.grantee = 0
                        AND acl.privilege_type = 'EXECUTE'
                   ) AS public_revoked
              FROM pg_proc p
             WHERE p.oid = 'casework.admit_evidence(jsonb)'::regprocedure
            """
        ).fetchone()

        self.assertTrue(row[0])
        self.assertIn(
            "search_path=pg_catalog, casework, retrieval",
            row[1] or [],
        )
        self.assertTrue(row[2])

    def test_schema_reapply_preserves_the_receipt_view(self) -> None:
        diagnostics_sql = (REPO_ROOT / "sql/04_diagnostics.sql").read_text(
            encoding="utf-8"
        )
        schema_sql = (REPO_ROOT / "sql/01_schema.sql").read_text(encoding="utf-8")

        self.conn.execute(diagnostics_sql)
        self.assertIsNotNone(
            self.conn.execute(
                "SELECT to_regclass('proof.v_run_receipts')"
            ).fetchone()[0]
        )

        self.conn.execute(schema_sql)
        self.assertIsNotNone(
            self.conn.execute(
                "SELECT to_regclass('proof.v_run_receipts')"
            ).fetchone()[0]
        )


FIXTURE = REPO_ROOT / "admission" / "fixture_payload.json"


class FixtureContractTest(unittest.TestCase):
    def test_fixture_has_required_top_level_fields(self) -> None:
        p = json.loads((REPO_ROOT / "admission" / "fixture_payload.json").read_text())
        for field in ["schema", "source", "kind", "external_key", "title", "occurred_at", "body", "structured"]:
            self.assertIn(field, p)
        self.assertEqual(p["schema"], "admission payload v1")
        self.assertEqual(p["kind"], "lock_evidence")
        self.assertEqual(p["structured"]["incident_external_key"], "INC-2047")
        self.assertNotIn("AccessExclusiveLock", p["body"])
        self.assertEqual(p["structured"]["blocked_lock_mode"], "RowExclusiveLock")
        self.assertEqual(p["structured"]["blocking_lock_mode"], "ShareLock")


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
    for kind, key, title in [
        ("incident", "INC-2047", "checkout lock incident"),
        ("incident", "INC-ADMISSION-ALT", "alternate admission incident"),
        ("change", "CHG-1842", "index build change"),
    ]:
        conn.execute(
            """
            INSERT INTO casework.evidence_items
              (evidence_kind, external_key, title, source_system, source_uri, source_revision, source_updated_at)
            VALUES (%s, %s, %s, 'seed', %s, 'r1', now())
            ON CONFLICT (evidence_kind, external_key) DO NOTHING
            """,
            (kind, key, title, f"seed://{key}"),
        )
    for key in ("INC-2047", "INC-ADMISSION-ALT"):
        incident_id = conn.execute(
            """
            SELECT evidence_id
              FROM casework.evidence_items
             WHERE evidence_kind = 'incident' AND external_key = %s
            """,
            (key,),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO casework.incidents
              (evidence_id, incident_id, cluster_id, severity, status, started_at,
               summary, customer_impact)
            VALUES (%s, %s, 'orion-prod', 'SEV-2', 'resolved', now(), 's', 'i')
            ON CONFLICT (evidence_id) DO NOTHING
            """,
            (incident_id, key),
        )
    change_evidence_id = conn.execute(
        """
        SELECT evidence_id
          FROM casework.evidence_items
         WHERE evidence_kind = 'change' AND external_key = 'CHG-1842'
        """
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO casework.changes
          (evidence_id, change_id, cluster_id, change_type, status, started_at,
           owner_team, description, rollback_plan)
        VALUES
          (%s, 'CHG-1842', 'orion-prod', 'ddl', 'completed', now(),
           'database-platform', 'admission test change', 'drop test index')
        ON CONFLICT (evidence_id) DO NOTHING
        """,
        (change_evidence_id,),
    )


@unittest.skipUnless(TEST_DSN and RESET_OK, "needs TEST_DATABASE_URL + ALLOW_TEST_DATABASE_RESET=1")
class AdmitEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = psycopg.connect(TEST_DSN, autocommit=True)
        _assert_disposable_database(self.conn)
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

    def _payload_copy(self) -> dict:
        return json.loads(json.dumps(self.payload))

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
        lock_row = self.conn.execute(
            """
            SELECT relation_oid, blocked_state, blocked_lock_mode,
                   blocked_lock_granted, blocking_lock_mode,
                   blocking_lock_granted, blocking_pids,
                   blocking_pids_sql, blocking_pids_output
            FROM casework.lock_evidence
            WHERE observation_id = 'LOCK-LIVE-001'
            """
        ).fetchone()
        self.assertEqual(
            lock_row,
            (
                4242,
                "active",
                "RowExclusiveLock",
                False,
                "ShareLock",
                True,
                [20044],
                "SELECT pg_blocking_pids(20919);",
                "{20044}",
            ),
        )

    def test_identical_replay_returns_the_original_receipt(self) -> None:
        first = self._admit(self.payload)
        second = self._admit(self.payload)
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(first["ingest_id"], second["ingest_id"])
        self.assertEqual(first["content_hash"], second["content_hash"])
        n_receipts = self.conn.execute(
            "SELECT count(*) FROM casework.ingest_receipts WHERE external_key='LOCK-LIVE-001'"
        ).fetchone()[0]
        self.assertEqual(n_receipts, 1)
        n_items = self.conn.execute(
            "SELECT count(*) FROM casework.evidence_items WHERE external_key='LOCK-LIVE-001'"
        ).fetchone()[0]
        self.assertEqual(n_items, 1)

    def test_acl_only_change_creates_a_new_revision_and_updates_the_header(self) -> None:
        first = self._admit(self.payload)
        revised = self._payload_copy()
        revised["acl"] = {
            "visibility": "restricted",
            "reason": "operator identity",
        }

        second = self._admit(revised)

        self.assertFalse(second["idempotent_replay"])
        self.assertNotEqual(first["ingest_id"], second["ingest_id"])
        self.assertNotEqual(first["content_hash"], second["content_hash"])
        row = self.conn.execute(
            """
            SELECT evidence_id, acl, source_revision, content_hash
              FROM casework.evidence_items
             WHERE evidence_kind = 'lock_evidence'
               AND external_key = 'LOCK-LIVE-001'
            """
        ).fetchone()
        self.assertEqual(str(row[0]), first["evidence_id"])
        self.assertEqual(row[1], revised["acl"])
        self.assertEqual(row[2], second["payload_hash"])
        self.assertEqual(row[3], second["content_hash"])
        self.assertEqual(
            self.conn.execute(
                """
                SELECT count(*)
                  FROM casework.ingest_receipts
                 WHERE external_key = 'LOCK-LIVE-001'
                """
            ).fetchone()[0],
            2,
        )

    def test_structured_change_replaces_header_and_detail_fields(self) -> None:
        first = self._admit(self.payload)
        change_id = self.conn.execute(
            """
            SELECT evidence_id
              FROM casework.evidence_items
             WHERE evidence_kind = 'change' AND external_key = 'CHG-1842'
            """
        ).fetchone()[0]
        self.conn.execute(
            """
            UPDATE casework.lock_evidence
               SET change_evidence_id = %s,
                   relation_oid = 4242,
                   blocked_state = 'active',
                   blocking_pids = ARRAY[20044],
                   database_insights_slice = '{"stale":true}'::jsonb
             WHERE observation_id = 'LOCK-LIVE-001'
            """,
            (change_id,),
        )

        revised = self._payload_copy()
        revised["source"] = dict(
            revised["source"],
            observation_window={
                "start": "2026-07-28T14:00:30+00:00",
                "end": "2026-07-28T14:04:00+00:00",
            },
        )
        revised["title"] = "Updated blocked writer observation"
        revised["occurred_at"] = "2026-07-28T14:02:30+00:00"
        revised["available_at"] = "2026-07-28T14:04:00+00:00"
        revised["structured"] = {
            "incident_external_key": "INC-ADMISSION-ALT",
            "captured_at": "2026-07-28T14:02:30+00:00",
            "relation_name": "shop.order_items",
            "blocked_pid": 30919,
            "blocking_pid": 30044,
            "wait_event_type": "Lock",
            "wait_event": "relation",
            "blocked_statement": "UPDATE shop.order_items SET quantity = $1",
            "blocking_statement": (
                "CREATE INDEX idx_order_items_product ON shop.order_items (product_id)"
            ),
            "raw_capture": {"blocking_pids": [30044], "revision": 2},
        }

        second = self._admit(revised)

        self.assertFalse(second["idempotent_replay"])
        self.assertEqual(second["evidence_id"], first["evidence_id"])
        self.assertNotEqual(second["content_hash"], first["content_hash"])
        header = self.conn.execute(
            """
            SELECT title, source_system, source_uri, source_revision,
                   source_updated_at, content_hash, available_at
              FROM casework.evidence_items
             WHERE evidence_kind = 'lock_evidence'
               AND external_key = 'LOCK-LIVE-001'
            """
        ).fetchone()
        self.assertEqual(header[0], revised["title"])
        self.assertEqual(header[1], revised["source"]["system"])
        self.assertEqual(header[2], revised["source"]["uri"])
        self.assertEqual(header[3], second["payload_hash"])
        self.assertEqual(header[4], datetime.fromisoformat(revised["occurred_at"]))
        self.assertEqual(header[5], second["content_hash"])
        self.assertEqual(header[6], datetime.fromisoformat(revised["available_at"]))

        detail = self.conn.execute(
            """
            SELECT incident.external_key, lock.captured_at, lock.relation_name,
                   lock.blocked_pid, lock.blocking_pid, lock.wait_event_type,
                   lock.wait_event, lock.blocked_statement,
                   lock.blocking_statement, lock.raw_capture,
                   lock.change_evidence_id, lock.relation_oid,
                   lock.blocked_state, lock.blocking_pids,
                   lock.database_insights_slice
              FROM casework.lock_evidence lock
              JOIN casework.evidence_items incident
                ON incident.evidence_id = lock.incident_evidence_id
             WHERE lock.observation_id = 'LOCK-LIVE-001'
            """
        ).fetchone()
        self.assertEqual(detail[0], "INC-ADMISSION-ALT")
        self.assertEqual(
            detail[1],
            datetime.fromisoformat(revised["structured"]["captured_at"]),
        )
        self.assertEqual(detail[2:9], (
            revised["structured"]["relation_name"],
            revised["structured"]["blocked_pid"],
            revised["structured"]["blocking_pid"],
            revised["structured"]["wait_event_type"],
            revised["structured"]["wait_event"],
            revised["structured"]["blocked_statement"],
            revised["structured"]["blocking_statement"],
        ))
        self.assertEqual(detail[9], revised["structured"]["raw_capture"])
        self.assertEqual(detail[10:], (None, None, None, None, None))

    def test_cross_kind_external_key_collision_is_rejected(self) -> None:
        self.conn.execute(
            """
            INSERT INTO casework.evidence_items
              (evidence_kind, external_key, title, source_system, source_uri,
               source_revision, source_updated_at)
            VALUES
              ('change', 'LOCK-LIVE-001', 'conflicting change', 'seed',
               'seed://LOCK-LIVE-001', 'r1', now())
            """
        )

        with self.assertRaises(psycopg.errors.UniqueViolation) as ctx:
            self._admit(self.payload)

        self.assertEqual(ctx.exception.sqlstate, "23505")
        self.assertIn("already belongs to evidence kind change", str(ctx.exception))
        self.assertEqual(
            self.conn.execute(
                """
                SELECT count(*)
                  FROM casework.ingest_receipts
                 WHERE external_key = 'LOCK-LIVE-001'
                """
            ).fetchone()[0],
            0,
        )

    def test_existing_external_key_cannot_be_claimed_by_another_source(self) -> None:
        self.conn.execute(
            """
            INSERT INTO casework.evidence_items
              (evidence_kind, external_key, title, source_system, source_uri,
               source_revision, source_updated_at)
            VALUES
              ('lock_evidence', 'LOCK-LIVE-001', 'foreign-source lock',
               'other_capture', 'other://lock/1', 'r1', now())
            """
        )

        with self.assertRaises(psycopg.errors.UniqueViolation) as ctx:
            self._admit(self.payload)

        self.assertEqual(ctx.exception.sqlstate, "23505")
        self.assertIn("is owned by source other_capture", str(ctx.exception))
        self.assertEqual(
            self.conn.execute(
                """
                SELECT source_system, source_uri
                  FROM casework.evidence_items
                 WHERE evidence_kind = 'lock_evidence'
                   AND external_key = 'LOCK-LIVE-001'
                """
            ).fetchone(),
            ("other_capture", "other://lock/1"),
        )

    def test_concurrent_identical_admissions_collapse_to_one_receipt(self) -> None:
        payload_json = json.dumps(self.payload)
        barrier = Barrier(2)

        def admit_from_new_connection() -> dict:
            with psycopg.connect(TEST_DSN, autocommit=True) as connection:
                barrier.wait(timeout=10)
                return connection.execute(
                    "SELECT casework.admit_evidence(%s::jsonb)",
                    (payload_json,),
                ).fetchone()[0]

        with ThreadPoolExecutor(max_workers=2) as executor:
            receipts = list(executor.map(lambda _: admit_from_new_connection(), range(2)))

        self.assertEqual(
            sorted(receipt["idempotent_replay"] for receipt in receipts),
            [False, True],
        )
        self.assertEqual(receipts[0]["ingest_id"], receipts[1]["ingest_id"])
        self.assertEqual(
            self.conn.execute(
                """
                SELECT count(*)
                  FROM casework.ingest_receipts
                 WHERE external_key = 'LOCK-LIVE-001'
                """
            ).fetchone()[0],
            1,
        )

    def test_invalid_schema_string_rejected_and_writes_nothing(self) -> None:
        bad = dict(self.payload, schema="wrong")
        with self.assertRaises(psycopg.errors.Error) as ctx:
            self._admit(bad)
        self.assertEqual(ctx.exception.sqlstate, "22023")
        n = self.conn.execute(
            "SELECT count(*) FROM casework.evidence_items WHERE external_key='LOCK-LIVE-001'"
        ).fetchone()[0]
        self.assertEqual(n, 0, "rejected payload must write nothing")

    def test_missing_incident_rejected(self) -> None:
        # A payload naming an incident absent from the corpus is rejected with
        # 23503. Craft the missing reference rather than deleting the seeded
        # incident: deletion fought the fixture_captures -> incidents RESTRICT
        # FK whenever the corpus was already loaded in the same physical
        # database, making the outcome depend on test order.
        orphan = dict(self.payload)
        orphan["source"] = dict(self.payload["source"], uri="capture://missing-incident")
        orphan["structured"] = dict(
            self.payload["structured"], incident_external_key="INC-DOES-NOT-EXIST"
        )
        with self.assertRaises(psycopg.errors.Error) as ctx:
            self._admit(orphan)
        self.assertEqual(ctx.exception.sqlstate, "23503")

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
