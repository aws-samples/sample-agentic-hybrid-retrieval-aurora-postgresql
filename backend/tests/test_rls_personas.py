"""End-to-end persona enforcement: row filtering, masking, and fail-closed.

Every other test in this repo proves retrieval behaviour. This one proves the
enforcement claim the workshop makes out loud -- that the database refuses, not the
application -- and it proves it through the same connection path a request uses
(``db.get_dict_conn``), not through a hand-rolled psql session.

Requires a cluster where sql/11_roles_rls.sql has been applied and the persona
roles exist. Masking coverage additionally requires pg_columnmask, so those
assertions live in their own class and skip where the extension is absent rather
than failing a local run.

NOTHING HERE IS WRITTEN DOWN AS A LITERAL KEY. A live corpus names every row after
the capture that produced it (the cohort measured while writing this file was
TEL-478FD535-P02/-P03/-P04/-P05/-P07, from CAP-478FD535), so a pinned identifier
would pass once and fail on the next `make live-workshop`. The restricted cohort is
resolved from the owner at run time and every persona assertion is made against
that measured set.
"""

from __future__ import annotations

import os
import re
import unittest
from uuid import uuid4

import psycopg

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
SECURITY_ENABLED = os.environ.get("WORKBENCH_SECURITY_ENABLED") == "1"
SECURITY_DATABASE_TESTS = bool(TEST_DATABASE_URL and SECURITY_ENABLED)
if SECURITY_DATABASE_TESTS:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ["WORKSHOP_APP_DATABASE_URL"] = TEST_DATABASE_URL

from backend.app import db

READ_PATH_TABLES = (
    "casework.evidence_items",
    "retrieval.documents",
    "retrieval.chunks",
)


