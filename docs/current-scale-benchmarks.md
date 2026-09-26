# Mosaic scale benchmarks

Measured on 26 September 2026 (16:07 to 16:13 UTC) against Mosaic's served
catalog on the development Aurora cluster: **553,911 real source products with
their saved Cohere Embed v4 vectors (1,024 dimensions)**, catalog identity
`c4d5913f8905…`, source revision `3f5a379` with a clean worktree. Query
vectors are the stored embeddings of the **70 anchors** in
`data/benchmarks/hnsw_anchors.json` (anchor-set hash `af84d6ab2763…`): the
fifteen lab products plus a category-stratified hash sample (headphones 13,
monitors 15, chairs 17, long tail 10, and five each from headphone cases,
monitor stands and chair mats). No product row was modified to mark an anchor.

Everything below is a database measurement: no embedding, reranking or agent
call was made, and the client was an EC2 instance in the cluster's VPC.

## The served index

| Fact | Value |
|---|---|
| Index | `mosaic_catalog_search.real_search_vector_idx`, HNSW, `m=16`, `ef_construction=200`, cosine, total (no `WHERE`) |
| Size | 4,534,624,256 bytes for 553,911 vectors, 8,187 bytes per vector, 2.0× the 4,096-byte fp32 payload |
| Instance | `db.r8g.2xlarge`, Aurora PostgreSQL 18.3, pgvector 0.8.1, `work_mem` 4 MB, `shared_buffers` 41.5 GB |
| Exact baseline | Sequential scan with index and bitmap paths disabled, timed on 5 anchors after the cache was warm: 2,516 ms server (median), 4,085 ms p50 from the client, 2,499,748 shared buffer hits |

The served index is total, so the query without `embedding IS NOT NULL` still
ran as an index scan at 1.15 ms. The slowdown that predicate avoided on the
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
| 40 | 96.0% | 0.685 ms | 1.107 ms | 1.785 ms | 1.221 ms | 758 |
| 80 | 98.0% | 0.972 ms | 1.436 ms | 1.546 ms | 1.527 ms | 1,125 |
| **100 (served)** | **98.0%** | **1.125 ms** | **1.636 ms** | **1.991 ms** | **1.683 ms** | **1,288** |
| 200 | 98.0% | 2.077 ms | 3.611 ms | 4.294 ms | 2.568 ms | 2,052 |
| 400 | 99.86% | 3.231 ms | 5.261 ms | 5.553 ms | 3.757 ms | 3,370 |

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
| No filter (553,911, 100%) | 10.0, 98.0%, 1.14 ms | 10.0, 98.0%, 1.18 ms | 10.0, 98.0%, 1.14 ms |
| Rating ≥ 4.5 (195,951, 35.4%) | 9.56, 92.7%, 1.09 ms | 10.0, 96.9%, 1.19 ms | 10.0, 97.0%, 1.17 ms |
| Home office only (117,878, 21.3%) | 3.39, 32.4%, 1.10 ms | 10.0, 70.9%, 34.2 ms | 10.0, 76.3%, 32.1 ms |
| Monitors only (8,229, 1.49%) | 2.30, 23.0%, 1.12 ms | 5.23, 39.0%, 48.4 ms | 5.23, 40.7%, 50.4 ms |
| One brand: Dell (3,320, 0.60%) | 0.91, 9.1%, 1.02 ms | 4.76, 40.3%, 49.2 ms | 4.76, 41.3%, 48.3 ms |
| Bose, rating ≥ 4.5 (95, 0.02%) | 0.30, 3.0%, 0.97 ms | 2.46, 19.4%, 56.0 ms | 2.46, 19.4%, 57.1 ms |

What the table establishes:

- **Selectivity alone does not predict the outcome.** The rating filter keeps
  35% of the catalog and loses almost nothing even with the iterative scan
  off. The home-office filter keeps 21% and returns 3.39 rows of 10 with the
  scan off, because the anchors are mostly electronics and their neighbours
  are too.
- **Iterative scans recover rows at a price.** Relaxed ordering fills the
  home-office shortlist and lifts recall to 76% at 32 ms, thirty times the
  unfiltered cost. Under the four narrowest presets it never fills the
  shortlist: the scan stops at the 20,000-tuple limit with 2 to 5 rows.
- **The memory budget matters less than the tuple limit here.** Doubling the
  scan memory from 4 MB to 8 MB moved home office from 9.73 to 10 rows and the
  narrow presets by well under a row. The served `max_scan_tuples` is the
  binding limit for those presets on this catalog. This is the opposite of
  what the legacy catalog showed, and the artifact carries the rows that say
  so rather than a remembered rule.
- **Rows returned is the first thing to read.** Off returned 0.30 rows per
  query under the Bose filter at 0.97 ms and looked fast. Ninety-five products
  match that filter; a shortlist that never fills is the signal.

Every plan node in the matrix is an index scan on `real_search_vector_idx`;
no preset made the planner leave the index for a filtered exact scan on this
catalog.

## Representations

No halfvec or binary index exists on the served catalog, so the comparison
was not measured rather than borrowed from the legacy catalog. The artifact
carries `representations_unavailable_reason` naming the two missing indexes.
The legacy comparison remains in
`data/benchmarks/archive/hnsw_measured_2026-09-20_legacy-catalog.json`.

## Index build

INDEX_BUILD_SECTION

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
- [Runner](../scripts/benchmark_mosaic_scale.py), [seeder](../scripts/seed_exact_neighbors.py), [anchor selection](../scripts/select_hnsw_anchors.py)
- [Legacy catalog artifact, 20 September 2026](../data/benchmarks/archive/hnsw_measured_2026-09-20_legacy-catalog.json)
  and [17 August 2026](../data/benchmarks/archive/hnsw_measured_2026-08-17.json),
  kept for their earlier catalog, representation and hardware comparisons.
- [Instance comparison](hardware-comparison-2026-09-26.md), published
  separately because it ran on restored copies of the catalog, not on this
  cluster.

With `DATABASE_URL` pointing at the served catalog and a clean checkout:

```sh
make select-hnsw-anchors      # once per catalog; commit the file
make db-seed-exact-neighbors  # about four minutes on this catalog
make benchmark-hnsw AURORA_INSTANCE_CLASS=db.r8g.2xlarge
make simulate                 # re-baselines the scale projection
```

The runner refuses a dirty checkout, an anchor set selected from another
catalog, unseeded anchor/preset pairs and a missing fp32 index. The API
compares the recorded catalog identity with the connected catalog's receipt
before labelling these numbers current.
