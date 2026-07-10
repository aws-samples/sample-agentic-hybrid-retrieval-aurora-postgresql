#!/usr/bin/env python3
import os

import aws_cdk as cdk
from stacks.agentcore_gateway_stack import AgenticRetrievalAgentCoreGatewayStack
from stacks.core_stack import AgenticRetrievalCoreStack

TARGET_REGION = os.environ.get("WORKSHOP_AWS_REGION", "us-east-1")
ENABLE_AGENTCORE_GATEWAY_STACK = os.environ.get("ENABLE_AGENTCORE_GATEWAY_STACK", "").lower() in {
    "1",
    "true",
    "yes",
}

app = cdk.App()
core_stack = AgenticRetrievalCoreStack(
    app,
    "AgenticRetrievalCoreStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=TARGET_REGION,
    ),
)
if ENABLE_AGENTCORE_GATEWAY_STACK:
    AgenticRetrievalAgentCoreGatewayStack(
        app,
        "AgenticRetrievalAgentCoreGatewayStack",
        core_stack=core_stack,
        env=cdk.Environment(
            account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
            region=TARGET_REGION,
        ),
    )
app.synth()
