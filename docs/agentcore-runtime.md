# AgentCore Runtime (optional)

This document describes packaging the Mosaic retrieval service as an Amazon
Bedrock AgentCore Runtime container.

**None of this is required.** The three labs run against the FastAPI service on
the Code Editor host and never touch AgentCore. Nothing here is deployed by the
workshop bootstrap, nothing here is deployed by CI, and nothing here has been
deployed from the machine that wrote these artifacts. Treat it as a
facilitator-provisioned demonstration for flex time, not as a lab step.

Pre-provisioning an endpoint in the event account is CloudFormation work in the
sibling Workshop Studio repository. It is not included here, and this repository
holds no stack, no role, and no endpoint for it.

## Why this beat exists

The claim it supports is narrow and worth stating exactly: the process ships to
AgentCore Runtime unchanged because Aurora is the evidence authority, not the
harness. The agent's tools read Aurora. Which rows an answer may cite is decided
in `service/retrieval_scope.py` and `service/agent_tools.py` against what Aurora
returns. Moving the process from a uvicorn on an EC2 host into a managed runtime
changes who starts the process and who routes traffic to it. It changes nothing
about retrieval, ranking, citation, or the receipts.

That is the whole point. If moving the harness changed the answers, the evidence
authority was in the harness.

## What gets deployed

`deploy/agentcore/Dockerfile` builds one image from the repository root as the
build context. It contains:

- The dependency set resolved from `pyproject.toml` and `uv.lock` with
  `uv sync --frozen --no-dev`, so the image installs exactly what the repository
  pins and leaves `pytest` and `ruff` out.
- `service/`, the FastAPI application and the Strands agent it hosts.
- `db/` and three named files under `scripts/`, because the retrieval
  fingerprint in `service/retrieval_fingerprint.py` hashes them and refuses to
  produce a fingerprint over a category that lost its files.
- `data/evals/` and `data/benchmarks/`, the measured artifacts the scorecard and
  the HNSW instrument replay, plus `data/media/asset_labels_200.json` and
  `data/full/manifest.json`.

It deliberately does not contain the UI. The storefront build stays on the
workshop host and talks to this service over HTTP. It also does not contain
`.env`. Every `COPY` names an explicit path, so a facilitator's real Aurora DSN
cannot be swept into a layer by a recursive copy.
`tests/test_agentcore_artifacts.py` enforces both the explicit-path rule and the
non-root user.

## The container contract

AgentCore Runtime's HTTP protocol contract, as the packaging reference states
it:

| Requirement | Value |
|---|---|
| Architecture | ARM64 (Graviton). An x86 image will not start. |
| Port | 8080, bound to `0.0.0.0` for AgentCore's internal routing |
| Health check | `GET /ping`, returning `{"status":"Healthy"}` or `{"status":"HealthyBusy"}` |
| Invocation | `POST /invocations` |
| Logging | stdout and stderr, routed to CloudWatch |
| Shutdown | handle SIGTERM |

The Dockerfile satisfies architecture, port, host binding, logging, and the
non-root requirement. Do not publish port 8080 to the internet. AgentCore
terminates TLS at its load balancer and hands the container plaintext HTTP over
an internal network, so a directly exposed container is an unauthenticated
endpoint.

## Where the contract does not line up yet

The service exposes `GET /api/health` and `POST /api/agent/answer`. AgentCore
checks `GET /ping` and routes to `POST /invocations`. Those routes do not exist
in `service/main.py` today, and this image adds nothing to the application, so a
runtime created from it will fail its health check.

Closing that gap is two routes: a `/ping` that returns the health status
document, and an `/invocations` that accepts the `AgentRequest` body and returns
what `/api/agent/answer` returns. That is application code and it is not part of
these artifacts. State the gap when demonstrating this beat rather than implying
a working endpoint. The image, the build, and the local smoke run are real and
verifiable now; a live AgentCore endpoint is not, until those two routes exist.

## Environment the runtime needs

Every setting below is one `config/.env.example` assigns a value to, which is
that file's own marker for a deployment or service setting rather than a
retrieval tunable. Retrieval numbers live in `db/config/retrieval.yaml` and are
not passed to the runtime. `tests/test_agentcore_artifacts.py` derives this list
from the example file and fails if a setting is missing from this table.

