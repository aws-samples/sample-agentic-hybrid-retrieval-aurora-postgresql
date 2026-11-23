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
import csv
import errno
import io
import json
import math
import os
import re
import stat
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.readiness_checks import (
    Line,
    error_code,
)

READY = "READY FOR LAB 1"
LOG_GROUP = "/aws/mosaic/readiness"
RECORD_COMMAND = "/usr/local/sbin/mosaic-readiness-record"
STACK_PARAMETER = "InfrastructureRevision"
# The editor launcher (deploy/cloudformation/editor_launcher.py) tags every host it starts.
DEFAULT_CAP_SECONDS = 90.0
DEFAULT_MAX_AGE_HOURS = 24.0
# The morning recheck reads a run saved the day before, after provisioning.
RECHECK_MAX_AGE_HOURS = 36.0
SAVE_VERSION = 1
# A credential file, the Teams CSV or a saved run is far smaller than this.
MAX_INPUT_BYTES = 4 * 1024 * 1024
# Lines after the first in `ls -led` that list a macOS access control entry.
ACL_ENTRY = re.compile(r"\s*\d+: ")
# Every saved account entry has exactly these fields, of these types.
SAVED_FIELDS = {
    "region": str,
    "instance": str,
    "recorded": str,
    "ready": bool,
    "status": str,
    "storefront": str,
    "editor": str,
    "checkedAt": str,
}
# Above this, a typo such as 1e9 would switch STALE off.
MAX_AGE_LIMIT_HOURS = 72.0
# The table and the saved run show a record's time in UTC to the minute.
SHOWN_TIME = "%Y-%m-%d %H:%M"
# A spreadsheet that reopened the Teams CSV may have dropped leading zeros.
ACCOUNT_DIGITS = re.compile(r"[0-9]{1,12}")
TEAM_COLUMNS = ("Team name", "AWS account ID")
MAX_PARALLEL_ACCOUNTS = 8
LIVE_WAIT_SECONDS = 240
LIVE_POLL_SECONDS = 5
LIVE_GRACE_POLLS = 3
NESTED_STACK = "AWS::CloudFormation::Stack"
MAX_STACKS_READ = 20
NO_STACK = "no workshop stack in this Region"
# The participant's browser path, read from the laptop with no token and no claim.
STOREFRONT_OUTPUT = "MosaicURL"
# The nested Code Editor stack names the exact instance it created.
EDITOR_INSTANCE_OUTPUT = "EditorInstanceId"
EDITOR_OUTPUT = "CodeEditorURL"
WEB_TIMEOUT_SECONDS = 15
WEB_DEADLINE_SECONDS = 20
# Readiness reaches Aurora and gets one more try than the page and the editor.
WEB_ATTEMPTS = 3
PAGE_ATTEMPTS = 2
WEB_BUDGET_SECONDS = 60
WEB_PAUSE_SECONDS = 5
WEB_BODY_BYTES = 65536
WEB_AGENT = "mosaic-event-readiness"
# Both URLs come from the stack's outputs; anything else is never fetched.
WEB_HOST_SUFFIX = ".cloudfront.net"
MAX_EVENT_PAGES = 20
# The root's own operation start: failures before it belong to an older operation.
OPERATION_STARTS = {"CREATE_IN_PROGRESS", "UPDATE_IN_PROGRESS", "IMPORT_IN_PROGRESS"}
TERMINAL_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|[\x00-\x1f\x7f-\x9f]")
UNREADABLE_STACK = "stack unreadable: "
# Only a finished, non-rollback root lets the box's record decide the row.
COMPLETE_STACK_STATES = {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}
RUNNING_STACK_STATES = {
    "CREATE_IN_PROGRESS",
    "UPDATE_IN_PROGRESS",
    "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
}
LOG_LOOKBACK = timedelta(days=14)
MAX_LOG_PAGES = 100
FUTURE_SKEW = timedelta(minutes=5)
REGION_NAME = re.compile(r"[a-z]{2}(?:-[a-z]+)+-\d+")
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
    storefront: str = field(default="", compare=False)
    editor: str = field(default="", compare=False)

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


def received(event: dict[str, Any]) -> tuple[int, int]:
    """When CloudWatch received a log event, then the time its sender stamped."""
    return event.get("ingestionTime", event["timestamp"]), event["timestamp"]


