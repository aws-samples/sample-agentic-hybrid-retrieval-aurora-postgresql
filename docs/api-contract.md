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

`GET /api/tools` defaults to `surface=agent`; pass `surface=mcp` for the
explicit MCP subset. Both are projections of
`db/config/agent_tool_contracts.json`, not independent schemas.

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

- `POST /api/hnsw/probe` runs one real ANN query and reports what the server did:
  plan node, index name, server-side execution time, buffer counts, planner
  estimate, rows returned against rows that exist, recall, and which product ids
  were missed. Every HNSW setting is applied through
  `mosaic_search.configure_hnsw` — the same function served retrieval calls — inside
  one transaction with a `statement_timeout`. `filter_preset` is a key into
  `service.hnsw_presets.FILTER_PRESETS`, never a predicate, so no request value
  reaches the SQL. Recall is computed against the precomputed ground truth, which
  is what bounds this endpoint's cost at a filtered HNSW scan instead of a
  2.4-second sequential scan.

  `scan_mem_multiplier` accepts 1, the pre-2026-08-17 default, so a participant can
  reproduce the silent candidate truncation it caused and then fix it.

## Production additions

- authenticated tenant/catalog scope;
- timeouts and partial-failure behavior by candidate source;
- query/event retention and PII policy;
- request and model versioning;
- inventory freshness policy;
- pagination and canonical-group diversity;
- deployment alarms and benchmark provenance.
