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
- `follow_evidence_links`
- `synthesize_cited_answer`

Those functions are Strands `@tool`s in the FastAPI app.
`lambda_mcp/handler.py` remains a directly deployable adapter over the same
implementations. For the one-hour managed proof, Workshop Studio provisions an
`AWS_IAM`-authorized AgentCore Gateway and a stateless Lambda target over two
stable FastAPI operations:

- `POST /v1/search` as the `search_evidence` MCP tool
- `POST /v1/agent/answer` as the `answer_with_citations` MCP tool

The Gateway target does not own ranking or synthesis. It translates MCP
`tools/call` into the private API, which keeps Aurora retrieval, Cohere rerank,
run persistence, and cited-answer behavior in one implementation. The
SigV4 client in `scripts/invoke_agentcore_gateway.py` proves that managed path.

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
on the Strands-oriented app, portable retrieval API, SQL, seed data, Gateway
client, Lambda MCP adapter source, and optional MCP wrapper.