def latest_record(
    logs: Any, *, stream: str | None = None, since_ms: int | None = None
) -> dict[str, Any] | None:
    """The newest record in the log group, or None when there is none."""
    query: dict[str, Any] = {"logGroupName": LOG_GROUP}
    if stream:
        query["logStreamNames"] = [stream]
    if since_ms is None:
        since_ms = int((datetime.now(UTC) - LOG_LOOKBACK).timestamp() * 1000)
    query["startTime"] = since_ms
    newest = None
    try:
        pages = logs.get_paginator("filter_log_events").paginate(**query)
        for number, page in enumerate(pages, start=1):
            if number > MAX_LOG_PAGES:
                raise CannotRead("TooManyLogEvents")
            for event in page.get("events", []):
                if newest is None or received(event) >= received(newest):
                    newest = event
    except CannotRead:
        raise
    except Exception as error:
        if error_code(error) == "ResourceNotFoundException":
            return None
        raise CannotRead(error_code(error)) from error
    if newest is None:
        return None
    try:
        found = json.loads(newest["message"])
    except ValueError as error:
        raise CannotRead("MalformedRecord") from error
    if isinstance(found, dict) and "ingestionTime" in newest:
        # AWS's clock, not the box's: it judges whether the record is this stack's.
        found["ingestedAt"] = datetime.fromtimestamp(
            newest["ingestionTime"] / 1000, UTC
        ).isoformat()
    return found


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
    events: list[dict[str, Any]] = []
    for number, page in enumerate(pages, start=1):
        if number > MAX_EVENT_PAGES:
            break
        events += page.get("StackEvents", [])
    return events


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
        try:
            found = stack_events(cfn, stack_id)
        except Exception:  # one vanished nested stack must not hide the others
            if stack_id == root_id:
                raise
            continue
        events += found
        pending += [
            event["PhysicalResourceId"]
            for event in found
            if event.get("ResourceType") == NESTED_STACK
            and str(event.get("PhysicalResourceId", "")).startswith("arn:")
        ]
    return events


UNPRINTABLE = {"Cc", "Cf", "Cs", "Co", "Cn"}


def printable(text: str) -> str:
    """Every control, format (bidi overrides included), surrogate, private-use or
    unassigned character becomes "?", so no cell can rewrite the terminal or reorder
    what is shown. Emoji and their variation selectors are marks, so they survive."""
    return "".join(
        "?" if unicodedata.category(char) in UNPRINTABLE else char for char in text
    )


def plain(text: str, limit: int = 400) -> str:
    """Text safe for one table cell: no terminal escapes or control characters."""
    flat = printable(" ".join(TERMINAL_ESCAPE.sub(" ", text).split()))
    return flat if len(flat) <= limit else f"{flat[: limit - 1]}…"


def short_reason(text: str) -> str:
    """A reason that fits one row. A wait condition's cause ends its message."""
    reason = re.sub(r"'? for uniqueId: \S+$", "", plain(text, limit=len(text)))
    if len(reason) <= REASON_CHARS:
        return reason
    return f"{reason[:40]} … {reason[-(REASON_CHARS - 43) :]}"


def first_failure(cfn: Any, root: dict[str, Any]) -> str:
    """The earliest failed resource's reason across the root and its nested stacks."""
    events = family_events(cfn, root["StackId"])
    starts = [
        event["Timestamp"]
        for event in events
        if event.get("PhysicalResourceId") == root["StackId"]
        and event.get("ResourceType") == NESTED_STACK
        and event.get("ResourceStatus") in OPERATION_STARTS
    ]
    since = max(starts, default=None)
    failures = [
        event
        for event in events
        if (since is None or event["Timestamp"] >= since)
        and event.get("ResourceStatus", "").endswith("_FAILED")
        and "cancelled" not in event.get("ResourceStatusReason", "")
        and "Embedded stack" not in event.get("ResourceStatusReason", "")
    ]
    if not failures:
        return ""
    first = min(failures, key=lambda event: event["Timestamp"])
    reason = short_reason(first.get("ResourceStatusReason", ""))
    return f"{first['LogicalResourceId']}: {reason}"


def stack_facts(cfn: Any) -> tuple[str, str, dict[str, Any], str | None]:
    """From one stack listing: the status, why it failed or is unknown, the root,
    and the editor instance the root's nested Code Editor stack created."""
    try:
        stacks = mosaic_stacks(cfn)
        root = root_stack(stacks)
        if root is None:
            return "", NO_STACK, {}, None
        status = root["StackStatus"]
        editor = editor_instance_id(stacks, root)
    except Exception as error:  # noqa: BLE001 - the row still prints
        return "", f"{UNREADABLE_STACK}{error_code(error)}", {}, None
    if not setup_failed(status):
        return status, "", root, editor
    try:
        reason = first_failure(cfn, root)
    except Exception:  # noqa: BLE001 - the failed status still decides the row
        reason = ""
    reason = reason or short_reason(root.get("StackStatusReason", ""))
    return status, reason, root, editor


def stack_state(cfn: Any) -> tuple[str, str]:
    """The Mosaic stack's status, and why it failed or why it is unknown."""
    status, reason, _, _ = stack_facts(cfn)
    return status, reason


def no_record_row(account: str, region: str, cfn: Any) -> Row:
    """An account with no record: a failed setup, or what CloudFormation says."""
    status, reason = stack_state(cfn)
    if setup_failed(status):
        return Row(account, region, "-", "-", "❌", f"setup failed: {reason or status}")
    summary = ": ".join(part for part in (status, reason) if part)
    return Row(account, region, "-", "-", "⚠️", f"no record ({summary})")


