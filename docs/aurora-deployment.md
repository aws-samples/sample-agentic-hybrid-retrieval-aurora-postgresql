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

1. Create the cluster and database. There is no local alternative; see
   `ARTIFACTS.md`.
2. `make db-install` — schemas, tables, functions, and non-concurrent indexes
   (`db/sql/install.sql`).
3. `make db-prepare-mosaic` then `make db-load-mosaic` — normalize and load the
   three catalog shards declared in `data/full/manifest.json`.
4. `make db-embed`, or `make db-import-embeddings` to restore the cached vectors
   instead of paying for re-embedding.
5. `make db-index-concurrent` — the HNSW index, which cannot be built inside a
   transaction block and is pointless before embeddings exist. If a concurrent
   build was interrupted, run `make db-drop-invalid-indexes` first; the
   bootstrap's `index_creation` phase does this automatically. The optional
   halfvec and binary indexes for the Vector index at scale lens are a separate
   `make db-index-quantized`.
6. `make db-load-cohort` — the 120 premium products with real photography.
7. `make db-smoke` — correctness queries.
8. `make validate-missions`, `make validate-config`, `make validate-functions` —
   the three gates. Set `MISSION_GATE_REQUIRE_DB=1` and
   `FUNCTION_CENSUS_REQUIRE_DB=1` in CI so a missing DSN is loud.
9. `scripts/benchmark_hnsw.py` for the measured harness.
10. Populate the UI only with measured or labeled projected values.

`make db-bootstrap-cached` runs steps 2 through 7 in order.

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
