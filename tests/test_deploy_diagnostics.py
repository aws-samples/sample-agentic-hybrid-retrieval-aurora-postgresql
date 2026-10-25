"""Deployment must narrate long waits and name the cause and next command on failure."""

import subprocess
import sys
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from scripts import deploy_agentcore as deploy
from service.participant_commands import DEPLOY_AGENT, VERIFY_AGENT

URI = "123456789012.dkr.ecr.us-east-1.amazonaws.com/workshop"


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(deploy.time, "sleep", lambda *_: None)


def test_failed_runtime_prints_its_failure_reason_and_the_retry_command():
    control = Mock()
    control.get_agent_runtime.return_value = {
        "status": "UPDATE_FAILED",
        "failureReason": "Image pull failed: manifest unknown",
    }
    with pytest.raises(RuntimeError) as raised:
        deploy.wait_runtime(control, "mosaic_agent-AbC123", "agent runtime")
    message = str(raised.value)
    assert "UPDATE_FAILED" in message
    assert "Image pull failed: manifest unknown" in message
    assert DEPLOY_AGENT in message


def test_runtime_wait_returns_once_the_endpoint_serves_the_new_version():
    control = Mock()
    control.get_agent_runtime.side_effect = [
        {"status": "UPDATING", "agentRuntimeVersion": "2"},
        {"status": "UPDATING", "agentRuntimeVersion": "2"},
        {"status": "READY", "agentRuntimeVersion": "2"},
    ]
    control.get_agent_runtime_endpoint.return_value = {
        "status": "READY",
        "liveVersion": "2",
    }
    runtime = deploy.wait_runtime(control, "mosaic_agent-AbC123", "agent runtime")
    assert runtime["agentRuntimeVersion"] == "2"
    assert control.get_agent_runtime.call_count == 3


def test_runtime_timeout_names_the_last_state(monkeypatch):
    control = Mock()
    control.get_agent_runtime.return_value = {
        "status": "UPDATING",
        "agentRuntimeVersion": "2",
    }
    clock = iter([0, 1, 2, 901, 902, 903])
    monkeypatch.setattr(deploy.time, "monotonic", lambda: next(clock))
    with pytest.raises(TimeoutError) as raised:
        deploy.wait_runtime(control, "mosaic_agent-AbC123", "agent runtime")
    assert "UPDATING" in str(raised.value)
    assert DEPLOY_AGENT in str(raised.value)


def gateway_environment(monkeypatch, control, states):
    for name in (
        "MOSAIC_AGENTCORE_TOOLS_RUNTIME_ARN",
        "MOSAIC_AGENTCORE_RUNTIME_ARN",
    ):
        monkeypatch.setenv(name, "arn:aws:x:us-east-1:123456789012:runtime/r")
    monkeypatch.setenv("MOSAIC_AGENTCORE_GATEWAY_ID", "gateway-id")
    monkeypatch.setenv("MOSAIC_AGENTCORE_GATEWAY_TARGET_ID", "target-id")
    control.meta.service_model.operation_model.return_value.input_shape.members = {}
    control.get_agent_runtime.return_value = {}
    control.get_gateway_target.side_effect = states
    monkeypatch.setattr(deploy, "client", lambda _: control)
    monkeypatch.setattr(deploy, "wait_runtime", lambda *_: {"agentRuntimeVersion": "2"})


def test_failed_gateway_sync_prints_the_first_status_reason(monkeypatch):
    control = Mock()
    gateway_environment(
        monkeypatch,
        control,
        [
            {
                "status": "SYNCHRONIZE_UNSUCCESSFUL",
                "statusReasons": ["Tools runtime returned 424: cold start timed out"],
            }
        ],
    )
    with pytest.raises(RuntimeError) as raised:
        deploy.update("example.ecr/repo@sha256:" + "a" * 64, deploy.deploy_progress())
    message = str(raised.value)
    assert "SYNCHRONIZE_UNSUCCESSFUL" in message
    assert "cold start timed out" in message
    assert "inspect its status reasons" not in message
    assert DEPLOY_AGENT in message


def test_gateway_sync_waits_through_synchronizing_until_ready(monkeypatch, capsys):
    control = Mock()
    gateway_environment(
        monkeypatch,
        control,
        [{"status": "SYNCHRONIZING"}, {"status": "READY"}],
    )
    deploy.update("example.ecr/repo@sha256:" + "a" * 64, deploy.deploy_progress())
    assert control.get_gateway_target.call_count == 2
    assert "4/5  Synchronize the Gateway tools (usually about 0:21)" in (
        capsys.readouterr().out
    )


