"""Contract and live concurrency tests for the participant incident lab."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from urllib.parse import urlparse

import psycopg

from admission.promote_pg_incident import build_payload


REPO_ROOT = Path(__file__).resolve().parents[2]
LAB_DIR = REPO_ROOT / "labs" / "incident"
TEST_DSN = os.environ.get("TEST_DATABASE_URL")
RESET_OK = os.environ.get("ALLOW_TEST_DATABASE_RESET") == "1"
PSQL = shutil.which("psql")


class IncidentLabScriptContractTests(unittest.TestCase):
    def test_expected_participant_scripts_exist(self) -> None:
        expected = {
            "00_setup.sql",
            "10_unsafe_index.sql",
            "20_blocked_writer.sql",
            "30_observe_unsafe.sql",
            "40_safe_writer.sql",
            "50_concurrent_index.sql",
            "60_observe_safe.sql",
            "70_verify.sql",
            "99_cleanup.sql",
            "README.md",
        }
        self.assertEqual(
            {path.name for path in LAB_DIR.iterdir() if path.is_file()},
            expected,
        )

    def test_unsafe_and_safe_ddl_are_not_conflated(self) -> None:
        unsafe = (LAB_DIR / "10_unsafe_index.sql").read_text(encoding="utf-8")
        safe = (LAB_DIR / "50_concurrent_index.sql").read_text(encoding="utf-8")

        self.assertIn("BEGIN;", unsafe)
        self.assertIn("ROLLBACK;", unsafe)
        self.assertIn("CREATE INDEX idx_orders_customer_created", unsafe)
        self.assertNotIn("CREATE INDEX CONCURRENTLY", unsafe)
        self.assertIn("CREATE INDEX CONCURRENTLY", safe)
        self.assertNotIn("BEGIN;", safe)

    def test_capture_names_the_measured_lock_modes(self) -> None:
        observer = (LAB_DIR / "30_observe_unsafe.sql").read_text(
            encoding="utf-8"
        )

        self.assertIn("'ShareLock'", observer)
        self.assertIn("'RowExclusiveLock'", observer)
        self.assertNotIn("AccessExclusiveLock", observer)
        self.assertIn("pg_blocking_pids(writer.pid)", observer)


@unittest.skipUnless(
    TEST_DSN and RESET_OK and PSQL,
    "needs psql, TEST_DATABASE_URL, and ALLOW_TEST_DATABASE_RESET=1",
)
class IncidentLabIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        database_name = urlparse(TEST_DSN).path.lstrip("/")
        if not database_name.endswith("_test"):
            raise RuntimeError(
                f"refusing incident lab test against {database_name!r}; "
                "the database name must end in '_test'"
            )
        resolved = os.environ.get("DATABASE_URL")
        if resolved != TEST_DSN:
            raise RuntimeError(
                "DATABASE_URL and TEST_DATABASE_URL must identify the same "
                "disposable database for the incident lab test"
            )

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.capture_file = Path(self.temporary.name) / "lock_capture.json"
        self._terminate_lab_sessions()
        self._drop_lab_schema()
        self._run_script("00_setup.sql")

    def tearDown(self) -> None:
        self._terminate_lab_sessions()
        self._drop_lab_schema()
        self.temporary.cleanup()

    def _psql_command(
        self,
        filename: str,
        *,
        capture_file: Path | None = None,
    ) -> list[str]:
        command = [
            PSQL,
            TEST_DSN,
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
        ]
        if capture_file is not None:
            command.extend(["-v", f"capture_file={capture_file}"])
        command.extend(["-f", str(LAB_DIR / filename)])
        return command

    def _run_script(
        self,
        filename: str,
        *,
        capture_file: Path | None = None,
    ) -> str:
        completed = subprocess.run(
            self._psql_command(filename, capture_file=capture_file),
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
        )
        output = completed.stdout + completed.stderr
        self.assertEqual(
            completed.returncode,
            0,
            f"{filename} failed:\n{output}",
        )
        return output

    def _start_script(self, filename: str) -> subprocess.Popen[str]:
        return subprocess.Popen(
            self._psql_command(filename),
            cwd=REPO_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def _finish_prompted(
        self,
        process: subprocess.Popen[str],
        filename: str,
    ) -> str:
        output, _ = process.communicate(input="\n", timeout=20)
        self.assertEqual(
            process.returncode,
            0,
            f"{filename} failed:\n{output}",
        )
        return output

    def _finish_waiting(
        self,
        process: subprocess.Popen[str],
        filename: str,
    ) -> str:
        output, _ = process.communicate(timeout=20)
        self.assertEqual(
            process.returncode,
            0,
            f"{filename} failed:\n{output}",
        )
        return output

    def _wait_until(self, sql: str, *, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        with psycopg.connect(TEST_DSN, autocommit=True) as connection:
            while time.monotonic() < deadline:
                if connection.execute(sql).fetchone()[0]:
                    return
                time.sleep(0.05)
        self.fail(f"condition did not become true before timeout:\n{sql}")

    def _terminate_lab_sessions(self) -> None:
        with psycopg.connect(TEST_DSN, autocommit=True) as connection:
            connection.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE pid <> pg_backend_pid()
                  AND datname = current_database()
                  AND application_name LIKE 'workbench-lab-%'
                """
            )

    def _drop_lab_schema(self) -> None:
        with psycopg.connect(TEST_DSN, autocommit=True) as connection:
            connection.execute("DROP SCHEMA IF EXISTS workbench_lab CASCADE")

    def test_exact_participant_workflow(self) -> None:
        unsafe_index = self._start_script("10_unsafe_index.sql")
        blocked_writer = None
        safe_writer = None
        concurrent_index = None
        try:
            self._wait_until(
                """
                SELECT EXISTS (
                  SELECT 1
                  FROM pg_stat_activity activity
                  JOIN pg_locks lock_row ON lock_row.pid = activity.pid
                  WHERE activity.application_name =
                        'workbench-lab-unsafe-index'
                    AND lock_row.relation =
                        'workbench_lab.orders'::regclass
                    AND lock_row.mode = 'ShareLock'
                    AND lock_row.granted
                )
                """
            )

            blocked_writer = self._start_script("20_blocked_writer.sql")
            self._wait_until(
                """
                SELECT EXISTS (
                  SELECT 1
                  FROM pg_stat_activity activity
                  JOIN pg_locks lock_row ON lock_row.pid = activity.pid
                  WHERE activity.application_name =
                        'workbench-lab-blocked-writer'
                    AND activity.wait_event_type = 'Lock'
                    AND lower(activity.wait_event) = 'relation'
                    AND lock_row.relation =
                        'workbench_lab.orders'::regclass
                    AND lock_row.mode = 'RowExclusiveLock'
                    AND NOT lock_row.granted
                )
                """
            )

            unsafe_output = self._run_script(
                "30_observe_unsafe.sql",
                capture_file=self.capture_file,
            )
            self.assertIn(
                "PASS: reads continued; ShareLock blocked the writer",
                unsafe_output,
            )
            capture = json.loads(self.capture_file.read_text(encoding="utf-8"))
            structured = capture["structured"]
            self.assertEqual(structured["blocked_lock_mode"], "RowExclusiveLock")
            self.assertFalse(structured["blocked_lock_granted"])
            self.assertEqual(structured["blocking_lock_mode"], "ShareLock")
            self.assertTrue(structured["blocking_lock_granted"])
            self.assertIn(
                structured["blocking_pid"],
                structured["blocking_pids"],
            )
            promoted = build_payload(
                self.capture_file.parent,
                REPO_ROOT / "admission" / "fixture_payload.json",
            )
            self.assertEqual(promoted["external_key"], "LOCK-LIVE-001")
            self.assertEqual(
                promoted["structured"]["relation_oid"],
                structured["relation_oid"],
            )
            self.assertEqual(
                promoted["structured"]["blocking_lock_mode"],
                "ShareLock",
            )

            self._finish_prompted(unsafe_index, "10_unsafe_index.sql")
            unsafe_index = None
            writer_output = self._finish_waiting(
                blocked_writer,
                "20_blocked_writer.sql",
            )
            blocked_writer = None
            self.assertIn("WRITER DRAINED", writer_output)

            with psycopg.connect(TEST_DSN, autocommit=True) as connection:
                index_name, status = connection.execute(
                    """
                    SELECT
                      to_regclass(
                        'workbench_lab.idx_orders_customer_created'
                      ),
                      status
                    FROM workbench_lab.orders
                    WHERE order_id = 1
                    """
                ).fetchone()
            self.assertIsNone(index_name)
            if isinstance(status, bytes):
                status = status.decode()
            self.assertEqual(status, "unsafe-writer-drained")

            safe_writer = self._start_script("40_safe_writer.sql")
            self._wait_until(
                """
                SELECT EXISTS (
                  SELECT 1
                  FROM pg_stat_activity activity
                  JOIN pg_locks lock_row ON lock_row.pid = activity.pid
                  WHERE activity.application_name =
                        'workbench-lab-safe-writer'
                    AND lock_row.relation =
                        'workbench_lab.orders'::regclass
                    AND lock_row.mode = 'RowExclusiveLock'
                    AND lock_row.granted
                )
                """
            )

            concurrent_index = self._start_script("50_concurrent_index.sql")
            self._wait_until(
                """
                SELECT EXISTS (
                  SELECT 1
                  FROM pg_stat_activity activity
                  JOIN pg_locks lock_row ON lock_row.pid = activity.pid
                  WHERE activity.application_name =
                        'workbench-lab-concurrent-index'
                    AND lock_row.relation =
                        'workbench_lab.orders'::regclass
                    AND lock_row.mode = 'ShareUpdateExclusiveLock'
                    AND lock_row.granted
                )
                """
            )

            safe_output = self._run_script("60_observe_safe.sql")
            self.assertIn(
                "PASS: RowExclusiveLock coexisted with "
                "ShareUpdateExclusiveLock",
                safe_output,
            )

            self._finish_prompted(safe_writer, "40_safe_writer.sql")
            safe_writer = None
            concurrent_output = self._finish_waiting(
                concurrent_index,
                "50_concurrent_index.sql",
            )
            concurrent_index = None
            self.assertIn("COMPLETE: the concurrent index build", concurrent_output)

            verify_output = self._run_script("70_verify.sql")
            self.assertIn(
                "PASS: safe index is ready, valid, live",
                verify_output,
            )

            cleanup_output = self._run_script("99_cleanup.sql")
            self.assertIn("CLEAN: workbench_lab was removed", cleanup_output)
        finally:
            for process in (
                unsafe_index,
                blocked_writer,
                safe_writer,
                concurrent_index,
            ):
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
