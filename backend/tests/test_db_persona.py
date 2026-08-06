"""The persona contract on the connection checkout.

These tests need a live database because the whole point is that Postgres, not
Python, is the enforcement point. They are skipped without TEST_DATABASE_URL,
matching backend/tests/test_retrieval_integration.py.
"""

from __future__ import annotations

import os
import unittest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
SECURITY_ENABLED = os.environ.get("WORKBENCH_SECURITY_ENABLED") == "1"
SECURITY_DATABASE_TESTS = bool(TEST_DATABASE_URL and SECURITY_ENABLED)
if SECURITY_DATABASE_TESTS:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ["WORKSHOP_APP_DATABASE_URL"] = TEST_DATABASE_URL

from backend.app import db


class PersonaContractTests(unittest.TestCase):
    """Pure-Python persona contract checks; no database required."""

    def test_personas_are_the_three_bound_values(self) -> None:
        self.assertEqual(db.PERSONAS, ("app_engineer", "auditor", "dba"))

    def test_persona_role_prefixes_the_database_role(self) -> None:
        self.assertEqual(db.persona_role("app_engineer"), "persona_app_engineer")
        self.assertEqual(db.persona_role("dba"), "persona_dba")
        self.assertEqual(db.persona_role("auditor"), "persona_auditor")

    def test_persona_role_rejects_an_unknown_persona(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown persona"):
            db.persona_role("support-lead")

    def test_get_conn_requires_a_persona(self) -> None:
        with self.assertRaises(TypeError):
            with db.get_conn():  # type: ignore[call-arg]
                pass


@unittest.skipUnless(
    SECURITY_DATABASE_TESTS,
    "set TEST_DATABASE_URL and WORKBENCH_SECURITY_ENABLED=1 for persona checkout",
)
class PersonaCheckoutTests(unittest.TestCase):
    def test_checkout_runs_as_the_persona_not_the_login(self) -> None:
        with db.get_dict_conn("app_engineer") as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_user AS role")
                self.assertEqual(cursor.fetchone()["role"], "persona_app_engineer")

    def test_role_does_not_leak_to_the_next_checkout(self) -> None:
        with db.get_dict_conn("dba") as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_user AS role")
                self.assertEqual(cursor.fetchone()["role"], "persona_dba")

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
                    {"persona_app_engineer", "persona_dba", "persona_auditor"},
                )


CONTENT_VIEWS = (
    "evidence.v_evidence_documents",
    "retrieval.evidence_edges",
    "proof.v_run_receipts",
    "proof.v_answer_receipts",
    "proof.v_candidate_receipts",
    "proof.v_evaluation_results",
    "proof.v_traversal_evaluation_results",
)

