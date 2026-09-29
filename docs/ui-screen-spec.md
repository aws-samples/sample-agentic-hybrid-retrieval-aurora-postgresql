# UI route and component specification

## Shared shell

Participant-facing navigation exposes exactly Shop and Playground.
Product detail, retrieval inspection, and HNSW tuning are contextual deep
routes, not competing destinations. Mobile navigation collapses behind one menu
button.

## `/` and `/discover`

`/` opens Shop at `/catalog`. `/discover`, the address of the retired Discover
page, redirects to `/catalog#alex-profile`, Alex's brief on the Shop landing.

## `/catalog` - Shop

Purpose: establish Alex's scenario and use Mosaic as one integrated
product-discovery experience.

Landing, before a query or an Ask Mosaic shortlist:

- centred headline, search composer, catalog scope line, and one line of
  example searches grouped as Keywords, Typo, and Intent;
- Meet Alex: the five-step workspace walkthrough beside Alex's profile
  (`#alex-profile`), with links to his three categories;
- three full-width bands, one per need, each linking to its category and to
  its category-scoped search from the mission manifest;
- the Ask Mosaic invitation as the closing band, then the note that Alex is
  fictional and the workspace imagery is AI-generated;
- the workspace edit grid below the story.

With a query the story is not rendered. The headline stays the page's h1 for
assistive technology only, and `Results for ...` is the display line. Ranked
results read as an editorial list: the first in the final order as a feature,
the rest as rows with their position at the end. Browsing keeps the grid.

Components:

- domain, availability, and minimum-rating filters;
- featured, rating, price, and newest sorting;
- direct hybrid search in the product grid;
- an Ask Mosaic sidecar that is the only agent composer, opened from the Shop
  header, with starter questions drawn from the eval set;
- stable product cards with complete 3:2 premium catalog photography;
- agent shortlist cards labelled by the arms that retrieved them, the searches
  and constraints behind the shortlist, evidence citations, rank explanation,
  and tool receipts;
- one compact receipt vocabulary across search and agent turns: filters,
  candidates by arm, fused rank, rerank, evidence IDs, and latency;
- a side-by-side comparison of two to five ticked results, served by the
  scoped compare route rather than filtered from the rendered list, so it can
  print the arms that found each product, its rank before reranking, and the
  rank shown. Offered only once a search has run, because the retrieval's
  grant is what authorises it; a product outside that grant is refused with a
  detail that names no product;
- a coverage notice above the results naming the request words the catalog
  does not carry;
- pagination;
- compact mobile filter disclosure.

API: `GET /api/catalog/products`, `GET /api/retrieval/examples`, `POST
/api/search`, `POST /api/retrieval/events/{search_event_id}/compare`, and
`POST /api/agent/answer/stream`.

## `/mosaic-labs` - Playground

Purpose: make the three-lab `Retrieve -> Rank -> Reason` progression and its
evidence requirements visible.

Components:

- stage switcher for Retrieve, Rank, Reason, and optional Advanced work;
- an observational Retrieve -> Rank -> Reason stage switcher; the separate
  Workshop Studio Code Editor owns each Broken -> Diagnose -> Fix exercise and
  Shop is the proof surface;
- three participant requests and five validator-owned proof anchors, grouped
  inside the three labs;
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

## `/labs/retrieval` - Playground

Purpose: preserve one query while inspecting how each retrieval stage changes
candidate order.

Stages:

1. PostgreSQL full-text search;
2. `pg_trgm`;
3. pgvector semantic search;
4. reciprocal rank fusion;
5. Cohere Rerank.

The page shows stage rank, raw stage score, candidate-arm agreement, hard
eligibility, run ID, the shared compact receipt, diagnostics, and directly
copyable canonical SQL.

API: `GET /api/retrieval/examples` and `POST /api/search`.

## `/mosaic-labs/hnsw` - Scale & HNSW

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

## `/mosaic-labs/memory` - Session & Memory

Purpose: explore AgentCore conversation events, memory strategies and recall.
The page starts with empty answer areas and reads actual stored records when
connected. New session keeps Alex’s identity; Start fresh begins a separate Alex.

The former `/mosaic-labs/studio` route redirects to Hybrid retrieval. The footer
and tab strip expose the same three current destinations in the same order.

## Ownership boundary

The React application renders API and lab contracts. It does not reproduce SQL
filtering, ranking, fusion, reranking, citation validation, or run persistence.
Those remain in the service and Aurora PostgreSQL. Ask Mosaic displays tool
receipts and evidence; it never exposes hidden model chain-of-thought.
