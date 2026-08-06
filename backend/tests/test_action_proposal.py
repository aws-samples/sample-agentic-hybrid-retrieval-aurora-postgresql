"""Structured action-proposal contracts.

Pure parsing and rendering checks run in every suite. The live check requires
the current participant's Investigation Evidence capture, before the participant executes the
proposed index. It makes one extra Bedrock tool-use request after cited
synthesis, so it is explicitly gated and never runs against a reset-only test
database that has no captured incident.
"""
from __future__ import annotations

import os
import re
import unittest

import psycopg
from psycopg.rows import dict_row

from backend.app.action_proposal import (
    ACTION_PROPOSAL_TOOL_NAME,
    ACTION_PROPOSAL_TOOL_SPEC,
    IndexKey,
    ProposalFields,
    index_name_for,
    parse_proposal_fields,
    render_create_index,
    render_rollback,
)


LIVE_CAPTURE_DATABASE_URL = os.environ.get("LIVE_CAPTURE_DATABASE_URL")
LIVE_CAPTURE_RUN_ID = os.environ.get("LIVE_CAPTURE_RUN_ID")

VALID_PAYLOAD = {
    "action_type": "create_index",
    "target_schema": "workbench_lab",
    "target_table": "orders",
    "index_method": "btree",
    "is_unique": False,
    "key_columns": [
        {"column": "priority_tier", "direction": "asc"},
        {"column": "created_at", "direction": "desc"},
    ],
    "included_columns": [],
    "predicate": None,
    "expected_effect": "an index scan replaces the sequential scan",
    "supporting_citations": [
        {"citation_number": 1, "claim": "the plan remained a sequential scan"}
    ],
}


class ProposalParsingTests(unittest.TestCase):
    def test_tool_spec_names_the_tool_it_is_registered_under(self) -> None:
        self.assertEqual(
            ACTION_PROPOSAL_TOOL_SPEC["toolSpec"]["name"],
            ACTION_PROPOSAL_TOOL_NAME,
        )

    def test_valid_payload_parses(self) -> None:
        fields = parse_proposal_fields(VALID_PAYLOAD)
        self.assertEqual(fields.action_type, "create_index")
        self.assertEqual(
            fields.key_columns,
            (IndexKey("priority_tier", "asc"), IndexKey("created_at", "desc")),
        )

    def test_key_column_order_is_preserved_not_sorted(self) -> None:
        reversed_payload = dict(VALID_PAYLOAD)
        reversed_payload["key_columns"] = list(
            reversed(VALID_PAYLOAD["key_columns"])
        )

        fields = parse_proposal_fields(reversed_payload)

        self.assertEqual(
            [key.column for key in fields.key_columns],
            ["created_at", "priority_tier"],
        )

    def test_an_injected_identifier_is_refused(self) -> None:
        for bad in (
            "orders; DROP TABLE workbench_lab.orders",
            'orders" ; --',
            "pg_catalog.pg_class",
            "",
        ):
            with self.subTest(identifier=bad):
                with self.assertRaises(ValueError):
                    parse_proposal_fields(dict(VALID_PAYLOAD, target_table=bad))

    def test_no_key_columns_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            parse_proposal_fields(dict(VALID_PAYLOAD, key_columns=[]))

    def test_an_unknown_direction_is_refused(self) -> None:
        payload = dict(VALID_PAYLOAD)
        payload["key_columns"] = [
            {"column": "created_at", "direction": "sideways"}
        ]
        with self.assertRaises(ValueError):
            parse_proposal_fields(payload)

    def test_a_partial_index_predicate_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "predicate is not supported"):
            parse_proposal_fields(
                dict(VALID_PAYLOAD, predicate="status = 'open'")
            )


class ProposalRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fields = parse_proposal_fields(VALID_PAYLOAD)

    def test_rendered_ddl_is_deterministic_and_qualified(self) -> None:
        name, ddl = render_create_index(self.fields)
        self.assertEqual(name, index_name_for(self.fields))
        self.assertEqual(
            ddl,
            "CREATE INDEX idx_orders_priority_tier_created_at\n"
            "  ON workbench_lab.orders USING btree "
            "(priority_tier ASC, created_at DESC);",
        )

    def test_rendered_ddl_emits_no_nulls_or_opclass_clause(self) -> None:
        _name, ddl = render_create_index(self.fields)
        self.assertNotIn("NULLS", ddl)
        self.assertNotIn("opclass", ddl.lower())
        self.assertNotIn("text_pattern_ops", ddl)

    def test_rollback_drops_exactly_the_proposed_index(self) -> None:
        name, _ddl = render_create_index(self.fields)
        self.assertEqual(
            render_rollback(self.fields, name),
            "DROP INDEX IF EXISTS workbench_lab.idx_orders_priority_tier_created_at;",
        )

    def test_index_name_stays_within_the_identifier_limit(self) -> None:
        long_fields = ProposalFields(
            action_type="create_index",
            target_schema="workbench_lab",
            target_table="orders",
            index_method="btree",
            is_unique=False,
            key_columns=tuple(
                IndexKey(f"a_very_long_column_name_number_{number}", "asc")
                for number in range(6)
            ),
            included_columns=(),
            predicate=None,
            expected_effect="x",
            supporting_citations=(),
        )
        self.assertLessEqual(
            len(index_name_for(long_fields).encode("utf-8")),
            63,
        )


