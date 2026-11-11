"""Deployment must narrate long waits and name the cause and next command on failure."""

import io
import subprocess
import sys
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from scripts import deploy_agentcore as deploy
from scripts import progress as progress_module
from service.participant_commands import DEPLOY_AGENT, VERIFY_AGENT

URI = "123456789012.dkr.ecr.us-east-1.amazonaws.com/workshop"


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(deploy.time, "sleep", lambda *_: None)


@pytest.fixture(autouse=True)
def _a_laptop_terminal(monkeypatch):
    """Code Editor's terminal on a laptop, where each step's line fits on one line."""
    monkeypatch.setattr(progress_module, "columns", lambda: 97)


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
        deploy.update(
            "example.ecr/repo@sha256:" + "a" * 64, deploy.deploy_progress(), "c" * 64
        )
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
    deploy.update(
        "example.ecr/repo@sha256:" + "a" * 64, deploy.deploy_progress(), "c" * 64
    )
    assert control.get_gateway_target.call_count == 2
    assert "4/5  Synchronize the Gateway tools (usually about 0:21)" in (
        capsys.readouterr().out
    )


def run_main(monkeypatch, action, failure):
    monkeypatch.setattr(sys, "argv", ["deploy_agentcore.py", action])
    monkeypatch.setattr("scripts.lab_state.lab_source_is_repaired", lambda lab: True)
    monkeypatch.setattr(
        deploy, "publish_image_storing_dsn_at_bootstrap", Mock(side_effect=failure)
    )
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
    from scripts.progress import bar, bounds, span, total, usually
    from service.participant_commands import DEPLOY_PHASE_SECONDS

    control = Mock()
    gateway_environment(monkeypatch, control, [{"status": "READY"}])
    monkeypatch.setattr(sys, "argv", ["deploy_agentcore.py", "deploy"])
    monkeypatch.setattr("scripts.lab_state.lab_source_is_repaired", lambda lab: True)
    monkeypatch.setattr(
        deploy,
        "publish_image_storing_dsn_at_bootstrap",
        lambda: "example.ecr/repo@sha256:" + "a" * 64,
    )
    monkeypatch.setattr(deploy, "verify", lambda: None)

    assert deploy.main() == 0

    output = capsys.readouterr().out
    usual = DEPLOY_PHASE_SECONDS
    longest = [bounds(step)[1] for step in usual]
    shown = [
        f"Deploying your Retrieval agent: 5 steps, usually {span(*total(usual))} in all."
    ]
    for index, (label, done) in enumerate(deploy.DEPLOY_PHASES):
        number = f"{index + 1}/{len(usual)}"
        shown.append(
            f"{bar(sum(longest[:index]), sum(longest))}  {number}  {label} "
            f"({usually(usual[index])})"
        )
        low, high = total(usual[index + 1 :])
        shown.append(
            f"  {number}  {done}" + (f", {span(low, high)} left" if high else "")
        )
    shown.append("  Done in ")
    positions = [output.index(line) for line in shown]
    assert positions == sorted(positions)
    # Verification is the one step whose measured time varies, so it and the totals that
    # include it show the shortest and longest; the steps that never varied keep one figure.
    assert "5 steps, usually 1:11 to 1:25 in all." in output
    assert "2/5  Update the tools runtime (usually about 0:16)" in output
    assert "5/5  Verify the deployment (usually 0:13 to 0:27)" in output
    assert "3/5  Updated the Retrieval agent runtime, 0:34 to 0:48 left" in output


def test_a_failed_phase_says_so_before_the_failure(monkeypatch, capsys):
    run_main(monkeypatch, "deploy", RuntimeError("Image build rule: it broke"))

    captured = capsys.readouterr()
    assert "1/5  Build and push the image: failed" in captured.out
    assert "Image build rule: it broke" in captured.err


