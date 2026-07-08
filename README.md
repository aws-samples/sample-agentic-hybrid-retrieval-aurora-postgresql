# Sample Agentic Hybrid Retrieval with Amazon Aurora PostgreSQL

This repository is a security-reviewable starter implementation for a re:Invent builders' session:

> **Build agentic hybrid retrieval with Amazon Aurora PostgreSQL**

The sample application builds an operational evidence retrieval layer over fragmented work systems such as Slack-like conversations, Jira issues, Confluence pages, Salesforce cases, GitHub pull requests, runbooks, and incident notes.

The repo intentionally uses **synthetic data by default**. It contains optional connector scaffolds, but no real SaaS credentials, no vendor logo assets, no customer data, and no production secrets.

## Prerequisites

- Python 3.11 or later
- Aurora PostgreSQL or PostgreSQL with the required extensions from [`sql/00_extensions.sql`](sql/00_extensions.sql)
- Node.js 20.19 or later for the optional frontend and MCP server
- AWS credentials only for optional Bedrock embeddings, Amazon Bedrock Agent integration, or CDK deployment

## What participants build

Participants build a lightweight retrieval system that can answer questions like:

> Why is Project Orion delayed, what did the team decide in Slack, and what customer commitments are impacted?

The system:

1. Ingests operational source objects.
2. Normalizes records into an Aurora PostgreSQL schema.
3. Chunks long text.
4. Generates embeddings.
5. Stores source links and citations.
6. Runs PostgreSQL full-text search, pgvector semantic similarity, SQL filters, metadata filters, time-window filters, and pg_trgm fuzzy matching.
7. Combines retrieval sets with Reciprocal Rank Fusion.
8. Returns cited answers through agent-callable tools.
9. Stores retrieval diagnostics for evaluation and explainability.

## Repo layout

```text
.
├── backend/                    # FastAPI API, ingestion pipeline, search, agent tools
├── frontend/                   # Vite + React UI scaffold
├── sql/                        # Aurora PostgreSQL schema, indexes, functions, diagnostics
├── data/                       # Small synthetic sample data
├── connectors/                 # Optional connector scaffolds and normalizers
├── bedrock-agent/              # Optional Amazon Bedrock Agent action group wrapper
├── mcp-server/                 # Optional MCP wrapper around the retrieval API
├── infra/                      # CDK skeleton for AWS resources
├── mockups/                    # Static HTML prototype based on the latest design
└── docs/                       # Session plan, architecture, security notes, stretch labs
```

## Quick Start: Local API + Aurora

Set up Python dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
```

Edit `.env` and set `DATABASE_URL` to your Aurora PostgreSQL connection string. Do not commit `.env`.

Create schema and search functions:

```bash
python backend/scripts/run_sql.py --files \
  sql/00_extensions.sql \
  sql/01_schema.sql \
  sql/02_indexes.sql \
  sql/03_search_functions.sql \
  sql/04_diagnostics.sql \
  sql/05_evaluation.sql
```

Generate a small synthetic corpus:

```bash
python backend/scripts/generate_synthetic_operational_data.py \
  --objects 2000 \
  --out data/generated \
  --seed 42
```

Ingest it through the API path:

```bash
python backend/scripts/load_jsonl_to_aurora.py --input data/generated/source_objects.jsonl --truncate
python backend/scripts/embed_chunks.py --provider hash --batch-size 500
```

Run the API:

```bash
uvicorn backend.app.main:app --reload --port 8000
```

Search:

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

Agent answer:

```bash
curl -X POST http://localhost:8000/v1/agent/answer \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "Why is Project Orion delayed, what did the team decide in Slack, and what customer commitments are impacted?",
    "limit": 8
  }'
```

## Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

The frontend defaults to mock data if the API is unavailable.

## Optional AWS CDK Skeleton

The CDK app in [`infra/cdk`](infra/cdk) creates starter resources for the workshop sample, including S3 buckets, a Secrets Manager secret, and the optional Bedrock Agent action Lambda.

```bash
cd infra/cdk
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cdk synth
cdk deploy --parameters RetrievalApiUrl=<retrieval-api-url>
```

The `RetrievalApiUrl` parameter is optional. Leave it blank until the retrieval API has been deployed.

## Repository Conventions

- Keep local configuration in `.env`; only `.env.example` is committed.
- Keep generated corpora under `data/generated/`; it is ignored by git.
- Keep live connector exports under `data/live/`; it is ignored by git.
- Keep workshop-safe synthetic seed data under `data/sample/`.
- Use `SECURITY_REVIEW.md` for review notes that should remain visible to maintainers.

## Security Review Notes

See [`SECURITY_REVIEW.md`](SECURITY_REVIEW.md). The package is intentionally review-friendly:

- No committed credentials.
- No real customer data.
- Synthetic workshop data only.
- Optional connectors require explicit environment variables.
- No vendor logo assets included.
- No telemetry or analytics.
- No remote font or image dependencies in the React app.

For security issue notifications, see [`CONTRIBUTING.md`](CONTRIBUTING.md#security-issue-notifications).

## License

This library is licensed under the MIT-0 License. See the [`LICENSE`](LICENSE) file.
