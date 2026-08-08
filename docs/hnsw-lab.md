# HNSW performance lab

## Objective

Turn HNSW from a single `CREATE INDEX` statement into an observable engineering trade-off among latency, recall, memory/index size, build cost, filtering, and concurrency.

## Scale ladder

| Scale | Treatment |
|---:|---|
| 500K | Canonical physical catalog shipped in this package; attendee baseline |
| 1M | Optional physical expansion or instructor-prebuilt environment |
| 5M | Instructor benchmark environment or calibrated projection |
| 10M | Advanced scale profile; preferably measured before presentation |
| 100M | Architecture/capacity scenario; never imply local UI values are measured |

## Measured experiment matrix

For each selected scale and hardware profile, capture:

- dimensions: selected embedding-model dimension
- index configuration: `m`, `ef_construction`
- runtime: `ef_search`, iterative-scan mode
- query `k`
- filter selectivity: 100%, 25%, 10%, 1%, 0.1%
- p50, p95, p99 latency
- recall@10 or recall@k versus an exact baseline
- QPS at controlled concurrency
- HNSW index size and total relation size
- build duration and peak resource use
- plan shape and rows removed by filter

## Lab sequence

### 1. Establish exact ground truth

For a sampled query set, disable index scans in a local transaction and retrieve exact nearest neighbors. Save the IDs; these become recall ground truth.

### 2. Sweep `ef_search`

Run 16, 32, 64, 128, 256, and 512. Plot p95 latency and recall@10. Let attendees select a workload-appropriate operating point instead of declaring one universal optimum.

### 3. Introduce metadata filters

Use domain, category, stock, price, and JSON-attribute filters at different selectivities. Observe how post-index filtering can reduce returned rows and recall.

### 4. Enable iterative scans

Compare:

```sql
SET LOCAL hnsw.iterative_scan = off;
SET LOCAL hnsw.iterative_scan = strict_order;
SET LOCAL hnsw.iterative_scan = relaxed_order;
```

Strict order preserves exact distance order; relaxed order can trade slight ordering looseness for improved recall/performance in filtered searches. Record behavior rather than asserting a universal winner.

### 5. Compare physical strategies

- shared global HNSW index
- partial index for a stable high-value predicate
- partitioning by domain or tenant boundary
- prefilter versus postfilter patterns

### 6. Build-time parameters

Rebuild a smaller lab table with `m` and `ef_construction` variations. Observe build duration, index size, and recall—not just query latency.

## Scripts

- `scripts/benchmark_hnsw.py` emits **measured** JSON results and EXPLAIN plans.
- `scripts/simulate_scale.py` emits **simulated_calibrated** projections.
- `sql/06_hnsw_performance_lab.sql` contains inspection and filter-selectivity exercises.

## UI contract

Every chart must show one of these badges:

- `MEASURED`
- `PROJECTED FROM 500K BASELINE`
- `SAMPLE UI DATA`

The badge is not optional. This protects the session from presenting invented performance as Aurora results.
