# Managed Strands agent

Mosaic runs the Strands agent in Amazon Bedrock AgentCore Runtime. The agent
calls three SQL capabilities through an IAM-authenticated AgentCore Gateway:

- `mosaic___search_products`: hybrid search, rank fusion and reranking.
- `mosaic___get_product_evidence`: source records for a retrieved product.
- `mosaic___inspect_retrieval_run`: saved search and ranking details.

Gateway forwards MCP requests to a separate tools Runtime. Both runtimes use
private VPC access to Aurora and read their database credential from Secrets
Manager. The browser reaches Mosaic through CloudFront; the API invokes Runtime
with IAM credentials. The browser never receives AWS credentials.

Aurora remains the authority for products, evidence, search runs and citations.
Strands chooses tools; application code enforces retrieval scope, product
ownership, the tool budget and citation checks. Amazon Bedrock supplies Cohere
Embed v4, Cohere Rerank 3.5 and Claude Sonnet 5. AgentCore Memory provides semantic
facts, preferences, summaries and episodes. See [conversation memory](session-memory.md).

## Workshop deployment

The Workshop Studio stack creates the code bucket, two runtimes, Gateway target,
execution roles, encrypted logs and Memory. Bootstrap restores the real catalog
with its saved vectors, stages the ARM64 Python package and connects the managed
resources before declaring the application ready.

Participants build `create_agent` in [labs/lab3/agent.py](../labs/lab3/agent.py).
The SQL they repaired in Labs 1 and 2 travels with the tools package.

```sh
make agent-tools
make deploy-agent
make verify-agent
```

Deployment updates both runtimes, waits until the DEFAULT endpoints serve the
new versions, synchronizes Gateway and exercises real Aurora search and scoped
evidence. A deployment receipt records the source digest, runtime and search ID.
The code package is built from the locked dependencies and an explicit list of
application files; credentials, local caches and symlinks are excluded.

## Runtime boundary

The HTTP runtime entry point is `deploy/agentcore/run.py` on port 8080; the MCP
tools entry point is `deploy/agentcore/run_tools.py` on port 8000. The HTTP adapter
supports health, source/readiness status, answers and streamed answers. It uses
the same agent and citation path as the Mosaic API.

Each invocation binds the workspace source digest. Stale deployed code is
rejected with a command to redeploy. A fresh Runtime session is used per
invocation; Mosaic's Aurora session records retain the conversation. Only the
opaque browser capability is forwarded for shopper ownership. A supplied actor
ID or untrusted browser header cannot select another shopper.

The adapter closes the upstream stream and releases its admission slot on
completion, client disconnect or cancellation. AWS invocation failures produce
an actionable participant message; sensitive SDK details stay out of responses.

## Configuration

Bootstrap supplies these values; participants do not copy credentials:

| Setting | Purpose |
|---|---|
| `MOSAIC_AGENTCORE_RUNTIME_ARN` | Agent endpoint invoked by the Mosaic API |
| `MOSAIC_AGENTCORE_TOOLS_RUNTIME_ARN` | SQL tools runtime updated by deployment |
| `MOSAIC_AGENTCORE_GATEWAY_URL` | Signed MCP destination |
| `MOSAIC_AGENTCORE_GATEWAY_ID`, `MOSAIC_AGENTCORE_GATEWAY_TARGET_ID` | Tool synchronization |
| `MOSAIC_RUNTIME_CODE_BUCKET` | This account's deployment packages |
| `MOSAIC_EDITOR_STACK` | Native resource discovery |
| `MOSAIC_DATABASE_SECRET_ARN` | Runtime's least-privilege Aurora credential |
| `MOSAIC_CATALOG_DATASET` | Selected manifest-backed real catalog |
| `MOSAIC_AGENTCORE_MEMORY_ID` | Preconfigured conversation memory |

Retrieval settings remain in `db/config/retrieval.yaml`. The runtime environment
selects the same model IDs and catalog as the API. Product evidence is read fresh
from Aurora even when Memory recalls a preference.

## Shared service settings

The stack sets the model and catalog values; the database secret supplies the
connection. These settings also apply to the HTTP service and container path:

| Setting | Runtime source and behavior |
|---|---|
| `DATABASE_URL` | Read from Secrets Manager when `MOSAIC_DATABASE_SECRET_ARN` is set; never put it in the package |
| `BEDROCK_REGION` | Deployment region; defaults to the AWS region |
| `BEDROCK_EMBED_MODEL_ID`, `BEDROCK_RERANK_MODEL_ID`, `BEDROCK_CHAT_MODEL_ID` | Pinned stack model IDs; embedding, reranking and agent/answer model respectively |
| `EMBEDDING_PROVIDER`, `RERANK_PROVIDER`, `RERANK_REQUIRED` | Stack selects Bedrock and requires reranking |
| `ALLOW_DEVELOPMENT_EMBEDDINGS` | False in the workshop; saved source vectors and Bedrock query vectors are required |
| `MOSAIC_SOURCE_REVISION`, `AURORA_INSTANCE_CLASS` | Stack revision and database class recorded with results |
| `MOSAIC_DB_STATEMENT_TIMEOUT_MS`, `MOSAIC_DB_LOCK_TIMEOUT_MS` | Bound Aurora statement and lock waits; defaults come from service configuration |
| `MOSAIC_AGENT_TURN_DEADLINE_SECONDS` | Bounds the model/tool loop |
| `MOSAIC_MAX_CONCURRENT_MODEL_RUNS`, `MOSAIC_MODEL_RATE_LIMIT_PER_MINUTE` | API admission limits; Runtime also has managed scaling controls |
| `CORS_ORIGINS`, `MOSAIC_CODE_EDITOR_URL` | Browser API origin and editor link; not agent tool credentials |
| `MOSAIC_REQUIRE_ORIGIN_VERIFICATION`, `MOSAIC_ORIGIN_VERIFY_SECRET` | CloudFront/API ingress protection; the Runtime invocation is protected by IAM and does not receive this secret |
| `MOSAIC_AGENTCORE_OBSERVABILITY`, `MOSAIC_AGENTCORE_CAPTURE_CONTENT` | Disabled unless the operator configures an exporter and explicitly opts into content capture |

## Release acceptance

Offline contracts are necessary but do not establish a working managed service.
Before release, deploy the exact source and verify Gateway discovery, Aurora
search and evidence, an actual cited agent answer, a changed-requirement follow-up,
streaming, shopper isolation and Memory. A stale workspace must fail before it
can receive credit for a deployed reference implementation. Record the account,
source revision, source digest and live run IDs in the release evidence.
