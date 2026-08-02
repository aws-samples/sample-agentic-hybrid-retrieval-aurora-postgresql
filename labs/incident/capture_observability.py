#!/usr/bin/env python3
"""Collect AWS observations for a bounded participant-induced incident window."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any

import boto3
from botocore.config import Config
import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row


METRICS = (
    "WriteLatency",
    "WriteIOPS",
    "WriteThroughput",
    "CommitThroughput",
    "DatabaseConnections",
)
PERIOD_SECONDS = 60
MAX_PI_SQL_DOCUMENTS = 7


def _client_config() -> Config:
    return Config(
        retries={"total_max_attempts": 5, "mode": "adaptive"},
        connect_timeout=10,
        read_timeout=60,
    )


def _validate_target(
    rds,
    *,
    database_url: str,
    cluster_id: str,
    instance_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    instance = rds.describe_db_instances(
        DBInstanceIdentifier=instance_id
    )["DBInstances"][0]
    cluster = rds.describe_db_clusters(
        DBClusterIdentifier=cluster_id
    )["DBClusters"][0]
    if instance.get("DBClusterIdentifier") != cluster_id:
        raise RuntimeError(f"{instance_id} does not belong to {cluster_id}")
    writer_ids = {
        member["DBInstanceIdentifier"]
        for member in cluster.get("DBClusterMembers", [])
        if member.get("IsClusterWriter")
    }
    if instance_id not in writer_ids:
        raise RuntimeError(
            f"{instance_id} is not the writer for Aurora cluster {cluster_id}"
        )
    if not instance.get("PerformanceInsightsEnabled"):
        raise RuntimeError(
            f"{instance_id} does not have Performance Insights enabled"
        )
    configured_host = conninfo_to_dict(database_url).get("host")
    if configured_host != cluster.get("Endpoint"):
        raise RuntimeError(
            "DATABASE_URL host does not match the requested Aurora writer endpoint"
        )
    return cluster, instance


def _database_identity(database_url: str) -> dict[str, Any]:
    with psycopg.connect(
        database_url,
        autocommit=True,
        row_factory=dict_row,
        application_name="workbench-live-aws-identity",
    ) as connection:
        row = connection.execute(
            """
            SELECT
              current_database() AS database_name,
              aurora_version() AS aurora_version,
              current_setting('server_version') AS engine_version
            """
        ).fetchone()
    if row is None:
        raise RuntimeError("Aurora did not return database identity")
    return dict(row)


def _pi_rows(
    pi,
    *,
    resource_id: str,
    start_time: datetime,
    end_time: datetime,
    group: str,
    limit: int = 25,
) -> list[dict[str, Any]]:
    response = pi.get_resource_metrics(
        ServiceType="RDS",
        Identifier=resource_id,
        MetricQueries=[
            {
                "Metric": "db.load.avg",
                "GroupBy": {"Group": group, "Limit": limit},
            }
        ],
        StartTime=start_time,
        EndTime=end_time,
        PeriodInSeconds=PERIOD_SECONDS,
    )
    return response.get("MetricList", [])


def _points_in_window(
    row: dict[str, Any],
    *,
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    return [
        point
        for point in row.get("DataPoints", [])
        if point.get("Timestamp")
        and point["Timestamp"] <= end_time
        and point["Timestamp"] + timedelta(seconds=PERIOD_SECONDS) >= start_time
    ]


def _wait_for_database_insights(
    pi,
    *,
    resource_id: str,
    start_time: datetime,
    end_time: datetime,
    wait_seconds: int,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + wait_seconds
    while True:
        query_end = max(
            datetime.now(timezone.utc),
            end_time + timedelta(seconds=PERIOD_SECONDS),
        )
        wait_rows = _pi_rows(
            pi,
            resource_id=resource_id,
            start_time=start_time - timedelta(minutes=1),
            end_time=query_end,
            group="db.wait_event",
        )
        matching_waits: list[dict[str, Any]] = []
        for row in wait_rows:
            dimensions = row.get("Key", {}).get("Dimensions", {})
            if str(dimensions.get("db.wait_event.name", "")).casefold() != (
                "lock:relation"
            ):
                continue
            points = _points_in_window(
                row,
                start_time=start_time,
                end_time=end_time,
            )
            if not points:
                continue
            point = max(points, key=lambda item: item["Timestamp"])
            matching_waits.append(
                {
                    "evidence_type": "top_wait",
                    "captured_at": point["Timestamp"],
                    "dimension": "db.wait_event.name",
                    "dimension_value": "Lock:relation",
                    "db_load": point["Value"],
                    "statement": None,
                    "query_id": None,
                    "source_api": "pi:GetResourceMetrics",
                    "raw_payload": row,
                }
            )
        if matching_waits:
            sql_observations: list[dict[str, Any]] = []
            for row in _pi_rows(
                pi,
                resource_id=resource_id,
                start_time=start_time - timedelta(minutes=1),
                end_time=query_end,
                group="db.sql",
            ):
                dimensions = row.get("Key", {}).get("Dimensions", {})
                statement = dimensions.get("db.sql.statement")
                points = _points_in_window(
                    row,
                    start_time=start_time,
                    end_time=end_time,
                )
                if not statement or not points:
                    continue
                point = max(points, key=lambda item: item["Timestamp"])
                sql_observations.append(
                    {
                        "evidence_type": "top_sql",
                        "captured_at": point["Timestamp"],
                        "dimension": "db.sql.id",
                        "dimension_value": dimensions.get(
                            "db.sql.id", "not-published"
                        ),
                        "db_load": point["Value"],
                        "statement": statement,
                        "query_id": dimensions.get("db.sql.id"),
                        "source_api": "pi:GetResourceMetrics",
                        "raw_payload": row,
                    }
                )
            sql_observations.sort(
                key=lambda observation: float(observation["db_load"] or 0),
                reverse=True,
            )
            matching_waits.sort(
                key=lambda observation: float(observation["db_load"] or 0),
                reverse=True,
            )
            selected_sql = sql_observations[:MAX_PI_SQL_DOCUMENTS]
            if any(
                "create index" in str(observation["statement"]).casefold()
                for observation in selected_sql
            ):
                return [matching_waits[0], *selected_sql]
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "Performance Insights did not publish this run's Lock:relation "
                "wait and ordinary CREATE INDEX SQL before timeout"
            )
        time.sleep(15)


def _cloudwatch_samples(
    cloudwatch,
    *,
    cluster_id: str,
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for metric_name in METRICS:
        response = cloudwatch.get_metric_statistics(
            Namespace="AWS/RDS",
            MetricName=metric_name,
            Dimensions=[
                {"Name": "DBClusterIdentifier", "Value": cluster_id}
            ],
            StartTime=start_time - timedelta(minutes=1),
            EndTime=end_time + timedelta(minutes=1),
            Period=PERIOD_SECONDS,
            Statistics=["Average"],
        )
        points = [
            point
            for point in response.get("Datapoints", [])
            if point.get("Timestamp")
            and point["Timestamp"] <= end_time
            and point["Timestamp"] + timedelta(seconds=PERIOD_SECONDS)
            >= start_time
        ]
        if not points:
            raise RuntimeError(
                f"CloudWatch returned no incident-window {metric_name} datapoint"
            )
        point = max(points, key=lambda item: item["Timestamp"])
        samples.append(
            {
                "metric_name": metric_name,
                "namespace": "AWS/RDS",
                "dimension_name": "DBClusterIdentifier",
                "dimension_value": cluster_id,
                "statistic": "Average",
                "period_seconds": PERIOD_SECONDS,
                "observed_at": point["Timestamp"],
                "period_start": point["Timestamp"],
                "period_end": point["Timestamp"]
                + timedelta(seconds=PERIOD_SECONDS),
                "value": point["Average"],
                "unit": point["Unit"],
                "raw_datapoint": point,
            }
        )
    return samples


def preflight_aws_observability(
    *,
    database_url: str,
    region: str,
    cluster_id: str,
    instance_id: str,
) -> dict[str, Any]:
    session = boto3.Session(region_name=region)
    config = _client_config()
    rds = session.client("rds", config=config)
    cloudwatch = session.client("cloudwatch", config=config)
    pi = session.client("pi", config=config)
    sts = session.client("sts", config=config)
    cluster, instance = _validate_target(
        rds,
        database_url=database_url,
        cluster_id=cluster_id,
        instance_id=instance_id,
    )
    now = datetime.now(timezone.utc)
    cloudwatch.get_metric_statistics(
        Namespace="AWS/RDS",
        MetricName="DatabaseConnections",
        Dimensions=[{"Name": "DBClusterIdentifier", "Value": cluster_id}],
        StartTime=now - timedelta(minutes=5),
        EndTime=now,
        Period=PERIOD_SECONDS,
        Statistics=["Average"],
    )
    _pi_rows(
        pi,
        resource_id=instance["DbiResourceId"],
        start_time=now - timedelta(minutes=5),
        end_time=now,
        group="db.wait_event",
        limit=1,
    )
    caller = sts.get_caller_identity()
    return {
        "cluster_id": cluster["DBClusterIdentifier"],
        "instance_id": instance["DBInstanceIdentifier"],
        "db_resource_id": instance["DbiResourceId"],
        "caller_arn": caller["Arn"],
    }


def collect_aws_observability(
    *,
    database_url: str,
    region: str,
    cluster_id: str,
    instance_id: str,
    start_time: datetime,
    end_time: datetime,
    wait_seconds: int = 300,
) -> dict[str, Any]:
    if end_time <= start_time:
        raise ValueError("incident end_time must be after start_time")
    config = _client_config()
    session = boto3.Session(region_name=region)
    rds = session.client("rds", config=config)
    cloudwatch = session.client("cloudwatch", config=config)
    pi = session.client("pi", config=config)
    sts = session.client("sts", config=config)
    cluster, instance = _validate_target(
        rds,
        database_url=database_url,
        cluster_id=cluster_id,
        instance_id=instance_id,
    )
    identity = _database_identity(database_url)
    insights = _wait_for_database_insights(
        pi,
        resource_id=instance["DbiResourceId"],
        start_time=start_time,
        end_time=end_time,
        wait_seconds=wait_seconds,
    )
    metrics = _cloudwatch_samples(
        cloudwatch,
        cluster_id=cluster_id,
        start_time=start_time,
        end_time=end_time,
    )
    caller = sts.get_caller_identity()
    return json.loads(
        json.dumps(
            {
                "database": {
                    "cluster_id": cluster_id,
                    "instance_id": instance_id,
                    "db_resource_id": instance["DbiResourceId"],
                    "database_name": identity["database_name"],
                    "engine": "aurora-postgresql",
                    "engine_version": cluster["EngineVersion"],
                    "aurora_version": identity["aurora_version"],
                    "aws_region": region,
                    "instance_class": instance["DBInstanceClass"],
                    "endpoint": cluster["Endpoint"],
                },
                "observation_window": {
                    "start": start_time,
                    "end": end_time,
                },
                "cloudwatch_metrics": metrics,
                "database_insights": insights,
                "capture_metadata": {
                    "collected_at": datetime.now(timezone.utc),
                    "source_apis": [
                        "rds:DescribeDBClusters",
                        "rds:DescribeDBInstances",
                        "cloudwatch:GetMetricStatistics",
                        "pi:GetResourceMetrics",
                    ],
                    "caller_arn": caller["Arn"],
                    "aws_account_id": caller["Account"],
                },
            },
            default=str,
        )
    )


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