def _roles_exist() -> bool:
    """True when the persona roles and the clearance role are on the cluster."""
    if not SECURITY_DATABASE_TESTS:
        return False
    try:
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_roles WHERE rolname = ANY(%s)",
                [["persona_app_engineer", "persona_dba", "persona_auditor",
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
    if not SECURITY_DATABASE_TESTS:
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


def _restricted_keys() -> list[str]:
    """The restricted cohort, resolved as the owner.

    retrieval_admin holds can_see_restricted and is subject to its own FORCEd
    policy, so it reads the whole corpus (measured: 110 evidence rows, 5
    restricted) and its answer is an oracle rather than a persona restating the
    fact under test.
    """
    with db.get_owner_conn() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT external_key
              FROM casework.evidence_items
             WHERE acl ->> 'visibility' = 'restricted'
               AND NOT is_deleted
             ORDER BY external_key
            """
        )
        return [row[0] for row in cursor.fetchall()]


def _count_restricted(persona: str, table: str) -> int:
    """Count the restricted rows ``persona`` reads in ``table``.

    A bare single-table predicate on the same scalar the row policy tests -- never
    a join out to casework.evidence_items. A leak scan that reaches its target
    through a second protected table measures the OTHER table's protection: with
    retrieval.chunks' policy loosened to USING (true), the joined form still
    returned the filtered count while a bare SELECT handed over every restricted
    chunk. Same discipline as gates/rls_enforcement.py and G-29.
    """
    column = "acl ->> 'visibility'" if table.startswith("casework.") else "acl_visibility"
    current = "" if table == "casework.evidence_items" else "is_current AND "
    with db.get_dict_conn(persona) as conn, conn.cursor() as cursor:
        cursor.execute(
            f"SELECT count(*)::int AS n FROM {table} "
            f"WHERE {current}{column} = 'restricted'"
        )
        return cursor.fetchone()["n"]


@unittest.skipUnless(
    ROLES_PRESENT,
    "enable security mode and apply sql/11_roles_rls.sql to TEST_DATABASE_URL",
)
class RowFilteringTests(unittest.TestCase):
    """RLS decides which rows exist for a persona."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.restricted_keys = _restricted_keys()
        if not cls.restricted_keys:
            raise unittest.SkipTest(
                "no evidence row is marked restricted, so every assertion in this "
                "class would hold vacuously. Re-run the lab: the capture must "
                "build a restricted telemetry cohort"
            )

    def test_app_engineer_sees_no_restricted_rows_on_any_read_path_table(self) -> None:
        """All three tables, because the arms read them separately.

        The vector and fuzzy arms read retrieval.chunks standalone, so a policy on
        retrieval.documents alone would leak restricted body text through them.
        """
        for table in READ_PATH_TABLES:
            with self.subTest(table=table):
                self.assertEqual(_count_restricted("app_engineer", table), 0)

    def test_cleared_personas_see_the_restricted_cohort(self) -> None:
        expected = len(self.restricted_keys)
        for persona in ("dba", "auditor"):
            with self.subTest(persona=persona):
                self.assertEqual(
                    _count_restricted(persona, "casework.evidence_items"), expected
                )

    def test_cleared_personas_see_restricted_documents_and_chunks(self) -> None:
        """Counted separately from evidence: the derived tables version rows, so
        their restricted count is a property of the index build rather than of the
        cohort size, and pinning it to len(restricted_keys) would be wrong."""
        for table in ("retrieval.documents", "retrieval.chunks"):
            with self.subTest(table=table):
                dba = _count_restricted("dba", table)
                auditor = _count_restricted("auditor", table)
                self.assertGreater(
                    dba,
                    0,
                    f"{table} holds no restricted row, so the app_engineer "
                    f"assertion over it proves nothing -- rebuild the search index",
                )
                self.assertEqual(auditor, dba)

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
        self.assertGreater(counts["app_engineer"], 0, "no workshop rows: corpus not seeded")
        self.assertEqual(len(set(counts.values())), 1, counts)

    def test_casework_evidence_is_filtered_by_the_jsonb_form(self) -> None:
        """casework carries visibility in acl->>'visibility', not a scalar column.
        Both predicate forms must agree or the two layers disagree on one row."""
        with db.get_dict_conn("app_engineer") as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT count(*)::int AS n FROM casework.evidence_items "
                "WHERE external_key = ANY(%s)",
                [self.restricted_keys],
            )
            self.assertEqual(cursor.fetchone()["n"], 0)

    def test_restricted_keys_are_absent_from_every_app_engineer_arm(self) -> None:
        """The enforcement claim is about retrieval, not just SELECT. Query each arm
        by the restricted identifier itself -- the strongest possible probe.

        KEY SETS, not row counts, and the difference is load-bearing. Measured on
        the reference capture: probing a restricted key, the lexical arm returns 0
        rows for the app_engineer and 1 for the dba -- a count difference. The fuzzy
        arm returns 25 rows for BOTH, because it backfills with trigram neighbours,
        and the app_engineer's 25 simply contain none of the restricted keys. A test
        comparing counts there would see 25 == 25 and conclude nothing was filtered.

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
        restricted = set(self.restricted_keys)
        for name, statement, params in arms:
            for key in self.restricted_keys:
                with self.subTest(arm=name, key=key):
                    with db.get_dict_conn("app_engineer") as conn, conn.cursor() as cur:
                        cur.execute(statement, params(key))
                        found = {row["external_key"] for row in cur.fetchall()}
                    self.assertFalse(
                        found & restricted,
                        f"the {name} arm handed persona_app_engineer "
                        f"{sorted(found & restricted)} while probing for {key}",
                    )

    def test_a_cleared_persona_does_reach_the_restricted_key_through_an_arm(self) -> None:
        """The non-vacuity half of the test above.

        Without this, an arm that returns nothing to anyone -- a broken index, an
        embedding-space mismatch, a typo in the probe -- satisfies every assertion
        above. This asserts the same probe DOES reach the row for a cleared persona,
        so absence for the app_engineer means filtering rather than emptiness.
        """
        reached = []
        for key in self.restricted_keys:
            with db.get_dict_conn("dba") as conn, conn.cursor() as cursor:
                cursor.execute(
                    "SELECT external_key FROM retrieval.full_text_search("
                    "%s, p_limit => 25)",
                    (key,),
                )
                if key in {row["external_key"] for row in cursor.fetchall()}:
                    reached.append(key)
        self.assertTrue(
            reached,
            f"persona_dba, which holds can_see_restricted, could not reach any of "
            f"{self.restricted_keys} through the lexical arm. The arm is broken or "
            f"the index is stale, and the app_engineer assertions above are "
            f"therefore vacuous",
        )


@unittest.skipUnless(
    ROLES_PRESENT,
    "enable security mode and apply sql/11_roles_rls.sql to TEST_DATABASE_URL",
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
                  FROM unnest(%s::text[]) AS t
                """,
                [list(READ_PATH_TABLES)],
            )
            for row in cursor.fetchall():
                with self.subTest(table=row[1]):
                    self.assertFalse(row[0], f"workshop_app can SELECT {row[1]}")

    def test_role_is_scoped_to_the_transaction(self) -> None:
        """SET LOCAL, not SET: a session-scoped role would leak to the next
        borrower of this pooled connection."""
        with db.get_dict_conn("dba") as conn, conn.cursor() as cursor:
            cursor.execute("SELECT current_user AS role")
            self.assertEqual(cursor.fetchone()["role"], "persona_dba")
        with db.get_dict_conn("app_engineer") as conn, conn.cursor() as cursor:
            cursor.execute("SELECT current_user AS role")
            self.assertEqual(cursor.fetchone()["role"], "persona_app_engineer")

    def test_clearance_is_withheld_from_the_app_engineer_not_marked_on_it(self) -> None:
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            for persona, expected in (
                ("persona_app_engineer", False),
                ("persona_dba", True),
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
                [list(READ_PATH_TABLES)],
            )
            rows = cursor.fetchall()
        self.assertEqual(len(rows), 3, rows)
        for tbl, enabled, forced in rows:
            with self.subTest(table=tbl):
                self.assertTrue(enabled, f"{tbl}: RLS not enabled")
                self.assertTrue(forced, f"{tbl}: RLS not forced; the owner is unfiltered")


