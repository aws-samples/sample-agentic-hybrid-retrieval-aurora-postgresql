"""Record, and read back, whether each Mosaic event box is ready for the event.

On the box, bootstrap writes a record once its acceptance gate passes, and records
the failing step when the gate fails. A record holds the UTC time, one line per
check and a final line: READY FOR LAB 1, or the first failing check. Root keeps it
in /var/lib/mosaic-readiness/record.json, and it goes to CloudWatch Logs,
/aws/mosaic/readiness, one stream per instance. Participants never see it.

From a laptop, with an event account's Ops credentials:

    uv run scripts/event_readiness.py                      # this account's record
    uv run scripts/event_readiness.py --live               # record again now, via SSM
    uv run scripts/event_readiness.py --accounts DIR       # one row per account
    uv run scripts/event_readiness.py --accounts DIR --live

DIR holds one *.env file per account, mode 0600: the facilitator console's Ops
credential block, pasted as is, plus an AWS_DEFAULT_REGION line. The files are
parsed, never sourced, and account IDs go to the terminal only. Reading is
read-only. `--live` runs /usr/local/sbin/mosaic-readiness-record --live on the box
through SSM Run Command, which repeats the read-only checks and records again, but
only before a participant starts a lab; afterwards the row reads "lab in progress".

Exit status: 0 when every row reads READY FOR LAB 1 (and there is at least one),
1 otherwise, 2 on a usage error. A record older than --max-age-hours is STALE.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.readiness_checks import (
    Line,
)

READY = "READY FOR LAB 1"
LOG_GROUP = "/aws/mosaic/readiness"
RECORD_COMMAND = "/usr/local/sbin/mosaic-readiness-record"
STACK_PARAMETER = "InfrastructureRevision"
# The editor launcher (deploy/cloudformation/editor_launcher.py) tags every host it starts.
LAUNCHER_TAG = "eval-skills:launch-inputs"
DEFAULT_CAP_SECONDS = 90.0
DEFAULT_MAX_AGE_HOURS = 24.0
MAX_PARALLEL_ACCOUNTS = 8
LIVE_WAIT_SECONDS = 240
LIVE_POLL_SECONDS = 5
LIVE_GRACE_POLLS = 3
NESTED_STACK = "AWS::CloudFormation::Stack"
# A rollback deletes the stack's own readiness log group, and the failure record in it.
FAILED_STACK_STATES = {
    "CREATE_FAILED",
    "ROLLBACK_IN_PROGRESS",
    "ROLLBACK_COMPLETE",
    "ROLLBACK_FAILED",
}
MAX_STACKS_READ = 20
REASON_CHARS = 160
SSM_FINISHED = {"Success", "Failed", "Cancelled", "TimedOut"}
# The box refused --live because a lab has started; it wrote no record.
LAB_IN_PROGRESS_EXIT = 3
HEADERS = ("Account", "Region", "Instance", "Recorded (UTC)", "Status")
ASSIGNMENT = re.compile(
    r"(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)="
    r"(?:\"(?P<double>[^\"]*)\"|'(?P<single>[^']*)'"
    r"|(?P<bare>[^\s\"']*?)(?=\s|$|(?:export\s+)?[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]*=))"
)


class LabInProgress(Exception):
    """--live found a started lab on the box and rechecked nothing."""

    def __init__(self, lab: str, instance_id: str, previous: dict[str, Any] | None):
        super().__init__(lab)
        self.lab, self.instance_id, self.previous = lab, instance_id, previous


class CannotRead(Exception):
    """An account could not be read; `code` is the AWS error code or the reason."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Row:
    """One account in the fleet table."""

    account: str
    region: str
    instance: str
    recorded: str
    icon: str
    status: str

    @property
    def ready(self) -> bool:
        return self.icon == "✅"


# ---------------------------------------------------------------------------
# on the box
# ---------------------------------------------------------------------------


