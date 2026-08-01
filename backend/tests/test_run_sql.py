from __future__ import annotations

from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from backend.scripts.run_sql import run_sql_files, should_skip_masking


class TransactionProbe:
    def __init__(self) -> None:
        self.entries = 0
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self):
        self.entries += 1
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if exc_type is None:
            self.commits += 1
        else:
            self.rollbacks += 1
        return False


class ConnectionProbe:
    def __init__(self, cursor: MagicMock) -> None:
        self.cursor_value = cursor
        self.transaction_probe = TransactionProbe()
        self.transaction_calls = 0

    def transaction(self) -> TransactionProbe:
        self.transaction_calls += 1
        return self.transaction_probe

    def cursor(self):
        return nullcontext(self.cursor_value)


class MaskingMigrationDispatchTests(unittest.TestCase):
    def test_non_masking_files_never_probe_the_engine(self) -> None:
        cursor = MagicMock()

        self.assertFalse(should_skip_masking(cursor, Path("sql/01_schema.sql")))
        cursor.execute.assert_not_called()

    def test_local_postgres_skips_an_unavailable_aurora_extension(self) -> None:
        cursor = MagicMock()
        cursor.fetchone.side_effect = [(False,), (False,)]

        self.assertTrue(should_skip_masking(cursor, Path("sql/12_masking.sql")))

    def test_aurora_fails_when_selected_masking_is_unavailable(self) -> None:
        cursor = MagicMock()
        cursor.fetchone.side_effect = [(False,), (True,)]

        with self.assertRaisesRegex(
            RuntimeError, "explicitly selected.*pg_columnmask is required"
        ):
            should_skip_masking(cursor, Path("sql/12_masking.sql"))

    def test_available_masking_extension_runs_everywhere(self) -> None:
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)

        self.assertFalse(should_skip_masking(cursor, Path("sql/12_masking.sql")))
        self.assertEqual(cursor.execute.call_count, 1)


class TransactionalSqlRunnerTests(unittest.TestCase):
    def _files(self, *contents: tuple[str, str]) -> list[Path]:
        temporary = tempfile.TemporaryDirectory()
        paths = []
        for name, sql in contents:
            path = Path(temporary.name) / name
            path.write_text(sql, encoding="utf-8")
            paths.append(path)
        self.addCleanup(temporary.cleanup)
        return paths

    def test_successful_file_set_commits_once(self) -> None:
        first, second = self._files(
            ("01_first.sql", "SELECT 'first'"),
            ("02_second.sql", "SELECT 'second'"),
        )
        cursor = MagicMock()
        connection = ConnectionProbe(cursor)
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            applied = run_sql_files(connection, [first, second])

        self.assertEqual(applied, [first, second])
        self.assertEqual(connection.transaction_calls, 1)
        self.assertEqual(connection.transaction_probe.entries, 1)
        self.assertEqual(connection.transaction_probe.commits, 1)
        self.assertEqual(connection.transaction_probe.rollbacks, 0)
        self.assertEqual(
            [call.args[0] for call in cursor.execute.call_args_list],
            ["SELECT 'first'", "SELECT 'second'"],
        )
        self.assertIn(f"Running {first}", stdout.getvalue())
        self.assertIn(
            f"Executed {second}; pending transaction commit",
            stdout.getvalue(),
        )
        self.assertIn("Committed 2 SQL file(s) in one transaction", stdout.getvalue())

    def test_later_file_failure_rolls_back_the_whole_set(self) -> None:
        first, second, third = self._files(
            ("01_first.sql", "SELECT 'first'"),
            ("02_broken.sql", "BROKEN"),
            ("03_never.sql", "SELECT 'never'"),
        )
        cursor = MagicMock()

        def execute(statement: str) -> None:
            if statement == "BROKEN":
                raise RuntimeError("later file failed")

        cursor.execute.side_effect = execute
        connection = ConnectionProbe(cursor)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            with self.assertRaisesRegex(RuntimeError, "later file failed"):
                run_sql_files(connection, [first, second, third])

        self.assertEqual(connection.transaction_calls, 1)
        self.assertEqual(connection.transaction_probe.commits, 0)
        self.assertEqual(connection.transaction_probe.rollbacks, 1)
        self.assertEqual(
            [call.args[0] for call in cursor.execute.call_args_list],
            ["SELECT 'first'", "BROKEN"],
        )
        self.assertIn(
            f"Executed {first}; pending transaction commit",
            stdout.getvalue(),
        )
        self.assertNotIn(str(third), stdout.getvalue())
        self.assertIn(str(second), stderr.getvalue())
        self.assertIn("rolled back selected SQL set", stderr.getvalue())

    def test_local_masking_skip_stays_inside_the_committed_set(self) -> None:
        first, masking = self._files(
            ("01_first.sql", "SELECT 'first'"),
            ("12_masking.sql", "CREATE EXTENSION pg_columnmask"),
        )
        cursor = MagicMock()
        cursor.fetchone.side_effect = [(False,), (False,)]
        connection = ConnectionProbe(cursor)
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            applied = run_sql_files(connection, [first, masking])

        self.assertEqual(applied, [first])
        self.assertEqual(connection.transaction_probe.commits, 1)
        self.assertEqual(connection.transaction_probe.rollbacks, 0)
        self.assertNotIn(
            "CREATE EXTENSION pg_columnmask",
            [call.args[0] for call in cursor.execute.call_args_list],
        )
        self.assertIn("Skipping sql/12_masking.sql", stdout.getvalue())

    def test_aurora_missing_masking_rolls_back_preceding_files(self) -> None:
        first, masking = self._files(
            ("01_first.sql", "SELECT 'first'"),
            ("12_masking.sql", "CREATE EXTENSION pg_columnmask"),
        )
        cursor = MagicMock()
        cursor.fetchone.side_effect = [(False,), (True,)]
        connection = ConnectionProbe(cursor)

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(
                RuntimeError, "explicitly selected.*pg_columnmask is required"
            ):
                run_sql_files(connection, [first, masking])

        self.assertEqual(connection.transaction_probe.commits, 0)
        self.assertEqual(connection.transaction_probe.rollbacks, 1)
        self.assertNotIn(
            "CREATE EXTENSION pg_columnmask",
            [call.args[0] for call in cursor.execute.call_args_list],
        )


if __name__ == "__main__":
    unittest.main()