| Variable | Where the runtime gets it | Notes |
|---|---|---|
| `DATABASE_URL` | Secrets Manager, read by the container at startup | The Aurora DSN, including a password. Never an AgentCore environment variable: `get-agent-runtime` returns those in plaintext to anyone who can call it. |
| `BEDROCK_REGION` | Runtime environment variable | Region for embedding, rerank, and chat calls. Falls back to `AWS_REGION`, which AgentCore injects. |
| `BEDROCK_EMBED_MODEL_ID` | Runtime environment variable | `us.cohere.embed-v4:0` |
| `BEDROCK_RERANK_MODEL_ID` | Runtime environment variable | `cohere.rerank-v3-5:0` |
| `BEDROCK_CHAT_MODEL_ID` | Runtime environment variable | `global.anthropic.claude-sonnet-4-6`. `BEDROCK_AGENT_MODEL_ID` and `BEDROCK_SYNTHESIS_MODEL_ID` are optional and split the agent and synthesis routes; omit both to use the chat model for the whole path. |
| `EMBEDDING_PROVIDER` | Runtime environment variable | `bedrock` |
| `RERANK_PROVIDER` | Runtime environment variable | `bedrock` |
| `RERANK_REQUIRED` | Runtime environment variable | `true`. A silent fallback to unreranked results would make the receipts wrong. |
| `ALLOW_DEVELOPMENT_EMBEDDINGS` | Runtime environment variable | `false`. Hash vectors never support a relevance claim. |
| `CORS_ORIGINS` | Runtime environment variable | Origin of the storefront that calls this runtime. The workshop-host default does not apply once the service moves. |
| `MOSAIC_SOURCE_REVISION` | Runtime environment variable, set at build or deploy time | The image has no `.git`, so `service/config.py` cannot derive the revision and reports `unknown`. Set this or the receipts cannot name what produced them. |
| `AURORA_INSTANCE_CLASS` | Runtime environment variable | Recorded on measured artifacts. Describes the Aurora instance, not the runtime. |
| `MOSAIC_CODE_EDITOR_URL` | Leave unset | Points participants at a Code Editor the runtime does not have. The service refuses to start if the value carries a `tkn=` token. |
| `MOSAIC_AGENTCORE_OBSERVABILITY` | Runtime environment variable | `false` unless an OpenTelemetry exporter is actually configured. Aurora stays the canonical ledger either way. See `docs/telemetry-contract.md`. |
| `MOSAIC_AGENTCORE_CAPTURE_CONTENT` | Runtime environment variable | `false`. Turning it on projects question and answer text off Aurora. |

## IAM the runtime role needs

The role passed as `--role-arn` on `create-agent-runtime` is what the container
can reach. Scope it to this list and nothing wider.

1. **Bedrock invoke on the three models.** `bedrock:InvokeModel` and
   `bedrock:InvokeModelWithResponseStream` for the embedding, rerank, and chat
   model ids above, including the inference profile ARNs the `us.` and `global.`
   prefixes resolve through. Reranking is the exception: `bedrock:Rerank`
   requires `Resource: "*"`, because a model-scoped resource on that action
   evaluates as an implicit deny.
2. **Secrets Manager read.** `secretsmanager:GetSecretValue` on the single ARN of
   the secret holding `DATABASE_URL`, plus `kms:Decrypt` on the key that secret
   uses if it is not the AWS managed key.
3. **A network path to Aurora.** Aurora is in a VPC, so the runtime needs VPC
   network mode and the elastic network interface permissions that go with it
   (`ec2:CreateNetworkInterface`, `ec2:DescribeNetworkInterfaces`,
   `ec2:DeleteNetworkInterface`). Attach it to subnets that route to the cluster
   and to a security group the Aurora security group admits on 5432. Adding an
   inbound rule to the Aurora security group is a deliberate act; the cluster's
   group is closed by default in this project.
4. **CloudWatch Logs write** for the runtime's log group.

Two further rules from the AgentCore reference apply and are not optional in a
shared account: include `aws:SourceArn` and `aws:SourceAccount` conditions in the
role's trust policy to prevent a confused deputy, and give each runtime its own
role rather than sharing one.

The exact field shape of `--network-configuration` for VPC mode is not pinned by
this repository. Take it from the current AgentCore control-plane API reference
and pass it through `AGENTCORE_NETWORK_CONFIG`. The Makefile default is
`{"networkMode":"VPC"}`, which is the mode but not a complete VPC attachment.

