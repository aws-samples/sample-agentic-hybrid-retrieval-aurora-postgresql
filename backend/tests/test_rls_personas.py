"""End-to-end persona enforcement: row filtering, masking, and fail-closed.

Every other test in this repo proves retrieval behaviour. This one proves the
enforcement claim the workshop makes out loud -- that the database refuses, not the
application -- and it proves it through the same connection path a request uses
(``db.get_dict_conn``), not through a hand-rolled psql session.

Requires a cluster where sql/11_roles_rls.sql has been applied and the persona
roles exist. Masking coverage additionally requires pg_columnmask, so those
assertions live in their own class and skip where the extension is absent rather
than failing a local run.
"""

from __future__ import annotations

import os
import unittest

import psycopg

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from backend.app import db

RESTRICTED_KEYS = (
    "CASE-7421",
    "CASE-8102",
    "CASE-8137",
    "CHG-3309",
    "CHG-6213",
    "INC-3162",
    "INC-4117",
)


def _roles_exist() -> bool:
    """True when the persona roles and the clearance role are on the cluster."""
    if not TEST_DATABASE_URL:
        return False
    try:
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_roles WHERE rolname = ANY(%s)",
                [["persona_analyst", "persona_admin", "persona_auditor",
                  "can_see_restricted"]],
            )
            return cursor.fetchone()[0] == 4
    except (psycopg.OperationalError, RuntimeError):
        return False


def _extension_available(name: str) -> bool:
    """True when the cluster has ``name`` installed (not merely available).

    Guarded on TEST_DATABASE_URL like _roles_exist(): backend.app.config calls
    load_dotenv(override=False), so an unset TEST_DATABASE_URL would otherwise let
    get_owner_conn() silently resolve DATABASE_URL from .env -- the live Aurora
    credential -- and open a connection to production at import time.
    """
    if not TEST_DATABASE_URL:
        return False
    try:
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_extension WHERE extname = %s", [name]
            )
            return cursor.fetchone()[0] == 1
    except (
        psycopg.OperationalError,
        RuntimeError,
        psycopg.errors.InsufficientPrivilege,
    ):
        return False


ROLES_PRESENT = _roles_exist()
COLUMNMASK_PRESENT = ROLES_PRESENT and _extension_available("pg_columnmask")


