# Production-readiness checklist

## Relevance

- fixed offline eval set with cohort breakdown
- human review of hard negatives and top failure queries
- exact model/SKU preservation tests
- typo recovery precision and false-positive thresholds
- canonical-group diversity
- constraint satisfaction validated independently of reranker output

## Data quality

- source-system precedence
- freshness SLA per field family
- inventory conflict handling
- sparse/invalid JSON attributes
- product merge and variant rules
- embedding refresh policy when searchable text changes

## Performance

- p50/p95/p99 by query class
- exact-baseline recall sampling
- filtered ANN tests at realistic selectivity
- concurrent load and connection pooling
- index build/rebuild operational plan
- bloat, vacuum, statistics, and plan stability monitoring

## Safety and governance

- tenant/catalog isolation
- application least privilege
- query and telemetry retention policy
- sponsorship/business-signal bounds
- explanation does not expose sensitive internal signals
- model/provider version capture
- fallback when embeddings or reranker are unavailable

## UX

- explicit filters visible to the user
- “why this ranked” at product level
- source/data freshness
- no invented benchmark labels
- accessible charts and textual metric summaries
- graceful partial-result state