@unittest.skipUnless(
    ROLES_PRESENT,
    "enable security mode and apply sql/11_roles_rls.sql to TEST_DATABASE_URL",
)
class ProofAuthorizationTests(unittest.TestCase):
    """Proof and inferred relationships stay bound to their creating persona."""

    def _retrieval_run(self, persona: str) -> str:
        with db.get_dict_conn(persona) as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO proof.retrieval_runs(
                  query_text,
                  retrieval_mode,
                  role,
                  rrf_k,
                  text_weight,
                  vector_weight,
                  fuzzy_weight,
                  status,
                  completed_at
                )
                VALUES (%s, 'lexical', %s, 60, 2, 1, 1, 'complete', now())
                RETURNING run_id
                """,
                (f"proof authorization {uuid4()}", persona),
            )
            return str(cursor.fetchone()["run_id"])

    def _agent_run(self, persona: str) -> str:
        with db.get_dict_conn(persona) as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO proof.agent_runs(
                  question,
                  role,
                  controls_initial,
                  contract_version,
                  status,
                  ended_at
                )
                VALUES (%s, %s, '{}'::jsonb, 'test', 'complete', now())
                RETURNING agent_run_id
                """,
                (f"proof authorization {uuid4()}", persona),
            )
            return str(cursor.fetchone()["agent_run_id"])

    def test_retrieval_run_and_children_are_exact_persona_only(self) -> None:
        run_id = self._retrieval_run("dba")
        try:
            with db.get_dict_conn("dba") as conn, conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO proof.run_stages(
                      run_id, stage_ordinal, stage_name, duration_ms
                    )
                    VALUES (%s, 1, 'authorization test', 0)
                    """,
                    (run_id,),
                )

            for persona, expected in (("app_engineer", 0), ("dba", 1)):
                with self.subTest(persona=persona):
                    with db.get_dict_conn(persona) as conn, conn.cursor() as cursor:
                        cursor.execute(
                            "SELECT count(*) AS n FROM proof.retrieval_runs "
                            "WHERE run_id = %s",
                            (run_id,),
                        )
                        self.assertEqual(cursor.fetchone()["n"], expected)
                        cursor.execute(
                            "SELECT count(*) AS n FROM proof.run_stages "
                            "WHERE run_id = %s",
                            (run_id,),
                        )
                        self.assertEqual(cursor.fetchone()["n"], expected)
                        cursor.execute(
                            "SELECT count(*) AS n FROM proof.v_run_receipts "
                            "WHERE run_id = %s",
                            (run_id,),
                        )
                        self.assertEqual(cursor.fetchone()["n"], expected)

            with db.get_dict_conn("app_engineer") as conn, conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE proof.retrieval_runs SET status = 'failed' "
                    "WHERE run_id = %s",
                    (run_id,),
                )
                self.assertEqual(cursor.rowcount, 0)

            # WITH CHECK, not a missing grant: the app_engineer HOLDS INSERT on this
            # table (sql/11 grants it -- the API writes receipts as the requesting
            # persona). What it cannot do is write a row claiming to be someone
            # else's. psycopg raises InsufficientPrivilege for a WITH CHECK
            # violation because PostgreSQL reports SQLSTATE 42501 for both, so the
            # message is asserted too -- otherwise a revoked INSERT grant would
            # satisfy this test while proving something different.
            with self.assertRaises(psycopg.errors.InsufficientPrivilege) as caught:
                with db.get_dict_conn("app_engineer") as conn, conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO proof.retrieval_runs(
                          query_text,
                          retrieval_mode,
                          role,
                          rrf_k,
                          text_weight,
                          vector_weight,
                          fuzzy_weight
                        )
                        VALUES ('forged DBA run', 'lexical', 'dba', 60, 2, 1, 1)
                        """
                    )
            self.assertIn("row-level security", str(caught.exception).lower())
        finally:
            with db.get_owner_conn() as conn, conn.cursor() as cursor:
                cursor.execute("DELETE FROM proof.run_stages WHERE run_id = %s", (run_id,))
                cursor.execute(
                    "DELETE FROM proof.retrieval_runs WHERE run_id = %s", (run_id,)
                )

    def test_agent_run_and_children_are_exact_persona_only(self) -> None:
        agent_run_id = self._agent_run("auditor")
        try:
            with db.get_dict_conn("auditor") as conn, conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO proof.agent_subquestions(
                      agent_run_id,
                      subquestion_id,
                      ordinal,
                      subquestion_text,
                      required_kinds
                    )
                    VALUES (%s, 'sq-test', 1, 'Authorization test', ARRAY['change'])
                    """,
                    (agent_run_id,),
                )
            with db.get_dict_conn("app_engineer") as conn, conn.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) AS n FROM proof.agent_runs "
                    "WHERE agent_run_id = %s",
                    (agent_run_id,),
                )
                self.assertEqual(cursor.fetchone()["n"], 0)
                cursor.execute(
                    "SELECT count(*) AS n FROM proof.agent_subquestions "
                    "WHERE agent_run_id = %s",
                    (agent_run_id,),
                )
                self.assertEqual(cursor.fetchone()["n"], 0)
        finally:
            with db.get_owner_conn() as conn, conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM proof.agent_subquestions WHERE agent_run_id = %s",
                    (agent_run_id,),
                )
                cursor.execute(
                    "DELETE FROM proof.agent_runs WHERE agent_run_id = %s",
                    (agent_run_id,),
                )

    def test_transport_receipt_without_run_id_keeps_its_persona(self) -> None:
        from backend.app.contracts import InvocationContext, record_transport_invocation

        request_id = f"req-proof-{uuid4()}"
        record_transport_invocation(
            InvocationContext(transport="http", request_id=request_id),
            "authorization_test",
            {"role": "dba"},
            response_payload=None,
            status="failed",
            error="expected test failure",
        )
        try:
            for persona, expected in (("app_engineer", 0), ("dba", 1)):
                with self.subTest(persona=persona):
                    with db.get_dict_conn(persona) as conn, conn.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT count(*) AS n
                            FROM proof.transport_invocations
                            WHERE metadata ->> 'request_id' = %s
                            """,
                            (request_id,),
                        )
                        self.assertEqual(cursor.fetchone()["n"], expected)
        finally:
            with db.get_owner_conn() as conn, conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM proof.transport_invocations "
                    "WHERE metadata ->> 'request_id' = %s",
                    (request_id,),
                )


