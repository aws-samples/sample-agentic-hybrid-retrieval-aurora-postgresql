#!/usr/bin/env python3
"""
Release-author example for adding the packaged OpenAPI schema to a pre-created
Amazon Bedrock AgentCore Gateway.

This is intentionally not part of the participant path.

Before use:
1. upload contracts/openapi/verity-tools.openapi.yaml to S3;
2. replace placeholders below;
3. choose and configure the correct outbound credential provider;
4. recheck the current AgentCore Gateway API and Region support.

This call configures outbound auth only. Inbound auth is set on CreateGateway via
authorizerType (NONE | CUSTOM_JWT | AWS_IAM | AUTHENTICATE_ONLY); authorizerConfiguration
is required only for CUSTOM_JWT. NONE or AWS_IAM is sufficient for the workshop.
https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_CreateGateway.html
"""
from __future__ import annotations

import os
import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
GATEWAY_ID = os.environ["AGENTCORE_GATEWAY_ID"]
SCHEMA_S3_URI = os.environ["VERITY_OPENAPI_S3_URI"]
BUCKET_OWNER_ACCOUNT_ID = os.environ["VERITY_OPENAPI_BUCKET_OWNER"]
API_KEY_PROVIDER_ARN = os.environ["VERITY_API_KEY_PROVIDER_ARN"]

client = boto3.client("bedrock-agentcore-control", region_name=REGION)

response = client.create_gateway_target(
    gatewayIdentifier=GATEWAY_ID,
    name="verity-openapi-tools",
    description="Hybrid Retrieval Workbench tool contracts exposed through a managed MCP endpoint",
    targetConfiguration={
        "mcp": {
            "openApiSchema": {
                # Two mutually exclusive schema sources are accepted:
                #   "s3"            -> object reference, used here
                #   "inlinePayload" -> the schema document as a string, e.g.
                #                      "inlinePayload": Path(SCHEMA).read_text()
                # Prefer S3 for the packaged contract so the deployed schema is
                # versioned and auditable rather than embedded in a call.
                "s3": {
                    "uri": SCHEMA_S3_URI,
                    # bucketOwnerAccountId is for cross-account S3 reads.
                    "bucketOwnerAccountId": BUCKET_OWNER_ACCOUNT_ID,
                }
            }
        }
    },
    credentialProviderConfigurations=[
        {
            # Outbound auth: how Gateway calls the Hybrid Retrieval Workbench HTTP API.
            # credentialProviderType also accepts GATEWAY_IAM_ROLE, OAUTH,
            # CALLER_IAM_CREDENTIALS, JWT_PASSTHROUGH.
            "credentialProviderType": "API_KEY",
            # Note the nesting: the provider block sits under "credentialProvider",
            # not directly on the list item.
            "credentialProvider": {
                "apiKeyCredentialProvider": {
                    "providerArn": API_KEY_PROVIDER_ARN,
                    # "HEADER" or "QUERY_PARAMETER".
                    "credentialLocation": "HEADER",
                    "credentialParameterName": "X-API-Key",
                    # Optional. Prepended to the key value, e.g. "Bearer" for
                    # an Authorization header. Omit for a bare API key.
                    # "credentialPrefix": "Bearer",
                }
            },
        }
    ],
)

# Resulting MCP tool names are prefixed with the target name, delimiter "___":
#   verity-openapi-tools___decompose_question
#   verity-openapi-tools___search_evidence
#   verity-openapi-tools___follow_evidence_links
#   verity-openapi-tools___compare_sources
#   verity-openapi-tools___explain_ranking
#   verity-openapi-tools___synthesize_cited_answer
#   verity-openapi-tools___answer_with_citations
# The bare operationId is not the exposed name. Renaming the target above renames
# every exposed tool. See:
# https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-tool-naming.html

print(response)
