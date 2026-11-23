"""The event readiness record and fleet view report ready only when they can prove it."""

import json
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from botocore.exceptions import ClientError

from scripts import event_readiness as readiness

REAL_HTTP_GET = readiness.http_get
from scripts import readiness_checks as checks
from scripts.deploy_agentcore import RUNTIME_ROLES
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


NAME = "MosaicTools_abc"
REDEPLOY = (
    "Fix: in the box's terminal, before Lab 3, run uv run python "
    "scripts/deploy_agentcore.py deploy; it updates the runtime in place on V1"
)


def not_ready(line: Line) -> bool:
    """Whether this line alone makes an otherwise ready record not ready."""
    record = readiness.build_record(
        [Line("PASS", "Services", "active"), line],
        mode="live",
        instance_id="i",
        now=NOW,
    )
    return record["ready"] is False and record["final"] == f"x {line.text()}"


def without_platform(**overrides) -> dict:
    found = runtime(**overrides)
    del found["platformVersion"]
    return found


def test_runtime_on_v1_reads_ready_on_platform_v1():
    line = checks.runtime_platform_line(NAME, runtime())
    assert (
        line.text() == "PASS  AgentCore Runtime MosaicTools_abc: READY on platform V1"
    )
    assert not not_ready(line)


@pytest.mark.parametrize("platform", ["V2", "V3"])
def test_runtime_off_v1_is_not_ready_and_names_the_fix(platform):
    line = checks.runtime_platform_line(NAME, runtime(platformVersion=platform))
    assert line.text() == (
        f"FAIL  AgentCore Runtime MosaicTools_abc: platform {platform}, not the pinned "
        f"V1. {REDEPLOY}"
    )
    assert not_ready(line)


@pytest.mark.parametrize("platform", [None, ""])
def test_a_missing_platform_version_is_not_v1(platform):
    """Readiness confirms V1 positively: a runtime that names no platform is not ready."""
    found = without_platform() if platform is None else runtime(platformVersion="")
    line = checks.runtime_platform_line(NAME, found)
    assert line.text() == (
        "FAIL  AgentCore Runtime MosaicTools_abc: could not read the platform version "
        "(GetAgentRuntime returned no platformVersion)"
    )
    assert not_ready(line)


@pytest.mark.parametrize("status", ["UPDATING", "CREATE_FAILED", None])
def test_runtime_not_ready_is_not_ready(status):
    line = checks.runtime_platform_line(NAME, runtime(status=status))
    assert line.text() == (
        f"FAIL  AgentCore Runtime MosaicTools_abc: status {status}, not READY"
    )
    assert not_ready(line)


def runtimes_context(**overrides) -> checks.Context:
    arns = {
        variable: f"arn:aws:bedrock-agentcore:us-east-1:1:runtime/{variable}-id"
        for variable, _label, _role in RUNTIME_ROLES
    }
    return context(**{**arns, **overrides})


def runtimes_control(monkeypatch, **behaviour) -> Mock:
    from scripts import deploy_agentcore

    control = ready_control()
    for name, value in behaviour.items():
        setattr(control.get_agent_runtime, name, value)
    monkeypatch.setattr(deploy_agentcore, "client", lambda _service: control)
    return control


def test_each_runtime_gets_its_platform_line_then_its_deployment_line(monkeypatch):
    runtimes_control(
        monkeypatch,
        side_effect=lambda agentRuntimeId: runtime(
            agentRuntimeName=agentRuntimeId.removesuffix("-id")
        ),
    )
    lines = [line.text() for line in checks.check_runtimes(runtimes_context())]
    assert lines[0::2] == [
        f"PASS  AgentCore Runtime {variable}: READY on platform V1"
        for variable, _label, _role in RUNTIME_ROLES
    ]
    assert [text.split(":")[0] for text in lines[1::2]] == [
        f"PASS  {label}" for _variable, label, _role in RUNTIME_ROLES
    ]


def test_a_failed_read_is_not_ready(monkeypatch):
    runtimes_control(monkeypatch, side_effect=client_error("AccessDeniedException"))
    lines = checks.check_runtimes(runtimes_context())
    assert [line.text() for line in lines] == [
        f"FAIL  AgentCore Runtime {variable}-id: could not read the platform version "
        "(AccessDeniedException)"
        for variable, _label, _role in RUNTIME_ROLES
    ]


def test_a_runtime_arn_that_is_not_configured_is_not_ready(monkeypatch):
    control = runtimes_control(monkeypatch, return_value=runtime())
    variable = RUNTIME_ROLES[0][0]
    lines = checks.check_runtimes(runtimes_context(**{variable: ""}))
    assert lines[0].text() == (
        f"FAIL  AgentCore Runtime {variable}: could not read the platform version "
        f"({variable} is unset; fix: load this workshop's .env)"
    )
    assert control.get_agent_runtime.call_count == len(RUNTIME_ROLES) - 1


def test_a_runtime_not_ready_gets_no_deployment_line(monkeypatch):
    control = runtimes_control(monkeypatch, return_value=runtime(status="UPDATING"))
    lines = checks.check_runtimes(runtimes_context())
    assert [line.status for line in lines] == ["FAIL"] * len(RUNTIME_ROLES)
    control.get_agent_runtime_endpoint.assert_not_called()


def test_a_platform_check_that_crashes_did_not_finish(monkeypatch):
    from scripts import deploy_agentcore

    def broken(_service):
        raise RuntimeError("no Region\nlast words")

    monkeypatch.setattr(deploy_agentcore, "client", broken)
    lines = checks.run_checks(
        runtimes_context(), 5, ((checks.PLATFORM_CHECK, checks.check_runtimes),)
    )
    assert [line.text() for line in lines] == [
        "FAIL  AgentCore Runtime platform check did not finish: RuntimeError: last words"
    ]
    assert not_ready(lines[0])


def test_a_platform_check_that_prints_nothing_did_not_finish(monkeypatch):
    monkeypatch.setattr(checks, "runtime_lines", lambda _ctx: [])
    lines = checks.check_runtimes(runtimes_context())
    assert [line.text() for line in lines] == [
        "FAIL  AgentCore Runtime platform check did not finish: it printed no line"
    ]


def test_the_pinned_botocore_returns_the_platform_version():
    """The check reads platformVersion from the parsed response, so the pinned botocore
    must model it: 1.43.51 and 1.43.67 dropped it, and the line would then read
    "could not read" on every account."""
    import botocore.session

    model = botocore.session.get_session().get_service_model(
        "bedrock-agentcore-control"
    )
    assert (
        "platformVersion"
        in model.operation_model("GetAgentRuntime").output_shape.members
    )


def test_runtime_with_matching_models_passes_without_judging_the_platform():
    line = checks.runtime_line(
        context(), ready_control(), "Tools runtime", runtime(platformVersion="V2")
    )
    assert line.status == "PASS"
    assert "platform" not in line.detail