# The tables sql/12_masking.sql masks, and the persona each policy names. Written
# down rather than read from pgcolumnmask.ddm_policies on purpose: a test that asks
# the catalog which roles are masked and then asserts exactly that cannot fail. G-29
# measured three mutations of a policy staying green under catalog-derived
# expectations (drop, widen, narrow). Keep in sync with sql/12 section 3 and with
# MASKED_FOR in gates/masking_determinism.py.
# ALL SIX masked columns, not one per table. The second column of each policy is
# where the measured leak actually was: sql/12 redacted the statement column and
# returned the identical text one column over in the jsonb copy (raw_row for
# activity, raw_payload for insights, queries for statements). A test covering only
# the obvious text column would have passed against every one of those leaks.
MASKED_COLUMNS = (
    ("casework.pg_stat_activity_samples", "query"),
    ("casework.pg_stat_activity_samples", "raw_row"),
    ("casework.database_insights_samples", "statement"),
    ("casework.database_insights_samples", "raw_payload"),
    ("casework.pg_stat_statements_samples", "queries"),
    ("casework.pg_stat_statements_samples", "raw_row"),
)

# casework.telemetry_evidence is NOT here, and that is a fix rather than an
# omission: masking it crashed the Aurora instance through
# casework.v_evidence_documents and protected nothing, because the same statements
# are readable in the deliberately-unmasked chunk corpus. See sql/12_masking.sql
# section 3 and G-29's MUST_NOT_BE_MASKED.
MASKED_FOR = ("persona_app_engineer", "persona_auditor")
UNMASKED_PERSONA = "dba"

