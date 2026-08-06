"""Hybrid Retrieval Agent contract tests.

The live synthesis test costs a real Bedrock call and requires a completed,
participant-generated two-wave Aurora capture. The static guard runs in every
suite.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_CAPTURE_DATABASE_URL = os.environ.get("LIVE_CAPTURE_DATABASE_URL")
LIVE_CAPTURE_RUN_ID = os.environ.get("LIVE_CAPTURE_RUN_ID")


class AgentToolSurfaceTests(unittest.TestCase):
    def test_registry_exposes_exactly_seven_readonly_tools(self) -> None:
        from agent.registry import TOOLS

        self.assertEqual(len(TOOLS), 7)
        source = (REPO_ROOT / "agent" / "registry.py").read_text(encoding="utf-8")
        for forbidden in (
            "CREATE INDEX",
            "CREATE ",
            "UPDATE ",
            "DELETE ",
            "ALTER ",
            "DROP ",
        ):
            self.assertNotIn(
                forbidden,
                source,
                f"registry.py must stay read-only; found {forbidden!r}",
            )


@unittest.skipUnless(
    LIVE_CAPTURE_DATABASE_URL and LIVE_CAPTURE_RUN_ID,
    (
        "requires LIVE_CAPTURE_DATABASE_URL and LIVE_CAPTURE_RUN_ID for a "
        "completed participant two-wave capture"
    ),
)
class AgentCitationScopeTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        from backend.app.db import close_pool

        close_pool()

    def test_diagnostic_answer_cites_no_wave_b_evidence(self) -> None:
        run_id, citations, answer = self._answer_the_diagnostic_question()
        self.assertTrue(citations, "the agent must cite something")
        waves = self._waves_for(run_id)
        self.assertEqual(
            waves,
            {"A"},
            f"diagnostic answer leaked Validation Evidence records: {waves}",
        )
        for expected in (
            "unbatched",
            "pool",
            "ANALYZE",
            "composite index",
            "batch",
        ):
            self.assertIn(
                expected.lower(),
                answer.lower(),
                f"diagnostic answer omitted required finding: {expected}",
            )
        self.assertRegex(
            answer.lower(),
            (
                r"(?:\[\d+\][^.]*\b(?:future migration|future backfill)\b|"
                r"(?:future migration|future backfill)[^.]*\[\d+\])"
            ),
            "future backfill guidance must cite the observed unbatched backfill",
        )

    def _answer_the_diagnostic_question(self) -> tuple[str, list[dict], str]:
        """Run the canonical Investigation Evidence question against an already-admitted corpus."""
        from backend.app.agent import answer_question
        from backend.app.config import get_settings
        from backend.app.models import AgentAnswerRequest

        with psycopg.connect(
            LIVE_CAPTURE_DATABASE_URL,
            row_factory=dict_row,
            autocommit=True,
        ) as connection:
            capture = connection.execute(
                """
                SELECT
                  wave_a.capture_id::text AS capture_id,
                  incident.incident_id
                FROM evidence.incident_capture_runs wave_a
                JOIN evidence.incidents incident
                  ON incident.evidence_id = wave_a.incident_evidence_id
                WHERE wave_a.wave = 'A'
                  AND wave_a.capture_id = %s::uuid
                  AND EXISTS (
                    SELECT 1
                    FROM evidence.incident_capture_runs wave_b
                    WHERE wave_b.incident_evidence_id =
                          wave_a.incident_evidence_id
                      AND wave_b.wave = 'B'
                )
                """,
                (LIVE_CAPTURE_RUN_ID,),
            ).fetchone()
        self.assertIsNotNone(
            capture,
            "the live test requires the named admitted Investigation Evidence plus Validation Evidence capture",
        )
        assert capture is not None
        suffix = capture["capture_id"].replace("-", "")[-8:].upper()
        question = (
            f"How did the unbatched priority_tier backfill in CHG-{suffix}-01 "
            f"cause the write stall in {capture['incident_id']}, why did queued "
            "requests time out and connected writers recover, and why did "
            f"CHG-{suffix}-02 leave the reference query slow after ANALYZE? "
            f"What did LOCK-{suffix}-01 prove about the blocker and why is the "
            "missing composite index the next action, and what should a future "
            "migration do differently?"
        )

        original_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = str(LIVE_CAPTURE_DATABASE_URL)
        get_settings.cache_clear()
        try:
            response = answer_question(
                AgentAnswerRequest(
                    question=question,
                    incident_id=capture["incident_id"],
                    source_systems=["pg_incident_capture"],
                    limit=8,
                )
            )
        finally:
            if original_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = original_database_url
            get_settings.cache_clear()

        self.assertTrue(response["answer"])
        return (
            str(response["run_id"]),
            list(response["citations"]),
            str(response["answer"]),
        )

    def _waves_for(self, run_id: str) -> set[str]:
        with psycopg.connect(
            LIVE_CAPTURE_DATABASE_URL,
            row_factory=dict_row,
            autocommit=True,
        ) as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT capture.wave
                FROM proof.answer_citations citation
                JOIN evidence.evidence_items item
                  ON item.evidence_id = citation.evidence_id
                JOIN evidence.incident_capture_runs capture
                  ON item.source_uri LIKE capture.source_bundle_uri || '/%%'
                WHERE citation.run_id = %s::uuid
                ORDER BY capture.wave
                """,
                (run_id,),
            ).fetchall()
        return {str(row["wave"]) for row in rows}


if __name__ == "__main__":
    unittest.main()