def test_only_the_readiness_record_runs_the_platform_check():
    """Versions rule 5 without a gate: the check lives in the readiness checks, which only
    event_readiness.py imports, and bootstrap writes that record after its SUCCESS
    signal, so it can fail neither the CloudFormation stack nor a participant command."""
    repo = Path(__file__).resolve().parents[1]
    importers = sorted(
        str(path.relative_to(repo))
        for folder in ("scripts", "service", "deploy", "labs")
        for path in (repo / folder).rglob("*.py")
        if path.name != "readiness_checks.py"
        and "readiness_checks" in path.read_text(encoding="utf-8")
    )
    assert importers == ["scripts/event_readiness.py"]
    bootstrap = (repo / "deploy" / "mosaic-bootstrap.sh").read_text(encoding="utf-8")
    # The signal that completes the stack, not the image-ready one before it.
    success = bootstrap.index('"Status":"SUCCESS","Reason":"Mosaic bootstrap complete"')
    runs = [
        (found.start(), found.group(1))
        for found in re.finditer(
            r"^\s*/usr/local/sbin/mosaic-readiness-record(.*)$", bootstrap, re.MULTILINE
        )
    ]
    # --failed records the failing phase and runs no check (tested above).
    checked = [
        start for start, rest in runs if not rest.lstrip().startswith("--failed")
    ]
    assert len(runs) == 2 and len(checked) == 1
    assert checked[0] > success


def test_runtime_without_a_container_image_fails_with_a_reason():
    code_only = runtime(agentRuntimeArtifact={"codeConfiguration": {"code": {}}})
    line = checks.runtime_line(context(), ready_control(), "Tools runtime", code_only)
    assert line.status == "FAIL"
    assert "no container image" in line.detail


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


class VersionRow:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class VersionConnection(Connection):
    def execute(self, *_):
        return VersionRow(self.rows)


def aurora_line(monkeypatch, row, psql_major="18"):
    repo = Path(checks.__file__).resolve().parents[1]
    monkeypatch.setattr(checks, "connect", lambda _ctx: VersionConnection(row))
    ctx = checks.Context(repo=repo, env={}, expected={"psql_major": psql_major})
    return checks.check_aurora(ctx)[0]


def test_aurora_check_passes_on_the_pinned_engine_and_extensions(monkeypatch):
    engine = checks.pinned_engine_version(Path(checks.__file__).resolve().parents[1])
    line = aurora_line(monkeypatch, (engine, "0.8.2", "1.6"))
    assert line.status == "PASS", line.detail
    assert engine == "18.6", (
        "the extension pins name 18.6's versions; move them together"
    )


@pytest.mark.parametrize(
    ("row", "psql_major", "named"),
    [
        (("18.3", "0.8.2", "1.6"), "18", "not the template's 18.6"),
        (("17.6", "0.8.2", "1.6"), "18", "not psql's 18"),
        (("18.6", "0.8.1", "1.6"), "18", "vector is 0.8.1, not 0.8.2"),
        (("18.6", None, "1.6"), "18", "vector is missing"),
        (("18.6", "0.8.2", "1.5"), "18", "pg_trgm is 1.5, not 1.6"),
        (("18.6", "0.8.2", None), "18", "pg_trgm is missing"),
    ],
)
def test_aurora_check_names_each_version_off_its_pin(
    monkeypatch, row, psql_major, named
):
    line = aurora_line(monkeypatch, row, psql_major)
    assert line.status == "FAIL"
    assert named in line.detail


def test_a_template_without_a_full_engine_pin_is_an_error(tmp_path):
    (tmp_path / checks.DATABASE_TEMPLATE).parent.mkdir(parents=True)
    (tmp_path / checks.DATABASE_TEMPLATE).write_text("      EngineVersion: '18'\n")
    with pytest.raises(checks.CheckError, match="pins no EngineVersion"):
        checks.pinned_engine_version(tmp_path)


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


EDITOR_DOMAIN = "d1editorexample.cloudfront.net"
EDITOR_TOKEN = "tkn-secret-0123456789"


def stack(status: str, **extra) -> dict:
    return {
        "StackId": "root",
        "StackName": "mosaic",
        "StackStatus": status,
        "CreationTime": NOW,
        "Parameters": [
            {"ParameterKey": "InfrastructureRevision", "ParameterValue": "x"}
        ],
        "Outputs": [
            {"OutputKey": "MosaicURL", "OutputValue": "https://d1shop.cloudfront.net/"},
            {
                "OutputKey": "CodeEditorURL",
                "OutputValue": f"https://{EDITOR_DOMAIN}/?workspace=/w&tkn={EDITOR_TOKEN}",
            },
        ],
        **extra,
    }


HEALTHY_WEB = {
    "/": (200, b"<!doctype html><html lang='en'>"),
    "/api/readiness": (200, b'{"status": "ready"}'),
    "/healthz": (200, b'{"hasActiveConnections": false}'),
}


class Web:
    """The participant's browser path: healthy unless a test says otherwise."""

    def __init__(self):
        self.answers: dict[str, list] = {}
        self.urls: list[str] = []

    def __call__(self, url: str):
        self.urls.append(url)
        path = urlsplit(url).path
        queued = self.answers.get(path)
        answer = queued.pop(0) if queued else HEALTHY_WEB[path]
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture(autouse=True)
def web(monkeypatch) -> Web:
    fake = Web()
    monkeypatch.setattr(readiness, "http_get", fake)
    monkeypatch.setattr(readiness, "WEB_PAUSE_SECONDS", 0)
    return fake


ROOT_ARN = "arn:aws:cloudformation:us-east-1:111122223333:stack/mosaic/0"
EDITOR_ARN = "arn:aws:cloudformation:us-east-1:111122223333:stack/mosaic-CodeEditor/1"


class Cfn:
    """DescribeStacks lists only live stacks; events stay readable by ARN after delete."""

    def __init__(self, stacks, events):
        self.stacks, self.events = stacks, events

    def get_paginator(self, name):
        if name == "describe_stacks":
            return Paginator([{"Stacks": self.stacks}])
        return SimpleNamespace(
            paginate=lambda StackName: iter([{"StackEvents": self.events[StackName]}])
        )


