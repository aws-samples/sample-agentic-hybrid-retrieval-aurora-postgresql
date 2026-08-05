"""Contracts for the guided, live-only participant incident orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from labs.incident.run_live_workshop import (
    LAB_CUSTOMER_ROWS,
    LAB_ROWS,
    LiveWorkshopError,
    SOURCE_SYSTEM,
    _parser,
    _assert_lab_workload_ready,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
LAB_DIR = REPO_ROOT / "labs" / "incident"


class IncidentLabContractTests(unittest.TestCase):
    def test_incident_module_file_set_matches_the_four_phase_runtime(self) -> None:
        expected = {
            "capture_observability.py",
            "evidence_builder.py",
            "hold_controller.py",
            "migration.py",
            "prepare_workload.py",
            "query_regression.py",
            "recovery_verifier.py",
            "run_live_workshop.py",
        }
        self.assertEqual(
            {path.name for path in LAB_DIR.glob("*.py")},
            expected,
        )
        self.assertTrue(
            (REPO_ROOT / "backend" / "app" / "lab_routes.py").is_file(),
            "the real FastAPI pool route is part of the incident runtime",
        )

    def test_workshop_topology_uses_the_real_application_pool(self) -> None:
        source = (LAB_DIR / "run_live_workshop.py").read_text(encoding="utf-8")

        self.assertEqual(SOURCE_SYSTEM, "pg_incident_capture")
        self.assertIn("settings.db_pool_max_size", source)
        self.assertIn("settings.lab_hot_write_request_count", source)
        for retired in ("OBSERVATION_COUNT", "WRITER_COUNT", "READER_COUNT"):
            self.assertNotIn(
                retired,
                source,
                f"{retired} belongs to the retired fixed-sample mechanism",
            )

    def test_no_performance_insights_dependency_remains(self) -> None:
        for name in ("capture_observability.py", "run_live_workshop.py"):
            source = (LAB_DIR / name).read_text(encoding="utf-8")
            for forbidden in (
                "PerformanceInsightsEnabled",
                "MAX_PI_SQL_DOCUMENTS",
                "_wait_for_database_insights",
                "pi-wait-seconds",
                "performance_insights",
            ):
                self.assertNotIn(
                    forbidden,
                    source,
                    f"{name} still references {forbidden}",
                )

    def test_cloudwatch_is_best_effort(self) -> None:
        source = (LAB_DIR / "capture_observability.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("_cloudwatch_samples", source)
        self.assertIn("cloudwatch_status", source)
        self.assertIn("unavailable", source)

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
            "touched_rows": 0,
            "unexpected_status_rows": 0,
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
            {**ready, "touched_rows": 1},
            {**ready, "unexpected_status_rows": 1},
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

    def test_post_collision_workload_requires_exact_measured_write_footprint(
        self,
    ) -> None:
        post_collision = {
            "observed_row_count": LAB_ROWS,
            "canonical_rows": LAB_ROWS - 11,
            "touched_rows": 11,
            "unexpected_status_rows": 0,
            "observed_customer_count": LAB_CUSTOMER_ROWS,
            "minimum_customer_id": 1,
            "maximum_customer_id": LAB_CUSTOMER_ROWS,
            "referenced_customers": LAB_CUSTOMER_ROWS,
            "orphan_order_count": 0,
            "minimum_order_id": 1,
            "maximum_order_id": LAB_ROWS,
            "target_index_exists": True,
        }

        self.assertIs(
            _assert_lab_workload_ready(
                post_collision,
                target_index_expected=True,
                expected_touched_rows=11,
            ),
            post_collision,
        )
        with self.assertRaises(LiveWorkshopError):
            _assert_lab_workload_ready(
                {**post_collision, "touched_rows": 10},
                target_index_expected=True,
                expected_touched_rows=11,
            )

    def test_retired_ordinary_index_payload_builder_is_not_left_beside_the_collision_runtime(
        self,
    ) -> None:
        source = (LAB_DIR / "run_live_workshop.py").read_text(encoding="utf-8")

        for retired in (
            "_telemetry_documents",
            "build_live_payload",
            "_write_exercise_requests",
        ):
            self.assertNotIn(
                retired,
                source,
                f"{retired} belongs to the retired ordinary-index path",
            )

    def test_orchestrator_exposes_both_wave_entry_points(self) -> None:
        source = (LAB_DIR / "run_live_workshop.py").read_text(encoding="utf-8")

        self.assertIn("def admit_wave_a", source)
        self.assertIn("def admit_wave_b", source)
        self.assertIn('"--wave"', source)
        wave_b = source.split("def admit_wave_b", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("incident_key", wave_b)
        wave_b_payload = source.split("def _wave_b_payload", 1)[1].split(
            "\ndef ", 1
        )[0]
        self.assertIn('"wave": "B"', wave_b_payload)
        self.assertNotIn(
            "workbench_lab.{RECOMMENDED_INDEX_NAME}",
            wave_b_payload,
            "the rollback SQL must not qualify an already-qualified index name",
        )

    def test_lab_schema_survives_by_default_and_cleanup_is_explicit(self) -> None:
        parsed = _parser().parse_args(
            [
                "--database-url",
                "postgresql://example",
                "--db-cluster-identifier",
                "cluster",
                "--db-instance-identifier",
                "instance",
            ]
        )

        self.assertFalse(
            parsed.drop_lab_schema,
            "Labs 2-4 require workbench_lab unless cleanup is explicitly requested",
        )
        source = (LAB_DIR / "run_live_workshop.py").read_text(encoding="utf-8")
        self.assertIn("--drop-lab-schema", source)
        self.assertNotIn("--keep-lab-schema", source)

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

    def test_statement_stats_serializes_its_observed_timestamp(self) -> None:
        from labs.incident.run_live_workshop import _statement_stats

        captured_at = datetime(2026, 8, 5, 12, 34, 56, tzinfo=timezone.utc)

        class Cursor:
            def fetchone(self):
                return {
                    "phase": "before",
                    "captured_at": captured_at,
                    "calls": 0,
                    "total_exec_time": 0.0,
                    "rows": 0,
                    "queryids": [],
                    "queries": [],
                }

        class Connection:
            def execute(self, statement, parameters):
                self.statement = statement
                self.parameters = parameters
                return Cursor()

        sample = _statement_stats(Connection(), "before")  # type: ignore[arg-type]

        self.assertEqual(sample["captured_at"], "2026-08-05T12:34:56+00:00")
        self.assertEqual(sample["phase"], "before")

    def test_orchestrator_fails_fast_on_an_incomplete_core_schema(self) -> None:
        source = (LAB_DIR / "run_live_workshop.py").read_text(encoding="utf-8")

        self.assertIn("casework.admit_evidence(jsonb)", source)
        self.assertIn("casework.assert_live_capture_ready()", source)
        self.assertIn("retrieval.assert_search_index_ready()", source)
        self.assertIn("core schema is incomplete", source)

    def test_hold_requires_three_consecutive_proving_samples(self) -> None:
        from labs.incident.hold_controller import PollSample, evaluate_samples

        proving = PollSample(
            pool_size=10,
            pool_max=10,
            pool_available=0,
            requests_waiting=2,
            blocked_session_count=10,
        )
        not_proving = PollSample(
            pool_size=10,
            pool_max=10,
            pool_available=1,
            requests_waiting=2,
            blocked_session_count=10,
        )

        self.assertFalse(
            evaluate_samples([proving, proving], expected_blocked_sessions=10)
        )
        self.assertTrue(
            evaluate_samples(
                [proving, proving, proving], expected_blocked_sessions=10
            )
        )
        self.assertFalse(
            evaluate_samples(
                [proving, not_proving, proving], expected_blocked_sessions=10
            ),
            "a non-proving sample must reset the streak, not be skipped",
        )

    def test_hold_failure_names_the_condition_that_never_held(self) -> None:
        from labs.incident.hold_controller import PollSample, describe_failure

        samples = [
            PollSample(
                pool_size=10,
                pool_max=10,
                pool_available=0,
                requests_waiting=2,
                blocked_session_count=7,
            )
        ] * 4

        message = describe_failure(samples, expected_blocked_sessions=10)
        self.assertIn("only 7 of 10", message)
        self.assertNotIn("timeout", message.lower())

        underfilled_pool = [
            PollSample(
                pool_size=10,
                pool_max=10,
                pool_available=3,
                requests_waiting=0,
                blocked_session_count=7,
            )
        ]
        self.assertIn(
            "only 7 of 10",
            describe_failure(
                underfilled_pool,
                expected_blocked_sessions=10,
            ),
        )

    def test_hold_expects_pool_max_blocked_sessions_not_request_count(self) -> None:
        """Queued requests never reach PostgreSQL, so only pool-held requests can
        be counted in pg_stat_activity.
        """
        from labs.incident.hold_controller import PollSample, evaluate_samples

        fully_saturated = PollSample(
            pool_size=10,
            pool_max=10,
            pool_available=0,
            requests_waiting=2,
            blocked_session_count=10,
        )
        samples = [fully_saturated] * 3

        self.assertTrue(
            evaluate_samples(samples, expected_blocked_sessions=10)
        )
        self.assertFalse(
            evaluate_samples(samples, expected_blocked_sessions=12),
            "expected_blocked_sessions must be DB_POOL_MAX_SIZE, not "
            "LAB_HOT_WRITE_REQUEST_COUNT",
        )

    def test_hold_persists_every_poll_and_only_state_transitions(self) -> None:
        from labs.incident.hold_controller import prove_hold

        class Result:
            def fetchone(self):
                return {"blocked_session_count": 10}

        class Connection:
            def execute(self, statement, parameters):
                self.statement = statement
                self.parameters = parameters
                return Result()

        proof = prove_hold(
            Connection(),  # type: ignore[arg-type]
            backfill_pid=991,
            pool_status=lambda: {
                "pool_size": 10,
                "pool_available": 0,
                "requests_waiting": 2,
            },
            expected_blocked_sessions=10,
            poll_interval=0.001,
            hold_seconds=0,
            max_attempt_seconds=1,
        )

        self.assertEqual(len(proof.samples), 3)
        self.assertEqual(len(proof.state_changes), 1)
        self.assertTrue(proof.proven_at)

    def test_recovery_assertions_fail_independently(self) -> None:
        from labs.incident.recovery_verifier import (
            RecoveryProof,
            failed_assertions,
        )

        proof = RecoveryProof(
            backfill_no_longer_blocking=True,
            pool_fully_available=False,
            no_requests_waiting=True,
            no_sessions_blocked=True,
            pool_timeout_observed=True,
            blocked_writers_drained=True,
            fresh_write_committed=False,
        )
        self.assertEqual(
            failed_assertions(proof),
            ["pool_fully_available", "fresh_write_committed"],
        )
        self.assertEqual(
            failed_assertions(RecoveryProof()),
            [],
            "the default proof must be explicitly all-passing",
        )

    def test_recovery_rejects_a_hold_that_never_saturated_the_pool(self) -> None:
        """Without a pool timeout, recovery assertions are vacuously green."""
        from labs.incident.recovery_verifier import (
            RecoveryProof,
            failed_assertions,
        )

        proof = RecoveryProof(pool_timeout_observed=False)
        self.assertEqual(
            failed_assertions(proof),
            ["pool_timeout_observed"],
        )

    def test_verify_recovery_names_each_failed_measurement(self) -> None:
        """Each recovery signal must fail independently at the verifier boundary."""
        from labs.incident.hold_controller import LiveWorkshopError
        from labs.incident.recovery_verifier import verify_recovery

        class Cursor:
            def __init__(self, recovered: bool) -> None:
                self.recovered = recovered

            def fetchone(self):
                return (self.recovered,)

        class Connection:
            def __init__(
                self,
                *,
                backfill_recovered: bool = True,
                sessions_recovered: bool = True,
            ) -> None:
                self.backfill_recovered = backfill_recovered
                self.sessions_recovered = sessions_recovered

            def execute(self, statement, _parameters=None):
                if "pg_blocking_pids" in statement:
                    return Cursor(self.backfill_recovered)
                return Cursor(self.sessions_recovered)

        good_status = {
            "pool_size": 10,
            "pool_available": 10,
            "requests_waiting": 0,
        }
        good_outcomes = (
            [SimpleNamespace(outcome="committed")] * 10
            + [SimpleNamespace(outcome="pool_timeout")] * 2
        )

        cases = (
            (
                "backfill_no_longer_blocking",
                Connection(backfill_recovered=False),
                good_status,
                good_outcomes,
                SimpleNamespace(outcome="committed"),
            ),
            (
                "pool_fully_available",
                Connection(),
                {**good_status, "pool_available": 9},
                good_outcomes,
                SimpleNamespace(outcome="committed"),
            ),
            (
                "no_requests_waiting",
                Connection(),
                {**good_status, "requests_waiting": 1},
                good_outcomes,
                SimpleNamespace(outcome="committed"),
            ),
            (
                "no_sessions_blocked",
                Connection(sessions_recovered=False),
                good_status,
                good_outcomes,
                SimpleNamespace(outcome="committed"),
            ),
            (
                "pool_timeout_observed",
                Connection(),
                good_status,
                [SimpleNamespace(outcome="committed")] * 10,
                SimpleNamespace(outcome="committed"),
            ),
            (
                "blocked_writers_drained",
                Connection(),
                good_status,
                [SimpleNamespace(outcome="committed")] * 9
                + [SimpleNamespace(outcome="pool_timeout")] * 3,
                SimpleNamespace(outcome="committed"),
            ),
            (
                "fresh_write_committed",
                Connection(),
                good_status,
                good_outcomes,
                SimpleNamespace(outcome="pool_timeout"),
            ),
        )

        for expected, connection, status, outcomes, fresh_result in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(
                    LiveWorkshopError,
                    rf"recovery verification failed on: {expected}$",
                ):
                    verify_recovery(
                        connection,
                        backfill_pid=42,
                        pool_status=lambda: status,
                        write_outcomes=outcomes,
                        fresh_write=lambda: fresh_result,
                    )

    def test_wave_a_captures_only_the_pre_index_checkpoints(self) -> None:
        from labs.incident.query_regression import (
            WAVE_A_CHECKPOINTS,
            WAVE_B_CHECKPOINTS,
        )

        self.assertEqual(
            WAVE_A_CHECKPOINTS,
            ("before_analyze", "after_analyze"),
        )
        self.assertEqual(WAVE_B_CHECKPOINTS, ("after_index",))
        self.assertNotIn("after_index", WAVE_A_CHECKPOINTS)

    def test_plan_checkpoints_assert_shape_not_timing(self) -> None:
        source = (LAB_DIR / "query_regression.py").read_text(encoding="utf-8")

        self.assertIn("Seq Scan", source)
        self.assertIn("Index Scan", source)
        for forbidden in ("471.75", "245.65", "2.24", "225", "219", "1.5"):
            self.assertNotIn(
                f"execution_ms == {forbidden}",
                source,
                "timings are reference observations, never assertions",
            )

    def test_drain_requires_pool_max_commits_and_no_statement_timeouts(self) -> None:
        """All pool-held writers must commit after the backfill releases."""
        from labs.incident.recovery_verifier import evaluate_drain

        def outcomes(
            committed: int,
            pool_timeout: int,
            statement_timeout: int = 0,
        ):
            return (
                [SimpleNamespace(outcome="committed")] * committed
                + [SimpleNamespace(outcome="pool_timeout")] * pool_timeout
                + [SimpleNamespace(outcome="statement_timeout")]
                * statement_timeout
            )

        self.assertTrue(evaluate_drain(outcomes(10, 2), pool_max_size=10))
        self.assertFalse(
            evaluate_drain(
                outcomes(9, 2, 1),
                pool_max_size=10,
            ),
            "a statement timeout means the statement bound was too short",
        )
        self.assertFalse(
            evaluate_drain(outcomes(9, 3), pool_max_size=10),
            "only nine commits means a blocked writer failed to drain",
        )
        self.assertTrue(
            evaluate_drain(outcomes(10, 0), pool_max_size=10),
            "pool saturation is independently verified by pool_timeout_observed",
        )


if __name__ == "__main__":
    unittest.main()
