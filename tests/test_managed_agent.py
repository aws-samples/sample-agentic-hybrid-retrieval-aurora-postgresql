"""The managed path must preserve source identity, ownership and tool scope."""

import io
import json
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from deploy.agentcore import app as adapter
from scripts import package_agentcore
from service import agentcore_transport as transport
from service import gateway_tools
from service.agent_setup import AgentSetupError
from service.models import AgentRequest
from service.session_memory import COOKIE

ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/MosaicAgent_example"
SHA = "a" * 64


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setattr("service.lab_validation_receipt.source_digest", lambda: SHA)
    monkeypatch.setattr("scripts.lab_state.lab_is_solved", lambda lab: True)


def test_runtime_invocation_binds_source_and_browser_capability(monkeypatch, source):
    monkeypatch.setenv("MOSAIC_AGENTCORE_RUNTIME_ARN", ARN)
    client = Mock()
    body = io.BytesIO(b"{}")
    client.invoke_agent_runtime.return_value = {"response": body}
    monkeypatch.setattr(transport, "runtime_client", lambda: client)
    http = Request(
        {"type": "http", "headers": [(b"cookie", f"{COOKIE}={'b' * 64}".encode())]}
    )
    transport.invoke("answer", AgentRequest(question="A monitor"), http)
    first = client.invoke_agent_runtime.call_args.kwargs
    envelope = json.loads(first["payload"])
    assert envelope["source_sha256"] == SHA
    assert envelope["shopper_token"] == "b" * 64
    assert envelope["request"]["question"] == "A monitor"
    transport.invoke("status")
    assert (
        client.invoke_agent_runtime.call_args.kwargs["runtimeSessionId"]
        != first["runtimeSessionId"]
    )


def test_unbuilt_agent_names_file_and_command_before_any_aws_call(monkeypatch, source):
    monkeypatch.setenv("MOSAIC_AGENTCORE_RUNTIME_ARN", ARN)
    monkeypatch.setattr("scripts.lab_state.lab_is_solved", lambda lab: False)
    client = Mock()
    monkeypatch.setattr(transport, "runtime_client", lambda: client)
    with pytest.raises(AgentSetupError, match="labs/lab3/agent.py.*make deploy-agent"):
        transport.invoke("answer", AgentRequest(question="A monitor"))
    client.invoke_agent_runtime.assert_not_called()


def test_runtime_rejects_stale_code_and_accepts_restored_source(source):
    with pytest.raises(HTTPException) as raised:
        transport.require_current_source("0" * 64)
    assert raised.value.status_code == 409
    assert "make deploy-agent" in raised.value.detail
    assert transport.require_current_source(SHA) == SHA


def test_adapter_forwards_only_the_opaque_browser_capability(monkeypatch, source):
    monkeypatch.delenv("MOSAIC_AGENTCORE_RUNTIME_ARN", raising=False)
    calls = []

    def answer(request, http):
        calls.append((request.question, dict(http.headers)))
        return {"answer": "A supported result"}

    monkeypatch.setattr(adapter, "agent_answer", answer)
    response = TestClient(adapter.app).post(
        "/invocations",
        json={
            "operation": "answer",
            "source_sha256": SHA,
            "shopper_token": "b" * 64,
            "request": {"question": "A monitor"},
        },
        headers={"x-untrusted-actor-id": "another-person"},
    )
    assert response.status_code == 200
    assert calls == [("A monitor", {"cookie": f"{COOKIE}={'b' * 64}"})]


def test_adapter_source_mismatch_never_runs_agent(monkeypatch, source):
    monkeypatch.delenv("MOSAIC_AGENTCORE_RUNTIME_ARN", raising=False)
    answer = Mock()
    monkeypatch.setattr(adapter, "agent_answer", answer)
    response = TestClient(adapter.app).post(
        "/invocations",
        json={
            "operation": "answer",
            "source_sha256": "0" * 64,
            "request": {"question": "A monitor"},
        },
    )
    assert response.status_code == 409
    answer.assert_not_called()