def test_rolled_back_stack_reports_the_deleted_nested_stacks_cause():
    cause = "catalog restore failed: no space left on device"
    tail = "x" * 400
    events = {
        ROOT_ARN: [
            {
                "ResourceStatus": "CREATE_FAILED",
                "Timestamp": NOW,
                "LogicalResourceId": "CodeEditorStack",
                "PhysicalResourceId": EDITOR_ARN,
                "ResourceType": "AWS::CloudFormation::Stack",
                "ResourceStatusReason": f"Embedded stack {EDITOR_ARN} was not created",
            },
            {
                "ResourceStatus": "ROLLBACK_COMPLETE",
                "Timestamp": NOW,
                "LogicalResourceId": "mosaic",
                "PhysicalResourceId": ROOT_ARN,
                "ResourceType": "AWS::CloudFormation::Stack",
            },
        ],
        EDITOR_ARN: [
            {
                "ResourceStatus": "CREATE_FAILED",
                "Timestamp": NOW - timedelta(minutes=1),
                "LogicalResourceId": "RuntimeImageRepository",
                "ResourceStatusReason": "Resource creation cancelled",
            },
            {
                "ResourceStatus": "CREATE_FAILED",
                "Timestamp": NOW - timedelta(minutes=2),
                "LogicalResourceId": "BootstrapWaitCondition",
                "ResourceStatusReason": "WaitCondition received failed message: 'Mosaic "
                f"bootstrap failed. Tail of the log: {tail} {cause}' for uniqueId: userdata",
            },
        ],
    }
    root = stack("ROLLBACK_COMPLETE", StackId=ROOT_ARN)
    row = readiness.no_record_row("123456789012", "us-east-1", Cfn([root], events))
    assert row.icon == "❌"
    assert row.status.startswith(
        "setup failed: BootstrapWaitCondition: WaitCondition received failed"
    )
    assert row.status.endswith(cause)
    assert len(row.status) < 240
    assert not row.ready


@pytest.mark.parametrize(
    "status", ["CREATE_FAILED", "ROLLBACK_IN_PROGRESS", "ROLLBACK_FAILED"]
)
def test_every_failed_setup_state_without_a_record_is_a_failure(status):
    root = stack(status, StackId=ROOT_ARN, StackStatusReason="The following failed")
    row = readiness.no_record_row("1", "us-east-1", Cfn([root], {ROOT_ARN: []}))
    assert (row.icon, row.status) == ("❌", "setup failed: The following failed")


def test_a_stack_still_creating_without_a_record_is_a_warning():
    root = stack("CREATE_IN_PROGRESS", StackId=ROOT_ARN)
    row = readiness.no_record_row("1", "us-east-1", Cfn([root], {ROOT_ARN: []}))
    assert (row.icon, row.status) == ("⚠️", "no record (CREATE_IN_PROGRESS)")


def test_account_without_a_stack_says_so():
    row = readiness.no_record_row("1", "us-east-1", Cfn([], {}))
    assert (row.icon, row.status) == (
        "⚠️",
        "no record (no workshop stack in this Region)",
    )


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
    recent = record(recordedAt=(datetime.now(UTC) - timedelta(hours=1)).isoformat())
    logs = logs_with([{"events": [{"timestamp": 1, "message": json.dumps(recent)}]}])
    cfn = Cfn([stack("CREATE_COMPLETE")], {})
    row, found = readiness.account_row(
        session_with(
            {"sts": sts, "logs": logs, "cloudformation": cfn, "ec2": editor_ec2()}
        ),
        "us-west-2",
        live=False,
        max_age=10**6,
    )
    assert (row.account, row.region, row.instance) == (
        "123456789012",
        "us-west-2",
        "i-0123456789abcdef0",
    )
    assert found["final"] == readiness.READY


# --- CloudFormation decides before the record ----------------------------------


READY_ROW = readiness.Row(
    "1", "us-east-1", "i-1", "2026-12-01 05:40", "✅", readiness.READY
)
FAILED_EVENT = {
    "StackId": "root",
    "LogicalResourceId": "AgentRuntime",
    "ResourceType": "AWS::BedrockAgentCore::Runtime",
    "ResourceStatus": "CREATE_FAILED",
    "ResourceStatusReason": "Runtime quota exceeded",
    "Timestamp": NOW,
}


@pytest.mark.parametrize(
    "status", ["ROLLBACK_COMPLETE", "CREATE_FAILED", "UPDATE_ROLLBACK_COMPLETE"]
)
def test_a_failed_or_rolled_back_stack_outranks_a_ready_record(status):
    cfn = Cfn([stack(status)], {"root": [FAILED_EVENT]})
    row = readiness.stack_verdict(READY_ROW, cfn)
    assert (row.icon, row.status) == (
        "❌",
        "setup failed: AgentRuntime: Runtime quota exceeded",
    )
    assert not row.ready


@pytest.mark.parametrize(
    "status", ["CREATE_IN_PROGRESS", "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS"]
)
def test_a_ready_record_on_a_stack_still_running_is_not_ready(status):
    row = readiness.stack_verdict(READY_ROW, Cfn([stack(status)], {}))
    assert (row.icon, row.status) == ("⚠️", f"setup still running ({status})")


@pytest.mark.parametrize("status", ["CREATE_COMPLETE", "UPDATE_COMPLETE"])
def test_a_finished_stack_lets_the_ready_record_decide(status):
    assert readiness.stack_verdict(READY_ROW, Cfn([stack(status)], {})) == READY_ROW


def test_a_failing_record_is_not_hidden_by_a_running_stack():
    failing = readiness.Row(
        "1", "us-east-1", "i-1", "-", "❌", "Memory: status CREATING"
    )
    assert readiness.stack_verdict(failing, Cfn([stack("CREATE_IN_PROGRESS")], {})) == (
        failing
    )


def test_a_ready_record_without_a_readable_stack_is_not_ready():
    missing = readiness.stack_verdict(READY_ROW, Cfn([], {}))
    assert (missing.icon, missing.status) == ("⚠️", "no workshop stack in this Region")
    cfn = Mock()
    cfn.get_paginator.side_effect = client_error("AccessDenied")
    denied = readiness.stack_verdict(READY_ROW, cfn)
    assert (denied.icon, denied.status) == ("⚠️", "cannot read: AccessDenied")
    deleting = readiness.stack_verdict(
        READY_ROW, Cfn([stack("DELETE_IN_PROGRESS")], {})
    )
    assert (deleting.icon, deleting.status) == (
        "⚠️",
        "setup not complete (DELETE_IN_PROGRESS)",
    )


def test_account_row_applies_the_stack_verdict_to_a_ready_record():
    sts = Mock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}
    logs = logs_with([{"events": [{"timestamp": 1, "message": json.dumps(record())}]}])
    cfn = Cfn([stack("ROLLBACK_COMPLETE")], {"root": [FAILED_EVENT]})
    row, _ = readiness.account_row(
        session_with(
            {"sts": sts, "logs": logs, "cloudformation": cfn, "ec2": editor_ec2()}
        ),
        "us-east-1",
        live=False,
        max_age=10**6,
    )
    assert (row.icon, row.status) == (
        "❌",
        "setup failed: AgentRuntime: Runtime quota exceeded",
    )


def test_a_reason_with_terminal_escapes_prints_as_plain_text():
    raw = "\x1b[31mBootstrap failed\x1b[0m\nline two\x07\ttab"
    assert readiness.short_reason(raw) == "Bootstrap failed line two tab"


def test_a_long_failing_record_line_keeps_its_fix_and_loses_its_escapes():
    fix = (
        "AgentCore Runtime mosaic_agent: platform V2, not the pinned V1. Fix: in the "
        "box's terminal, before Lab 3, run uv run python scripts/deploy_agentcore.py "
        "deploy; it updates the runtime in place on V1"
    )
    bad = record(ready=False, final=f"x FAIL  \x1b[1m{fix}\x1b[0m")
    row = readiness.record_row("1", "us-east-1", bad, NOW, 24)
    assert (row.icon, row.status) == ("❌", fix)