def build_record(
    lines: list[Line], *, mode: str, instance_id: str, now: datetime
) -> dict[str, Any]:
    """The record; it is ready only when some check passed and none failed."""
    failure = next((line for line in lines if line.status == "FAIL"), None)
    if failure is None and not any(line.status == "PASS" for line in lines):
        failure = Line("FAIL", "Readiness", "no check ran")
    final = READY if failure is None else f"x FAIL  {failure.name}: {failure.detail}"
    return {
        "recordedAt": now.isoformat(timespec="seconds"),
        "instanceId": instance_id,
        "mode": mode,
        "ready": failure is None,
        "final": final,
        "lines": [line.text() for line in lines],
    }


def imds_instance_id() -> str:
    """This instance's ID through IMDSv2."""
    from scripts.readiness_checks import imds

    return imds("meta-data/instance-id")


def error_code(error: Exception) -> str:
    response = getattr(error, "response", None) or {}
    return response.get("Error", {}).get("Code") or type(error).__name__


def write_cloudwatch(record: dict[str, Any], logs: Any) -> None:
    """Append the record to this instance's stream; the template owns the group."""
    stream = record["instanceId"]
    try:
        logs.create_log_stream(logGroupName=LOG_GROUP, logStreamName=stream)
    except Exception as error:
        if error_code(error) != "ResourceAlreadyExistsException":
            raise
    stamp = int(datetime.fromisoformat(record["recordedAt"]).timestamp() * 1000)
    logs.put_log_events(
        logGroupName=LOG_GROUP,
        logStreamName=stream,
        logEvents=[{"timestamp": stamp, "message": json.dumps(record)}],
    )


def box_lines(args: argparse.Namespace) -> tuple[str, list[Line]]:
    if args.failed:
        return "failed", [Line("FAIL", "Bootstrap", args.failed)]
    from scripts.readiness_checks import Context, bootstrap_gate_lines, run_checks

    with redirect_stdout(sys.stderr):
        checks = run_checks(Context.from_environment(), args.cap)
    return ("live" if args.live else "bootstrap"), [
        *bootstrap_gate_lines(args.gate_passed_at),
        *checks,
    ]


def lab_in_progress(repo: Path = REPO) -> str | None:
    """The newest lab a participant started, or why that is unknown; None if none."""
    try:
        from scripts.lab_entry import load_record

        started = [lab for lab in (1, 2, 3) if load_record(lab, repo) is not None]
    except Exception as error:  # noqa: BLE001 - unreadable state refuses the recheck
        return f"lab state unreadable: {type(error).__name__}"
    return f"Lab {started[-1]}" if started else None


def record_on_box(
    args: argparse.Namespace,
    *,
    logs: Any = None,
    busy: Callable[[], str | None] = lab_in_progress,
) -> int:
    """Run the checks, write CloudWatch, and print the record for root to keep.

    --live first reads the labs' state: once a participant has started a lab, the
    checks would run against their work, so it opens no session and writes nothing.
    """
    if args.live and (lab := busy()):
        print(json.dumps({"labInProgress": lab}))
        return LAB_IN_PROGRESS_EXIT
    mode, lines = box_lines(args)
    record = build_record(
        lines, mode=mode, instance_id=imds_instance_id(), now=datetime.now(UTC)
    )
    try:
        write_cloudwatch(record, logs or aws_client(None, "logs"))
    except Exception as error:  # noqa: BLE001 - the box keeps its local record
        print(
            f"Readiness: CloudWatch write failed ({error_code(error)}); the box keeps "
            "/var/lib/mosaic-readiness/record.json",
            file=sys.stderr,
        )
    print(json.dumps(record))
    return 0 if record["ready"] else 1


# ---------------------------------------------------------------------------
# from a laptop
# ---------------------------------------------------------------------------


def aws_client(session: Any, service: str) -> Any:
    import boto3
    from botocore.config import Config

    config = Config(
        connect_timeout=10,
        read_timeout=30,
        retries={"total_max_attempts": 3, "mode": "standard"},
    )
    return (session or boto3.Session()).client(service, config=config)