def setup_failed(status: str) -> bool:
    """A failed or rolled-back stack: the record cannot outrank it.

    A rollback also deletes the stack's own readiness log group, and any failure
    record in it, so CloudFormation is the only witness left.
    """
    return "FAILED" in status or "ROLLBACK" in status


def stack_time(root: dict[str, Any]) -> datetime:
    """When the stack's current form began: its last update, else its creation.

    CloudFormation stamps LastUpdatedTime at an update's start. Workshop Studio also
    updates each stack once right after creating it, so a CREATE_COMPLETE root carries
    a LastUpdatedTime too; only an UPDATE_* status moves the start past creation.
    """
    updated = root.get("LastUpdatedTime")
    if root.get("StackStatus", "").startswith("UPDATE") and updated:
        return updated
    return root["CreationTime"]


def editor_instance_id(
    stacks: list[dict[str, Any]], root: dict[str, Any]
) -> str | None:
    """The instance this stack's nested Code Editor stack created, from its output."""
    for stack in stacks:
        if stack.get("RootId") != root["StackId"]:
            continue
        for output in stack.get("Outputs", []):
            if output["OutputKey"] == EDITOR_INSTANCE_OUTPUT:
                return output["OutputValue"]
    return None


def instance_running(ec2: Any, instance_id: str) -> bool:
    try:
        answer = ec2.describe_instances(InstanceIds=[instance_id])
    except Exception as error:
        if error_code(error) == "InvalidInstanceID.NotFound":
            return False
        raise
    return any(
        instance.get("State", {}).get("Name") == "running"
        for reservation in answer.get("Reservations", [])
        for instance in reservation.get("Instances", [])
    )


def record_time(record: dict[str, Any]) -> datetime | None:
    """CloudWatch's receipt time when there is one, else the box's own time."""
    try:
        when = datetime.fromisoformat(
            str(record.get("ingestedAt") or record["recordedAt"])
        )
    except (KeyError, TypeError, ValueError):
        return None
    return when if when.tzinfo is not None else None


def record_mismatch(
    record: dict[str, Any], root: dict[str, Any], editor: str | None, ec2: Any
) -> tuple[str, str] | None:
    """Why a READY record cannot speak for this stack's running box, or None.

    The log group can outlive a box (an update that replaces only the instance), so
    a record must reach CloudWatch after the stack's current form began and come
    from the instance this stack created, which must be running now.
    """
    recorded = record_time(record)
    if recorded is None or recorded < stack_time(root):
        return "⚠️", "no record (the newest record predates this stack)"
    if editor is None:
        return "⚠️", f"cannot read: No{EDITOR_INSTANCE_OUTPUT}Output"
    try:
        if record.get("instanceId") != editor:
            return "⚠️", "no record (the newest record is from another instance)"
        if not instance_running(ec2, editor):
            return "❌", "Code Editor instance not running"
    except Exception as error:  # noqa: BLE001 - the reason is the row
        return "⚠️", f"cannot read: {error_code(error)}"
    return None


def stack_verdict(
    row: Row,
    cfn: Any,
    record: dict[str, Any] | None = None,
    ec2: Any = None,
) -> Row:
    """CloudFormation first: a record never outranks a failed or unfinished stack.

    A box can write READY before a later resource fails the stack, so a failed or
    rolled-back root is a failed setup whatever the record says, and a READY record
    counts only once the root has finished without a rollback.
    """
    status, reason, root, editor = stack_facts(cfn)
    cells = (row.account, row.region, row.instance, row.recorded)
    if setup_failed(status):
        return Row(*cells, "❌", f"setup failed: {reason or status}")
    if not row.ready:
        return row
    if status in COMPLETE_STACK_STATES:
        if record is not None:
            mismatch = record_mismatch(record, root, editor, ec2)
            if mismatch:
                return Row(*cells, *mismatch)
        outputs = {o["OutputKey"]: o["OutputValue"] for o in root.get("Outputs", [])}
        return web_verdict(row, outputs)
    if status in RUNNING_STACK_STATES:
        return Row(*cells, "⚠️", f"setup still running ({status})")
    if status:
        return Row(*cells, "⚠️", f"setup not complete ({status})")
    if reason.startswith(UNREADABLE_STACK):
        return Row(*cells, "⚠️", f"cannot read: {reason.removeprefix(UNREADABLE_STACK)}")
    return Row(*cells, "⚠️", NO_STACK)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is the answer, never followed: it could leave the CloudFront host."""

    def redirect_request(self, *_args: Any) -> None:
        return None


WEB_OPENER = urllib.request.build_opener(NoRedirect())


def http_get(url: str) -> tuple[int, bytes]:
    """One HTTPS GET as a browser makes it: the status and the start of the body."""
    request = urllib.request.Request(url, headers={"User-Agent": WEB_AGENT})
    try:
        with WEB_OPENER.open(request, timeout=WEB_TIMEOUT_SECONDS) as response:
            return response.status, response.read(WEB_BODY_BYTES)
    except urllib.error.HTTPError as error:
        return error.code, error.read(WEB_BODY_BYTES)


class DeadlineExceeded(Exception):
    """A fetch outlived its deadline: urllib's timeout does not bound DNS."""