def root_start(status: str, at: datetime) -> dict:
    return {
        "ResourceStatus": status,
        "Timestamp": at,
        "LogicalResourceId": "mosaic",
        "PhysicalResourceId": ROOT_ARN,
        "ResourceType": "AWS::CloudFormation::Stack",
    }


def failure(name: str, at: datetime, reason: str) -> dict:
    return {
        "ResourceStatus": "CREATE_FAILED",
        "Timestamp": at,
        "LogicalResourceId": name,
        "ResourceType": "AWS::Lambda::Function",
        "ResourceStatusReason": reason,
    }


def test_only_failures_of_the_latest_root_operation_are_named():
    events = {
        ROOT_ARN: [
            failure("OldFunction", NOW - timedelta(hours=3), "an older failed update"),
            root_start("UPDATE_IN_PROGRESS", NOW - timedelta(hours=1)),
            failure(
                "NewFunction", NOW - timedelta(minutes=30), "this operation's cause"
            ),
        ]
    }
    root = stack("UPDATE_ROLLBACK_COMPLETE", StackId=ROOT_ARN)
    row = readiness.no_record_row("1", "us-east-1", Cfn([root], events))
    assert row.status == "setup failed: NewFunction: this operation's cause"


class VanishingNested(Cfn):
    """The root's events read; a nested stack's events cannot."""

    def get_paginator(self, name):
        if name == "describe_stacks":
            return super().get_paginator(name)

        def paginate(StackName):
            if StackName == EDITOR_ARN:
                raise client_error("ValidationError")
            return iter([{"StackEvents": self.events[StackName]}])

        return SimpleNamespace(paginate=paginate)


def test_a_nested_stack_that_cannot_be_read_does_not_hide_the_failure():
    events = {
        ROOT_ARN: [
            {
                "ResourceStatus": "CREATE_FAILED",
                "Timestamp": NOW,
                "LogicalResourceId": "CodeEditorStack",
                "PhysicalResourceId": EDITOR_ARN,
                "ResourceType": "AWS::CloudFormation::Stack",
                "ResourceStatusReason": f"Embedded stack {EDITOR_ARN} was not created",
            },
            failure("ReadinessLogs", NOW, "log group already exists"),
        ]
    }
    root = stack("ROLLBACK_COMPLETE", StackId=ROOT_ARN)
    row = readiness.no_record_row("1", "us-east-1", VanishingNested([root], events))
    assert (row.icon, row.status) == (
        "❌",
        "setup failed: ReadinessLogs: log group already exists",
    )


def test_a_failed_root_whose_events_cannot_be_read_still_fails():
    cfn = Mock()
    cfn.get_paginator.side_effect = lambda name: (
        Paginator([{"Stacks": [stack("ROLLBACK_COMPLETE", StackStatusReason="")]}])
        if name == "describe_stacks"
        else Paginator(error=client_error("Throttling"))
    )
    row = readiness.stack_verdict(READY_ROW, cfn)
    assert (row.icon, row.status) == ("❌", "setup failed: ROLLBACK_COMPLETE")


def test_live_never_runs_twice_on_one_box(tmp_path):
    for name in ("a.env", "b.env", "c.env"):
        write_account(tmp_path, name, "x")
    accounts = {"a": "111122223333", "b": "444455556666", "c": "111122223333"}
    ran = []

    def row(path, **_):
        ran.append(path.name)
        return readiness.Row(accounts[path.stem], "us-east-1", "-", "-", "✅", "ok")

    rows = readiness.fleet_rows(
        tmp_path,
        live=True,
        max_age=24,
        row=row,
        account_of=lambda path: accounts[path.stem],
    )
    assert sorted(ran) == ["a.env", "b.env"]
    assert (rows[2].icon, rows[2].status) == ("⚠️", "same account as a.env")


# --- a record speaks only for this stack and its own box --------------------


BOX = "i-0123456789abcdef0"


def editor_stack(instance_id: str = BOX, root_id: str = "root") -> dict:
    """The nested Code Editor stack, with the instance it created as an output."""
    return {
        "StackId": "editor",
        "StackName": "mosaic-CodeEditorStack",
        "ParentId": root_id,
        "RootId": root_id,
        "StackStatus": "CREATE_COMPLETE",
        "CreationTime": NOW,
        "Outputs": [{"OutputKey": "EditorInstanceId", "OutputValue": instance_id}],
    }


def with_editor(root: dict, instance_id: str = BOX) -> Cfn:
    return Cfn([root, editor_stack(instance_id)], {})


def editor_ec2(state: str = "running") -> Mock:
    ec2 = Mock()
    ec2.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"InstanceId": BOX, "State": {"Name": state}}]}]
    }
    return ec2


def fresh(**overrides) -> dict:
    """A READY record that reached CloudWatch after the test stack was created."""
    later = (NOW + timedelta(minutes=30)).isoformat()
    return record(recordedAt=later, ingestedAt=later, **overrides)


def test_a_record_from_this_stacks_running_box_counts(web):
    cfn = with_editor(stack("CREATE_COMPLETE"))
    assert readiness.stack_verdict(READY_ROW, cfn, fresh(), editor_ec2()) == READY_ROW


def test_a_record_received_before_the_stack_is_not_this_stacks(web):
    old = (NOW - timedelta(minutes=5)).isoformat()
    cfn = with_editor(stack("CREATE_COMPLETE"))
    row = readiness.stack_verdict(
        READY_ROW, cfn, record(recordedAt=old, ingestedAt=old), editor_ec2()
    )
    assert (row.icon, row.status) == (
        "⚠️",
        "no record (the newest record predates this stack)",
    )
    assert web.urls == []


def test_a_fast_box_clock_cannot_make_an_old_record_current(web):
    stale = record(
        recordedAt=(NOW + timedelta(hours=2)).isoformat(),
        ingestedAt=(NOW - timedelta(minutes=5)).isoformat(),
    )
    cfn = with_editor(stack("CREATE_COMPLETE"))
    row = readiness.stack_verdict(READY_ROW, cfn, stale, editor_ec2())
    assert row.status == "no record (the newest record predates this stack)"


def test_a_record_older_than_an_update_is_not_this_stacks(web):
    updated = stack("UPDATE_COMPLETE", LastUpdatedTime=NOW + timedelta(hours=1))
    row = readiness.stack_verdict(
        READY_ROW, with_editor(updated), fresh(), editor_ec2()
    )
    assert row.status == "no record (the newest record predates this stack)"


def test_a_created_stacks_own_update_time_does_not_hide_its_record(web):
    created = stack("CREATE_COMPLETE", LastUpdatedTime=NOW + timedelta(hours=1))
    row = readiness.stack_verdict(
        READY_ROW, with_editor(created), fresh(), editor_ec2()
    )
    assert row == READY_ROW