# Whitespace and the two-character escape sequences that stand in for it inside a
# jsonb value rendered ::text. Mirrors the (\s|\\[a-z])+ matcher sql/12's
# refresh_mask_blob() builds, and for the same measured reason: four of the six
# masked columns are jsonb, so a newline in the captured statement arrives as the
# two characters backslash-n. Without collapsing both sides, `literal in value` can
# never match those four columns and the leak scan below would pass on a real leak
# -- the precise failure mode sql/12 documents having hit.
_WHITESPACE_OR_ESCAPE = re.compile(r"(\s|\\[a-z])+")


def _collapse(value: str) -> str:
    """Collapse whitespace and escaped whitespace to a single space, lowercased.

    Lowercased because the generated mask is case-insensitive ('gi') and G-29's
    leak scan is ILIKE; a case-varied copy of a restricted statement is still a
    leak.
    """
    return _WHITESPACE_OR_ESCAPE.sub(" ", value).strip().lower()


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

    NEVER PUT A MASKED COLUMN IN A PREDICATE. pg_columnmask rejects it outright --
    "Predicates on masked columns are not allowed" -- and the rejection reaches
    inside a subquery and inside a FILTER (WHERE ...) clause, so counting redacted
    values needs the rows materialised first. Worse, a masked role JOINING a masked
    table segfaults the backend and restarts the whole instance, so these tests
    read one table at a time and compare in Python.
    """

    def _column_values(self, persona: str, table: str, column: str) -> list[str | None]:
        """Read one masked column for one persona: no join, no predicate.

        Cast to text in SQL rather than str() in Python. Four of the six masked
        columns are jsonb, which psycopg adapts to dict/list -- so a Python-side
        substring test would search the repr, where key order is not guaranteed and
        a match could be missed. ::text renders it once, in the database, exactly as
        the mask expression saw it.
        """
        with db.get_dict_conn(persona) as conn, conn.cursor() as cursor:
            cursor.execute(
                f"SELECT {column}::text AS value FROM {table} ORDER BY sample_id"
            )
            return [row["value"] for row in cursor.fetchall()]

    def test_the_masked_personas_hold_execute_on_the_mask_functions(self) -> None:
        """Not covered by sql/11. pg_columnmask evaluates a masking expression with
        the QUERYING role's privileges, so a persona without EXECUTE gets 42501
        permission denied instead of a redacted value."""
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            for persona in MASKED_FOR:
                for function in (
                    "retrieval.mask_blob(text)",
                    "casework.mask_redact(text)",
                    "casework.mask_redact_json(jsonb)",
                ):
                    with self.subTest(persona=persona, function=function):
                        cursor.execute(
                            "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                            [persona, function],
                        )
                        self.assertTrue(
                            cursor.fetchone()[0],
                            f"{persona} cannot EXECUTE {function}; every read of a "
                            f"column masked by it raises 42501",
                        )

    def test_the_unmasked_persona_reads_the_captured_statements_raw(self) -> None:
        """The baseline the lab compares against.

        persona_dba is named by no masking policy, and this must stay true: if the
        dba's read were redacted too, "cleared reads raw, uncleared reads
        [REDACTED]" -- the comparison the workshop asks a participant to run --
        would be a distinction without a difference.
        """
        for table, column in MASKED_COLUMNS:
            with self.subTest(table=table, column=column):
                values = self._column_values(UNMASKED_PERSONA, table, column)
                self.assertTrue(values, f"{table} is empty; nothing to compare")
                redacted = [v for v in values if v and "[REDACTED]" in v]
                self.assertFalse(
                    redacted,
                    f"persona_{UNMASKED_PERSONA} read {len(redacted)} redacted value(s) "
                    f"in {table}.{column}. It holds can_see_restricted and is named by "
                    f"no policy in sql/12_masking.sql, so its read is the unmasked "
                    f"baseline -- a policy has been widened to include it",
                )

    def test_the_masked_personas_never_read_a_sensitive_literal(self) -> None:
        """The leak scan, and the honest form of it.

        "Every value differs from the owner's" would FAIL a correct mask: measured
        on the reference capture, 240 of 270 pg_stat_activity rows are redacted
        because the other 30 legitimately contain no restricted literal. The claim
        is therefore narrower and true -- no masked persona reads any literal
        retrieval.sensitive_literals() names, and at least one value is redacted so
        the scan is not passing on an empty mask.
        """
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT literal FROM retrieval.sensitive_literals()")
            literals = [row[0] for row in cursor.fetchall()]
        self.assertTrue(literals, "no sensitive literals: the mask is a no-op")

        needles = [_collapse(literal) for literal in literals]
        for table, column in MASKED_COLUMNS:
            for persona in MASKED_FOR:
                short = persona.removeprefix("persona_")
                with self.subTest(table=table, column=column, persona=short):
                    values = self._column_values(short, table, column)
                    self.assertTrue(values, f"{table} is empty for {short}")
                    self.assertTrue(
                        any(v and "[REDACTED]" in v for v in values),
                        f"not one value in {table}.{column} is redacted for "
                        f"{persona}; the policy is absent or its expression is a "
                        f"no-op",
                    )
                    for literal, needle in zip(literals, needles):
                        leaked = [
                            v for v in values if v and needle in _collapse(v)
                        ]
                        self.assertFalse(
                            leaked,
                            f"{persona} read a restricted literal verbatim in "
                            f"{table}.{column} ({len(leaked)} value(s)): "
                            f"{literal[:60]!r}",
                        )

    def test_masking_is_deterministic_between_the_app_path_and_the_verify_sql(self) -> None:
        """Law 2: the value in the panel and the value in a pasted verify-SQL must
        be byte-identical. Two reads through get_dict_conn() over an IMMUTABLE mask
        are trivially equal and prove nothing -- this instead compares the app-path
        read against the same SELECT run inside the verify-SQL envelope
        (BEGIN; SET LOCAL ROLE persona_auditor; <SELECT>; ROLLBACK;) on a separate
        connection, which is the actual claim being tested."""
        table, column = MASKED_COLUMNS[0]
        app_values = self._column_values("auditor", table, column)
        self.assertTrue(app_values, f"{table} is empty; nothing to compare")

        # The owner DSN, then SET LOCAL ROLE -- exactly what the rendered envelope
        # does. get_owner_conn() is autocommit, so the explicit BEGIN/ROLLBACK is
        # what scopes the role, and the ROLLBACK leaves the database untouched.
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            cursor.execute("BEGIN")
            try:
                cursor.execute("SET LOCAL ROLE persona_auditor")
                cursor.execute(
                    f"SELECT {column}::text FROM {table} ORDER BY sample_id"
                )
                verify_values = [row[0] for row in cursor.fetchall()]
            finally:
                cursor.execute("ROLLBACK")
        self.assertEqual(app_values, verify_values)

    def test_the_tables_that_must_not_be_masked_are_not(self) -> None:
        """Two absences that are load-bearing, asserted so they cannot regress
        silently.

        casework.telemetry_evidence: a mask here made an auditor's read of
        casework.v_evidence_documents terminate the backend and restart the whole
        Aurora instance, and it protected nothing anyway.

        retrieval.chunks: a mask on chunk_text makes all three search functions
        fail with "failed to postpone qual containing lateral reference", because
        each returns a snippet from a LATERAL subquery. RLS already covers that
        column.
        """
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT schemaname || '.' || tablename AS qualified, policyname
                  FROM pgcolumnmask.ddm_policies
                 WHERE schemaname || '.' || tablename = ANY(%s)
                """,
                [["casework.telemetry_evidence", "retrieval.chunks"]],
            )
            offenders = cursor.fetchall()
        self.assertEqual(
            offenders,
            [],
            f"masking policies exist on tables that must carry none: {offenders}. "
            f"See sql/12_masking.sql section 3 -- one crashes the instance, the "
            f"other breaks every search function",
        )


if __name__ == "__main__":
    unittest.main()
