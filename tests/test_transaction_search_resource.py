"""The Transaction Search custom resource puts back at deletion only what it changed."""

import json
import types
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[1] / (
    "deploy/cloudformation/hybrid-retrieval-code-editor.yml"
)
INLINE_LIMIT = 4096
SLEEPS: list[float] = []
PROPS = {
    "PolicyName": "MosaicTransactionSearchAccess",
    "PolicyDocument": "{}",
    "IndexingPercentage": "100",
}


def inline_code() -> str:
    text = TEMPLATE.read_text()
    start = text.index("  TransactionSearchConfigurator:\n")
    block = text[start : text.index("  TransactionSearch:\n", start)]
    body = block[block.index("ZipFile: |\n") + len("ZipFile: |\n") :]
    return "\n".join(line[10:] for line in body.splitlines())


class NotFound(Exception):
    pass


class XRay:
    def __init__(self, destination="XRay", percentage=1.0, pending_reads=0):
        self.destination = destination
        self.percentage = percentage
        self.pending_reads = pending_reads
        self.calls = []

    def get_trace_segment_destination(self):
        status = "ACTIVE"
        if self.pending_reads:
            self.pending_reads -= 1
            status = "PENDING"
        return {"Destination": self.destination, "Status": status}

    def update_trace_segment_destination(self, Destination):
        self.calls.append(("destination", Destination))
        self.destination = Destination

    def get_indexing_rules(self):
        return {
            "IndexingRules": [
                {
                    "Name": "Default",
                    "Rule": {
                        "Probabilistic": {"DesiredSamplingPercentage": self.percentage}
                    },
                }
            ]
        }

    def update_indexing_rule(self, Name, Rule):
        self.calls.append(
            ("indexing", Rule["Probabilistic"]["DesiredSamplingPercentage"])
        )
        self.percentage = Rule["Probabilistic"]["DesiredSamplingPercentage"]


class Logs:
    def __init__(self, groups=(), policies=(), streams=None):
        self.groups = set(groups)
        self.policies = set(policies)
        self.streams = dict(streams or {})
        self.calls = []
        self.exceptions = type("E", (), {"ResourceNotFoundException": NotFound})

    def describe_log_streams(self, logGroupName, limit, orderBy=None, descending=False):
        if logGroupName not in self.groups:
            raise NotFound()
        # X-Ray creates an empty "default" stream with every group it makes (measured);
        # only a stream with events carries a firstEventTimestamp.
        streams = [{"logStreamName": "default"}] + [
            {"logStreamName": name, "firstEventTimestamp": 1}
            for name in self.streams.get(logGroupName, [])
        ]
        if orderBy == "LastEventTime":
            streams.sort(key=lambda s: "firstEventTimestamp" in s, reverse=descending)
        return {"logStreams": streams[:limit]}

    def describe_resource_policies(self):
        return {"resourcePolicies": [{"policyName": p} for p in self.policies]}

    def put_resource_policy(self, policyName, policyDocument):
        self.calls.append(("put policy", policyName))
        self.policies.add(policyName)

    def delete_resource_policy(self, policyName):
        self.calls.append(("delete policy", policyName))
        self.policies.discard(policyName)

    def delete_log_group(self, logGroupName):
        if logGroupName not in self.groups:
            raise NotFound()
        self.calls.append(("delete group", logGroupName))
        self.groups.discard(logGroupName)


def load(xray, logs):
    namespace = {}
    # The handler lives inline in the template, so there is no module to import.
    exec(compile(inline_code(), "transaction-search", "exec"), namespace)  # noqa: S102
    namespace["boto3"] = type(
        "Boto3",
        (),
        {"client": staticmethod(lambda name, config: xray if name == "xray" else logs)},
    )
    responses = []
    namespace["respond"] = lambda event, pid, note: responses.append((pid, note))
    namespace["time"] = types.SimpleNamespace(
        sleep=lambda seconds: SLEEPS.append(seconds)
    )
    return namespace["handler"], responses


def event(kind, physical_id=None):
    data = {
        "RequestType": kind,
        "ResourceProperties": PROPS,
        "StackId": "s",
        "RequestId": "r",
        "LogicalResourceId": "TransactionSearch",
        "ResponseURL": "https://example/response",
    }
    if physical_id is not None:
        data["PhysicalResourceId"] = physical_id
    return data


def test_inline_code_fits_cloudformations_limit():
    assert len(inline_code().encode()) <= INLINE_LIMIT


def test_create_then_delete_puts_a_fresh_account_back_as_found():
    xray, logs = XRay(), Logs()
    handler, responses = load(xray, logs)
    handler(event("Create"), None)
    pid, note = responses[-1]
    assert note == "enabled"
    assert json.loads(pid.removeprefix("transaction-search:")) == {
        "policy": False,
        "groups": [],
        "percentage": 1.0,
    }
    assert xray.calls == [("destination", "CloudWatchLogs"), ("indexing", 100.0)]
    assert logs.calls == [("put policy", "MosaicTransactionSearchAccess")]
    # X-Ray created the groups when the destination switched.
    logs.groups.update(("aws/spans", "/aws/application-signals/data"))
    handler(event("Delete", pid), None)
    assert responses[-1] == (
        pid,
        (
            "restored indexing, destination, policy, aws/spans, "
            "/aws/application-signals/data"
        ),
    )
    assert xray.destination == "XRay" and xray.percentage == 1.0
    assert logs.groups == set() and logs.policies == set()


