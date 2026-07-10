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
        ├── Agent tools
        ├── Optional Bedrock Agent action group
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

The lab can use localhost PostgreSQL or the CDK-provisioned Aurora PostgreSQL
18.3 cluster; both paths use the same schema and search functions. The committed
seed bundle stands in for the enterprise ingestion pipeline during the
time-boxed builder session.