def test_deploy_records_the_retrieval_agent_version_it_made_ready(monkeypatch):
    """Questions and completion read this record; the tools runtime alone is not a deploy."""
    from service.agent_deploys import deploys_path, load_deploys, record_deploy

    control = Mock()
    gateway_environment(monkeypatch, control, [{"status": "READY"}])
    deploy.update(
        "example.ecr/repo@sha256:" + "a" * 64, deploy.deploy_progress(), "c" * 64
    )

    (recorded,) = load_deploys()
    assert (recorded.runtime_version, recorded.application_sha256) == ("2", "c" * 64)

    deploys_path().write_text("{not json")
    record_deploy("3", "d" * 64)
    assert [item.runtime_version for item in load_deploys()] == ["3"]


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"AWS_REGION": "us-west-2", "AWS_DEFAULT_REGION": "eu-west-1"}, "us-west-2"),
        ({"AWS_DEFAULT_REGION": "us-west-2"}, "us-west-2"),
        ({}, "us-east-1"),
    ],
)
def test_the_clients_use_the_terminals_region_before_the_default(
    monkeypatch, env, expected
):
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    made = []
    monkeypatch.setattr(deploy.boto3, "client", lambda *a, **k: made.append(k))

    deploy.client("bedrock-agentcore-control")

    assert made[0]["region_name"] == expected


def test_the_tool_list_wraps_long_descriptions_at_word_boundaries():
    """Code Editor's terminal wrapped a long description mid-word ("semantic sea|rch")."""
    description = (
        "Search Aurora with shared filters, full-text search, pg_trgm fuzzy matching, "
        "pgvector semantic search and reranking."
    )
    tools = [
        {"name": "mosaic___search_products", "description": description},
        {"name": "mosaic___explain_retrieval", "description": "Read a saved search."},
    ]

    lines = deploy.tool_lines(tools)

    assert all(len(line) <= deploy.LINE_CHARS for line in lines)
    assert lines[0].startswith("mosaic___search_products: Search Aurora")
    assert lines[1].startswith("    ") and not lines[1][4].isspace()
    assert " ".join(line.strip() for line in lines[:2]) == (
        f"mosaic___search_products: {description}"
    )
    assert lines[2] == "mosaic___explain_retrieval: Read a saved search."


# ---------------------------------------------------------------- layout, Next and colour


class Terminal(io.StringIO):
    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


