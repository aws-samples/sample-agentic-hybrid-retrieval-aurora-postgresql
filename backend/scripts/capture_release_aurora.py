from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from psycopg.conninfo import conninfo_to_dict

sys.path.append(str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[2]))

from seed.capture import (
    capture_bundle_digest,
    capture_offline_lock_fixture,
    validate_capture_bundle,
)


METRICS = (
    "WriteLatency",
    "WriteIOPS",
    "WriteThroughput",
    "CommitThroughput",
    "DatabaseConnections",
)
PERIOD_SECONDS = 60


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture controlled Aurora lock evidence plus CloudWatch and "
            "Performance Insights observations for the release corpus."
        )
    )
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--db-cluster-identifier", required=True)
    parser.add_argument("--db-instance-identifier", required=True)
    parser.add_argument("--row-count", type=int, default=25_000)
    parser.add_argument("--hold-seconds", type=float, default=75.0)
    parser.add_argument("--metrics-wait-seconds", type=int, default=300)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/generated/release-aurora-capture.json"),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing output only after a new capture succeeds",
    )
    return parser


def _latest_datapoint(response: dict[str, Any], metric_name: str) -> dict[str, Any]:
    datapoints = response.get("Datapoints", [])
    if not datapoints:
        raise RuntimeError(f"CloudWatch returned no {metric_name} datapoints")
    return max(datapoints, key=lambda point: point["Timestamp"])


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
                {
                    "Name": "DBClusterIdentifier",
                    "Value": cluster_id,
                }
            ],
            StartTime=start_time - timedelta(minutes=2),
            EndTime=end_time + timedelta(minutes=2),
            Period=PERIOD_SECONDS,
            Statistics=["Average"],
        )
        datapoint = _latest_datapoint(response, metric_name)
        samples.append(
            {
                "metric_name": metric_name,
                "namespace": "AWS/RDS",
                "dimension_name": "DBClusterIdentifier",
                "dimension_value": cluster_id,
                "statistic": "Average",
                "period_seconds": PERIOD_SECONDS,
                "observed_at": datapoint["Timestamp"],
                "value": datapoint["Average"],
                "unit": datapoint["Unit"],
                "raw_datapoint": datapoint,
            }
        )
    return samples


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


def _wait_for_lock_sample(
    pi,
    *,
    resource_id: str,
    start_time: datetime,
    wait_seconds: int,
) -> tuple[dict[str, Any], datetime]:
    deadline = time.monotonic() + wait_seconds
    while True:
        end_time = datetime.now(timezone.utc)
        rows = _pi_rows(
            pi,
            resource_id=resource_id,
            start_time=start_time - timedelta(minutes=2),
            end_time=end_time,
            group="db.wait_event",
        )
        for row in rows:
            dimensions = row.get("Key", {}).get("Dimensions", {})
            wait_name = str(dimensions.get("db.wait_event.name", ""))
            if wait_name.casefold() != "lock:relation":
                continue
            datapoints = row.get("DataPoints", [])
            if datapoints:
                return row, end_time
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "Performance Insights did not publish Lock:relation before timeout"
            )
        time.sleep(15)


def _database_insights_samples(
    pi,
    *,
    resource_id: str,
    start_time: datetime,
    wait_seconds: int,
) -> tuple[list[dict[str, Any]], datetime]:
    wait_row, end_time = _wait_for_lock_sample(
        pi,
        resource_id=resource_id,
        start_time=start_time,
        wait_seconds=wait_seconds,
    )
    wait_point = max(wait_row["DataPoints"], key=lambda point: point["Timestamp"])
    wait_dimensions = wait_row["Key"]["Dimensions"]
    samples = [
        {
            "evidence_type": "top_wait",
            "captured_at": wait_point["Timestamp"],
            "dimension": "db.wait_event.name",
            "dimension_value": "Lock:relation",
            "db_load": wait_point["Value"],
            "statement": None,
            "query_id": None,
            "source_api": "pi:GetResourceMetrics",
            "raw_payload": wait_row,
        }
    ]

    for row in _pi_rows(
        pi,
        resource_id=resource_id,
        start_time=start_time - timedelta(minutes=2),
        end_time=end_time,
        group="db.sql",
    ):
        dimensions = row.get("Key", {}).get("Dimensions", {})
        statement = dimensions.get("db.sql.statement")
        datapoints = row.get("DataPoints", [])
        if not statement or not datapoints:
            continue
        point = max(datapoints, key=lambda item: item["Timestamp"])
        samples.append(
            {
                "evidence_type": "top_sql",
                "captured_at": point["Timestamp"],
                "dimension": "db.sql.id",
                "dimension_value": dimensions.get("db.sql.id", "unknown"),
                "db_load": point["Value"],
                "statement": statement,
                "query_id": dimensions.get("db.sql.id"),
                "source_api": "pi:GetResourceMetrics",
                "raw_payload": row,
            }
        )
    return samples, end_time


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
        raise RuntimeError(f"{instance_id} does not have Performance Insights enabled")
    configured_host = conninfo_to_dict(database_url).get("host")
    if configured_host != cluster.get("Endpoint"):
        raise RuntimeError(
            "DATABASE_URL host does not match the requested Aurora cluster endpoint"
        )
    return cluster, instance


