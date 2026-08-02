"""Contracts for the guided, live-only participant incident orchestrator."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from labs.incident.run_live_workshop import (
    OBSERVATION_COUNT,
    READER_COUNT,
    SOURCE_SYSTEM,
    WRITER_COUNT,
    _write_exercise_requests,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
LAB_DIR = REPO_ROOT / "labs" / "incident"


class IncidentLabContractTests(unittest.TestCase):
    def test_only_the_guided_live_path_is_shipped(self) -> None:
        expected = {
            "README.md",
            "capture_observability.py",
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

    def test_orchestrator_contains_both_measured_ddl_paths(self) -> None:
        source = (LAB_DIR / "run_live_workshop.py").read_text(encoding="utf-8")

        self.assertIn("CREATE INDEX idx_orders_customer_created", source)
        self.assertIn(
            "CREATE INDEX CONCURRENTLY idx_orders_customer_created",
            source,
        )
        self.assertIn("'ShareLock'", source)
        self.assertIn("'RowExclusiveLock'", source)
        self.assertIn("'ShareUpdateExclusiveLock'", source)
        self.assertIn("pg_blocking_pids(pid)", source)

    def test_orchestrator_escapes_modulo_in_parameterized_setup_sql(self) -> None:
        source = (LAB_DIR / "run_live_workshop.py").read_text(encoding="utf-8")

        self.assertIn("value %% 5000", source)
        self.assertIn("value %% 86400", source)

    def test_orchestrator_fails_fast_on_an_incomplete_core_schema(self) -> None:
        source = (LAB_DIR / "run_live_workshop.py").read_text(encoding="utf-8")

        self.assertIn("casework.admit_evidence(jsonb)", source)
        self.assertIn("casework.assert_live_capture_ready()", source)
        self.assertIn("retrieval.assert_search_index_ready()", source)
        self.assertIn("core schema is incomplete", source)


if __name__ == "__main__":
    unittest.main()