def bounded_get(url: str, deadline: float | None = None) -> tuple[int, bytes]:
    """http_get in a daemon thread with a hard deadline, so no lookup can stall the
    fleet and no stuck thread holds the process open at exit."""
    outcome: dict[str, Any] = {}

    def fetch() -> None:
        try:
            outcome["answer"] = http_get(url)
        except Exception as error:  # noqa: BLE001 - re-raised in the caller
            outcome["error"] = error

    worker = threading.Thread(target=fetch, daemon=True)
    worker.start()
    worker.join(WEB_DEADLINE_SECONDS if deadline is None else deadline)
    if worker.is_alive():
        raise DeadlineExceeded
    if "error" in outcome:
        raise outcome["error"]
    return outcome["answer"]


def web_answer(
    url: str,
    accept: Callable[[int, bytes], str | None],
    attempts: int,
    budget_end: float,
) -> str | None:
    """None once the URL answers as `accept` wants, else why not; never the URL.

    A failure is tried once more after a short pause, so one dropped connection
    does not fail an account.
    """
    why = "no answer"
    for attempt in range(attempts):
        if attempt:
            time.sleep(min(WEB_PAUSE_SECONDS, max(0.0, budget_end - time.monotonic())))
        remaining = budget_end - time.monotonic()
        if remaining <= 0:
            return (
                f"{why}; account time budget spent"
                if attempt
                else "account time budget spent"
            )
        try:
            status, body = bounded_get(url, min(WEB_DEADLINE_SECONDS, remaining))
        except Exception as error:  # noqa: BLE001 - the reason is the row
            why = type(error).__name__
            continue
        why = accept(status, body)
        if why is None:
            return None
    return why


def html_page(status: int, body: bytes) -> str | None:
    if status != 200:
        return f"HTTP {status}"
    return None if b"<html" in body[:4096].lower() else "not an HTML page"


def database_ready(status: int, body: bytes) -> str | None:
    if status != 200:
        return f"HTTP {status}"
    try:
        answer = json.loads(body)
    except ValueError:
        return "readiness is not JSON"
    return None if answer.get("status") == "ready" else "database not ready"


def editor_health(status: int, body: bytes) -> str | None:
    if status != 200:
        return f"HTTP {status}"
    try:
        answer = json.loads(body)
    except ValueError:
        return "health is not JSON"
    return None if "hasActiveConnections" in answer else "not the Code Editor's health"


def cloudfront_host(url: str) -> str | None:
    """The CloudFront host of an https output URL, or None for anything else.

    A user name, password or port, another scheme or another host is refused, so
    the laptop never sends a request outside the account's own distributions.
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname or ""
    if (
        parts.scheme != "https"
        or parts.username is not None
        or parts.password is not None
        or port is not None
        or not host.endswith(WEB_HOST_SUFFIX)
        or host == WEB_HOST_SUFFIX.lstrip(".")
    ):
        return None
    return host


def browser_path(storefront: str | None, editor: str | None) -> str | None:
    """None when the storefront page, its readiness and the editor's health answer
    from these CloudFront hosts; else the row's ❌ status."""
    if not storefront:
        return f"storefront does not answer (no usable {STOREFRONT_OUTPUT})"
    budget_end = time.monotonic() + WEB_BUDGET_SECONDS
    why = web_answer(
        f"https://{storefront}/", html_page, PAGE_ATTEMPTS, budget_end
    ) or web_answer(
        f"https://{storefront}/api/readiness", database_ready, WEB_ATTEMPTS, budget_end
    )
    if why:
        return f"storefront does not answer ({why})"
    if not editor:
        return f"Code Editor does not answer (no usable {EDITOR_OUTPUT})"
    why = web_answer(
        f"https://{editor}/healthz", editor_health, PAGE_ATTEMPTS, budget_end
    )
    return f"Code Editor does not answer ({why})" if why else None


def web_verdict(row: Row, outputs: dict[str, str]) -> Row:
    """A ✅ also needs the participant's browser path to answer, through CloudFront.

    The storefront page and its readiness (which reaches Aurora) and the Code
    Editor's own health answer without a token or a sign-in, so no account is
    claimed. The editor URL carries its connection token, so only its domain is
    kept; neither URL is ever printed. The row keeps both hosts for --save.
    """
    storefront = cloudfront_host(outputs.get(STOREFRONT_OUTPUT, ""))
    editor = cloudfront_host(outputs.get(EDITOR_OUTPUT, ""))
    hosts = {"storefront": storefront or "", "editor": editor or ""}
    failure = browser_path(storefront, editor)
    if failure:
        return replace(row, icon="❌", status=failure, **hosts)
    return replace(row, **hosts)


