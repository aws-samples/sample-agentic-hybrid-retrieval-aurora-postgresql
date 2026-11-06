"""The event readiness record and fleet view report ready only when they can prove it."""

import json
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from scripts import event_readiness as readiness
from scripts import readiness_checks as checks
from scripts.readiness_checks import Line

NOW = datetime(2026, 12, 1, 6, 40, tzinfo=UTC)
TOKEN = "IQoJb3JpZ2luX2VjEA4aCXVzLWVhc3Qt+/abc=="


def client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "Operation")


def record(**overrides) -> dict:
    base = {
        "recordedAt": (NOW - timedelta(hours=1)).isoformat(timespec="seconds"),
        "instanceId": "i-0123456789abcdef0",
        "mode": "bootstrap",
        "ready": True,
        "final": readiness.READY,
        "lines": ["PASS  Services: active"],
    }
    return {**base, **overrides}


# --- credential files ---------------------------------------------------------


def test_console_block_with_export_and_quotes_parses():
    text = (
        'export AWS_ACCESS_KEY_ID="ASIAEXAMPLE"\n'
        'export AWS_SECRET_ACCESS_KEY="se/cr+et"\n'
        f'export AWS_SESSION_TOKEN="{TOKEN}"\n'
        "AWS_DEFAULT_REGION=us-west-2\n"
    )
    values = readiness.parse_credentials(text)
    assert values["AWS_SECRET_ACCESS_KEY"] == "se/cr+et"
    assert values["AWS_SESSION_TOKEN"] == TOKEN
    assert values["AWS_DEFAULT_REGION"] == "us-west-2"


@pytest.mark.parametrize(
    "glued",
    [
        f'export AWS_SESSION_TOKEN="{TOKEN}"AWS_DEFAULT_REGION=us-west-2',
        f'export AWS_SESSION_TOKEN="{TOKEN}"export AWS_DEFAULT_REGION=us-west-2',
        f"AWS_SESSION_TOKEN={TOKEN}AWS_DEFAULT_REGION=us-west-2",
        f"AWS_SESSION_TOKEN={TOKEN}export AWS_DEFAULT_REGION=us-west-2",
    ],
)
def test_region_appended_without_a_newline_splits_from_the_token(glued):
    values = readiness.parse_credentials("AWS_ACCESS_KEY_ID=A\n" + glued)
    assert values["AWS_SESSION_TOKEN"] == TOKEN
    assert values["AWS_DEFAULT_REGION"] == "us-west-2"


def test_comments_and_windows_line_ends_are_ignored():
    values = readiness.parse_credentials(
        "# AWS_REGION=eu-west-1\r\nAWS_REGION=us-east-1\r\n"
    )
    assert values == {"AWS_REGION": "us-east-1"}


def write_account(directory: Path, name: str, text: str, mode: int = 0o600) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path


def test_file_readable_by_others_is_refused_before_it_is_read(tmp_path):
    path = write_account(tmp_path, "a.env", "AWS_ACCESS_KEY_ID=A", mode=0o644)
    row = readiness.file_row(path, live=False, max_age=24)
    assert row.icon == "⚠️"
    assert row.status == "cannot read: FilePermissions (a.env; fix: chmod 600 a.env)"


def test_file_without_a_region_names_the_fix(tmp_path):
    path = write_account(
        tmp_path, "b.env", "AWS_ACCESS_KEY_ID=A\nAWS_SECRET_ACCESS_KEY=B"
    )
    row = readiness.file_row(path, live=False, max_age=24)
    assert row.status.startswith("cannot read: MissingRegion (b.env")


# --- the record ---------------------------------------------------------------


def test_record_is_ready_only_when_a_check_passed_and_none_failed():
    good = readiness.build_record(
        [Line("PASS", "Services", "active")],
        mode="bootstrap",
        instance_id="i-1",
        now=NOW,
    )
    assert good["ready"] and good["final"] == readiness.READY
    empty = readiness.build_record([], mode="live", instance_id="i-1", now=NOW)
    assert not empty["ready"]
    assert empty["final"] == "x FAIL  Readiness: no check ran"
    info_only = readiness.build_record(
        [Line("INFO", "Lab state", "started")], mode="live", instance_id="i-1", now=NOW
    )
    assert not info_only["ready"]


