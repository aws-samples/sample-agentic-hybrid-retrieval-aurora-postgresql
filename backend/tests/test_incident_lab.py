"""Contracts for the guided, live-only participant incident orchestrator."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from labs.incident.run_live_workshop import (
    LAB_CUSTOMER_ROWS,
    LAB_ROWS,
    LiveWorkshopError,
    OBSERVATION_COUNT,
    READER_COUNT,
    SOURCE_SYSTEM,
    WRITER_COUNT,
    _assert_lab_workload_ready,
    _write_exercise_requests,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
LAB_DIR = REPO_ROOT / "labs" / "incident"


class IncidentLabContractTests(unittest.TestCase):
    def test_only_the_guided_live_path_is_shipped(self) -> None:
        expected = {
            "README.md",
            "capture_observability.py",
            "migration.py",
            "prepare_workload.py",
            "run_live_workshop.py",
        }
        self.assertEqual(
            {path.name for path in LAB_DIR.iterdir() if path.is_file()},
            expected,
        )

    def test_workshop_scale_comes_from_repeated_live_observations(self) -> None:
        self.assertEqual(OBSERVATION_COUNT, 30)
        self.assertEqual(WRITER_COUNT, 6)
        self.assertEqual(READER_COUNT, 2)
        self.assertEqual(SOURCE_SYSTEM, "pg_incident_capture")

    def test_lab_workload_is_three_million_orders(self) -> None:
        orchestrator = (LAB_DIR / "run_live_workshop.py").read_text(
            encoding="utf-8"
        )
        bootstrap = orchestrator.split("def _create_lab_workload", 1)[1].split(
            "\ndef ", 1
        )[0]
        source = (LAB_DIR / "prepare_workload.py").read_text(encoding="utf-8")

        self.assertEqual(LAB_ROWS, 3_000_000)
        self.assertEqual(LAB_CUSTOMER_ROWS, 5_000)
        self.assertIn("DROP SCHEMA IF EXISTS workbench_lab CASCADE", bootstrap)
        self.assertNotIn("priority_tier", bootstrap)
        self.assertNotIn("updated_at", bootstrap)
        self.assertIn("prepare_lab_workload", source)
        self.assertIn("empty participant evidence store", source)

    def test_preloaded_workload_must_be_canonical_and_unindexed(self) -> None:
        ready = {
            "observed_row_count": LAB_ROWS,
            "canonical_rows": LAB_ROWS,
            "observed_customer_count": LAB_CUSTOMER_ROWS,
            "minimum_customer_id": 1,
            "maximum_customer_id": LAB_CUSTOMER_ROWS,
            "referenced_customers": LAB_CUSTOMER_ROWS,
            "orphan_order_count": 0,
            "minimum_order_id": 1,
            "maximum_order_id": LAB_ROWS,
            "target_index_exists": False,
        }
        self.assertIs(_assert_lab_workload_ready(ready), ready)

        invalid_states = (
            None,
            {**ready, "observed_row_count": LAB_ROWS - 1},
            {**ready, "canonical_rows": LAB_ROWS - 1},
            {**ready, "observed_customer_count": LAB_CUSTOMER_ROWS - 1},
            {**ready, "minimum_customer_id": 2},
            {**ready, "maximum_customer_id": LAB_CUSTOMER_ROWS + 1},
            {**ready, "referenced_customers": LAB_CUSTOMER_ROWS - 1},
            {**ready, "orphan_order_count": 1},
            {**ready, "minimum_order_id": 2},
            {**ready, "maximum_order_id": LAB_ROWS + 1},
            {**ready, "target_index_exists": True},
        )
        for state in invalid_states:
            with self.subTest(state=state):
                with self.assertRaises(LiveWorkshopError):
                    _assert_lab_workload_ready(state)

    def test_orchestrator_writes_only_run_derived_exercise_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            written = _write_exercise_requests(
                Path(directory),
                incident_key="INC-A1B2C3D4",
                unsafe_change_key="CHG-A1B2C3D4-01",
                repair_change_key="CHG-A1B2C3D4-02",
                lock_key="LOCK-A1B2C3D4-01",
            )
            rendered = "\n".join(
                Path(path).read_text(encoding="utf-8")
                for path in written.values()
            )
        self.assertIn("INC-A1B2C3D4", rendered)
        self.assertIn("CHG-A1B2C3D4-01", rendered)
        self.assertIn("CHG-A1B2C3D4-02", rendered)
        self.assertIn("LOCK-A1B2C3D4-01", rendered)
        self.assertNotIn("INC-LIVE-001", rendered)
        self.assertNotIn("REPLACE_WITH_", rendered)

    def test_old_hold_mechanism_is_gone(self) -> None:
        source = (LAB_DIR / "run_live_workshop.py").read_text(encoding="utf-8")

        for retired in (
            "_hold_unsafe_index",
            "_blocked_writer",
            "_active_reader",
        ):
            self.assertNotIn(
                retired,
                source,
                f"{retired} implements the replaced mechanism and must be deleted",
            )

    def test_add_column_commits_before_the_backfill_opens(self) -> None:
        from labs.incident.migration import add_priority_tier_column

        class DdlConnection:
            def __init__(self) -> None:
                self.statements: list[str] = []
                self.commits = 0

            def execute(self, statement: str) -> None:
                self.statements.append(statement)

            def commit(self) -> None:
                self.commits += 1

        connection = DdlConnection()
        add_priority_tier_column(connection)  # type: ignore[arg-type]

        self.assertEqual(
            connection.statements,
            ["ALTER TABLE workbench_lab.orders ADD COLUMN priority_tier int"],
        )
        self.assertEqual(connection.commits, 1)

    def test_backfill_handle_bounds_its_idle_transaction(self) -> None:
        from labs.incident.migration import BackfillHandle

        source = (LAB_DIR / "migration.py").read_text(encoding="utf-8")
        self.assertIn("idle_in_transaction_session_timeout", source)
        self.assertIn("order_id % 5", source)
        self.assertNotIn("order_id %% 5", source)

        class BackfillConnection:
            def __init__(self) -> None:
                self.commits = 0
                self.rollbacks = 0
                self.closes = 0

            def commit(self) -> None:
                self.commits += 1

            def rollback(self) -> None:
                self.rollbacks += 1

            def close(self) -> None:
                self.closes += 1

        committed = BackfillConnection()
        BackfillHandle(
            pid=1,
            duration_seconds=1.0,
            rows_updated=LAB_ROWS,
            _conn=committed,  # type: ignore[arg-type]
        ).commit()
        self.assertEqual(
            (committed.commits, committed.rollbacks, committed.closes),
            (1, 0, 1),
        )

        aborted = BackfillConnection()
        BackfillHandle(
            pid=2,
            duration_seconds=1.0,
            rows_updated=LAB_ROWS,
            _conn=aborted,  # type: ignore[arg-type]
        ).abort()
        self.assertEqual(
            (aborted.commits, aborted.rollbacks, aborted.closes),
            (0, 1, 1),
        )

    def test_orchestrator_escapes_modulo_in_parameterized_setup_sql(self) -> None:
        source = (LAB_DIR / "run_live_workshop.py").read_text(encoding="utf-8")

        self.assertIn("(value - 1) %% %s", source)
        self.assertIn("value %% 86400", source)

    def test_orchestrator_fails_fast_on_an_incomplete_core_schema(self) -> None:
        source = (LAB_DIR / "run_live_workshop.py").read_text(encoding="utf-8")

        self.assertIn("casework.admit_evidence(jsonb)", source)
        self.assertIn("casework.assert_live_capture_ready()", source)
        self.assertIn("retrieval.assert_search_index_ready()", source)
        self.assertIn("core schema is incomplete", source)


if __name__ == "__main__":
    unittest.main()
