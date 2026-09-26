# Instance comparison: db.r8g.2xlarge against db.r8gd.2xlarge

Measured on 26 September 2026 on two clusters restored from Mosaic's
development cluster by copy-on-write clone, both on Aurora I/O-Optimized
storage, each with one writer in `us-east-1b`: `mosaic-hw-r8g-w`
(db.r8g.2xlarge) and `mosaic-hw-r8gd-w` (db.r8gd.2xlarge, Optimized Reads).
Both hold the same 553,911 products, saved Cohere Embed v4 vectors, indexes
and exact ground truth (catalog `c4d5913f8905…`, anchor set `af84d6ab2763…`,
presets hash recorded in the artifact). The client was one EC2 instance
(c7g.xlarge) in the same VPC and availability zone, running
`scripts/benchmark_hardware.py` at source revision `296c7b4` with a clean
worktree. This is a different claim class from the served instrument's
artifact: it describes restored copies under a synthetic load, not the
workshop cluster under participants.

## What was held constant

- Rows, vectors, the HNSW index (`m=16`, `ef_construction=200`) and the
  seeded exact neighbours: identical bytes from the same clone source.
- Engine and extension: Aurora PostgreSQL 18.3, pgvector 0.8.1, the default
  `aurora-postgresql18` parameter groups on both clusters.
- Query text, parameters and settings: the served probe SQL and
  `configure_hnsw` at ef_search 100, relaxed ordering, 20,000 scan tuples,
  scan-memory multiplier 2, k = 10, over the 70 anchors and 6 presets in a
  fixed round-robin sequence shared by every worker.
- Client placement, concurrency levels (1, 4, 8, 16 connections), trial
  duration (60 s), warm-up (45 s at concurrency 1, recorded and never
  counted) and the number of trials (2 per level).

## How cache state was observed rather than assumed

Before and after every phase the runner read `pg_stat_database` block
counters for the database, and after every trial it ran one
`EXPLAIN (ANALYZE, BUFFERS)` of the unfiltered probe in text form, which on
an Optimized Reads instance prints `aurora_orcache_hit` and
`aurora_storage_read` in its `Buffers:` line when they are non-zero. It also
called `aurora_stat_optimized_reads_cache()` on both clusters; the function
exists only where the tiered cache exists. CloudWatch `BufferCacheHitRatio`,
`AuroraOptimizedReadsCacheHitRatio`, `ReadIOPS`, `ReadLatency`,
`CPUUtilization`, `DatabaseConnections` and `FreeableMemory` were fetched per
trial window at one-minute resolution.

## Results

### Default memory: the working set fits, and the tiered cache stays empty

Both writers ran the default `aurora-postgresql18` parameter group:
`shared_buffers` 41.5 GiB on the r8g writer and 39.5 GiB on the r8gd writer
(Aurora reserves memory for the tiered cache on Optimized Reads instances).
The working set is 13.0 GB: 8.5 GB of table and TOAST plus the 4.53 GB
index. `pg_prewarm` loaded 127,744 heap, 815,711 TOAST and 553,543 index
blocks on each side (9.8 s and 11.1 s). During every counted trial
`pg_stat_database.blks_read` did not move on either instance, CloudWatch
`BufferCacheHitRatio` read 100%, `aurora_stat_optimized_reads_cache()` on
the r8gd writer reported 262 GB total and 32 kB used, its
`AuroraOptimizedReadsCacheHitRatio` was 0, and no EXPLAIN printed
`aurora_orcache_hit` or `aurora_storage_read`. Nothing was evicted, so the
NVMe cache had nothing to serve. This is the honest result for a catalog of
this size on instances of this class: the comparison below is a CPU and
memory-bandwidth comparison, not a storage one.

