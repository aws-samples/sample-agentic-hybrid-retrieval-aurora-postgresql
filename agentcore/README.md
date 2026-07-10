# AgentCore Gateway

This directory is the optional [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/)
path for the hybrid retrieval engine. The production-ready deployable resource is
an **AgentCore Gateway** with a Lambda MCP target. The Lambda is built and owned
by the repo's Python CDK stack so VPC placement, Aurora ingress, Secrets Manager
access, and Bedrock Runtime permissions stay in infrastructure as code.

The `runtime/` folder is kept as a local BYO Runtime scaffold for extension work,
but it is not deployed by default. A production runtime needs its own VPC and IAM
contract; the Gateway Lambda already has that contract and is the supported
optional path for this workshop.

## Layout

```text
agentcore/
├── agentcore.json            # AgentCore CLI project config: Gateway + Lambda ARN target
├── aws-targets.json          # Empty template; provision.sh writes the active account/region
├── provision.sh              # Resolve GatewayLambdaArn + run the Node-based AgentCore CLI
├── gateway/
│   ├── handler.py            # Lambda MCP target: 4 tools, dual-shape resolve_invocation
│   ├── retrieval_tools.json  # MCP tool schemas referenced by the Gateway target
│   └── requirements.txt      # psycopg + boto3 for the packaged Lambda
└── runtime/
    ├── main.py               # Local BYO Runtime scaffold for future extension
    └── requirements.txt      # bedrock-agentcore SDK + backend agent deps
```

## The four Gateway tools

| MCP tool | SQL function | Signal |
| --- | --- | --- |
| `full_text_search` | `ops.full_text_search` | Lexical (`tsvector` / `ts_rank_cd`) |
| `vector_search` | `ops.vector_search` | Semantic (pgvector cosine, Cohere embed-v4) |
| `fuzzy_match` | `ops.fuzzy_match` | Typo-tolerant (`pg_trgm` trigram) |
| `hybrid_search` | `ops.hybrid_search` | RRF fusion of all three + metadata/recency scoring |

### The OR-combine invariant holds here too

`full_text_search` builds its `tsquery` through **`ops.to_or_tsquery`**, the
single home of the OR-combine rewrite. `websearch_to_tsquery` defaults to
AND-semantics, which can score `text_rank = 0` for every row on a natural
language question and silently disable full-text search. Both `ops.hybrid_search`
and `ops.full_text_search` call the same helper.

## Deploy

Prerequisites: Node.js 20.19+, `npx`, AWS credentials for `us-east-1`, Docker
available for CDK Lambda bundling, and the default Aurora stack already deployed.

```bash
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1

cd infra/cdk
ENABLE_AGENTCORE_GATEWAY_STACK=1 \
  npx aws-cdk deploy AgenticRetrievalCoreStack AgenticRetrievalAgentCoreGatewayStack
cd ../..

make agentcore-provision
```

`provision.sh` resolves the `AgentCoreGatewayLambdaArn` CloudFormation output,
validates that the Lambda is `python3.12`, uses `handler.lambda_handler`, and is
VPC-attached, then runs:

```bash
cd agentcore
npx -y @aws/agentcore@0.18.0 validate --directory .
npx -y @aws/agentcore@0.18.0 deploy --target default --yes
cd ..
```

For a non-mutating CLI check:

```bash
AGENTCORE_DRY_RUN=1 make agentcore-provision
```

If you use a different stack name or deployment target:

```bash
STACK_NAME=MyStackName AGENTCORE_DEPLOY_TARGET=prod make agentcore-provision
```

If automation already has the Lambda ARN, bypass CloudFormation output lookup:

```bash
GATEWAY_LAMBDA_ARN=arn:aws:lambda:us-east-1:<account>:function:<name> \
  make agentcore-provision
```

## Local smoke test

The Gateway handler can be exercised without AgentCore. Set `DATABASE_URL` first
so the SQL calls resolve.

```bash
DATABASE_URL=postgresql://localhost:55432/retrieval?sslmode=disable \
  python -c 'import json; from agentcore.gateway.handler import lambda_handler; \
print(lambda_handler({"tool": "full_text_search", "arguments": {"query": "ORION-1489", "limit": 5}}, None))'
```

> Scope note: the connected systems are Slack, Jira, Confluence, Salesforce, and
> GitHub (ServiceNow is out of scope for this workshop), matching the rest of the repo.
