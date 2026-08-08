# Aurora PostgreSQL deployment guide

## Prerequisites

- an Aurora PostgreSQL cluster/version that supports the required pgvector capabilities
- network access from the loader/benchmark client
- a database role able to create the required extensions, schemas, tables, and indexes
- enough temporary and persistent capacity for the catalog, embeddings, and HNSW build

Confirm the installed pgvector version rather than assuming it:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
SELECT extversion FROM pg_extension WHERE extname = 'vector';
```

## Recommended sequence

1. Create the cluster and database.
2. Run `sql/00_extensions.sql` and `sql/01_schema.sql`.
3. Load the three catalog shards declared in `data/full/manifest.json`.
4. Populate embeddings in batches.
5. Create relational, FTS, trigram, JSONB, and HNSW indexes.
6. Run `ANALYZE`.
7. Execute correctness/eval queries.
8. Run the measured HNSW harness.
9. Populate the UI only with measured or labeled projected values.

## Operational considerations

- HNSW builds are resource-intensive; isolate and observe the build phase.
- Keep embedding model and vector dimension in the deployment manifest.
- Batch updates and avoid repeatedly rebuilding the graph during initial ingestion.
- Treat inventory/freshness updates separately from immutable embedding text where possible.
- Monitor index growth, table bloat, autovacuum behavior, query plans, buffers, and filter selectivity.
- Use least-privilege application roles; workshop schema-owner credentials should not become runtime credentials.

## Technical references

- Aurora PostgreSQL vector-store preparation: `https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraPostgreSQL.VectorDB.html`
- pgvector HNSW and iterative scans: `https://github.com/pgvector/pgvector`
- PostgreSQL trigram extension: `https://www.postgresql.org/docs/current/pgtrgm.html`
