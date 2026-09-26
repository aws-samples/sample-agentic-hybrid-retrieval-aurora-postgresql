# Mosaic scale benchmarks

Measured on 26 September 2026 (17:46 to 17:49 UTC) against Mosaic's served
catalog on the development Aurora cluster: **553,911 real source products with
their saved Cohere Embed v4 vectors (1,024 dimensions)**, catalog identity
`c4d5913f8905…`, source revision `2efb0be` with a clean worktree. Query
vectors are the stored embeddings of the **70 anchors** in
`data/benchmarks/hnsw_anchors.json` (anchor-set hash `af84d6ab2763…`): the
fifteen lab products plus a category-stratified hash sample (headphones 13,
monitors 15, chairs 17, long tail 10, and five each from headphone cases,
monitor stands and chair mats). No product row was modified to mark an anchor.

Everything below is a database measurement: no embedding, reranking or agent
call was made, and the client was an EC2 instance in the cluster's VPC. An
earlier sweep of the same catalog at revision `3f5a379` (16:07 to 16:13 UTC,
before the halfvec and binary indexes existed) returned the same recall and
the same rows at every operating point, with server timings 0.1 to 0.5 ms
higher; it stays in the git history of the artifact and is not repeated here.

## The served index

| Fact | Value |
|---|---|
| Index | `mosaic_catalog_search.real_search_vector_idx`, HNSW, `m=16`, `ef_construction=200`, cosine, total (no `WHERE`) |
| Size | 4,534,624,256 bytes for 553,911 vectors, 8,187 bytes per vector, 2.0× the 4,096-byte fp32 payload |
| Instance | `db.r8g.2xlarge`, Aurora PostgreSQL 18.3, pgvector 0.8.1, `work_mem` 4 MB, `shared_buffers` 41.5 GB |
| Exact baseline | Sequential scan with index and bitmap paths disabled, timed on 5 anchors after the cache was warm: 2,443 ms server (median), 4,087 ms p50 from the client, 2,499,748 shared buffer hits |

The served index is total, so the query without `embedding IS NOT NULL` still
ran as an index scan at 1.12 ms. The slowdown that predicate avoided on the
legacy catalog's partial index does not exist here; the artifact records that
as `missing_predicate.applies = false` instead of restating the old figure.

## Recall against search effort, unfiltered

Recall@10 is id overlap with the seeded exact neighbours, averaged over the
70 anchors. Server times are the p50 across anchors of a warmed second
execution under `EXPLAIN (ANALYZE, BUFFERS)`; client times are the first
execution's wall clock from the in-VPC client. Relaxed ordering, the served
mode:

| ef_search | Recall@10 | Server p50 | Server p95 | Server p99 | Client p50 | Buffer hits |
|---:|---:|---:|---:|---:|---:|---:|
| 40 | 96.0% | 0.530 ms | 0.754 ms | 0.828 ms | 1.066 ms | 758 |
| 80 | 98.0% | 0.813 ms | 1.185 ms | 1.313 ms | 1.382 ms | 1,125 |
| **100 (served)** | **98.0%** | **0.947 ms** | **1.417 ms** | **1.637 ms** | **1.542 ms** | **1,288** |
| 200 | 98.0% | 1.651 ms | 2.580 ms | 2.646 ms | 2.250 ms | 2,052 |
| 400 | 99.86% | 2.716 ms | 4.727 ms | 5.184 ms | 3.439 ms | 3,370 |

