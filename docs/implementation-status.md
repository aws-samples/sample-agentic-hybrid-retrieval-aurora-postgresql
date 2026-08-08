# Implementation Status

## Baseline Complete

- established the catalog-retrieval workshop narrative and product discovery
  experience;
- retained the aws-samples license and contribution governance;
- imported the catalog narrative, retrieval stages, SQL skeleton, and eval assets;
- corrected generated SKU and timestamp invariants;
- aligned all evaluation filters with the SQL contract;
- split the 500K catalog into GitHub-safe domain shards;
- added full-catalog, filter-target, shard, and contract validation.
- integrated Cohere Embed v4 at 1,024 dimensions for indexing and queries;
- integrated Cohere Rerank 3.5 without replacing PostgreSQL RRF provenance;
- added the typed FastAPI and Strands product-discovery boundaries.
- added an isolated MCP 2.0 service with typed, read-only product discovery
  tools and stateless `2026-07-28` discovery.
- added the responsive React Catalog Studio application with discover, catalog,
  search/agent, product evidence, retrieval lab, and HNSW tuning routes;
- validated every React route at desktop and mobile sizes against the real 5K
  API database, including a live Cohere rerank and cited Strands agent run;
- added an audit-clean frontend production build and root Make targets.

## Next Phases

- broaden database-backed retrieval, SQL, API, and automated browser tests;
- add deployment, bootstrap, and workshop reset automation;
- expand the screened category fallback set with publication-safe product
  merchandising assets;
- measure Aurora HNSW and end-to-end retrieval performance.
- assess RLS and `pg_columnmask` when tenant-scoped access or column-level
  disclosure becomes a workshop requirement.
- integrate the catalog product-discovery agent with AgentCore as its managed
  runtime boundary.

Hash embeddings are development-only and cannot support workshop relevance
claims. Simulated scale output is not Aurora benchmark evidence.
