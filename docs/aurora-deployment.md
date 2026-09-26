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

1. Create a fresh Aurora cluster and database; see `ARTIFACTS.md`.
2. Download and verify the three pinned catalog parts and the two real-catalog
   vocabulary files before database writes.
3. Run `make db-bootstrap-schema` to install the shared schemas and lab tables.
4. Run `scripts/real_catalog_cache.py restore` to load the 553,911 real source
   products, saved Cohere embeddings and real evidence, and build the search indexes.
5. Select the dataset from `db/config/real-catalog-cache.json` through
   `MOSAIC_CATALOG_DATASET`, then run `make db-verify-bootstrap`.
6. Run `make validate-missions validate-evals validate-config validate-functions`.
   Require the database in CI with `MISSION_GATE_REQUIRE_DB=1` and
   `FUNCTION_CENSUS_REQUIRE_DB=1`.

Do not load the historical synthetic products, review corpus, premium cohort or
vocabulary. The Scale & HNSW instrument reads the served catalog: run
`make select-hnsw-anchors` once per catalog (the committed anchor set already
names `reviews-2023-v2`) and `make db-seed-exact-neighbors` on the cluster so
the neighbourhood and probe routes have exact ground truth.

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