def test_a_record_from_another_instance_does_not_count(web):
    cfn = with_editor(stack("CREATE_COMPLETE"), instance_id="i-replacement")
    row = readiness.stack_verdict(READY_ROW, cfn, fresh(), editor_ec2())
    assert (row.icon, row.status) == (
        "⚠️",
        "no record (the newest record is from another instance)",
    )


def test_a_leftover_editor_of_another_stack_is_not_this_stacks(web):
    other = editor_stack("i-0123456789abcdef0", root_id="another-root")
    cfn = Cfn([stack("CREATE_COMPLETE"), other], {})
    row = readiness.stack_verdict(READY_ROW, cfn, fresh(), editor_ec2())
    assert (row.icon, row.status) == ("⚠️", "cannot read: NoEditorInstanceIdOutput")


@pytest.mark.parametrize("state", ["stopped", "terminated"])
def test_this_stacks_editor_not_running_is_a_failure(web, state):
    cfn = with_editor(stack("CREATE_COMPLETE"))
    row = readiness.stack_verdict(READY_ROW, cfn, fresh(), editor_ec2(state))
    assert (row.icon, row.status) == ("❌", "Code Editor instance not running")


def test_an_editor_instance_that_no_longer_exists_is_not_running(web):
    ec2 = Mock()
    ec2.describe_instances.side_effect = client_error("InvalidInstanceID.NotFound")
    cfn = with_editor(stack("CREATE_COMPLETE"))
    row = readiness.stack_verdict(READY_ROW, cfn, fresh(), ec2)
    assert (row.icon, row.status) == ("❌", "Code Editor instance not running")


def test_an_unreadable_instance_is_not_ready(web):
    ec2 = Mock()
    ec2.describe_instances.side_effect = client_error("UnauthorizedOperation")
    cfn = with_editor(stack("CREATE_COMPLETE"))
    row = readiness.stack_verdict(READY_ROW, cfn, fresh(), ec2)
    assert (row.icon, row.status) == ("⚠️", "cannot read: UnauthorizedOperation")


def test_the_log_read_keeps_cloudwatchs_receipt_time():
    event = {
        "timestamp": 1,
        "ingestionTime": int(NOW.timestamp() * 1000),
        "message": json.dumps(record()),
    }
    found = readiness.latest_record(logs_with([{"events": [event]}]))
    assert datetime.fromisoformat(found["ingestedAt"]) == NOW


def test_the_newest_record_is_the_one_cloudwatch_received_last():
    fast_old_box = {
        "timestamp": 9_000,
        "ingestionTime": 1_000,
        "message": json.dumps(record(final="from the old box")),
    }
    current_box = {
        "timestamp": 2_000,
        "ingestionTime": 2_000,
        "message": json.dumps(record(final="from the current box")),
    }
    found = readiness.latest_record(
        logs_with([{"events": [fast_old_box, current_box]}])
    )
    assert found["final"] == "from the current box"


def test_live_targets_the_instance_this_stack_created():
    session = session_with({"cloudformation": with_editor(stack("CREATE_COMPLETE"))})
    assert readiness.box_instance(session) == BOX


def test_live_without_this_stacks_editor_output_targets_nothing():
    session = session_with({"cloudformation": Cfn([stack("CREATE_COMPLETE")], {})})
    with pytest.raises(readiness.CannotRead) as missing:
        readiness.box_instance(session)
    assert missing.value.code == "NoEditorInstanceIdOutput"


def test_one_stack_listing_serves_the_status_and_the_editor():
    cfn = with_editor(stack("CREATE_COMPLETE"))
    listings = []
    real = cfn.get_paginator

    def counting(name):
        listings.append(name)
        return real(name)

    cfn.get_paginator = counting
    readiness.stack_verdict(READY_ROW, cfn, fresh(), editor_ec2())
    assert listings.count("describe_stacks") == 1


def test_a_fetch_that_outlives_its_deadline_fails_without_waiting_for_it(monkeypatch):
    release = threading.Event()

    def hung(_url):
        release.wait(5)
        return 200, b"<html>"

    monkeypatch.setattr(readiness, "http_get", hung)
    monkeypatch.setattr(readiness, "WEB_DEADLINE_SECONDS", 0.05)
    started = time.monotonic()
    with pytest.raises(readiness.DeadlineExceeded):
        readiness.bounded_get("https://d1shop.cloudfront.net/")
    assert time.monotonic() - started < 1
    release.set()


def test_two_records_received_together_are_ordered_by_the_box_time():
    first = {
        "timestamp": 1,
        "ingestionTime": 5,
        "message": json.dumps(record(final="a")),
    }
    second = {
        "timestamp": 2,
        "ingestionTime": 5,
        "message": json.dumps(record(final="b")),
    }
    found = readiness.latest_record(logs_with([{"events": [second, first]}]))
    assert found["final"] == "b"


# --- the participant's browser path ------------------------------------------


def complete() -> Cfn:
    return Cfn([stack("CREATE_COMPLETE")], {})


def test_a_ready_account_reads_its_storefront_and_editor_without_the_token(web):
    assert readiness.stack_verdict(READY_ROW, complete()) == READY_ROW
    assert web.urls == [
        "https://d1shop.cloudfront.net/",
        "https://d1shop.cloudfront.net/api/readiness",
        f"https://{EDITOR_DOMAIN}/healthz",
    ]
    assert not any(EDITOR_TOKEN in url for url in web.urls)


@pytest.mark.parametrize(
    ("path", "answer", "status"),
    [
        ("/", (502, b"Bad Gateway"), "storefront does not answer (HTTP 502)"),
        ("/", (200, b"{}"), "storefront does not answer (not an HTML page)"),
        (
            "/api/readiness",
            (503, b"Database is not ready"),
            "storefront does not answer (HTTP 503)",
        ),
        (
            "/api/readiness",
            (200, b'{"status": "degraded"}'),
            "storefront does not answer (database not ready)",
        ),
        ("/healthz", (403, b"Forbidden."), "Code Editor does not answer (HTTP 403)"),
        (
            "/healthz",
            (200, b"<html>"),
            "Code Editor does not answer (health is not JSON)",
        ),
    ],
)
def test_a_browser_path_that_does_not_answer_is_not_ready(web, path, answer, status):
    web.answers[path] = [answer] * readiness.WEB_ATTEMPTS
    row = readiness.stack_verdict(READY_ROW, complete())
    assert (row.icon, row.status) == ("❌", status)
    assert EDITOR_TOKEN not in row.status
    assert EDITOR_DOMAIN not in row.status
    assert "d1shop" not in row.status


def test_one_dropped_connection_is_tried_again(web):
    web.answers["/healthz"] = [TimeoutError("timed out")]
    assert readiness.stack_verdict(READY_ROW, complete()) == READY_ROW
    assert web.urls.count(f"https://{EDITOR_DOMAIN}/healthz") == 2


