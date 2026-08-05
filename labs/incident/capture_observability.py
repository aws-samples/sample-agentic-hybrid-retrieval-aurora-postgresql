#!/usr/bin/env python3
"""Collect AWS observations for a bounded participant-induced incident window."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
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


def _collect_cloudwatch_best_effort(
    cloudwatch,
    *,
    cluster_id: str,
    start_time: datetime,
    end_time: datetime,
) -> dict[str, Any]:
    """Return CloudWatch samples when available without gating the incident.

    PostgreSQL plus application-pool observations prove the incident. CloudWatch
    is supplemental evidence, so an unavailable metric endpoint is recorded for
    replay instead of aborting the participant's capture.
    """
    try:
        metrics = _cloudwatch_samples(
            cloudwatch,
            cluster_id=cluster_id,
            start_time=start_time,
            end_time=end_time,
        )
    except (BotoCoreError, ClientError, RuntimeError) as error:
        return {
            "cloudwatch_metrics": [],
            "cloudwatch_status": "unavailable",
            "cloudwatch_error": str(error),
        }
    return {
        "cloudwatch_metrics": metrics,
        "cloudwatch_status": "available",
        "cloudwatch_error": None,
    }


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
    sts = session.client("sts", config=config)
    cluster, instance = _validate_target(
        rds,
        database_url=database_url,
        cluster_id=cluster_id,
        instance_id=instance_id,
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
) -> dict[str, Any]:
    if end_time <= start_time:
        raise ValueError("incident end_time must be after start_time")
    config = _client_config()
    session = boto3.Session(region_name=region)
    rds = session.client("rds", config=config)
    sts = session.client("sts", config=config)
    cluster, instance = _validate_target(
        rds,
        database_url=database_url,
        cluster_id=cluster_id,
        instance_id=instance_id,
    )
    identity = _database_identity(database_url)
    cloudwatch_region = os.getenv("CLOUDWATCH_REGION", region)
    try:
        cloudwatch = boto3.Session(region_name=cloudwatch_region).client(
            "cloudwatch",
            config=config,
        )
        cloudwatch_capture = _collect_cloudwatch_best_effort(
            cloudwatch,
            cluster_id=cluster_id,
            start_time=start_time,
            end_time=end_time,
        )
    except (BotoCoreError, ClientError, RuntimeError) as error:
        cloudwatch_capture = {
            "cloudwatch_metrics": [],
            "cloudwatch_status": "unavailable",
            "cloudwatch_error": str(error),
        }
    caller = sts.get_caller_identity()
    source_apis = [
        "rds:DescribeDBClusters",
        "rds:DescribeDBInstances",
    ]
    if cloudwatch_capture["cloudwatch_status"] == "available":
        source_apis.append("cloudwatch:GetMetricStatistics")
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
                **cloudwatch_capture,
                "capture_metadata": {
                    "collected_at": datetime.now(timezone.utc),
                    "source_apis": source_apis,
                    "cloudwatch_status": cloudwatch_capture["cloudwatch_status"],
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
