# HNSW performance lab

## Objective and scope

Use the optional `hnsw-performance` checkpoint in
`data/evals/mosaic_labs_missions.json` to explain a measured recall and latency
trade-off. The required Retrieve lab proves candidate recovery and eligibility;
it does not require rebuilding indexes or running a benchmark matrix.

Open **Scale & HNSW** at `/mosaic-labs/hnsw`. Establish whether each value comes
from the connected Aurora cluster, a recorded measurement, or a projection
before interpreting it. The graph illustration explains HNSW; its links and
path are not a recorded Aurora traversal.

## Participant sequence

1. **State the question.** Choose a filter preset and predict whether the
   approximate search will return enough eligible neighbors. Use the declared
   checkpoint request when checking its target; do not substitute another query
   and treat the result as the same proof.
2. **Read the evidence identity.** Record the catalog/source attribution,
   instance class, extension version, index definition and size, query sample,
   filter and runtime settings. A recorded artifact from another catalog is
   historical evidence even when the current index has the same name.
3. **Compare approximate results with exact filtered neighbors.** Inspect
   returned-row count as well as Recall@K. Correct filters can still leave too
   few results after an approximate scan. A full result window can also omit
   the exact neighbors, so count alone does not establish recall.
4. **Change one setting.** Compare search breadth or iterative-scan settings
   while holding the query sample, filter, representation and memory budget
   constant. Use the recorded matrix to distinguish those dimensions; do not
   attribute a change to one setting if another also changed.
5. **Explain the plan and trade-off.** Name the actual scan node and index,
   returned rows and available filter statistics. Compare recall with server
   time and index size. State which operating point meets the workload's needs
   and what the measurement does not establish.

Ask: "If every returned product is eligible, what evidence could still show
that this search missed good candidates?" The answer should refer to exact
filtered ground truth, not a larger-looking result list or a faster timer.

## Failure and recovery

| Observation | Inspect next | Proof after correction |
|---|---|---|
| Filtered search returns too few rows or loses recall | Applied HNSW settings, iterative scan and memory budget, then the actual plan | Repeat the same query and filter; compare both exact-neighbor recall and returned count |
| Apparent perfect recall comes from a sequential scan | Whether exact-baseline planner settings leaked into the ANN run | The ANN plan uses the intended access path and recall is recomputed |
| Plan shows only an outer function scan | The served probe's inner plan | Name the underlying index node; the wrapper alone does not prove HNSW ran |
| Recorded data does not match the connected catalog | Attribution banner and artifact provenance | Label it historical, or collect a fresh measurement before claiming a current result |
| Probe cannot run because an index or exact-neighbor baseline is absent | Provisioning and bootstrap checks | Restore the required Aurora resources and rerun; do not replace the missing measurement with a projection |

These are diagnosis steps, not promises that increasing a setting always fixes
recall. Inspect the measured constraint before choosing a repair.

## Instructor measurement path

`make select-hnsw-anchors` records the query anchors for the served catalog
(the lab products plus a category-stratified hash sample) in
`data/benchmarks/hnsw_anchors.json`; `make check-hnsw-anchors` recomputes the
selection and refuses drift. `make db-seed-exact-neighbors` then stores the
exact neighbours of every anchor under every preset, keyed by the catalog,
anchor-set and predicate identities.

`make benchmark-hnsw` calls `scripts/benchmark_mosaic_scale.py`. From a clean
worktree with `DATABASE_URL` pointing at Aurora and `AURORA_INSTANCE_CLASS`
matching the connected instance, it measures the served catalog's fp32 index
(and the halfvec and binary indexes only where they exist) using the production
probe SQL and the served catalog's `configure_hnsw`, across every
iterative-scan mode. The Make target owns the experiment matrix; retrieval
defaults remain in `db/config/retrieval.yaml`.

The runner writes `data/benchmarks/hnsw_measured.json`, its raw sample file and
its plan file. Retain all three. It recomputes exact fp32 neighbors for each
filter, records source, catalog and anchor-set identity, and checks that the
unfiltered plans use the expected index. It does not rebuild indexes. Build
duration is a separate measurement: `make benchmark-index-build` times a
benchmark-owned index on the same table with the production build parameters
and records the worker and memory settings the server used.

Each query runs once for product IDs and again under `EXPLAIN`. Server
percentiles describe the warmed second execution across the sampled anchors;
client times are recorded separately. One sequential connection does not
establish cold-cache performance, throughput, concurrency behavior or an
end-to-end agent latency claim.

The supporting `scripts/benchmark_hnsw.py` runner also persists its runs to
`mosaic_bench.run` and `mosaic_bench.measurement`. Do not confuse that runner's
outputs with the current Make target. `scripts/simulate_scale.py` emits
`simulated_calibrated` projections, not larger physical measurements.

### Exact-baseline isolation

The runners disable index and bitmap scans as session settings for exact
ground truth, then reset both in a `finally` block. They deliberately avoid
`SET LOCAL` here: a nested psycopg transaction can become a savepoint, and
releasing it does not restore a transaction-local setting. Leaked settings can
make the ANN run use a sequential scan and report perfect recall for the wrong
reason. Confirm both paths from their recorded plans.

### Further experiments

Partial indexes, partitioning and larger physical catalogs belong in
separately provisioned Aurora experiments. Build duration comes from
`make benchmark-index-build`, and concurrent load and instance-class
comparisons from `make benchmark-hardware`, which runs on restored copies of
the catalog from an in-VPC client and publishes its results apart from the
served instrument's artifact (see `docs/current-scale-benchmarks.md`).

## Presentation rule

Keep the artifact's attribution visible. Say **measured** only for the catalog,
hardware, sample and settings actually recorded. Label scale extrapolations as
projections and illustrative data as examples. A new embedding count or an
index definition alone does not refresh a historical performance result.