def run_main(monkeypatch, action, failure):
    monkeypatch.setattr(sys, "argv", ["deploy_agentcore.py", action])
    monkeypatch.setattr("scripts.lab_state.lab_is_solved", lambda lab: True)
    monkeypatch.setattr(deploy, "stage", Mock(side_effect=failure))
    monkeypatch.setattr(deploy, "verify", Mock(side_effect=failure))
    return deploy.main()


def test_aws_error_prints_code_message_and_retry_command(monkeypatch, capsys):
    error = ClientError(
        {
            "Error": {
                "Code": "AccessDeniedException",
                "Message": "role is not authorized password=hunter2hunter2",
            }
        },
        "UpdateAgentRuntime",
    )
    assert run_main(monkeypatch, "deploy", error) == 1
    shown = capsys.readouterr().err
    assert "AccessDeniedException" in shown and "not authorized" in shown
    assert "UpdateAgentRuntime" in shown
    assert "hunter2hunter2" not in shown
    assert DEPLOY_AGENT in shown


def test_verify_failure_points_at_verify_not_deploy(monkeypatch, capsys):
    error = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
        "GetGateway",
    )
    assert run_main(monkeypatch, "verify", error) == 1
    shown = capsys.readouterr().err
    assert "ThrottlingException" in shown and VERIFY_AGENT in shown


def test_unrelated_os_error_is_not_called_an_image_failure(monkeypatch, capsys):
    assert run_main(monkeypatch, "verify", PermissionError("deployment.json")) == 1
    shown = capsys.readouterr().err
    assert "image" not in shown.lower()
    assert "PermissionError" in shown and "deployment.json" in shown


def image_fixture(monkeypatch, run):
    from tests.test_runtime_images import DIGEST, image_client

    ecr, missing = image_client(monkeypatch)
    ecr.describe_images.side_effect = [
        missing(),
        {"imageDetails": [{"imageDigest": DIGEST}]},
    ]
    monkeypatch.setattr(deploy.subprocess, "run", run)


def test_failed_docker_build_names_the_step_exit_code_and_command(monkeypatch):
    def run(argv, **_):
        if argv[1] == "build":
            raise subprocess.CalledProcessError(2, argv)

    image_fixture(monkeypatch, run)
    with pytest.raises(RuntimeError) as raised:
        deploy.publish_image(URI, bootstrap=False)
    message = str(raised.value)
    assert "docker build" in message and "exit code 2" in message
    assert DEPLOY_AGENT in message


def test_docker_timeout_names_the_limit(monkeypatch):
    def run(argv, **kwargs):
        if argv[1] == "push":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    image_fixture(monkeypatch, run)
    with pytest.raises(RuntimeError) as raised:
        deploy.publish_image(URI, bootstrap=False)
    assert "docker push" in str(raised.value) and "600" in str(raised.value)


def test_missing_docker_binary_says_docker_is_not_installed(monkeypatch):
    def run(argv, **_):
        raise FileNotFoundError("docker")

    image_fixture(monkeypatch, run)
    with pytest.raises(RuntimeError, match="Docker"):
        deploy.publish_image(URI, bootstrap=False)


def test_a_docker_build_leaves_its_output_to_docker_and_warns_the_first_is_slow(
    monkeypatch, capsys
):
    def run(argv, **_):
        if argv[1] == "build":
            print("#1 [internal] load build definition from Dockerfile")

    image_fixture(monkeypatch, run)
    deploy.publish_image(URI, bootstrap=False)
    output = capsys.readouterr().out
    assert "first build is the slowest" in output
    assert "load build definition" in output
    assert "elapsed" not in output


def test_stale_code_prints_both_digests_and_the_deploy_command(monkeypatch):
    monkeypatch.setattr(
        deploy.agentcore_transport,
        "deployed_status",
        lambda: {"application_sha256": "a" * 64},
    )
    monkeypatch.setattr(deploy, "application_digest", lambda: "b" * 64)
    with pytest.raises(RuntimeError) as raised:
        deploy.verify()
    message = str(raised.value)
    assert "a" * 12 in message and "b" * 12 in message
    assert DEPLOY_AGENT in message


def test_catalog_not_ready_is_a_separate_failure_for_the_facilitator(monkeypatch):
    monkeypatch.setattr(
        deploy.agentcore_transport,
        "deployed_status",
        lambda: {
            "application_sha256": "a" * 64,
            "readiness": {"database": {"catalog_ready": False}},
        },
    )
    monkeypatch.setattr(deploy, "application_digest", lambda: "a" * 64)
    with pytest.raises(RuntimeError) as raised:
        deploy.verify()
    message = str(raised.value)
    assert "catalog" in message and "facilitator" in message
    assert "stale" not in message


