"""Adversarial tests for G-34's structural and behavioral halves."""

from __future__ import annotations

import os
import unittest

import psycopg

from gates.retroactive_safety import (
    CONTRADICTION_SCAN,
    FunctionSource,
    inspect_static,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def _function(
    oid: int,
    schema: str,
    name: str,
    source: str,
    arguments: str = "p_id uuid",
) -> FunctionSource:
    return FunctionSource(oid, schema, name, arguments, source)


HELPER = _function(
    2,
    "proof",
    "validate_answer_citations",
    "BEGIN RETURN QUERY SELECT 1; END",
    "p_run_id uuid",
)

CLEAN_BODY = """
DECLARE
  v_pre text[] := '{}';
BEGIN
  v_pre := v_pre || 'checked'::text;
  v_pre := v_pre || CASE
    WHEN EXISTS (
      SELECT 1 FROM proof.validate_answer_citations(p_id)
    ) THEN '{}'::text[] ELSE '{}'::text[] END;
  RETURN QUERY SELECT
    (array_length(v_pre, 1) IS NULL), v_pre, false, '{}'::text[];
END
"""


def _subject(source: str = CLEAN_BODY) -> FunctionSource:
    return _function(1, "proof", "autonomy_readiness", source)


class StaticGateTests(unittest.TestCase):
    def _problems(
        self,
        source: str = CLEAN_BODY,
        *helpers: FunctionSource,
    ) -> tuple[list[str], int, list[str]]:
        catalog = (HELPER, *helpers)
        return inspect_static(_subject(source), catalog)

    def test_shipped_shape_is_clean_and_walks_the_helper(self) -> None:
        problems, assignments, helpers = self._problems()
        self.assertEqual(problems, [])
        self.assertEqual(assignments, 2)
        self.assertEqual(
            helpers,
            ["proof.validate_answer_citations(p_run_id uuid)"],
        )

    def test_direct_pre_execution_read_is_rejected(self) -> None:
        source = CLEAN_BODY.replace(
            "v_pre := v_pre || 'checked'::text;",
            "SELECT * INTO v_exec FROM proof.action_executions LIMIT 1;\n"
            "  v_pre := v_pre || 'checked'::text;",
        )
        problems, _, _ = self._problems(source)
        self.assertTrue(any("pre-execution region reads" in item for item in problems))

    def test_helper_read_is_rejected_in_any_schema(self) -> None:
        helper = _function(
            3,
            "public",
            "sneaky_lookup",
            "BEGIN RETURN EXISTS (SELECT 1 FROM proof.action_executions); END",
        )
        source = CLEAN_BODY.replace(
            "v_pre := v_pre || 'checked'::text;",
            "v_pre := CASE WHEN public.sneaky_lookup(p_id) "
            "THEN '{}'::text[] ELSE v_pre END;",
        )
        problems, _, helpers = self._problems(source, helper)
        self.assertTrue(any("public.sneaky_lookup" in item for item in problems))
        self.assertIn("public.sneaky_lookup(p_id uuid)", helpers)

    def test_every_matching_overload_is_inspected(self) -> None:
        clean = _function(
            3,
            "public",
            "overloaded",
            "BEGIN RETURN true; END",
            "p_id uuid",
        )
        unsafe = _function(
            4,
            "public",
            "overloaded",
            "BEGIN RETURN EXISTS (SELECT 1 FROM proof.action_executions); END",
            "p_text text",
        )
        source = CLEAN_BODY.replace(
            "v_pre := v_pre || 'checked'::text;",
            "v_pre := CASE WHEN public.overloaded(p_id) "
            "THEN '{}'::text[] ELSE v_pre END;",
        )
        problems, _, helpers = self._problems(source, clean, unsafe)
        self.assertTrue(any("public.overloaded(p_text text)" in item for item in problems))
        self.assertEqual(
            [item for item in helpers if item.startswith("public.overloaded")],
            ["public.overloaded(p_id uuid)", "public.overloaded(p_text text)"],
        )

    def test_internal_comma_does_not_hide_returned_execution_read(self) -> None:
        source = CLEAN_BODY.replace(
            "(array_length(v_pre, 1) IS NULL)",
            "(array_length(v_pre, 1) IS NULL OR v_exec.fingerprint_matches)",
        )
        problems, _, _ = self._problems(source)
        self.assertTrue(
            any("returned eligibility expression reads" in item for item in problems)
        )

    def test_local_boolean_cannot_launder_an_execution_read(self) -> None:
        source = CLEAN_BODY.replace(
            "(array_length(v_pre, 1) IS NULL)",
            "(array_length(v_pre, 1) IS NULL OR v_flag)",
        )
        problems, _, _ = self._problems(source)
        self.assertTrue(any("non-allowlisted" in item for item in problems))

    def test_last_assignment_right_hand_side_is_scanned(self) -> None:
        source = CLEAN_BODY.replace(
            "v_pre := v_pre || CASE",
            "v_pre := CASE WHEN EXISTS (SELECT 1 FROM proof.action_executions) "
            "THEN '{}'::text[] ELSE v_pre END;\n"
            "  v_pre := v_pre || CASE",
        )
        problems, _, _ = self._problems(source)
        self.assertTrue(any("pre-execution region reads" in item for item in problems))

    def test_dynamic_sql_after_a_comment_like_literal_is_rejected(self) -> None:
        source = CLEAN_BODY.replace(
            "v_pre := v_pre || 'checked'::text;",
            "v_note := '-- not a comment';\n"
            "  EXECUTE v_sql INTO v_flag;\n"
            "  v_pre := v_pre || 'checked'::text;",
        )
        problems, _, _ = self._problems(source)
        self.assertTrue(any("dynamic SQL" in item for item in problems))

    def test_execution_token_inside_a_literal_is_rejected(self) -> None:
        source = CLEAN_BODY.replace(
            "v_pre := v_pre || 'checked'::text;",
            "v_note := 'proof.action_executions';\n"
            "  v_pre := v_pre || 'checked'::text;",
        )
        problems, _, _ = self._problems(source)
        self.assertTrue(any("string literal" in item for item in problems))

    def test_execution_tokens_in_comments_are_ignored(self) -> None:
        source = CLEAN_BODY.replace(
            "v_pre := v_pre || 'checked'::text;",
            "-- proof.action_executions fingerprint_matches\n"
            "  v_pre := v_pre || 'checked'::text;",
        )
        problems, _, _ = self._problems(source)
        self.assertEqual(problems, [])


@unittest.skipUnless(TEST_DATABASE_URL, "requires TEST_DATABASE_URL")
class BehavioralGateTests(unittest.TestCase):
    def test_contradiction_scan_goes_red_when_verdict_ignores_requirements(self) -> None:
        with psycopg.connect(TEST_DATABASE_URL) as connection:
            database = connection.execute("SELECT current_database()").fetchone()[0]
            if not database.endswith("_test"):
                raise RuntimeError(f"SAFETY ABORT: refusing to mutate {database}")

            run_id = connection.execute(
                """
                INSERT INTO proof.retrieval_runs(
                  query_text, retrieval_mode, rrf_k, text_weight,
                  vector_weight, fuzzy_weight
                )
                VALUES ('G-34 contradiction probe', 'hybrid', 60, 1, 1, 1)
                RETURNING run_id
                """
            ).fetchone()[0]
            agent_run_id = connection.execute(
                """
                INSERT INTO proof.agent_runs(
                  question, controls_initial, contract_version
                )
                VALUES ('G-34 contradiction probe', '{}'::jsonb, 'test')
                RETURNING agent_run_id
                """
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO proof.action_proposals(
                  agent_run_id, run_id, action_type, target_schema,
                  target_table, key_columns, proposed_fingerprint,
                  proposed_sql, proposed_sql_sha256, preconditions,
                  expected_effect
                )
                VALUES (
                  %s, %s, 'create_index', 'workbench_lab', 'orders',
                  ARRAY['priority_tier asc nulls_last default'],
                  'test-fingerprint', 'CREATE INDEX test_only',
                  'test-sql-sha256', '[]'::jsonb, 'test-only expected effect'
                )
                """,
                (agent_run_id, run_id),
            )
            connection.execute(
                """
                CREATE OR REPLACE FUNCTION proof.autonomy_readiness(p_proposal_id uuid)
                RETURNS TABLE (
                  pre_execution_eligible boolean,
                  pre_execution_reasons text[],
                  post_execution_validated boolean,
                  post_execution_reasons text[]
                )
                LANGUAGE sql STABLE AS $$
                  SELECT true, '{}'::text[], false,
                         ARRAY['test-only broken verdict']::text[]
                $$
                """
            )
            contradictions = connection.execute(CONTRADICTION_SCAN).fetchall()
            self.assertTrue(
                contradictions,
                "the behavioral half must find proposals made falsely eligible",
            )
            connection.rollback()


if __name__ == "__main__":
    unittest.main()