def test_first_failing_check_is_the_final_line():
    lines = [
        Line("PASS", "Services", "active"),
        Line("FAIL", "Memory", "status CREATING"),
        Line("FAIL", "Gateway", "status FAILED"),
    ]
    made = readiness.build_record(lines, mode="live", instance_id="i-1", now=NOW)
    assert made["final"] == "x FAIL  Memory: status CREATING"
    assert made["lines"][1] == "FAIL  Memory: status CREATING"


def test_failed_bootstrap_records_its_phase_without_running_checks(monkeypatch, capsys):
    monkeypatch.setattr(readiness, "imds_instance_id", lambda: "i-0fedcba9876543210")
    logs = Mock()
    args = readiness.parser().parse_args(
        ["--record", "--failed", "bootstrap phase catalog exited 1"]
    )
    assert readiness.record_on_box(args, logs=logs) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["mode"] == "failed"
    assert printed["final"] == "x FAIL  Bootstrap: bootstrap phase catalog exited 1"
    sent = logs.put_log_events.call_args.kwargs
    assert sent["logGroupName"] == "/aws/mosaic/readiness"
    assert sent["logStreamName"] == "i-0fedcba9876543210"


def test_existing_stream_is_reused_and_other_errors_surface():
    logs = Mock()
    logs.create_log_stream.side_effect = client_error("ResourceAlreadyExistsException")
    readiness.write_cloudwatch(record(), logs)
    assert logs.put_log_events.called
    logs.create_log_stream.side_effect = client_error("AccessDeniedException")
    with pytest.raises(ClientError):
        readiness.write_cloudwatch(record(), logs)


def test_gate_lines_need_the_gate_marker():
    assert checks.bootstrap_gate_lines(None)[0].status == "FAIL"
    lines = checks.bootstrap_gate_lines("2026-12-01T06:30:00Z")
    assert len(lines) == len(checks.BOOTSTRAP_ONLY)
    assert all("recorded 2026-12-01T06:30:00Z" in line.detail for line in lines)


def test_checks_past_the_cap_fail_and_name_the_running_check():
    release = threading.Event()

    def slow(_ctx):
        release.wait(5)
        return [Line("PASS", "Slow", "done")]

    lines = checks.run_checks(
        Mock(),
        0.2,
        checks=(("Fast", lambda _ctx: [Line("PASS", "Fast", "ok")]), ("Slow", slow)),
    )
    release.set()
    assert [line.status for line in lines] == ["PASS", "FAIL"]
    assert lines[-1].name == "Readiness cap"
    assert "Slow was still running" in lines[-1].detail


def test_a_check_that_raises_becomes_a_failing_line():
    def broken(_ctx):
        raise RuntimeError("password=hunter2 rejected")

    lines = checks.run_checks(Mock(), 5, checks=(("Broken", broken),))
    assert lines[0].status == "FAIL"
    assert "hunter2" not in lines[0].detail


# --- positive controls on the box ---------------------------------------------


def context(**env) -> checks.Context:
    base = {key: "model" for key in checks.MODEL_VARIABLES}
    return checks.Context(repo=Path("."), env={**base, **env}, expected={})


def runtime(**overrides) -> dict:
    base = {
        "agentRuntimeId": "r-1",
        "status": "READY",
        "platformVersion": "V1",
        "agentRuntimeVersion": "3",
        "environmentVariables": {key: "model" for key in checks.MODEL_VARIABLES},
        "agentRuntimeArtifact": {
            "containerConfiguration": {"containerUri": "repo:bootstrap-abc"}
        },
    }
    return {**base, **overrides}


def ready_control() -> Mock:
    control = Mock()
    control.get_agent_runtime_endpoint.return_value = {
        "status": "READY",
        "liveVersion": "3",
    }
    return control


def test_runtime_with_no_platform_version_is_not_v1():
    line = checks.runtime_line(
        context(), ready_control(), "Tools runtime", runtime(platformVersion=None)
    )
    assert line.status == "FAIL"
    assert "a missing value is not V1" in line.detail