EVIDENCE_CONTENT_VIEWS = (
    "evidence.v_evidence_documents",
    "retrieval.evidence_edges",
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

# The restricted cohort, resolved from the database rather than written down.
#
# Every external_key in a live corpus carries the capture suffix of the run that
# produced it -- the cohort measured while writing these tests was
# TEL-478FD535-P02/-P03/-P04/-P05/-P07, from capture CAP-478FD535. A literal key
# would pass once and then fail on every subsequent `make live-workshop`, so the
# tests below ask the owner which rows are restricted and probe those.
#
# Read as the OWNER on purpose. retrieval_admin holds can_see_restricted and is
# subject to its own FORCEd policy, so it reads the whole corpus -- an oracle,
# rather than a persona restating the fact under test. A persona-run subquery is
# itself RLS-filtered, so a zero from it cannot distinguish "no such row" from "a
# row you may not see".
_RESTRICTED_KEYS_SQL = """
SELECT external_key
  FROM evidence.evidence_items
 WHERE acl ->> 'visibility' = 'restricted'
   AND NOT is_deleted
 ORDER BY external_key
"""


def _restricted_keys() -> list[str]:
    """Return the restricted external keys, as measured by the owner."""
    with db.get_owner_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(_RESTRICTED_KEYS_SQL)
            return [row[0] for row in cursor.fetchall()]


@unittest.skipUnless(
    SECURITY_DATABASE_TESTS,
    "set TEST_DATABASE_URL and WORKBENCH_SECURITY_ENABLED=1 for view RLS checks",
)
class ContentViewRlsTests(unittest.TestCase):
    def test_content_views_are_security_invoker(self) -> None:
        """A view that returns evidence text must be subject to the caller's RLS."""
        with db.get_dict_conn("app_engineer") as conn:
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
        with db.get_dict_conn("app_engineer") as conn:
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
        with db.get_dict_conn("app_engineer") as conn:
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
    SECURITY_DATABASE_TESTS,
    "set TEST_DATABASE_URL and WORKBENCH_SECURITY_ENABLED=1 for row filtering",
)
class ContentViewRowFilteringTests(unittest.TestCase):
    """Row counts, not reloptions.

    ContentViewRlsTests above asserts the security_invoker flag is set. That flag
    is necessary and not sufficient, and the gap between the two is where the real
    defect lived: a nested view whose inner relation was security_invoker while the
    outer one was not, and later a security_invoker view over base tables that had
    RLS disabled -- where invoker rights are a no-op. Both passed the reloptions
    test and leaked rows. These tests read what a persona can actually count.

    ``persona_dba`` is the high-water mark rather than the table owner: dba
    holds can_see_restricted, so its count is the unfiltered one, and using it
    keeps these tests off get_owner_conn() -- which connects with DATABASE_URL and
    would reach the live cluster in a shell where only TEST_DATABASE_URL is set.
    """

    def test_content_views_filter_rows_for_the_app_engineer(self) -> None:
        """At least one content view must demonstrably hide rows from the app_engineer.

        Proof views are deliberately excluded here: proof rows use exact-persona
        isolation, so one persona can legitimately have more runs than another.
        ProofAuthorizationTests exercises those views with named run IDs.
        """
        filtered = []
        for qualified in EVIDENCE_CONTENT_VIEWS:
            with self.subTest(view=qualified):
                app_engineer = _count_as("app_engineer", qualified)
                dba = _count_as("dba", qualified)
                self.assertLessEqual(
                    app_engineer,
                    dba,
                    f"{qualified}: persona_app_engineer counted {app_engineer} rows and "
                    f"persona_dba counted {dba}. The app_engineer holds no "
                    f"clearance, so it can never out-read dba -- this view is "
                    f"either running with owner rights or its policy grants the "
                    f"wrong direction",
                )
                if app_engineer < dba:
                    filtered.append(f"{qualified} ({app_engineer} < {dba})")
        self.assertTrue(
            filtered,
            "no content view hid a single row from persona_app_engineer, so this test "
            "proved nothing. Either RLS is not enforcing or the database holds no "
            "restricted evidence -- re-run the lab so the capture builds a "
            "restricted cohort, then rebuild the search index",
        )

    def test_the_restricted_cohort_is_invisible_to_the_app_engineer(self) -> None:
        """Named rows, so the previous test cannot pass on an unrelated diff.

        This reads evidence.v_evidence_documents as the auditor, which used to
        restart the entire Aurora instance: the view joins
        evidence.telemetry_evidence, and a masked role joining a masked table
        segfaults the backend on pg_columnmask 1.1.0. sql/12_masking.sql no longer
        masks that table (it protected nothing -- the same statements are readable
        in the deliberately-unmasked chunk corpus), and G-29's MUST_NOT_BE_MASKED
        keeps it that way. If a mask is ever re-added there, this test takes the
        cluster down rather than failing.
        """
        keys = _restricted_keys()
        self.assertTrue(
            keys,
            "no evidence row is marked restricted, so the app_engineer assertion "
            "below would hold over an empty cohort. Re-run the lab: the capture "
            "must build restricted telemetry evidence for any of this to mean anything",
        )
        sql = (
            "SELECT count(*) AS n FROM evidence.v_evidence_documents "
            "WHERE external_key = ANY(%s)"
        )
        counts = {}
        for persona in ("app_engineer", "dba", "auditor"):
            with db.get_dict_conn(persona) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, (keys,))
                    counts[persona] = cursor.fetchone()["n"]
        self.assertEqual(
            counts["dba"],
            len(keys),
            f"persona_dba read {counts['dba']} of the {len(keys)} restricted rows "
            f"the owner resolved ({', '.join(keys)}). The app_engineer assertion "
            f"below would hold over rows that are simply absent from the view",
        )
        self.assertEqual(
            counts["app_engineer"],
            0,
            f"persona_app_engineer read {counts['app_engineer']} restricted row(s) "
            f"out of evidence.v_evidence_documents",
        )
        self.assertEqual(
            counts["auditor"],
            counts["dba"],
            "persona_auditor holds the same clearance as persona_dba, so it must "
            "reach the same rows; the two differ only in column masking, and "
            "evidence.telemetry_evidence behind this view is masked for neither",
        )

    def test_count_only_views_do_not_differ_across_personas(self) -> None:
        """The C2 catcher.

        These four are owner-rights on purpose so the health surfaces report the
        true corpus. The defect this catches: one of them selected from a nested
        security_invoker view, which re-applied the caller's RLS through the back
        door -- an app_engineer saw a lower drift count than the owner and the panel
        silently under-reported. The reloptions test above cannot see that,
        because the outer view's own flag was correctly false.
        """
        for qualified in COUNT_ONLY_VIEWS:
            with self.subTest(view=qualified):
                counts = {
                    persona: _count_as(persona, qualified)
                    for persona in ("app_engineer", "dba", "auditor")
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