## Build

```sh
make agentcore-image
```

Builds `mosaic-retrieval-agent:local` for `linux/arm64` from the repository root.
Override the tag with `AGENTCORE_IMAGE_TAG`. This requires a Docker installation
with `buildx`, and on an x86 host it requires emulation, because the image must
be ARM64 whatever the builder is.

## Smoke the image before pushing it

```sh
set -a; . ./.env; set +a
make agentcore-image-smoke
```

Runs the image with the port published to `127.0.0.1` only, forwards
`DATABASE_URL` and the AWS credential variables by name so no value is printed,
polls `GET /api/health` until it answers, prints the response, and removes the
container. A health check that fails here fails on AgentCore too, so this is the
cheapest place to find a packaging mistake.

## Deploy

```sh
make agentcore-deploy
```

Prints the full command sequence and exits without making a network call. That
is the default and it is what this repository is for. To execute it, supply the
target account's values and confirm explicitly:

```sh
make agentcore-deploy \
  AGENTCORE_CONFIRM=1 \
  AGENTCORE_ECR_REPO=<account>.dkr.ecr.<region>.amazonaws.com/mosaic-retrieval-agent \
  AGENTCORE_ROLE_ARN=arn:aws:iam::<account>:role/<runtime-role> \
  AGENTCORE_AUTHORIZER_CONFIG='<authorizer-configuration>' \
  AGENTCORE_NETWORK_CONFIG='<vpc-network-configuration>'
```

The target refuses to run with an empty `AGENTCORE_AUTHORIZER_CONFIG`. An
unauthenticated runtime endpoint is not acceptable outside an isolated
development account.

After `create-agent-runtime` returns an id, create the endpoint and wait for it:

```sh
aws bedrock-agentcore-control create-agent-runtime-endpoint \
  --agent-runtime-id <id> --name default --region <region>
aws bedrock-agentcore-control get-agent-runtime-endpoint \
  --agent-runtime-id <id> --endpoint-id <endpoint-id> --region <region>
```

The runtime is not invocable until that endpoint reports `READY`. Roll back by
deploying the previous image tag, which is why the deploy pushes a version tag
alongside `latest` in any real account.

## Invoke it once

The application endpoint is `POST /api/agent/answer`, taking an `AgentRequest`
and returning an `AgentResponse` (`service/models.py`). Against a local
container:

```sh
curl -fsS http://127.0.0.1:8080/api/agent/answer \
  -H 'content-type: application/json' \
  -d '{
        "question": "quiet keyboard for an open-plan office under $150",
        "result_limit": 6,
        "filters": {"in_stock_only": true, "max_price_cents": 15000}
      }'
```

`question` is required, 4 to 2000 characters. `result_limit` defaults to 6 and is
bounded to 2 through 12. `filters` is the same `SearchFilters` object the search
endpoint takes, with prices in integer cents. An optional `context` object
carries `previous_agent_run_id` and the prior recommendations for a follow-up
turn. The body rejects unknown fields, so a typo fails with a 422 rather than
being silently ignored.

Once the two contract routes exist, the same body goes to `POST /invocations`,
and through AgentCore it goes to `bedrock-agentcore invoke-agent-runtime` with a
`runtimeSessionId`. The request shape does not change.

## What the receipts prove

The response carries `agent_run_id`. That id is the `agent_turn_id` written to
`mosaic.agent_turn` in Aurora by `service/agent_tools.py`, with each retrieval
the agent ran linked back to that turn. A run against the AgentCore Runtime lands
in the same ledger, in the same table, with the same shape as a run against the
service on the workshop host. Nothing about the receipt records which harness
produced it, because nothing about the receipt depends on the harness.

That is the check worth doing during a demonstration. Take the `agent_run_id`
from the runtime's response, query `mosaic.agent_turn` and the retrieval rows
joined to it, and show that the evidence trail is identical to a local run. The
answer is reproducible from Aurora, not from the runtime's logs.

## Related

- `docs/telemetry-contract.md` for the Aurora ledger schema and the optional
  OpenTelemetry projection.
- `docs/aurora-deployment.md` for the cluster the runtime has to reach.
- `docs/api-contract.md` for the full request and response contracts.
