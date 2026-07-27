# AgentCore CLI example

Release authors can add the OpenAPI target with the AgentCore CLI after replacing
the placeholder server URL and configuring outbound authorization.

## Which CLI

These commands belong to the **`aws/agentcore-cli`** (the `agentcore` command), not to the
`bedrock-agentcore-starter-toolkit`. The starter toolkit is now explicitly legacy and has
no gateway-target CLI command.

Reference: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-create-cli.html

```bash
agentcore add gateway-target \
  --name verity-openapi-tools \
  --type open-api-schema \
  --schema contracts/openapi/verity-tools.openapi.yaml \
  --outbound-auth api-key \
  --gateway "$AGENTCORE_GATEWAY_NAME"

agentcore deploy
```

Valid `--type` values: `mcp-server`, `api-gateway`, `open-api-schema`, `smithy-model`,
`lambda-function-arn`.

For `open-api-schema`, outbound auth must be `oauth` or `api-key`.

The target name is load-bearing. `--name verity-openapi-tools` is what produces the
exposed tool names `verity-openapi-tools___<operationId>`. See `README.md`.

## Starter-toolkit alternative

The `bedrock-agentcore-starter-toolkit` exposes Python methods rather than CLI commands:

```python
from bedrock_agentcore_starter_toolkit.operations.gateway import GatewayClient

client = GatewayClient(region_name="us-east-1")
gateway = client.create_mcp_gateway(name="verity-gateway")
target = client.create_mcp_gateway_target(
    gateway=gateway,
    name="verity-openapi-tools",
    target_type="openApiSchema",
)
```

Reference: https://aws.github.io/bedrock-agentcore-starter-toolkit/user-guide/gateway/quickstart.html

For full control over target and credential configuration, call
`bedrock-agentcore-control` directly with boto3. See `create_openapi_target.example.py`.

## Inbound authorization

Not set here. Inbound auth is a `CreateGateway` property, not a target property.
`authorizerType` is required, and `NONE` is valid alongside `CUSTOM_JWT`, `AWS_IAM`, and
`AUTHENTICATE_ONLY`; `authorizerConfiguration` is required only for `CUSTOM_JWT`. For a
workshop, `NONE` or `AWS_IAM` is the path of least resistance.

Reference: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_CreateGateway.html

The exact authorization choice is deployment-specific and is made by the release author.
The workshop must use a pre-provisioned target and must not ask participants to configure
this.
