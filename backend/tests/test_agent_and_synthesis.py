from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.app.agent import (
    _attach_relationships,
    _cited_numbers,
    _extractive_answer,
    _merge_evidence,
    decompose_question_impl,
)
from backend.app.synthesis import evidence_block


class AgentContractTests(unittest.TestCase):
    def test_decomposition_extracts_database_identifiers(self) -> None:
        plan = decompose_question_impl(
            "Why did CHG-478FD535-01 block writes during INC-478FD535?"
        )

        self.assertEqual(
            plan["identified_keys"],
            ["CHG-478FD535-01", "INC-478FD535"],
        )
        self.assertEqual(
            plan["inferred_filters"],
            {"incident_id": "INC-478FD535", "cluster_id": None},
        )

    def test_canonical_decomposition_drives_coverage_loop(self) -> None:
        with patch(
            "backend.app.agent._anchor_keys",
            return_value={
                "lock_evidence": "LOCK-478FD535-01",
            },
        ):
            plan = decompose_question_impl(
                "During INC-478FD535, determine how CHG-478FD535-01 caused the "
                "stall, how CHG-478FD535-02 repaired it, and what the measured "
                "lock and telemetry evidence prove."
            )

        self.assertEqual(
            [row["subquestion_id"] for row in plan["subquestions"]],
            ["SQ-1", "SQ-2", "SQ-3", "SQ-4", "SQ-5"],
        )
        self.assertEqual(
            plan["subquestions"][-1]["required_kinds"],
            ["change", "telemetry"],
        )
        self.assertEqual(
            plan["subquestions"][2]["required_kinds"],
            ["telemetry"],
        )
        self.assertFalse(
            any("explain_ranking" in step for step in plan["steps"])
        )

    def test_citation_parser_fails_closed_on_unknown_number(self) -> None:
        with self.assertRaises(ValueError):
            _cited_numbers("Claim [1]. PID list [47901].", 4)

    def test_citation_parser_returns_unique_source_numbers(self) -> None:
        self.assertEqual(
            _cited_numbers("Cause [1]. Impact [2][1].", 3),
            [1, 2],
        )

    def test_prompt_uses_square_brackets_only_for_citations(self) -> None:
        block = evidence_block(
            [
                {
                    "evidence_kind": "lock_evidence",
                    "external_key": "LOCK-1",
                    "title": "Lock snapshot",
                    "source_revision": "r1",
                    "snippet": "pg_blocking_pids returned [47901]",
                }
            ]
        )

        self.assertIn("pg_blocking_pids returned (47901)", block)
        self.assertNotIn("[47901]", block)

    def test_extractive_fallback_prefers_diverse_positive_evidence(self) -> None:
        evidence = [
            {
                "evidence_id": "incident",
                "evidence_kind": "incident",
                "external_key": "INC-478FD535",
                "snippet": "Writes waited. Reads remained available.",
            },
            {
                "evidence_id": "confirmed-change",
                "evidence_kind": "change",
                "external_key": "CHG-478FD535-01",
                "via_relation": "change_confirmed",
                "snippet": "Ordinary CREATE INDEX blocked writes.",
            },
            {
                "evidence_id": "ruled-out-change",
                "evidence_kind": "change",
                "external_key": "CHG-478FD535-03",
                "via_relation": "change_ruled_out",
                "snippet": "Worker count was unrelated.",
            },
            {
                "evidence_id": "lock",
                "evidence_kind": "lock_evidence",
                "external_key": "LOCK-478FD535-01",
                "via_relation": "observed_during",
                "snippet": "pg_blocking_pids returned [47901].",
            },
            {
                "evidence_id": "telemetry",
                "evidence_kind": "telemetry",
                "external_key": "TEL-478FD535-ACT01",
                "via_relation": "measured_during",
                "snippet": "Six writers waited on Lock:relation.",
            },
            {
                "evidence_id": "repair-change",
                "evidence_kind": "change",
                "external_key": "CHG-478FD535-02",
                "via_relation": "change_remediated",
                "snippet": "Use CREATE INDEX CONCURRENTLY outside a transaction.",
            },
        ]

        answer, numbers = _extractive_answer(
            "How did CHG-478FD535-01 cause INC-478FD535 and how did "
            "CHG-478FD535-02 repair it?",
            evidence,
        )

        self.assertEqual(numbers, [1, 2, 4, 5, 6])
        self.assertIn("Six writers waited", answer)
        self.assertIn("CREATE INDEX CONCURRENTLY", answer)
        self.assertIn("pg_blocking_pids returned (47901)", answer)
        self.assertNotIn("CHG-478FD535-03", answer)

    def test_merge_enriches_named_evidence_with_canonical_relation(self) -> None:
        retrieved = [
            {
                "evidence_id": "change",
                "external_key": "CHG-A1B2C3D4-01",
                "title": "Index change",
            }
        ]
        reached = [
            {
                "evidence_id": "change",
                "external_key": "CHG-A1B2C3D4-01",
                "depth": 1,
                "via_relation": "change_confirmed",
                "via_origin": "canonical_relation",
            }
        ]

        merged = _merge_evidence(
            retrieved,
            reached,
            named_keys=["CHG-A1B2C3D4-01"],
            limit=8,
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["title"], "Index change")
        self.assertEqual(merged[0]["via_relation"], "change_confirmed")
        self.assertEqual(merged[0]["via_origin"], "canonical_relation")

    def test_compare_relationships_are_attached_for_synthesis(self) -> None:
        evidence = [
            {
                "evidence_id": "incident",
                "external_key": "INC-A1B2C3D4",
                "evidence_kind": "incident",
            },
            {
                "evidence_id": "change",
                "external_key": "CHG-A1B2C3D4-01",
                "evidence_kind": "change",
            },
        ]
        relationships = [
            {
                "from_evidence_id": "incident",
                "to_evidence_id": "change",
                "relation": "change_confirmed",
                "origin": "canonical_relation",
                "confidence": 1.0,
                "metadata": {"rationale": "Lock timing matched the change."},
            }
        ]

        enriched = _attach_relationships(evidence, relationships)

        self.assertEqual(
            enriched[1]["relationships"],
            [
                {
                    "relation": "change_confirmed",
                    "origin": "canonical_relation",
                    "confidence": 1.0,
                    "rationale": "Lock timing matched the change.",
                    "direction": "inbound",
                    "other_external_key": "INC-A1B2C3D4",
                }
            ],
        )
        block = evidence_block(enriched)
        self.assertIn(
            "Relationship: change_confirmed inbound INC-A1B2C3D4",
            block,
        )


if __name__ == "__main__":
    unittest.main()