def _gateway_verify(monkeypatch, tmp_path, searched_sql):
    """Every verify step passes up to the search through Gateway, which ran `searched_sql`."""
    monkeypatch.setattr(
        deploy.agentcore_transport,
        "deployed_status",
        lambda: {
            "application_sha256": "a" * 64,
            "readiness": {"database": {"catalog_ready": True}},
        },
    )
    monkeypatch.setattr(deploy, "application_digest", lambda: "a" * 64)
    monkeypatch.setattr(deploy, "require_applied_sql", lambda: "c" * 64)
    monkeypatch.setattr(deploy, "participant_sql_digest", lambda: "c" * 64)
    monkeypatch.setattr(deploy, "ROOT", tmp_path)
    monkeypatch.setenv("MOSAIC_AGENTCORE_RUNTIME_ARN", "arn:runtime")
    monkeypatch.setenv("MOSAIC_AGENTCORE_GATEWAY_URL", "https://gateway.example")
    expected = [
        f"{deploy.gateway_tools.TARGET_NAME}___{name}"
        for name in deploy.gateway_tools.TOOL_NAMES
    ]
    monkeypatch.setattr(
        deploy.gateway_tools,
        "rpc",
        lambda method, params: {"tools": [{"name": name} for name in expected]},
    )
    calls = []

    def call_tool(name, arguments):
        calls.append((name, arguments))
        if name == "search_products":
            return {
                "search_event_id": "e" * 8,
                "results": [{"product_id": 1492978}],
                "diagnostics": {"search_sql_sha256": searched_sql},
            }
        return {"evidence": [{"evidence_id": 1}]}

    monkeypatch.setattr(deploy.gateway_tools, "call_tool", call_tool)
    return calls


def test_verify_proves_the_search_through_gateway_ran_the_lab_sql(
    monkeypatch, tmp_path, capsys
):
    calls = _gateway_verify(monkeypatch, tmp_path, "c" * 64)

    deploy.verify()

    search = next(arguments for name, arguments in calls if name == "search_products")
    assert search["request"]["include_diagnostics"] is True
    output = capsys.readouterr().out
    assert (
        "A search through Gateway ran your Lab 1 and Lab 2 SQL in Aurora "
        "(cccccccccccc): passed"
    ) in output


def test_verify_refuses_a_gateway_search_that_ran_other_sql(monkeypatch, tmp_path):
    _gateway_verify(monkeypatch, tmp_path, "d" * 64)

    with pytest.raises(RuntimeError) as raised:
        deploy.verify()
    message = str(raised.value)
    assert "Gateway SQL rule" in message
    assert "dddddddddddd" in message and "cccccccccccc" in message
    assert VERIFY_AGENT in message


def test_deploy_shows_each_phase_with_its_usual_time_and_what_is_left(
    monkeypatch, capsys
):
    from scripts.progress import bar, clock
    from service.participant_commands import DEPLOY_PHASE_SECONDS

    control = Mock()
    gateway_environment(monkeypatch, control, [{"status": "READY"}])
    monkeypatch.setattr(sys, "argv", ["deploy_agentcore.py", "deploy"])
    monkeypatch.setattr("scripts.lab_state.lab_is_solved", lambda lab: True)
    monkeypatch.setattr(deploy, "stage", lambda: "example.ecr/repo@sha256:" + "a" * 64)
    monkeypatch.setattr(deploy, "verify", lambda: None)

    assert deploy.main() == 0

    output = capsys.readouterr().out
    usual = DEPLOY_PHASE_SECONDS
    shown = [
        f"Deploying your Retrieval agent: 5 steps, usually about {clock(sum(usual))}"
    ]
    for index, (label, done) in enumerate(deploy.DEPLOY_PHASES):
        number = f"{index + 1}/{len(usual)}"
        shown.append(
            f"{bar(sum(usual[:index]), sum(usual))}  {number}  {label} "
            f"(usually about {clock(usual[index])})"
        )
        left = sum(usual[index + 1 :])
        shown.append(
            f"  {number}  {done}" + (f", about {clock(left)} left" if left else "")
        )
    shown.append("  Done in ")
    positions = [output.index(line) for line in shown]
    assert positions == sorted(positions)


def test_a_failed_phase_says_so_before_the_failure(monkeypatch, capsys):
    run_main(monkeypatch, "deploy", RuntimeError("Image build rule: it broke"))

    captured = capsys.readouterr()
    assert "1/5  Build and push the image: failed" in captured.out
    assert "Image build rule: it broke" in captured.err
