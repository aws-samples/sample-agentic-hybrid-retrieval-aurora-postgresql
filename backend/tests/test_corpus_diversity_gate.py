"""Unit contracts for G-33's corpus coverage and duplicate-rate checks."""

from __future__ import annotations

import unittest

from gates.corpus_diversity import (
    CORPUS_SQL,
    MAX_NEAR_DUPLICATE_RATE,
    PHASES,
    SIGNAL_TYPES,
    CorpusMeasurement,
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


if __name__ == "__main__":
    unittest.main()
