# Implementation status

## Release baseline

- 500,000-product Mosaic catalog on Aurora PostgreSQL 18.3 with 1,024-dimension
  Cohere Embed v4 vectors;
- SQL-owned full-text, `pg_trgm`, HNSW, filtering, unweighted served RRF,
  weighted Advanced comparison, and retrieval-diagnostics paths;
- Cohere Rerank 3.5 with PostgreSQL provenance retained before and after rerank,
  plus explicit exact-SKU preservation so model reranking cannot displace a
  catalog-identifier lookup;
- typed FastAPI, Strands product-discovery tools, cited synthesis, and retrieval
  run inspection;
- responsive React application with visible Discover, Shop, and Playground
  surfaces; product detail, retrieval inspection, and HNSW tuning remain
  contextual or optional;
- three required labs, two embedded Lab 1 checkpoints, and three optional
  Advanced Labs; the HNSW check is governed by
  `data/evals/mosaic_labs_missions.json`;
- isolated MCP 2.0 adapter exposing the canonical read-only retrieval tools; and
- snapshot-safe schema upgrades plus release gates that require the live Aurora
  integration suite.

Workshop Studio clones the source repository at its immutable `SourceRevision`.
There is intentionally no source archive producer: an archive would duplicate
the application delivery path and can drift from the pinned revision.

The serving HNSW path is implemented. HNSW retrieval itself is not deferred;
the remaining work below concerns certification and the optional performance
exercise, not whether semantic retrieval exists.

## Deliberately deferred

- release-certified HNSW benchmark output contract and advanced performance
  lane;
- behavioral assertions `rrf_recomputes` and `rerank_off_invariant`;
- per-token trigram expansion and the measured 500K trigram latency issue;
- broader media fallback coverage; and
- corpus-wide evaluation beyond the curated canonical release set.

Hash embeddings are development-only and cannot support workshop relevance
claims. Simulated scale output is not Aurora benchmark evidence.

### Return-shape checking covers the packaged skill, not every tool

Two different gates run over the tool registry, and they prove different things.
`capability_parity_receipt()` proves one capability declares the same semantic
payload on every surface it appears on. `test_returned_payload_matches_the_declared_contract`
proves the declaration is true of what the code actually returns.

The second gate is scoped to the four capabilities the packaged skill exposes:
`open_retrieval`, `get_product_evidence`, `compare_products`, and
`explain_retrieval`. `synthesize_cited_answer` is orchestration rather than part
of the skill, so its declaration is checked for cross-surface consistency but not
against its implementation. An exhaustiveness test asserts the gate's scope equals
the skill surface, so the list cannot silently shrink.

Both gates compare field sets rather than the internal shape of each field's
value. The agent surface's `results` entries are `_product_for_model`
projections, not `ProductSummary` rows, and neither gate claims otherwise.
