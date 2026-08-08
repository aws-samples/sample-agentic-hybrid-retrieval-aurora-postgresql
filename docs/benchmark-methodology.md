# Benchmark methodology

## Measurement boundaries

Separate these timings:

1. query normalization/embedding
2. lexical candidate retrieval
3. trigram candidate retrieval
4. vector/HNSW candidate retrieval
5. metadata filtering and fusion
6. reranking
7. answer assembly
8. end-to-end user latency

A fast HNSW query does not imply a fast end-to-end search experience.

## Dataset and query sampling

- sample queries across all three domains and challenge cohorts
- preserve a fixed evaluation set for regression tracking
- include clean, typo, exact model, semantic, filter-heavy, and hard-negative queries
- report warm and cold-cache behavior separately
- report filter selectivity and returned `k`

## Exact baseline

Recall requires a ground truth. For the sampled query vectors, run exact nearest-neighbor search with ANN index scans disabled in a local transaction. Store exact top-k IDs and compare ANN overlap.

## Latency reporting

- discard or identify startup/warm-up separately
- report p50, p95, and p99, not only an average
- record client region/network path
- distinguish database execution time from client-observed time
- preserve concurrency, connection pooling, and transaction settings

## HNSW build reporting

Record:

- row count and non-null vector count
- dimension and data type
- `m` and `ef_construction`
- build duration
- index size
- instance/storage profile
- concurrent workload
- maintenance memory and parallelism settings relevant to the run

## Projection policy

`simulate_scale.py` is a capacity-teaching model. Its defaults are illustrative. Before using its output, provide a measured 500K baseline from the target environment. The generated CSV includes `projection_kind=simulated_calibrated` so projected rows cannot be mistaken for measured results.