def latest_record(
    logs: Any, *, stream: str | None = None, since_ms: int | None = None
) -> dict[str, Any] | None:
    """The newest record in the log group, or None when there is none."""
    query: dict[str, Any] = {"logGroupName": LOG_GROUP}
    if stream:
        query["logStreamNames"] = [stream]
    if since_ms is not None:
        query["startTime"] = since_ms
    newest = None
    try:
        for page in logs.get_paginator("filter_log_events").paginate(**query):
            for event in page.get("events", []):
                if newest is None or event["timestamp"] >= newest["timestamp"]:
                    newest = event
    except Exception as error:
        if error_code(error) == "ResourceNotFoundException":
            return None
        raise CannotRead(error_code(error)) from error
    if newest is None:
        return None
    try:
        return json.loads(newest["message"])
    except ValueError as error:
        raise CannotRead("MalformedRecord") from error


def mosaic_stacks(cfn: Any) -> list[dict[str, Any]]:
    pages = cfn.get_paginator("describe_stacks").paginate()
    return [stack for page in pages for stack in page.get("Stacks", [])]


def root_stack(stacks: list[dict[str, Any]]) -> dict[str, Any] | None:
    roots = [
        stack
        for stack in stacks
        if not stack.get("ParentId")
        and any(
            p["ParameterKey"] == STACK_PARAMETER for p in stack.get("Parameters", [])
        )
    ]
    return max(roots, key=lambda stack: stack["CreationTime"], default=None)


def stack_events(cfn: Any, stack_id: str) -> list[dict[str, Any]]:
    pages = cfn.get_paginator("describe_stack_events").paginate(StackName=stack_id)
    return [event for page in pages for event in page.get("StackEvents", [])]


def family_events(cfn: Any, root_id: str) -> list[dict[str, Any]]:
    """Events of a stack and of every nested stack it created, deleted ones included.

    A rollback deletes the nested stacks, and DescribeStacks lists only stacks that
    still exist, so each nested stack is found by the ARN in its parent's events.
    """
    events: list[dict[str, Any]] = []
    pending, seen = [root_id], set()
    while pending and len(seen) < MAX_STACKS_READ:
        stack_id = pending.pop()
        if stack_id in seen:
            continue
        seen.add(stack_id)
        found = stack_events(cfn, stack_id)
        events += found
        pending += [
            event["PhysicalResourceId"]
            for event in found
            if event.get("ResourceType") == NESTED_STACK
            and str(event.get("PhysicalResourceId", "")).startswith("arn:")
        ]
    return events


def short_reason(text: str) -> str:
    """A reason that fits one row. A wait condition's cause ends its message."""
    reason = re.sub(r"'? for uniqueId: \S+$", "", " ".join(text.split()))
    if len(reason) <= REASON_CHARS:
        return reason
    return f"{reason[:40]} … {reason[-(REASON_CHARS - 43) :]}"


def first_failure(cfn: Any, root: dict[str, Any]) -> str:
    """The earliest failed resource's reason across the root and its nested stacks."""
    failures = [
        event
        for event in family_events(cfn, root["StackId"])
        if event.get("ResourceStatus", "").endswith("_FAILED")
        and "cancelled" not in event.get("ResourceStatusReason", "")
        and "Embedded stack" not in event.get("ResourceStatusReason", "")
    ]
    if not failures:
        return ""
    first = min(failures, key=lambda event: event["Timestamp"])
    reason = short_reason(first.get("ResourceStatusReason", ""))
    return f"{first['LogicalResourceId']}: {reason}"


def stack_state(cfn: Any) -> tuple[str, str]:
    """The Mosaic stack's status, and why it failed or why it is unknown."""
    try:
        stacks = mosaic_stacks(cfn)
        root = root_stack(stacks)
        if root is None:
            return "", "no Mosaic stack in this Region"
        status = root["StackStatus"]
        if "FAILED" not in status and "ROLLBACK" not in status:
            return status, ""
        reason = first_failure(cfn, root) or short_reason(
            root.get("StackStatusReason", "")
        )
    except Exception as error:  # noqa: BLE001 - the row still prints
        return "", f"stack unreadable: {error_code(error)}"
    return status, reason


