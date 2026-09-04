# Mosaic API contract

## Hybrid retrieval

`POST /api/search`

```json
{
  "query": "wireless noise-cancelling headphones under $200",
  "filters": {
    "domain": "consumer_electronics",
    "max_price_cents": 20000,
    "in_stock_only": true,
    "attributes": {"active_noise_cancellation": true}
  },
  "limit": 12,
  "include_diagnostics": true,
  "rerank": true
}
```

The response contains:

- `search_event_id`, original query, and normalized query;
- applied hard filters;
- source-attributed products;
- separate lexical, trigram, semantic, RRF, and rerank signals, including the
  model's rerank rank and any exact-SKU preservation applied to final order;
- `coverage`, the `service.coverage` result: per-term catalog presence and the
  rescue decision behind it, so a request naming something absent from the
  catalog is labelled rather than silently answered as if it were grounded;
- candidate counts, the configured retrieval profile, model IDs, stage timings,
  and total latency.

Search returns ranked evidence, not a natural-language answer.

## Fusion comparison

`POST /api/retrieval/fusion-comparison`

The comparison applies unweighted and weighted RRF to one candidate pool and
returns both orders with their ranking signals. It fails if the two functions
do not receive the same substrate; it does not change the production
`POST /api/search` path.

## Cited agent answer

`POST /api/agent/answer`

`POST /api/agent/answer/stream`

```json
{
  "question": "Compare quiet mechanical keyboards for shared-office calls under $200",
  "filters": {"domain": "home_office", "max_price_cents": 20000},
  "result_limit": 6
}
```

The Strands response contains:

- persisted `agent_run_id`;
- tool-generated retrieval plan;
- citation-bounded answer of record with deterministic product, numeric,
  availability, and mission-claim checks;
- source-backed product recommendations;
- numbered citations;
- bounded tool trace with retrieval run IDs.

The streaming route emits server-sent application stages and then the same
citation-bounded answer contract. It does not expose model reasoning or claim
general semantic entailment.

## Telemetry timeline

`GET /api/telemetry/agent-turns/{agent_turn_id}`

The response is the persisted `mosaic.telemetry.v1` contract:

- explicit agent-turn, search-event, trace, and span correlation;
- ordered Retrieve → Rank → Reason stages with status and measured duration;
- model IDs, token use, stop reason, synthesis latency, and turn latency;
- exact per-arm RRF contributions, rerank movement, and candidate disposition;
- evidence coverage, citation-validation outcome, and authorization outcomes.

The endpoint reads Aurora receipts and does not execute retrieval or a model.
It is a candidate-level workshop inspection surface. The optional AgentCore
adapter exports only aggregate counts and timings; see
[`telemetry-contract.md`](telemetry-contract.md).

## Catalog inspection

- `GET /api/catalog/summary`
- `GET /api/catalog/suggestions`
- `GET /api/catalog/products`
- `GET /api/catalog/reviews/highlights`
- `GET /api/products/{product_id}`
- `GET /api/evidence/{evidence_id}`
- `POST /api/products/{product_id}/evidence` requires `retrieval_scope_id`, the
  `search_event_id` of the retrieval that granted the product. A product the
  retrieval did not grant returns 404 with a generic detail. See
  `skills/mosaic-hybrid-retrieval/SKILL.md` for the scope rules.

The product-evidence route requires an `evidence_query` and returns
source-addressable specification and review records ranked for that question,
without invoking the agent. The evidence-ID route resolves a persisted
citation to its exact evidence row.

Review highlights back the storefront's "what others are saying" strip: at
most five verified customer-review excerpts from the photographed cohort, one
per distinct opening sentence and one per product. Each `quote` is the review
body's opening sentence verbatim, and each highlight carries the `source_uri`
of the evidence row it was excerpted from.

Catalog suggestions accept the shopper text in the `q` query parameter, require
at least two non-space characters, and return a bounded mix of matching product,
brand, and category identities. Product
matches use the existing full-text index over `mosaic_search.product_document`;
the route does not create an embedding, invoke reranking, or call a model.

