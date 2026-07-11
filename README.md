# Agentic Hybrid Retrieval with PostgreSQL and pgvector

[![License: MIT-0](https://img.shields.io/badge/License-MIT--0-yellow.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![PostgreSQL 18.3+](https://img.shields.io/badge/PostgreSQL-18.3%2B-336791.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![pgvector 0.8.1+](https://img.shields.io/badge/pgvector-0.8.1%2B-4B8BBE.svg)](https://github.com/pgvector/pgvector)
[![Aurora PostgreSQL](https://img.shields.io/badge/Amazon%20Aurora-PostgreSQL-FF9900.svg?logo=amazonaws&logoColor=white)](https://aws.amazon.com/rds/aurora/)
[![Amazon Bedrock](https://img.shields.io/badge/Amazon%20Bedrock-Cohere%20%26%20Claude-232F3E.svg?logo=amazonaws&logoColor=white)](https://aws.amazon.com/bedrock/)
[![Strands Agents](https://img.shields.io/badge/Strands-Agents-4B5563.svg)](https://strandsagents.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB.svg?logo=react&logoColor=black)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-8-646CFF.svg?logo=vite&logoColor=white)](https://vite.dev/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

This repository is a security-reviewable starter implementation for a re:Invent 2026 builders' session:

> **Build agentic hybrid retrieval with Amazon Aurora PostgreSQL**

For the builder-session path, the retrieval engine is **Amazon Aurora PostgreSQL 18.3 or later with pgvector 0.8.1 or later**. This repo contains the application, schema, seed data, and runtime helpers. AWS infrastructure is owned by the Workshop Studio repo and delivered as CloudFormation assets.

The product is an operational evidence retrieval layer over fragmented work systems such as Slack-like conversations, Jira issues, Confluence pages, Salesforce cases, GitHub pull requests, runbooks, and incident notes.

The agentic layer is framed around **Strands Agents**. Strands provides the lab harness and concrete `@tool` contract; Aurora PostgreSQL provides the durable evidence index; Amazon Bedrock provides embeddings and Claude model access where live model calls are enabled. The tool boundary is harness-agnostic: the same retrieval contract can be called from Strands, Claude Code, MCP clients, or another agent harness.

The default model routing uses the best model for the job: Sonnet 5 for planning, tool routing, and Claude Code discovery; Opus 4.8 for answer synthesis when live composition is enabled.

## Prerequisites

- Python 3.13 or later
- Node.js 20.19 or later for the frontend and MCP server
- A Workshop Studio-provisioned Aurora PostgreSQL cluster in `us-east-1`
- AWS credentials that can read the workshop stack outputs and Secrets Manager database secret
- Bedrock model access for live query embeddings when `EMBED_PROVIDER=bedrock`

## What participants build

Participants build a lightweight retrieval system that can answer questions like:

> Why did Orion slip, and which customer commitments are at risk?

The system:

1. Ingests operational source objects.
2. Normalizes records into a PostgreSQL schema.
3. Chunks long text.
4. Generates embeddings.
5. Stores source links and citations.
6. Runs PostgreSQL full-text search, pgvector semantic similarity, SQL filters, metadata filters, time-window filters, and pg_trgm fuzzy matching.
7. Combines retrieval sets with Reciprocal Rank Fusion.
8. Returns cited answers through Strands-style agent-callable tools.
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
├── lambda_mcp/                 # Lambda MCP adapter for Strands tool packaging
├── mcp-server/                 # Optional MCP wrapper around the retrieval API
├── seed/                       # Canonical Orion corpus generator + pg_dump/restore
├── mockups/                    # Static design prototype reference
└── docs/                       # Session plan, architecture, security notes, stretch labs
```

## Infrastructure Boundary

This source repo does not provision AWS resources. The Workshop Studio repo owns:

- `static/hybrid-retrieval-main.yml` as the root CloudFormation template
- `assets/hybrid-retrieval-*.yml` as nested CloudFormation templates
- the packaged source archive that Workshop Studio uploads to the assets S3 bucket
- the Code Editor, Aurora PostgreSQL, VPC, IAM, and bootstrap workflow

Keep application code, SQL, seed data, connector scaffolds, and local runtime helpers here. Put infrastructure templates and deployment packaging in the Workshop Studio repo.

## Quick Start: Workshop Aurora + API + UI

Set up Python dependencies:

```bash
make install
cp .env.example .env
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
```

When Workshop Studio has deployed the lab, configure this checkout from the workshop stack outputs:

```bash
make aurora-local-env
make aurora-verify
make seed-load
```

Run the API:

```bash
make api
```

Run the frontend in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

`make aurora-local-env` resolves the stack outputs, reads the database secret
from Secrets Manager, writes ignored local `.env` files for the backend and
frontend, and checks whether the Aurora endpoint is reachable from the local
machine. The files are intentionally not committed. If the network check says
Aurora is not reachable, run from Code Editor or another environment inside the
workshop VPC.

## Workshop Seed Data

The demo answers one canonical question — **"Why did Orion slip?"** — and every
number the UI shows (the cited answer, the six sources, the timeline, the diagnostics
funnel) is backed by real rows in the `ops` schema, not hardcoded in the frontend.
The `seed/` directory regenerates that dataset and ships it as a `pg_dump -Fc`
archive so a workshop bootstrap can restore it with **$0 in Bedrock spend**.

```bash
# Restore the prebuilt corpus into the configured Aurora database (idempotent):
make seed-load

# Or regenerate from source (seed authors - writes JSONL + manifest + dump):
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

The visible result-card score is not a raw Cohere similarity score. Cohere
contributes the semantic vector signal; `ops.hybrid_search` combines vector,
full-text, fuzzy, metadata, recency, and RRF signals into the final SQL score.

## Bedrock Model Routing

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

`/v1/agent/answer` includes an `agent` metadata object so the app and lab can show the live routing:

- `planning_and_tool_routing`: Sonnet 5
- `answer_synthesis`: Opus 4.8
- `claude_code_harness`: Sonnet 5

The canonical workshop answer is replayed from Aurora for stable citations and diagnostics; live composition paths use the configured synthesis model.

## Search

```bash
curl -X POST http://localhost:8000/v1/search \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "Why did Orion slip, and which customer commitments are at risk?",
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
    "question": "Why did Orion slip, and which customer commitments are at risk?",
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
