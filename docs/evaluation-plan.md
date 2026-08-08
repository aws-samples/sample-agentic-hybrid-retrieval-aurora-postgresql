# Retrieval evaluation plan

## Included ground truth

- 720 balanced evaluation queries
- 45 polished instructor/demo queries
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
- `hard_negative`: decisive mismatch is removed or materially demoted
- `near_duplicate`: top results are not monopolized by one canonical group
- `selective_filter`: result count and recall remain stable under configured iterative scan
- `sponsored_low_relevance`: sponsorship never bypasses required constraints

## Online-style signals for the demo

The schema includes `catalog.search_event` for query, filter, latency, result, click, and diagnostics telemetry. In a real deployment, extend this with add-to-cart, conversion, reformulation, abandonment, and human-quality feedback.

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
