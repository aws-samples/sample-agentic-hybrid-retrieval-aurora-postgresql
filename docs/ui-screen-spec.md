# UI route and component specification

## Shared shell

Participant-facing navigation exposes exactly Discover, Shop, and Mosaic Labs.
Product detail, retrieval inspection, and HNSW tuning are contextual deep
routes, not competing destinations. Mobile navigation collapses behind one menu
button.

## `/` - Discover

Purpose: establish the catalog scenario and launch a domain-scoped or natural
language query.

Components:

- Mosaic product and workshop identity;
- full-bleed product image;
- search composer and four real sample queries;
- compact `Retrieve -> Rank -> Reason` workshop rail.

Every search and preset leaves Discover and enters Shop. Discover never becomes
a second results surface.

## `/catalog` - Shop

Purpose: use Mosaic as one integrated product-discovery experience.

Components:

- domain, availability, and minimum-rating filters;
- featured, rating, price, and newest sorting;
- direct hybrid search in the product grid;
- an inline Ask Mosaic composer that becomes a contextual sidecar after submit;
- stable product cards with complete 3:2 premium catalog photography;
- inline agent shortlist cards, evidence citations, rank explanation, and tool
  receipts;
- pagination;
- compact mobile filter disclosure.

API: `GET /api/catalog/products`, `POST /api/search`, and
`POST /api/agent/answer/stream`.

## `/search` - Lab 3 deep route

Purpose: preserve existing Lab 3 and bookmarked agent-inspection links. This
route is not present in participant-facing navigation; the primary shopper
experience is Ask Mosaic inside Shop.

Retrieval view:

- applied query and hard filters;
- ranked product cards;
- FTS, trigram, vector, and rerank signals;
- candidate-pool counts, RRF configuration, and request latency.

API: `POST /api/search` and `POST /api/agent/answer`.

## `/mosaic-labs` - Mosaic Labs

Purpose: make the three-lab `Retrieve -> Rank -> Reason` progression and its
evidence requirements visible.

Components:

- stage switcher for Retrieve, Rank, Reason, and optional Advanced work;
- exactly three required Broken -> Fix -> Prove lab cards;
- all eight participant runs, grouped inside the three labs;
- candidate-source, ranking-movement, and agent-tool signature visuals;
- optional HNSW performance lab.

API: the lab manifest is source-controlled; linked retrieval runs use
`POST /api/search` and `GET /api/retrieval/events/{search_event_id}`.

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
4. reciprocal rank fusion;
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

The React application renders API and lab contracts. It does not reproduce SQL
filtering, ranking, fusion, reranking, citation validation, or run persistence.
Those remain in the service and Aurora PostgreSQL. Ask Mosaic displays tool
receipts and evidence; it never exposes hidden model chain-of-thought.