def no_record_row(account: str, region: str, cfn: Any) -> Row:
    """An account with no record: a failed setup, or what CloudFormation says."""
    status, reason = stack_state(cfn)
    if status in FAILED_STACK_STATES:
        return Row(account, region, "-", "-", "❌", f"setup failed: {reason or status}")
    summary = ": ".join(part for part in (status, reason) if part)
    return Row(account, region, "-", "-", "⚠️", f"no record ({summary})")


def running_instance(ec2: Any) -> str | None:
    """The newest running Code Editor instance, by the editor launcher's tag."""
    pages = ec2.get_paginator("describe_instances").paginate(
        Filters=[
            {"Name": "tag-key", "Values": [LAUNCHER_TAG]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )
    instances = [
        instance
        for page in pages
        for reservation in page.get("Reservations", [])
        for instance in reservation.get("Instances", [])
    ]
    newest = max(instances, key=lambda instance: instance["LaunchTime"], default=None)
    return newest["InstanceId"] if newest else None


def box_instance(session: Any, previous: dict[str, Any] | None) -> str:
    """The instance the newest record names, or else the running Code Editor host."""
    named = (previous or {}).get("instanceId")
    if named:
        return named
    try:
        found = running_instance(aws_client(session, "ec2"))
    except Exception as error:
        raise CannotRead(error_code(error)) from error
    if not found:
        raise CannotRead("NoInstance")
    return found


def send_live(ssm: Any, instance_id: str) -> str:
    try:
        sent = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [f"{RECORD_COMMAND} --live"]},
            Comment="Mosaic event readiness",
        )
    except Exception as error:
        raise CannotRead(error_code(error)) from error
    return sent["Command"]["CommandId"]


def command_invocation(ssm: Any, command_id: str, instance_id: str) -> dict[str, Any]:
    try:
        return ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
    except Exception as error:
        if error_code(error) == "InvocationDoesNotExist":
            return {"Status": "Pending"}
        raise CannotRead(error_code(error)) from error


def refused_lab(invocation: dict[str, Any]) -> str | None:
    """The started lab a finished --live command reported, or None."""
    if invocation.get("Status") not in SSM_FINISHED:
        return None
    if invocation.get("ResponseCode") != LAB_IN_PROGRESS_EXIT:
        return None
    for line in reversed((invocation.get("StandardOutputContent") or "").splitlines()):
        try:
            return str(json.loads(line)["labInProgress"])
        except (ValueError, KeyError, TypeError):
            continue
    return "a lab"


def live_record(
    session: Any, *, sleep: Callable[[float], None] = time.sleep
) -> dict[str, Any]:
    """Record again on the box through SSM, then read that record back.

    The wrapper exits 1 for a box that is not ready, so a Failed command can still
    have written a record; CloudWatch decides, and a finished command without one
    gets a short grace for the record to arrive.
    """
    logs = aws_client(session, "logs")
    previous = latest_record(logs)
    instance_id = box_instance(session, previous)
    ssm = aws_client(session, "ssm")
    since_ms = int((datetime.now(UTC) - timedelta(seconds=60)).timestamp() * 1000)
    command_id = send_live(ssm, instance_id)
    deadline = time.monotonic() + LIVE_WAIT_SECONDS
    grace = LIVE_GRACE_POLLS
    while time.monotonic() < deadline and grace > 0:
        sleep(LIVE_POLL_SECONDS)
        invocation = command_invocation(ssm, command_id, instance_id)
        status = invocation["Status"]
        if lab := refused_lab(invocation):
            raise LabInProgress(lab, instance_id, previous)
        record = latest_record(logs, stream=instance_id, since_ms=since_ms)
        if record and record.get("mode") == "live":
            return record
        if status in SSM_FINISHED:
            grace -= 1
    if grace == 0:
        raise CannotRead(f"LiveCommand{status} on {instance_id}, and no new record")
    raise CannotRead(f"LiveRecordTimeout after {LIVE_WAIT_SECONDS} s on {instance_id}")


