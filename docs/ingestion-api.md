# Evidence Pipeline API

The ingestion API turns source objects into PostgreSQL-ready hybrid search evidence.

Your systems keep the work; Aurora makes the evidence comparable. The API stores
an approved, rebuildable retrieval projection, not a full copy of every source
system. Source systems remain authoritative for workflow state, permissions,
ownership, comments, and mutations. Aurora stores the fields needed to rank,
join, cite, evaluate, and reproduce retrieval across them.

## Endpoints

```text
POST /v1/sources
POST /v1/ingest/objects
GET  /v1/jobs/{job_id}
GET  /v1/sources/{source_id}/status
POST /v1/search
POST /v1/agent/answer
```

## Ingestion contract

```json
{
  "source_name": "orion-demo-bundle",
  "source_system": "source_bundle",
  "sync_mode": "full",
  "sync_cursor": {"revision": "abc123"},
  "objects": [
    {
      "source_system": "jira",
      "source_type": "issue",
      "external_id": "ORION-1473",
      "title": "Read replica lag causing delayed cutover",
      "url": "https://example.atlassian.net/browse/ORION-1473",
      "status": "In Progress",
      "priority": "P1",
      "project_key": "ORION",
      "component": "PostgreSQL",
      "updated_at": "2026-05-02T14:52:00Z",
      "body": "Read replica lag observed during peak load is delaying cutover...",
      "metadata": {"labels": ["database", "replication"]},
      "acl": {"visibility": "workshop"}
    }
  ]
}
```

## Pipeline steps

1. Normalize source records.
2. Store source metadata and ACLs.
3. Chunk long content.
4. Create citations.
5. Generate embeddings.
6. Index FTS, vectors, trigrams, metadata.
7. Keep the source `indexing` while embeddings are pending, then mark it
   `ready` for hybrid search.

`sync_mode: "upsert"` applies only records present in the request. `sync_mode:
"full"` also tombstones active records for that connector that are absent from
the authoritative snapshot. The response separates inserted, changed,
unchanged, deactivated, and embedding-pending counts, plus lexical and semantic
readiness.

## Store versus call live

Materialize into Aurora when the data is needed for low-latency cross-source
search, ranking, filtering, citation joins, evaluation, or repeatable answer
diagnostics. Typical fields are source IDs, URLs, titles, text excerpts, bodies,
metadata, ACL markers, relationships, sync cursors, and provenance.

The `final_score` returned from `/v1/search` is an Aurora SQL composite, not a
raw embedding-model score. Cohere `embed-v4` supplies the query embedding for
the semantic arm, while PostgreSQL combines semantic, full-text, fuzzy,
metadata, recency, and RRF signals.

Call the source system live through a connector or MCP tool when the workflow
needs the latest mutable state, a write action, a permission check that cannot
be represented in the indexed ACL metadata, or source-specific detail that is
too large or volatile to index.

The workshop seed bundle represents the output of this pipeline. A production
deployment replaces that bundle with scheduled exports, webhooks, AppFlow/Glue
jobs, custom connectors, or MCP-backed live tools depending on each source.

PostgreSQL maintains GIN, trigram, generated full-text, and HNSW indexes during
ordinary DML. Connector updates do not run `REINDEX`; large initial loads build
indexes after bulk loading, while changed HNSW parameters require a controlled
replacement index. See `connector-lifecycle.md`.