Recall reaches 98% at ef_search 80 and does not move again until 400, which
spends 2.6× the buffers of the served point for the last two points. Off,
strict and relaxed scans return the same recall at every unfiltered point
(the artifact's `ef_sweep_by_mode` carries all three), which is expected: with
no filter there is nothing for an iterative scan to recover.

## Filters and iterative scans

Every preset was measured under all three scan modes at the served
ef_search 100 and both scan-memory budgets (4 MB and 8 MB, the served
`work_mem` times scan-memory multipliers of 1 and 2), with the served
`max_scan_tuples` of 20,000. Rows returned are per query out of 10 exact
rows; every anchor had 10 exact neighbours under every preset.

| Preset (matching rows, selectivity) | Off: rows, recall, p50 | Strict 8 MB: rows, recall, p50 | Relaxed 8 MB: rows, recall, p50 |
|---|---|---|---|
| No filter (553,911, 100%) | 10.0, 98.0%, 0.93 ms | 10.0, 98.0%, 0.93 ms | 10.0, 98.0%, 0.93 ms |
| Rating ≥ 4.5 (195,951, 35.4%) | 9.56, 92.7%, 0.93 ms | 10.0, 96.9%, 0.97 ms | 10.0, 97.0%, 0.96 ms |
| Home office only (117,878, 21.3%) | 3.39, 32.4%, 0.92 ms | 10.0, 70.9%, 27.4 ms | 10.0, 76.3%, 26.1 ms |
| Monitors only (8,229, 1.49%) | 2.30, 23.0%, 0.82 ms | 5.23, 39.0%, 47.4 ms | 5.23, 40.7%, 46.2 ms |
| One brand: Dell (3,320, 0.60%) | 0.91, 9.1%, 0.85 ms | 4.76, 40.3%, 45.3 ms | 4.76, 41.3%, 45.7 ms |
| Bose, rating ≥ 4.5 (95, 0.02%) | 0.30, 3.0%, 0.81 ms | 2.46, 19.4%, 51.3 ms | 2.46, 19.4%, 59.5 ms |

What the table establishes:

- **Selectivity alone does not predict the outcome.** The rating filter keeps
  35% of the catalog and loses almost nothing even with the iterative scan
  off. The home-office filter keeps 21% and returns 3.39 rows of 10 with the
  scan off, because the anchors are mostly electronics and their neighbours
  are too.
- **Iterative scans recover rows at a price.** Relaxed ordering fills the
  home-office shortlist and lifts recall to 76% at 26 ms, twenty-eight times
  the unfiltered cost. Under the four narrowest presets it never fills the
  shortlist: the scan stops at the 20,000-tuple limit with 2 to 5 rows.
- **The memory budget matters less than the tuple limit here.** Doubling the
  scan memory from 4 MB to 8 MB moved home office from 9.73 to 10 rows and the
  narrow presets by well under a row. The served `max_scan_tuples` is the
  binding limit for those presets on this catalog. This is the opposite of
  what the legacy catalog showed, and the artifact carries the rows that say
  so rather than a remembered rule.
- **Rows returned is the first thing to read.** Off returned 0.30 rows per
  query under the Bose filter at 0.81 ms and looked fast. Ninety-five products
  match that filter; a shortlist that never fills is the signal.
- **The rows are deterministic; only the timings carry noise.** Every recall
  and rows-returned figure in this table matches the earlier sweep at
  `3f5a379` to four decimals. The graph, the anchors and the ground truth are
  fixed, so a rerun changes milliseconds, not results.

Every plan node in the matrix is an index scan on `real_search_vector_idx`;
no preset made the planner leave the index for a filtered exact scan on this
catalog.

## Representations

The halfvec and binary indexes were built on the served table at 17:19 UTC
the same day (`make db-index-quantized-catalog`, revision `2efb0be`) as
expression indexes over the same fp32 column with the production `m=16,
ef_construction=200`; no row changed and nothing was re-embedded. The build
report is
[`hnsw_quantized_build.json`](../data/benchmarks/hnsw_quantized_build.json):
halfvec 82.5 s and 1,511,555,072 bytes, binary 37.6 s and 240,467,968 bytes.
That report predates the builder's session-settings field, so the memory and
worker settings of those two builds are not recorded and no claim is made
about them.

The comparison ran at the served point (ef_search 100, relaxed ordering, 8 MB
scan memory) over the same 70 anchors against the same fp32 exact ground
truth. Binary rows are a two-pass query: the Hamming index returns the
`rescore` nearest codes, which are re-sorted by exact cosine distance on the
fp32 column before the top 10 is taken.

| Representation | Index size | Bytes per vector | Recall@10 | Server p50 | Server p95 | Server p99 | Client p50 | Buffer hits |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fp32, `real_search_vector_idx` | 4,534,624,256 | 8,187 | 98.0% | 1.236 ms | 1.721 ms | 1.993 ms | 1.805 ms | 1,288 |
| halfvec, `real_search_vector_halfvec_idx` | 1,511,555,072 | 2,729 | 99.29% | 1.850 ms | 2.835 ms | 3.302 ms | 2.416 ms | 1,311 |
| binary, rescore 10, `real_search_vector_binary_idx` | 240,467,968 | 434 | 74.57% | 1.432 ms | 2.229 ms | 3.158 ms | 2.058 ms | 1,703 |
| binary, rescore 20 | 240,467,968 | 434 | 87.14% | 1.520 ms | 2.350 ms | 3.204 ms | 2.136 ms | 1,799 |
| binary, rescore 50 | 240,467,968 | 434 | 96.43% | 1.850 ms | 2.646 ms | 3.472 ms | 2.446 ms | 2,086 |
| binary, rescore 100 | 240,467,968 | 434 | 98.57% | 2.412 ms | 3.152 ms | 4.014 ms | 2.995 ms | 2,565 |
| binary, rescore 200 | 240,467,968 | 434 | 99.14% | 4.265 ms | 5.686 ms | 6.553 ms | 4.834 ms | 4,462 |

Deeper operating points, same anchors and truth:

| Configuration | Recall@10 | Server p50 | Server p95 | Server p99 | Client p50 | Buffer hits |
|---|---:|---:|---:|---:|---:|---:|
| fp32, ef_search 800 | 99.86% | 5.93 ms | 9.33 ms | 11.34 ms | 6.46 ms | 5,696 |
| binary, ef_search 800, rescore 1,400 | 100% | 25.0 ms | 31.2 ms | 35.0 ms | 25.5 ms | 25,224 |
| binary, ef_search 800, rescore 3,000 | 100% | 47.4 ms | 58.4 ms | 62.3 ms | 47.1 ms | 47,248 |

What the tables establish:

- **halfvec costs a third of the storage and loses no recall.** The half
  precision index is 33% of the fp32 index and returned 99.3% recall against
  98.0%. The extra 1.3 points are a property of a differently built graph
  over the same vectors, not evidence that half precision is more accurate;
  the served p50 was 0.6 ms slower in this run.
- **Binary codes trade recall for a 5% footprint, and rescoring buys it
  back.** The Hamming index alone is unusable for a ten-row shortlist (74.6%
  at rescore 10). A 50-row rescore reaches 96.4% at 1.85 ms and a 100-row
  rescore matches the fp32 index (98.6%) at 2.4 ms, with twice the buffer
  reads of the fp32 query.
- **Both quantized paths can reach exact recall, at a cost.** At ef_search
  800 the fp32 index reaches 99.86% at 5.9 ms; the binary index with a
  1,400-row rescore reaches 100% at 25 ms and 25,224 buffers, four times the
  fp32 cost at the same search effort.
- **Sub-2 ms differences are inside the noise.** The fp32 row here (1.236 ms)
  and the unfiltered sweep point at the same settings (0.947 ms) were
  measured minutes apart on the shared cluster. That 0.3 ms spread is the
  noise floor at these points, so a gap of that size between representations
  is not a ranking.

## Index build

Measured separately by `make benchmark-index-build` on the same cluster and
table right after the first retrieval run, each as one plain `CREATE INDEX`
of a benchmark-owned index with the production `m=16, ef_construction=200`;
the serving index was never dropped. Settings are the values the server
reported from `pg_settings` for that session.

| Session settings | Build time | Index size |
|---|---:|---:|
| Aurora defaults: `maintenance_work_mem` 1,057,792 kB (about 1 GiB), `max_parallel_maintenance_workers` 2 | 567.4 s | 4,534,632,448 bytes |
| `maintenance_work_mem` 8 GB, `max_parallel_maintenance_workers` 7 | 98.1 s | 4,534,632,448 bytes |

The memory setting is the lever on this catalog: with 1 GiB the graph no
longer fits in maintenance memory and pgvector builds it in passes. For
context only, the catalog's own projection log recorded 552 s for the
serving index with seven workers and the default memory on 25 September; it
is an earlier build's log line, not part of this measurement.

Both build records carry `source_worktree_dirty: true` because the retrieval
artifact written a step earlier sat untracked in the checkout while they ran;
no source file differed from revision `3f5a379` (first build) or `7bea92f`
(second build). The artifact is
[`hnsw_index_build.json`](../data/benchmarks/hnsw_index_build.json).

## What this measures

- Aurora PostgreSQL 18.3, pgvector 0.8.1, `db.r8g.2xlarge` in `us-east-1`,
  writer `agenticretrievalcorestack-aurorapostgresretrievalc-5wdg4dpl2bg2`.
- Exact ground truth was seeded once by `make db-seed-exact-neighbors`: for
  each batch of ten anchors one pass computes every vector's cosine distance
  into a session table, and each preset's top-50 per anchor is a ranked read
  of that table under the preset's own predicate, ordered by distance and then
  `product_id` so ties are deterministic. The anchor itself is included when
  it passes the filter. Recall is id overlap divided by the exact rows that
  exist, so a filter matching fewer than k rows is scored against those rows;
  none did here.
- Each configuration used one sequential connection. Each query first
  returned product ids, then ran again under `EXPLAIN (ANALYZE, BUFFERS)` for
  warmed database timing and index evidence. Server percentiles are the
  runner's rounded order-statistic percentile over 70 anchors; the first
  anchor's full plan at every operating point is in the plan file.
- Client timings include the in-VPC network and are stored separately. These
  results do not measure cold cache, concurrent users, reranking, agent
  reasoning or end-to-end Shop response time. No database setting or index
  was changed persistently. Background activity on the shared development
  cluster was not controlled.

## Results and rerunning

- [Summary JSON](../data/benchmarks/hnsw_measured.json)
- [Per-query samples, returned ids, exact ids and plan summaries](../data/benchmarks/hnsw_measured.samples.json)
- [Full plans, one per operating point](../data/benchmarks/hnsw_measured.plans.json)
- [Anchor set](../data/benchmarks/hnsw_anchors.json)
- [Quantized index build report](../data/benchmarks/hnsw_quantized_build.json)
- [Runner](../scripts/benchmark_mosaic_scale.py), [seeder](../scripts/seed_exact_neighbors.py), [anchor selection](../scripts/select_hnsw_anchors.py), [quantized index builder](../scripts/build_quantized_indexes.py)
- [Legacy catalog artifact, 20 September 2026](../data/benchmarks/archive/hnsw_measured_2026-09-20_legacy-catalog.json)
  and [17 August 2026](../data/benchmarks/archive/hnsw_measured_2026-08-17.json),
  kept for their earlier catalog, representation and hardware comparisons.
- [Instance comparison](hardware-comparison-2026-09-26.md), published
  separately because it ran on restored copies of the catalog, not on this
  cluster.

With `DATABASE_URL` pointing at the served catalog and a clean checkout:

```sh
make select-hnsw-anchors         # once per catalog; commit the file
make db-seed-exact-neighbors     # about four minutes on this catalog
make db-index-quantized-catalog  # halfvec and binary indexes, about two minutes
make benchmark-hnsw AURORA_INSTANCE_CLASS=db.r8g.2xlarge
make simulate                    # re-baselines the scale projection
```

The runner refuses a dirty checkout, an anchor set selected from another
catalog, unseeded anchor/preset pairs and a missing fp32 index. It measures
the representation comparison only when both quantized indexes are valid and
otherwise records which one is missing. The API compares the recorded catalog
identity with the connected catalog's receipt before labelling these numbers
current.
