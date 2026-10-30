"""Launch the workshop's Code Editor host on the first zone and instance type with capacity.

A CloudFormation custom resource (``Custom::EditorInstance``) that calls RunInstances with the
stack's launch template when CloudFormation creates the host, so the choice is made at launch
time. Each instance type, in priority order, is tried in every private subnet before the next
type, and the subnet order is rotated per stack so event accounts spread across zones. A shortage,
or a type a zone does not offer, moves to the next option; when every option is short, the
launcher pauses and tries them all again while Lambda has time. Any other refusal fails the stack
with its error code, so nothing launches unprotected and nothing fails silently.

The result is a plain EC2 instance, so EC2's automatic recovery stays on, and the host is replaced
only when a stack update changes its launch inputs. Every instance is tagged with the request that
launched it, so a request that fails, or runs out of time, terminates what it launched. This file
is the canonical copy for every workshop that uses it; keep the copies byte-identical.
"""

import hashlib
import json
import threading
import time
import urllib.request

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, WaiterError

REQUEST_TAG = "eval-skills:launch-request"
INPUTS_TAG = "eval-skills:launch-inputs"
FAILED_PREFIX = "editor-launch-failed-"
SKIP_CODES = frozenset({"InsufficientInstanceCapacity", "Unsupported"})
ENDED_FOR_CAPACITY = "Server.InsufficientInstanceCapacity"
LAUNCH_INPUTS = ("LaunchTemplateId", "LaunchTemplateVersion", "InstanceTypes", "Subnets")
ROUND_PAUSE_SECONDS = 30
# No new attempt starts with less than this left: room for the running wait and the answer.
RESERVE_MS = 240_000
# Kept back from every wait for cleanup and the answer to CloudFormation.
CLEANUP_SECONDS = 60
# The watchdog answers FAILED this long before Lambda stops the function.
WATCHDOG_SECONDS = 20
POLL_SECONDS = 5
MAX_RUNNING_ATTEMPTS = 36
REASON_LIMIT = 1000
LIVE_STATES = ["pending", "running", "stopping", "stopped"]
CLIENT_CONFIG = Config(connect_timeout=5, read_timeout=20,
                       retries={"mode": "standard", "max_attempts": 4})


class LaunchError(Exception):
    """A launch or termination the stack must not continue past."""


def options(props, stack_id):
    """Return the (instance type, subnet) pairs in the order the launcher tries them.

    Args:
        props: The custom resource's properties, with ``InstanceTypes`` and ``Subnets``.
        stack_id: The stack's ID, which picks the first subnet so accounts spread across zones.

    Raises:
        LaunchError: When either list is empty.
    """
    types = list(dict.fromkeys(props["InstanceTypes"]))
    subnets = list(props["Subnets"])
    if not types or not subnets:
        raise LaunchError("InstanceTypes and Subnets must each name at least one value")
    start = int(hashlib.sha256(stack_id.encode()).hexdigest(), 16) % len(subnets)
    rotated = subnets[start:] + subnets[:start]
    return [(itype, subnet) for itype in types for subnet in rotated]


def inputs_digest(props):
    """A short digest of the launch inputs, tagged on the instance they launched."""
    inputs = json.dumps([props.get(key) for key in LAUNCH_INPUTS], sort_keys=True)
    return hashlib.sha256(inputs.encode()).hexdigest()[:32]


def launch(ec2, props, request_id, stack_id, context, sleep):
    """Launch one instance on the first option with capacity and wait until it runs.

    Args:
        ec2: An EC2 client.
        props: The custom resource's properties.
        request_id: CloudFormation's request ID, tagged on the instance and part of each token.
        stack_id: The stack's ID.
        context: Lambda's context; its remaining time bounds the retries and waits.
        sleep: Pauses between rounds, in seconds.

    Returns:
        The instance's identity: InstanceId, PrivateDnsName, PrivateIpAddress, InstanceType,
        SubnetId and AvailabilityZoneId.

    Raises:
        LaunchError: On any refusal other than a shortage, or when time runs out first.
    """
    order = options(props, stack_id)
    tags = [{"Key": REQUEST_TAG, "Value": request_id},
            {"Key": INPUTS_TAG, "Value": inputs_digest(props)}]
    shortages = {}
    round_number = 0
    while True:
        for itype, subnet in order:
            if context.get_remaining_time_in_millis() < RESERVE_MS:
                raise LaunchError(no_capacity(shortages, round_number))
            token = client_token(request_id, round_number, itype, subnet)
            instance, shortage = attempt(ec2, props, (itype, subnet), tags, token, context)
            if instance:
                return identity(ec2, instance)
            shortages[(itype, subnet)] = shortage
        if context.get_remaining_time_in_millis() - ROUND_PAUSE_SECONDS * 1000 < RESERVE_MS:
            raise LaunchError(no_capacity(shortages, round_number))
        sleep(ROUND_PAUSE_SECONDS)
        round_number += 1