## Labs and replay

- `GET /api/retrieval/examples`
- `GET /api/retrieval/events/{search_event_id}`
- `POST /api/retrieval/events/{search_event_id}/plan`
- `POST /api/retrieval/events/{search_event_id}/compare` requires two to five
  distinct `product_ids`, all granted by that retrieval's scope. A product the
  retrieval did not grant returns 404 with the same generic scope-denied
  detail as the evidence route. See `skills/mosaic-hybrid-retrieval/SKILL.md`
  for the scope rules.
- `GET /api/benchmarks/projection`
- `GET /api/tools`

Retrieval-run inspection returns persisted request, diagnostics, and
candidate-level ranking signals plus source, dataset, model, SQL strategy,
Aurora, pgvector, and HNSW identity. Plan capture replays that event's exact
fusion call after applying `mosaic_search.configure_hnsw`, then persists
`EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON)`. It is explicit and
on-demand because `ANALYZE` executes the query. Benchmark projections remain
labeled simulated; `scripts/benchmark_hnsw.py` persists measured Aurora runs to
`mosaic_bench`.

The compare route is a projection over one retrieval's persisted receipt: it
hydrates the requested products and their ranking signals from
`mosaic.search_result_event` without issuing fusion, reranking, or any new
candidate generation, so it cannot return a set wider than what that
retrieval already granted.

`GET /api/tools` defaults to `surface=agent`; pass `surface=mcp` or
`surface=skill` for those explicit subsets. All three are projections of the
one canonical `db/config/agent_tool_contracts.json`, not independently
authored schemas, but each projection is scoped to that surface alone:
`output_schema` carries the transport-independent payload plus only the
envelope fields that surface declares, never a field another surface's
envelope adds. The canonical record still holds the full cross-surface union
for introspection; no served surface does.

`GET /api/catalog/products` browses the 200 installed product IDs in
`data/media/asset_labels_200.json`. `sort=featured` preserves manifest order;
facets and other sort modes stay bounded to that photographed edit. Search and
Ask Mosaic continue to retrieve across all 500,000 products.

## Runtime status

- `GET /api/health` reports the configured service and model IDs.
- `GET /api/readiness` verifies the product/vector counts, premium cohort,
  specification-evidence coverage, required retrieval indexes/functions,
  model-space compatibility, and the current process's AWS credential validity.

## HNSW instrument

Five read-only routes behind `/mosaic-labs/hnsw`. Two are live reads, two replay
stored measurements, and one issues a real query. Which is which is the point: the
page labels them differently because they are different kinds of claim.

- `GET /api/hnsw/substrate` reads the cluster now: HNSW index size and definition,
  the heap/TOAST/index storage split, bytes per vector against the raw fp32
  payload, and the settings that explain those numbers (`work_mem`,
  `maintenance_work_mem`, `shared_buffers`, `effective_cache_size`,
  `max_parallel_workers_per_gather`). It deliberately does **not** count distinct
  vectors: deduplicating 500,000 `vector(1024)` values sorts roughly 2 GB against a
  4 MB `work_mem` and terminated the Aurora backend when tried.

- `GET /api/hnsw/measured` serves `data/benchmarks/hnsw_measured.json` verbatim,
  written by `make benchmark-hnsw`. It carries its own provenance (source revision,
  dataset manifest sha256, database instance id, instance class, query-sample
  sha256) and is refused with HTTP 503 if its `kind` is not `measured`, so a
  projection cannot be served under a measured label.

- `GET /api/hnsw/anchors` lists the query anchors the instrument offers: the 30
  retrieval anchors, which are the products carrying real media.

- `GET /api/hnsw/neighborhood/{anchor_product_id}`, with optional `preset` and `k`
  query parameters, returns the
  precomputed exact top-k from `mosaic_bench.exact_neighbor` with real cosine
  distances, plus the `band` those neighbours occupy. It runs no vector query.
  Ground truth is keyed by dataset manifest sha256; a mismatch is HTTP 503 rather
  than a silent answer from another corpus.

