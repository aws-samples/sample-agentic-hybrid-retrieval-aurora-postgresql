from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from labs.incident.capture_observability import (
    METRICS,
    _cloudwatch_samples,
    _wait_for_database_insights,
    _validate_target,
    _write_atomic,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


class FakeCloudWatch:
    def get_metric_statistics(self, **kwargs):
        return {
            "Datapoints": [
                {
                    "Timestamp": NOW,
                    "Average": 1.0,
                    "Unit": "Count",
                }
            ]
        }


class FakePerformanceInsights:
    def get_resource_metrics(self, **kwargs):
        group = kwargs["MetricQueries"][0]["GroupBy"]["Group"]
        if group == "db.wait_event":
            return {
                "MetricList": [
                    {
                        "Key": {
                            "Dimensions": {
                                "db.wait_event.name": "Lock:Relation",
                                "db.wait_event.type": "Lock",
                            }
                        },
                        "DataPoints": [{"Timestamp": NOW, "Value": 1.5}],
                    }
                ]
            }
        return {
            "MetricList": [
                {
                    "Key": {
                        "Dimensions": {
                            "db.sql.id": "sql-1",
                            "db.sql.statement": (
                                "CREATE INDEX idx_orders_customer_created "
                                "ON workbench_lab.orders(customer_id, created_at DESC)"
                            ),
                        }
                    },
                    "DataPoints": [{"Timestamp": NOW, "Value": 1.25}],
                }
            ]
        }


class FakeRds:
    def __init__(self, *, writer: bool = True):
        self.writer = writer

    def describe_db_instances(self, **kwargs):
        return {
            "DBInstances": [
                {
                    "DBInstanceIdentifier": kwargs["DBInstanceIdentifier"],
                    "DBClusterIdentifier": "cluster-1",
                    "PerformanceInsightsEnabled": True,
                }
            ]
        }

    def describe_db_clusters(self, **kwargs):
        return {
            "DBClusters": [
                {
                    "DBClusterIdentifier": kwargs["DBClusterIdentifier"],
                    "Endpoint": "cluster-1.example",
                    "DBClusterMembers": [
                        {
                            "DBInstanceIdentifier": "instance-1",
                            "IsClusterWriter": self.writer,
                        }
                    ],
                }
            ]
        }


class LiveObservabilityCaptureTests(unittest.TestCase):
    def test_live_guard_accepts_server_wait_event_casing(self) -> None:
        diagnostics = (
            Path(__file__).resolve().parents[2] / "sql" / "04_diagnostics.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("lower(activity.wait_event) = 'relation'", diagnostics)

    def test_cloudwatch_contract_uses_real_aurora_metrics(self) -> None:
        samples = _cloudwatch_samples(
            FakeCloudWatch(),
            cluster_id="cluster-1",
            start_time=NOW,
            end_time=NOW,
        )

        self.assertEqual(
            {sample["metric_name"] for sample in samples},
            set(METRICS),
        )
        self.assertTrue(
            all(sample["dimension_name"] == "DBClusterIdentifier" for sample in samples)
        )

    def test_pi_relation_wait_is_normalized_to_postgresql_spelling(self) -> None:
        samples = _wait_for_database_insights(
            FakePerformanceInsights(),
            resource_id="db-resource-1",
            start_time=NOW,
            end_time=NOW + timedelta(seconds=30),
            wait_seconds=0,
        )

        self.assertEqual(samples[0]["dimension_value"], "Lock:relation")
        self.assertEqual(
            samples[0]["raw_payload"]["Key"]["Dimensions"]["db.wait_event.name"],
            "Lock:Relation",
        )
        self.assertIn("CREATE INDEX", samples[1]["statement"])

    def test_target_requires_the_writer_instance(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "is not the writer"):
            _validate_target(
                FakeRds(writer=False),
                database_url="postgresql://cluster-1.example/retrieval",
                cluster_id="cluster-1",
                instance_id="instance-1",
            )

    def test_capture_output_is_atomic_and_replaces_the_prior_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "capture.json"
            _write_atomic(output, {"capture": {"version": 1}})
            _write_atomic(output, {"capture": {"version": 2}})
            self.assertIn('"version": 2', output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