def client_token(request_id, round_number, itype, subnet):
    """One idempotency token per attempt: never reused across options or rounds."""
    return hashlib.sha256(f"{request_id}/{round_number}/{itype}/{subnet}".encode()).hexdigest()


def attempt(ec2, props, option, tags, token, context):
    """Try one option. Return ``(instance, None)``, or ``(None, code)`` on a shortage."""
    itype, subnet = option
    try:
        reply = ec2.run_instances(
            LaunchTemplate={"LaunchTemplateId": props["LaunchTemplateId"],
                            "Version": str(props["LaunchTemplateVersion"])},
            InstanceType=itype,
            NetworkInterfaces=[{"DeviceIndex": 0, "SubnetId": subnet}],
            TagSpecifications=[{"ResourceType": "instance", "Tags": tags}],
            ClientToken=token, MinCount=1, MaxCount=1)
    except ClientError as error:
        code = error_code(error)
        print(f"{itype} in {subnet}: {code}")
        if code in SKIP_CODES:
            return None, code
        raise LaunchError(f"RunInstances refused {itype} in {subnet}: {code}: "
                          f"{error.response['Error'].get('Message', '')}") from error
    instance_id = reply["Instances"][0]["InstanceId"]
    try:
        ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id],
                                                WaiterConfig=running_wait(context))
    except WaiterError as error:
        return None, ended(ec2, instance_id, error)
    print(f"{itype} in {subnet}: launched {instance_id}")
    return described(ec2, instance_id), None


