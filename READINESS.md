# Mosaic release readiness

This is the release gate for **Build agentic hybrid retrieval with Amazon Aurora
PostgreSQL**. It is not a benchmark report and it does not convert an offline
test pass into deployment evidence.

## Fixed session contract

- exactly three required labs;
- `RETRIEVE -> RANK -> REASON`;
- 553,911 real source products and saved Cohere Embed v4 vectors in Aurora;
- no historical synthetic products, reviews or vocabulary in fresh workshops;
- 40 minutes of required hands-on work, including completion, inside a 60-minute session;
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
make validate-config
make validate-release-workflow
uv run python scripts/mission_contract.py --shape-only
PYTHONPATH=. uv run pytest -q
make mcp-install && make mcp-test && make mcp-wheel-smoke
cd ui && npm test && npm run build && npm audit --audit-level=moderate
```

This is the list `.github/workflows/ci.yml` runs on every push and pull
request; [the development guide](docs/development.md) explains the common subset.
The offline pytest run covers the whole suite except the files marked `aurora`, which `tests/conftest.py` skips
without a `DATABASE_URL`. These gates prove source shape, deterministic
contracts, package integrity, and offline behavior. They do not prove Aurora
connectivity, Bedrock entitlement, asset transfer, or live-session timing.

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

The canonical set contains nine real-catalog requests: eight product-retrieval
cases for Recall@10, MRR and nDCG@10, plus one agent-contract case checked
through Lab 3. The twelve historical canonical requests and 720 generated
filter cases live separately under `data/evals/historical/`. Historical scores
do not certify the real catalog; a reviewed real-catalog baseline is still owed.

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

The committed HNSW measurements describe a historical catalog. They do not
certify the 553,911-product real catalog. The service withholds the historical
instrument when the selected catalog is incompatible and explains the reason.
Semantic retrieval and the required labs still use the real catalog's HNSW
index. Re-enabling the optional instrument requires compatible real anchors,
filter presets, exact-neighbour ground truth and fresh measurements; see
[the benchmark methodology](docs/benchmark-methodology.md).

## Optional flex-time beats

None of these sits on the required path, none is proved by the gates above, and
none deploys an AgentCore resource. Removing any of them leaves the three
labs, the completion gate, and the scorecard untouched.

- **The Gateway appendix** in `docs/mcp-interoperability.md` ("The gate is not
  the guard") is documentation. `scripts/tool_contracts.py --check` proves the
  portable boundary that exists locally; no gate here proves a deployed
  Amazon Bedrock AgentCore Gateway, and none claims one.
- **AgentCore Observability** (`service/telemetry.py`,
  `service/telemetry_contract.py`, `docs/telemetry-contract.md`) is off unless
  an operator installs the optional `agentcore-observability` extra and sets
  `MOSAIC_AGENTCORE_OBSERVABILITY=true`. `tests/test_telemetry_contract.py`
  covers the projection's shape, its default-off behavior, and its content
  exclusions offline. Whether spans arrive in an operator's own collector or in
  CloudWatch is **PENDING RUNTIME VERIFICATION**.
- **AgentCore Runtime** (`deploy/agentcore/`, `docs/agentcore-runtime.md`)
  ships a container and a two-route adapter (`GET /ping`, `POST /invocations`)
  that mounts the service whole. On 17 September 2026 the ARM64 image built and
  ran locally against Aurora and Bedrock: health, readiness, public downloads,
  and a grounded invocation passed. This verifies the packaged process; a
  managed Runtime endpoint has not been deployed from this repository. A
  pre-provisioned endpoint in an event account is a facilitator call-out, not a
  participant step, and no lab depends on it. Managed routing, the execution
  role, and VPC attachment remain **PENDING RUNTIME VERIFICATION** until an
  endpoint is deployed and rehearsed.
- **Postgres 18 facts** (`docs/postgres-18.md`) records the engine and
  extension versions the connected cluster reports and what this pipeline uses.
  It makes no version-to-version performance claim, and none may be added until
  one is measured on this corpus.

## Release measurement checks

The committed canonical scorecard and stage ablation record their measurement
dates and immutable source revisions. The running service checks their retrieval, methodology,
model, query-set, and configuration identities before attributing them.
The 17 September audit concerned the historical catalog. Its scorecard and
HNSW attribution do not certify the current catalog or participant repairs.

Run `make score-evals` from the clean release candidate to detect live quality
regressions. If a covered source or configuration change invalidates the
baseline, review the new ranked results before using `--write-baseline`, then
re-measure the stage ablation. Re-measure the HNSW artifact when its corpus or
measurement conditions change.

## Clean-account acceptance test

Release readiness requires one recorded Workshop Studio rehearsal:

1. deploy the nested templates in a clean environment;
2. synchronize the three `real-catalog/real-catalog.tar.gz.part-*` objects;
3. join and verify them with `scripts/real_catalog_cache.py join`;
4. confirm the joined archive's SHA-256 matches `db/config/real-catalog-cache.json`;
5. run `make db-bootstrap-schema` (shared schemas and lab tables, no synthetic rows);
6. save `build/bootstrap-timings.tsv` and restore with
   `--report build/real-catalog-restore.json` to record schema, restore and index times;
7. run `make db-verify-bootstrap` to verify the pinned 553,911 real products and
   saved vectors, required FTS/trigram/HNSW indexes, real vocabulary and receipts,
   with zero historical products, brands or search documents;
8. rehearse Labs 1, 2, and 3, including independent reset and solution paths;
9. rehearse Cohere reranking and Ask Mosaic cold starts, recording prior model
   canaries or requests; warmed probes cannot support a cold-start claim;
10. record deployment, transfer, bootstrap, index, first-query, reranker, and
   agent timing;
11. verify laptop, tablet, mobile, and projector layouts.

The [26 September fresh-account record](docs/evidence/fresh-account-2026-09-26.md)
verifies deployment, real-only restore, repeated lab repairs, access controls,
bounded load and browser checks for its recorded source revision. The broader
rehearsal remains incomplete: physical projector checks, human completion timing,
controlled UI race checks, cold-start timings and reviewed relevance measurements
are still owed.
Later source revisions need their own acceptance evidence.

## Release rule

A release candidate is ready only when:

- source and Workshop Studio pin the same immutable source revision;
- Workshop Studio validators and CloudFormation lint pass;
- the three approved Bedrock model IDs match infrastructure, IAM, runtime, and
  intake records;
- all repository and Aurora-backed gates pass;
- the clean-account acceptance record contains real measurements and no
  unresolved participant-path blocker.