def test_runtime_on_v1_with_matching_models_passes():
    line = checks.runtime_line(context(), ready_control(), "Tools runtime", runtime())
    assert line.status == "PASS"


def test_runtime_whose_models_differ_from_the_box_fails():
    line = checks.runtime_line(
        context(BEDROCK_CHAT_MODEL_ID="other"), ready_control(), "Agent", runtime()
    )
    assert line.status == "FAIL"
    assert "BEDROCK_CHAT_MODEL_ID" in line.detail


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, *_):
        return Rows(self.rows)


def test_fuzzy_control_fails_when_fuzzy_matching_cannot_find_the_logitech(monkeypatch):
    repo = Path(checks.__file__).resolve().parents[1]
    monkeypatch.setattr(checks, "connect", lambda _ctx: Connection([(7, 1), (8, 2)]))
    lines = checks.check_fuzzy_control(checks.Context(repo=repo, env={}, expected={}))
    assert lines[0].status == "FAIL"
    assert "without 1492978" in lines[0].detail


def test_fuzzy_control_passes_when_it_finds_the_logitech(monkeypatch):
    repo = Path(checks.__file__).resolve().parents[1]
    monkeypatch.setattr(checks, "connect", lambda _ctx: Connection([(1492978, 1)]))
    lines = checks.check_fuzzy_control(checks.Context(repo=repo, env={}, expected={}))
    assert lines[0].status == "PASS"


def test_lab_state_after_a_start_is_information_not_a_failure(monkeypatch):
    from scripts import lab_entry

    monkeypatch.setattr(
        lab_entry, "load_record", lambda lab, _repo: {} if lab == 1 else None
    )
    lines = checks.check_lab_state(checks.Context(repo=Path("."), env={}, expected={}))
    assert lines[0].status == "INFO"


# --- reading records from a laptop --------------------------------------------


class Paginator:
    def __init__(self, pages=None, error=None):
        self.pages, self.error = pages or [], error

    def paginate(self, **_):
        if self.error:
            raise self.error
        return iter(self.pages)


def logs_with(pages=None, error=None) -> Mock:
    logs = Mock()
    logs.get_paginator.return_value = Paginator(pages, error)
    return logs


def test_latest_record_is_the_newest_event_across_pages():
    older = {"timestamp": 1, "message": json.dumps(record(final="older"))}
    newer = {"timestamp": 9, "message": json.dumps(record(final="newer"))}
    logs = logs_with([{"events": [newer]}, {"events": [older]}])
    assert readiness.latest_record(logs)["final"] == "newer"


def test_missing_group_is_no_record_and_denial_is_cannot_read():
    assert (
        readiness.latest_record(
            logs_with(error=client_error("ResourceNotFoundException"))
        )
        is None
    )
    with pytest.raises(readiness.CannotRead) as denied:
        readiness.latest_record(logs_with(error=client_error("AccessDeniedException")))
    assert denied.value.code == "AccessDeniedException"


def test_ready_record_row():
    row = readiness.record_row("123456789012", "us-east-1", record(), NOW, 24)
    assert (row.icon, row.status, row.recorded) == (
        "✅",
        readiness.READY,
        "2026-12-01 05:40",
    )


def test_old_record_is_stale_even_when_it_was_ready():
    old = record(recordedAt=(NOW - timedelta(hours=30)).isoformat())
    row = readiness.record_row("123456789012", "us-east-1", old, NOW, 24)
    assert (row.icon, row.status) == ("⚠️", "STALE (30 h old)")
    assert not row.ready


def test_failing_record_shows_its_first_failing_check():
    bad = record(ready=False, final="x FAIL  Memory: status CREATING")
    row = readiness.record_row("123456789012", "us-east-1", bad, NOW, 24)
    assert (row.icon, row.status) == ("❌", "Memory: status CREATING")


def test_ready_flag_without_the_ready_phrase_is_not_ready():
    odd = record(final="something else")
    assert readiness.record_row("1", "us-east-1", odd, NOW, 24).icon == "❌"


def stack(status: str, **extra) -> dict:
    return {
        "StackId": "root",
        "StackName": "mosaic",
        "StackStatus": status,
        "CreationTime": NOW,
        "Parameters": [
            {"ParameterKey": "InfrastructureRevision", "ParameterValue": "x"}
        ],
        **extra,
    }


