"""Unit contracts for G-33's corpus coverage and duplicate-rate checks."""

from __future__ import annotations

import unittest

from gates.corpus_diversity import (
    CORPUS_SQL,
    MAX_NEAR_DUPLICATE_RATE,
    PHASES,
    SCHEMA_PROBE_SQL,
    SIGNAL_TYPES,
    CorpusMeasurement,
    schema_block_reason,
    validate_measurement,
)


def measurement(
    *,
    total_pairs: int = 100,
    near_duplicate_pairs: int = 14,
    signal_types: frozenset[str] = frozenset(SIGNAL_TYPES),
    phases: frozenset[str] = frozenset(PHASES),
) -> CorpusMeasurement:
    return CorpusMeasurement(
        document_count=57,
        total_pairs=total_pairs,
        near_duplicate_pairs=near_duplicate_pairs,
        signal_types=signal_types,
        phases=phases,
    )


class CorpusDiversityGateTests(unittest.TestCase):
    def test_missing_current_evidence_view_blocks_before_corpus_measurement(
        self,
    ) -> None:
        class StaleSchemaConnection:
            def execute(self, sql: str):
                self.sql = sql
                return self

            def fetchone(self):
                return {"evidence_documents": None, "capture_wave": True}

        connection = StaleSchemaConnection()

        self.assertEqual(
            schema_block_reason(connection),
            (
                "current incident-evidence schema is not applied; missing "
                "evidence.v_evidence_documents"
            ),
        )
        self.assertEqual(connection.sql, SCHEMA_PROBE_SQL)

    def test_missing_capture_stage_column_blocks_before_corpus_measurement(
        self,
    ) -> None:
        class LegacySchemaConnection:
            def execute(self, _sql: str):
                return self

            def fetchone(self):
                return {
                    "evidence_documents": "evidence.v_evidence_documents",
                    "capture_wave": False,
                }

        self.assertEqual(
            schema_block_reason(LegacySchemaConnection()),
            (
                "current incident-evidence schema is not applied; missing "
                "evidence.incident_capture_runs.wave"
            ),
        )

    def test_current_evidence_view_allows_corpus_measurement(self) -> None:
        class CurrentSchemaConnection:
            def execute(self, _sql: str):
                return self

            def fetchone(self):
                return {
                    "evidence_documents": "evidence.v_evidence_documents",
                    "capture_wave": True,
                }

        self.assertIsNone(schema_block_reason(CurrentSchemaConnection()))

    def test_complete_diverse_corpus_passes(self) -> None:
        validate_measurement(measurement())

    def test_missing_hardcoded_signal_type_fails(self) -> None:
        with self.assertRaisesRegex(AssertionError, "missing signal types"):
            validate_measurement(
                measurement(signal_types=frozenset(SIGNAL_TYPES[:-1]))
            )

    def test_missing_hardcoded_phase_fails(self) -> None:
        with self.assertRaisesRegex(AssertionError, "missing phases"):
            validate_measurement(measurement(phases=frozenset(PHASES[:-1])))

    def test_rate_at_threshold_fails_with_measured_pair_count(self) -> None:
        near_duplicate_pairs = int(MAX_NEAR_DUPLICATE_RATE * 100)
        with self.assertRaisesRegex(
            AssertionError,
            r"near-duplicate rate 15\.00% \(15/100 pairs\)",
        ):
            validate_measurement(
                measurement(
                    total_pairs=100,
                    near_duplicate_pairs=near_duplicate_pairs,
                )
            )

    def test_gate_reconstructs_document_bodies_from_current_chunks(self) -> None:
        self.assertIn("string_agg(chunk.chunk_text", CORPUS_SQL)
        self.assertIn("chunk.is_current", CORPUS_SQL)
        self.assertIn("similarity(left_document.body, right_document.body)", CORPUS_SQL)
        self.assertIn("JOIN retrieval.chunks AS chunk", CORPUS_SQL)
        self.assertNotIn("LEFT JOIN retrieval.chunks AS chunk", CORPUS_SQL)
        self.assertNotIn("d.search_document", CORPUS_SQL)
        self.assertIn("to_regclass('evidence.v_evidence_documents')", SCHEMA_PROBE_SQL)
        self.assertIn("column_name = 'wave'", SCHEMA_PROBE_SQL)


if __name__ == "__main__":
    unittest.main()
