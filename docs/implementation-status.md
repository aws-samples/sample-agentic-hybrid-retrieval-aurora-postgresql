# Implementation status

## Release baseline

- 500,000-product Mosaic catalog on Aurora PostgreSQL 18.3 with 1,024-dimension
  Cohere Embed v4 vectors;
- SQL-owned full-text, `pg_trgm`, HNSW, filtering, RRF, weighted-comparison, and
  retrieval-diagnostics paths;
- Cohere Rerank 3.5 with PostgreSQL provenance retained before and after rerank;
- typed FastAPI, Strands product-discovery tools, cited synthesis, and retrieval
  run inspection;
- responsive React application with Discover, Catalog, Search, Product Detail,
  Mosaic Labs, Retrieval Lab, and Performance surfaces;
- three required labs, two embedded Lab 1 checkpoints, and three optional
  Advanced Labs; the HNSW check is governed by
  `data/evals/mosaic_labs_missions.json`;
- isolated MCP 2.0 adapter exposing the canonical read-only retrieval tools; and
- snapshot-safe schema upgrades plus release gates that require the live Aurora
  integration suite.

## Deliberately deferred

- measured HNSW output contract and advanced performance lane;
- behavioral assertions `rrf_recomputes` and `rerank_off_invariant`;
- per-token trigram expansion and the measured 500K trigram latency issue;
- broader media fallback coverage; and
- measured corpus-wide evaluation results for the current Aurora configuration.

Hash embeddings are development-only and cannot support workshop relevance
claims. Simulated scale output is not Aurora benchmark evidence.