@unittest.skipUnless(
    LIVE_CAPTURE_DATABASE_URL and LIVE_CAPTURE_RUN_ID,
    (
        "requires LIVE_CAPTURE_DATABASE_URL and LIVE_CAPTURE_RUN_ID for a "
        "current Investigation Evidence participant capture"
    ),
)
class ProposalEmissionTests(unittest.TestCase):
    """One real Investigation Evidence Lab 3 answer validates the append-only record."""

    @classmethod
    def setUpClass(cls) -> None:
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
                  capture.capture_id::text AS capture_id,
                  incident.incident_id
                FROM evidence.incident_capture_runs capture
                JOIN evidence.incidents incident
                  ON incident.evidence_id = capture.incident_evidence_id
                WHERE capture.capture_origin = 'participant_induced'
                  AND capture.wave = 'A'
                  AND capture.capture_id = %s::uuid
                  AND NOT EXISTS (
                    SELECT 1
                    FROM evidence.incident_capture_runs later
                    WHERE later.incident_evidence_id =
                          capture.incident_evidence_id
                      AND later.wave = 'B'
                  )
                """,
                (LIVE_CAPTURE_RUN_ID,),
            ).fetchone()
        if capture is None:
            raise RuntimeError(
                "the live proposal test requires the named admitted Investigation Evidence "
                "capture before Validation Evidence"
            )

        cls.capture = capture
        suffix = capture["capture_id"].replace("-", "")[-8:].upper()
        cls.question = (
            f"How did the unbatched priority_tier backfill in CHG-{suffix}-01 "
            f"cause the write stall in {capture['incident_id']}, why did queued "
            "requests time out and connected writers recover, and why did "
            f"CHG-{suffix}-02 leave the reference query slow after ANALYZE? "
            f"What did LOCK-{suffix}-01 prove about the blocker, why is the "
            "missing composite index the next action, and what should a future "
            "migration do differently?"
        )
        original_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = str(LIVE_CAPTURE_DATABASE_URL)
        get_settings.cache_clear()
        try:
            cls.response = answer_question(
                AgentAnswerRequest(
                    question=cls.question,
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

        cls.agent_run_id = cls.response["agent_run_id"]
        with psycopg.connect(
            LIVE_CAPTURE_DATABASE_URL,
            row_factory=dict_row,
            autocommit=True,
        ) as connection:
            cls.proposal = connection.execute(
                """
                SELECT *
                FROM proof.action_proposals
                WHERE agent_run_id = %s::uuid
                """,
                (cls.agent_run_id,),
            ).fetchone()

    @classmethod
    def tearDownClass(cls) -> None:
        from backend.app.db import close_pool

        close_pool()

    def test_the_answer_path_writes_exactly_one_proposal(self) -> None:
        proposal = self.proposal
        self.assertIsNotNone(proposal)
        assert proposal is not None
        self.assertEqual(str(proposal["agent_run_id"]), self.agent_run_id)
        self.assertEqual(proposal["action_type"], "create_index")
        self.assertEqual(proposal["target_schema"], "workbench_lab")
        self.assertEqual(proposal["target_table"], "orders")
        self.assertEqual(
            proposal["key_columns"],
            [
                "priority_tier asc nulls_last default",
                "created_at desc nulls_first default",
            ],
        )
        self.assertTrue(proposal["proposed_sql"].startswith("CREATE INDEX "))
        self.assertEqual(len(proposal["proposed_sql_sha256"]), 64)
        self.assertEqual(len(proposal["proposed_fingerprint"]), 64)
        self.assertEqual(proposal["statement_timeout"], "5min")
        self.assertEqual(proposal["lock_timeout"], "5s")
        with psycopg.connect(
            LIVE_CAPTURE_DATABASE_URL,
            row_factory=dict_row,
            autocommit=True,
        ) as connection:
            row = connection.execute(
                """
                SELECT to_regclass(
                  'workbench_lab.idx_orders_priority_tier_created_at'
                ) AS index_name
                """
            ).fetchone()
        self.assertIsNone(row["index_name"], "the proposal must not execute DDL")

    def test_the_proposal_cites_only_validated_citations(self) -> None:
        proposal = self._require_proposal()
        with psycopg.connect(
            LIVE_CAPTURE_DATABASE_URL,
            row_factory=dict_row,
            autocommit=True,
        ) as connection:
            row = connection.execute(
                """
                SELECT
                  count(*) AS cited,
                  count(*) FILTER (WHERE validation.is_valid) AS valid
                FROM proof.action_proposal_citations proposal_citation
                LEFT JOIN LATERAL proof.validate_answer_citations(
                  proposal_citation.run_id
                ) validation
                  ON validation.citation_number =
                     proposal_citation.citation_number
                WHERE proposal_citation.proposal_id = %s::uuid
                """,
                (proposal["proposal_id"],),
            ).fetchone()
        self.assertGreater(row["cited"], 0, "a proposal with no citations is ineligible")
        self.assertEqual(row["valid"], row["cited"])

    def test_the_fresh_proposal_is_pre_execution_eligible(self) -> None:
        proposal = self._require_proposal()
        with psycopg.connect(
            LIVE_CAPTURE_DATABASE_URL,
            row_factory=dict_row,
            autocommit=True,
        ) as connection:
            verdict = connection.execute(
                """
                SELECT *
                FROM proof.autonomy_readiness(%s::uuid)
                """,
                (proposal["proposal_id"],),
            ).fetchone()
        self.assertTrue(
            verdict["pre_execution_eligible"],
            f"ineligible: {verdict['pre_execution_reasons']}",
        )
        self.assertFalse(verdict["post_execution_validated"])
        self.assertEqual(
            verdict["post_execution_reasons"],
            ["no execution has been recorded yet"],
        )

    def test_strands_tool_synthesis_writes_no_proposal(self) -> None:
        """The non-canonical synthesis path has no proof.agent_runs parent.

        Lab 3 uses answer_question(), which writes the supervised proposal. The
        direct synthesis tool remains read/synthesis-only: an unguarded proposal
        insert here would either create false attribution or fail its NOT NULL
        agent_run_id foreign key and turn the Strands path into a 500.
        """
        from backend.app import agent_tools
        from backend.app.agent import (
            decompose_question_impl,
            search_evidence_impl,
        )
        from backend.app.config import get_settings

        before = self._proposal_count()
        original_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = str(LIVE_CAPTURE_DATABASE_URL)
        get_settings.cache_clear()
        try:
            plan = decompose_question_impl(self.question)
            run_ids = [
                search_evidence_impl(
                    subquestion["text"],
                    incident_id=self.capture["incident_id"],
                    source_systems=["pg_incident_capture"],
                    limit=8,
                    rerank=False,
                )["run_id"]
                for subquestion in plan["subquestions"]
            ]
            agent_tools.start_run("app_engineer", ["pg_incident_capture"])
            result = agent_tools.synthesize_cited_answer(self.question, run_ids)
        finally:
            if original_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = original_database_url
            get_settings.cache_clear()

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["answer"])
        self.assertEqual(
            self._proposal_count(),
            before,
            "direct/Strands synthesis must not write a supervised proposal",
        )

    def _proposal_count(self) -> int:
        with psycopg.connect(
            LIVE_CAPTURE_DATABASE_URL,
            row_factory=dict_row,
            autocommit=True,
        ) as connection:
            row = connection.execute(
                "SELECT count(*) AS count FROM proof.action_proposals"
            ).fetchone()
        return int(row["count"])

    def _require_proposal(self) -> dict:
        self.assertIsNotNone(self.proposal, "the answer path wrote no proposal")
        assert self.proposal is not None
        return self.proposal


if __name__ == "__main__":
    unittest.main()