- `POST /api/hnsw/probe` runs one real ANN query and reports what the server did.
  It runs the statement twice inside one transaction: once to fetch the actual
  rows, and once more wrapped in `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`
  purely for telemetry. Rows and recall come from the first run; every timing
  and buffer count comes from the second run, against a cache the first run
  already warmed, so `plan` is not an annotation of the run that produced the
  returned rows. Every probe response carries `plan.execution`, a sentence
  labelling the EXPLAIN run as that second execution with warmed buffers, next
  to the rest of `plan`: node, index name, server-side execution time, buffer
  counts, and planner estimate. Rows returned are compared against rows
  that exist, recall is reported, and missed product ids are named. Every HNSW
  setting is applied through `mosaic_search.configure_hnsw`, the same
  function served retrieval calls, inside that same transaction, with a
  `statement_timeout`. `filter_preset` is a key into
  `service.hnsw_presets.FILTER_PRESETS`, never a predicate, so no request value
  reaches the SQL. Recall is computed against the precomputed ground truth, which
  is what bounds this endpoint's cost at a filtered HNSW scan instead of a
  2.4-second sequential scan.

  `scan_mem_multiplier` accepts 1, the pre-2026-08-17 default, so a participant can
  reproduce the silent candidate truncation it caused and then fix it.

## Retrieval scorecard

- `GET /api/scorecard` is the Prove step: a read-only render of
  `data/evals/canonical_scorecard.json`, `data/evals/canonical_queries.jsonl`, the
  `service.assertions` vocabulary, and the tool-contract registry. No DDL, no
  `eval_run` table (ruling R7) — the response is computed fresh from those files on
  every request rather than persisted.

  Four sections, never conflated: `retrieval_quality` (population Recall@10, MRR,
  nDCG@10 over the 20 scored searches, gated on provenance), `regression_anchors`
  (compact PASS/total over the golden release checks), `eligibility_contracts` (hard
  eligibility/filter fixtures — not a relevance judgment, no Recall/MRR/nDCG),
  and `agent_contracts` (deterministic retrieval-scope, compare-boundary,
  evidence-authorization, citation-resolution, and tool-contract guarantees, backed
  by real `service.assertions` names and the live tool-contract count).

  `provenance.attributed` is the gate the UI renders on: true only when the
  artifact's recorded `retrieval_fingerprint`, embedding and rerank model ids,
  query-set hashes, methodology hash, and retrieval settings hash all match
  what the running service reports right now, **and** the artifact's own
  worktree was clean at measurement time. A plain revision-equality check can
  never hold here: the artifact is written before it is committed, so
  committing it always advances the repository one commit past what was
  measured, and that check would read "pending" forever. That is why
  `source_revision` is never part of the gate; it and the current server's own
  worktree cleanliness (`current_source_worktree_dirty`) stay display and
  audit evidence only. When `attributed` is false, `provenance.attribution_note`
  starts with the exact string `Metrics pending evaluation for this retrieval revision`.

  Four provenance fields describe how this artifact is served, not just what it
  measured:

  - `artifact_kind` is always the literal `release_baseline`: this is a maintainers'
    release artifact measured against Aurora at one revision, not a live proof of
    the attendee's own retrieval run.
  - `served_at` is the UTC time this response was assembled. It is always distinct
    from `measured_at`, the time the artifact itself was measured, so a baseline
    rendered months later does not read as a measurement taken now.
  - `retrieval_settings_sha256` is the hash of the resolved retrieval settings the
    artifact was measured with. It is absent (`null`) on artifacts written before
    this hash existed, and an absent hash fails the attribution gate closed rather
    than being read as agreement.
  - `current_retrieval_settings_sha256` is the same hash resolved by the running
    service right now, so a reader can compare both sides of the settings clause
    directly rather than trusting `attributed` alone.

## Production additions

- authenticated tenant/catalog scope;
- timeouts and partial-failure behavior by candidate source;
- query/event retention and PII policy;
- request and model versioning;
- inventory freshness policy;
- pagination and canonical-group diversity;
- deployment alarms and benchmark provenance.
