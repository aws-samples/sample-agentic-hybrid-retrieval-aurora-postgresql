# Mosaic scale benchmarks

Measured on 3 October 2026 (19:01 to 19:18 UTC) against Mosaic's served
catalog on the development Aurora cluster: **553,911 real source products with
their saved Cohere Embed v4 vectors (1,024 dimensions)**, catalog identity
`c4d5913f8905…`, source revision `725b97a` with a clean worktree. Query
vectors are the stored embeddings of the **73 anchors** in
`data/benchmarks/hnsw_anchors.json` (anchor-set hash `99e31e05b239…`): the
eighteen lab products plus a category-stratified hash sample of 55 (ten each
from headphones, monitors, chairs and the long tail, and five each from
headphone cases, monitor stands and chair mats). By category the set holds
headphones 16, monitors 15, chairs 17, long tail 10 and five of each accessory
kind. No product row was modified to mark an anchor.

Everything below is a database measurement: no embedding, reranking or agent
call was made. Server times come from `EXPLAIN (ANALYZE, BUFFERS)` and exclude
the network. The client was a workstation outside AWS, so each client
wall-clock time includes an internet round trip of about 40 ms; those times
stay in the artifact but are not tabulated here.

This replaces the 26 September measurement over the earlier 70-anchor set
(`af84d6ab2763…`, revision `2efb0be`, an EC2 client in the cluster's VPC),
which stays in the git history of the artifact. That set predates the three
Logitech Zone 900 listings the labs now use, and the 27 September
reclassification changed three of its sampled anchors; 67 anchors are common to
both sets.

## The served index

| Fact | Value |
|---|---|
| Index | `mosaic_catalog_search.real_search_vector_idx`, HNSW, `m=16`, `ef_construction=200`, cosine, total (no `WHERE`) |
| Size | 4,535,148,544 bytes for 553,911 vectors, 8,188 bytes per vector, 2.0× the 4,096-byte fp32 payload |
| Instance | `db.r8g.2xlarge`, Aurora PostgreSQL 18.3, pgvector 0.8.1, `work_mem` 4 MB, `shared_buffers` 41.5 GB |
| Exact baseline | Sequential scan with index and bitmap paths disabled, timed on 5 anchors after the cache was warm: 2,446 ms server (median), 2,508,454 shared buffer hits |

Every index is slightly larger than on 26 September (this one by 524,288
bytes). The 27 September reclassification rewrote 51,248 rows of
`product_document` without HOT updates, and the 50,776 dead row versions it
left had not been vacuumed when this ran. No vector changed. The same
relabelling is why `Monitors only` now matches 8,205 rows instead of 8,229.

The served index is total, so the query without `embedding IS NOT NULL` still
ran as an index scan at 1.23 ms. The slowdown that predicate avoided on the
legacy catalog's partial index does not exist here; the artifact records that
as `missing_predicate.applies = false` instead of restating the old figure.

## Recall against search effort, unfiltered

Recall@10 is id overlap with the seeded exact neighbours, averaged over the
73 anchors. Server times are the p50 across anchors of a warmed second
execution under `EXPLAIN (ANALYZE, BUFFERS)`. Relaxed ordering, the served
mode:

| ef_search | Recall@10 | Server p50 | Server p95 | Server p99 | Buffer hits |
|---:|---:|---:|---:|---:|---:|
| 40 | 96.71% | 0.663 ms | 0.883 ms | 1.043 ms | 738 |
| 80 | 98.63% | 0.916 ms | 1.291 ms | 1.405 ms | 1,103 |
| **100 (served)** | **98.63%** | **1.047 ms** | **1.497 ms** | **1.574 ms** | **1,265** |
| 200 | 98.63% | 1.816 ms | 2.689 ms | 2.781 ms | 2,032 |
| 400 | 100% | 3.092 ms | 4.837 ms | 5.077 ms | 3,368 |

Recall reaches 98.63% at ef_search 80 and does not move again until 400, which
returns every exact neighbour and spends 2.7× the buffers of the served point.
Off, strict and relaxed scans return the same recall at every unfiltered point
(the artifact's `ef_sweep_by_mode` carries all three), which is expected: with
no filter there is nothing for an iterative scan to recover.

## Filters and iterative scans

Every preset was measured under all three scan modes at the served
ef_search 100 and both scan-memory budgets (4 MB and 8 MB, the served
`work_mem` times scan-memory multipliers of 1 and 2), with the served
`max_scan_tuples` of 20,000. The table shows the 8 MB runs; a scan that is off
uses no scan memory. Rows returned are per query out of 10 exact rows; every
anchor had 10 exact neighbours under every preset.

| Preset (matching rows, selectivity) | Off: rows, recall, p50 | Strict 8 MB: rows, recall, p50 | Relaxed 8 MB: rows, recall, p50 |
|---|---|---|---|
| No filter (553,911, 100%) | 10.0, 98.6%, 0.97 ms | 10.0, 98.6%, 1.13 ms | 10.0, 98.6%, 1.02 ms |
| Rating ≥ 4.5 (195,951, 35.4%) | 9.41, 92.2%, 1.13 ms | 10.0, 97.8%, 1.09 ms | 10.0, 98.0%, 1.23 ms |
| Home office only (117,878, 21.3%) | 3.25, 31.1%, 1.07 ms | 10.0, 71.4%, 32.8 ms | 10.0, 76.3%, 30.9 ms |
| Monitors only (8,205, 1.48%) | 2.15, 21.5%, 1.12 ms | 4.84, 32.0%, 48.8 ms | 4.84, 34.1%, 48.6 ms |
| One brand: Dell (3,320, 0.60%) | 0.90, 9.0%, 1.12 ms | 4.96, 41.6%, 49.2 ms | 4.96, 42.6%, 51.7 ms |
| Bose, rating ≥ 4.5 (95, 0.02%) | 0.29, 2.9%, 1.11 ms | 2.82, 23.8%, 55.5 ms | 2.82, 23.8%, 55.1 ms |

What the table establishes:

- **Selectivity alone does not predict the outcome.** The rating filter keeps
  35% of the catalog and loses little even with the iterative scan off. The
  home-office filter keeps 21% and returns 3.25 rows of 10 with the scan off,
  because the anchors are mostly electronics and their neighbours are too.
- **Iterative scans recover rows at a price.** Relaxed ordering fills the
  home-office shortlist and lifts recall to 76.3% at 30.9 ms, about thirty
  times the unfiltered cost. Under the three narrowest presets it never fills
  the shortlist and stops with 2.8 to 5.0 rows.
- **The memory budget matters less than the tuple limit here.** Doubling the
  scan memory from 4 MB to 8 MB moved home office from 9.79 to 10 rows and the
  three narrow presets by 0.3 to 0.6 rows, while their relaxed p50 rose from
  33–46 ms to 49–55 ms. The served `max_scan_tuples` is the main limit for
  those presets on this catalog. This is the opposite of what the legacy
  catalog showed, and the artifact carries the rows that say so rather than a
  remembered rule.
- **Rows returned is the first thing to read.** Off returned 0.29 rows per
  query under the Bose filter at 1.11 ms and looked fast. Ninety-five products
  match that filter; a shortlist that never fills is the signal.
- **The rows are deterministic; only the timings carry noise.** On
  26 September two sweeps of the earlier 70-anchor set, at `3f5a379` and
  `2efb0be`, returned the same recall and rows to four decimals. The graph, the
  anchors and the ground truth are fixed, so a rerun changes milliseconds, not
  results. This 73-anchor set was measured once.

Every plan node in the matrix is an index scan on `real_search_vector_idx`;
no preset made the planner leave the index for a filtered exact scan on this
catalog.

## Representations

The halfvec and binary indexes were built on the served table at 17:19 UTC
on 26 September (`make db-index-quantized-catalog`, revision `2efb0be`) as
expression indexes over the same fp32 column with the production `m=16,
ef_construction=200`; no row changed and nothing was re-embedded. The build
report is
[`hnsw_quantized_build.json`](../data/benchmarks/hnsw_quantized_build.json):
halfvec 82.5 s and 1,511,555,072 bytes, binary 37.6 s and 240,467,968 bytes.
Both have grown slightly since, for the reason given above. That report
predates the builder's session-settings field, so the memory and worker
settings of those two builds are not recorded and no claim is made about them.

The comparison ran at the served point (ef_search 100, relaxed ordering, 8 MB
scan memory) over the same 73 anchors against the same fp32 exact ground
truth. Binary rows are a two-pass query: the Hamming index returns the
`rescore` nearest codes, which are re-sorted by exact cosine distance on the
fp32 column before the top 10 is taken.

| Representation | Index size | Bytes per vector | Recall@10 | Server p50 | Server p95 | Server p99 | Buffer hits |
|---|---:|---:|---:|---:|---:|---:|---:|
| fp32, `real_search_vector_idx` | 4,535,148,544 | 8,188 | 98.63% | 1.134 ms | 1.581 ms | 1.611 ms | 1,265 |
| halfvec, `real_search_vector_halfvec_idx` | 1,511,833,600 | 2,729 | 98.63% | 1.750 ms | 2.568 ms | 2.670 ms | 1,281 |
| binary, rescore 10, `real_search_vector_binary_idx` | 240,500,736 | 434 | 76.58% | 1.339 ms | 2.023 ms | 2.900 ms | 1,669 |
| binary, rescore 20 | 240,500,736 | 434 | 89.18% | 1.448 ms | 2.101 ms | 2.849 ms | 1,766 |
| binary, rescore 50 | 240,500,736 | 434 | 97.53% | 1.633 ms | 2.290 ms | 3.117 ms | 2,055 |
| binary, rescore 100 | 240,500,736 | 434 | 99.18% | 2.118 ms | 2.897 ms | 3.650 ms | 2,539 |
| binary, rescore 200 | 240,500,736 | 434 | 99.73% | 4.041 ms | 5.418 ms | 5.673 ms | 4,459 |

Deeper operating points, same anchors and truth:

| Configuration | Recall@10 | Server p50 | Server p95 | Server p99 | Buffer hits |
|---|---:|---:|---:|---:|---:|
| fp32, ef_search 800 | 100% | 5.40 ms | 8.27 ms | 8.78 ms | 5,679 |
| binary, ef_search 800, rescore 1,400 | 100% | 24.1 ms | 30.1 ms | 31.1 ms | 25,372 |
| binary, ef_search 800, rescore 3,000 | 100% | 46.4 ms | 56.3 ms | 57.9 ms | 47,744 |

What the tables establish:

- **halfvec costs a third of the storage and loses no recall.** The half
  precision index is 33% of the fp32 index and returned the same 98.63%. On
  26 September, over the 70-anchor set, it returned 99.3% against 98.0%; that
  gap belonged to those anchors and a differently built graph, not to half
  precision, and it did not recur here. Its served p50 was 0.6 ms slower in
  both runs.
- **Binary codes trade recall for a 5% footprint, and rescoring buys it
  back.** The Hamming index alone is unusable for a ten-row shortlist (76.6%
  at rescore 10). A 50-row rescore reaches 97.5% at 1.63 ms and a 100-row
  rescore passes the fp32 index (99.2% against 98.6%) at 2.12 ms, with twice
  the buffer reads of the fp32 query.
- **Both paths can reach exact recall, at a cost.** At ef_search 800 the fp32
  index returns every exact neighbour at 5.4 ms; the binary index with a
  1,400-row rescore does too, at 24.1 ms and 25,372 buffers, about four and a
  half times the fp32 cost at the same search effort.
- **Small timing gaps are not rankings.** The same unfiltered fp32 query at the
  served settings measured 1.017 ms in the filter matrix, 1.047 ms in the
  sweep and 1.134 ms in this comparison, minutes apart on the shared cluster.
  Binary at rescore 10 to 50 sits within 0.5 ms of fp32. halfvec's 0.6 ms gap
  is larger than that 0.12 ms spread and repeated across both runs, but no
  trial was repeated within a run.

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
  runner's rounded order-statistic percentile over 73 anchors; the first
  anchor's full plan at every operating point is in the plan file.
- Client timings include the internet path from the workstation and are
  stored separately. These results do not measure cold cache, concurrent
  users, reranking, agent reasoning or end-to-end Shop response time. No
  database setting or index was changed persistently. Background activity on
  the shared development cluster was not controlled, and the dead row
  versions described above were present.

## Results and rerunning

- [Summary JSON](../data/benchmarks/hnsw_measured.json)
- [Per-query samples, returned ids, exact ids and plan summaries](../data/benchmarks/hnsw_measured.samples.json)
- [Full plans, one per operating point](../data/benchmarks/hnsw_measured.plans.json)
- [Anchor set](../data/benchmarks/hnsw_anchors.json)
- [Quantized index build report](../data/benchmarks/hnsw_quantized_build.json)
- [Runner](../scripts/bench/benchmark_mosaic_scale.py), [seeder](../scripts/bench/seed_exact_neighbors.py), [anchor selection](../scripts/bench/select_hnsw_anchors.py), [quantized index builder](../scripts/bench/build_quantized_indexes.py)
- [Legacy catalog artifact, 20 September 2026](../data/benchmarks/archive/hnsw_measured_2026-09-20_legacy-catalog.json)
  and [17 August 2026](../data/benchmarks/archive/hnsw_measured_2026-08-17.json),
  kept for their earlier catalog, representation and hardware comparisons.
- [Instance comparison](hardware-comparison-2026-09-26.md), published
  separately because it ran on restored copies of the catalog, not on this
  cluster.

With `DATABASE_URL` pointing at the served catalog and a clean checkout:

```sh
make select-hnsw-anchors         # once per catalog; commit the file
make db-seed-exact-neighbors     # 22 minutes for the 73 anchors on 3 October
make db-index-quantized-catalog  # halfvec and binary indexes, about two minutes
make benchmark-hnsw AURORA_INSTANCE_CLASS=db.r8g.2xlarge  # 17 minutes from outside AWS
make simulate                    # re-baselines the scale projection
```

The runner refuses a dirty checkout, an anchor set selected from another
catalog, unseeded anchor/preset pairs and a missing fp32 index. It measures
the representation comparison only when both quantized indexes are valid and
otherwise records which one is missing. The API compares the recorded catalog
identity with the connected catalog's receipt before labelling these numbers
current.
