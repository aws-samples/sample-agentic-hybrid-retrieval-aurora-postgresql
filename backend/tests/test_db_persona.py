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

# The restricted noun seed/corpus.py pins into the cohort, matching
# gates/rls_enforcement.py's CANONICAL_RESTRICTED_KEY. Named so a row-count test
# cannot pass on some unrelated difference between two personas.
CANONICAL_RESTRICTED_KEY = "CASE-7421"

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


def _count_as(persona: str, qualified: str) -> int:
    """Return how many rows of ``qualified`` ``persona`` can read."""
    with db.get_dict_conn(persona) as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT count(*) AS n FROM {qualified}")
            return cursor.fetchone()["n"]


@unittest.skipUnless(
    os.environ.get("TEST_DATABASE_URL"),
    "set TEST_DATABASE_URL for the row-filtering contract",
)
class ContentViewRowFilteringTests(unittest.TestCase):
    """Row counts, not reloptions.

    ContentViewRlsTests above asserts the security_invoker flag is set. That flag
    is necessary and not sufficient, and the gap between the two is where the real
    defect lived: a nested view whose inner relation was security_invoker while the
    outer one was not, and later a security_invoker view over base tables that had
    RLS disabled -- where invoker rights are a no-op. Both passed the reloptions
    test and leaked rows. These tests read what a persona can actually count.

    ``persona_admin`` is the high-water mark rather than the table owner: admin
    holds can_see_restricted, so its count is the unfiltered one, and using it
    keeps these tests off get_owner_conn() -- which connects with DATABASE_URL and
    would reach the live cluster in a shell where only TEST_DATABASE_URL is set.
    """

    def test_content_views_filter_rows_for_the_analyst(self) -> None:
        """At least one content view must demonstrably hide rows from the analyst.

        Per-view equality is not asserted, because whether a given view holds
        restricted rows is a property of the seeded cohort, not of RLS: the four
        proof.* views are empty until an agent run is recorded, and asserting
        "analyst sees fewer" there would fail for a reason unrelated to RLS. What
        IS asserted on every view is the direction -- the analyst can never see
        MORE than admin -- plus the fixture-level requirement that the cohort
        proved the mechanism somewhere. Without that second assertion the whole
        test passes vacuously on an empty database, which is worse than no test.
        """
        filtered = []
        for qualified in CONTENT_VIEWS:
            with self.subTest(view=qualified):
                analyst = _count_as("analyst", qualified)
                admin = _count_as("admin", qualified)
                self.assertLessEqual(
                    analyst,
                    admin,
                    f"{qualified}: persona_analyst counted {analyst} rows and "
                    f"persona_admin counted {admin}. The analyst holds no "
                    f"clearance, so it can never out-read admin -- this view is "
                    f"either running with owner rights or its policy grants the "
                    f"wrong direction",
                )
                if analyst < admin:
                    filtered.append(f"{qualified} ({analyst} < {admin})")
        self.assertTrue(
            filtered,
            "no content view hid a single row from persona_analyst, so this test "
            "proved nothing. Either RLS is not enforcing or the database holds no "
            "restricted evidence -- reseed with seed/corpus.py's RESTRICTED_ACL "
            "cohort and rebuild the search index",
        )

    def test_the_canonical_restricted_row_is_invisible_to_the_analyst(self) -> None:
        """A named row, so the previous test cannot pass on an unrelated diff."""
        sql = (
            "SELECT count(*) AS n FROM casework.v_evidence_documents "
            "WHERE external_key = %s"
        )
        counts = {}
        for persona in ("analyst", "admin", "auditor"):
            with db.get_dict_conn(persona) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, (CANONICAL_RESTRICTED_KEY,))
                    counts[persona] = cursor.fetchone()["n"]
        self.assertGreater(
            counts["admin"],
            0,
            f"persona_admin cannot see {CANONICAL_RESTRICTED_KEY}, which "
            f"seed/corpus.py pins into the restricted cohort. The analyst "
            f"assertion below would hold over a row that is simply absent",
        )
        self.assertEqual(
            counts["analyst"],
            0,
            f"persona_analyst read {CANONICAL_RESTRICTED_KEY} out of "
            f"casework.v_evidence_documents",
        )
        self.assertEqual(
            counts["auditor"],
            counts["admin"],
            "persona_auditor holds the same clearance as persona_admin and "
            "differs only in column masking; the row must be present for the "
            "mask to apply to",
        )

    def test_count_only_views_do_not_differ_across_personas(self) -> None:
        """The C2 catcher.

        These four are owner-rights on purpose so the health surfaces report the
        true corpus. The defect this catches: one of them selected from a nested
        security_invoker view, which re-applied the caller's RLS through the back
        door -- an analyst saw a lower drift count than the owner and the panel
        silently under-reported. The reloptions test above cannot see that,
        because the outer view's own flag was correctly false.
        """
        for qualified in COUNT_ONLY_VIEWS:
            with self.subTest(view=qualified):
                counts = {
                    persona: _count_as(persona, qualified)
                    for persona in ("analyst", "admin", "auditor")
                }
                self.assertEqual(
                    len(set(counts.values())),
                    1,
                    f"{qualified} returned different row counts per persona: "
                    f"{counts}. This view is documented as counting every row "
                    f"regardless of clearance, so either it or something it "
                    f"selects from is now subject to the caller's RLS. Check for "
                    f"a nested security_invoker relation in its definition",
                )


class PersonaLiteralAgreementTests(unittest.TestCase):
    def test_the_two_persona_literals_agree(self) -> None:
        """models.Persona and db.PERSONAS are declared separately; keep them equal."""
        from typing import get_args

        from backend.app.models import Persona

        self.assertEqual(get_args(Persona), db.PERSONAS)


if __name__ == "__main__":
    unittest.main()
