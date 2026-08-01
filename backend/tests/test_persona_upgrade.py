"""Disposable-database contract for the optional persona-role upgrade."""

from __future__ import annotations

import os
from pathlib import Path
import unittest
from urllib.parse import urlparse

import psycopg

from backend.scripts.run_sql import run_sql_files


REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_DSN = os.environ.get("TEST_DATABASE_URL")
RESET_OK = os.environ.get("ALLOW_TEST_DATABASE_RESET") == "1"
SECURITY_ENABLED = os.environ.get("WORKBENCH_SECURITY_ENABLED") == "1"
TARGET_ROLES = (
    "persona_analyst",
    "persona_admin",
    "persona_app_engineer",
    "persona_dba",
    "persona_auditor",
    "can_see_restricted",
    "workshop_app",
    "workshop_participant",
)


def _database_name(dsn: str) -> str:
    return urlparse(dsn).path.lstrip("/")


@unittest.skipUnless(
    TEST_DSN and RESET_OK and SECURITY_ENABLED,
    "needs TEST_DATABASE_URL, ALLOW_TEST_DATABASE_RESET=1, and "
    "WORKBENCH_SECURITY_ENABLED=1",
)
class PersonaUpgradeTests(unittest.TestCase):
    def test_old_personas_upgrade_in_place_and_reapply_idempotently(self) -> None:
        if not _database_name(TEST_DSN).endswith("_test"):
            self.skipTest("TEST_DATABASE_URL database name must end in _test")

        conn = psycopg.connect(TEST_DSN, autocommit=False)
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT rolsuper OR (
                             rolcreaterole
                             AND pg_has_role(
                               current_user,
                               'pg_monitor',
                               'MEMBER WITH ADMIN OPTION'
                             )
                           )
                      FROM pg_roles
                     WHERE rolname = current_user
                    """
                )
                if not cursor.fetchone()[0]:
                    self.skipTest(
                        "upgrade test requires CREATEROLE and ADMIN OPTION "
                        "on pg_monitor, or superuser"
                    )

                cursor.execute(
                    "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
                    [list(TARGET_ROLES)],
                )
                existing_roles = [row[0] for row in cursor.fetchall()]
                if existing_roles:
                    self.skipTest(
                        "upgrade test will not mutate existing cluster roles: "
                        + ", ".join(sorted(existing_roles))
                    )

            # The outer transaction rolls back schemas and cluster-global roles,
            # including successful ALTER ROLE renames, when the connection closes.
            setup_files = [
                REPO_ROOT / "sql/00_extensions.sql",
                REPO_ROOT / "sql/01_schema.sql",
                REPO_ROOT / "sql/10_admission.sql",
            ]
            run_sql_files(conn, setup_files)

            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    ALTER TABLE proof.retrieval_runs
                      DROP CONSTRAINT retrieval_runs_role_check;
                    ALTER TABLE proof.retrieval_runs
                      ALTER COLUMN role SET DEFAULT 'analyst';
                    UPDATE proof.retrieval_runs
                       SET role = CASE role
                         WHEN 'app_engineer' THEN 'analyst'
                         WHEN 'dba' THEN 'admin'
                         ELSE role
                       END;
                    ALTER TABLE proof.retrieval_runs
                      ADD CONSTRAINT retrieval_runs_role_check
                      CHECK (role IN ('analyst', 'admin', 'auditor'));

                    ALTER TABLE proof.agent_runs
                      DROP CONSTRAINT agent_runs_role_check;
                    ALTER TABLE proof.agent_runs
                      ALTER COLUMN role SET DEFAULT 'analyst';
                    UPDATE proof.agent_runs
                       SET role = CASE role
                         WHEN 'app_engineer' THEN 'analyst'
                         WHEN 'dba' THEN 'admin'
                         ELSE role
                       END;
                    ALTER TABLE proof.agent_runs
                      ADD CONSTRAINT agent_runs_role_check
                      CHECK (role IN ('analyst', 'admin', 'auditor'));

                    INSERT INTO proof.retrieval_runs(
                      query_text, retrieval_mode, role, rrf_k,
                      text_weight, vector_weight, fuzzy_weight
                    )
                    VALUES
                      ('old analyst receipt', 'hybrid', 'analyst', 60, 2, 1, 1),
                      ('old admin receipt', 'hybrid', 'admin', 60, 2, 1, 1);

                    INSERT INTO proof.agent_runs(
                      question, role, controls_initial, contract_version
                    )
                    VALUES
                      ('old analyst agent run', 'analyst', '{}'::jsonb, 'test'),
                      ('old admin agent run', 'admin', '{}'::jsonb, 'test');

                    CREATE ROLE persona_analyst NOLOGIN;
                    CREATE ROLE persona_admin NOLOGIN;
                    """
                )
                cursor.execute(
                    """
                    SELECT rolname, oid
                      FROM pg_roles
                     WHERE rolname IN ('persona_analyst', 'persona_admin')
                     ORDER BY rolname
                    """
                )
                old_oids = dict(cursor.fetchall())

            upgrade_files = [
                REPO_ROOT / "sql/01_schema.sql",
                REPO_ROOT / "sql/11_roles_rls.sql",
            ]
            run_sql_files(conn, upgrade_files)
            self._assert_upgraded(conn, old_oids)

            run_sql_files(conn, upgrade_files)
            self._assert_upgraded(conn, old_oids)
        finally:
            conn.rollback()
            conn.close()

    def _assert_upgraded(self, conn, old_oids: dict[str, int]) -> None:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT role, count(*)
                  FROM proof.retrieval_runs
                 WHERE query_text LIKE 'old % receipt'
                 GROUP BY role
                 ORDER BY role
                """
            )
            self.assertEqual(cursor.fetchall(), [("app_engineer", 1), ("dba", 1)])

            cursor.execute(
                """
                SELECT role, count(*)
                  FROM proof.agent_runs
                 WHERE question LIKE 'old % agent run'
                 GROUP BY role
                 ORDER BY role
                """
            )
            self.assertEqual(cursor.fetchall(), [("app_engineer", 1), ("dba", 1)])

            for table in ("retrieval_runs", "agent_runs"):
                cursor.execute(
                    """
                    SELECT pg_get_expr(d.adbin, d.adrelid)
                      FROM pg_attrdef d
                      JOIN pg_attribute a
                        ON a.attrelid = d.adrelid AND a.attnum = d.adnum
                     WHERE d.adrelid = %s::regclass
                       AND a.attname = 'role'
                    """,
                    [f"proof.{table}"],
                )
                self.assertEqual(cursor.fetchone()[0], "'app_engineer'::text")

                cursor.execute(
                    """
                    SELECT pg_get_constraintdef(oid)
                      FROM pg_constraint
                     WHERE conrelid = %s::regclass
                       AND conname = %s
                    """,
                    [f"proof.{table}", f"{table}_role_check"],
                )
                definition = cursor.fetchone()[0]
                self.assertIn("app_engineer", definition)
                self.assertIn("dba", definition)
                self.assertIn("auditor", definition)
                self.assertNotIn("'analyst'", definition)

            cursor.execute(
                """
                SELECT rolname, oid
                  FROM pg_roles
                 WHERE rolname IN (
                   'persona_analyst', 'persona_admin',
                   'persona_app_engineer', 'persona_dba'
                 )
                 ORDER BY rolname
                """
            )
            roles = dict(cursor.fetchall())
            self.assertNotIn("persona_analyst", roles)
            self.assertNotIn("persona_admin", roles)
            self.assertEqual(
                roles["persona_app_engineer"],
                old_oids["persona_analyst"],
            )
            self.assertEqual(roles["persona_dba"], old_oids["persona_admin"])

            cursor.execute(
                """
                SELECT polroles
                  FROM pg_policy
                 WHERE polrelid = 'casework.evidence_items'::regclass
                   AND polname = 'rls_evidence_items_visibility'
                """
            )
            policy_roles = set(cursor.fetchone()[0])
            self.assertIn(roles["persona_app_engineer"], policy_roles)
            self.assertIn(roles["persona_dba"], policy_roles)


if __name__ == "__main__":
    unittest.main()
