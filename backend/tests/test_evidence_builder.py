"""Evidence builder tests. Pure functions -- no database required."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from backend.app.lab_routes import HotWriteResult
from labs.incident.evidence_builder import (
    CLASSIFICATION_REASONS,
    CLASSIFIER_VERSION,
    SIGNAL_TYPES,
    build_wave_a_documents,
    build_wave_b_documents,
    classify_visibility,
)
from labs.incident.hold_controller import HoldProof, PollSample, StateChange
from labs.incident.query_regression import PlanCheckpoint
from labs.incident.query_regression import REFERENCE_QUERY
from labs.incident.recovery_verifier import RecoveryProof


class VisibilityClassifierTests(unittest.TestCase):
    """The classifier is the only producer of restricted visibility after PI removal."""

    def test_version_is_a_single_constant(self) -> None:
        self.assertEqual(CLASSIFIER_VERSION, "statement-text/1")

    def test_reason_vocabulary_is_closed(self) -> None:
        self.assertEqual(
            CLASSIFICATION_REASONS,
            (
                "statement_text_present",
                "no_statement_text",
                "statement_text_empty",
            ),
        )

    def test_resolved_statement_text_is_restricted_with_its_sources(self) -> None:
        decision = classify_visibility(
            {
                "statement": "UPDATE workbench_lab.orders SET priority_tier = 2",
                "activity_sample_ids": [41, 7],
                "statements_sample_ids": [3],
            }
        )

        self.assertEqual(decision.visibility, "restricted")
        self.assertEqual(decision.reason, "statement_text_present")
        self.assertEqual(decision.classifier_version, CLASSIFIER_VERSION)
        self.assertEqual(
            decision.sources,
            (
                "pg_stat_activity_samples:7",
                "pg_stat_activity_samples:41",
                "pg_stat_statements_samples:3",
            ),
        )

    def test_absent_and_empty_statement_text_have_different_reasons(self) -> None:
        absent = classify_visibility({"pool_available": 0})
        self.assertEqual(absent.visibility, "workshop")
        self.assertEqual(absent.reason, "no_statement_text")

        empty = classify_visibility(
            {"statement": "   ", "activity_sample_ids": [9]}
        )
        self.assertEqual(empty.visibility, "workshop")
        self.assertEqual(empty.reason, "statement_text_empty")

    def test_restricted_without_a_source_row_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            classify_visibility({"statement": "SELECT 1"})

    def test_classification_is_byte_identical_on_replay(self) -> None:
        payload = {
            "statement": "UPDATE workbench_lab.orders SET priority_tier = 2",
            "activity_sample_ids": [41, 7],
        }
        self.assertEqual(
            classify_visibility(payload),
            classify_visibility(payload),
        )


class EvidenceBuilderTests(unittest.TestCase):
    def _wave_a_inputs(self) -> dict:
        started = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
        samples = [
            PollSample(
                pool_size=10,
                pool_max=10,
                pool_available=0,
                requests_waiting=2,
                blocked_session_count=10,
                observed_at=(started + timedelta(milliseconds=250 * ordinal)).isoformat(),
            )
            for ordinal in range(70)
        ]
        hold_proof = HoldProof(
            samples=samples,
            state_changes=[
                StateChange(
                    label="hold_state_observed",
                    detail=(
                        "pool_size=10/10, pool_available=0, "
                        "requests_waiting=2, blocked_sessions=10/10"
                    ),
                    observed_at=samples[0].observed_at,
                ),
                StateChange(
                    label="hold_state_changed",
                    detail=(
                        "pool_size=10/10, pool_available=0, "
                        "requests_waiting=2, blocked_sessions=10/10"
                    ),
                    observed_at=samples[2].observed_at,
                ),
            ],
            proven_at=samples[2].observed_at,
            hold_seconds=12.0,
        )
        activity_samples = [
            {
                "sample_id": ordinal,
                "order_id": ordinal,
                "pid": 6_000 + ordinal,
                "captured_at": samples[ordinal].observed_at,
                "statement": (
                    "UPDATE workbench_lab.orders SET status = 'touched' "
                    f"WHERE order_id = {ordinal}"
                ),
            }
            for ordinal in range(1, 11)
        ]
        statement_samples = [
            {
                "sample_id": 101,
                "phase": "before",
                "captured_at": samples[0].observed_at,
                "calls": 0,
                "rows": 0,
                "total_exec_time": 0.0,
                "queries": [],
            },
            {
                "sample_id": 102,
                "phase": "during",
                "captured_at": samples[20].observed_at,
                "calls": 10,
                "rows": 3_000_000,
                "total_exec_time": 22_700.0,
                "queries": [
                    "UPDATE workbench_lab.orders SET priority_tier = 3"
                ],
            },
            {
                "sample_id": 103,
                "phase": "after",
                "captured_at": samples[-1].observed_at,
                "calls": 12,
                "rows": 3_000_010,
                "total_exec_time": 22_735.0,
                "queries": [
                    "UPDATE workbench_lab.orders SET status = 'touched' "
                    "WHERE order_id = $1"
                ],
            },
        ]
        return {
            "run_suffix": "A1B2C3D4",
            "backfill_pid": 5_000,
            "backfill_duration_seconds": 22.7,
            "backfill_rows_updated": 3_000_000,
            "hold_proof": hold_proof,
            "recovery_proof": RecoveryProof(),
            "hot_write_results": [
                *[
                    HotWriteResult(
                        order_id=ordinal,
                        outcome="committed",
                        waited_seconds=12.5 + ordinal / 10,
                    )
                    for ordinal in range(1, 11)
                ],
                HotWriteResult(
                    order_id=11,
                    outcome="pool_timeout",
                    waited_seconds=3.0,
                ),
                HotWriteResult(
                    order_id=12,
                    outcome="pool_timeout",
                    waited_seconds=3.0,
                ),
            ],
            "activity_samples": activity_samples,
            "statement_samples": statement_samples,
            "plan_checkpoints": [
                PlanCheckpoint(
                    label="before_analyze",
                    plan_type="Seq Scan",
                    execution_ms=473.911,
                    rows_returned=20,
                    rows_removed_by_filter=2_400_000,
                    buffers=47_062,
                    raw_explain="{}",
                ),
                PlanCheckpoint(
                    label="after_analyze",
                    plan_type="Seq Scan",
                    execution_ms=229.169,
                    rows_returned=20,
                    rows_removed_by_filter=2_400_000,
                    buffers=47_059,
                    raw_explain="{}",
                ),
            ],
        }

    def _wave_b_inputs(self) -> dict:
        return {
            "run_suffix": "E5F6A7B8",
            "occurred_at": "2026-08-05T18:01:00+00:00",
            "plan_checkpoints": [
                PlanCheckpoint(
                    label="after_index",
                    plan_type="Index Scan",
                    execution_ms=2.581,
                    rows_returned=20,
                    rows_removed_by_filter=0,
                    buffers=26,
                    raw_explain="{}",
                ),
            ],
        }

    def test_every_document_carries_replayable_classification(self) -> None:
        for document in build_wave_a_documents(**self._wave_a_inputs()):
            with self.subTest(key=document.key):
                self.assertIn(document.visibility, ("workshop", "restricted"))
                self.assertEqual(document.classifier_version, CLASSIFIER_VERSION)
                self.assertIn(
                    document.classification_reason,
                    CLASSIFICATION_REASONS,
                )
                if document.visibility == "restricted":
                    self.assertTrue(document.classification_sources)

    def test_wave_a_corpus_is_genuinely_mixed(self) -> None:
        visibilities = {
            document.visibility
            for document in build_wave_a_documents(**self._wave_a_inputs())
        }
        self.assertEqual(visibilities, {"workshop", "restricted"})

    def test_signal_types_are_the_six_from_the_design(self) -> None:
        self.assertEqual(
            SIGNAL_TYPES,
            ("lock", "pool", "request", "wal", "meta", "plan"),
        )

    def test_wave_a_covers_every_signal_type(self) -> None:
        covered = {
            document.signal_type
            for document in build_wave_a_documents(**self._wave_a_inputs())
        }
        self.assertEqual(covered, set(SIGNAL_TYPES))

    def test_wave_a_emits_no_post_index_plan_checkpoint(self) -> None:
        documents = build_wave_a_documents(**self._wave_a_inputs())
        plans = [document for document in documents if document.signal_type == "plan"]

        self.assertEqual(len(plans), 2)
        self.assertNotIn("after_index", " ".join(document.key for document in plans))
        self.assertNotIn("index scan", " ".join(document.body.lower() for document in plans))

    def test_plan_documents_name_the_reference_query(self) -> None:
        documents = build_wave_a_documents(**self._wave_a_inputs())
        expected = " ".join(REFERENCE_QUERY.split())
        plans = [document for document in documents if document.signal_type == "plan"]

        self.assertTrue(plans)
        for document in plans:
            with self.subTest(key=document.key):
                self.assertIn(expected, document.body)
                self.assertEqual(document.structured["reference_query"], expected)

    def test_documents_are_fewer_than_raw_poll_samples(self) -> None:
        inputs = self._wave_a_inputs()
        self.assertLess(
            len(build_wave_a_documents(**inputs)),
            len(inputs["hold_proof"].samples),
        )

    def test_wave_b_adds_new_facts_not_restatements(self) -> None:
        wave_a = build_wave_a_documents(**self._wave_a_inputs())
        wave_b = build_wave_b_documents(**self._wave_b_inputs())

        self.assertTrue(wave_b)
        self.assertEqual(
            {document.key for document in wave_a}
            & {document.key for document in wave_b},
            set(),
        )
        self.assertEqual({document.signal_type for document in wave_b}, {"meta", "plan"})

    def test_queued_requests_are_never_described_as_blocked(self) -> None:
        documents = build_wave_a_documents(**self._wave_a_inputs())
        queued = [
            document
            for document in documents
            if "pool_timeout" in document.body
        ]

        self.assertTrue(queued)
        for document in queued:
            self.assertNotIn("Lock:transactionid", document.body)
            self.assertNotIn("entered a", document.body)

    def test_no_document_claims_a_statement_timeout(self) -> None:
        for document in build_wave_a_documents(**self._wave_a_inputs()):
            self.assertNotIn("statement_timeout", document.body)
            self.assertNotIn("statement timeout", document.body)

    def test_drain_is_recorded_as_the_recovery(self) -> None:
        bodies = " ".join(
            document.body
            for document in build_wave_a_documents(**self._wave_a_inputs())
        )
        self.assertIn("committed", bodies)
        self.assertNotIn("No hot-write request completed successfully", bodies)


if __name__ == "__main__":
    unittest.main()
