# Build report

Package: `mosaic-data-models-aurora`
Version: `1.0.0`

## Validated

- 120 unique premium product assignments
- exact 48 / 36 / 36 domain distribution
- six flagships
- thirty retrieval anchors, ten per domain
- ten complete Shop pages with twelve products each
- eleven valid JSON Schema contracts
- Pydantic model import and default validation
- twenty ordered SQL files
- base installer excludes concurrent HNSW index creation
- explicit FTS, `pg_trgm`, semantic, RRF, rerank, and evidence representations
- no stale legacy branding
- eight offline tests passing
- legacy 500K transformer smoke-tested against 1,000 sample rows
- alternate 1,024-dimensional SQL rendering smoke-tested

## Environment boundary

No live Aurora PostgreSQL cluster was attached to this build environment. SQL was statically validated and contract-tested, but measured database execution plans, HNSW build times, latency, and Recall@10 must be captured in the target Aurora environment.
