# Clean-account rehearsal runbook

`READINESS.md`'s "Clean-account acceptance test" names eleven things a
maintainer must run and record on a fresh Aurora deployment before a release
is ready. This is the runbook for that list: which real commands to run, in
which order, and how to fold their results into one machine-readable evidence
manifest with `scripts/rehearsal.py`. A separate, opt-in `scripts/load_exercise.py`
covers the bounded concurrency exercise this task adds on top of it.

Both tools are offline-testable and covered by `tests/test_rehearsal.py` and
`tests/test_load_exercise.py`. Neither tool deploys, provisions, resets a lab,
or touches a database directly; they record facts about commands the operator
already ran, plus a small number of read-only HTTP calls against an
already-running deployment. **No rehearsal has been recorded from this
repository as of this writing.** Every deployment-time, latency, and
throughput claim below is a description of the runbook, not a result; running
it requires an authorized Aurora cluster, a deployed Workshop Studio stack or
an equivalent Aurora + API environment, and Bedrock model access, none of
which are available in an offline development session.

## Who can run this

A maintainer with:

- authorization to deploy the workshop's CloudFormation templates into a
  clean AWS account (or an existing clean-account stack already up), per the
  companion Workshop Studio repository's own process (see "Companion
  repository handoffs" below — that repository is not available from this one
  and this runbook does not reproduce its deployment steps);
- the scoped S3 read access `deploy/mosaic-bootstrap.sh` describes for the
  `real-catalog/real-catalog.tar.gz.part-*` objects;
- an Aurora `DATABASE_URL` for the deployed cluster;
- network access to the deployed API's base URL (the CloudFront/ALB host
  Workshop Studio's stack outputs, or `http://127.0.0.1:8000` for a
  Code-Editor-local rehearsal).

## 1. Initialize the manifest

```sh
uv run python scripts/rehearsal.py init \
  --output build/rehearsal-evidence.json \
  --operator "<your name or handle>" \
  --workshop-studio-stack-id <stack-id-or-name> \
  --aws-region us-east-1
```

This writes an empty manifest with all eleven required stages present as
`not_started`, plus the local facts that need no live environment: the
checked-out git revision and dirty flag, `deploy/mosaic-bootstrap.sh`'s
SHA-256, the two dataset-cache contract hashes
(`db/config/real-catalog-cache.json`, `db/config/corpus-vocabulary-cache.json`),
and the session contract snapshot from `data/evals/mosaic_labs_missions.json`.

## 2. Deploy, then capture identity

Deploy the nested templates in a clean environment through the companion
Workshop Studio repository's own process (step 1 of `READINESS.md`'s
acceptance test). Once the stack is up and the API answers:

```sh
uv run python scripts/rehearsal.py capture-identity \
  --manifest build/rehearsal-evidence.json \
  --api-url https://<stack-host> \
  --started-at <identity-check-start-iso> --ended-at <identity-check-end-iso>
```

This calls `GET /api/health` and `GET /api/readiness` once, records the
served dataset ID and catalog SHA-256 against the expected
`reviews-2023-500k-v1`, and marks `deployment_identity` `passed` only if
`/api/readiness` reports `status: "ready"`. **`--started-at`/`--ended-at` are
required for `deployment_seconds` to appear in the timing rollup in step 8**;
without them `deployment_identity.elapsed_seconds` stays null and
`overall_status` can never reach `complete`, even after every other stage
passes (`tests/test_rehearsal.py`'s
`test_a_fully_populated_manifest_reaches_complete_overall_status`).

Once identity is confirmed `ready`, record the deployment's first live query
— READINESS.md item 10's "first-query" timing figure, alongside deployment,
transfer, bootstrap, index, reranker, and agent timing:

```sh
uv run python scripts/rehearsal.py record-first-query \
  --manifest build/rehearsal-evidence.json --api-url https://<stack-host>
```

This issues one plain, non-reranked `POST /api/search` call and stores its
latency as `deployment_identity.first_query_ms`, without disturbing that
stage's `status`/`detail`. It is also required for the timing rollup to pass
in step 8.

## 3. Archive transfer and join

On the Code Editor host (or wherever the bootstrap's `aws s3 sync` and
`scripts/real_catalog_cache.py join` ran):

```sh
uv run python scripts/rehearsal.py record-stage \
  --manifest build/rehearsal-evidence.json \
  --stage archive_transfer_and_join --status passed \
  --detail "3 parts synced from s3://<bucket>/<prefix>real-catalog/; \
join verified sha256 against db/config/real-catalog-cache.json" \
  --started-at 2026-01-01T00:00:00+00:00 --ended-at 2026-01-01T00:05:00+00:00 \
  --artifact build/real-catalog-cache/real-catalog.tar.gz.sha256
```

