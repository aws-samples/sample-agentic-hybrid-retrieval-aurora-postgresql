"""Read-only contracts for a participant-generated live Aurora capture."""

from __future__ import annotations

import os
import unittest

import psycopg
from psycopg.rows import dict_row


LIVE_DSN = os.environ.get("LIVE_CAPTURE_DATABASE_URL")
EXPECTED_CAPTURE_ID = os.environ.get("LIVE_CAPTURE_RUN_ID")
LIVE_SOURCE = "pg_incident_capture"


@unittest.skipUnless(
    LIVE_DSN,
    "set LIVE_CAPTURE_DATABASE_URL to a database populated by the current lab run",
)
class LiveRetrievalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.conn = psycopg.connect(
            LIVE_DSN,
            autocommit=True,
            row_factory=dict_row,
            options="-c default_transaction_read_only=on",
        )
        target = cls.conn.execute(
            """
            SELECT
              current_database() AS database_name,
              to_regprocedure('aurora_version()') IS NOT NULL AS is_aurora
            """
        ).fetchone()
        if not target["is_aurora"]:
            raise RuntimeError(
                "LIVE_CAPTURE_DATABASE_URL must point to Aurora PostgreSQL"
            )

        validation = cls.conn.execute(
            "SELECT casework.assert_live_capture_ready() AS result"
        ).fetchone()["result"]
        if not validation["live_ready"]:
            raise RuntimeError(f"live capture is not ready: {validation}")

        capture = cls.conn.execute(
            """
            SELECT
              capture_id,
              capture_key,
              upper(right(replace(capture_id::text, '-', ''), 8)) AS run_suffix
            FROM casework.incident_capture_runs
            WHERE capture_origin = 'participant_induced'
            ORDER BY capture_started_at DESC
            LIMIT 1
            """
        ).fetchone()
        if capture is None:
            raise RuntimeError("no participant-induced capture is loaded")
        cls.capture_id = str(capture["capture_id"])
        cls.run_suffix = capture["run_suffix"]
        cls.incident_key = f"INC-{cls.run_suffix}"
        cls.unsafe_change_key = f"CHG-{cls.run_suffix}-01"
        cls.repair_change_key = f"CHG-{cls.run_suffix}-02"
        cls.lock_key = f"LOCK-{cls.run_suffix}-01"
        cls.core_keys = {
            cls.incident_key,
            cls.unsafe_change_key,
            cls.repair_change_key,
            cls.lock_key,
        }
        if EXPECTED_CAPTURE_ID and cls.capture_id != EXPECTED_CAPTURE_ID:
            raise RuntimeError(
                f"expected capture {EXPECTED_CAPTURE_ID}, found {cls.capture_id}"
            )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_only_this_capture_is_participant_facing(self) -> None:
        rows = self.conn.execute(
            """
            SELECT source_system, array_agg(external_key ORDER BY external_key) AS keys
            FROM casework.evidence_items
            WHERE NOT is_deleted
            GROUP BY source_system
            """
        ).fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_system"], LIVE_SOURCE)
        self.assertTrue(self.core_keys <= set(rows[0]["keys"]))
        self.assertGreaterEqual(len(rows[0]["keys"]), 100)
        self.assertLessEqual(len(rows[0]["keys"]), 120)
        self.assertTrue(
            all(
                key in self.core_keys or key.startswith(f"TEL-{self.run_suffix}-")
                for key in rows[0]["keys"]
            )
        )

        projected_sources = self.conn.execute(
            """
            SELECT DISTINCT source_system
            FROM retrieval.documents
            WHERE is_current
            ORDER BY source_system
            """
        ).fetchall()
        self.assertEqual(
            [row["source_system"] for row in projected_sources],
            [LIVE_SOURCE],
        )

    def test_search_index_is_ready_for_exact_and_fuzzy_retrieval(self) -> None:
        health = self.conn.execute(
            "SELECT retrieval.assert_search_index_ready() AS result"
        ).fetchone()["result"]
        self.assertEqual(health["status"], "ready")
        self.assertEqual(health["drift_issues"], 0)
        self.assertGreaterEqual(health["source_documents"], 100)
        self.assertLessEqual(health["source_documents"], 120)

        exact = self.conn.execute(
            """
            SELECT external_key, source_system
            FROM retrieval.full_text_search(
              %s,
              p_source_systems => ARRAY['pg_incident_capture'],
              p_limit => 5
            )
            """,
            (self.unsafe_change_key,),
        ).fetchall()
        self.assertTrue(exact)
        self.assertEqual(exact[0]["external_key"], self.unsafe_change_key)
        self.assertTrue(
            all(row["source_system"] == LIVE_SOURCE for row in exact)
        )

        fuzzy = self.conn.execute(
            """
            SELECT external_key, source_system, score
            FROM retrieval.fuzzy_search(
              ARRAY[%s],
              p_source_systems => ARRAY['pg_incident_capture'],
              p_limit => 5
            )
            """,
            (self.unsafe_change_key.replace("CHG-", "CGH-", 1),),
        ).fetchall()
        self.assertTrue(fuzzy)
        self.assertEqual(fuzzy[0]["external_key"], self.unsafe_change_key)
        self.assertTrue(
            all(row["source_system"] == LIVE_SOURCE for row in fuzzy)
        )

    def test_relationship_traversal_reaches_the_measured_core_records(self) -> None:
        rows = self.conn.execute(
            """
            SELECT reached.external_key, reached.via_relation
            FROM casework.evidence_items incident
            CROSS JOIN LATERAL retrieval.traverse_evidence(
              ARRAY[incident.evidence_id],
              2
            ) reached
            WHERE incident.external_key = %s
            """,
            (self.incident_key,),
        ).fetchall()

        self.assertTrue(
            self.core_keys <= {row["external_key"] for row in rows}
        )
        self.assertTrue(
            {"observed_during", "change_confirmed", "change_remediated"}
            <= {
                row["via_relation"]
                for row in rows
                if row["via_relation"] is not None
            }
        )
        blocking_edge = self.conn.execute(
            """
            SELECT EXISTS (
              SELECT 1
              FROM retrieval.evidence_edges edge
              JOIN casework.evidence_items source
                ON source.evidence_id = edge.from_evidence_id
              JOIN casework.evidence_items target
                ON target.evidence_id = edge.to_evidence_id
              WHERE source.external_key = %s
                AND edge.relation = 'blocked_by_change'
                AND target.external_key = %s
            ) AS present
            """,
            (self.lock_key, self.unsafe_change_key),
        ).fetchone()["present"]
        self.assertTrue(blocking_edge)

    def test_telemetry_is_complete_and_bound_to_one_capture(self) -> None:
        counts = self.conn.execute(
            """
            SELECT
              (SELECT count(*) FROM casework.pg_stat_activity_samples
                WHERE capture_id = %(capture_id)s) AS activity,
              (SELECT count(*) FROM casework.pg_lock_samples
                WHERE capture_id = %(capture_id)s) AS locks,
              (SELECT count(*) FROM casework.pg_blocking_pids_samples
                WHERE capture_id = %(capture_id)s) AS blocking_pids,
              (SELECT count(*) FROM casework.pg_stat_statements_samples
                WHERE capture_id = %(capture_id)s) AS statements,
              (SELECT count(*) FROM casework.cloudwatch_metric_samples
                WHERE capture_id = %(capture_id)s) AS cloudwatch,
              (SELECT count(*) FROM casework.database_insights_samples
                WHERE capture_id = %(capture_id)s) AS database_insights
            """,
            {"capture_id": self.capture_id},
        ).fetchone()

        self.assertEqual(counts["activity"], 270)
        self.assertEqual(counts["locks"], 270)
        self.assertEqual(counts["blocking_pids"], 180)
        self.assertEqual(counts["statements"], 3)
        self.assertEqual(counts["cloudwatch"], 5)
        self.assertGreaterEqual(counts["database_insights"], 1)

        delta = self.conn.execute(
            """
            SELECT delta_from_before
            FROM casework.pg_stat_statements_samples
            WHERE capture_id = %s
              AND phase = 'after'
            """,
            (self.capture_id,),
        ).fetchone()["delta_from_before"]
        self.assertGreaterEqual(delta["calls"], 8)
        self.assertGreater(delta["total_exec_time"], 0)
        self.assertGreaterEqual(delta["rows"], 8)

    def test_every_measured_row_traces_to_the_selected_capture(self) -> None:
        mismatches = self.conn.execute(
            """
            WITH expected(capture_id) AS (VALUES (%s::uuid)),
            observed AS (
              SELECT capture_id FROM casework.lock_evidence
              UNION ALL
              SELECT capture_id FROM casework.pg_stat_activity_samples
              UNION ALL
              SELECT capture_id FROM casework.pg_lock_samples
              UNION ALL
              SELECT capture_id FROM casework.pg_blocking_pids_samples
              UNION ALL
              SELECT capture_id FROM casework.pg_stat_statements_samples
              UNION ALL
              SELECT capture_id FROM casework.cloudwatch_metric_samples
              UNION ALL
              SELECT capture_id FROM casework.database_insights_samples
              UNION ALL
              SELECT capture_id FROM casework.telemetry_evidence
            )
            SELECT count(*) AS mismatches
            FROM observed
            CROSS JOIN expected
            WHERE observed.capture_id <> expected.capture_id
            """,
            (self.capture_id,),
        ).fetchone()["mismatches"]
        self.assertEqual(mismatches, 0)


if __name__ == "__main__":
    unittest.main()
