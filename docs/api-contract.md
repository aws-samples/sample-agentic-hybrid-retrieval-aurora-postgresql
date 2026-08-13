# Mosaic API contract

## Hybrid retrieval

`POST /api/search`

```json
{
  "query": "wireless noise-cancelling headphones under $200",
  "filters": {
    "domain": "consumer_electronics",
    "max_price": 200,
    "availability": "In Stock",
    "attributes": {"active_noise_cancellation": true}
  },
  "limit": 12,
  "include_diagnostics": true,
  "rerank": true
}
```

The response contains:

- `run_id`, original query, and normalized query;
- applied hard filters;
- source-attributed products;
- separate lexical, trigram, semantic, RRF, and rerank signals, including the
  model's rerank rank and any exact-SKU preservation applied to final order;
- candidate counts, arm weights, model IDs, stage timings, and total latency.

Search returns ranked evidence, not a natural-language answer.

## Cited agent answer

`POST /api/agent/answer`

```json
{
  "question": "Compare quiet mechanical keyboards for shared-office calls under $200",
  "filters": {"domain": "home_office", "max_price": 200},
  "result_limit": 6
}
```

The Strands response contains:

- persisted `agent_run_id`;
- tool-generated retrieval plan;
- citation-validated answer of record;
- source-backed product recommendations;
- numbered citations;
- bounded tool trace with retrieval run IDs.

## Catalog inspection

- `GET /api/catalog/summary`
- `GET /api/catalog/products`
- `GET /api/products/{product_id}`

These routes expose the physical catalog and product evidence without invoking
the agent.

## Labs and replay

- `GET /api/retrieval/examples`
- `GET /api/retrieval/events/{search_event_id}`
- `GET /api/benchmarks/projection`
- `GET /api/tools`

Retrieval-run inspection returns persisted request, diagnostics, and
candidate-level ranking signals. Benchmark projections are labeled simulated
until replaced by measured Aurora output.

## Runtime status

- `GET /api/health` reports the configured service and model IDs.
- `GET /api/readiness` verifies the product/vector counts, premium cohort,
  specification-evidence coverage, required retrieval indexes/functions,
  model-space compatibility, and the current process's AWS credential validity.

## Production additions

- authenticated tenant/catalog scope;
- timeouts and partial-failure behavior by candidate source;
- query/event retention and PII policy;
- request and model versioning;
- inventory freshness policy;
- pagination and canonical-group diversity;
- deployment alarms and benchmark provenance.
