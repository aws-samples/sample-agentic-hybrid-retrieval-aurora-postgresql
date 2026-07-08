# Architecture

```text
Slack-like threads / Jira / Confluence / Salesforce / GitHub / files
        │
        │  Source Ingest API, connector, AppFlow export, or synthetic bundle
        ▼
Normalization + chunking + citation extraction
        │
        ▼
Amazon Aurora PostgreSQL
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

The connector is not the retrieval engine. Connectors feed source objects into Aurora PostgreSQL; Aurora performs retrieval, ranking, diagnostics, and evidence storage.
