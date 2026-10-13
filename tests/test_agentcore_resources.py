"""`deploy_agentcore.py resources` shows the event's AgentCore pieces with read-only calls.

The Code Editor role may read the runtimes, Gateway and Memory it deployed by ID, but
it holds no List* discovery actions, so the command must name each resource from the
workshop's .env and call only Get* operations. A Stubber client fails on any other call.
"""

from datetime import UTC, datetime

import boto3
import pytest
from botocore.stub import Stubber

from scripts import deploy_agentcore as deploy

UPDATED = datetime(2026, 10, 12, 14, 3, tzinfo=UTC)
AGENT_ARN = (
    "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/MosaicAgent_ab12-xyz"
)
TOOLS_ARN = (
    "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/MosaicTools_ab12-xyz"
)


def runtime(name, version):
    return {
        "agentRuntimeArn": f"arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/{name}-xyz",
        "agentRuntimeName": name,
        "agentRuntimeId": f"{name}-xyz",
        "agentRuntimeVersion": version,
        "createdAt": UPDATED,
        "lastUpdatedAt": UPDATED,
        "roleArn": "arn:aws:iam::123456789012:role/agent",
        "networkConfiguration": {"networkMode": "VPC"},
        "status": "READY",
        "lifecycleConfiguration": {},
    }


def memory():
    strategy = {
        "strategyId": "preferences-1234",
        "name": "WorkspacePreferences",
        "type": "USER_PREFERENCE",
        "namespaces": ["/mosaic/{actorId}/"],
        "namespaceTemplates": ["/mosaic/{actorId}/"],
        "status": "ACTIVE",
    }
    return {
        "memory": {
            "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/MosaicMemory-1",
            "id": "MosaicMemory-1",
            "name": "MosaicMemory",
            "eventExpiryDuration": 30,
            "status": "ACTIVE",
            "createdAt": UPDATED,
            "updatedAt": UPDATED,
            "strategies": [strategy],
        }
    }


@pytest.fixture
def control(monkeypatch):
    client = boto3.client(
        "bedrock-agentcore-control",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    monkeypatch.setattr(deploy, "client", lambda service: client)
    monkeypatch.setenv("MOSAIC_AGENTCORE_RUNTIME_ARN", AGENT_ARN)
    monkeypatch.setenv("MOSAIC_AGENTCORE_TOOLS_RUNTIME_ARN", TOOLS_ARN)
    monkeypatch.setenv("MOSAIC_AGENTCORE_GATEWAY_ID", "mosaic-gw-1")
    monkeypatch.setenv("MOSAIC_AGENTCORE_GATEWAY_TARGET_ID", "TARGET1")
    monkeypatch.setenv("MOSAIC_AGENTCORE_MEMORY_ID", "MosaicMemory-1")
    with Stubber(client) as stub:
        yield stub
        stub.assert_no_pending_responses()


def stub_runtimes_and_gateway(stub):
    stub.add_response(
        "get_agent_runtime",
        runtime("MosaicAgent_ab12", "2"),
        {"agentRuntimeId": "MosaicAgent_ab12-xyz"},
    )
    stub.add_response(
        "get_agent_runtime",
        runtime("MosaicTools_ab12", "2"),
        {"agentRuntimeId": "MosaicTools_ab12-xyz"},
    )
    stub.add_response(
        "get_gateway",
        {
            "gatewayArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/mosaic-gw-1",
            "gatewayId": "mosaic-gw-1",
            "gatewayUrl": "https://example.gateway",
            "createdAt": UPDATED,
            "updatedAt": UPDATED,
            "status": "READY",
            "name": "mosaic-gateway",
            "roleArn": "arn:aws:iam::123456789012:role/gw",
            "protocolType": "MCP",
            "authorizerType": "AWS_IAM",
        },
        {"gatewayIdentifier": "mosaic-gw-1"},
    )
    stub.add_response(
        "get_gateway_target",
        {
            "gatewayArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/mosaic-gw-1",
            "targetId": "TARGET1",
            "createdAt": UPDATED,
            "updatedAt": UPDATED,
            "status": "READY",
            "name": "mosaic",
            "targetConfiguration": {
                "mcp": {"mcpServer": {"endpoint": "https://example.tools"}}
            },
            "credentialProviderConfigurations": [
                {"credentialProviderType": "GATEWAY_IAM_ROLE"}
            ],
            "lastSynchronizedAt": UPDATED,
        },
        {"gatewayIdentifier": "mosaic-gw-1", "targetId": "TARGET1"},
    )


def test_resources_names_each_piece_with_its_role_and_state(control, capsys):
    stub_runtimes_and_gateway(control)
    control.add_response("get_memory", memory(), {"memoryId": "MosaicMemory-1"})

    deploy.resources()

    out = capsys.readouterr().out
    assert (
        f"{'Retrieval agent runtime':<24} MosaicAgent_ab12   READY   version 2" in out
    )
    assert f"{'Tools runtime':<24} MosaicTools_ab12   READY   version 2" in out
    assert f"{'Gateway':<24} mosaic-gateway   READY   MCP" in out
    assert "target mosaic, READY" in out
    assert f"{'Memory':<24} MosaicMemory   ACTIVE" in out
    assert "WorkspacePreferences (USER_PREFERENCE)" in out
    assert "synthesize_cited_answer" in out
    assert "123456789012" not in out


def test_an_event_without_memory_says_it_is_optional(control, capsys, monkeypatch):
    monkeypatch.delenv("MOSAIC_AGENTCORE_MEMORY_ID")
    stub_runtimes_and_gateway(control)

    deploy.resources()

    assert f"{'Memory':<24} not configured (optional)" in capsys.readouterr().out


def test_a_missing_runtime_setting_names_the_variable(control, monkeypatch):
    monkeypatch.delenv("MOSAIC_AGENTCORE_RUNTIME_ARN")

    with pytest.raises(ValueError, match="MOSAIC_AGENTCORE_RUNTIME_ARN is unset"):
        deploy.resources()


def test_the_command_string_is_the_one_participants_type():
    from service.participant_commands import AGENTCORE_RESOURCES

    assert AGENTCORE_RESOURCES == "uv run python scripts/deploy_agentcore.py resources"
