#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.core_stack import AgenticRetrievalCoreStack

app = cdk.App()
AgenticRetrievalCoreStack(app, "AgenticRetrievalCoreStack")
app.synth()
