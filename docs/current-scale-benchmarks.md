# Mosaic scale benchmarks

Measured on September 8, 2026 in New York (September 9 UTC), against the current
Aurora catalog: **500,000 embeddings, 1,024 dimensions, and all 30 retrieval
anchors**. Each domain contributes 10 anchors: consumer electronics, home office,
and running & fitness.

| Format, at ef_search 100 | Index size | Recall@10 | Database p50 | Database p95 |
|---|---:|---:|---:|---:|
| Full precision | 3,918.5 MiB | 99.0% | 1.882 ms | 2.454 ms |
| halfvec | 1,306.1 MiB | 99.0% | 2.474 ms | 3.174 ms |
| Binary + cosine, 200 candidates | 207.7 MiB | 94.0% | 5.120 ms | 6.793 ms |

halfvec used about **3× less index space** with the same recall in this sample.
Binary used about **18.9× less index space**, with a tradeoff between candidate
depth, recall and query time. A smaller index did not guarantee a faster query.
These sizes include the graph. All three indexes already existed; build times
were not measured.

## Filters and iterative scans

Both Strict and Relaxed are iterative scan modes. Strict preserves distance order
among the returned candidates. Relaxed allows small order changes and can find
more of the exact closest matches; an outer sort can restore order.
See the [pgvector examples](https://github.com/pgvector/pgvector#iterative-index-scans).

The brand-and-stock filter matched 1,872 catalog products. With the same
ef_search 100, 4 MiB scan budget and 20,000 scan-tuple limit:

| Scan mode | Products returned, average / 10 | Recall@10 | Database p50 | Database p95 |
|---|---:|---:|---:|---:|
| Off | 0.63 | 6.33% | 1.789 ms | 2.310 ms |
| Strict | 6.07 | 52.33% | 27.106 ms | 50.518 ms |
| Relaxed | 6.07 | 54.00% | 27.470 ms | 51.336 ms |

Strict found 5.44 more products on average than Off. Relaxed returned the same
average count with slightly better recall. Neither filled every shortlist at
these work limits. The download includes all six filters at both 4 and 8 MiB.
For the six-row flagship filter, PostgreSQL chose an exact scan; those rows
are recorded as such, rather than treated as evidence for HNSW scan ordering.

## More search effort

The unfiltered full-precision sweep reached 99% recall at ef_search 80
(1.631 ms p50). Raising ef_search through 400 did not improve recall on this
query set. The exact full-precision scan took 2,279.914 ms database time
(median across the 30 anchors).

At ef_search 800, the deeper comparison measured:

| Search | Recall@10 | Database p50 |
|---|---:|---:|
| Full precision | 99.00% | 8.449 ms |
| Binary + cosine, 1,400 candidates | 99.67% | 21.691 ms |
| Binary + cosine, 3,000 candidates | 100.00% | 40.978 ms |

The 100% result applies to these 30 anchors. It is not a guarantee for unseen
queries. Candidate depth and search effort are part of each configuration.

## What this measures

- Aurora PostgreSQL 18.3, pgvector 0.8.1, `db.r8g.2xlarge` in `us-east-1`.
- Existing HNSW indexes: `m=16`, `ef_construction=200`. Representation comparisons
  use Relaxed scans, `work_mem=4MB`, scan-memory multiplier 2 and a 20,000
  scan-tuple limit. Filter comparisons hold search effort and memory constant.
- Query vectors are the current anchor products' stored embeddings. Exact
  full-precision top-10 IDs were recomputed for every anchor and filter using
  transaction-local settings that disable index and bitmap scans. The anchor
  itself is included when it passes the filter. Recall is ID overlap against
  that exact result, averaged across anchors; equal-distance ties are not
  treated as interchangeable IDs.
- Each configuration uses one sequential connection. Each query first returns
  product IDs, then runs again under `EXPLAIN (ANALYZE, BUFFERS)` for warmed
  database timing and index-use evidence. p50/p95 summarize 30 second executions
  using the runner's rounded order-statistic percentile. This is one sweep,
  with fixed configuration order, rather than repeated randomized trials.
- Client timings include the local machine's connection to Aurora and are
  stored separately. No embeddings or model calls were generated. These results
  do not measure cold cache, concurrent users, reranking, agent reasoning or
  end-to-end Shop response time. No database settings or indexes were changed
  persistently, and background cluster activity was not controlled.

## Results and rerunning

- [Summary JSON](../data/benchmarks/hnsw_measured.json)
- [Per-query samples, returned IDs, exact IDs and plan details](../data/benchmarks/hnsw_measured.samples.json)
- [Runner](../scripts/benchmark_mosaic_scale.py)
- [Historical August artifact](../data/benchmarks/archive/hnsw_measured_2026-08-17.json),
  kept separately for its earlier catalog and hardware comparisons.

The measurement source is clean commit
`ba81904d3e4654bce62046535fc65053d7917bb5` on
`benchmarks/mosaic-scale-20260908`. The dataset manifest is
`2cbb04b93521a62be0c6512cec13a70149c51e24543f8a3d6e53d335ae7f5774`.
The summary records the anchor IDs and hashes for both the anchor list and raw
samples. The API checks the recorded dataset against the connected catalog
before labeling it current.

With the existing Aurora connection configured and the source committed in a
clean checkout:

```sh
make benchmark-hnsw AURORA_INSTANCE_CLASS=db.r8g.2xlarge
```

Set the instance class to the actual connected instance when running elsewhere.
The equivalent command used for this run was:

```sh
python scripts/benchmark_mosaic_scale.py \
  --output /tmp/mosaic-benchmark-results/hnsw_measured.json \
  --k 10 --ef-search 10 20 40 80 100 200 400 \
  --binary-depth 10 20 50 100 200 \
  --deep-ef-search 800 --deep-binary-depth 1400 3000 \
  --instance-class db.r8g.2xlarge
```

The runner measures all current anchors and existing indexes without carrying
older measurements into the new artifact. It refuses a dirty source checkout,
missing exact matches or a missing representation index.

The separate scale projection has also been recalculated from this run's
measured p95 and index size. Its larger-catalog rows remain estimates. Run
`make simulate` after refreshing measurements to keep that baseline aligned.