def test_a_connection_dropped_on_every_try_fails_with_the_error_name(web):
    web.answers["/"] = [ConnectionResetError()] * readiness.WEB_ATTEMPTS
    row = readiness.stack_verdict(READY_ROW, complete())
    assert (row.icon, row.status) == (
        "❌",
        "storefront does not answer (ConnectionResetError)",
    )


def test_a_stack_without_its_url_outputs_is_not_ready(web):
    bare = stack("CREATE_COMPLETE")
    bare["Outputs"] = [o for o in bare["Outputs"] if o["OutputKey"] != "CodeEditorURL"]
    row = readiness.stack_verdict(READY_ROW, Cfn([bare], {}))
    assert (row.icon, row.status) == (
        "❌",
        "Code Editor does not answer (no usable CodeEditorURL)",
    )
    assert not readiness.stack_verdict(
        READY_ROW, Cfn([{**bare, "Outputs": []}], {})
    ).ready


@pytest.mark.parametrize(
    "url",
    [
        "http://d1shop.cloudfront.net/",
        "https://user:pw@d1shop.cloudfront.net/",
        "https://d1shop.cloudfront.net:8443/",
        "https://d1shop.example.com/",
        "https://cloudfront.net/",
        "https://d1shop.cloudfront.net.example.com/",
        "not a url",
    ],
)
def test_an_output_url_outside_cloudfront_is_never_fetched(web, url):
    odd = stack("CREATE_COMPLETE")
    odd["Outputs"] = [
        {**o, "OutputValue": url} if o["OutputKey"] == "MosaicURL" else o
        for o in odd["Outputs"]
    ]
    row = readiness.stack_verdict(READY_ROW, Cfn([odd], {}))
    assert (row.icon, row.status) == (
        "❌",
        "storefront does not answer (no usable MosaicURL)",
    )
    assert web.urls == []


def test_a_redirect_is_the_answer_and_is_never_followed():
    import http.server
    import threading

    followed = []

    class Server(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/elsewhere":
                followed.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"<html>")
                return
            self.send_response(302)
            self.send_header("Location", "/elsewhere")
            self.end_headers()

        def log_message(self, *_args):
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), Server)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _ = REAL_HTTP_GET(f"http://127.0.0.1:{server.server_port}/")
    finally:
        server.shutdown()
    assert status == 302
    assert followed == []


def test_readiness_gets_three_tries_and_the_page_and_editor_two(web):
    web.answers["/api/readiness"] = [(503, b"x"), (503, b"x")]
    assert readiness.stack_verdict(READY_ROW, complete()) == READY_ROW
    web.urls.clear()
    web.answers["/"] = [(502, b"x"), (502, b"x")]
    row = readiness.stack_verdict(READY_ROW, complete())
    assert row.status == "storefront does not answer (HTTP 502)"
    assert web.urls.count("https://d1shop.cloudfront.net/") == readiness.PAGE_ATTEMPTS


def test_an_account_stops_trying_when_its_time_budget_is_spent(web, monkeypatch):
    clock = iter([0.0, 0.0, 61.0, 61.0, 61.0, 61.0])
    monkeypatch.setattr(readiness.time, "monotonic", lambda: next(clock, 61.0))
    web.answers["/"] = [(502, b"x")]
    row = readiness.stack_verdict(READY_ROW, complete())
    assert (
        row.status == "storefront does not answer (HTTP 502; account time budget spent)"
    )


def test_a_malformed_http_reply_is_retried_like_any_dropped_connection(web):
    import http.client

    web.answers["/healthz"] = [http.client.IncompleteRead(b"")]
    assert readiness.stack_verdict(READY_ROW, complete()) == READY_ROW


def test_editor_json_without_its_health_field_is_not_the_editor(web):
    web.answers["/healthz"] = [(200, b'{"status": "ok"}')] * readiness.PAGE_ATTEMPTS
    row = readiness.stack_verdict(READY_ROW, complete())
    assert row.status == "Code Editor does not answer (not the Code Editor's health)"


def test_a_ready_phrase_without_the_ready_flag_is_not_ready():
    odd = record(ready=False, final=readiness.READY)
    assert readiness.record_row("1", "us-east-1", odd, NOW, 24).icon == "❌"


def test_no_cell_can_carry_a_terminal_or_bidi_control():
    sly = "\u202eYDAER\u200b\x1b[2J"
    row = readiness.Row("1", "us-east-1", f"i-1{sly}", "-", "⚠️", f"oops {sly}")
    line = readiness.table([row])[1]
    for char in ("\u202e", "\u200b", "\x1b"):
        assert char not in line
    assert "⚠️" in readiness.table([row])[1]


def test_a_record_that_is_not_ready_skips_the_browser_path(web):
    failing = readiness.Row("1", "us-east-1", "i-1", "-", "❌", "Memory: CREATING")
    assert readiness.stack_verdict(failing, complete()) == failing
    assert web.urls == []


# --- the saved run and the morning recheck -----------------------------------


A, B, C = "111122223333", "444455556666", "123456789012"


def saved_row(account: str, icon: str = "✅", status: str = readiness.READY) -> object:
    return readiness.Row(
        account,
        "us-east-1",
        "i-1",
        "2026-12-01 05:40",
        icon,
        status,
        storefront="d1shop.cloudfront.net",
        editor=EDITOR_DOMAIN,
    )


def saved_file(tmp_path, rows, at=None) -> Path:
    path = tmp_path / "mosaic-run.json"
    readiness.save_run(path, rows, at or datetime.now(UTC))
    return path


def test_the_saved_run_is_private_and_keeps_hosts_never_a_token(tmp_path):
    path = saved_file(tmp_path, [saved_row(A)])
    assert path.stat().st_mode & 0o777 == 0o600
    text = path.read_text()
    assert EDITOR_DOMAIN in text and "d1shop.cloudfront.net" in text
    assert EDITOR_TOKEN not in text and "tkn" not in text
    assert json.loads(text)["accounts"][A]["ready"] is True


def test_saving_merges_by_account_and_never_saves_an_unread_or_repeated_row(tmp_path):
    path = saved_file(tmp_path, [saved_row(A)])
    unread = readiness.Row("-", "-", "-", "-", "⚠️", "cannot read: ExpiredToken")
    repeat = readiness.Row(B, "-", "-", "-", "⚠️", "same account as b.env")
    readiness.save_run(
        path,
        [saved_row(B, "❌", "Memory: CREATING"), unread, repeat],
        datetime.now(UTC),
    )
    accounts = json.loads(path.read_text())["accounts"]
    assert sorted(accounts) == [A, B]
    assert accounts[B]["status"] == "❌ Memory: CREATING"


def test_a_damaged_saved_run_is_moved_aside_and_saving_continues(tmp_path, capsys):
    path = tmp_path / "mosaic-run.json"
    path.write_text("{not json")
    path.chmod(0o600)
    readiness.save_run(path, [saved_row(A)], datetime(2026, 12, 1, 6, 0, tzinfo=UTC))
    assert (tmp_path / "mosaic-run.json.damaged-20261201T060000Z").exists()
    assert A in json.loads(path.read_text())["accounts"]
    assert "could not be read" in capsys.readouterr().out


