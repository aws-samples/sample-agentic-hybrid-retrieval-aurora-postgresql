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

- on a browser's first visit (not under automation), the guided tour: a dimmed page
  with a pulsing ring on one control at a time (search and examples, Browse all
  products, Ask Mosaic, Playground, Alex, Code Editor) and a card with Next and
  Skip the tour; the header's **Take the tour** compass replays it
  (`ui/src/tour.ts`, `ui/src/components/SpotlightTour.tsx`);

- centred headline, search composer, catalog scope line, and one unlabelled row
  of example searches that stays in view after a search;
- a horizontal workspace product shelf, category links, **Browse all products**
  and a shortcut to Meet Alex;
- Meet Alex: the five-step workspace walkthrough beside Alex's profile
  (`#alex-profile`), with links to his three categories;
- three full-width bands, one per need, each linking to its category and to
  its category-scoped search from the mission manifest;
- the Ask Mosaic invitation as the closing band, then the note that Alex is
  fictional and the workspace imagery is AI-generated;
The shelf supports touch, keyboard scrolling and previous/next controls. Category
links and **Browse all products** replace the story with the full browse grid,
its existing tabs, filters and pagination.

With a query the story is not rendered. The headline stays the page's h1 for
assistive technology only, and `Results for ...` is the display line. A search
shows, in order: one strip of chips for how it ran (each search's count in the
combined pool, Combined in Aurora (RRF), Reranked, shown) with a link to watch
the ranking change in the Playground; **Each method's top five**, one column per
search plus Combined and Reranked, with ▲/▼ movement; then the result grid,
eight cards a page, each with a dot per search that found it and its reranked
position. **Compare positions** swaps the grid for the same products in combined
and reranked order. Before Lab 2 is prepared, Lab 2's request shows only the
lab's next step. Browsing keeps the grid.

Components:

- domain, availability, and minimum-rating filters;
- featured, rating, price, and newest sorting;
- direct hybrid search in the product grid;
- an Ask Mosaic sidecar that is the only agent composer, opened from the Shop
  header, with starter questions drawn from the eval set;
- stable product cards with complete 3:2 premium catalog photography;
- a run status line with a segment per phase and a finding for each finished one,
  counted from the actual plan, searches, comparisons and citations; a collapsed
  "How Mosaic answered" fold once answered, and a Builder view switch that adds
  the full Retrieval agent record ID, recorded steps and each search's ranks;
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

## `/labs/retrieval` - Hybrid retrieval

Purpose: show, on one screen, how a request moves from three searches to
Aurora's combined order to the reranked order and, when asked, to the Retrieval
agent's cited answer.

The search bar's button is a magnifying glass until a search's results are in,
then the arrow that asks the Retrieval agent; agent examples start the agent
directly. A run shows one row of chips (each search's count, the combined pool,
reranking, the record ID, or the agent's tool calls), the agent's answer when
there is one (its picks on the left from the first word, the prose read out
beside them, compact sources after), then **Watch the ranking change**: the
returned products racing from each search to Combined (RRF) to Reranked, with a
journey line for the followed product. One row of details opens beneath it, one
at a time: **Each search's top five**, **How Aurora combined them**, **Why this
position**, **Agent steps and sources**. Before Lab 2 is prepared, Lab 2's
request shows only the lab's next step. A first visit runs the Playground's own
short tour.

The canonical example selector and the bar's button start the production agent.
The completed summary links each final choice to its recorded search. **Trace
all returned products** lists the actual search positions, successful comparisons,
registered evidence counts, and final inclusion; listing IDs distinguish similar
titles. Missing records remain visibly unavailable, and omission alone is not
presented as a rejection explanation.

The board and the details follow the selected search; after an agent run that
is the agent's first search, and the original search stays in the selector.
Each search column shows how that search read the request (lexemes, trigrams,
the vector) above what it found. The details hold the fusion arithmetic and
receipts, the saved candidate pool, and the activity log.

`?view=lab` retains the guided lab workbench and proof controls.

API: `POST /api/agent/answer/stream`,
`GET /api/retrieval/events/{search_event_id}/response`, and linked evidence records.

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

### Lab 1's missing-product state

The outcome notice is text only. It names the requested listing as missing,
explains that the cards below are other returned products, and offers Search
again after the participant applies SQL. No product photo appears in the
notice, even after repair; product imagery belongs to actual result cards.
**Lab 1: request and evidence** discloses the typed/listing IDs and the saved
run's Playground link. The no-exact-ID coverage message stays available inside
the result's **Why this match**, rather than competing with the outcome.