def age_text(hours: float) -> str:
    return f"{round(hours)} h old" if hours < 48 else f"{round(hours / 24)} days old"


def record_row(
    account: str, region: str, record: dict[str, Any], now: datetime, max_age: float
) -> Row:
    recorded = datetime.fromisoformat(record["recordedAt"])
    hours = (now - recorded).total_seconds() / 3600
    cells = (account, region, record.get("instanceId") or "-")
    when = recorded.astimezone(UTC).strftime("%Y-%m-%d %H:%M")
    if hours > max_age:
        return Row(*cells, when, "⚠️", f"STALE ({age_text(hours)})")
    if record.get("ready") is True and record.get("final") == READY:
        return Row(*cells, when, "✅", READY)
    final = str(record.get("final") or "no final line")
    return Row(*cells, when, "❌", final.removeprefix("x FAIL").strip())


def busy_row(account: str, region: str, busy: LabInProgress) -> Row:
    """A box --live left alone, shown with the record it already had."""
    previous = busy.previous or {}
    when = "-"
    if previous.get("recordedAt"):
        recorded = datetime.fromisoformat(previous["recordedAt"]).astimezone(UTC)
        when = recorded.strftime("%Y-%m-%d %H:%M")
    instance = previous.get("instanceId") or busy.instance_id
    status = f"lab in progress ({busy.lab}), not rechecked"
    return Row(account, region, instance, when, "⚠️", status)


def account_row(
    session: Any, region: str, *, live: bool, max_age: float, label: str = ""
) -> tuple[Row, dict[str, Any] | None]:
    """One account's row, and its record when there is one."""
    suffix = f" ({label})" if label else ""
    try:
        account = aws_client(session, "sts").get_caller_identity()["Account"]
    except Exception as error:  # noqa: BLE001 - the reason is the row
        return Row(
            "-", region, "-", "-", "⚠️", f"cannot read: {error_code(error)}{suffix}"
        ), None
    try:
        record = (
            live_record(session) if live else latest_record(aws_client(session, "logs"))
        )
    except CannotRead as error:
        return Row(account, region, "-", "-", "⚠️", f"cannot read: {error.code}"), None
    except LabInProgress as busy:
        return busy_row(account, region, busy), busy.previous
    if record is None:
        return no_record_row(
            account, region, aws_client(session, "cloudformation")
        ), None
    return record_row(account, region, record, datetime.now(UTC), max_age), record


def parse_credentials(text: str) -> dict[str, str]:
    """KEY=value pairs from a pasted block; never sourced, never evaluated.

    The console block has no final newline, so a region line appended with >> can
    land on the session token's line; each assignment is found on its own.
    """
    values: dict[str, str] = {}
    for raw in text.replace("\r", "").splitlines():
        if raw.lstrip().startswith("#"):
            continue
        for match in ASSIGNMENT.finditer(raw):
            value = next(
                group
                for group in (match["double"], match["single"], match["bare"])
                if group is not None
            )
            values[match["key"]] = value
    return values