def build_release_capture(args: argparse.Namespace) -> dict[str, Any]:
    if os.getenv("ALLOW_RELEASE_CAPTURE") != "1":
        raise RuntimeError(
            "set ALLOW_RELEASE_CAPTURE=1 after confirming the target Aurora cluster"
        )
    if not args.database_url:
        raise RuntimeError("DATABASE_URL or --database-url is required")
    if args.hold_seconds < PERIOD_SECONDS:
        raise RuntimeError("--hold-seconds must be at least 60")

    config = Config(
        retries={"total_max_attempts": 5, "mode": "adaptive"},
        connect_timeout=10,
        read_timeout=60,
    )
    session = boto3.Session(region_name=args.region)
    rds = session.client("rds", config=config)
    cloudwatch = session.client("cloudwatch", config=config)
    pi = session.client("pi", config=config)
    sts = session.client("sts", config=config)

    cluster, instance = _validate_target(
        rds,
        database_url=args.database_url,
        cluster_id=args.db_cluster_identifier,
        instance_id=args.db_instance_identifier,
    )
    caller = sts.get_caller_identity()
    capture_started = datetime.now(timezone.utc)
    bundle = capture_offline_lock_fixture(
        args.database_url,
        row_count=args.row_count,
        hold_seconds=args.hold_seconds,
        timeout_seconds=30.0,
    )

    insights, metrics_end = _database_insights_samples(
        pi,
        resource_id=instance["DbiResourceId"],
        start_time=capture_started,
        wait_seconds=args.metrics_wait_seconds,
    )
    bundle["cloudwatch_metrics"] = _cloudwatch_samples(
        cloudwatch,
        cluster_id=args.db_cluster_identifier,
        start_time=capture_started,
        end_time=metrics_end,
    )
    bundle["database_insights"] = insights

    capture = bundle["capture"]
    capture["capture_key"] = "CAP-AURORA-" + capture_started.strftime(
        "%Y%m%dT%H%M%SZ"
    )
    capture["capture_mode"] = "release_aurora"
    capture["engine_version"] = cluster["EngineVersion"]
    capture["instance_class"] = instance["DBInstanceClass"]
    capture["source_bundle_uri"] = (
        f"workshop://capture-bundles/{capture['capture_key']}"
    )
    capture["release_verified_at"] = datetime.now(timezone.utc)
    capture["capture_tool_version"] = "workbench-aurora-release-capture-v1"
    capture["manifest"] = {
        "capture_method": "post_build_transaction_hold",
        "release_evidence": True,
        "db_cluster_identifier": args.db_cluster_identifier,
        "db_instance_identifier": args.db_instance_identifier,
        "dbi_resource_id": instance["DbiResourceId"],
        "signature": {
            "type": "aws-caller-attestation",
            "principal_arn": caller["Arn"],
            "account_id": caller["Account"],
            "request_id": caller["ResponseMetadata"]["RequestId"],
            "verification": "metadata-only",
        },
        "note": (
            "Controlled synthetic lock capture on the target Aurora instance. "
            "The bundle digest detects content changes; caller identity is an "
            "attestation, not a cryptographic signature."
        ),
    }
    capture["source_bundle_sha256"] = capture_bundle_digest(bundle)
    validate_capture_bundle(bundle, require_release=True)
    return json.loads(json.dumps(bundle, default=str))


def _write_capture(
    output: Path,
    bundle: dict[str, Any],
    *,
    force: bool,
) -> None:
    if output.exists() and not force:
        raise RuntimeError(
            f"{output} already exists; pass --force to replace it after a "
            "successful capture"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(bundle, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(output)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    args = _parser().parse_args()
    try:
        bundle = build_release_capture(args)
        _write_capture(args.output, bundle, force=args.force)
    except (ClientError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    capture = bundle["capture"]
    print(f"capture: {capture['capture_key']}")
    print(f"target: {capture['instance_class']} Aurora PostgreSQL")
    print(f"sha256: {capture['source_bundle_sha256']}")
    print(f"output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
