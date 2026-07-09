# Agentic Hybrid Retrieval with PostgreSQL and pgvector

This repository is a security-reviewable starter implementation for a re:Invent 2026 builders' session:

> **Build agentic hybrid retrieval with Amazon Aurora PostgreSQL**

For local development and the first builder-session path, the retrieval engine is **localhost PostgreSQL 18.4 with pgvector 0.8.2 or later**. The schema and query patterns are designed to carry forward to Aurora PostgreSQL after the local lab is working.

The product is an operational evidence retrieval layer over fragmented work systems such as Slack-like conversations, Jira issues, Confluence pages, Salesforce cases, GitHub pull requests, runbooks, and incident notes.

## Prerequisites

- Python 3.11 or later
- Node.js 20.19 or later for the frontend and MCP server
- Local PostgreSQL 18.4 with pgvector 0.8.2+, pg_trgm, btree_gin, pgcrypto, and pg_stat_statements
- Optional: Docker, if you prefer the Compose-based Postgres path
- AWS credentials only for optional Bedrock embeddings, Bedrock Agent integration, or later Aurora deployment

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

Install PostgreSQL and pgvector with Homebrew:

```bash
brew install postgresql@18 pgvector
```

The native bootstrap checks for PostgreSQL 18.4 or later and pgvector 0.8.2 or later. The local scripts prefer Homebrew's `postgresql@18` binaries at `/usr/local/opt/postgresql@18`.

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

The Compose image builds PostgreSQL `18.4` with pgvector `v0.8.2`.

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