Use the real timestamps the transfer took and point `--artifact` at whatever
the join step wrote (its printed SHA-256, or a saved copy of its stdout).

## 4. Bootstrap phases and timings

Run the real bootstrap, then fold its timings file straight in — this stage's
numbers come from `Makefile`'s own `bootstrap-phase` instrumentation, never
retyped:

```sh
make db-bootstrap-base
uv run python scripts/rehearsal.py import-bootstrap-timings \
  --manifest build/rehearsal-evidence.json \
  --timings-file build/bootstrap-timings.tsv \
  --started-at <bootstrap-start-iso> --ended-at <bootstrap-end-iso>
```

`import-bootstrap-timings` fails the stage (`status: "failed"`) if any of the
ten expected phases or the `total` row is missing from the TSV, which is what
a bootstrap that died partway through looks like.

## 5. Catalog restore verification

After `scripts/real_catalog_cache.py restore` and its own printed
verification:

```sh
uv run python scripts/rehearsal.py record-stage \
  --manifest build/rehearsal-evidence.json \
  --stage catalog_restore_verification --status passed \
  --detail "500000 products, 500000 vectors, 120 premium, evidence rows present, \
FTS/trigram/HNSW indexes valid" \
  --started-at <restore-start-iso> --ended-at <restore-end-iso>
```

## 6. Rehearse each lab, independently

For each lab, run its real reset, solution, and validate targets and save
their output, then record one stage per lab:

```sh
make reset-lab-1 > .local/lab-1-rehearsal.log 2>&1
make solution-lab-1 >> .local/lab-1-rehearsal.log 2>&1
DATABASE_URL="$DATABASE_URL" make validate-lab-1 >> .local/lab-1-rehearsal.log 2>&1

uv run python scripts/rehearsal.py record-stage \
  --manifest build/rehearsal-evidence.json \
  --stage lab_1_rehearsal --status passed \
  --detail "reset isolated; solution applied; validate-lab-1 PASS (see artifact)" \
  --artifact .local/lab-1-rehearsal.log
```

Repeat for `lab_2_rehearsal` and `lab_3_rehearsal` with `reset-lab-2`/`reset-lab-3`
etc. A lab that fails its validate step is recorded `--status failed` with the
validator's own failure message in `--detail`; that is a real finding, not a
tooling error, and belongs in the manifest exactly as it happened.

## 7. Reranker and Ask Mosaic, cold and warm

