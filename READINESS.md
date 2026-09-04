# Mosaic release readiness

This is the release gate for **Build agentic hybrid retrieval with Amazon Aurora
PostgreSQL**. It is not a benchmark report and it does not convert an offline
test pass into deployment evidence.

## Fixed session contract

- exactly three required labs;
- `RETRIEVE -> RANK -> REASON`;
- 500,000 Aurora PostgreSQL product rows and Cohere Embed v4 vectors;
- a 120-product visual cohort over the same catalog;
- 45 minutes of required hands-on work inside a 60-minute session;
- HNSW tuning remains an optional Advanced Lab.

`data/evals/mosaic_labs_missions.json` owns the lab queries, assertions, and
timing. `db/config/retrieval.yaml` owns retrieval limits, RRF `k`, weights, and
trigram threshold.

## Repository gates

Run these against the release candidate:

```bash
make lint
make validate
make validate-db
python scripts/config_tripwire.py
python scripts/retrieval_profile.py --check
python scripts/mission_contract.py --shape-only
cd ui && npm test && npm run build && npm audit --audit-level=moderate
```

These gates prove source shape, deterministic contracts, package integrity, and
offline behavior. They do not prove Aurora connectivity, Bedrock entitlement,
asset transfer, or live-session timing.

## Aurora-backed gates

With `DATABASE_URL` pointing only at the intended Aurora cluster:

```bash
make test
MISSION_GATE_REQUIRE_DB=1 make validate-missions
make validate-evals
FUNCTION_CENSUS_REQUIRE_DB=1 make validate-functions
make db-verify-bootstrap
make score-evals
make validate-lab-1
make validate-lab-2
make validate-lab-3
```

The canonical scorecard is the curated 21-query set. Twenty product-retrieval
queries produce Recall@10, MRR, nDCG@10, per-query metrics, deterministic
fixture checks, and a hash of the exact ranked result set. The 720 generated
cases are filter-contract tests, not retrieval-quality judgments.

## Participant completion proof

The canonical scorecard above is a maintainers' release artifact. It is served
with `artifact_kind = release_baseline` and is attributed to the running
service only when its retrieval fingerprint, models, query-set hashes,
methodology hash, and live retrieval-settings hash all match. It never proves
an attendee's repairs.

The attendee's proof is `POST /api/labs/{lab_id}/proof`, rendered in the
Playground's Prove stage. Labs 1 and 2 run the mission request through the
production search path and report the new `search_event_id`; Lab 3 evaluates
the attendee's own persisted agent run. Each check carries its falsifier, and
`GET /api/labs/state` reports source and applied-database state per lab. Both
are covered by the offline suite (`tests/test_lab_checks.py`,
`tests/test_lab_proof.py`) and by `make validate-lab-{1,2,3}` against Aurora.

## Optional Vector index at scale lens

The committed HNSW artifact (`data/benchmarks/hnsw_measured.json`) was measured
on a different dataset manifest from a dirty worktree, so the lens renders it
as `MEASURED ELSEWHERE` with its provenance until it is re-measured on the
released corpus from a clean checkout. `representations` is served only when
`make db-index-quantized` has built the halfvec and binary indexes on the
connected cluster. Exact-neighbour ground truth still requires
`make db-seed-exact-neighbors` after bootstrap; readiness reports whether it is
seeded. An interrupted concurrent index build is recovered by
`make db-drop-invalid-indexes`, which the `index_creation` bootstrap phase now
runs first.

## Release measurements still owed

- Re-run `make score-evals` with `--write-baseline` and the stage ablation
  after the source freeze: this revision changed SQL and contract files, so the
  scorecard reads pending until then.
- Re-measure or retire the HNSW artifact.

## Clean-account acceptance test

Release readiness requires one recorded Workshop Studio rehearsal:

1. deploy the nested templates in a clean environment;
2. synchronize the 51 embedding-cache objects;
3. run `make db-fetch-embeddings`;
4. verify the pinned manifest SHA-256;
5. run `make db-bootstrap-cached`;
6. save `build/embedding-cache-download-timing.tsv` and
   `build/bootstrap-timings.tsv`; the latter records every load phase,
   `index_creation`, and the measured total;
7. verify 500,000 products, 500,000 embeddings, model ID, dimensions, required
   FTS/trigram/HNSW indexes, evidence rows, and 120 premium products;
8. rehearse Labs 1, 2, and 3, including independent reset and solution paths;
9. rehearse Cohere reranking and Ask Mosaic cold starts;
10. record deployment, transfer, bootstrap, index, first-query, reranker, and
   agent timing;
11. verify laptop, tablet, mobile, and projector layouts.

Until that rehearsal is recorded, these checks are **PENDING RUNTIME
VERIFICATION**. No latency, throughput, or deployment-time claim may be marked
passed from repository inspection alone.

## Release rule

A release candidate is ready only when:

- source and Workshop Studio pin the same immutable source revision;
- Workshop Studio validators and CloudFormation lint pass;
- the three approved Bedrock model IDs match infrastructure, IAM, runtime, and
  intake records;
- all repository and Aurora-backed gates pass;
- the clean-account acceptance record contains real measurements and no
  unresolved participant-path blocker.