| Concurrency | Instance | Queries in 60 s | Throughput | p50 | p95 | p99 | Recall@10 | Errors |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | r8g | 2,148 / 2,188 | 35.8 / 36.5 q/s | 13.5 / 14.6 ms | 70.8 / 70.1 ms | 73.5 / 72.5 ms | 0.621 / 0.624 | 0 |
| 1 | r8gd | 2,118 / 2,111 | 35.3 / 35.2 q/s | 17.0 / 17.1 ms | 70.8 / 70.9 ms | 72.4 / 72.7 ms | 0.621 / 0.621 | 0 |
| 4 | r8g | 8,196 / 8,257 | 136.5 / 137.5 q/s | 15.2 / 15.3 ms | 73.9 / 73.2 ms | 83.9 / 82.7 ms | 0.621 / 0.622 | 0 |
| 4 | r8gd | 7,952 / 7,914 | 132.4 / 131.8 q/s | 17.5 / 15.9 ms | 74.8 / 75.0 ms | 83.1 / 84.0 ms | 0.621 / 0.622 | 0 |
| 8 | r8g | 15,676 / 15,625 | 261.0 / 260.2 q/s | 15.6 / 15.8 ms | 77.7 / 78.3 ms | 83.8 / 84.1 ms | 0.621 / 0.621 | 0 |
| 8 | r8gd | 14,971 / 14,991 | 249.3 / 249.6 q/s | 18.5 / 18.3 ms | 80.8 / 80.4 ms | 86.0 / 85.8 ms | 0.621 / 0.621 | 0 |
| 16 | r8g | 17,225 / 17,507 | 286.8 / 291.5 q/s | 40.9 / 41.0 ms | 121.2 / 120.2 ms | 147.6 / 143.8 ms | 0.621 / 0.622 | 0 |
| 16 | r8gd | 15,557 / 15,585 | 259.1 / 259.4 q/s | 43.5 / 41.5 ms | 150.8 / 151.7 ms | 180.0 / 179.9 ms | 0.621 / 0.621 | 0 |

Each cell is trial 1 / trial 2. Recall is the mean over the mixed workload
(every preset, including the narrow ones the served settings cannot fill),
and it is the same on both instances to three decimals: the instances
returned the same rows. Both saturate their eight vCPUs at 16 connections
(CloudWatch CPU 81% and 96% on the r8gd writer's two trials); throughput
stops scaling between 8 and 16 connections and p50 roughly triples. The
r8g writer completed 3 to 11% more queries per second at every level and
had lower p99 at 16 connections (144 to 148 ms against 180 ms). A single
unfiltered probe under EXPLAIN after each trial ran in 0.41 to 0.54 ms on
the r8g writer and 0.61 to 0.69 ms on the r8gd writer, all 705 buffers hit,
none read.

Index build, one plain `CREATE INDEX` per instance with `maintenance_work_mem`
8 GB and 7 parallel maintenance workers: 91.3 s on the r8g writer, 100.2 s on
the r8gd writer, 4,534,632,448 bytes each. Nothing about the build touched
local storage that the Aurora build path would use differently, and the
result says so.

## Cost

On-demand, us-east-1, Aurora PostgreSQL I/O-Optimized instance hours
(AWS Price List API, `InstanceUsageIOOptimized`): db.r8g.2xlarge 1.436 USD/h,
db.r8gd.2xlarge 1.6224 USD/h. Cost per million successful queries at the
recall both instances delivered:

| Concurrency | r8g | r8gd |
|---:|---:|---:|
| 1 | 10.94 to 11.15 USD | 12.78 to 12.81 USD |
| 4 | 2.90 to 2.92 USD | 3.40 to 3.42 USD |
| 8 | 1.53 USD | 1.81 USD |
| 16 | 1.37 to 1.39 USD | 1.74 USD |

At matched recall the r8gd writer cost 13% more per hour and 17 to 26% more
per query, because it also completed fewer queries. With the working set in
memory there is no workload here that the tiered cache could have made
cheaper.

## Limitations

- These are restored copies under a synthetic round-robin load from one
  client, not the workshop cluster under participants. Two trials per level
  is enough to show the numbers repeat, not to bound their variance.
- The workload mixes the served instrument's six presets equally, so the
  narrow presets that never fill their shortlist dominate the latency tail
  and pull the mean recall to 0.62; the comparison is between instances, not
  a statement about the served operating point (see
  `current-scale-benchmarks.md` for that).
- Client latency includes the in-VPC network and the client's own scheduling
  at 16 threads on a four-vCPU instance; server-side EXPLAIN samples are
  single warmed executions.
- CloudWatch samples are one-minute averages over windows that include the
  neighbouring minute, so the `ReadIOPS` and `BufferCacheHitRatio` values for
  the first trial on each side still carry the prewarm.
- A first, aborted attempt ran before the prewarm existed and measured cold
  index reads on the r8g clone (42 queries in a minute, p99 13.4 s at one
  connection). It was discarded and is mentioned only so the prewarm step's
  reason is on record; its log stayed on the client.
- A separately labelled small-memory pair (both clusters on a
  `shared_buffers` 2 GB parameter group) is reported below when available; it
  is the configuration in which the tiered cache can participate.

## Artifacts

- [Summary](../data/benchmarks/hardware_comparison_default-memory.json)
- [Per-query records and errors](../data/benchmarks/hardware_comparison_default-memory.samples.json)
- [Runner](../scripts/benchmark_hardware.py)
