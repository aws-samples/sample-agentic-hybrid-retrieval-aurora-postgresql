"""Bootstrap must report the failed dependency, including later result pages."""

from datetime import UTC, datetime
from unittest.mock import Mock

import boto3
import pytest
from botocore.stub import Stubber

from scripts import deploy_agentcore as deploy


@pytest.fixture
def discovery(monkeypatch):
    cfn = boto3.client(
        "cloudformation",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    control = Mock()
    monkeypatch.setenv("MOSAIC_EDITOR_STACK", "workshop")
    monkeypatch.setattr(
        deploy,
        "client",
        lambda service: cfn if service == "cloudformation" else control,
    )
    sleep = Mock()
    monkeypatch.setattr(deploy.time, "sleep", sleep)
    # A missing failure branch must terminate the test, never actually wait 20 minutes.
    monkeypatch.setattr(deploy.time, "monotonic", Mock(side_effect=[0, 1, 2, 1201]))
    with Stubber(cfn) as stub:
        yield stub, control, sleep
        stub.assert_no_pending_responses()


def resource(name, status="CREATE_COMPLETE", **fields):
    return {
        "LogicalResourceId": name,
        "PhysicalResourceId": name + "-example",
        "ResourceType": "AWS::BedrockAgentCore::Runtime",
        "ResourceStatus": status,
        "LastUpdatedTimestamp": datetime(2026, 9, 26, tzinfo=UTC),
        **fields,
    }


@pytest.mark.parametrize("status", ["CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED"])
def test_failed_tools_are_found_when_agent_does_not_exist(discovery, status):
    stub, control, sleep = discovery
    stub.add_response(
        "list_stack_resources",
        {
            "StackResourceSummaries": [resource("CodeEditorInstance")],
            "NextToken": "page2",
        },
        {"StackName": "workshop"},
    )
    stub.add_response(
        "list_stack_resources",
        {
            "StackResourceSummaries": [
                resource(
                    "MosaicToolsRuntime",
                    status,
                    ResourceStatusReason="subnet-example uses unsupported use1-az6",
                )
            ]
        },
        {"StackName": "workshop", "NextToken": "page2"},
    )
    with pytest.raises(
        RuntimeError, match=rf"MosaicToolsRuntime.*{status}.*use1-az6.*fix:"
    ):
        deploy.discover()
    sleep.assert_not_called()
    control.get_gateway.assert_not_called()


def test_pending_resources_retry_then_resolve_all_bindings(discovery, monkeypatch):
    stub, control, sleep = discovery
    stub.add_response(
        "list_stack_resources",
        {
            "StackResourceSummaries": [
                resource("MosaicToolsRuntime", "CREATE_IN_PROGRESS")
            ]
        },
        {"StackName": "workshop"},
    )
    rows = [
        resource(name)
        for name in (
            "MosaicToolsRuntime",
            "MosaicGateway",
            "MosaicGatewayTarget",
            "MosaicAgentRuntime",
        )
    ]
    rows[2]["PhysicalResourceId"] = "gateway|target"
    rows.append(resource("UnrelatedResource", "DELETE_COMPLETE"))
    stub.add_response(
        "list_stack_resources",
        {"StackResourceSummaries": rows},
        {"StackName": "workshop"},
    )
    control.get_gateway.return_value = {"gatewayUrl": "https://example.invalid/mcp"}
    wait = Mock(
        side_effect=lambda client, runtime_id: {"agentRuntimeArn": "arn/" + runtime_id}
    )
    monkeypatch.setattr(deploy, "wait_runtime", wait)
    values = deploy.discover()
    assert values["MOSAIC_AGENTCORE_GATEWAY_TARGET_ID"] == "target"
    assert values["MOSAIC_AGENTCORE_RUNTIME_ARN"] == "arn/MosaicAgentRuntime-example"
    assert (
        values["MOSAIC_AGENTCORE_TOOLS_RUNTIME_ARN"] == "arn/MosaicToolsRuntime-example"
    )
    assert values["MOSAIC_AGENTCORE_GATEWAY_URL"] == "https://example.invalid/mcp"
    assert wait.call_count == 2
    sleep.assert_called_once_with(5)


def test_failure_reason_is_redacted_before_truncation(discovery, monkeypatch):
    stub, _, _ = discovery
    secret = "unique-private-bootstrap-value"
    monkeypatch.setenv("ORIGIN_VERIFY_SECRET", secret)
    reason = (
        "unsupported zone; "
        + secret
        + " postgres://user:password@host/db "
        + "x" * 2000
    )
    stub.add_response(
        "list_stack_resources",
        {
            "StackResourceSummaries": [
                resource(
                    "MosaicToolsRuntime", "CREATE_FAILED", ResourceStatusReason=reason
                )
            ]
        },
        {"StackName": "workshop"},
    )
    with pytest.raises(RuntimeError) as raised:
        deploy.discover()
    message = str(raised.value)
    assert secret not in message
    assert "user:password" not in message
    assert "[REDACTED]" in message
    assert len(message) < 1200


def test_discovery_permission_errors_are_not_hidden_as_timeout(discovery):
    stub, _, sleep = discovery
    stub.add_client_error(
        "list_stack_resources",
        "AccessDenied",
        expected_params={"StackName": "workshop"},
    )
    with pytest.raises(deploy.ClientError, match="AccessDenied"):
        deploy.discover()
    sleep.assert_not_called()
