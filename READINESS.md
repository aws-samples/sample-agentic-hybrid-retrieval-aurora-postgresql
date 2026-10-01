# Mosaic release readiness

This is the release gate for **Build agentic hybrid retrieval with Amazon Aurora
PostgreSQL**. It is not a benchmark report and it does not convert an offline
test pass into deployment evidence.

## Fixed session contract

- exactly three required labs;
- `RETRIEVE -> RANK -> RE-RANK -> REASON`;
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
uv run python scripts/checks/mission_contract.py --shape-only
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

The canonical set contains ten real-catalog requests: nine product-retrieval
cases for Recall@10, MRR and nDCG@10, plus one agent-contract case checked
through Lab 3. The twelve historical canonical requests and 720 generated
filter cases live separately under `data/evals/historical/`. Historical scores
do not certify the real catalog. The committed real-catalog baseline over the
nine product-retrieval cases reads Recall@10 1.0,
MRR 0.759 and nDCG@10 0.803; both release checks passed and both eligibility
fixtures held. `data/evals/canonical_scorecard.json` records its measurement date
and source revision. The baseline and every later check search with the query
vectors recorded in `data/evals/canonical_query_vectors.json`, because Bedrock
returns a slightly different vector for the same query on each call.

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

The committed HNSW anchors and measurements now describe the selected real
`reviews-2023-v2` catalog. The service checks corpus and artifact compatibility
before serving the instrument. These measurements cover the recorded anchor set
and conditions; they do not establish relevance quality or a performance promise
for another Aurora instance. See [the methodology](docs/benchmark-methodology.md).

## Optional flex-time beats

None of these sits on the required participant path. AgentCore Memory is
provisioned and connected by the workshop stack; its exercise remains optional.
Runtime and Gateway are required by Lab 3; observability export and the
extensions below do not add a required lab.

- **AgentCore Memory** uses four built-in strategies: semantic facts, user
  preferences, session summaries and episodes with actor-scoped reflections.
  All four can supply agent context. Readiness requires the expected active
  strategies and namespaces. Bootstrap's `scripts/checks/verify_session_memory.py`
  checks event storage, strategy reads, recall and actor isolation through the
  runtime API. The [29 September rehearsal](docs/evidence/fresh-account-2026-09-29.md)
  verified extraction and a cited answer in a new session, with an earlier
  grounding refusal retained in the evidence.
- **Gateway documentation** in `docs/mcp-interoperability.md` explains why
  transport authentication does not replace the application authorization boundary.
  `scripts/checks/tool_contracts.py --check` checks local contracts;
  `make verify-agent` exercises the deployed Gateway and Aurora tools.
- **AgentCore Observability** (`service/telemetry.py`,
  `service/telemetry_contract.py`, `docs/telemetry-contract.md`) is off unless
  an operator installs the optional `agentcore-observability` extra and sets
  `MOSAIC_AGENTCORE_OBSERVABILITY=true`. `tests/test_telemetry_contract.py`
  covers the projection's shape, its default-off behavior, and its content
  exclusions offline. Whether spans arrive in an operator's own collector or in
  CloudWatch is **PENDING RUNTIME VERIFICATION**.
- **Managed Runtime and Gateway** are required, provisioned resources for Lab 3,
  documented in `docs/agentcore-runtime.md`. The 26 September test event restored
  Aurora successfully but its tools Runtime failed in an unsupported physical AZ.
  The [29 September deployment](docs/evidence/fresh-account-2026-09-29.md) passed
  provisioning and managed-agent rehearsal. Its subsequent cache/bootstrap
  correction still needs pristine provisioning under its new release pin.
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
3. join and verify them with `scripts/catalog/real_catalog_cache.py join`;
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