@pytest.mark.parametrize("structured", [True, False])
def test_gateway_requires_matching_code_and_actual_tool_data(
    monkeypatch, source, structured
):
    envelope = {"source_sha256": SHA, "data": {"results": [1]}}
    calls = []

    def rpc(method, params):
        calls.append((method, params))
        if structured:
            return {"structuredContent": envelope}
        return {"content": [{"type": "text", "text": json.dumps(envelope)}]}

    monkeypatch.setattr(gateway_tools, "rpc", rpc)
    assert gateway_tools.call_tool("search_products", {"request": {}}) == {
        "results": [1]
    }
    assert calls == [
        (
            "tools/call",
            {"name": "mosaic___search_products", "arguments": {"request": {}}},
        )
    ]
    envelope["source_sha256"] = "0" * 64
    with pytest.raises(AgentSetupError, match="make deploy-agent"):
        gateway_tools.call_tool("search_products", {})
    envelope["source_sha256"] = SHA
    envelope["extra_description"] = "An unrelated tool field"
    assert gateway_tools.call_tool("search_products", {}) == {"results": [1]}


def test_gateway_does_not_promote_an_mcp_error_to_tool_data(monkeypatch, source):
    monkeypatch.setattr(
        gateway_tools,
        "rpc",
        lambda *_: {
            "isError": True,
            "structuredContent": {"source_sha256": SHA, "data": {"results": [1]}},
        },
    )
    with pytest.raises(AgentSetupError, match="refused"):
        gateway_tools.call_tool("search_products", {})


def test_runtime_package_excludes_secrets_caches_and_symlinks(tmp_path):
    for name in package_agentcore.FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("source")
    (tmp_path / "service").mkdir()
    (tmp_path / "service/main.py").write_text("source")
    (tmp_path / "service/.env").write_text("private")
    (tmp_path / "service/.private").mkdir()
    (tmp_path / "service/.private/leak.py").write_text("private")
    (tmp_path / "service/linked.py").symlink_to(tmp_path / "service/.env")
    included = {
        p.relative_to(tmp_path).as_posix()
        for p in package_agentcore.application_files(tmp_path)
    }
    assert "service/main.py" in included
    assert (
        not {"service/.env", "service/.private/leak.py", "service/linked.py"} & included
    )


@pytest.mark.parametrize(
    "result",
    [
        {"structuredContent": []},
        {"structuredContent": {"source_sha256": SHA}},
        {"content": [{"type": "text", "text": "not JSON"}]},
    ],
)
def test_malformed_gateway_data_names_recovery(monkeypatch, source, result):
    monkeypatch.setattr(gateway_tools, "rpc", lambda *_: result)
    with pytest.raises(AgentSetupError, match="make verify-agent"):
        gateway_tools.call_tool("search_products", {})


def test_ready_runtime_waits_for_the_live_endpoint_version(monkeypatch):
    from scripts import deploy_agentcore as deployment

    control = Mock()
    control.get_agent_runtime.return_value = {
        "status": "READY",
        "agentRuntimeVersion": "2",
    }
    control.get_agent_runtime_endpoint.side_effect = [
        {"status": "READY", "liveVersion": "1", "targetVersion": "2"},
        {"status": "READY", "liveVersion": "2"},
    ]
    monkeypatch.setattr(deployment.time, "sleep", lambda *_: None)
    assert deployment.wait_runtime(control, "runtime-id")["agentRuntimeVersion"] == "2"
    assert control.get_agent_runtime_endpoint.call_count == 2


def test_deployment_preserves_network_without_echoing_legacy_read_field(monkeypatch):
    from scripts import deploy_agentcore as deployment

    for name in ("MOSAIC_AGENTCORE_TOOLS_RUNTIME_ARN", "MOSAIC_AGENTCORE_RUNTIME_ARN"):
        monkeypatch.setenv(name, ARN)
    monkeypatch.setenv("MOSAIC_AGENTCORE_GATEWAY_ID", "gateway-id")
    monkeypatch.setenv("MOSAIC_AGENTCORE_GATEWAY_TARGET_ID", "target-id")
    control = Mock()
    control.meta.service_model.operation_model.return_value.input_shape.members = {
        "networkConfiguration": None,
        "agentRuntimeArtifact": None,
        "roleArn": None,
    }
    control.get_agent_runtime.side_effect = lambda **_: {
        "roleArn": "runtime-role",
        "networkConfiguration": {
            "networkMode": "VPC",
            "networkModeConfig": {
                "subnets": ["private-subnet"],
                "securityGroups": ["runtime-sg"],
                "requireServiceS3Endpoint": False,
            },
        },
        "agentRuntimeArtifact": {"codeConfiguration": {"code": {}}},
    }
    control.get_gateway_target.return_value = {"status": "READY"}
    monkeypatch.setattr(deployment, "client", lambda _: control)
    monkeypatch.setattr(
        deployment, "wait_runtime", lambda *_: {"agentRuntimeVersion": "2"}
    )
    deployment.update("code-bucket", "deployment.zip")
    for call in control.update_agent_runtime.call_args_list:
        assert call.kwargs["networkConfiguration"] == {
            "networkMode": "VPC",
            "networkModeConfig": {
                "subnets": ["private-subnet"],
                "securityGroups": ["runtime-sg"],
            },
        }
        assert call.kwargs["agentRuntimeArtifact"]["codeConfiguration"]["code"] == {
            "s3": {"bucket": "code-bucket", "prefix": "deployment.zip"}
        }