def test_no_record_row_carries_the_stack_failure():
    cfn = Mock()
    cfn.get_paginator.return_value = Paginator(
        [{"Stacks": [stack("ROLLBACK_COMPLETE")]}]
    )
    cfn.describe_stack_events.return_value = {
        "StackEvents": [
            {
                "ResourceStatus": "CREATE_FAILED",
                "Timestamp": NOW,
                "LogicalResourceId": "CodeEditorStack",
                "ResourceStatusReason": "Embedded stack arn failed",
            },
            {
                "ResourceStatus": "CREATE_FAILED",
                "Timestamp": NOW - timedelta(minutes=5),
                "LogicalResourceId": "BootstrapWaitCondition",
                "ResourceStatusReason": "Mosaic bootstrap failed. Tail: catalog restore",
            },
        ]
    }
    summary = readiness.stack_summary(cfn)
    assert summary == (
        "ROLLBACK_COMPLETE: BootstrapWaitCondition: Mosaic bootstrap failed. Tail: "
        "catalog restore"
    )


def test_account_without_a_stack_says_so():
    cfn = Mock()
    cfn.get_paginator.return_value = Paginator([{"Stacks": []}])
    assert readiness.stack_summary(cfn) == "no Mosaic stack in this Region"


def session_with(clients: dict) -> SimpleNamespace:
    return SimpleNamespace(client=lambda name, **_: clients[name])


def test_expired_credentials_are_a_cannot_read_row():
    sts = Mock()
    sts.get_caller_identity.side_effect = client_error("ExpiredToken")
    row, _ = readiness.account_row(
        session_with({"sts": sts}), "us-east-1", live=False, max_age=24, label="c.env"
    )
    assert (row.account, row.icon, row.status) == (
        "-",
        "⚠️",
        "cannot read: ExpiredToken (c.env)",
    )


def test_account_row_reads_the_account_from_sts():
    sts = Mock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}
    logs = logs_with([{"events": [{"timestamp": 1, "message": json.dumps(record())}]}])
    row, found = readiness.account_row(
        session_with({"sts": sts, "logs": logs}), "us-west-2", live=False, max_age=10**6
    )
    assert (row.account, row.region, row.instance) == (
        "123456789012",
        "us-west-2",
        "i-0123456789abcdef0",
    )
    assert found["final"] == readiness.READY


# --- the fleet table ----------------------------------------------------------


def rows_of(*icons: str) -> list:
    return [readiness.Row("1", "us-east-1", "i-1", "-", icon, "x") for icon in icons]


def test_table_shape_and_count():
    lines = readiness.table(rows_of("✅", "❌"))
    assert lines[0].split() == [
        "Account",
        "Region",
        "Instance",
        "Recorded",
        "(UTC)",
        "Status",
    ]
    assert lines[-1] == "1 of 2 ready"


@pytest.mark.parametrize(
    ("icons", "status"),
    [(("✅", "✅"), 0), (("✅", "⚠️"), 1), (("❌",), 1), ((), 1)],
)
def test_exit_zero_only_when_every_row_is_ready_and_there_is_one(icons, status):
    assert readiness.exit_status(rows_of(*icons)) == status


def test_fleet_keeps_file_order_and_reads_at_most_eight_at_once(tmp_path):
    for index in range(12):
        write_account(tmp_path, f"{index:02d}.env", "x")
    write_account(tmp_path, "notes.txt", "ignored")
    running, peak, lock = [0], [0], threading.Lock()

    def row(path, **_):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.05)
        with lock:
            running[0] -= 1
        return readiness.Row(path.stem, "us-east-1", "-", "-", "✅", "ok")

    rows = readiness.fleet_rows(tmp_path, live=False, max_age=24, row=row)
    assert [r.account for r in rows] == [f"{i:02d}" for i in range(12)]
    assert peak[0] == readiness.MAX_PARALLEL_ACCOUNTS