def file_session(path: Path) -> tuple[Any, str]:
    """A boto3 session from one account file, and its Region."""
    if path.stat().st_mode & 0o077:
        raise CannotRead(f"FilePermissions ({path.name}; fix: chmod 600 {path.name})")
    values = parse_credentials(path.read_text(encoding="utf-8"))
    missing = [
        k for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY") if not values.get(k)
    ]
    if missing:
        raise CannotRead(f"MissingCredentials ({path.name} lacks {', '.join(missing)})")
    region = values.get("AWS_DEFAULT_REGION") or values.get("AWS_REGION")
    if not region:
        raise CannotRead(
            f"MissingRegion ({path.name}; add AWS_DEFAULT_REGION=<region>)"
        )
    import boto3

    session = boto3.Session(
        aws_access_key_id=values["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=values["AWS_SECRET_ACCESS_KEY"],
        aws_session_token=values.get("AWS_SESSION_TOKEN"),
        region_name=region,
    )
    return session, region


def file_row(path: Path, *, live: bool, max_age: float) -> Row:
    """One account file's row; any failure becomes that row's reason."""
    try:
        session, region = file_session(path)
    except CannotRead as error:
        return Row("-", "-", "-", "-", "⚠️", f"cannot read: {error.code}")
    except OSError as error:
        return Row(
            "-",
            "-",
            "-",
            "-",
            "⚠️",
            f"cannot read: {type(error).__name__} ({path.name})",
        )
    try:
        return account_row(
            session, region, live=live, max_age=max_age, label=path.name
        )[0]
    except Exception as error:  # noqa: BLE001 - one account must not hide the others
        return Row(
            "-",
            region,
            "-",
            "-",
            "⚠️",
            f"cannot read: {error_code(error)} ({path.name})",
        )


def fleet_rows(
    directory: Path, *, live: bool, max_age: float, row: Callable[..., Row] = file_row
) -> list[Row]:
    """One row per *.env file, in file-name order, at most eight accounts at once."""
    files = sorted(directory.glob("*.env"))
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_ACCOUNTS) as pool:
        return list(pool.map(lambda path: row(path, live=live, max_age=max_age), files))


def table(rows: list[Row]) -> list[str]:
    cells = [
        (r.account, r.region, r.instance, r.recorded, f"{r.icon} {r.status}")
        for r in rows
    ]
    widths = [
        max([len(h), *(len(c[i]) for c in cells)]) for i, h in enumerate(HEADERS[:-1])
    ]

    def line(values: tuple[str, ...]) -> str:
        padded = (v.ljust(w) for v, w in zip(values[:-1], widths, strict=True))
        return "   ".join([*padded, values[-1]])

    ready = sum(row.ready for row in rows)
    return [line(HEADERS), *(line(c) for c in cells), f"{ready} of {len(rows)} ready"]


def exit_status(rows: list[Row]) -> int:
    return 0 if rows and all(row.ready for row in rows) else 1


# ---------------------------------------------------------------------------


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    cli.add_argument(
        "--accounts",
        type=Path,
        metavar="DIR",
        help="one *.env Ops credential file per account",
    )
    cli.add_argument(
        "--live",
        action="store_true",
        help="record again on each box through SSM Run Command",
    )
    cli.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS)
    box = cli.add_argument_group("on the box: bootstrap and SSM only")
    box.add_argument("--record", action="store_true", help=argparse.SUPPRESS)
    box.add_argument("--failed", metavar="REASON", help=argparse.SUPPRESS)
    box.add_argument("--gate-passed-at", metavar="UTC", help=argparse.SUPPRESS)
    box.add_argument(
        "--cap", type=float, default=DEFAULT_CAP_SECONDS, help=argparse.SUPPRESS
    )
    return cli


def validate(cli: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.record and args.accounts:
        cli.error("--record runs on the box; --accounts runs on a laptop")
    if args.failed and not args.record:
        cli.error("--failed belongs to --record")
    if args.max_age_hours <= 0:
        cli.error(f"--max-age-hours must be positive, not {args.max_age_hours:g}")
    if args.accounts and not args.accounts.is_dir():
        cli.error(f"--accounts {args.accounts} is not a directory")


def one_account(args: argparse.Namespace) -> int:
    import boto3

    session = boto3.Session()
    if not session.region_name:
        print("Readiness: no Region; set AWS_DEFAULT_REGION with the Ops credentials.")
        return 2
    row, record = account_row(
        session, session.region_name, live=args.live, max_age=args.max_age_hours
    )
    print("\n".join(table([row])))
    for text in (record or {}).get("lines", []):
        print(f"  {text}")
    return exit_status([row])


def main(argv: list[str] | None = None) -> int:
    cli = parser()
    args = cli.parse_args(argv)
    validate(cli, args)
    if args.record:
        return record_on_box(args)
    if args.accounts:
        rows = fleet_rows(args.accounts, live=args.live, max_age=args.max_age_hours)
        print("\n".join(table(rows)))
        return exit_status(rows)
    return one_account(args)


if __name__ == "__main__":
    sys.exit(main())