def test_stream_releases_admission_if_client_disconnects_before_iteration(monkeypatch):
    import asyncio

    body = Mock()
    body.iter_chunks.return_value = iter([b"data: ready\n\n"])
    acquire, release = Mock(return_value="slot"), Mock()
    monkeypatch.setattr("service.access_control.acquire_model_admission_slot", acquire)
    monkeypatch.setattr("service.access_control.release_model_admission_slot", release)
    monkeypatch.setattr(transport, "invoke", lambda *_: body)
    response = transport.stream(AgentRequest(question="A monitor"), None)

    async def disconnected():
        return {"type": "http.disconnect"}

    async def send(_):
        raise OSError("client disconnected")

    from starlette.requests import ClientDisconnect

    with pytest.raises(ClientDisconnect):
        asyncio.run(
            response(
                {"type": "http", "asgi": {"spec_version": "2.4"}}, disconnected, send
            )
        )
    body.close.assert_called_once()
    release.assert_called_once_with("slot")


def test_stale_runtime_reply_names_redeployment(monkeypatch, source):
    from botocore.exceptions import ClientError

    monkeypatch.setenv("MOSAIC_AGENTCORE_RUNTIME_ARN", ARN)
    client = Mock()
    client.invoke_agent_runtime.side_effect = ClientError(
        {"Error": {"Code": "RuntimeClientError", "Message": "HTTP status (409)"}},
        "InvokeAgentRuntime",
    )
    monkeypatch.setattr(transport, "runtime_client", lambda: client)
    with pytest.raises(
        AgentSetupError, match="differs from your workspace.*make deploy-agent"
    ):
        transport.invoke("answer", AgentRequest(question="A monitor"))


def test_runtime_ready_waits_for_live_endpoint_version(monkeypatch):
    from scripts import deploy_agentcore as deploy

    control = Mock()
    control.get_agent_runtime.return_value = {
        "status": "READY",
        "agentRuntimeVersion": "3",
    }
    control.get_agent_runtime_endpoint.side_effect = [
        {"status": "READY", "liveVersion": "2", "targetVersion": "3"},
        {"status": "READY", "liveVersion": "3", "targetVersion": None},
    ]
    monkeypatch.setattr(deploy.time, "sleep", lambda seconds: None)
    assert deploy.wait_runtime(control, "example")["agentRuntimeVersion"] == "3"
    assert control.get_agent_runtime_endpoint.call_count == 2


def test_runtime_update_removes_response_only_network_flag(monkeypatch):
    from scripts import deploy_agentcore as deploy

    control = Mock()
    control.meta.service_model.operation_model.return_value.input_shape.members = {
        "networkConfiguration": None,
        "agentRuntimeArtifact": None,
    }
    control.get_agent_runtime.side_effect = [
        {
            "networkConfiguration": {
                "networkMode": "VPC",
                "networkModeConfig": {
                    "subnets": ["subnet-example"],
                    "securityGroups": ["sg-example"],
                    "requireServiceS3Endpoint": False,
                },
            },
            "agentRuntimeArtifact": {"codeConfiguration": {"code": {"s3": {}}}},
        }
        for _ in range(2)
    ]
    control.get_gateway_target.return_value = {"status": "READY"}
    monkeypatch.setattr(deploy, "client", lambda service: control)
    monkeypatch.setattr(
        deploy, "required", lambda name: ARN if name.endswith("_ARN") else "example"
    )
    monkeypatch.setattr(
        deploy, "wait_runtime", lambda *args: {"agentRuntimeVersion": "4"}
    )
    deploy.update("workshop-code", "deployments/source.zip")
    assert control.update_agent_runtime.call_count == 2
    for call in control.update_agent_runtime.call_args_list:
        network = call.kwargs["networkConfiguration"]["networkModeConfig"]
        assert network == {
            "subnets": ["subnet-example"],
            "securityGroups": ["sg-example"],
        }
        assert call.kwargs["agentRuntimeArtifact"]["codeConfiguration"]["code"] == {
            "s3": {"bucket": "workshop-code", "prefix": "deployments/source.zip"}
        }
