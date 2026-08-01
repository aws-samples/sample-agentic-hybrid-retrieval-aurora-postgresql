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
            "Why did CHG-1842 block checkout-prod-cluster-01 during INC-2047?"
        )

        self.assertEqual(plan["identified_keys"], ["CHG-1842", "INC-2047"])
        self.assertEqual(
            plan["inferred_filters"],
            {"incident_id": "INC-2047", "cluster_id": "checkout-prod-cluster-01"},
        )

    def test_canonical_decomposition_drives_coverage_loop(self) -> None:
        with patch(
            "backend.app.agent._anchor_keys",
            return_value={
                "lock_evidence": "LOCK-2047-001",
                "runbook": "RB-017",
            },
        ):
            plan = decompose_question_impl(
                "During INC-2047 on checkout-prod-cluster-01, determine whether "
                "CHG-1842 or CHG-1838 caused the incident, identify customer "
                "impact, and cite the lock evidence and approved runbook for "
                "recovery."
            )

        self.assertEqual(
            [row["subquestion_id"] for row in plan["subquestions"]],
            ["SQ-1", "SQ-2", "SQ-3", "SQ-4", "SQ-5"],
        )
        self.assertEqual(
            plan["subquestions"][-1]["required_kinds"],
            ["lock_evidence", "runbook"],
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
                "external_key": "INC-2047",
                "snippet": "Writes waited. Reads remained available.",
            },
            {
                "evidence_id": "confirmed-change",
                "evidence_kind": "change",
                "external_key": "CHG-1842",
                "via_relation": "change_confirmed",
                "snippet": "Ordinary CREATE INDEX blocked writes.",
            },
            {
                "evidence_id": "ruled-out-change",
                "evidence_kind": "change",
                "external_key": "CHG-1838",
                "via_relation": "change_ruled_out",
                "snippet": "Worker count was unrelated.",
            },
            {
                "evidence_id": "lock",
                "evidence_kind": "lock_evidence",
                "external_key": "LOCK-1",
                "via_relation": "observed_during",
                "snippet": "pg_blocking_pids returned [47901].",
            },
            {
                "evidence_id": "affected-case",
                "evidence_kind": "support_case",
                "external_key": "CASE-7419",
                "account_name": "Acme Retail",
                "via_relation": "support_case_affected",
                "snippet": "Checkout submissions timed out.",
            },
            {
                "evidence_id": "runbook",
                "evidence_kind": "runbook",
                "external_key": "RB-017",
                "via_relation": "runbook_used",
                "snippet": "Use CREATE INDEX CONCURRENTLY outside a transaction.",
            },
            {
                "evidence_id": "unaffected-case",
                "evidence_kind": "support_case",
                "external_key": "CASE-7424",
                "via_relation": "support_case_not_affected",
                "snippet": "Catalog reads were unrelated.",
            },
        ]

        answer, numbers = _extractive_answer(
            "Why did CHG-1842 cause INC-2047, who was affected, and what was safe?",
            evidence,
        )

        self.assertEqual(numbers, [1, 2, 4, 5, 6])
        self.assertIn("Acme Retail", answer)
        self.assertIn("CREATE INDEX CONCURRENTLY", answer)
        self.assertIn("pg_blocking_pids returned (47901)", answer)
        self.assertNotIn("CHG-1838", answer)
        self.assertNotIn("CASE-7424", answer)

    def test_merge_enriches_named_evidence_with_canonical_relation(self) -> None:
        retrieved = [
            {
                "evidence_id": "change",
                "external_key": "CHG-1842",
                "title": "Index change",
            }
        ]
        reached = [
            {
                "evidence_id": "change",
                "external_key": "CHG-1842",
                "depth": 1,
                "via_relation": "change_confirmed",
                "via_origin": "canonical_relation",
            }
        ]

        merged = _merge_evidence(
            retrieved,
            reached,
            named_keys=["CHG-1842"],
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
                "external_key": "INC-2047",
                "evidence_kind": "incident",
            },
            {
                "evidence_id": "change",
                "external_key": "CHG-1842",
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
                    "other_external_key": "INC-2047",
                }
            ],
        )
        block = evidence_block(enriched)
        self.assertIn(
            "Relationship: change_confirmed inbound INC-2047",
            block,
        )


if __name__ == "__main__":
    unittest.main()
