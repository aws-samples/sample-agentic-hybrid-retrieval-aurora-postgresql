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

Landing, before a query or Ask Mosaic's picks:

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
shows, in order: one strip of chips for how it ran (each search's count on the
shortlist, Combined (RRF) · shortlist, Reranked with the shortlist's size, shown)
with a link to watch the ranking change in the Playground; **Each method's top
five**, one column per search plus Combined (RRF) and Reranked, each naming the
SQL function the guides call (`search_fts`, `search_trigram`, `search_vector`,
`search_hybrid_rrf`). Each column lists that method's own top five on the
shortlist, read from the search's saved receipts: a search row gives its final
position, Combined and Reranked rows their ▲/▼ movement, and rows below the page
are faded. A column is empty only when its search put nothing on the shortlist.
Then the result grid, eight cards a
page, each with its path: the searches that found it with their ranks, then its
combined and final positions. **Compare positions** swaps the grid for the same
products in a table with each search's rank, the combined and reranked
positions and the change, where — means that search did not return it. Before Lab 2 is prepared, Lab 2's request shows only the
lab's next step. Browsing keeps the grid.

Components:

- domain, availability, and minimum-rating filters;
- featured, rating, price, and newest sorting;
- direct hybrid search in the product grid;
- an Ask Mosaic sidecar that is the only agent composer, opened from the Shop
  header, with suggested questions drawn from the eval set;
- stable product cards with complete 3:2 premium catalog photography;
- a run status line with a segment per phase and a finding for each finished one,
  counted from the actual plan, searches, comparisons and citations; a collapsed
  "How Mosaic answered" fold once answered, opened by default on the Builder
  view (the "Show tool calls" switch): the full Retrieval agent record ID,
  recorded steps and each search's ranks;
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
position**, **Agent steps and sources**. **How Aurora combined them** is one
table: each search's `1 / (k + rank)` with the share the run reported, their sum
and the reported `rrf_score` (neutral, red only when it differs from the sum:
a sum of wrong shares still agrees), first five rows and the
followed product, then **Show all**. Before Lab 2 is prepared, Lab 2's request
shows only the lab's next step, and holds its results while the search runs and
the lab state is read. A first visit runs the Playground's own short tour. Two
one-time tips (`hint` mode of `SpotlightTour`: one card, Got it, the page stays
live) ring the bar's button when **Agent steps and sources** opens before the
agent has run, and **Agent steps and sources** after the first answer. Shop has
one more, on the link into the Playground after the first search. Tips are off
under automation, like the tours' first-visit start. **Use it in your own agent**
ends the page: what the downloads hold, three short lines on adapting it (your data,
your models, your agent, from `docs/use-in-your-app.md`), then **Download the SQL
and guide** (`/api/builder-package`), **Download the agent skill** and **Connect over MCP**.

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

The older guided lab workbench is retired: `?view=lab`, `?run=` and bare
`?example=` links open this page. Labs are proved in the terminal; after Lab 3's
request, Shop shows `complete_agent.py --run-id` with that run's ID filled in; without
`--run-id` the command checks the newest setup run.

API: `POST /api/agent/answer/stream`,
`GET /api/retrieval/events/{search_event_id}/response`, and linked evidence records.

## `/mosaic-labs/hnsw` - Scale & HNSW

Purpose: teach HNSW as a measured workload rather than a checkbox. Every number
is a saved measurement from `GET /api/hnsw/measured`, beside the live index from
`GET /api/hnsw/substrate`; the page never runs a benchmark.

Sections, each one card with a heading and one sentence:

- **Recall against speed.** Recall and database time for each measured
  `ef_search`, the served setting marked. **Benchmarks & SQL** holds the sweep
  table, the exact-scan baseline and the iterative-scan SQL.
- **Keep looking after filters.** **Alex's filter** is a segmented control; the
  table compares Off, Strict and Relaxed scans at one search effort and memory.
- **A smaller index.** Full precision (`vector`), Half precision (`halfvec`) and
  Binary, then re-checked (`bit`, re-checked by cosine against the full vectors),
  each with index size (and how many times smaller than full precision), Recall@10
  and server time. **Binary: matches re-checked** is a segmented control over the
  measured shortlist sizes.

Times print at the three decimals `EXPLAIN ANALYZE` prints (`formatMs`) and sizes
in `pg_size_pretty` units (`formatBytes`), so both check against psql. Segmented
controls fill the chosen option with the action blue. `?view=bench` opens the
full benchmark workbench.

## `/mosaic-labs/memory` - Session & Memory

Purpose: explore AgentCore conversation events, memory strategies and recall.
The page starts with empty answer areas and reads actual stored records when
connected. New session keeps Alex’s identity; Start fresh begins a separate Alex.
Alex's card holds the session picker and **Refresh memories**. The four memory
types (Facts, Preferences, Summaries, Past outcomes) are a picker whose chosen
type is filled with the action blue; example messages and questions are pills,
and the memory switch uses the same blue.

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
