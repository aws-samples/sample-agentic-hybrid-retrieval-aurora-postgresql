#!/usr/bin/env python3
import os

import aws_cdk as cdk
from stacks.core_stack import AgenticRetrievalCoreStack

TARGET_REGION = os.environ.get("WORKSHOP_AWS_REGION", "us-east-1")

app = cdk.App()
AgenticRetrievalCoreStack(
    app,
    "AgenticRetrievalCoreStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=TARGET_REGION,
    ),
)
app.synth()
