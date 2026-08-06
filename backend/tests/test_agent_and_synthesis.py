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
        with patch("backend.app.agent._anchor_keys", return_value={}):
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
                "During INC-478FD535, determine how the unbatched priority_tier "
                "backfill in CHG-478FD535-01 caused the write stall, why the "
                "application pool timed out then recovered, and why "
                "CHG-478FD535-02 ANALYZE did not resolve the slow query."
            )

        self.assertEqual(
            [row["subquestion_id"] for row in plan["subquestions"]],
            ["SQ-1", "SQ-2", "SQ-3"],
        )
        self.assertEqual(
            plan["subquestions"][0]["required_kinds"],
            ["incident", "change", "lock_evidence"],
        )
        self.assertEqual(
            plan["subquestions"][1]["required_kinds"],
            ["telemetry"],
        )
        self.assertEqual(
            plan["subquestions"][-1]["required_kinds"],
            ["change", "telemetry"],
        )
        self.assertIn("missing composite index", plan["subquestions"][-1]["text"])
        self.assertIn("future backfills", plan["subquestions"][0]["text"])
        self.assertFalse(
            any("explain_ranking" in step for step in plan["steps"])
        )

    def test_unkeyed_question_plans_from_the_current_capture(self) -> None:
        """A question with no INC- key still earns the three-part evidence plan.

        The participant-facing question is prose: the business framing carries no
        identifier at all, and the technical framing may still hold an unrendered
        placeholder. Both name one live capture implicitly, because a completed
        Investigation Evidence run is the only thing the agent can answer from.
        Falling through to the single-subquestion path loses the pool and
        plan-regression evidence requirements silently, which reads as a working
        answer.
        """
        framings = (
            "Why did the migration disrupt order processing, why did service "
            "recover, and why was the priority query still slow?",
            "For INC-<run-suffix>, why did some order writes block inside "
            "PostgreSQL while others timed out before reaching it, why did only "
            "the blocked writers recover when the backfill committed, and why "
            "did the reference query remain slow after ANALYZE?",
        )
        for question in framings:
            with self.subTest(question=question[:40]):
                with patch(
                    "backend.app.agent._current_capture_incident_id",
                    return_value="INC-478FD535",
                ), patch(
                    "backend.app.agent._anchor_keys",
                    return_value={"lock_evidence": "LOCK-478FD535-01"},
                ):
                    plan = decompose_question_impl(question)

                self.assertEqual(
                    [row["subquestion_id"] for row in plan["subquestions"]],
                    ["SQ-1", "SQ-2", "SQ-3"],
                )
                self.assertEqual(
                    plan["subquestions"][1]["required_kinds"],
                    ["telemetry"],
                )
                self.assertEqual(
                    plan["subquestions"][-1]["required_kinds"],
                    ["change", "telemetry"],
                )
                self.assertEqual(
                    plan["inferred_filters"]["incident_id"],
                    "INC-478FD535",
                )

    def test_unkeyed_question_without_a_capture_keeps_the_narrow_plan(self) -> None:
        """With no completed capture, the planner must not invent an incident."""
        with patch(
            "backend.app.agent._current_capture_incident_id",
            return_value=None,
        ), patch("backend.app.agent._anchor_keys", return_value={}):
            plan = decompose_question_impl(
                "Why did the migration disrupt order processing, why did "
                "service recover, and why was the priority query still slow?"
            )

        self.assertEqual(
            [row["subquestion_id"] for row in plan["subquestions"]],
            ["SQ-1"],
        )
        self.assertIsNone(plan["inferred_filters"]["incident_id"])

    def test_explicit_key_still_wins_over_the_capture_fallback(self) -> None:
        """A question naming an incident must never be redirected to another."""
        with patch(
            "backend.app.agent._current_capture_incident_id",
            return_value="INC-OTHERRUN",
        ), patch(
            "backend.app.agent._anchor_keys",
            return_value={"lock_evidence": "LOCK-478FD535-01"},
        ):
            plan = decompose_question_impl(
                "For INC-478FD535, why did writes time out and why did the "
                "reference query remain slow after ANALYZE?"
            )

        self.assertEqual(
            plan["inferred_filters"]["incident_id"],
            "INC-478FD535",
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
                "snippet": (
                    "One unbatched priority_tier backfill held row locks after "
                    "updating all orders."
                ),
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
                "snippet": (
                    "Two requests timed out at pool checkout while ten writers "
                    "waited on Lock:transactionid, then committed after release."
                ),
            },
        ]

        answer, numbers = _extractive_answer(
            "How did CHG-478FD535-01 cause the write stall in INC-478FD535, "
            "why did the pool time out, and why did ANALYZE not fix the plan?",
            evidence,
        )

        self.assertEqual(numbers, [1, 2, 4, 5])
        self.assertIn("Two requests timed out", answer)
        self.assertIn("unbatched priority_tier backfill", answer)
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

    def test_merge_retains_a_plan_checkpoint_within_the_evidence_budget(self) -> None:
        retrieved = [
            {
                "evidence_id": "incident",
                "external_key": "INC-A1B2C3D4",
                "title": "Participant-induced write stall",
            },
            {
                "evidence_id": "change",
                "external_key": "CHG-A1B2C3D4-01",
                "title": "Unbatched priority-tier backfill",
            },
            {
                "evidence_id": "lock",
                "external_key": "LOCK-A1B2C3D4-01",
                "title": "Measured transaction-ID lock wait",
            },
            {
                "evidence_id": "recovery",
                "external_key": "TEL-A1B2C3D4-M08",
                "title": "Backfill commit began recovery",
            },
            {
                "evidence_id": "pool",
                "external_key": "TEL-A1B2C3D4-Q99",
                "title": "Pool capacity recovered",
            },
            {
                "evidence_id": "plan",
                "external_key": "TEL-A1B2C3D4-P01",
                "title": "Investigation Evidence plan checkpoint: after analyze",
            },
        ]

        merged = _merge_evidence(
            retrieved,
            [],
            named_keys=[
                "INC-A1B2C3D4",
                "CHG-A1B2C3D4-01",
                "LOCK-A1B2C3D4-01",
            ],
            limit=4,
        )

        self.assertEqual(
            [row["external_key"] for row in merged],
            [
                "INC-A1B2C3D4",
                "CHG-A1B2C3D4-01",
                "LOCK-A1B2C3D4-01",
                "TEL-A1B2C3D4-P01",
            ],
        )

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
