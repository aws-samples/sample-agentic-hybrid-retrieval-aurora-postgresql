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
            "SELECT evidence.assert_live_capture_ready() AS result"
        ).fetchone()["result"]
        if not validation["two_wave_ready"]:
            raise RuntimeError(f"two-wave live capture is not ready: {validation}")

        captures = cls.conn.execute(
            """
            SELECT
              capture.capture_id,
              capture.capture_key,
              capture.wave,
              capture.source_bundle_uri,
              upper(right(replace(capture.capture_id::text, '-', ''), 8))
                AS run_suffix,
              incident.external_key AS incident_key
            FROM evidence.incident_capture_runs capture
            JOIN evidence.evidence_items incident
              ON incident.evidence_id = capture.incident_evidence_id
            WHERE capture.capture_origin = 'participant_induced'
            ORDER BY capture.wave
            """
        ).fetchall()
        if len(captures) != 2 or [capture["wave"] for capture in captures] != [
            "A",
            "B",
        ]:
            raise RuntimeError(
                "expected exactly one Investigation Evidence and one Validation Evidence participant capture"
            )
        wave_a, wave_b = captures
        if wave_a["incident_key"] != wave_b["incident_key"]:
            raise RuntimeError("the two captures do not attach to one incident")
        if wave_a["source_bundle_uri"] == wave_b["source_bundle_uri"]:
            raise RuntimeError("Investigation Evidence and Validation Evidence reused one source bundle URI")

        cls.wave_a_capture_id = str(wave_a["capture_id"])
        cls.wave_b_capture_id = str(wave_b["capture_id"])
        cls.wave_a_suffix = wave_a["run_suffix"]
        cls.wave_b_suffix = wave_b["run_suffix"]
        cls.incident_key = wave_a["incident_key"]
        cls.unsafe_change_key = f"CHG-{cls.wave_a_suffix}-01"
        cls.analyze_change_key = f"CHG-{cls.wave_a_suffix}-02"
        cls.validation_change_key = f"CHG-{cls.wave_b_suffix}-01"
        cls.lock_key = f"LOCK-{cls.wave_a_suffix}-01"
        cls.core_keys = {
            cls.incident_key,
            cls.unsafe_change_key,
            cls.analyze_change_key,
            cls.validation_change_key,
            cls.lock_key,
        }
        if EXPECTED_CAPTURE_ID and EXPECTED_CAPTURE_ID not in {
            cls.wave_a_capture_id,
            cls.wave_b_capture_id,
        }:
            raise RuntimeError(
                "expected capture "
                f"{EXPECTED_CAPTURE_ID}, found Investigation Evidence {cls.wave_a_capture_id} "
                f"and Validation Evidence {cls.wave_b_capture_id}"
            )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_only_this_two_wave_incident_is_participant_facing(self) -> None:
        rows = self.conn.execute(
            """
            SELECT source_system, array_agg(external_key ORDER BY external_key) AS keys
            FROM evidence.evidence_items
            WHERE NOT is_deleted
            GROUP BY source_system
            """
        ).fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_system"], LIVE_SOURCE)
        self.assertTrue(self.core_keys <= set(rows[0]["keys"]))
        self.assertGreaterEqual(len(rows[0]["keys"]), 50)
        self.assertLessEqual(len(rows[0]["keys"]), 80)
        self.assertTrue(
            all(
                key in self.core_keys
                or key.startswith(f"TEL-{self.wave_a_suffix}-")
                or key.startswith(f"TEL-{self.wave_b_suffix}-")
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
        self.assertGreaterEqual(health["source_documents"], 50)
        self.assertLessEqual(health["source_documents"], 80)

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
            FROM evidence.evidence_items incident
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
            {
                "observed_during",
                "change_confirmed",
                "change_ruled_out",
                "change_validates",
            }
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
              JOIN evidence.evidence_items source
                ON source.evidence_id = edge.from_evidence_id
              JOIN evidence.evidence_items target
                ON target.evidence_id = edge.to_evidence_id
              WHERE source.external_key = %s
                AND edge.relation = 'blocked_by_change'
                AND target.external_key = %s
            ) AS present
            """,
            (self.lock_key, self.unsafe_change_key),
        ).fetchone()["present"]
        self.assertTrue(blocking_edge)

    def test_telemetry_is_complete_and_bound_to_its_wave(self) -> None:
        wave_a_counts = self.conn.execute(
            """
            SELECT
              (SELECT count(*) FROM evidence.pg_stat_activity_samples
                WHERE capture_id = %(capture_id)s) AS activity,
              (SELECT count(*) FROM evidence.pg_lock_samples
                WHERE capture_id = %(capture_id)s) AS locks,
              (SELECT count(*) FROM evidence.pg_blocking_pids_samples
                WHERE capture_id = %(capture_id)s) AS blocking_pids,
              (SELECT count(*) FROM evidence.pg_stat_statements_samples
                WHERE capture_id = %(capture_id)s) AS statements,
              (SELECT count(*) FROM evidence.cloudwatch_metric_samples
                WHERE capture_id = %(capture_id)s) AS cloudwatch
            """,
            {"capture_id": self.wave_a_capture_id},
        ).fetchone()

        self.assertGreaterEqual(wave_a_counts["activity"], 10)
        self.assertGreaterEqual(wave_a_counts["locks"], 10)
        self.assertGreaterEqual(wave_a_counts["blocking_pids"], 10)
        self.assertEqual(wave_a_counts["statements"], 3)
        self.assertGreaterEqual(wave_a_counts["cloudwatch"], 0)

        delta = self.conn.execute(
            """
            SELECT delta_from_before
            FROM evidence.pg_stat_statements_samples
            WHERE capture_id = %s
              AND phase = 'after'
            """,
            (self.wave_a_capture_id,),
        ).fetchone()["delta_from_before"]
        self.assertGreaterEqual(delta["calls"], 8)
        self.assertGreater(delta["total_exec_time"], 0)
        self.assertGreaterEqual(delta["rows"], 8)

        wave_b = self.conn.execute(
            """
            SELECT
              count(*) AS documents,
              array_agg(
                DISTINCT structured ->> 'telemetry_type'
                ORDER BY structured ->> 'telemetry_type'
              ) AS signal_types
            FROM evidence.telemetry_evidence
            WHERE capture_id = %s
            """,
            (self.wave_b_capture_id,),
        ).fetchone()
        self.assertGreaterEqual(wave_b["documents"], 2)
        self.assertEqual(wave_b["signal_types"], ["meta", "plan"])

    def test_every_measured_row_traces_to_the_selected_incident_waves(self) -> None:
        mismatches = self.conn.execute(
            """
            WITH expected(capture_id) AS (
              VALUES (%s::uuid), (%s::uuid)
            ),
            observed AS (
              SELECT capture_id FROM evidence.lock_evidence
              UNION ALL
              SELECT capture_id FROM evidence.pg_stat_activity_samples
              UNION ALL
              SELECT capture_id FROM evidence.pg_lock_samples
              UNION ALL
              SELECT capture_id FROM evidence.pg_blocking_pids_samples
              UNION ALL
              SELECT capture_id FROM evidence.pg_stat_statements_samples
              UNION ALL
              SELECT capture_id FROM evidence.cloudwatch_metric_samples
              UNION ALL
              SELECT capture_id FROM evidence.telemetry_evidence
            )
            SELECT count(*) AS mismatches
            FROM observed
            CROSS JOIN expected
            GROUP BY observed.capture_id
            HAVING NOT bool_or(observed.capture_id = expected.capture_id)
            """,
            (self.wave_a_capture_id, self.wave_b_capture_id),
        ).fetchall()
        self.assertEqual(mismatches, [])


if __name__ == "__main__":
    unittest.main()
