# HNSW performance data model

The benchmark tables distinguish **measured**, **instructor-provided**, and **projected** results.

## Profiles

A profile records:

- vector count and dimension
- distance operator
- HNSW `m` and `ef_construction`
- runtime `ef_search`
- iterative scan mode
- `max_scan_tuples`
- `scan_mem_multiplier`
- filter selectivity
- hardware/database label

## Measurements

Capture at minimum:

- p50, p95, and p99 latency
- Recall@10
- index size
- build time
- rows and buffers from `EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON)`
- execution plan JSON

QPS is recorded only by a runner that measures concurrent load. The current-scale
measurement does not report it (see `docs/current-scale-benchmarks.md`).

## Scale labels

| Scale | Treatment |
|---:|---|
| 553,911 | the served `reviews-2023-v2` catalog, measured on the physical rows |
| 1M, 5M, 10M, 100M | projections only (`simulated_calibrated`); no larger physical catalog is saved |