Cold means "run this immediately, e.g. right after the API first starts
serving or right after deploying"; warm means "run this again once the
service has already served traffic." The tool does not infer which is which
(see `scripts/load_exercise.py`'s docstring for why) — declare it explicitly:

```sh
uv run python scripts/rehearsal.py record-cold-warm \
  --manifest build/rehearsal-evidence.json \
  --target reranker --condition cold --api-url https://<stack-host>
uv run python scripts/rehearsal.py record-cold-warm \
  --manifest build/rehearsal-evidence.json \
  --target reranker --condition warm --api-url https://<stack-host>
uv run python scripts/rehearsal.py record-cold-warm \
  --manifest build/rehearsal-evidence.json \
  --target ask_mosaic --condition cold --api-url https://<stack-host>
uv run python scripts/rehearsal.py record-cold-warm \
  --manifest build/rehearsal-evidence.json \
  --target ask_mosaic --condition warm --api-url https://<stack-host>
```

Each call issues exactly one live request (`POST /api/search` with
`rerank: true` for `reranker`, `POST /api/agent/answer` for `ask_mosaic`) and
records the response's own `diagnostics.stage_timings_ms` /
`diagnostics.total_latency_ms` (reranker) or tool-trace shape and outcome
(`ask_mosaic`), plus the client-measured wall latency. Both `cold` and `warm`
must be recorded before the stage can pass.

## 8. Timing summary

Once bootstrap, restore, and cold/warm are recorded, derive the rollup —
never retype a number that is already sitting in another stage:

```sh
uv run python scripts/rehearsal.py compute-timing-summary \
  --manifest build/rehearsal-evidence.json
```

## 9. Layout walkthrough

Visually confirm the Playground/readiness strip/lab cards on each device
shape, then record each one:

```sh
uv run python scripts/rehearsal.py record-layout \
  --manifest build/rehearsal-evidence.json \
  --device laptop --status ok --detail "1440x900, no overflow"
uv run python scripts/rehearsal.py record-layout \
  --manifest build/rehearsal-evidence.json \
  --device tablet --status ok --detail "iPad portrait, cards stack cleanly"
uv run python scripts/rehearsal.py record-layout \
  --manifest build/rehearsal-evidence.json \
  --device mobile --status ok --detail "375px width, no horizontal scroll"
uv run python scripts/rehearsal.py record-layout \
  --manifest build/rehearsal-evidence.json \
  --device projector --status ok --detail "1080p from the back row, legible"
```

## 10. Validate and summarize

```sh
make rehearsal-validate     # or: uv run python scripts/rehearsal.py validate --manifest ...
make rehearsal-summary      # human-readable status block
```

`validate` rejects the manifest if any of the eleven required stages is
missing, or if the serialized JSON contains anything shaped like a DSN
password, an AWS access key ID, a bearer token, a
`password`/`secret`/`security-token`-style assignment (including an
`x-amz-security-token` header or query parameter), or a `tkn=`/`token=` query
parameter (`tests/test_rehearsal.py` keeps every one of these as a permanent,
red-at-birth fixture). `record-stage` and the other recording subcommands
redact free-text `--detail` values against the same patterns automatically,
but `validate` is the gate a hand-edited manifest still has to pass.

Commit or attach `build/rehearsal-evidence.json` as the release's rehearsal
record; `build/` is git-ignored, so archive it wherever the release evidence
for this workshop is kept (the release notes, an attached artifact, or
alongside `build/bootstrap-timings.tsv` in whatever the maintainer's release
process already retains).

## Bounded concurrency exercise

Run this against the same deployment, separately from the manifest above (its
report format is intentionally distinct — see "Simulated versus measured"
below):

```sh
uv run python scripts/load_exercise.py \
  --api-url https://<stack-host> --condition cold \
  --duration-seconds 120 --concurrency 8 \
  --output build/load-exercise-cold.json

uv run python scripts/load_exercise.py \
  --api-url https://<stack-host> --condition warm \
  --duration-seconds 120 --concurrency 8 \
  --output build/load-exercise-warm.json
```

or via
`make load-exercise LOAD_EXERCISE_ARGS='--condition warm --duration-seconds 120 --concurrency 8'`.

What it does:

- sends a weighted mix of `POST /api/search` (default weight 0.5),
  `POST /api/retrieval/fusion-comparison` (0.2), and `POST /api/agent/answer`
  (0.3) — override with `--search-weight`/`--fusion-weight`/`--agent-weight`;
- caps the total number of `/api/agent/answer` calls at `--max-agent-calls`
  (default 20), because each one can drive a full Strands tool loop
  (`service.agent.build_agent`'s server-side `max_tool_calls`, 10 by default)
  plus a Bedrock synthesis call — the most expensive request this API serves;
- toggles the Cohere rerank call on search requests with `--rerank`/`--no-rerank`
  (fusion comparison never reranks regardless);
- stops itself the moment `--error-rate-ceiling` (default 0.5), `--latency-ceiling-ms`
  (default 5000, checked over the last `--latency-window-size` samples), or
  `--duration-seconds` trips, and reports which one (`abort_reason`);
- after an error/latency abort, **or** after any run that observed a nonzero
  `saturation_signals` count even without aborting (a burst that clears on its
  own before the error-rate ceiling trips is still saturation), probes
  recovery for `--recovery-window-seconds` (default 30s, 0 disables it) with
  single, sequential search requests and reports whether and when a clean
  response returned;
- reports sample counts, error counts and rate, p50/p95/p99 latency overall
  and per request kind, and `saturation_signals` (429 and 503 counts) —
  everything split out separately, never blended into one number;
- reads `GET /api/readiness` twice — once before the first worker starts and
  once after the run ends — and looks for a served admission/rate-limit block
  under `admission`, `admission_control`, `rate_limit`, or `rate_limiting`.
  Each read is reported independently under `admission_context.before` and
  `admission_context.after`, so a reviewer can see whether the server's
  declared limits held steady or changed once traffic hit it, not just what
  they were when the run finished. Each is `source: "served"` when found;
  when absent, `--expected-max-concurrent-requests` supplies the same slot
  with `source: "cli_flag"`, and `source: "unknown"` when neither is
  available. **As of this writing, no branch has shipped that endpoint
  field**, so every run reports `source: "unknown"` on both reads unless
  `--expected-max-concurrent-requests` is passed. This script does not change
  its own concurrency based on the discovered value; probing at or above a
  declared ceiling is the point.

Its results are meant to check the access-control task's admission and
timeout behavior once that branch merges: re-run this exercise against the
merged deployment with `--concurrency` set comfortably above whatever ceiling
it configures, and confirm `saturation_signals` shows 429s (or 503s) instead
of unbounded queuing or crashed connections, and that `recovery.recovered` is
`true` once the burst ends.

### Simulated versus measured

Every report `scripts/load_exercise.py` and `scripts/rehearsal.py` write
carries `"kind": "measured"` — the same discriminator
`data/benchmarks/hnsw_measured.json` uses. `scripts/simulate_scale.py`'s CSV
rows carry `projection_kind: "simulated_calibrated"` instead. The two must
never be merged into one artifact or cited as if they were the same kind of
claim; see `docs/benchmark-methodology.md`'s "Projection policy".

## Companion-repository and infrastructure handoffs

This repository owns the rehearsal recorder, the load exercise, and the
manifest/report formats. It does not own, and this session did not have
access to, the following — each is a concrete handoff to whoever runs the
rehearsal for real:

1. **Deploying the stack.** The companion Workshop Studio repository
   (`build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql`) owns the
   CloudFormation templates, the asset bucket, and `BootstrapScriptSha256`
   verification. Step 2 above ("Deploy, then capture identity") assumes that
   stack already exists; this runbook does not create it.
2. **Scoped S3 credentials** for the `real-catalog/real-catalog.tar.gz.part-*`
   objects and `vocabulary/*.csv.gz`, per `deploy/README.md`'s "Catalog
   selection and assets" section.
3. **An Aurora `DATABASE_URL`** for the deployed cluster, exported before
   `make db-bootstrap-base` and the lab `make` targets in steps 4 and 6.
4. **Bedrock model access** for the three pinned model IDs
   (`scripts/check_model_access.py`), needed for steps 6 (Lab 3), 7, and the
   load exercise's agent-kind requests.
5. **A reachable API base URL** for `capture-identity`, `record-cold-warm`,
   and `scripts/load_exercise.py` — either the deployed stack's public host or
   `http://127.0.0.1:8000` when rehearsing from the Code Editor instance
   itself.
6. **The access-control branch**, once merged, for the load exercise's
   `admission_context.source: "served"` path and for a meaningful
   `saturation_signals` comparison against a configured ceiling.

## What this session verified, and what it could not

Every function in `scripts/rehearsal.py` and `scripts/load_exercise.py` is
covered by an offline test (`tests/test_rehearsal.py`,
`tests/test_load_exercise.py`) using fixture manifests and
`httpx.MockTransport`, including several red-at-birth gates per
`docs/house-standards.md` rule 4: a manifest missing a required stage; a
manifest carrying any of six unredacted-secret shapes (a DSN password, an AWS
access key ID, a bearer token, a password/secret/security-token assignment,
and a `tkn=`/`token=` query parameter); a fully rehearsed manifest that must
reach `overall_status: "complete"` and cannot without `capture-identity`'s
timestamps or `record-first-query`'s measurement; the load exercise's
before/after admission-context ordering; and its saturation-triggered
recovery probe. No DATABASE_URL, Bedrock credential, or deployed environment
was available in this session, so nothing above has been run against a real
Aurora cluster or a real Workshop Studio stack. To close that gap:

```sh
# from an authorized shell with AWS credentials, a deployed stack, and DATABASE_URL:
uv run python scripts/rehearsal.py init --output build/rehearsal-evidence.json \
  --operator "<name>" --workshop-studio-stack-id <stack-id> --aws-region us-east-1
uv run python scripts/rehearsal.py capture-identity \
  --manifest build/rehearsal-evidence.json --api-url https://<stack-host> \
  --started-at <start-iso> --ended-at <end-iso>
uv run python scripts/rehearsal.py record-first-query \
  --manifest build/rehearsal-evidence.json --api-url https://<stack-host>
# ... steps 3-9 above ...
make rehearsal-validate
make rehearsal-summary
uv run python scripts/load_exercise.py --api-url https://<stack-host> \
  --condition cold --duration-seconds 120 --concurrency 8 \
  --output build/load-exercise-cold.json
uv run python scripts/load_exercise.py --api-url https://<stack-host> \
  --condition warm --duration-seconds 120 --concurrency 8 \
  --output build/load-exercise-warm.json
```