def test_usage_errors_exit_two(tmp_path):
    with pytest.raises(SystemExit) as missing:
        readiness.main(["--accounts", str(tmp_path / "nowhere")])
    assert missing.value.code == 2
    with pytest.raises(SystemExit) as mixed:
        readiness.main(["--record", "--accounts", str(tmp_path)])
    assert mixed.value.code == 2


def test_empty_directory_reads_zero_of_zero_and_fails(tmp_path, capsys):
    assert readiness.main(["--accounts", str(tmp_path)]) == 1
    assert capsys.readouterr().out.strip().endswith("0 of 0 ready")


def test_host_line_records_the_booted_ami_and_never_decides_readiness(monkeypatch):
    values = {
        "meta-data/ami-id": "ami-0f11e0e04ccb60d0a",
        "meta-data/instance-type": "c6g.2xlarge",
    }
    monkeypatch.setattr(checks, "imds", values.__getitem__)
    line = checks.check_host(Mock())[0]
    assert line.status == "INFO"
    assert line.detail.startswith("ami-0f11e0e04ccb60d0a, c6g.2xlarge, ")

    def unreachable(_path):
        raise OSError("no route to host")

    monkeypatch.setattr(checks, "imds", unreachable)
    assert checks.check_host(Mock())[0].status == "INFO"


# --- --live through SSM -------------------------------------------------------


class Invocations:
    def __init__(self, status):
        self.status = status
        self.sent = []

    def send_command(self, **kwargs):
        self.sent.append(kwargs)
        return {"Command": {"CommandId": "c-1"}}

    def get_command_invocation(self, **_):
        return {"Status": self.status}


class ReadsInTurn:
    """FilterLogEvents answers: the old record first, then whatever `later` holds."""

    def __init__(self, first, later):
        self.calls, self.first, self.later = 0, first, later

    def get_paginator(self, _name):
        self.calls += 1
        events = self.first if self.calls == 1 else self.later
        return Paginator([{"events": events}])


def event(made: dict, stamp: int = 1) -> dict:
    return {"timestamp": stamp, "message": json.dumps(made)}


def test_live_returns_the_new_record_even_when_the_command_failed():
    ssm = Invocations("Failed")
    logs = ReadsInTurn([event(record())], [event(record(mode="live", ready=False), 9)])
    found = readiness.live_record(
        session_with({"logs": logs, "ssm": ssm}), sleep=lambda _s: None
    )
    assert found["mode"] == "live"
    assert ssm.sent[0]["InstanceIds"] == ["i-0123456789abcdef0"]
    assert ssm.sent[0]["Parameters"]["commands"] == [
        "/usr/local/sbin/mosaic-readiness-record --live"
    ]


def test_live_names_the_finished_command_when_no_record_arrives():
    logs = ReadsInTurn([event(record())], [event(record())])
    with pytest.raises(readiness.CannotRead) as missing:
        readiness.live_record(
            session_with({"logs": logs, "ssm": Invocations("Failed")}),
            sleep=lambda _s: None,
        )
    assert missing.value.code.startswith("LiveCommandFailed on i-0123456789abcdef0")


def test_without_a_record_live_finds_the_newest_running_editor_host():
    pages = [
        {
            "Reservations": [
                {
                    "Instances": [
                        {"InstanceId": "i-old", "LaunchTime": NOW - timedelta(days=1)},
                        {"InstanceId": "i-new", "LaunchTime": NOW},
                    ]
                }
            ]
        }
    ]
    ec2 = Mock()
    ec2.get_paginator.return_value.paginate.return_value = iter(pages)
    assert readiness.box_instance(session_with({"ec2": ec2}), logs_with([])) == "i-new"
    ec2.get_paginator.assert_called_once_with("describe_instances")
    assert ec2.get_paginator.return_value.paginate.call_args.kwargs["Filters"] == [
        {"Name": "tag-key", "Values": ["eval-skills:launch-inputs"]},
        {"Name": "instance-state-name", "Values": ["running"]},
    ]


def test_launcher_tag_matches_the_editor_launcher():
    launcher = Path(readiness.__file__).resolve().parents[1] / (
        "deploy/cloudformation/editor_launcher.py"
    )
    assert f'INPUTS_TAG = "{readiness.LAUNCHER_TAG}"' in launcher.read_text("utf-8")