def test_an_account_already_on_is_left_exactly_as_found():
    xray = XRay(destination="CloudWatchLogs", percentage=5.0)
    logs = Logs(groups=("aws/spans",), policies=("other",))
    handler, responses = load(xray, logs)
    handler(event("Create"), None)
    assert responses[-1] == ("transaction-search:on", "already on")
    handler(event("Delete", "transaction-search:on"), None)
    assert responses[-1] == ("transaction-search:on", "unchanged")
    assert xray.calls == [] and logs.calls == []
    assert xray.percentage == 5.0 and logs.groups == {"aws/spans"}


def test_what_existed_before_the_stack_stays_and_only_the_rest_is_removed():
    xray = XRay(percentage=2.5)
    logs = Logs(groups=("aws/spans",), policies=("MosaicTransactionSearchAccess",))
    handler, responses = load(xray, logs)
    handler(event("Create"), None)
    pid, _ = responses[-1]
    assert logs.calls == []  # the existing policy is kept, not overwritten
    logs.groups.add("/aws/application-signals/data")
    handler(event("Delete", pid), None)
    assert responses[-1][1] == (
        "restored indexing, destination, /aws/application-signals/data"
    )
    assert logs.groups == {"aws/spans"}
    assert logs.policies == {"MosaicTransactionSearchAccess"}


def test_a_percentage_someone_else_changed_is_not_touched():
    xray, logs = XRay(), Logs()
    handler, responses = load(xray, logs)
    handler(event("Create"), None)
    pid, _ = responses[-1]
    xray.percentage = 50.0
    handler(event("Delete", pid), None)
    assert responses[-1][1].startswith("restored destination")
    assert xray.percentage == 50.0


def test_a_stack_created_before_this_change_and_updates_change_nothing():
    xray = XRay(destination="CloudWatchLogs")
    handler, responses = load(xray, Logs())
    handler(event("Delete", "transaction-search"), None)
    assert responses[-1] == ("transaction-search", "unchanged")
    handler(event("Update", 'transaction-search:{"policy":false}'), None)
    assert responses[-1] == ('transaction-search:{"policy":false}', "unchanged")
    assert xray.calls == []


def test_a_failure_is_reported_and_never_fails_the_stack():
    class Broken(XRay):
        def get_trace_segment_destination(self):
            raise RuntimeError("xray down")

    handler, responses = load(Broken(), Logs())
    handler(event("Create"), None)
    assert responses[-1] == (
        "transaction-search:on",
        "Create: RuntimeError('xray down')",
    )
    handler(
        event(
            "Delete", 'transaction-search:{"policy":false,"groups":[],"percentage":1.0}'
        ),
        None,
    )
    assert responses[-1][1] == "Delete: RuntimeError('xray down')"


@pytest.mark.parametrize(
    "name",
    ["logs:DeleteLogGroup", "logs:DeleteResourcePolicy", "logs:DescribeLogStreams"],
)
def test_the_role_grants_what_restore_calls(name):
    text = TEMPLATE.read_text()
    role = text[
        text.index("  TransactionSearchConfiguratorRole:") : text.index(
            "  TransactionSearchConfigurator:\n"
        )
    ]
    assert name in role


def test_delete_waits_for_x_ray_to_leave_pending_before_switching_back():
    """A delete minutes after the enable (a rollback) meets a PENDING destination."""
    xray, logs = XRay(), Logs()
    handler, responses = load(xray, logs)
    handler(event("Create"), None)
    pid, _ = responses[-1]
    xray.pending_reads = 3
    SLEEPS.clear()
    handler(event("Delete", pid), None)
    assert SLEEPS == [10, 10, 10]
    assert xray.destination == "XRay"
    assert responses[-1][1].startswith("restored indexing, destination")


def test_the_lambda_has_time_to_wait_out_pending():
    text = TEMPLATE.read_text()
    configurator = text[
        text.index("  TransactionSearchConfigurator:\n") : text.index(
            "  TransactionSearch:\n"
        )
    ]
    assert "Timeout: 900" in configurator


def test_create_waits_for_the_switch_to_settle_before_indexing_everything():
    """UpdateIndexingRule during PENDING returns success and changes nothing (measured)."""
    xray, logs = XRay(), Logs()
    handler, responses = load(xray, logs)

    def switch(Destination):
        xray.calls.append(("destination", Destination))
        xray.destination = Destination
        xray.pending_reads = 2

    xray.update_trace_segment_destination = switch
    SLEEPS.clear()
    handler(event("Create"), None)
    assert responses[-1][1] == "enabled"
    assert SLEEPS == [10, 10]
    assert xray.calls == [("destination", "CloudWatchLogs"), ("indexing", 100.0)]


def test_a_created_group_that_holds_traces_is_kept_and_named():
    """Other applications' spans land in the shared groups once the setting is on."""
    xray, logs = XRay(), Logs()
    handler, responses = load(xray, logs)
    handler(event("Create"), None)
    pid, _ = responses[-1]
    logs.groups.update(("aws/spans", "/aws/application-signals/data"))
    logs.streams["aws/spans"] = ["another-application's-span-stream"]
    handler(event("Delete", pid), None)
    assert responses[-1][1] == (
        "restored indexing, destination, policy, kept aws/spans, "
        "/aws/application-signals/data"
    )
    assert logs.groups == {"aws/spans"}