def test_the_recheck_makes_no_aws_call_and_passes_a_ready_account(
    tmp_path, web, monkeypatch
):
    import boto3

    def no_aws(*_args, **_kwargs):
        raise AssertionError("the recheck must not call AWS")

    monkeypatch.setattr(boto3, "Session", no_aws)
    monkeypatch.setattr(boto3, "client", no_aws)
    rows = readiness.recheck_rows(saved_file(tmp_path, [saved_row(A)]), None, 36)
    assert [(r.account, r.icon, r.status) for r in rows] == [(A, "✅", readiness.READY)]
    assert web.urls[-1] == f"https://{EDITOR_DOMAIN}/healthz"


def test_the_recheck_keeps_an_account_that_was_not_ready(tmp_path, web):
    path = saved_file(tmp_path, [saved_row(A, "❌", "Memory: CREATING")])
    row = readiness.recheck_rows(path, None, 36)[0]
    assert (row.icon, row.status) == (
        "⚠️",
        "not ready at the saved run (❌ Memory: CREATING)",
    )
    assert web.urls == []


def test_the_recheck_fails_an_account_whose_browser_path_stopped_answering(
    tmp_path, web
):
    web.answers["/api/readiness"] = [(503, b"x")] * readiness.WEB_ATTEMPTS
    row = readiness.recheck_rows(saved_file(tmp_path, [saved_row(A)]), None, 36)[0]
    assert (row.icon, row.status) == ("❌", "storefront does not answer (HTTP 503)")


def test_the_recheck_never_fetches_a_host_edited_into_the_file(tmp_path, web):
    path = saved_file(tmp_path, [saved_row(A)])
    saved = json.loads(path.read_text())
    saved["accounts"][A]["storefront"] = "attacker.example.com"
    path.write_text(json.dumps(saved))
    row = readiness.recheck_rows(path, None, 36)[0]
    assert row.status == "storefront does not answer (no usable MosaicURL)"
    assert web.urls == []


def test_a_saved_run_older_than_its_limit_must_be_run_again(tmp_path, web):
    old = datetime.now(UTC) - timedelta(hours=40)
    row = readiness.recheck_rows(saved_file(tmp_path, [saved_row(A)], old), None, 36)[0]
    assert (row.icon, row.status) == ("⚠️", "saved run STALE (40 h old); run --accounts")


def test_the_recheck_refuses_a_saved_run_others_can_read(tmp_path):
    path = saved_file(tmp_path, [saved_row(A)])
    path.chmod(0o644)
    with pytest.raises(readiness.SavedRunError, match="chmod 600"):
        readiness.recheck_rows(path, None, 36)


def test_the_teams_csv_finds_missed_and_foreign_accounts_without_join_urls(
    tmp_path, web
):
    path = saved_file(tmp_path, [saved_row(A), saved_row(B)])
    teams = tmp_path / "teams.csv"
    teams.write_text(
        "Team name,AWS account ID,Join event URL\n"
        f"Team 1,{A},https://catalog.workshops.aws/join?access-code=SECRET1\n"
        f"Team 3,{C},https://catalog.workshops.aws/join?access-code=SECRET3\n"
    )
    rows = readiness.recheck_rows(path, teams, 36)
    assert [(r.account, r.icon, r.status) for r in rows] == [
        (A, "✅", readiness.READY),
        (B, "⚠️", "not a team of this event"),
        (C, "⚠️", "not in the saved run (Team 3)"),
    ]
    printed = "\n".join(readiness.table(rows))
    assert "SECRET" not in printed and "join" not in printed
    assert readiness.exit_status(rows) == 1


def test_a_csv_that_is_not_the_teams_export_is_refused(tmp_path):
    path = saved_file(tmp_path, [saved_row(A)])
    other = tmp_path / "other.csv"
    other.write_text("name,email\nx,y\n")
    with pytest.raises(readiness.SavedRunError, match="Download CSV"):
        readiness.recheck_rows(path, other, 36)


@pytest.mark.parametrize(
    "argv",
    [
        ["--save", "x.json"],
        ["--teams", "t.csv"],
        ["--recheck", "{run}", "--live"],
        ["--recheck", "{run}", "--accounts", "{dir}"],
        ["--recheck", "{dir}/missing.json"],
    ],
)
def test_save_recheck_and_teams_are_refused_out_of_place(tmp_path, argv):
    run = saved_file(tmp_path, [saved_row(A)])
    filled = [a.format(run=run, dir=tmp_path) for a in argv]
    with pytest.raises(SystemExit) as refused:
        readiness.main(filled)
    assert refused.value.code == 2


def test_main_rechecks_a_saved_run_and_exits_by_its_rows(tmp_path, web, capsys):
    run = saved_file(tmp_path, [saved_row(A)])
    assert readiness.main(["--recheck", str(run)]) == 0
    assert capsys.readouterr().out.strip().endswith("1 of 1 ready")


def test_main_saves_after_a_fleet_read(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        readiness, "fleet_rows", lambda *_a, **_k: [saved_row(A), saved_row(B)]
    )
    target = tmp_path / "run.json"
    assert readiness.main(["--accounts", str(tmp_path), "--save", str(target)]) == 0
    assert sorted(json.loads(target.read_text())["accounts"]) == [A, B]


# --- records and files that cannot be trusted ----------------------------------


@pytest.mark.parametrize(
    "recorded_at",
    [
        None,
        "not a time",
        "2026-12-01T05:40:00",
        (NOW + timedelta(minutes=10)).isoformat(),
    ],
)
def test_a_record_without_a_trustworthy_time_is_malformed(recorded_at):
    odd = record(recordedAt=recorded_at)
    if recorded_at is None:
        odd.pop("recordedAt")
    row = readiness.record_row("1", "us-east-1", odd, NOW, 24)
    assert (row.icon, row.status) == ("⚠️", "cannot read: MalformedRecord")


def test_a_record_that_is_not_an_object_is_malformed():
    row = readiness.record_row("1", "us-east-1", ["READY FOR LAB 1"], NOW, 24)
    assert (row.icon, row.status) == ("⚠️", "cannot read: MalformedRecord")


def test_log_read_looks_back_fourteen_days_and_stops_at_a_page_cap():
    seen = {}

    class Counting(Paginator):
        def paginate(self, **query):
            seen.update(query)
            return iter([{"events": []}] * (readiness.MAX_LOG_PAGES + 1))

    logs = Mock()
    logs.get_paginator.return_value = Counting()
    with pytest.raises(readiness.CannotRead) as too_many:
        readiness.latest_record(logs)
    assert too_many.value.code == "TooManyLogEvents"
    lookback = datetime.now(UTC) - datetime.fromtimestamp(seen["startTime"] / 1000, UTC)
    assert timedelta(days=14) - lookback < timedelta(minutes=1)


