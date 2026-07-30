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