def box_instance(session: Any) -> str:
    """The instance this stack created, from its nested Code Editor stack's output.

    No record's instance and no tag stands in for it: an old host could still be
    running while this stack's own instance is not.
    """
    try:
        stacks = mosaic_stacks(aws_client(session, "cloudformation"))
        root = root_stack(stacks)
        created = editor_instance_id(stacks, root) if root else None
    except Exception as error:
        raise CannotRead(error_code(error)) from error
    if not created:
        raise CannotRead(f"No{EDITOR_INSTANCE_OUTPUT}Output")
    return created


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
    instance_id = box_instance(session)
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


def recorded_time(record: Any, now: datetime) -> datetime | None:
    """The record's time, or None when it is missing, has no zone or lies ahead."""
    try:
        recorded = datetime.fromisoformat(str(record["recordedAt"]))
    except (KeyError, TypeError, ValueError):
        return None
    if recorded.tzinfo is None or recorded - now > FUTURE_SKEW:
        return None
    return recorded


def record_row(
    account: str, region: str, record: dict[str, Any], now: datetime, max_age: float
) -> Row:
    recorded = recorded_time(record, now) if isinstance(record, dict) else None
    if recorded is None:
        return Row(account, region, "-", "-", "⚠️", "cannot read: MalformedRecord")
    hours = (now - recorded).total_seconds() / 3600
    cells = (account, region, record.get("instanceId") or "-")
    when = recorded.astimezone(UTC).strftime(SHOWN_TIME)
    if hours > max_age:
        return Row(*cells, when, "⚠️", f"STALE ({age_text(hours)})")
    if record.get("ready") is True and record.get("final") == READY:
        return Row(*cells, when, "✅", READY)
    final = str(record.get("final") or "no final line")
    return Row(*cells, when, "❌", plain(final.removeprefix("x FAIL")))


def busy_row(account: str, region: str, busy: LabInProgress) -> Row:
    """A box --live left alone, shown with the record it already had."""
    previous = busy.previous or {}
    when = "-"
    if previous.get("recordedAt"):
        recorded = datetime.fromisoformat(previous["recordedAt"]).astimezone(UTC)
        when = recorded.strftime(SHOWN_TIME)
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
    row = record_row(account, region, record, datetime.now(UTC), max_age)
    verdict = stack_verdict(
        row,
        aws_client(session, "cloudformation"),
        record,
        aws_client(session, "ec2"),
    )
    return verdict, record


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
            if values.get(match["key"], value) != value:
                raise CannotRead(f"DuplicateKey {match['key']}")
            values[match["key"]] = value
    return values


class PrivateFileError(Exception):
    """A file that is not owner-only text; `code` names the rule, `fix` the repair."""

    def __init__(self, code: str, fix: str) -> None:
        super().__init__(code)
        self.code = code
        self.fix = fix


