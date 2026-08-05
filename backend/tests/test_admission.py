"""Atomic live-run admission tests on a disposable database."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from threading import Barrier
import unittest

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[2]
SQL_FILES = [
    "sql/00_extensions.sql",
    "sql/01_schema.sql",
    "sql/02_indexes.sql",
    "sql/03_search_functions.sql",
    "sql/09_traverse_evidence.sql",
    "sql/10_admission.sql",
]
TEST_DSN = os.environ.get("TEST_DATABASE_URL")
RESET_OK = os.environ.get("ALLOW_TEST_DATABASE_RESET") == "1"
LIVE_PAYLOAD = os.environ.get("LIVE_CAPTURE_PAYLOAD")
LIVE_CAPTURE_RUN_ID = os.environ.get("LIVE_CAPTURE_RUN_ID")


def _load_live_payload() -> dict:
    if not LIVE_PAYLOAD or not LIVE_CAPTURE_RUN_ID:
        raise RuntimeError(
            "LIVE_CAPTURE_PAYLOAD and LIVE_CAPTURE_RUN_ID are required"
        )
    payload = json.loads(Path(LIVE_PAYLOAD).read_text(encoding="utf-8"))
    if payload.get("capture", {}).get("capture_id") != LIVE_CAPTURE_RUN_ID:
        raise RuntimeError(
            "LIVE_CAPTURE_PAYLOAD does not match LIVE_CAPTURE_RUN_ID"
        )
    return payload


def _assert_disposable_database(connection) -> None:
    database_name = connection.execute(
        "SELECT current_database()"
    ).fetchone()[0]
    if isinstance(database_name, bytes):
        database_name = database_name.decode()
    if not database_name.endswith("_test"):
        raise RuntimeError(
            f"refusing admission tests against {database_name!r}; "
            "the database name must end in '_test'"
        )


def _apply_schema(connection, *, reset: bool = False) -> None:
    if reset:
        connection.execute(
            (REPO_ROOT / "sql/99_reset.sql").read_text(encoding="utf-8")
        )
    for relative_path in SQL_FILES:
        connection.execute(
            (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        )


def _decoded(value):
    if isinstance(value, bytes):
        return value.decode()
    if isinstance(value, (list, tuple)):
        return type(value)(_decoded(item) for item in value)
    return value


class DatabaseInsightsRemovalTest(unittest.TestCase):
    def test_no_sql_file_references_the_deleted_insights_table(self) -> None:
        """Every applied SQL file, not just the two that define the table.

        sql/02_indexes.sql, sql/04_diagnostics.sql, sql/11_roles_rls.sql and
        sql/12_masking.sql each CREATE or ALTER an object that references this
        table, and a missing relation is a hard apply-time ERROR in all four --
        `IF NOT EXISTS` and `OR REPLACE` guard the object being created, never
        the relation it references. Measured on PostgreSQL 17.10. A test naming
        only 01 and 10 passes while `make schema` fails.
        """
        for name in sorted(p.name for p in (REPO_ROOT / "sql").glob("*.sql")):
            sql = (REPO_ROOT / "sql" / name).read_text(encoding="utf-8")
            if name == "01_schema.sql":
                # The legacy migration-cleanup branch must keep dropping it.
                sql = sql.replace(
                    "DROP TABLE IF EXISTS casework.database_insights_samples CASCADE;",
                    "",
                )
            with self.subTest(sql_file=name):
                self.assertNotIn("database_insights_samples", sql)

    def test_admission_payload_has_no_database_insights_key(self) -> None:
        """The payload key and the telemetry_type enum value are both gone.

        Scoped to the two things this task removes rather than to the substring:
        `database_insights_mode` and `database_insights_slice` are retained
        columns on tables the workshop still uses, and a bare
        assertNotIn("database_insights", ...) would demand their removal too.
        """
        admission_sql = (REPO_ROOT / "sql" / "10_admission.sql").read_text(encoding="utf-8")
        schema_sql = (REPO_ROOT / "sql" / "01_schema.sql").read_text(encoding="utf-8")
        self.assertNotIn("-> 'database_insights'", admission_sql)
        self.assertNotIn("'database_insights',", schema_sql)
        self.assertIn("database_insights_mode", admission_sql)

    def test_no_python_read_path_references_the_deleted_insights_table(self) -> None:
        """bcfddef removed the table but missed two Python read paths.

        backend/app/insights.py summed a subquery against the deleted table
        into raw_telemetry_rows, and labs/incident/run_live_workshop.py did
        the same in its post-admission verification query. Both raised
        UndefinedTable at request time against a correctly-migrated database.
        A test scoped only to sql/*.sql (see the sibling test above) would
        stay green while these two call sites remained broken.
        """
        for relative_dir in ("backend/app", "labs/incident"):
            for path in sorted((REPO_ROOT / relative_dir).rglob("*.py")):
                source = path.read_text(encoding="utf-8")
                with self.subTest(source_file=str(path.relative_to(REPO_ROOT))):
                    self.assertNotIn("database_insights_samples", source)


class AdmissionContractTest(unittest.TestCase):
    def test_admission_contract_matches_the_four_phase_mechanism(self) -> None:
        sql = (REPO_ROOT / "sql" / "10_admission.sql").read_text(encoding="utf-8")
        for stale in (
            "observation_count <> 30",
            "writer_count <> 6",
            "reader_count <> 2",
            "pg_stat_statements",
            "cloudwatch_metrics <> 5",
        ):
            self.assertNotIn(stale, sql, f"stale contract still present: {stale}")
        self.assertIn("v_blocked_writer_count <> 10", sql)
        self.assertIn("v_request_count <= v_blocked_writer_count", sql)
        for phase in ("backfill", "pool_exhaustion", "recovery", "plan_regression"):
            self.assertIn(phase, sql)

    def test_admission_does_not_collapse_requests_into_blocked_writers(self) -> None:
        """A single writer_count field cannot express pool exhaustion: it has no
        way to say some requests never reached the database. Both counts must
        survive into the contract.
        """
        sql = (REPO_ROOT / "sql" / "10_admission.sql").read_text(encoding="utf-8")
        self.assertNotIn("v_writer_count", sql)
        self.assertIn("v_request_count", sql)
        self.assertIn("v_blocked_writer_count", sql)

    def test_admission_never_defaults_a_missing_acl(self) -> None:
        """A silent default is a classification the database invented for a
        producer that made none, and it fails unrestricted: the whole corpus comes
        out 'workshop' with no error on any surface the default gate sweep runs.
        """
        sql = (REPO_ROOT / "sql" / "10_admission.sql").read_text(encoding="utf-8")
        self.assertNotIn("""coalesce(v_record -> 'acl'""", sql)
        self.assertIn("v_record -> 'acl' IS NULL", sql)


@unittest.skipUnless(
    LIVE_PAYLOAD and LIVE_CAPTURE_RUN_ID,
    "needs LIVE_CAPTURE_PAYLOAD + LIVE_CAPTURE_RUN_ID from a participant run",
)
class LivePayloadContractTest(unittest.TestCase):
    def test_payload_has_run_derived_identity_and_measured_scale(self) -> None:
        payload = _load_live_payload()
        suffix = payload["capture"]["run_suffix"]

        self.assertEqual(payload["schema"], "admission payload v1")
        self.assertEqual(payload["kind"], "incident_bundle")
        self.assertEqual(payload["source"]["system"], "pg_incident_capture")
        self.assertEqual(
            payload["records"]["incident"]["external_key"],
            f"INC-{suffix}",
        )
        self.assertEqual(
            [record["external_key"] for record in payload["records"]["changes"]],
            [f"CHG-{suffix}-01", f"CHG-{suffix}-02"],
        )
        self.assertEqual(
            payload["records"]["lock_evidence"]["external_key"],
            f"LOCK-{suffix}-01",
        )
        self.assertGreaterEqual(
            len(payload["records"]["telemetry_documents"]),
            100,
        )
        self.assertLessEqual(
            len(payload["records"]["telemetry_documents"]),
            120,
        )
        self.assertEqual(len(payload["telemetry"]["pg_stat_activity"]), 270)
        self.assertEqual(len(payload["telemetry"]["pg_locks"]), 270)
        self.assertEqual(len(payload["telemetry"]["pg_blocking_pids"]), 180)


@unittest.skipUnless(
    TEST_DSN and RESET_OK,
    "needs TEST_DATABASE_URL + ALLOW_TEST_DATABASE_RESET=1",
)
class AdmissionSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = psycopg.connect(TEST_DSN, autocommit=True)
        _assert_disposable_database(self.connection)
        _apply_schema(self.connection, reset=True)

    def tearDown(self) -> None:
        self.connection.close()

    def test_schema_has_live_telemetry_and_definer_admission(self) -> None:
        row = self.connection.execute(
            """
            SELECT procedure.prosecdef, procedure.proconfig
            FROM pg_proc procedure
            WHERE procedure.oid =
              'casework.admit_evidence(jsonb)'::regprocedure
            """
        ).fetchone()
        self.assertTrue(row[0])
        self.assertIn(
            "search_path=pg_catalog, casework, retrieval",
            _decoded(row[1] or []),
        )
        evidence_kind = self.connection.execute(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'casework.evidence_items'::regclass
              AND conname = 'evidence_items_evidence_kind_check'
            """
        ).fetchone()[0]
        self.assertIn("telemetry", evidence_kind)
        self.assertIsNotNone(
            self.connection.execute(
                "SELECT to_regclass('casework.telemetry_evidence')"
            ).fetchone()[0]
        )

    def test_chunks_carry_source_system(self) -> None:
        column = self.connection.execute(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'retrieval'
              AND table_name = 'chunks'
              AND column_name = 'source_system'
            """
        ).fetchone()
        self.assertEqual(_decoded(column), ("NO",))


@unittest.skipUnless(
    TEST_DSN and RESET_OK and LIVE_PAYLOAD and LIVE_CAPTURE_RUN_ID,
    (
        "needs TEST_DATABASE_URL + ALLOW_TEST_DATABASE_RESET=1 + "
        "LIVE_CAPTURE_PAYLOAD + LIVE_CAPTURE_RUN_ID"
    ),
)
class AdmitEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = psycopg.connect(TEST_DSN, autocommit=True)
        _assert_disposable_database(self.connection)
        _apply_schema(self.connection, reset=True)
        self.payload = _load_live_payload()
        self.suffix = self.payload["capture"]["run_suffix"]
        self.incident_key = f"INC-{self.suffix}"
        self.unsafe_change_key = f"CHG-{self.suffix}-01"
        self.safe_change_key = f"CHG-{self.suffix}-02"
        self.lock_key = f"LOCK-{self.suffix}-01"
        self.telemetry_documents = len(
            self.payload["records"]["telemetry_documents"]
        )
        self.queued_documents = 4 + self.telemetry_documents

    def tearDown(self) -> None:
        self.connection.close()

    def _admit(self, payload: dict) -> dict:
        return self.connection.execute(
            "SELECT casework.admit_evidence(%s::jsonb)",
            (json.dumps(payload),),
        ).fetchone()[0]

    def _payload_copy(self) -> dict:
        return json.loads(json.dumps(self.payload))

    def test_admits_complete_run_and_queues_every_document(self) -> None:
        receipt = self._admit(self.payload)

        self.assertFalse(receipt["idempotent_replay"])
        self.assertEqual(receipt["evidence_kind"], "incident_bundle")
        self.assertEqual(receipt["queued"], self.queued_documents)
        self.assertEqual(
            receipt["edges_written"],
            4 + (2 * self.telemetry_documents),
        )
        self.assertGreaterEqual(receipt["rows_written"], 900)
        self.assertEqual(len(receipt["evidence"]), self.queued_documents)
        for key in (
            self.incident_key,
            self.unsafe_change_key,
            self.safe_change_key,
            self.lock_key,
        ):
            self.assertIn(key, receipt["evidence"])

        headers = _decoded(
            self.connection.execute(
                """
                SELECT evidence_kind, external_key, source_system
                FROM casework.evidence_items
                ORDER BY evidence_kind, external_key
                """
            ).fetchall()
        )
        self.assertEqual(len(headers), self.queued_documents)
        self.assertTrue(
            all(source == "pg_incident_capture" for _, _, source in headers)
        )
        self.assertEqual(
            sum(kind == "telemetry" for kind, _, _ in headers),
            self.telemetry_documents,
        )

        lock_row = _decoded(
            self.connection.execute(
                """
                SELECT
                  incident.incident_id,
                  change.change_id,
                  lock_row.wait_event_type,
                  lock_row.wait_event,
                  lock_row.blocked_lock_mode,
                  lock_row.blocked_lock_granted,
                  lock_row.blocking_lock_mode,
                  lock_row.blocking_lock_granted
                FROM casework.lock_evidence lock_row
                JOIN casework.incidents incident
                  ON incident.evidence_id = lock_row.incident_evidence_id
                JOIN casework.changes change
                  ON change.evidence_id = lock_row.change_evidence_id
                WHERE lock_row.observation_id = %s
                """,
                (self.lock_key,),
            ).fetchone()
        )
        self.assertEqual(
            lock_row,
            (
                self.incident_key,
                self.unsafe_change_key,
                "Lock",
                "relation",
                "RowExclusiveLock",
                False,
                "ShareLock",
                True,
            ),
        )
        relationships = _decoded(
            self.connection.execute(
                """
                SELECT relationship, confirmed_by
                FROM casework.incident_changes
                ORDER BY relationship
                """
            ).fetchall()
        )
        self.assertEqual(
            relationships,
            [
                ("confirmed", "pg_incident_capture"),
                ("remediated", "pg_incident_capture"),
            ],
        )
        counts = self.connection.execute(
            """
            SELECT
              (SELECT count(*) FROM casework.pg_stat_activity_samples),
              (SELECT count(*) FROM casework.pg_lock_samples),
              (SELECT count(*) FROM casework.pg_blocking_pids_samples),
              (SELECT count(*) FROM casework.telemetry_evidence),
              (SELECT count(*) FROM retrieval.search_index_queue)
            """
        ).fetchone()
        self.assertEqual(
            counts,
            (
                len(self.payload["telemetry"]["pg_stat_activity"]),
                len(self.payload["telemetry"]["pg_locks"]),
                len(self.payload["telemetry"]["pg_blocking_pids"]),
                self.telemetry_documents,
                self.queued_documents,
            ),
        )

    def test_identical_replay_returns_one_receipt_and_stable_ids(self) -> None:
        first = self._admit(self.payload)
        second = self._admit(self.payload)

        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(first["ingest_id"], second["ingest_id"])
        self.assertEqual(first["evidence"], second["evidence"])
        self.assertEqual(
            self.connection.execute(
                "SELECT count(*) FROM casework.ingest_receipts"
            ).fetchone()[0],
            1,
        )

    def test_changed_measurement_cannot_reuse_capture_identity(self) -> None:
        self._admit(self.payload)
        revised = self._payload_copy()
        revised["records"]["lock_evidence"]["structured"]["blocked_pid"] = 21919
        revised["records"]["lock_evidence"]["structured"][
            "blocking_pids_sql"
        ] = "SELECT pg_blocking_pids(21919);"

        with self.assertRaises(psycopg.errors.UniqueViolation):
            self._admit(revised)
        self.assertEqual(
            self.connection.execute(
                "SELECT count(*) FROM casework.ingest_receipts"
            ).fetchone()[0],
            1,
        )

    def test_invalid_bundle_rolls_back_every_record(self) -> None:
        invalid = self._payload_copy()
        invalid["records"]["lock_evidence"]["structured"][
            "blocking_lock_mode"
        ] = "AccessExclusiveLock"

        with self.assertRaises(psycopg.errors.InvalidParameterValue):
            self._admit(invalid)
        self.assertEqual(
            self.connection.execute(
                "SELECT count(*) FROM casework.evidence_items"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT count(*) FROM casework.database_clusters"
            ).fetchone()[0],
            0,
        )

    def test_cross_source_collision_rolls_back_the_run(self) -> None:
        self.connection.execute(
            """
            INSERT INTO casework.evidence_items(
              evidence_kind,
              external_key,
              title,
              source_system,
              source_uri,
              source_revision,
              source_updated_at
            )
            VALUES ('change', %s, 'foreign', 'other_source',
                    'other://change/1', 'r1', now())
            """,
            (self.unsafe_change_key,),
        )

        with self.assertRaises(psycopg.errors.UniqueViolation):
            self._admit(self.payload)
        self.assertEqual(
            self.connection.execute(
                """
                SELECT count(*)
                FROM casework.evidence_items
                WHERE external_key IN (%s, %s)
                """,
                (self.incident_key, self.lock_key),
            ).fetchone()[0],
            0,
        )

    def test_record_without_an_acl_is_rejected(self) -> None:
        payload = self._payload_copy()
        del payload["records"]["lock_evidence"]["acl"]
        with self.assertRaises(psycopg.errors.RaiseException) as caught:
            self._admit(payload)
        self.assertIn("acl", str(caught.exception))
        self.assertEqual(
            self.connection.execute(
                "SELECT count(*) FROM casework.evidence_items"
            ).fetchone()[0],
            0,
            "a rejected bundle must leave zero rows",
        )

    def test_unknown_visibility_value_is_rejected(self) -> None:
        """retrieval.acl_visible computes coalesce(..., 'restricted') = 'workshop',
        so an unrecognized value reads as restricted and the row silently vanishes
        from every retrieval arm. Reject it where the message can name it.
        """
        payload = self._payload_copy()
        payload["records"]["lock_evidence"]["acl"]["visibility"] = "internal"
        with self.assertRaises(psycopg.errors.RaiseException) as caught:
            self._admit(payload)
        self.assertIn("internal", str(caught.exception))

    def test_record_missing_classification_provenance_is_rejected(self) -> None:
        for absent in (
            "classifier_version",
            "classification_reason",
            "classification_sources",
        ):
            with self.subTest(absent=absent):
                payload = self._payload_copy()
                del payload["records"]["lock_evidence"]["acl"][absent]
                with self.assertRaises(psycopg.errors.RaiseException) as caught:
                    self._admit(payload)
                self.assertIn(absent, str(caught.exception))

    def test_restricted_without_sources_is_rejected(self) -> None:
        payload = self._payload_copy()
        acl = payload["records"]["lock_evidence"]["acl"]
        acl["visibility"] = "restricted"
        acl["classification_reason"] = "statement_text_present"
        acl["classification_sources"] = []
        with self.assertRaises(psycopg.errors.RaiseException) as caught:
            self._admit(payload)
        self.assertIn("classification_sources", str(caught.exception))

    def test_concurrent_replay_collapses_to_one_receipt(self) -> None:
        payload = json.dumps(self.payload)
        barrier = Barrier(2)

        def admit_from_new_connection() -> dict:
            with psycopg.connect(TEST_DSN, autocommit=True) as connection:
                barrier.wait(timeout=10)
                return connection.execute(
                    "SELECT casework.admit_evidence(%s::jsonb)",
                    (payload,),
                ).fetchone()[0]

        with ThreadPoolExecutor(max_workers=2) as executor:
            receipts = list(
                executor.map(
                    lambda _: admit_from_new_connection(),
                    range(2),
                )
            )
        self.assertEqual(
            sorted(receipt["idempotent_replay"] for receipt in receipts),
            [False, True],
        )
        self.assertEqual(receipts[0]["ingest_id"], receipts[1]["ingest_id"])


if __name__ == "__main__":
    unittest.main()
