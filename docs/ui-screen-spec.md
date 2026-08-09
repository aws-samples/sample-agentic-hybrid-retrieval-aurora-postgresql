# UI route and component specification

## Shared shell

Desktop navigation exposes Discover, Shop, Collections, Mosaic Labs, and
Performance. Mobile navigation collapses behind one menu button. The shell
identifies Aurora PostgreSQL as the runtime without implying readiness when an
API request fails.

## `/` - Discover

Purpose: establish the catalog scenario and launch a domain-scoped or natural
language query.

Components:

- Mosaic product and workshop identity;
- full-bleed product-category image;
- search composer and four real sample queries;
- exact API-backed domain counts;
- consumer electronics, running and fitness, and home-office entry points;
- FTS/`pg_trgm`, Cohere Embed v4, RRF, and source-attribution trust markers.

API: `GET /api/catalog/summary`.

## `/catalog` - Shop

Purpose: inspect physical catalog rows before retrieval.

Components:

- domain, availability, and minimum-rating filters;
- featured, rating, price, and newest sorting;
- stable product cards with source-backed identity;
- pagination;
- compact mobile filter disclosure.

API: `GET /api/catalog/products`.

## `/search` - Collections

Purpose: run either one inspectable hybrid retrieval or a multi-tool,
citation-validated agent answer.

Retrieval view:

- applied query and hard filters;
- ranked product cards;
- FTS, trigram, vector, and rerank signals;
- candidate-pool counts, RRF configuration, and request latency.

Agent view:

- structured Summary, Recommendations, and Trade-offs;
- citations linked to the returned product cards;
- source-backed recommendations;
- collapsed Strands tool trace.

API: `POST /api/search` and `POST /api/agent/answer`.

## `/mosaic-labs` - Mosaic Labs

Purpose: connect the five golden missions to the evidence required at each
retrieval stage.

Components:

- mission contract for exact identity, typo recovery, semantic eligibility,
  rank provenance, and cited agentic research;
- explicit RRF and Cohere Rerank boundary;
- instructor-led stateless MCP portable-tool checkpoint;
- optional HNSW performance lane.

API: the mission manifest is source-controlled; linked retrieval runs use
`POST /api/search` and `GET /api/retrieval/runs/{run_id}`.

## `/products/:productId` - Product evidence

Purpose: inspect the source row behind a catalog or retrieval result.

Components:

- product title, image, description, price, rating, and availability;
- source URI and revision;
- structured category attributes;
- loaded review/evidence excerpts.

API: `GET /api/products/{product_id}`.

## `/labs/retrieval` - Retrieval Lab

Purpose: preserve one query while inspecting how each retrieval stage changes
candidate order.

Stages:

1. PostgreSQL full-text search;
2. `pg_trgm`;
3. pgvector semantic search;
4. weighted reciprocal rank fusion;
5. Cohere Rerank.

The page shows stage rank, raw stage score, candidate-arm agreement, hard
eligibility, run ID, diagnostics, and directly copyable canonical SQL.

API: `GET /api/retrieval/examples` and `POST /api/search`.

## `/labs/performance` - HNSW Performance Tuning

Purpose: teach HNSW as a measured workload rather than a checkbox.

Controls:

- catalog scale;
- `hnsw.ef_search`;
- filter selectivity;
- iterative scan mode.

Outputs:

- projected or measured boundary label;
- p95 latency, Recall@10, index size, and build duration;
- scale chart;
- selected benchmark envelope;
- copyable `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` query.

API: `GET /api/benchmarks/projection`. Projected output must never be labeled as
an Aurora measurement.

## Ownership boundary

The React application renders API contracts. It does not reproduce SQL
filtering, ranking, fusion, reranking, citation validation, or run persistence.
Those remain in the service and Aurora PostgreSQL.
