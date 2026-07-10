# Agentic Hybrid Retrieval with PostgreSQL and pgvector

[![License: MIT-0](https://img.shields.io/badge/License-MIT--0-yellow.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![PostgreSQL 18.3+](https://img.shields.io/badge/PostgreSQL-18.3%2B-336791.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![pgvector 0.8.1+](https://img.shields.io/badge/pgvector-0.8.1%2B-4B8BBE.svg)](https://github.com/pgvector/pgvector)
[![Aurora PostgreSQL](https://img.shields.io/badge/Amazon%20Aurora-PostgreSQL-FF9900.svg?logo=amazonaws&logoColor=white)](https://aws.amazon.com/rds/aurora/)
[![Amazon Bedrock](https://img.shields.io/badge/Amazon%20Bedrock-Cohere%20%26%20Claude-232F3E.svg?logo=amazonaws&logoColor=white)](https://aws.amazon.com/bedrock/)
[![React](https://img.shields.io/badge/React-18-61DAFB.svg?logo=react&logoColor=black)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-8-646CFF.svg?logo=vite&logoColor=white)](https://vite.dev/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

This repository is a security-reviewable starter implementation for a re:Invent 2026 builders' session:

> **Build agentic hybrid retrieval with Amazon Aurora PostgreSQL**

For local development and the first builder-session path, the retrieval engine is **PostgreSQL 18.3 or later with pgvector 0.8.1 or later**. The same schema can run on localhost PostgreSQL or on a net-new Aurora PostgreSQL 18.3 cluster provisioned by the CDK stack in this repo.

The product is an operational evidence retrieval layer over fragmented work systems such as Slack-like conversations, Jira issues, Confluence pages, Salesforce cases, GitHub pull requests, runbooks, and incident notes.

## Prerequisites

- Python 3.13 or later
- Node.js 20.19 or later for the frontend and MCP server
- Local PostgreSQL 18.3 or later with pgvector 0.8.1+, pg_trgm, btree_gin, pgcrypto, and pg_stat_statements
- Optional: Docker, if you prefer the Compose-based Postgres path
- AWS credentials for optional Bedrock embeddings, Bedrock Agent integration, or the Aurora deployment path

## What participants build

Participants build a lightweight retrieval system that can answer questions like:

> Why is Project Orion delayed, what did the team decide in Slack, and what customer commitments are impacted?

The system:

1. Ingests operational source objects.
2. Normalizes records into a PostgreSQL schema.
3. Chunks long text.
4. Generates embeddings.
5. Stores source links and citations.
6. Runs PostgreSQL full-text search, pgvector semantic similarity, SQL filters, metadata filters, time-window filters, and pg_trgm fuzzy matching.
7. Combines retrieval sets with Reciprocal Rank Fusion.
8. Returns cited answers through agent-callable tools.
9. Stores retrieval diagnostics for evaluation and explainability.

## Pipeline Positioning

This workshop does **not** recommend replacing Jira, Slack, Confluence,
Salesforce, GitHub, or other source systems with Aurora PostgreSQL. Those systems
remain authoritative for workflow, permissions, ownership, and mutation.

The recommended pattern is a **materialized evidence index** in Aurora
PostgreSQL:

- Store the searchable projection: source IDs, URLs, titles, excerpts or bodies,
  metadata, ACL markers, citations, relationships, embeddings, sync cursors, and
  provenance.
- Keep that projection fresh with connectors, webhooks, scheduled exports,
  AppFlow/Glue jobs, or an ingestion API.
- Use MCP tools and connectors for live lookups, actions, revalidation, and
  source-specific operations.
- Build the UI and agent search path over Aurora because hybrid retrieval,
  filtering, citation joins, diagnostics, and evaluation need a durable,
  queryable index.

The lab uses a committed seed bundle to stand in for the enterprise data
pipeline, so participants can focus on the retrieval schema and agent-facing
search behavior. In production, the same schema receives data from the
connectors or export jobs that fit each source system.

## Repo Layout

```text
.
├── backend/                    # FastAPI API, ingestion pipeline, search, agent tools
├── frontend/                   # Vite + React UI
├── sql/                        # PostgreSQL schema, indexes, functions, diagnostics
├── data/                       # Workshop-safe source bundle
├── connectors/                 # Optional connector scaffolds and normalizers
├── bedrock-agent/              # Optional Amazon Bedrock Agent action group wrapper
├── agentcore/                  # Optional AgentCore Gateway (Lambda MCP target)
├── mcp-server/                 # Optional MCP wrapper around the retrieval API
├── infra/                      # CDK skeleton and local Postgres Dockerfile
├── seed/                       # Canonical Orion corpus generator + pg_dump/restore
├── mockups/                    # Static design prototype reference
└── docs/                       # Session plan, architecture, security notes, stretch labs
```

## Quick Start: Local Postgres + API + UI

Set up Python dependencies:

```bash
make install
cp .env.example .env
```

The sample is configured for `us-east-1` when AWS services are used. Keep `AWS_REGION=us-east-1` and `AWS_DEFAULT_REGION=us-east-1` in your shell for the Aurora and Bedrock paths.

Install PostgreSQL and pgvector with Homebrew:

```bash
brew install postgresql@18 pgvector
```

The native bootstrap checks for PostgreSQL 18.3 or later and pgvector 0.8.1 or later. The local scripts prefer Homebrew's `postgresql@18` binaries at `/usr/local/opt/postgresql@18`.

Start local Postgres, create the database, create schema, load the sample source bundle, and embed chunks:

```bash
make local-db-bootstrap
```

This uses:

```text
DATABASE_URL=postgresql://localhost:55432/retrieval?sslmode=disable
```

Run the API:

```bash
uvicorn backend.app.main:app --reload --port 8000
```

Run the frontend:

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

The frontend calls the API directly. If the API or database is unavailable, it shows an explicit setup/search error; it does not substitute offline result data.

## Docker Postgres Option

If Docker is available:

```bash
docker compose up -d --build postgres
export DATABASE_URL=postgresql://retrieval:retrieval@localhost:55432/retrieval?sslmode=disable
make schema
make seed-load   # pg_restore the Cohere-embedded dump + rebuild HNSW/GIN/trgm indexes
```

The Compose image builds PostgreSQL `18.3` with pgvector `v0.8.2`. `make seed-load`
restores the canonical 150-object corpus with its **real Cohere `embed-v4` vectors**
baked in — there is no separate embedding step and no Bedrock call at load time.

## Aurora PostgreSQL 18.3 Option

The CDK stack provisions a net-new Aurora PostgreSQL 18.3 Serverless v2 cluster, the source landing buckets, a Secrets Manager database secret, and the placeholder Bedrock Agent action Lambda. The optional AgentCore Gateway uses a separate Lambda and stack.

Bootstrap the target account and region if needed:

```bash
cd infra/cdk
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
npx aws-cdk@latest bootstrap
```

Deploy the stack. Pass your current client IP as a `/32` so the local API and schema loader can reach Aurora directly:

```bash
export CLIENT_CIDR="$(curl -s https://checkip.amazonaws.com)/32"
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
npx aws-cdk@latest deploy \
  --parameters ClientAccessCidr="$CLIENT_CIDR" \
  --parameters DatabaseName=retrieval
```

After deploy, use the `AuroraDatabaseUrlCommand` output from CloudFormation to create `DATABASE_URL`, then install the schema and verify PostgreSQL plus pgvector:

```bash
cd ../..
eval "$(scripts/aurora_database_url.sh <secret-arn> <cluster-endpoint> retrieval)"
make aurora-verify
make seed-load   # pg_restore the Cohere-embedded dump + rebuild HNSW/GIN/trgm indexes
```

`make aurora-verify` creates or updates the required extensions and schema, then checks for PostgreSQL 18.3+ and pgvector 0.8.1+.

### Local VSCode Against Workshop Aurora

When the Workshop Studio bootstrap has already deployed `AgenticRetrievalCoreStack`,
you can run the API and UI locally while pointing at the same Aurora cluster and
Bedrock region the workshop provisions:

```bash
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
make install
make aurora-local-env
make aurora-verify
make seed-load
make api
```

In a second VSCode terminal:

```bash
cd frontend
npm install
npm run dev
```

`make aurora-local-env` resolves the stack outputs, reads the database secret
from Secrets Manager, writes ignored local `.env` files for the backend and
frontend, and checks whether the Aurora endpoint is reachable from the local
machine. The files are intentionally not committed. If the network check says
Aurora is not reachable, run VSCode from an environment inside the VPC or add the
current client CIDR to the Aurora security group through the workshop stack.

## Optional AgentCore Gateway

The default Aurora stack does not deploy AgentCore resources. To opt in, deploy
the dedicated AgentCore Gateway stack, then run the Node-based AgentCore CLI
deployment flow:

```bash
cd infra/cdk
ENABLE_AGENTCORE_GATEWAY_STACK=1 \
  npx aws-cdk@latest deploy AgenticRetrievalCoreStack AgenticRetrievalAgentCoreGatewayStack
cd ../..

make agentcore-provision
```

The optional CDK stack owns the Gateway Lambda package, VPC attachment, Aurora
security-group ingress, private endpoints for Secrets Manager and Bedrock Runtime,
and IAM permissions for the Aurora secret and Bedrock embedding invocation.
`make agentcore-provision` resolves the `AgentCoreGatewayLambdaArn` stack output
and runs the pinned Node-based CLI:

```bash
npx -y @aws/agentcore@0.18.0 validate --directory agentcore
npx -y @aws/agentcore@0.18.0 deploy --target default --yes
```

See [`agentcore/README.md`](agentcore/README.md) for prerequisites and smoke
tests.

## Workshop Seed Data

The demo answers one canonical question — **"Why did Orion slip?"** — and every
number the UI shows (the cited answer, the six sources, the timeline, the diagnostics
funnel) is backed by real rows in the `ops` schema, not hardcoded in the frontend.
The `seed/` directory regenerates that dataset and ships it as a `pg_dump -Fc`
archive so a workshop bootstrap can restore it with **$0 in Bedrock spend**.

```bash
# Restore the prebuilt corpus into Aurora or local Postgres (idempotent):
DATABASE_URL=postgresql://localhost:55432/retrieval?sslmode=disable \
  make seed-load

# Or regenerate from source (seed authors — writes JSONL + manifest + dump):
make seed-jsonl        # JSONL + manifest only, no database needed
make seed-generate     # full rebuild, populates DB and writes the -Fc dump
```

`load.sh` restores the dump, then **rebuilds indexes after the data load** — the
HNSW graph (`m=16, ef_construction=64, vector_cosine_ops`) plus the GIN full-text
and `pg_trgm` fuzzy indexes. See [`seed/README.md`](seed/README.md) for the full
workflow and the flagged divergences from the original design mockups.

The shipped dump carries **real Cohere `embed-v4` (1024-d)** vectors, generated
once at build time and reused by every restore. Because the stored vectors live in
Cohere space, run the backend with `EMBED_PROVIDER=bedrock` so live `/v1/search`
embeds queries with the same model. (The canonical Orion answer is served from a
stored row, so it renders identically under either provider.)

## Optional Bedrock Model Defaults

The lab defaults to `EMBED_PROVIDER=bedrock` so live query embeddings share the
Cohere `embed-v4` space the shipped dump was built in. Set `EMBED_PROVIDER=hash`
for a fully offline run (deterministic embeddings, no Bedrock calls) — useful for
CI or air-gapped setup, though live-query relevance will differ from the seeded
vectors. When Bedrock is enabled, the repo expects these model IDs:

```text
BEDROCK_OPUS_MODEL=global.anthropic.claude-opus-4-8
BEDROCK_SONNET_MODEL=global.anthropic.claude-sonnet-5
BEDROCK_ROUTER_MODEL=global.anthropic.claude-sonnet-5
BEDROCK_REPORTING_MODEL=global.anthropic.claude-sonnet-5
BEDROCK_CHAT_MODEL=global.anthropic.claude-opus-4-8
BEDROCK_EMBEDDING_MODEL=us.cohere.embed-v4:0
```

## Search

```bash
curl -X POST http://localhost:8000/v1/search \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "Why is Project Orion delayed and what customer commitments are impacted?",
    "source_systems": ["slack", "jira", "confluence", "salesforce", "github"],
    "project_key": "ORION",
    "limit": 8
  }'
```

## Agent Answer

```bash
curl -X POST http://localhost:8000/v1/agent/answer \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "Why is Project Orion delayed, what did the team decide in Slack, and what customer commitments are impacted?",
    "limit": 8
  }'
```

## Repository Conventions

- Keep local configuration in `.env`; only `.env.example` is committed.
- Keep generated corpora under `data/generated/`; it is ignored by git.
- Keep live connector exports under `data/live/`; it is ignored by git.
- The canonical workshop corpus lives in `seed/` (generator + committed dump);
  restore it with `make seed-load`.
- Use `SECURITY_REVIEW.md` for review notes that should remain visible to maintainers.

## Security Review Notes

See [`SECURITY_REVIEW.md`](SECURITY_REVIEW.md). The package is intentionally review-friendly:

- No committed credentials.
- No real customer data.
- Workshop source data only.
- Optional connectors require explicit environment variables.
- Static connector logo assets are UI-only workshop visuals and contain no
  credentials or remote dependencies.
- No telemetry or analytics.
- No remote font or image dependencies in the React app.

For security issue notifications, see [`CONTRIBUTING.md`](CONTRIBUTING.md#security-issue-notifications).

## License

This library is licensed under the MIT-0 License. See the [`LICENSE`](LICENSE) file.