def has_acl(path: Path) -> bool:
    """Whether macOS lists an access control entry, which mode bits cannot show.

    `--` keeps a name that starts with a dash from reading as options, and a listing
    that fails refuses the file rather than passing it.
    """
    if sys.platform != "darwin":
        return False
    try:
        listing = subprocess.run(
            ["/bin/ls", "-led", "--", str(path)],
            capture_output=True,
            text=True,
            errors="replace",
            check=True,
            timeout=10,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise PrivateFileError(
            f"AclUnreadable {type(error).__name__}", f"ls -led {path.name}"
        ) from error
    return any(ACL_ENTRY.match(line) for line in listing.stdout.splitlines()[1:])


def private_text(path: Path, encoding: str = "utf-8") -> str:
    """A regular file only its owner can read, decoded, at most MAX_INPUT_BYTES.

    It opens without blocking or following a link and checks the open file, so a
    FIFO or a device is refused instead of hanging the run, and the file checked
    for an access control list is the file named.
    """
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise PrivateFileError(
                "NotAFile", f"pass the file itself, not the link {path.name}"
            ) from error
        raise PrivateFileError(
            type(error).__name__, f"check that {path.name} exists and can be read"
        ) from error
    try:
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise PrivateFileError(
                    "NotAFile", f"pass {path.name} itself, a plain file"
                )
            if info.st_mode & 0o077:
                raise PrivateFileError("FilePermissions", f"chmod 600 {path.name}")
            data = handle.read(MAX_INPUT_BYTES + 1)
    except OSError as error:
        raise PrivateFileError(
            type(error).__name__, f"check that {path.name} can be read"
        ) from error
    if len(data) > MAX_INPUT_BYTES:
        raise PrivateFileError("FileTooLarge", f"{path.name} must be under 4 MB")
    if has_acl(path):
        raise PrivateFileError("FileAcl", f"chmod -N {path.name}")
    try:
        return data.decode(encoding)
    except UnicodeDecodeError as error:
        raise PrivateFileError("NotText", f"save {path.name} as UTF-8") from error


def file_session(path: Path) -> tuple[Any, str]:
    """A boto3 session from one account file, and its Region."""
    try:
        values = parse_credentials(private_text(path))
    except PrivateFileError as error:
        raise CannotRead(f"{error.code} ({path.name}; fix: {error.fix})") from error
    except CannotRead as error:
        raise CannotRead(f"{error.code} ({path.name})") from error
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
    if not REGION_NAME.fullmatch(region):
        raise CannotRead(
            f"InvalidRegion ({path.name}; AWS_DEFAULT_REGION must look like us-east-1)"
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


def file_account(path: Path) -> str | None:
    """The account a file's credentials reach, or None when they cannot say."""
    try:
        session, _ = file_session(path)
        return aws_client(session, "sts").get_caller_identity()["Account"]
    except Exception:  # noqa: BLE001 - that file's own row reports why
        return None


def live_duplicates(
    files: list[Path], account_of: Callable[[Path], str | None]
) -> dict[Path, tuple[str, str]]:
    """Files whose account an earlier file already names: they get no --live run."""
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_ACCOUNTS) as pool:
        accounts = list(pool.map(account_of, files))
    first: dict[str, str] = {}
    repeats: dict[Path, tuple[str, str]] = {}
    for path, account in zip(files, accounts, strict=True):
        if account is None:
            continue
        if account in first:
            repeats[path] = (account, first[account])
        else:
            first[account] = path.name
    return repeats


def fleet_rows(
    directory: Path,
    *,
    live: bool,
    max_age: float,
    row: Callable[..., Row] = file_row,
    account_of: Callable[[Path], str | None] = file_account,
) -> list[Row]:
    """One row per *.env file, in file-name order, at most eight accounts at once.

    Before --live, each file's account is read first, so one box never gets two
    --live runs at once from two files of the same account.
    """
    files = sorted(directory.glob("*.env"))
    repeats = live_duplicates(files, account_of) if live else {}

    def one(path: Path) -> Row:
        if path in repeats:
            account, original = repeats[path]
            return Row(account, "-", "-", "-", "⚠️", f"same account as {original}")
        return row(path, live=live, max_age=max_age)

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_ACCOUNTS) as pool:
        rows = list(pool.map(one, files))
    return distinct_accounts(files, rows)


def distinct_accounts(files: list[Path], rows: list[Row]) -> list[Row]:
    """A second file for an account already listed is a warning, so M counts teams."""
    first: dict[str, str] = {}
    distinct = []
    for path, row in zip(files, rows, strict=True):
        if row.account != "-" and row.account in first:
            row = Row(
                row.account,
                row.region,
                row.instance,
                row.recorded,
                "⚠️",
                f"same account as {first[row.account]}",
            )
        elif row.account != "-":
            first[row.account] = path.name
        distinct.append(row)
    return distinct


