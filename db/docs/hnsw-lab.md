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
- QPS
- index size
- build time
- rows and buffers from `EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON)`
- execution plan JSON

## Scale labels

| Scale | Expected treatment |
|---:|---|
| 500K | attendee-measured physical catalog |
| 1M | optional physical expansion |
| 5M | instructor benchmark or physical lab |
| 10M | instructor benchmark |
| 100M | physical only when provisioned; otherwise explicitly projected |