@pytest.fixture
def colour_capable(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("MOSAIC_RUN_BY", raising=False)


def _deploy_with_passing_checks(monkeypatch, stream):
    """`deploy` end to end with the image, AWS and the verification substituted."""
    control = Mock()
    gateway_environment(monkeypatch, control, [{"status": "READY"}])
    monkeypatch.setattr(sys, "argv", ["deploy_agentcore.py", "deploy"])
    monkeypatch.setattr("scripts.lab_state.lab_source_is_repaired", lambda lab: True)
    monkeypatch.setattr(
        deploy,
        "publish_image_storing_dsn_at_bootstrap",
        lambda: "example.ecr/repo@sha256:" + "a" * 64,
    )

    def verified():
        print(
            "A search through Gateway ran your Lab 1 and Lab 2 SQL in Aurora "
            "(cccccccccccc): passed"
        )
        print(
            "Runtime code, Gateway discovery, Aurora search and scoped evidence: passed"
        )

    monkeypatch.setattr(deploy, "verify", verified)
    monkeypatch.setattr(sys, "stdout", stream)
    assert deploy.main() == 0
    return stream.getvalue()


def test_deploy_puts_a_blank_line_before_its_closing_summary_and_next(monkeypatch):
    from service.participant_commands import ask_setup_command

    output = _deploy_with_passing_checks(monkeypatch, io.StringIO())

    parts = output.rstrip("\n").split("\n\n")
    assert not output.startswith("\n") and "\n\n\n" not in output
    assert parts[-2] == (
        "Your Retrieval agent is deployed and its SQL tools are connected through Gateway."
    )
    assert parts[-1] == f"Next: ask Alex's setup request:\n{ask_setup_command()}"
    assert parts[-3].splitlines()[-1].startswith("  Done in ")


def test_deploy_colours_its_ready_lines_checks_and_summary_on_a_terminal(
    colour_capable, monkeypatch
):
    from scripts.terminal_text import GREEN

    painted = _deploy_with_passing_checks(monkeypatch, Terminal())

    assert f"\033[{GREEN}mReady:\033[0m tools runtime version 2" in painted
    assert f"\033[{GREEN}mReady:\033[0m Retrieval agent runtime version 2" in painted
    assert (
        f"\033[{GREEN}mYour Retrieval agent is deployed and its SQL tools are "
        "connected through Gateway.\033[0m"
    ) in painted


def test_deploy_prints_no_colour_when_piped(colour_capable, monkeypatch):
    plain = _deploy_with_passing_checks(monkeypatch, io.StringIO())

    assert "\033" not in plain
    assert "Ready: tools runtime version 2" in plain


def test_verify_colours_each_passed_on_a_terminal_only(
    colour_capable, monkeypatch, tmp_path
):
    from scripts.terminal_text import GREEN

    _gateway_verify(monkeypatch, tmp_path, "c" * 64)
    outputs = {}
    for name, stream in (("tty", Terminal()), ("pipe", io.StringIO())):
        monkeypatch.setattr(sys, "stdout", stream)
        deploy.verify()
        outputs[name] = stream.getvalue()

    assert outputs["tty"].count(f"\033[{GREEN}mpassed\033[0m") == 2
    assert "\033" not in outputs["pipe"]
    assert outputs["pipe"].count(": passed") == 2


def test_verify_alone_ends_with_asking_the_setup_request(monkeypatch, capsys):
    from service.participant_commands import ask_setup_command

    monkeypatch.setattr(sys, "argv", ["deploy_agentcore.py", "verify"])
    monkeypatch.setattr(deploy, "verify", lambda: print("Runtime code: passed"))

    assert deploy.main() == 0

    assert capsys.readouterr().out == (
        f"Runtime code: passed\n\nNext: ask Alex's setup request:\n{ask_setup_command()}\n"
    )


def test_verify_after_lab_3_is_complete_points_on_to_the_guide(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["deploy_agentcore.py", "verify"])
    monkeypatch.setattr(deploy, "verify", lambda: print("Runtime code: passed"))
    monkeypatch.setattr(deploy, "lab_3_solved", lambda: True)

    assert deploy.main() == 0

    assert capsys.readouterr().out == (
        "Runtime code: passed\n\nNext: the guide's next step. Lab 3 is complete.\n"
    )


def test_tools_ends_with_connecting_them_in_the_editor(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["deploy_agentcore.py", "tools"])
    monkeypatch.setattr(
        deploy.gateway_tools,
        "rpc",
        lambda *_: {
            "tools": [{"name": "mosaic___search_products", "description": "x"}]
        },
    )

    assert deploy.main() == 0

    out = capsys.readouterr().out
    assert out.startswith("mosaic___search_products: x")
    assert out.endswith(
        "\n\nNext: open labs/lab3_reason/agent.py and connect these SQL tools to your "
        "Retrieval agent.\n"
    )


def test_resources_puts_a_blank_line_before_its_next(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["deploy_agentcore.py", "resources"])
    monkeypatch.setattr(deploy, "client", lambda _service: Mock())
    for name in ("_runtime_lines", "_gateway_lines", "_memory_lines"):
        monkeypatch.setattr(deploy, name, lambda _control: ["  a line"])

    assert deploy.main() == 0

    out = capsys.readouterr().out
    assert "  a line\n\nNext: when your deploy finishes, run this again" in out


def test_a_failed_action_ends_with_a_next_that_names_the_retry(monkeypatch, capsys):
    run_main(monkeypatch, "verify", RuntimeError("Gateway sync rule: it broke"))

    err = capsys.readouterr().err
    assert err.endswith(
        f"\n\nNext: fix what the message above names, then run this again:\n{VERIFY_AGENT}\n"
    )