def table(rows: list[Row]) -> list[str]:
    cells = [
        tuple(printable(cell) for cell in (r.account, r.region, r.instance, r.recorded))
        + (f"{r.icon} {printable(r.status)}",)
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
# the day-before run saved, the morning recheck without credentials, and the
# event's own list of teams
# ---------------------------------------------------------------------------


class UnusableFile(Exception):
    """A saved run or Teams CSV that cannot be used; the message names the fix."""


def unusable_text(path: Path, encoding: str = "utf-8") -> str:
    """private_text for a saved run or the Teams CSV, as a usage error."""
    try:
        return private_text(path, encoding)
    except PrivateFileError as error:
        raise UnusableFile(
            f"{path} cannot be used ({error.code}); fix: {error.fix}"
        ) from error


BOX_NOT_READY = "the box's record is not ready"
SAVED_WORDS = frozenset(
    {
        READY,
        NO_STACK,
        "setup failed",
        "setup still running",
        "setup not complete",
        "no record",
        "Code Editor instance not running",
        "cannot read",
        "lab in progress",
        "STALE",
        "storefront does not answer",
        "Code Editor does not answer",
    }
)


def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("a key appears twice")
    return dict(pairs)


def load_saved(path: Path) -> dict[str, dict[str, Any]]:
    """The accounts of a saved run, by account ID. A file others can read, a repeated
    key, an entry that is not one account's, or nesting too deep is refused."""
    text = unusable_text(path)
    try:
        saved = json.loads(text, object_pairs_hook=unique_keys)
        accounts = saved["accounts"]
        if saved.get("version") != SAVE_VERSION or not isinstance(accounts, dict):
            raise ValueError("not this script's saved-run shape")
        for account, entry in accounts.items():
            if len(account) != 12 or not ACCOUNT_DIGITS.fullmatch(account):
                raise ValueError("a key that is not an account ID")
            if not isinstance(entry, dict) or entry.keys() != SAVED_FIELDS.keys():
                raise TypeError("an account entry without exactly the saved fields")
            if not all(type(entry[k]) is kind for k, kind in SAVED_FIELDS.items()):
                raise TypeError("a saved field of the wrong type")
    except (ValueError, KeyError, TypeError, RecursionError) as error:
        raise UnusableFile(
            f"{path} is not a saved run ({type(error).__name__}: "
            f"{plain(str(error), 80)}); fix: run --accounts with --save again"
        ) from error
    return accounts


def saved_status(row: Row) -> str:
    """The row's status as one of this script's own words, so a CloudFormation
    reason, a check's detail or a log line never reaches the file. Every other
    status is a box check's failure line; DAT416 and DAT432 save the same words."""
    head = re.split(r":| \(", row.status, maxsplit=1)[0].strip()
    return head if head in SAVED_WORDS else BOX_NOT_READY


def save_run(path: Path, rows: list[Row], now: datetime) -> None:
    """Merge this run's accounts into the saved run, by account ID, mode 0600.

    Only CloudFront hosts are kept, never a token. A row with no account or a second
    file of an account never replaces the real row. A damaged file is moved aside,
    so it never blocks the next save.
    """
    accounts: dict[str, dict[str, Any]] = {}
    if path.exists():
        try:
            accounts = load_saved(path)
        except UnusableFile:
            aside = path.with_name(f"{path.name}.damaged-{now:%Y%m%dT%H%M%SZ}")
            path.rename(aside)
            print(
                f"Readiness: {path.name} could not be read; moved it to {aside.name}."
            )
    for row in rows:
        if row.account == "-" or row.status.startswith("same account as"):
            continue
        accounts[row.account] = {
            "region": row.region,
            "instance": row.instance,
            "recorded": row.recorded,
            "ready": row.ready,
            "status": saved_status(row),
            "storefront": row.storefront,
            "editor": row.editor,
            "checkedAt": now.isoformat(),
        }
    body = json.dumps({"version": SAVE_VERSION, "accounts": accounts}, indent=2)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def shown_time(text: str) -> datetime | None:
    """A record time as the table shows it, in UTC to the minute."""
    try:
        return datetime.strptime(text, SHOWN_TIME).replace(tzinfo=UTC)
    except ValueError:
        return None


def recheck_row(
    account: str, entry: dict[str, Any], now: datetime, max_age: float
) -> Row:
    """One saved account, read again through its browser path with no credentials.

    A ✅ needs the account to have been ✅ at the saved run, its box record to be
    no older than the limit now, and its storefront, readiness (which reaches
    Aurora) and Code Editor health to answer now.
    """
    cells = (
        account,
        str(entry.get("region", "-")),
        str(entry.get("instance", "-")),
        str(entry.get("recorded", "-")),
    )
    try:
        checked = datetime.fromisoformat(str(entry["checkedAt"]))
        hours = (now - checked).total_seconds() / 3600
    except (KeyError, ValueError, TypeError):
        return Row(*cells, "⚠️", "cannot read: MalformedSavedRun")
    if hours > max_age:
        return Row(*cells, "⚠️", f"saved run STALE ({age_text(hours)}); run --accounts")
    if entry.get("ready") is not True:
        saved = plain(str(entry.get("status", "")), 80)
        return Row(*cells, "⚠️", f"not ready at the saved run ({saved})")
    recorded = shown_time(cells[3])
    if recorded is None or recorded - now > FUTURE_SKEW:
        return Row(*cells, "⚠️", "cannot read: MalformedSavedRun")
    record_hours = (now - recorded).total_seconds() / 3600
    if record_hours > max_age:
        return Row(*cells, "⚠️", f"STALE ({age_text(record_hours)})")
    failure = browser_path(
        cloudfront_host(f"https://{entry.get('storefront', '')}/"),
        cloudfront_host(f"https://{entry.get('editor', '')}/"),
    )
    if failure:
        return Row(*cells, "❌", failure)
    return Row(*cells, "✅", READY)


@dataclass(frozen=True)
class Teams:
    """This event's teams from the console's Teams CSV."""

    accounts: dict[str, str]
    unassigned: list[str]


def team_cell(row: dict[str, str | None], column: str) -> str:
    return (row.get(column) or "").strip()


def event_teams(path: Path) -> Teams:
    """Account ID to team name, and the teams with no account yet.

    Only the team name and account ID are read. The file holds no credentials, but
    its join URLs claim teams, so it must be 0600 like the credential files.
    """
    reader = csv.DictReader(io.StringIO(unusable_text(path, "utf-8-sig"), newline=""))
    try:
        missing = [c for c in TEAM_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise UnusableFile(
                f"{path} has no {' or '.join(missing)} column, so it is not the "
                "console's Teams CSV; fix: Teams > Download CSV"
            )
        cells = [tuple(team_cell(row, c) for c in TEAM_COLUMNS) for row in reader]
    except csv.Error as error:
        raise UnusableFile(
            f"{path} cannot be used (TeamsFile: csv.Error); fix: Teams > Download "
            "CSV, and do not re-save it from a spreadsheet"
        ) from error
    accounts: dict[str, str] = {}
    unassigned: list[str] = []
    for team, account in cells:
        if not account:
            unassigned.append(team or "a team with no name")
        elif ACCOUNT_DIGITS.fullmatch(account):
            accounts[account.zfill(12)] = team
        else:
            raise UnusableFile(
                f"{path}: {plain(team, 60) or 'a team'} has AWS account ID "
                f"{plain(account, 24)!r}, not up to 12 digits; fix: use the "
                "downloaded CSV unedited"
            )
    if not accounts and not unassigned:
        raise UnusableFile(f"{path} lists no teams; fix: Teams > Download CSV")
    return Teams(accounts, unassigned)


def against_teams(rows: list[Row], teams: Teams, absent: str) -> list[Row]:
    """The event's teams decide the count: an account outside them is flagged, and
    each team with no row, or with no account yet, gets a ⚠️ row of its own."""
    checked = [
        row
        if row.account == "-" or row.account in teams.accounts
        else replace(row, icon="⚠️", status="not a team of this event")
        for row in rows
    ]
    seen = {row.account for row in rows}
    checked += [
        Row(account, "-", "-", "-", "⚠️", f"{absent} ({plain(team)})")
        for account, team in sorted(teams.accounts.items())
        if account not in seen
    ]
    checked += [
        Row("-", "-", "-", "-", "⚠️", f"no AWS account in the Teams CSV ({plain(team)})")
        for team in teams.unassigned
    ]
    return checked


def recheck_rows(path: Path, max_age: float) -> list[Row]:
    """Every saved account rechecked through its browser path, eight at once."""
    accounts = load_saved(path)
    now = datetime.now(UTC)
    ordered = sorted(accounts.items())
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_ACCOUNTS) as pool:
        return list(pool.map(lambda item: recheck_row(*item, now, max_age), ordered))


def save_folder(path: Path) -> None:
    """Create the saved run's folder, private, before any account is read."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)


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
    cli.add_argument(
        "--save",
        type=Path,
        metavar="FILE",
        help="with --accounts: keep each account's result and CloudFront hosts (0600)",
    )
    cli.add_argument(
        "--recheck",
        type=Path,
        metavar="FILE",
        help="no credentials: recheck a saved run's browser path",
    )
    cli.add_argument(
        "--teams",
        type=Path,
        metavar="CSV",
        help="the console's Teams CSV (0600): every team needs a row",
    )
    cli.add_argument("--max-age-hours", type=float)
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
    if args.max_age_hours is None:
        args.max_age_hours = (
            RECHECK_MAX_AGE_HOURS if args.recheck else DEFAULT_MAX_AGE_HOURS
        )
    if not 0 < args.max_age_hours <= MAX_AGE_LIMIT_HOURS:
        cli.error(
            f"--max-age-hours must be above 0 and at most {MAX_AGE_LIMIT_HOURS:g}, "
            f"not {args.max_age_hours:g}"
        )
    if not math.isfinite(args.cap) or args.cap <= 0:
        cli.error(f"--cap must be a positive number of seconds, not {args.cap:g}")
    if args.accounts and not args.accounts.is_dir():
        cli.error(f"--accounts {args.accounts} is not a directory")
    if args.save and not args.accounts:
        cli.error("--save goes with --accounts")
    if args.teams and not (args.accounts or args.recheck):
        cli.error("--teams goes with --accounts or --recheck")
    if args.recheck and (args.accounts or args.live or args.record):
        cli.error("--recheck needs no credentials: use it without --accounts or --live")
    if args.recheck and not args.recheck.is_file():
        cli.error(f"--recheck {args.recheck} is not a file")


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


def fleet(cli: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Every input is checked before any account is read, so a bad path never
    wastes a sweep; the saved run holds real reads only, never a team-list row."""
    try:
        teams = event_teams(args.teams) if args.teams else None
        if args.save:
            save_folder(args.save)
        if args.recheck:
            rows = recheck_rows(args.recheck, args.max_age_hours)
    except (UnusableFile, OSError) as error:
        cli.error(str(error))
    if args.accounts:
        rows = fleet_rows(args.accounts, live=args.live, max_age=args.max_age_hours)
    shown = rows
    if teams:
        absent = "not in the saved run" if args.recheck else "not in this run"
        shown = against_teams(rows, teams, absent)
    print("\n".join(table(shown)))
    if args.save:
        save_run(args.save, rows, datetime.now(UTC))
    return exit_status(shown)


def main(argv: list[str] | None = None) -> int:
    cli = parser()
    args = cli.parse_args(argv)
    validate(cli, args)
    if args.record:
        return record_on_box(args)
    if args.recheck or args.accounts:
        return fleet(cli, args)
    return one_account(args)


if __name__ == "__main__":
    sys.exit(main())
