# Architecture

```text
Slack-like threads / Jira / Confluence / Salesforce / GitHub / files
        │
        │  Connector, webhook, export job, AppFlow/Glue, or workshop source bundle
        ▼
Normalization + chunking + citation extraction
        │
        ▼
Aurora PostgreSQL retrieval index
  - source_objects
  - object_chunks
  - object_links
  - citations
  - metadata JSONB
  - ACL JSONB
  - tsvector full-text columns
  - pgvector embeddings
  - pg_trgm fuzzy indexes
  - retrieval_runs
  - retrieval_candidates
        │
        ├── Search API
        ├── Strands Agent tools
        ├── Lambda MCP adapter (deployment asset)
        ├── Optional MCP wrapper
        └── React frontend
```

The source systems remain authoritative. Aurora stores the searchable evidence
projection needed for retrieval: normalized source objects, chunks, metadata,
ACL markers, citations, relationships, embeddings, diagnostics, and evaluation
rows. It is not a wholesale replacement for Jira, Slack, Confluence, Salesforce,
GitHub, or other systems of record.

Connectors and MCP tools have different jobs:

- Connectors, exports, webhooks, and scheduled jobs keep the Aurora evidence
  index fresh.
- MCP tools can expose the retrieval API to agents and can also perform live
  source-system lookups or actions when the answer needs current state or a
  mutation.
- The UI reads from the retrieval API because cross-source ranking, citation
  joins, diagnostics, and evaluation require a persisted index.

The agentic layer is organized around **Strands Agents** for the lab because the
local `@tool` contract is explicit and inspectable. The architecture itself is
harness-agnostic: Strands, Claude Code, MCP clients, or another orchestrator can
call the same retrieval boundary. Amazon Bedrock remains the model provider for
embeddings and Claude access; it is not the agent framework.

Model routing follows a best-model-for-the-job pattern:

- Sonnet 5 for planning, source selection, and tool routing.
- Opus 4.8 for answer synthesis when live composition is enabled.
- Sonnet 5 for Claude Code discovery questions and optional exercises.

The local tool contract is:

- `infer_sources`
- `search_evidence`
- `synthesize_cited_answer`

Those functions are Strands `@tool`s in the FastAPI app. The optional deployment
path wraps the same implementations in `lambda_mcp/handler.py` so Workshop
Studio can package them as Lambda MCP tools and front them with AgentCore
Gateway.

The lab uses the Workshop Studio-provisioned Aurora PostgreSQL 18.3 cluster. The
committed seed bundle stands in for the enterprise ingestion pipeline during the
time-boxed builder session.

## Infrastructure Boundary

This repo is application source only. AWS infrastructure lives in the Workshop
Studio repo:

- `static/hybrid-retrieval-main.yml` is the root CloudFormation template.
- `assets/hybrid-retrieval-*.yml` are nested CloudFormation templates.
- packaged source archives are uploaded through Workshop Studio assets.

Add or change infrastructure in the Workshop Studio repo so the participant
environment stays reproducible from one source of truth. Keep this repo focused
on the Strands-oriented app, retrieval API, SQL, seed data, Lambda MCP adapter
source, and optional MCP wrapper.
