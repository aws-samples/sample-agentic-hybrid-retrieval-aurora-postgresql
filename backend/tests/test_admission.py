"""Atomic live-run admission tests on a disposable database."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
from threading import Barrier
import unittest
from unittest.mock import patch
import uuid

import psycopg
from psycopg.rows import dict_row

from labs.incident.run_live_workshop import (
    LiveWorkshopError,
    _action_proposal,
    _prepare_lab_for_wave,
    prepare_lab_workload,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SQL_FILES = [
    "sql/00_extensions.sql",
    "sql/01_schema.sql",
    "sql/02_indexes.sql",
    "sql/03_search_functions.sql",
    "sql/06_receipts.sql",
    "sql/09_traverse_evidence.sql",
    "sql/10_admission.sql",
    "sql/13_supervised_execution.sql",
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


def _contract_record(
    *,
    external_key: str,
    title: str,
    source_uri: str,
    occurred_at: str,
    available_at: str,
    body: str,
    structured: dict,
) -> dict:
    return {
        "external_key": external_key,
        "title": title,
        "source_uri": source_uri,
        "occurred_at": occurred_at,
        "available_at": available_at,
        "body": body,
        "structured": structured,
        "acl": {
            "visibility": "workshop",
            "classifier_version": "contract-test/1",
            "classification_reason": "no_statement_text",
            "classification_sources": [],
        },
    }


def _wave_contract_payload(
    capture_id: uuid.UUID,
    *,
    wave: str,
    incident_key: str | None = None,
) -> dict:
    """Build the smallest two-wave payload that exercises admission behavior.

    This is a disposable-database contract input, not participant evidence. Wave
    B deliberately contains only new validation records; copying Wave A's lock
    observation into the later wave would make the test pass by violating the
    additive-evidence design.
    """
    suffix = capture_id.hex[-8:].upper()
    bundle_uri = f"workshop://contract-test/live-run/{capture_id}"
    started_at = "2026-08-04T12:00:00+00:00"
    ended_at = "2026-08-04T12:00:20+00:00"
    own_incident_key = f"INC-{suffix}"
    attached_incident_key = incident_key or own_incident_key

    capture = {
        "capture_id": str(capture_id),
        "capture_key": f"CAP-{suffix}",
        "run_suffix": suffix,
        "capture_origin": "participant_induced",
        "relation_name": "workbench_lab.orders",
        "relation_oid": 4242,
        "configured_row_count": 3_000_000,
        "observed_row_count": 3_000_000,
        "table_size_bytes": 268_435_456,
        "capture_started_at": started_at,
        "capture_ended_at": ended_at,
        "capture_tool_version": "wave-admission-contract-test/1",
        "manifest": {"contract_test": True},
    }
    if wave == "A":
        capture.update(
            {
                "request_count": 12,
                "blocked_writer_count": 10,
                "reader_count": 0,
                "phases": [
                    "backfill",
                    "pool_exhaustion",
                    "recovery",
                    "plan_regression",
                ],
                "signal_types": ["lock", "pool", "request", "wal", "meta", "plan"],
            }
        )
    else:
        capture.update(
            {
                "request_count": 0,
                "blocked_writer_count": 0,
                "reader_count": 0,
                "phases": ["plan_regression"],
                "signal_types": ["meta", "plan"],
            }
        )

    records: dict[str, object]
    if wave == "A":
        unsafe_key = f"CHG-{suffix}-01"
        records = {
            "incident": _contract_record(
                external_key=own_incident_key,
                title="Measured online migration write stall",
                source_uri=f"{bundle_uri}/incident",
                occurred_at=started_at,
                available_at=ended_at,
                body="An unbatched backfill blocked concurrent writes.",
                structured={
                    "severity": "SEV-3",
                    "status": "open",
                    "started_at": started_at,
                    "mitigated_at": None,
                    "resolved_at": None,
                    "summary": "The backfill blocked concurrent writes.",
                    "impact_summary": "The application pool exhausted.",
                    "resolution": None,
                },
            ),
            "changes": [
                _contract_record(
                    external_key=unsafe_key,
                    title="Unbatched priority-tier backfill",
                    source_uri=f"{bundle_uri}/change/backfill",
                    occurred_at=started_at,
                    available_at=ended_at,
                    body="One transaction updated all orders.",
                    structured={
                        "incident_external_key": own_incident_key,
                        "change_role": "unsafe",
                        "relationship": "confirmed",
                        "rationale": "Captured blockers named the backfill PID.",
                        "change_type": "ddl",
                        "status": "completed",
                        "started_at": started_at,
                        "completed_at": ended_at,
                        "owner_team": "workshop-participant",
                        "execution_sql": (
                            "UPDATE workbench_lab.orders "
                            "SET priority_tier = 2"
                        ),
                        "description": "The unbatched backfill held row locks.",
                        "rollback_plan": "ROLLBACK before commit.",
                    },
                ),
                _contract_record(
                    external_key=f"CHG-{suffix}-02",
                    title="ANALYZE did not change the plan shape",
                    source_uri=f"{bundle_uri}/change/analyze",
                    occurred_at=ended_at,
                    available_at=ended_at,
                    body="ANALYZE completed but the query remained a sequential scan.",
                    structured={
                        "incident_external_key": own_incident_key,
                        "change_role": "attempted_fix",
                        "relationship": "ruled_out",
                        "rationale": "The measured post-ANALYZE plan stayed sequential.",
                        "change_type": "ddl",
                        "status": "completed",
                        "started_at": ended_at,
                        "completed_at": ended_at,
                        "owner_team": "workshop-participant",
                        "execution_sql": "ANALYZE workbench_lab.orders",
                        "description": "Statistics refresh did not add an access path.",
                        "rollback_plan": "No rollback required.",
                    },
                ),
            ],
            "lock_evidence": _contract_record(
                external_key=f"LOCK-{suffix}-01",
                title="Measured blocked writer",
                source_uri=f"{bundle_uri}/lock/primary",
                occurred_at=started_at,
                available_at=ended_at,
                body="The writer waited while the migration transaction remained open.",
                structured={
                    "incident_external_key": own_incident_key,
                    "change_external_key": unsafe_key,
                    "captured_at": started_at,
                    "relation_name": "workbench_lab.orders",
                    "relation_oid": 4242,
                    "blocked_pid": 2002,
                    "blocking_pid": 2001,
                    "blocked_state": "active",
                    "blocked_query_start": started_at,
                    "wait_event_type": "Lock",
                    "wait_event": "transactionid",
                    "blocked_locktype": "transactionid",
                    "blocked_lock_mode": "ShareLock",
                    "blocked_lock_granted": False,
                    "blocking_pids": [2001],
                    "blocking_pids_sql": "SELECT pg_blocking_pids(2002);",
                    "blocking_pids_output": "{2001}",
                    "blocked_statement": "UPDATE workbench_lab.orders SET status='x'",
                    "blocking_statement": (
                        "UPDATE workbench_lab.orders SET priority_tier=2"
                    ),
                },
            ),
            "telemetry_documents": [],
        }
    else:
        validation_key = f"CHG-{suffix}-01"
        records = {
            "changes": [
                _contract_record(
                    external_key=validation_key,
                    title="Participant-applied supporting index",
                    source_uri=f"{bundle_uri}/change/index",
                    occurred_at=started_at,
                    available_at=ended_at,
                    body="The participant created and validated the recommended index.",
                    structured={
                        "incident_external_key": attached_incident_key,
                        "change_role": "validation",
                        "relationship": "validates",
                        "rationale": "The post-index plan used the measured index.",
                        "change_type": "ddl",
                        "status": "completed",
                        "started_at": started_at,
                        "completed_at": ended_at,
                        "owner_team": "workshop-participant",
                        "execution_sql": (
                            "CREATE INDEX idx_orders_priority_created "
                            "ON workbench_lab.orders(priority_tier, created_at DESC)"
                        ),
                        "description": "The new access path removed the sequential scan.",
                        "rollback_plan": (
                            "DROP INDEX workbench_lab.idx_orders_priority_created"
                        ),
                    },
                )
            ],
            "telemetry_documents": [
                _contract_record(
                    external_key=f"TEL-{suffix}-PLAN01",
                    title="Post-index query plan",
                    source_uri=f"{bundle_uri}/telemetry/plan/1",
                    occurred_at=ended_at,
                    available_at=ended_at,
                    body="The post-index checkpoint used an index scan.",
                    structured={
                        "incident_external_key": attached_incident_key,
                        "change_external_key": validation_key,
                        "telemetry_type": "plan",
                        "observation_number": 1,
                        "observed_until": ended_at,
                        "phase": "plan_regression",
                    },
                )
            ],
        }

    payload = {
        "schema": "admission payload v1",
        "kind": "incident_bundle",
        "wave": wave,
        "cloudwatch_status": "available",
        "source": {
            "system": "pg_incident_capture",
            "uri": bundle_uri,
            "observation_window": {"start": started_at, "end": ended_at},
        },
        "database": {
            "cluster_id": "contract-test-cluster",
            "database_name": "dat410_review_remediation_test",
            "engine": "aurora-postgresql",
            "engine_version": "18.3",
            "aws_region": "us-east-1",
            "instance_class": "db.r8g.xlarge",
            "endpoint": "contract-test.cluster.local",
        },
        "capture": capture,
        "telemetry": {
            "pg_stat_activity": [],
            "pg_locks": [],
            "pg_blocking_pids": [],
            "pg_stat_statements": [],
            "cloudwatch_metrics": [],
        },
        "records": records,
    }
    if wave == "B":
        payload["incident_key"] = attached_incident_key
    return payload


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
            "lower(v_lock #>> '{structured,wait_event}') IS DISTINCT FROM 'relation'",
            "v_lock #>> '{structured,blocked_lock_mode}'\n"
            "         IS DISTINCT FROM 'RowExclusiveLock'",
            "v_lock #>> '{structured,blocking_lock_mode}'\n"
            "         IS DISTINCT FROM 'ShareLock'",
            "OR (v_lock #>> '{structured,blocking_lock_granted}')::boolean\n"
            "         IS DISTINCT FROM true THEN",
        ):
            self.assertNotIn(stale, sql, f"stale contract still present: {stale}")
        self.assertIn(
            "lower(v_lock #>> '{structured,wait_event}')\n"
            "         IS DISTINCT FROM 'transactionid'",
            sql,
        )
        self.assertIn(
            "lower(v_lock #>> '{structured,blocked_locktype}')",
            sql,
        )
        self.assertIn("pg_blocking_pids", sql)
        self.assertIn(
            "v_cloudwatch_status IS NULL\n"
            "     OR v_cloudwatch_status NOT IN ('available', 'unavailable')",
            sql,
        )
        self.assertNotIn("'not_collected'", sql)
        self.assertIn("v_blocked_writer_count <> 10", sql)
        self.assertIn("v_request_count <= v_blocked_writer_count", sql)
        for phase in ("backfill", "pool_exhaustion", "recovery", "plan_regression"):
            self.assertIn(phase, sql)
        for signal_type in ("lock", "pool", "request", "wal", "meta", "plan"):
            self.assertIn(signal_type, sql)

    def test_admission_does_not_collapse_requests_into_blocked_writers(self) -> None:
        """A single writer_count field cannot express pool exhaustion: it has no
        way to say some requests never reached the database. Both counts must
        survive into the contract.
        """
        sql = (REPO_ROOT / "sql" / "10_admission.sql").read_text(encoding="utf-8")
        self.assertNotIn("v_writer_count", sql)
        self.assertNotIn("v_capture ->> 'writer_count'", sql)
        self.assertIn("v_request_count", sql)
        self.assertIn("v_blocked_writer_count", sql)
        self.assertIn(
            "1 + v_blocked_writer_count + v_reader_count",
            sql,
        )

    def test_admission_never_defaults_a_missing_acl(self) -> None:
        """A silent default is a classification the database invented for a
        producer that made none, and it fails unrestricted: the whole corpus comes
        out 'workshop' with no error on any surface the default gate sweep runs.
        """
        sql = (REPO_ROOT / "sql" / "10_admission.sql").read_text(encoding="utf-8")
        self.assertNotIn("""coalesce(v_record -> 'acl'""", sql)
        self.assertIn("v_record -> 'acl' IS NULL", sql)

    def test_doctor_checks_coverage_instead_of_old_document_counts(self) -> None:
        source = (REPO_ROOT / "backend" / "scripts" / "doctor.py").read_text(
            encoding="utf-8"
        )
        for stale in (
            '104 <= evidence["total"] <= 124',
            '100 <= evidence["telemetry"] <= 120',
            'evidence["incidents"] != 1',
            'evidence["changes"] != 2',
            'evidence["locks"] != 1',
        ):
            self.assertNotIn(stale, source)
        self.assertIn("EXPECTED_INCIDENT_PHASES", source)
        self.assertIn("EXPECTED_SIGNAL_TYPES", source)
        self.assertIn("missing_phases", source)
        self.assertIn("missing_signal_types", source)
        self.assertIn("get_owner_conn(row_factory=dict_row)", source)
        self.assertNotIn(
            "get_dict_conn(",
            source,
            "doctor must inspect the complete corpus, not one RLS-filtered persona",
        )


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
        self.assertEqual(payload["capture"]["request_count"], 12)
        self.assertEqual(payload["capture"]["blocked_writer_count"], 10)
        self.assertEqual(payload["capture"]["reader_count"], 0)
        self.assertEqual(
            set(payload["capture"]["phases"]),
            {"backfill", "pool_exhaustion", "recovery", "plan_regression"},
        )
        self.assertEqual(
            set(payload["capture"]["signal_types"]),
            {"lock", "pool", "request", "wal", "meta", "plan"},
        )
        self.assertTrue(payload["records"]["telemetry_documents"])
        for signal in (
            "pg_stat_activity",
            "pg_locks",
            "pg_blocking_pids",
            "pg_stat_statements",
        ):
            self.assertTrue(payload["telemetry"][signal], signal)


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
    TEST_DSN and RESET_OK,
    "needs TEST_DATABASE_URL + ALLOW_TEST_DATABASE_RESET=1",
)
class WaveAdmissionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = psycopg.connect(TEST_DSN, autocommit=True)
        _assert_disposable_database(self.connection)
        _apply_schema(self.connection, reset=True)

    def tearDown(self) -> None:
        self.connection.close()

    def _admit(self, payload: dict) -> dict:
        return self.connection.execute(
            "SELECT casework.admit_evidence(%s::jsonb)",
            (json.dumps(payload),),
        ).fetchone()[0]

    def _run_graph(self, run_id: str) -> dict:
        """Exercise the API owner with a disposable schema-bound connection.

        The regression belongs at this boundary, rather than testing the
        traversal function in isolation: ``run_graph`` selects the historical
        capture window, calls traversal, filters eligible evidence, and renders
        edge verification descriptors. The test database has no optional RLS
        roles, so a direct owner connection is the correct core-mode identity.
        """
        from backend.app import insights

        assert TEST_DSN is not None

        @contextmanager
        def test_dict_connection(_role: str):
            with psycopg.connect(
                TEST_DSN,
                autocommit=True,
                row_factory=dict_row,
            ) as connection:
                yield connection

        with patch.object(
            insights,
            "get_dict_conn",
            side_effect=test_dict_connection,
        ):
            return insights.run_graph(run_id, role="app_engineer")

    def _create_graph_run(
        self,
        *,
        incident_key: str,
        unsafe_change_key: str,
    ) -> str:
        """Persist two Wave A candidates with tied paths to their telemetry."""
        build_id = self.connection.execute(
            """
            INSERT INTO retrieval.search_index_builds(
              search_index_version, embedding_model, embedding_dimensions,
              renderer_version, chunker_version, status, completed_at,
              document_count, chunk_count
            )
            VALUES (
              'graph-replay-contract/1', 'test-only', 1024,
              'test/1', 'test/1', 'complete', clock_timestamp(), 2, 2
            )
            RETURNING build_id
            """
        ).fetchone()[0]

        document_rows = self.connection.execute(
            """
            INSERT INTO retrieval.documents(
              evidence_id, build_id, search_index_version, search_document_hash,
              source_revision, evidence_kind, external_key, title, source_system,
              source_uri, source_updated_at, acl, acl_visibility, cluster_id,
              incident_id, account_name, severity, environment, service_name,
              engine_version, aws_region, occurred_at, metadata, index_state,
              is_current, indexed_at
            )
            SELECT
              source.evidence_id,
              %s::uuid,
              'graph-replay-contract/1',
              source.search_document_hash,
              source.source_revision,
              source.evidence_kind,
              source.external_key,
              source.title,
              source.source_system,
              source.source_uri,
              source.source_updated_at,
              source.acl,
              coalesce(source.acl ->> 'visibility', 'restricted'),
              source.cluster_id,
              source.incident_id,
              source.account_name,
              source.severity,
              source.environment,
              source.service_name,
              source.engine_version,
              source.aws_region,
              source.occurred_at,
              source.metadata,
              'ready',
              false,
              clock_timestamp()
            FROM casework.v_evidence_documents source
            WHERE source.external_key = ANY(%s::text[])
            ORDER BY source.external_key
            RETURNING document_version_id, evidence_id, external_key
            """,
            (build_id, [incident_key, unsafe_change_key]),
        ).fetchall()
        self.assertEqual(len(document_rows), 2)

        candidates: list[tuple[object, object, object, str]] = []
        for document_version_id, evidence_id, external_key in document_rows:
            chunk_version_id = self.connection.execute(
                """
                INSERT INTO retrieval.chunks(
                  document_version_id, evidence_id, chunk_ordinal, section_title,
                  chunk_text, chunk_hash, embedding_state, is_current,
                  evidence_kind, source_system, source_updated_at, occurred_at,
                  acl, acl_visibility, cluster_id, incident_id, account_name,
                  severity, environment, service_name, engine_version, aws_region
                )
                SELECT
                  document.document_version_id,
                  document.evidence_id,
                  1,
                  'Graph replay contract',
                  'Contract chunk for deterministic historical graph replay.',
                  'graph-replay-' || document.document_version_id::text,
                  'pending',
                  false,
                  document.evidence_kind,
                  document.source_system,
                  document.source_updated_at,
                  document.occurred_at,
                  document.acl,
                  document.acl_visibility,
                  document.cluster_id,
                  document.incident_id,
                  document.account_name,
                  document.severity,
                  document.environment,
                  document.service_name,
                  document.engine_version,
                  document.aws_region
                FROM retrieval.documents document
                WHERE document.document_version_id = %s::uuid
                RETURNING chunk_version_id
                """,
                (document_version_id,),
            ).fetchone()[0]
            candidates.append(
                (evidence_id, document_version_id, chunk_version_id, external_key)
            )

        run_id = self.connection.execute(
            """
            INSERT INTO proof.retrieval_runs(
              query_text,
              retrieval_mode,
              role,
              rrf_k,
              text_weight,
              vector_weight,
              fuzzy_weight,
              status,
              started_at,
              completed_at
            )
            VALUES (
              'Graph replay contract',
              'hybrid',
              'app_engineer',
              60,
              1,
              1,
              1,
              'complete',
              '2026-08-04T12:00:30+00:00',
              '2026-08-04T12:00:31+00:00'
            )
            RETURNING run_id::text
            """
        ).fetchone()[0]
        for result_rank, (
            evidence_id,
            document_version_id,
            chunk_version_id,
            _external_key,
        ) in enumerate(candidates, start=1):
            self.connection.execute(
                """
                INSERT INTO proof.retrieval_candidates(
                  run_id,
                  evidence_id,
                  document_version_id,
                  chunk_version_id,
                  result_rank,
                  rrf_score,
                  final_score,
                  explanation,
                  evidence_snapshot
                )
                VALUES (
                  %s::uuid,
                  %s::uuid,
                  %s::uuid,
                  %s::uuid,
                  %s,
                  0.1,
                  0.1,
                  '{"contract":"graph_replay"}'::jsonb,
                  '{"contract":"graph_replay"}'::jsonb
                )
                """,
                (
                    run_id,
                    evidence_id,
                    document_version_id,
                    chunk_version_id,
                    result_rank,
                ),
            )
        return str(run_id)

    def _proposal_for_run(self, run_id: str) -> str:
        """Create the smallest persisted Lab 3 proposal for a retrieval run."""
        agent_run_id = self.connection.execute(
            """
            INSERT INTO proof.agent_runs(
              question,
              role,
              controls_initial,
              contract_version,
              status,
              ended_at
            )
            VALUES (
              'Graph proposal incident contract',
              'app_engineer',
              '{}'::jsonb,
              'graph-proposal-contract/1',
              'complete',
              clock_timestamp()
            )
            RETURNING agent_run_id
            """
        ).fetchone()[0]
        return str(
            self.connection.execute(
                """
                INSERT INTO proof.action_proposals(
                  agent_run_id,
                  run_id,
                  action_type,
                  target_schema,
                  target_table,
                  key_columns,
                  proposed_fingerprint,
                  proposed_sql,
                  proposed_sql_sha256,
                  preconditions,
                  expected_effect,
                  rollback_sql,
                  statement_timeout,
                  lock_timeout
                )
                VALUES (
                  %s::uuid,
                  %s::uuid,
                  'create_index',
                  'workbench_lab',
                  'orders',
                  ARRAY['priority_tier asc nulls_last default'],
                  repeat('0', 64),
                  'CREATE INDEX graph_proposal_contract',
                  repeat('0', 64),
                  '[{"check":"contract","satisfied":true}]'::jsonb,
                  'contract only',
                  'DROP INDEX graph_proposal_contract',
                  '5min',
                  '5s'
                )
                RETURNING proposal_id
                """,
                (agent_run_id, run_id),
            ).fetchone()[0]
        )

    def test_wave_b_rejects_a_proposal_not_grounded_in_its_wave_a_incident(
        self,
    ) -> None:
        wave_a = _wave_contract_payload(uuid.uuid4(), wave="A")
        self._admit(wave_a)
        incident_key = wave_a["records"]["incident"]["external_key"]
        run_id = self._create_graph_run(
            incident_key=incident_key,
            unsafe_change_key=wave_a["records"]["changes"][0]["external_key"],
        )
        proposal_id = self._proposal_for_run(run_id)

        proposal = _action_proposal(
            self.connection,
            proposal_id,
            incident_key=incident_key,
        )
        self.assertEqual(proposal["proposal_id"], proposal_id)

        with self.assertRaisesRegex(
            LiveWorkshopError,
            "not grounded in the current Wave A incident",
        ):
            _action_proposal(
                self.connection,
                proposal_id,
                incident_key="INC-NOT-THE-RETRIEVED-INCIDENT",
            )

    def test_run_graph_uses_one_stable_wave_a_route_after_wave_b_admission(
        self,
    ) -> None:
        """A later validation capture cannot change a historical graph route.

        Each Wave A telemetry record links to the incident and, when relevant,
        to the migration change. With both records as retrieval candidates those
        are equally short canonical paths. The traversal must choose one stable
        route before and after Wave B, rather than letting a join plan change
        path, relation, or edge key during replay.
        """
        wave_a = _wave_contract_payload(uuid.uuid4(), wave="A")
        run_suffix = wave_a["capture"]["run_suffix"]
        incident_key = wave_a["records"]["incident"]["external_key"]
        unsafe_change_key = wave_a["records"]["changes"][0]["external_key"]
        wave_a["records"]["telemetry_documents"].append(
            _contract_record(
                external_key=f"TEL-{run_suffix}-M01",
                title="Telemetry with incident and change relationships",
                source_uri=f"{wave_a['source']['uri']}/telemetry/meta/1",
                occurred_at=wave_a["capture"]["capture_started_at"],
                available_at=wave_a["capture"]["capture_ended_at"],
                body=(
                    "This test-only telemetry record has two equally short "
                    "canonical routes from the retrieved incident and change."
                ),
                structured={
                    "incident_external_key": incident_key,
                    "change_external_key": unsafe_change_key,
                    "telemetry_type": "meta",
                    "observation_number": 1,
                    "observed_until": wave_a["capture"]["capture_ended_at"],
                    "phase": "backfill",
                },
            )
        )
        self._admit(wave_a)
        tied_routes = self.connection.execute(
            """
            SELECT count(*)
            FROM casework.telemetry_evidence telemetry
            JOIN casework.evidence_items incident
              ON incident.evidence_id = telemetry.incident_evidence_id
            WHERE incident.external_key = %s
              AND telemetry.change_evidence_id IS NOT NULL
            """,
            (incident_key,),
        ).fetchone()[0]
        self.assertGreater(tied_routes, 0)

        run_id = self._create_graph_run(
            incident_key=incident_key,
            unsafe_change_key=unsafe_change_key,
        )
        before = [
            json.dumps(
                self._run_graph(run_id),
                sort_keys=True,
                default=str,
                separators=(",", ":"),
            )
            for _ in range(4)
        ]
        self.assertEqual(
            before,
            [before[0]] * len(before),
            "replaying one Wave A run selected different equally valid paths",
        )

        wave_b = _wave_contract_payload(
            uuid.uuid4(),
            wave="B",
            incident_key=incident_key,
        )
        self._admit(wave_b)
        self.connection.execute(
            """
            UPDATE casework.incident_capture_runs
            SET
              capture_started_at = '2026-08-04T12:01:00+00:00',
              capture_ended_at = '2026-08-04T12:01:20+00:00'
            WHERE capture_id = %s::uuid
            """,
            (wave_b["capture"]["capture_id"],),
        )

        after = [
            json.dumps(
                self._run_graph(run_id),
                sort_keys=True,
                default=str,
                separators=(",", ":"),
            )
            for _ in range(4)
        ]
        self.assertEqual(
            after,
            [before[0]] * len(after),
            "Wave B changed the persisted Wave A graph or its canonical route",
        )

    def test_wave_b_attaches_to_one_incident_and_replays_idempotently(self) -> None:
        wave_a = _wave_contract_payload(uuid.uuid4(), wave="A")
        wave_a_receipt = self._admit(wave_a)
        incident_key = wave_a["records"]["incident"]["external_key"]
        incident_source_uri = self.connection.execute(
            """
            SELECT source_uri
            FROM casework.evidence_items
            WHERE evidence_kind = 'incident' AND external_key = %s
            """,
            (incident_key,),
        ).fetchone()[0]

        wave_b = _wave_contract_payload(
            uuid.uuid4(),
            wave="B",
            incident_key=incident_key,
        )
        wave_b_receipt = self._admit(wave_b)
        counts_before_replay = self.connection.execute(
            """
            SELECT
              (SELECT count(*) FROM casework.evidence_items
               WHERE evidence_kind = 'incident'),
              (SELECT count(*) FROM casework.incident_capture_runs),
              (SELECT count(*) FROM casework.ingest_receipts),
              (SELECT count(*) FROM casework.incident_changes
               WHERE relationship = 'validates')
            """
        ).fetchone()

        replay = self._admit(wave_b)
        counts_after_replay = self.connection.execute(
            """
            SELECT
              (SELECT count(*) FROM casework.evidence_items
               WHERE evidence_kind = 'incident'),
              (SELECT count(*) FROM casework.incident_capture_runs),
              (SELECT count(*) FROM casework.ingest_receipts),
              (SELECT count(*) FROM casework.incident_changes
               WHERE relationship = 'validates')
            """
        ).fetchone()

        self.assertFalse(wave_a_receipt["idempotent_replay"])
        self.assertFalse(wave_b_receipt["idempotent_replay"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(wave_b_receipt["ingest_id"], replay["ingest_id"])
        self.assertEqual(counts_before_replay, (1, 2, 2, 1))
        self.assertEqual(counts_after_replay, counts_before_replay)
        self.assertEqual(
            _decoded(
                self.connection.execute(
                    """
                    SELECT array_agg(wave ORDER BY wave)
                    FROM casework.incident_capture_runs
                    """
                ).fetchone()[0]
            ),
            ["A", "B"],
        )
        self.assertEqual(
            self.connection.execute(
                """
                SELECT source_uri
                FROM casework.evidence_items
                WHERE evidence_kind = 'incident' AND external_key = %s
                """,
                (incident_key,),
            ).fetchone()[0],
            incident_source_uri,
            "Wave B must not replace the stable Wave A incident source URI",
        )

    def test_failed_wave_b_leaves_wave_a_intact(self) -> None:
        wave_a = _wave_contract_payload(uuid.uuid4(), wave="A")
        self._admit(wave_a)
        incident_key = wave_a["records"]["incident"]["external_key"]
        wave_b = _wave_contract_payload(
            uuid.uuid4(),
            wave="B",
            incident_key=incident_key,
        )
        wave_b["records"]["changes"][0]["structured"]["relationship"] = "remediated"

        with self.assertRaises(psycopg.errors.InvalidParameterValue):
            self._admit(wave_b)

        self.assertEqual(
            self.connection.execute(
                """
                SELECT
                  (SELECT count(*) FROM casework.incident_capture_runs),
                  (SELECT count(*) FROM casework.ingest_receipts),
                  (SELECT count(*) FROM casework.evidence_items
                   WHERE evidence_kind = 'incident')
                """
            ).fetchone(),
            (1, 1, 1),
        )

    def test_admission_requires_an_explicit_cloudwatch_result(self) -> None:
        wave_a = _wave_contract_payload(uuid.uuid4(), wave="A")
        del wave_a["cloudwatch_status"]

        with self.assertRaises(psycopg.errors.InvalidParameterValue) as caught:
            self._admit(wave_a)

        self.assertIn(
            "cloudwatch_status must be available or unavailable",
            str(caught.exception),
        )

    def test_wave_b_requires_an_existing_incident(self) -> None:
        wave_b = _wave_contract_payload(
            uuid.uuid4(),
            wave="B",
            incident_key="INC-DOESNOTEXIST",
        )
        with self.assertRaises(psycopg.errors.InvalidParameterValue) as caught:
            self._admit(wave_b)
        self.assertIn("has no Wave A capture", str(caught.exception))

    def test_wave_b_cannot_attach_across_clusters(self) -> None:
        wave_a = _wave_contract_payload(uuid.uuid4(), wave="A")
        self._admit(wave_a)
        incident_key = wave_a["records"]["incident"]["external_key"]
        wave_b = _wave_contract_payload(
            uuid.uuid4(),
            wave="B",
            incident_key=incident_key,
        )
        wave_b["database"]["cluster_id"] = "different-contract-test-cluster"

        with self.assertRaises(psycopg.errors.InvalidParameterValue) as caught:
            self._admit(wave_b)

        self.assertIn("has no Wave A capture", str(caught.exception))
        self.assertEqual(
            self.connection.execute(
                """
                SELECT
                  (SELECT count(*) FROM casework.incident_capture_runs),
                  (SELECT count(*) FROM casework.ingest_receipts)
                """
            ).fetchone(),
            (1, 1),
        )

    def test_wave_b_preparation_requires_wave_a_and_no_live_lab_sessions(self) -> None:
        """Wave B needs Wave A evidence and retains the shared lab-session guard."""
        try:
            prepare_lab_workload(TEST_DSN)
            with self.assertRaisesRegex(
                LiveWorkshopError,
                "Wave B requires Lab 1's admitted Wave A evidence; run Lab 1 first",
            ):
                _prepare_lab_for_wave(
                    TEST_DSN,
                    uuid.uuid4(),
                    wave="B",
                )

            wave_a = _wave_contract_payload(uuid.uuid4(), wave="A")
            self._admit(wave_a)
            self.connection.execute(
                "ALTER TABLE workbench_lab.orders ADD COLUMN priority_tier int"
            )
            self.connection.execute(
                """
                UPDATE workbench_lab.orders
                SET status = 'touched'
                WHERE order_id BETWEEN 1 AND 11
                """
            )
            self.connection.execute(
                """
                CREATE INDEX idx_orders_priority_tier_created_at
                  ON workbench_lab.orders (priority_tier, created_at DESC)
                """
            )

            workload, _ = _prepare_lab_for_wave(
                TEST_DSN,
                uuid.uuid4(),
                wave="B",
            )
            self.assertEqual(workload["observed_row_count"], 3_000_000)
            self.assertEqual(workload["observed_customer_count"], 5_000)

            with psycopg.connect(
                TEST_DSN,
                autocommit=True,
                application_name="workbench-live-squatter",
            ) as squatter:
                squatter.execute("SELECT 1")
                with self.assertRaisesRegex(
                    LiveWorkshopError,
                    "close stale workbench-live-\\* sessions",
                ):
                    _prepare_lab_for_wave(
                        TEST_DSN,
                        uuid.uuid4(),
                        wave="B",
                    )
        finally:
            self.connection.execute("DROP SCHEMA IF EXISTS workbench_lab CASCADE")

    def test_admission_preserves_supplied_classifier_sample_ids(self) -> None:
        """C1 provenance refers to the actual raw rows, not payload-local IDs."""
        payload = _wave_contract_payload(uuid.uuid4(), wave="A")
        suffix = payload["capture"]["run_suffix"]
        activity_id = 701
        statement_id = 702
        payload["telemetry"]["pg_stat_activity"] = [
            {
                "sample_id": activity_id,
                "observation_number": 1,
                "captured_at": "2026-08-04T12:00:05+00:00",
                "pid": 2002,
                "backend_type": "client backend",
                "application_name": "workbench-lab-api-hot-write",
                "state": "active",
                "wait_event_type": "Lock",
                "wait_event": "transactionid",
                "query_start": "2026-08-04T12:00:01+00:00",
                "xact_start": "2026-08-04T12:00:01+00:00",
                "query": "UPDATE workbench_lab.orders SET status = 'touched'",
            }
        ]
        payload["telemetry"]["pg_stat_statements"] = [
            {
                "sample_id": statement_id,
                "phase": "during",
                "captured_at": "2026-08-04T12:00:05+00:00",
                "calls": 1,
                "total_exec_time": 1.0,
                "rows": 1,
                "queryids": [],
                "queries": [
                    "UPDATE workbench_lab.orders SET priority_tier = (order_id % 5) + 1"
                ],
            }
        ]
        payload["records"]["telemetry_documents"] = [
            _contract_record(
                external_key=f"TEL-{suffix}-X01",
                title="Captured statement provenance",
                source_uri=f"{payload['source']['uri']}/telemetry/provenance",
                occurred_at="2026-08-04T12:00:05+00:00",
                available_at="2026-08-04T12:00:20+00:00",
                body="The captured statement text is a restricted observation.",
                structured={
                    "incident_external_key": f"INC-{suffix}",
                    "change_external_key": f"CHG-{suffix}-01",
                    "telemetry_type": "wal",
                    "observation_number": 1,
                    "observed_until": "2026-08-04T12:00:05+00:00",
                    "phase": "backfill",
                    "statement": "UPDATE workbench_lab.orders SET priority_tier = (order_id % 5) + 1",
                    "activity_sample_ids": [activity_id],
                    "statements_sample_ids": [statement_id],
                },
            )
        ]
        payload["records"]["telemetry_documents"][0]["acl"] = {
            "visibility": "restricted",
            "classifier_version": "statement-text/1",
            "classification_reason": "statement_text_present",
            "classification_sources": [
                f"pg_stat_activity_samples:{activity_id}",
                f"pg_stat_statements_samples:{statement_id}",
            ],
        }

        self._admit(payload)

        self.assertEqual(
            self.connection.execute(
                "SELECT sample_id FROM casework.pg_stat_activity_samples"
            ).fetchone()[0],
            activity_id,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT sample_id FROM casework.pg_stat_statements_samples"
            ).fetchone()[0],
            statement_id,
        )


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
        self.analyze_change_key = f"CHG-{self.suffix}-02"
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
        self.assertGreater(receipt["rows_written"], self.queued_documents)
        self.assertEqual(len(receipt["evidence"]), self.queued_documents)
        for key in (
            self.incident_key,
            self.unsafe_change_key,
            self.analyze_change_key,
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
                  lock_row.blocked_locktype,
                  lock_row.blocked_lock_mode,
                  lock_row.blocked_lock_granted
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
                "transactionid",
                "transactionid",
                "ShareLock",
                False,
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
                ("ruled_out", "pg_incident_capture"),
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
            "blocked_locktype"
        ] = "relation"

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
        with self.assertRaises(psycopg.errors.InvalidParameterValue) as caught:
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
        with self.assertRaises(psycopg.errors.InvalidParameterValue) as caught:
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
                with self.assertRaises(
                    psycopg.errors.InvalidParameterValue
                ) as caught:
                    self._admit(payload)
                self.assertIn(absent, str(caught.exception))

    def test_restricted_without_sources_is_rejected(self) -> None:
        payload = self._payload_copy()
        acl = payload["records"]["lock_evidence"]["acl"]
        acl["visibility"] = "restricted"
        acl["classification_reason"] = "statement_text_present"
        acl["classification_sources"] = []
        with self.assertRaises(psycopg.errors.InvalidParameterValue) as caught:
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
