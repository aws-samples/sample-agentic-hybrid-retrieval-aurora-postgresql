# Architecture

```text
Slack-like threads / Jira / Confluence / Salesforce / GitHub / files
        │
        │  Source Ingest API, connector, AppFlow export, or workshop source bundle
        ▼
Normalization + chunking + citation extraction
        │
        ▼
PostgreSQL with pgvector
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

The connector is not the retrieval engine. Connectors feed source objects into PostgreSQL; PostgreSQL performs retrieval, ranking, diagnostics, and evidence storage. The lab can use localhost PostgreSQL or the CDK-provisioned Aurora PostgreSQL 18.3 cluster; both paths use the same schema and search functions.
