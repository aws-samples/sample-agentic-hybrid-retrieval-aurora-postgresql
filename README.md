# Agentic Hybrid Retrieval with PostgreSQL and pgvector

This repository is a security-reviewable starter implementation for a re:Invent 2026 builders' session:

> **Build agentic hybrid retrieval with Amazon Aurora PostgreSQL**

For local development and the first builder-session path, the retrieval engine is **PostgreSQL 18.3 or later with pgvector 0.8.1 or later**. The same schema can run on localhost PostgreSQL or on a net-new Aurora PostgreSQL 18.3 cluster provisioned by the CDK stack in this repo.

The product is an operational evidence retrieval layer over fragmented work systems such as Slack-like conversations, Jira issues, Confluence pages, Salesforce cases, GitHub pull requests, runbooks, and incident notes.

## Prerequisites

- Python 3.11 or later
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

## Repo Layout

```text
.
├── backend/                    # FastAPI API, ingestion pipeline, search, agent tools
├── frontend/                   # Vite + React UI
├── sql/                        # PostgreSQL schema, indexes, functions, diagnostics
├── data/                       # Workshop-safe source bundle
├── connectors/                 # Optional connector scaffolds and normalizers
├── bedrock-agent/              # Optional Amazon Bedrock Agent action group wrapper
├── mcp-server/                 # Optional MCP wrapper around the retrieval API
├── infra/                      # CDK skeleton and local Postgres Dockerfile
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
python backend/scripts/load_jsonl_to_postgres.py --input data/sample/source_objects.jsonl --truncate
make embed
```

The Compose image builds PostgreSQL `18.3` with pgvector `v0.8.2`.

## Aurora PostgreSQL 18.3 Option

The CDK stack provisions a net-new Aurora PostgreSQL 18.3 Serverless v2 cluster, the source landing buckets, a Secrets Manager database secret, and the placeholder Bedrock Agent action Lambda.

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
python backend/scripts/load_jsonl_to_postgres.py --input data/sample/source_objects.jsonl --truncate
make embed
```

`make aurora-verify` creates or updates the required extensions and schema, then checks for PostgreSQL 18.3+ and pgvector 0.8.1+.

## Optional Bedrock Model Defaults

The local lab uses deterministic hash embeddings unless `EMBED_PROVIDER=bedrock` is set. When Bedrock is enabled, the repo expects these model IDs:

```text
BEDROCK_OPUS_MODEL=global.anthropic.claude-opus-4-8
BEDROCK_SONNET_MODEL=global.anthropic.claude-sonnet-5
BEDROCK_ROUTER_MODEL=global.anthropic.claude-sonnet-5
BEDROCK_REPORTING_MODEL=global.anthropic.claude-sonnet-5
BEDROCK_CHAT_MODEL=global.anthropic.claude-opus-4-8
BEDROCK_EMBEDDING_MODEL=us.cohere.embed-v4:0
BEDROCK_RERANK_MODEL=cohere.rerank-v3-5:0
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
- Keep workshop-safe seed data under `data/sample/`.
- Use `SECURITY_REVIEW.md` for review notes that should remain visible to maintainers.

## Security Review Notes

See [`SECURITY_REVIEW.md`](SECURITY_REVIEW.md). The package is intentionally review-friendly:

- No committed credentials.
- No real customer data.
- Workshop source data only.
- Optional connectors require explicit environment variables.
- No vendor logo assets included.
- No telemetry or analytics.
- No remote font or image dependencies in the React app.

For security issue notifications, see [`CONTRIBUTING.md`](CONTRIBUTING.md#security-issue-notifications).

## License

This library is licensed under the MIT-0 License. See the [`LICENSE`](LICENSE) file.
