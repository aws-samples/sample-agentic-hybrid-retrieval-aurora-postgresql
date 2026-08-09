# Package manifest

## SQL

- `00_extensions.sql` — pgvector, `pg_trgm`, `unaccent`, and `pgcrypto`
- `01_schemas_and_types.sql` — schemas, enums, and trigger helper
- `02_reference_data.sql` — brand, category, attribute definitions, model registry
- `03_catalog.sql` — product, offer, and merchandising tables
- `04_media.sql` — media assets, roles, crops, and mark zones
- `05_evidence.sql` — evidence text, FTS, trigram, and evidence vectors
- `06_retrieval_projection.sql` — denormalized product search projection and refresh procedure
- `07_indexes.sql` — relational, JSONB, FTS, and trigram indexes
- `08_indexes_concurrent.sql` — product and evidence HNSW indexes
- `09_search_functions.sql` — filters, FTS, typo recovery, semantic search, RRF, evidence search
- `10_agent_and_rerank.sql` — agent tool contracts/audit and reranker provenance
- `11_evaluation.sql` — queries, judgments, runs, results, and metrics
- `12_telemetry.sql` — searches, ranked results, interactions, and plans
- `13_benchmark.sql` — scale profiles, runs, measurements, and physical vector table
- `14_views.sql` — Shop, flagship, media coverage, and embedding backlog views
- `15_load_premium_cohort.sql` — loads the 120-product premium assignment
- `16_seed_tool_contracts.sql` — read-only agent tool schemas
- `17_load_normalized_catalog.sql` — bulk-loads transformed 500K catalog files
- `99_smoke_test.sql` — post-install verification
- `install.sql` — base installation order, excluding concurrent HNSW builds

## Contracts

- Pydantic v2 models for product ingest, commerce, media, evidence, search, comparison, and tool events
- 11 generated JSON Schema files
- DBML source and Mermaid ERD

## Included data

- 120-product premium cohort grounded in the existing 500K catalog
- 6 flagship mappings
- 30 retrieval anchors
- 10 complete Shop pages of 12 products
- premium media asset queue
- six example eval queries
- source rows for the six flagships

## Utilities

- vector-dimension renderer
- existing-catalog transformer
- JSON Schema exporter
- package validator
- checksum builder
- eight offline tests
