"""The persona contract on the connection checkout.

These tests need a live database because the whole point is that Postgres, not
Python, is the enforcement point. They are skipped without TEST_DATABASE_URL,
matching backend/tests/test_retrieval_integration.py.
"""

from __future__ import annotations

import os
import unittest

from backend.app import db


class PersonaContractTests(unittest.TestCase):
    """Pure-Python persona contract checks; no database required."""

    def test_personas_are_the_three_bound_values(self) -> None:
        self.assertEqual(db.PERSONAS, ("analyst", "admin", "auditor"))

    def test_persona_role_prefixes_the_database_role(self) -> None:
        self.assertEqual(db.persona_role("analyst"), "persona_analyst")
        self.assertEqual(db.persona_role("admin"), "persona_admin")
        self.assertEqual(db.persona_role("auditor"), "persona_auditor")

    def test_persona_role_rejects_an_unknown_persona(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown persona"):
            db.persona_role("support-lead")

    def test_get_conn_requires_a_persona(self) -> None:
        with self.assertRaises(TypeError):
            with db.get_conn():  # type: ignore[call-arg]
                pass


@unittest.skipUnless(
    os.environ.get("TEST_DATABASE_URL"),
    "set TEST_DATABASE_URL for the persona checkout contract",
)
class PersonaCheckoutTests(unittest.TestCase):
    def test_checkout_runs_as_the_persona_not_the_login(self) -> None:
        with db.get_dict_conn("analyst") as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_user AS role")
                self.assertEqual(cursor.fetchone()["role"], "persona_analyst")

    def test_role_does_not_leak_to_the_next_checkout(self) -> None:
        with db.get_dict_conn("admin") as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_user AS role")
                self.assertEqual(cursor.fetchone()["role"], "persona_admin")

        with db.get_dict_conn("auditor") as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_user AS role")
                self.assertEqual(cursor.fetchone()["role"], "persona_auditor")

    def test_owner_checkout_is_not_a_persona(self) -> None:
        with db.get_owner_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_user AS role")
                self.assertNotIn(
                    cursor.fetchone()[0],
                    {"persona_analyst", "persona_admin", "persona_auditor"},
                )


CONTENT_VIEWS = (
    "casework.v_evidence_documents",
    "retrieval.evidence_edges",
    "proof.v_answer_receipts",
    "proof.v_candidate_receipts",
    "proof.v_evaluation_results",
    "proof.v_traversal_evaluation_results",
)

# Counted, never content: these read the read-path tables as the owner on purpose,
# so /ready and the corpus panels report the true row counts for every persona.
COUNT_ONLY_VIEWS = (
    "retrieval.v_search_index_health",
    "retrieval.v_search_index_drift",
    "retrieval.v_corpus_distribution",
    "retrieval.v_embedding_spaces",
)

_RELOPTIONS_SQL = """
SELECT 'security_invoker=true' = ANY(coalesce(c.reloptions, '{}')) AS invoker
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND c.relname = %s
"""


@unittest.skipUnless(
    os.environ.get("TEST_DATABASE_URL"),
    "set TEST_DATABASE_URL for the view security_invoker contract",
)
class ContentViewRlsTests(unittest.TestCase):
    def test_content_views_are_security_invoker(self) -> None:
        """A view that returns evidence text must be subject to the caller's RLS."""
        with db.get_dict_conn("analyst") as conn:
            with conn.cursor() as cursor:
                for qualified in CONTENT_VIEWS:
                    with self.subTest(view=qualified):
                        schema, name = qualified.split(".")
                        cursor.execute(_RELOPTIONS_SQL, (schema, name))
                        row = cursor.fetchone()
                        self.assertIsNotNone(row, f"{qualified} does not exist")
                        self.assertTrue(
                            row["invoker"],
                            f"{qualified} runs with owner rights and leaks "
                            f"restricted rows",
                        )

    def test_count_only_views_are_deliberately_owner_rights(self) -> None:
        """The health surfaces count every row on purpose; assert that stays true."""
        with db.get_dict_conn("analyst") as conn:
            with conn.cursor() as cursor:
                for qualified in COUNT_ONLY_VIEWS:
                    with self.subTest(view=qualified):
                        schema, name = qualified.split(".")
                        cursor.execute(_RELOPTIONS_SQL, (schema, name))
                        self.assertFalse(
                            cursor.fetchone()["invoker"],
                            f"{qualified} became security_invoker; if that is "
                            "intended, its counts now differ per persona - update "
                            "the G-29 exclusion list and the health-surface honesty "
                            "claim first",
                        )

    def test_the_dropped_chunk_view_is_gone(self) -> None:
        with db.get_dict_conn("analyst") as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT to_regclass('retrieval.v_current_chunks') AS oid")
                self.assertIsNone(cursor.fetchone()["oid"])


class PersonaLiteralAgreementTests(unittest.TestCase):
    def test_the_two_persona_literals_agree(self) -> None:
        """models.Persona and db.PERSONAS are declared separately; keep them equal."""
        from typing import get_args

        from backend.app.models import Persona

        self.assertEqual(get_args(Persona), db.PERSONAS)


if __name__ == "__main__":
    unittest.main()