def running_wait(context):
    """Poll for running no longer than Lambda's time allows, keeping the cleanup reserve."""
    budget = context.get_remaining_time_in_millis() / 1000 - CLEANUP_SECONDS
    attempts = max(1, min(MAX_RUNNING_ATTEMPTS, int(budget // POLL_SECONDS)))
    return {"Delay": POLL_SECONDS, "MaxAttempts": attempts}


def ended(ec2, instance_id, error):
    """Explain an instance that never ran: a shortage moves on, anything else fails."""
    reason = described(ec2, instance_id).get("StateReason", {}).get("Code", "")
    if reason == ENDED_FOR_CAPACITY:
        print(f"{instance_id} ended: {reason}")
        return reason
    terminate(ec2, [instance_id])
    raise LaunchError(f"{instance_id} never reached running ({reason or error}); terminated it")


def described(ec2, instance_id):
    """Return one instance's description, or fail naming it."""
    try:
        reservations = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"]
    except ClientError as error:
        raise LaunchError(f"{instance_id}: {error_code(error)}") from error
    return reservations[0]["Instances"][0]


def identity(ec2, instance):
    """The fields the stack reads, with the subnet's physical zone."""
    subnet = instance["SubnetId"]
    zone = ec2.describe_subnets(SubnetIds=[subnet])["Subnets"][0]["AvailabilityZoneId"]
    return {"InstanceId": instance["InstanceId"], "PrivateDnsName": instance["PrivateDnsName"],
            "PrivateIpAddress": instance["PrivateIpAddress"],
            "InstanceType": instance["InstanceType"], "SubnetId": subnet,
            "AvailabilityZoneId": zone}


def no_capacity(shortages, round_number):
    tried = ", ".join(f"{itype} in {subnet} ({code})"
                      for (itype, subnet), code in shortages.items())
    return (f"No capacity after {round_number + 1} round(s) before Lambda's time ran low; "
            f"tried {tried or 'nothing'}")


def update(ec2, event, context, sleep):
    """Keep the instance when it was launched from these inputs; otherwise launch a replacement.

    The instance's own inputs tag decides, not the old properties, so a rollback to the inputs
    the host was launched with keeps it. CloudFormation deletes the old instance after a
    replacement answers with a new ID.
    """
    physical = event["PhysicalResourceId"]
    props = event["ResourceProperties"]
    if physical.startswith("i-"):
        instance = described(ec2, physical)
        tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
        if tags.get(INPUTS_TAG) == inputs_digest(props):
            if instance["State"]["Name"] in ("shutting-down", "terminated"):
                raise LaunchError(f"{physical} is {instance['State']['Name']}; "
                                  "change the launch inputs to replace the host")
            return physical, identity(ec2, instance)
    data = launch(ec2, props, event["RequestId"], event["StackId"], context, sleep)
    return data["InstanceId"], data


def delete(ec2, physical, context, sleep):
    """Terminate the instance, or whatever a failed create launched, and wait for it to end."""
    if physical.startswith("i-"):
        targets = [physical]
    elif physical.startswith(FAILED_PREFIX):
        targets = launched_by(ec2, physical[len(FAILED_PREFIX):])
    else:
        return
    if terminate(ec2, targets):
        wait_terminated(ec2, targets, context, sleep)


def launched_by(ec2, request_id):
    filters = [{"Name": f"tag:{REQUEST_TAG}", "Values": [request_id]},
               {"Name": "instance-state-name", "Values": LIVE_STATES}]
    reservations = ec2.describe_instances(Filters=filters)["Reservations"]
    return [i["InstanceId"] for r in reservations for i in r["Instances"]]


def terminate(ec2, instance_ids):
    """Ask EC2 to terminate; return whether there was anything to wait for."""
    if not instance_ids:
        return False
    try:
        ec2.terminate_instances(InstanceIds=instance_ids)
    except ClientError as error:
        if error_code(error) == "InvalidInstanceID.NotFound":
            return False
        raise LaunchError(f"TerminateInstances refused {instance_ids}: "
                          f"{error_code(error)}") from error
    return True


def wait_terminated(ec2, instance_ids, context, sleep):
    """Poll until every instance is terminated, so its network interface frees the subnet.

    Any state seen before ``terminated`` (a stale ``pending`` included) is polled again until
    the cleanup reserve; termination already requested continues after the answer if time runs
    short.
    """
    pending = list(instance_ids)
    while pending:
        try:
            reservations = ec2.describe_instances(InstanceIds=pending)["Reservations"]
        except ClientError as error:
            if error_code(error) == "InvalidInstanceID.NotFound":
                return
            raise
        states = {i["InstanceId"]: i["State"]["Name"] for r in reservations for i in r["Instances"]}
        pending = [i for i in pending if states.get(i, "terminated") != "terminated"]
        if not pending:
            return
        if context.get_remaining_time_in_millis() / 1000 - POLL_SECONDS < CLEANUP_SECONDS:
            print(f"Still terminating {pending}; answering before Lambda's time runs out")
            return
        sleep(POLL_SECONDS)


def clean_up(ec2, request_id):
    """Best effort: terminate whatever this request launched, after a failure or a late answer."""
    try:
        terminate(ec2, launched_by(ec2, request_id))
    except Exception as error:  # noqa: BLE001 - the answer to CloudFormation must still go out.
        print(f"Could not terminate what request {request_id} launched: {error}")


def error_code(error):
    return error.response.get("Error", {}).get("Code", "Unknown")


def dispatch(ec2, event, context, sleep):
    """Run one request and return the physical ID and data to answer with."""
    kind = event["RequestType"]
    if kind == "Create":
        data = launch(ec2, event["ResourceProperties"], event["RequestId"], event["StackId"],
                      context, sleep)
        return data["InstanceId"], data
    if kind == "Update":
        return update(ec2, event, context, sleep)
    delete(ec2, event["PhysicalResourceId"], context, sleep)
    return event["PhysicalResourceId"], {}


class Answer:
    """Answers CloudFormation exactly once; a second answer learns it came too late."""

    def __init__(self, event, opener):
        self.event, self.opener = event, opener
        self.lock = threading.Lock()
        self.sent = False

    def send(self, status, physical, data, reason):
        with self.lock:
            if self.sent:
                return False
            self.sent = True
        body = {"Status": status, "Reason": reason[:REASON_LIMIT], "PhysicalResourceId": physical,
                "StackId": self.event["StackId"], "RequestId": self.event["RequestId"],
                "LogicalResourceId": self.event["LogicalResourceId"], "Data": data}
        request = urllib.request.Request(self.event["ResponseURL"], method="PUT",
                                         data=json.dumps(body).encode(),
                                         headers={"Content-Type": ""})
        self.opener(request, timeout=30)
        return True


def respond(event, context, *, ec2=None, sleep=time.sleep, opener=urllib.request.urlopen,
            timer=threading.Timer):
    """Handle one custom-resource request and always answer CloudFormation, once, in time.

    A failed Create answers with ``FAILED_PREFIX`` plus its request ID, so the Delete that
    follows can terminate anything that request launched. A watchdog answers FAILED before
    Lambda stops the function; whatever the request launched after that is terminated.
    """
    reply = Answer(event, opener)
    request_id = event["RequestId"]
    physical = event.get("PhysicalResourceId") or FAILED_PREFIX + request_id
    ec2 = ec2 or boto3.client("ec2", config=CLIENT_CONFIG)
    launching = event["RequestType"] in ("Create", "Update")

    def out_of_time():
        reason = "The editor launcher ran out of time before the host was ready"
        if reply.send("FAILED", physical, {}, reason) and launching:
            clean_up(ec2, request_id)

    seconds = context.get_remaining_time_in_millis() / 1000 - WATCHDOG_SECONDS
    watchdog = timer(max(seconds, 1), out_of_time)
    watchdog.daemon = True
    watchdog.start()
    try:
        result, data = dispatch(ec2, event, context, sleep)
    except Exception as error:  # noqa: BLE001 - CloudFormation must hear every failure.
        reason = f"{type(error).__name__}: {error}"
        print(f"{event['RequestType']} failed: {reason}")
        if launching:
            clean_up(ec2, request_id)
        reply.send("FAILED", physical, {}, reason)
        return
    finally:
        watchdog.cancel()
    if not reply.send("SUCCESS", result, data, "") and launching:
        clean_up(ec2, request_id)


def handler(event, context):
    """Lambda entry point."""
    respond(event, context)
