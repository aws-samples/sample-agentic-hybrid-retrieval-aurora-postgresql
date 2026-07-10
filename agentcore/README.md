# AgentCore Gateway + Runtime

This directory is an optional [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/)
scaffold that exposes the same hybrid retrieval engine two ways:

- an **AgentCore Gateway** whose Lambda MCP target publishes four retrieval tools, and
- a **BYO AgentCore Runtime** that hosts the cited-answer agent behind the AgentCore
  invocation contract.

Both wrap the exact SQL in `sql/03_search_functions.sql` — nothing re-implements the
ranking. It is provisioned with the `@aws/agentcore` CLI from `agentcore.json`; the
repo's primary infrastructure remains the Python CDK stack in `infra/cdk`.

## Layout

```text
agentcore/
├── agentcore.json            # CLI project config: 1 runtime + 1 gateway (Lambda target)
├── provision.sh              # Resolve GatewayLambdaArn + run the Node-based AgentCore CLI
├── gateway/
│   ├── handler.py            # Lambda MCP target — 4 tools, dual-shape resolve_invocation
│   ├── retrieval_tools.json  # MCP tool schemas referenced by the gateway target
│   └── requirements.txt      # psycopg + boto3 for the packaged Lambda
└── runtime/
    ├── main.py               # BedrockAgentCoreApp entrypoint (:8080), resolve_invocation
    └── requirements.txt      # bedrock-agentcore SDK + backend agent deps
```

## The four Gateway tools

| MCP tool           | SQL function             | Signal                                   |
| ------------------ | ------------------------ | ---------------------------------------- |
| `full_text_search` | `ops.full_text_search`   | Lexical (tsvector / `ts_rank_cd`)        |
| `vector_search`    | `ops.vector_search`      | Semantic (pgvector cosine, Cohere embed-v4) |
| `fuzzy_match`      | `ops.fuzzy_match`        | Typo-tolerant (pg_trgm trigram)          |
| `hybrid_search`    | `ops.hybrid_search`      | RRF fusion of all three + metadata/recency |

### The OR-combine invariant holds here too

`full_text_search` builds its `tsquery` through **`ops.to_or_tsquery`**, the single
home of the OR-combine rewrite. `websearch_to_tsquery` defaults to AND-semantics,
which scores `text_rank = 0` for every row on a natural-language question and
silently disables full-text search — so the exact-ID teaching moment (a Jira key
like `ORION-1489` surfacing primarily by lexical match) would break. Both
`ops.hybrid_search` and `ops.full_text_search` call the same helper, so the rewrite
lives in exactly one place. Do not inline a raw `websearch_to_tsquery` in the tool.

## Invocation shapes

Both entrypoints normalize their payload with a `resolve_invocation` helper so the
same code answers more than one caller:

- **Gateway Lambda** (`gateway/handler.py`) — AgentCore Gateway MCP
  (`context.client_context.custom['bedrockAgentCoreToolName']`, split on `___`),
  a classic Bedrock Agent action group (`event["actionGroup"]`), or a direct
  `{"tool": "...", "arguments": {...}}` test call.
- **Runtime** (`runtime/main.py`) — a direct `{"question": "..."}` / `{"prompt": "..."}`
  payload, or a gateway-wrapped envelope that nests args under `input`/`arguments`.

## Deploy

Prerequisites: Node.js 20.19+, `npx`, AWS credentials for `us-east-1`, and Docker
available for CDK Lambda bundling. CDK owns the Gateway Lambda code package, VPC
placement, Aurora ingress, Secrets Manager access, and Bedrock Runtime invoke
permissions. The Node-based AgentCore CLI only wires the deployed Lambda ARN into
the Gateway target and provisions the BYO Runtime.

```bash
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1

cd infra/cdk
ENABLE_AGENTCORE_GATEWAY_STACK=1 \
  npx aws-cdk deploy AgenticRetrievalCoreStack AgenticRetrievalAgentCoreGatewayStack
cd ../..

make agentcore-provision
```

`provision.sh` resolves the `AgentCoreGatewayLambdaArn` CloudFormation output from
`AgenticRetrievalAgentCoreGatewayStack`, validates that the Lambda is `python3.12`,
uses `handler.lambda_handler`, and is VPC-attached, then runs:

```bash
npx -y @aws/agentcore@0.18.0 provision --config agentcore.json
```

If you use a different stack name, pass it explicitly:

```bash
STACK_NAME=MyStackName make agentcore-provision
```

If your automation already has the Lambda ARN, you can bypass CloudFormation
output lookup:

```bash
GATEWAY_LAMBDA_ARN=arn:aws:lambda:us-east-1:<account>:function:<name> \
  make agentcore-provision
```

## Local smoke test

Neither entrypoint needs AgentCore to be exercised locally — set `DATABASE_URL`
first so the SQL calls resolve.

```bash
# Runtime entrypoint (no SDK server; runs the agent once and prints the answer):
DATABASE_URL=postgresql://localhost:55432/retrieval?sslmode=disable \
  INVOKE_LOCAL=1 python agentcore/runtime/main.py \
  '{"question": "Why did Orion slip?"}'

# Gateway tool (direct-invocation shape):
DATABASE_URL=postgresql://localhost:55432/retrieval?sslmode=disable \
  python -c 'import json; from agentcore.gateway.handler import lambda_handler; \
print(lambda_handler({"tool": "full_text_search", "arguments": {"query": "ORION-1489", "limit": 5}}, None))'
```

> Scope note: the connected systems are Slack, Jira, Confluence, Salesforce, and
> GitHub (ServiceNow is out of scope for this workshop), matching the rest of the repo.