def test_two_values_for_one_key_in_one_file_are_refused(tmp_path):
    block = (
        'export AWS_ACCESS_KEY_ID="ASIAONE"\nexport AWS_SECRET_ACCESS_KEY="s1"\n'
        'export AWS_ACCESS_KEY_ID="ASIATWO"\nAWS_DEFAULT_REGION=us-east-1\n'
    )
    path = write_account(tmp_path, "pasted-twice.env", block)
    row = readiness.file_row(path, live=False, max_age=24)
    assert (
        row.status == "cannot read: DuplicateKey AWS_ACCESS_KEY_ID (pasted-twice.env)"
    )
    assert "ASIA" not in row.status


def test_the_same_key_repeated_with_the_same_value_is_accepted():
    values = readiness.parse_credentials("AWS_DEFAULT_REGION=us-east-1\n" * 2)
    assert values == {"AWS_DEFAULT_REGION": "us-east-1"}


@pytest.mark.parametrize("region", ["us-east-1x", "useast1", "US-EAST-1", "east-us"])
def test_a_region_that_is_not_a_region_name_is_refused_without_printing_it(
    tmp_path, region
):
    block = (
        'export AWS_ACCESS_KEY_ID="ASIAX"\nexport AWS_SECRET_ACCESS_KEY="s"\n'
        f"AWS_DEFAULT_REGION={region}\n"
    )
    row = readiness.file_row(
        write_account(tmp_path, "a.env", block), live=False, max_age=24
    )
    assert row.status.startswith("cannot read: InvalidRegion (a.env;")
    assert region not in row.status


def test_a_second_file_for_the_same_account_is_not_counted(tmp_path):
    for name in ("a.env", "b.env", "c.env"):
        write_account(tmp_path, name, "x")
    accounts = {"a": "111122223333", "b": "444455556666", "c": "111122223333"}

    def row(path, **_):
        return readiness.Row(accounts[path.stem], "us-east-1", "-", "-", "✅", "ok")

    rows = readiness.fleet_rows(tmp_path, live=False, max_age=24, row=row)
    assert [(r.icon, r.status) for r in rows] == [
        ("✅", "ok"),
        ("✅", "ok"),
        ("⚠️", "same account as a.env"),
    ]
    assert readiness.table(rows)[-1] == "2 of 3 ready"
    assert readiness.exit_status(rows) == 1


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
    def __init__(self, status, code=None, output=""):
        self.status, self.code, self.output = status, code, output
        self.sent = []

    def send_command(self, **kwargs):
        self.sent.append(kwargs)
        return {"Command": {"CommandId": "c-1"}}

    def get_command_invocation(self, **_):
        return {
            "Status": self.status,
            "ResponseCode": self.code,
            "StandardOutputContent": self.output,
        }


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


def live_stack() -> Cfn:
    """The stack whose nested Code Editor stack created the box --live targets."""
    return with_editor(stack("CREATE_COMPLETE"))


def test_live_returns_the_new_record_even_when_the_command_failed():
    ssm = Invocations("Failed")
    logs = ReadsInTurn([event(record())], [event(record(mode="live", ready=False), 9)])
    found = readiness.live_record(
        session_with({"logs": logs, "ssm": ssm, "cloudformation": live_stack()}),
        sleep=lambda _s: None,
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
            session_with(
                {
                    "logs": logs,
                    "ssm": Invocations("Failed"),
                    "cloudformation": live_stack(),
                }
            ),
            sleep=lambda _s: None,
        )
    assert missing.value.code.startswith("LiveCommandFailed on i-0123456789abcdef0")


def test_live_on_the_box_refuses_a_started_lab_before_any_check(monkeypatch, capsys):
    def no_checks(_args):
        pytest.fail("a check ran on a box where a lab has started")

    monkeypatch.setattr(readiness, "box_lines", no_checks)
    logs = Mock()
    args = readiness.parser().parse_args(["--record", "--live"])
    status = readiness.record_on_box(args, logs=logs, busy=lambda: "Lab 2")
    assert status == readiness.LAB_IN_PROGRESS_EXIT
    assert json.loads(capsys.readouterr().out) == {"labInProgress": "Lab 2"}
    assert not logs.method_calls


def test_bootstrap_record_ignores_the_lab_guard(monkeypatch, capsys):
    monkeypatch.setattr(readiness, "imds_instance_id", lambda: "i-1")
    monkeypatch.setattr(
        readiness, "box_lines", lambda _a: ("bootstrap", [Line("PASS", "S", "ok")])
    )
    args = readiness.parser().parse_args(["--record"])
    assert readiness.record_on_box(args, logs=Mock(), busy=lambda: "Lab 1") == 0


def test_started_and_unreadable_lab_state(monkeypatch):
    from scripts import lab_entry

    monkeypatch.setattr(
        lab_entry, "load_record", lambda lab, _r: {} if lab < 3 else None
    )
    assert readiness.lab_in_progress() == "Lab 2"
    monkeypatch.setattr(lab_entry, "load_record", lambda lab, _r: None)
    assert readiness.lab_in_progress() is None

    def unreadable(_lab, _repo):
        raise ValueError("bad json")

    monkeypatch.setattr(lab_entry, "load_record", unreadable)
    assert readiness.lab_in_progress() == "lab state unreadable: ValueError"


def test_fleet_row_for_a_box_with_a_lab_in_progress_keeps_the_old_record(monkeypatch):
    monkeypatch.setattr(readiness, "LIVE_POLL_SECONDS", 0)
    sts = Mock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}
    previous = record()
    logs = ReadsInTurn([event(previous)], [event(previous)])
    ssm = Invocations("Failed", code=3, output='{"labInProgress": "Lab 2"}\n')
    row, shown = readiness.account_row(
        session_with(
            {"sts": sts, "logs": logs, "ssm": ssm, "cloudformation": live_stack()}
        ),
        "us-east-1",
        live=True,
        max_age=24,
    )
    assert (row.icon, row.status) == ("⚠️", "lab in progress (Lab 2), not rechecked")
    assert (row.instance, row.recorded) == ("i-0123456789abcdef0", "2026-12-01 05:40")
    assert shown == previous
    assert not row.ready


# --- the box's SQL against Aurora itself --------------------------------------


def live_context() -> checks.Context:
    from service.config import get_settings

    return checks.Context(
        repo=Path(checks.__file__).resolve().parents[1],
        env={"DATABASE_URL": get_settings().database_url},
        expected={"psql_major": "18"},
    )


@pytest.mark.aurora
def test_fuzzy_control_binds_to_search_fuzzys_real_signature():
    """A mocked connection accepted argument types Aurora's function does not."""
    line = checks.check_fuzzy_control(live_context())[0]
    assert line.status == "PASS", line.detail


@pytest.mark.aurora
def test_aurora_versions_read_from_the_cluster():
    line = checks.check_aurora(live_context())[0]
    assert line.status == "PASS", line.detail
    assert line.detail.startswith("PostgreSQL 18.")
