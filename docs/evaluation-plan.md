# Retrieval evaluation plan

## Included ground truth

- 720 balanced evaluation queries
- 20 curated canonical workshop queries, of which 19 are scored as
  single-request product retrieval and one is an agent-contract scenario
- 5,000 typo cases
- graded judgments with relevance levels 1–3
- challenge-cohort labels on products

## Offline metrics

Primary:

- Recall@10 and Recall@50
- MRR
- nDCG@10
- constraint satisfaction rate
- typo target recovery rate
- hard-negative rejection rate

Secondary:

- result diversity by canonical group
- out-of-stock leakage
- sponsored-result policy violations
- explanation completeness
- source freshness
- p50/p95/p99 retrieval and total latency

## Required ablation table

| Variant | FTS | Trigram | Vector | Filters | RRF | Rerank |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| A | ✓ | | | ✓ | | |
| B | | | ✓ | ✓ | | |
| C | ✓ | ✓ | | ✓ | ✓ | |
| D | ✓ | | ✓ | ✓ | ✓ | |
| E | ✓ | ✓ | ✓ | ✓ | ✓ | |
| F | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

Compare the full metric suite, then break results down by challenge cohort.

## Cohort-specific success criteria

- `typo_target`: intended item or acceptable alternative appears in top 10
- `semantic_only`: vector or rerank improves nDCG over FTS baseline
- `lexical_only`: hybrid pipeline does not bury exact model/SKU hits
- `exact_sku`: an exact catalog SKU remains first after model reranking, while
  diagnostics retain both the model's rerank rank and the final preserved rank
- `hard_negative`: decisive mismatch is removed or materially demoted
- `near_duplicate`: top results are not monopolized by one canonical group
- `selective_filter`: result count and recall remain stable under configured iterative scan
- `sponsored_low_relevance`: sponsorship never bypasses required constraints

## Online-style signals for the demo

The schema includes `mosaic.search_event` for query, filter, latency, result, click, and diagnostics telemetry. In a real deployment, extend this with add-to-cart, conversion, reformulation, abandonment, and human-quality feedback.

## Reproducibility

Persist for every eval run:

- dataset manifest hash
- embedding model and dimension
- index definition and size
- all HNSW settings
- SQL/function version
- reranker model/version
- Aurora engine/instance configuration
- cache state and concurrency
- timestamp and code commit

Before model calls, validate that every packaged target exists and satisfies its
production Mosaic filters:

```bash
make validate-evals
```

The 720-query corpus uses `category_key`, integer cent price bounds, and explicit
refurbished or sponsored inclusion where the target requires it. Predecessor
keys such as `subcategory` and `max_price` fail closed in `SearchFilters`.

## Canonical release scorecard

`make score-evals` runs the served FTS, pg_trgm, HNSW, RRF, reranker, and
exact-SKU preservation path against the 19 product-retrieval cases. It writes
only an ignored per-run result CSV, verifies the committed measured baseline,
and fails on provenance or metric regressions. It also carries machine-readable
fixture checks for the exact SKU, non-plated road shoe, and waterproof IP67
speaker repairs, so a good aggregate average cannot hide those failures.

`G-010` is deliberately excluded from Recall@K, MRR, and nDCG. Its question
requires targeted retrieval, comparison, evidence retrieval, citation
resolution, and cited synthesis; score it through the Lab 3 agent-contract
validator rather than pretending it is one product-ranking request.