@unittest.skipUnless(
    ROLES_PRESENT,
    "apply sql/11_roles_rls.sql to TEST_DATABASE_URL for persona enforcement tests",
)
class RowFilteringTests(unittest.TestCase):
    """RLS decides which rows exist for a persona."""

    def _restricted_count(self, persona: str) -> int:
        with db.get_dict_conn(persona) as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)::int AS n
                  FROM retrieval.documents
                 WHERE is_current AND acl_visibility = 'restricted'
                """
            )
            return cursor.fetchone()["n"]

    def test_analyst_sees_no_restricted_documents(self) -> None:
        self.assertEqual(self._restricted_count("analyst"), 0)

    def test_admin_and_auditor_see_the_restricted_cohort(self) -> None:
        for persona in ("admin", "auditor"):
            with self.subTest(persona=persona):
                self.assertEqual(self._restricted_count(persona), len(RESTRICTED_KEYS))

    def test_workshop_rows_are_visible_to_every_persona(self) -> None:
        counts = {}
        for persona in db.PERSONAS:
            with db.get_dict_conn(persona) as conn, conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT count(*)::int AS n
                      FROM retrieval.documents
                     WHERE is_current AND acl_visibility = 'workshop'
                    """
                )
                counts[persona] = cursor.fetchone()["n"]
        self.assertGreater(counts["analyst"], 0, "no workshop rows: corpus not seeded")
        self.assertEqual(len(set(counts.values())), 1, counts)

    def test_chunks_are_filtered_too_not_just_documents(self) -> None:
        """The vector arm reads retrieval.chunks standalone; a documents-only
        policy would leak restricted body text through it."""
        for persona, expect_zero in (("analyst", True), ("admin", False)):
            with self.subTest(persona=persona):
                with db.get_dict_conn(persona) as conn, conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT count(*)::int AS n
                          FROM retrieval.chunks
                         WHERE is_current AND acl_visibility = 'restricted'
                        """
                    )
                    n = cursor.fetchone()["n"]
                self.assertEqual(n == 0, expect_zero, f"{persona} saw {n}")

    def test_casework_evidence_is_filtered_by_the_jsonb_form(self) -> None:
        """casework carries visibility in acl->>'visibility', not a scalar column.
        Both predicate forms must agree or the two layers disagree on one row."""
        with db.get_dict_conn("analyst") as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT count(*)::int AS n FROM casework.evidence_items "
                "WHERE external_key = ANY(%s)",
                [list(RESTRICTED_KEYS)],
            )
            self.assertEqual(cursor.fetchone()["n"], 0)

    def test_restricted_keys_are_absent_from_every_analyst_arm(self) -> None:
        """The enforcement claim is about retrieval, not just SELECT. Query each
        arm by the restricted identifier itself -- the strongest possible probe.

        The two arms take different parameter shapes, which is why this is a list of
        (statement, argument) pairs rather than one loop: the lexical arm is
        retrieval.full_text_search(p_query text, ...) and the fuzzy arm is
        retrieval.fuzzy_search(p_probe_tokens text[], ...). There is no
        retrieval.lexical_search.
        """
        arms = (
            ("full_text", "SELECT external_key FROM retrieval.full_text_search("
                          "%s, p_limit => 25)", lambda key: (key,)),
            ("fuzzy", "SELECT external_key FROM retrieval.fuzzy_search("
                      "%s::text[], p_limit => 25)", lambda key: ([key],)),
        )
        with db.get_dict_conn("analyst") as conn:
            for name, statement, params in arms:
                for key in RESTRICTED_KEYS:
                    with self.subTest(arm=name, key=key):
                        with conn.cursor() as cursor:
                            cursor.execute(statement, params(key))
                            found = [row["external_key"] for row in cursor.fetchall()]
                        self.assertNotIn(key, found)


@unittest.skipUnless(
    ROLES_PRESENT,
    "apply sql/11_roles_rls.sql to TEST_DATABASE_URL for persona enforcement tests",
)
class FailClosedTests(unittest.TestCase):
    """A forgotten SET LOCAL ROLE must deny, never return rows."""

    def test_the_pool_login_holds_no_read_grant(self) -> None:
        """The check that makes the whole design fail-closed. If workshop_app can
        read a table directly, a forgotten persona returns rows instead of raising,
        and every other assertion in this file is decorative."""
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT has_table_privilege('workshop_app', t, 'SELECT') AS granted, t
                  FROM unnest(ARRAY['casework.evidence_items',
                                    'retrieval.documents',
                                    'retrieval.chunks']) AS t
                """
            )
            for row in cursor.fetchall():
                with self.subTest(table=row[1]):
                    self.assertFalse(row[0], f"workshop_app can SELECT {row[1]}")

    def test_role_is_scoped_to_the_transaction(self) -> None:
        """SET LOCAL, not SET: a session-scoped role would leak to the next
        borrower of this pooled connection."""
        with db.get_dict_conn("admin") as conn, conn.cursor() as cursor:
            cursor.execute("SELECT current_user AS role")
            self.assertEqual(cursor.fetchone()["role"], "persona_admin")
        with db.get_dict_conn("analyst") as conn, conn.cursor() as cursor:
            cursor.execute("SELECT current_user AS role")
            self.assertEqual(cursor.fetchone()["role"], "persona_analyst")

    def test_clearance_is_withheld_from_the_analyst_not_marked_on_it(self) -> None:
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            for persona, expected in (
                ("persona_analyst", False),
                ("persona_admin", True),
                ("persona_auditor", True),
            ):
                with self.subTest(persona=persona):
                    cursor.execute(
                        "SELECT pg_has_role(%s, 'can_see_restricted', 'USAGE')",
                        [persona],
                    )
                    self.assertEqual(cursor.fetchone()[0], expected)

    def test_rls_is_enabled_and_forced_on_all_three_read_path_tables(self) -> None:
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT n.nspname || '.' || c.relname AS tbl,
                       c.relrowsecurity, c.relforcerowsecurity
                  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname || '.' || c.relname = ANY(%s)
                """,
                [["casework.evidence_items", "retrieval.documents", "retrieval.chunks"]],
            )
            rows = cursor.fetchall()
        self.assertEqual(len(rows), 3, rows)
        for tbl, enabled, forced in rows:
            with self.subTest(table=tbl):
                self.assertTrue(enabled, f"{tbl}: RLS not enabled")
                self.assertTrue(forced, f"{tbl}: RLS not forced; the owner is unfiltered")


@unittest.skipUnless(
    COLUMNMASK_PRESENT,
    "pg_columnmask is Aurora-managed; run against Aurora to cover masking",
)
class ColumnMaskingTests(unittest.TestCase):
    """Masking decides which columns a visible row shows.

    Unverified locally: pg_columnmask cannot be installed on local PostgreSQL, so
    this whole class is skipped on every local run and every assertion below is
    unexecuted here. Run this suite against a disposable Aurora database to cover
    it; do not read a local `OK` as coverage of masking.
    """

    def _case_row(self, persona: str) -> dict:
        with db.get_dict_conn(persona) as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT case_id, account_name, customer_commitment
                  FROM casework.support_cases WHERE case_id = %s
                """,
                ["CASE-7421"],
            )
            return cursor.fetchone()

    def test_admin_reads_the_restricted_case_unmasked(self) -> None:
        row = self._case_row("admin")
        self.assertIsNotNone(row, "CASE-7421 missing: corpus not seeded")
        self.assertNotIn("REDACTED", row["customer_commitment"])

    def test_auditor_reads_the_same_row_with_identity_redacted(self) -> None:
        """account_name is bound to pgcolumnmask.mask_text, not mask_redact, so its
        exact masked literal (width, character set) is a fact about the Aurora
        extension's implementation that this suite cannot measure locally. Assert
        only that none of the real value's characters survive, not a literal."""
        admin_row = self._case_row("admin")
        auditor_row = self._case_row("auditor")
        self.assertIsNotNone(auditor_row, "auditor cannot see CASE-7421 at all")
        self.assertEqual(auditor_row["case_id"], admin_row["case_id"])
        self.assertEqual(auditor_row["customer_commitment"], "[REDACTED]")
        real_account_name = admin_row["account_name"]
        masked_account_name = auditor_row["account_name"]
        self.assertTrue(
            all(ch not in masked_account_name for ch in set(real_account_name)),
            f"masked account_name {masked_account_name!r} still contains a "
            f"character from the real value {real_account_name!r}",
        )

    def test_no_sensitive_literal_survives_anywhere_in_the_auditor_corpus(self) -> None:
        """The leak scan. Masking one column is easy; the claim here is narrower
        than corpus-wide: retrieval.sensitive_literals() (sql/12_masking.sql)
        reads casework.support_cases only (account_name, customer_commitment,
        description of restricted cases). The restricted cohort also spans
        casework.incidents (INC-3162, INC-4117) and casework.changes (CHG-6213,
        CHG-3309), whose prose feeds chunk_text and contributes no literal to this
        scan. See design doc open item 7 for corpus-wide coverage."""
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT literal FROM retrieval.sensitive_literals()")
            literals = [row[0] for row in cursor.fetchall()]
        self.assertGreater(len(literals), 0, "no sensitive literals: mask is a no-op")

        with db.get_dict_conn("auditor") as conn:
            for literal in literals:
                with self.subTest(literal=literal[:40]):
                    with conn.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT count(*)::int AS n FROM retrieval.chunks
                             WHERE is_current AND chunk_text LIKE '%%' || %s || '%%'
                            """,
                            [literal],
                        )
                        self.assertEqual(cursor.fetchone()["n"], 0)

    def test_masking_is_deterministic_between_the_app_path_and_the_verify_sql(self) -> None:
        """Law 2: the value in the panel and the value in a pasted verify-SQL must
        be byte-identical. Two reads through get_dict_conn() over an IMMUTABLE mask
        are trivially equal and prove nothing about Law 2 -- this instead compares
        the app-path read against the same SELECT run inside the A3 verify-SQL
        envelope (BEGIN; SET LOCAL ROLE persona_auditor; <SELECT>; ROLLBACK;) on a
        separate connection, which is the actual claim being tested."""
        app_row = self._case_row("auditor")
        with db.get_owner_conn(row_factory=None) as conn, conn.cursor() as cursor:
            cursor.execute("BEGIN")
            try:
                cursor.execute("SET LOCAL ROLE persona_auditor")
                cursor.execute(
                    """
                    SELECT case_id, account_name, customer_commitment
                      FROM casework.support_cases WHERE case_id = %s
                    """,
                    ["CASE-7421"],
                )
                verify_sql_row = cursor.fetchone()
            finally:
                cursor.execute("ROLLBACK")
        self.assertEqual(
            (app_row["case_id"], app_row["account_name"], app_row["customer_commitment"]),
            verify_sql_row,
        )


if __name__ == "__main__":
    unittest.main()
