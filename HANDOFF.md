# Handoff

Current DAT410 redesign state as of August 5, 2026.

## Read This First

The `main` branch is implementing the approved four-phase online-migration
scenario. The redesign is not release-complete.
Do not restore the retired ordinary-`CREATE INDEX` /
concurrent-index-repair mechanism.

The binding implementation plan is
`docs/superpowers/plans/2026-08-04-dat410-incident-scenario-redesign-plan.md`.
Tasks A1-E4 and F1-F2 are complete. F1's live PI-disabled/IAM-revoked
rehearsal remains owed. Tasks G1-G3 own the remaining participant, failure, and
release rehearsal work. The plan's repository-wide alignment audit assigns
every known stale surface to an explicit task; finding an unassigned stale
surface is a plan defect and should be corrected before implementation
continues.

## Repositories

| Repository | Branch | Publication boundary |
|---|---|---|
| `sample-agentic-hybrid-retrieval-aurora-postgresql` | `main` | implementation worktree; do not edit the concurrent primary checkout |
| `build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql` | `mainline` | stage only; the user commits and publishes Workshop Studio |

Do not package or publish Workshop Studio until G3 freezes the source commit.
Then build the schema-only archive from that exact commit and update all
`SourceRevision` fields.

## Standing Evidence Rule

The participant database starts with schema, a pre-provisioned 3,000,000-row
`workbench_lab.orders` workload, and zero evidence. Operational workload rows
never enter retrieval or proof. The sole participant ingestion path remains
`make live-workshop`, but its target design is now two additive admissions:

```text
make live-workshop
  -> Wave A: run one unbatched priority_tier backfill
  -> collide 12 tagged API writes with the real 10-connection pool
  -> prove transaction-ID blocking, pool exhaustion, timeouts, and recovery
  -> compare before-ANALYZE and after-ANALYZE query plans
  -> admit measured diagnostic evidence
  -> generate Cohere embeddings through Bedrock
  -> build a cited, read-only Hybrid Retrieval Agent recommendation
  -> participant approves and executes the rendered CREATE INDEX
  -> Wave B: capture and admit the post-index validation plan
  -> persist proposal, execution, citations, verdicts, and replay receipts
```

CloudWatch is supplemental and non-gating. Performance Insights / Database
Insights is intentionally outside the core path. The incident is diagnosed from
native PostgreSQL evidence plus app-pool and request telemetry. The agent remains
read-only: it recommends structured action fields, code renders the SQL, and the
participant executes the DDL under supervision.

No fixture, authored record, dump, prior capture, JSON snapshot, offline
embedding, canned answer, customer, support case, runbook, postmortem, or
distractor may enter retrieval, agent tools, citations, evaluation, or proof.
The Overview main graphic is the only illustrative exception and is never data.

Identifiers are capture-derived:

```text
INC-<run-suffix>
CHG-<run-suffix>-...
LOCK-<run-suffix>-01
TEL-<run-suffix>-...
```

## Current Implementation Boundary

Completed and committed on this branch:

- A1 removes the Database Insights admission surface.
- A2 enforces the four-phase, explicit-ACL admission contract.
- A3 adds additive Wave A / Wave B admission.
- A4 adds G-32, makes G-25 wave-aware, and preserves Wave A fuzzy identity
  after Wave B.
- A5 adds append-only supervised-execution proposals, citation links,
  catalog-derived action fingerprints, execution receipts, independent
  pre/post autonomy-readiness verdicts, persona RLS, and the owner-only Wave B
  receipt attachment.
- A6 (`9453a6c`) adds G-34, which structurally proves that pre-execution
  autonomy readiness cannot read post-execution evidence, plus adversarial
  static and behavioral regressions.
- B1 (`3858379`) bootstraps exactly 5,000 customers and 3,000,000 orders with
  no migration columns. The workload is operational state and the evidence
  store stays empty.
- B1a adds `labs/incident/migration.py`: the nullable `priority_tier` column
  commits before the 3,000,000-row backfill opens, and `BackfillHandle` owns
  the intentionally open transaction until recovery commits or aborts it. The
  retired ordinary-index hold, blocked-writer, active-reader, and thread
  orchestration code is deleted. Until B2 and B3 install the real API-pool
  collision and condition-based controller, `make live-workshop` exits before
  any database work instead of running the retired scenario.
- B2 adds config-gated `POST /v1/lab/hot-write` and `GET /v1/lab/pool-status`
  routes. The hot write checks out from the real application pool, then keeps
  its application tag, statement timeout, and `UPDATE` in one explicit
  transaction. Pool timeout is a measured HTTP-200 outcome, not a 500. Lab
  mode fails closed unless `DB_POOL_MIN_SIZE = DB_POOL_MAX_SIZE = 10`, which
  pre-opens the app's existing ten pool slots before the 12-request collision.
- B3 adds `labs/incident/hold_controller.py` and the staged
  `run_migration_collision()` integration. It starts 12 concurrent API writes
  against B1a's open backfill, polls the pool and PostgreSQL every 250ms, and
  requires three consecutive samples proving ten transaction-ID-blocked
  sessions plus two pool waiters before its 12-second observation hold. Every
  poll is retained; state changes are recorded only at boundaries. A failed
  proof aborts the backfill and terminates only tagged sessions in the current
  database.
- B4 adds `labs/incident/recovery_verifier.py` and calls it immediately after
  the backfill commits. It independently proves that the released backfill
  blocks no backend, the ten-slot pool is fully available with no waiters,
  tagged lock waiters are gone, a pool timeout actually occurred, all ten
  blocked writers drained without statement timeout, and a fresh API write
  commits. A failure reports every failed assertion by name and cleans up
  tagged sessions before re-raising.
- B5 adds `labs/incident/query_regression.py`. It parses `EXPLAIN (ANALYZE,
  BUFFERS, FORMAT JSON)` structurally, never by text regex. With the
  participant-created index absent it returns only the before- and
  after-`ANALYZE` sequential-scan checkpoints for Wave A; with the named index
  present it returns only the Wave B index-scan checkpoint. It never creates
  or drops an index.
- B6 removes all Performance Insights / Database Insights collection and
  admission dependencies. CloudWatch is now explicitly best-effort: every
  payload must declare `cloudwatch_status` as `available` or `unavailable`,
  while an unavailable metric endpoint never invalidates the PostgreSQL and
  pool evidence. Admission, the capture schema, readiness diagnostics, smoke
  discovery, and tests now describe the transaction-ID blocking and
  four-phase contract.
- C1 adds `labs/incident/evidence_builder.py`. It turns one measured run into
  distinct `lock`, `pool`, `request`, `wal`, `meta`, and `plan` documents and
  never expands raw poll ticks into template rows. Its deterministic
  `statement-text/1` classifier derives visibility from captured
  `pg_stat_activity` / `pg_stat_statements` statement text and persists a
  version, closed reason, and source sample IDs with every document. The
  retired `_measured_visibility` / `unknown` compatibility path is deleted.
  The optional RLS/masking narrative and G-27 now validate that source
  provenance rather than the deleted Database Insights surface.
- C2 wires the two additive admission paths. Wave A runs the measured migration
  collision, persists its raw PostgreSQL samples before the C1 documents cite
  them, and admits/indexes diagnostic evidence. Wave B requires the
  participant-created index, captures only the post-index validation checkpoint,
  and is replay-idempotent. The CLI exposes `--wave {A,B}`; the lab schema now
  survives by default, while `--drop-lab-schema` is explicit. Doctor, the
  latest-run API, the live retrieval contract, and G-32 all resolve one incident
  across its two capture windows.
- C3 pins `run_graph` to the incident capture window available when the
  retrieval run began. It resolves the latest completed capture for the
  candidate incident before `run.started_at`, retains only source-bundle
  evidence available by that window, and consequently returns only eligible
  edges. `run_timeline` inherits the same boundary. The replay guard names
  Gate 2 so a future simplification cannot turn the historical graph back into
  a live graph.
- C4 adds read-only core gate G-33. It reconstructs each current document from
  its current chunks, requires all six hardcoded signal types and four
  hardcoded phases, and rejects a corpus whose `pg_trgm` near-duplicate rate
  reaches 15%. Doctor now reports the evidence-derived 50-80 document range
  as advisory volume guidance, never as an acceptance condition.
- D1 records live retrieval-arm differentiation in the smoke receipt. Exact
  and fuzzy ID recovery can agree, but a natural-language full-text probe and
  a semantic pool-exhaustion probe must yield at least a third distinct top
  candidate. It also requires Cohere rerank to change a top-five ordering
  without changing PostgreSQL's RRF or final scores for shared candidates.
- D2 scopes the Hybrid Retrieval Agent to the current Wave A diagnostic
  question. Its seven registered tools remain read/synthesis-only; a proposal
  never makes the agent write-capable, and the agent cannot cite or claim the
  post-index result that has not yet been admitted.
- D2a persists one structured, cited index proposal from the canonical
  `/v1/agent/answer` path after citation validation. Code validates the
  model-provided fields, renders the DDL, measures catalog preconditions, and
  stores the proposal, its citations, bounded timeouts, and rollback guidance.
- D3 adds the Lab 4 participant-executed action. `workbench_lab_owner` gives
  `workshop_participant` ownership only of the disposable lab workload, while
  `workshop_app` retains narrow DML grants and cannot create indexes, drop
  tables, or truncate. Wave B requires the stored proposal and explicit
  approver, reads the observed index shape from Aurora's catalog, records an
  append-only execution before admission, attaches the Wave B receipt only
  after successful admission, and prints the closing thesis only after the
  participant's own validation is ready. Wave B also rejects a proposal whose
  retrieval run was not grounded in the active Wave A incident.
- E1 removes the retired Database Insights configuration, API, and UI branch.
  `proof.observability_refs` still publishes the observed retrieval window with
  its verify SQL and can render only a configured lock-analysis link. The
  participant UI now names the Hybrid Retrieval Agent and describes the
  measured online schema and data migration, pool exhaustion and recovery,
  ineffective `ANALYZE`, and missing composite index rather than the retired
  ordinary-index / concurrent-repair story.
- E2 widens `retrieval.v_corpus_distribution` with a provenance-derived
  nullable wave. The Corpus surface groups the actual reported waves, exposes
  a null wave as a provenance gap rather than inventing a default, and lets the
  participant compare stable Wave A counts with additive Wave B counts. The
  diagnostics endpoint now publishes a canonical distribution verify descriptor,
  and G-13 replays it against the API response.
- E3 labels a sequential scan only when its observed relation proves the
  interpretation: a small `retrieval.*` evidence corpus may correctly scan
  sequentially, while a sequential scan of `workbench_lab.orders` identifies the
  missing access path that `ANALYZE` cannot create.
- E4 adds the Proof surface's `supervision` lens and
  `GET /v1/runs/{run_id}/supervision`. It reads the latest proposal for the run,
  the proposal's own citation links, only execution attempts for that proposal,
  and the database-computed autonomy verdict. The UI renders the verdict rather
  than inferring it, and G-13 replays every returned descriptor when a proposal
  exists. The lens explicitly distinguishes a missing proposal, a pending human
  action, a mismatched execution, and a validated Wave B outcome.
- F1 removes stale Performance Insights / Database Insights dependencies from
  source docs, schema cleanup, diagnostics comments, and archive requirements.
  `README.md`, `docs/architecture.md`, `docs/builder-session-flow.md`,
  `docs/implementation-spec.md`, `docs/live-data-audit.md`,
  `docs/data-model.md`, `DAT410-BUILD-BRIEF.md`,
  `WORKSHOP-BUILD-SUMMARY.md`, and `READINESS.md` now describe the current
  migration, two-wave admission, source-native observability, and
  human-supervised action contract. The source archive now requires every
  incident controller, supervised-execution runtime module, and release gate.
  `.env.example` documents the ten-slot Lab 1 pool configuration.

Not yet complete: infrastructure packaging and the complete rehearsal. A
source-only `make live-workshop` result is not evidence that the approved
scenario is release-complete.

For D2/D3's supervised participant action, render the controlled-lab repair as:

```sql
CREATE INDEX idx_orders_priority_tier_created_at
ON workbench_lab.orders (priority_tier, created_at DESC);
```

`workbench_lab.idx_orders_priority_tier_created_at` remains the catalog lookup
identifier, but PostgreSQL rejects a schema-qualified index name in the
`CREATE INDEX` statement itself. This was verified against the live rehearsal
database before the valid participant-equivalent command was run.

## Latest Validation

The branch was validated on August 5 against the dedicated
`dat410_review_remediation_test` database on the `agenticretrieval...` Aurora
PostgreSQL 18.3 cluster in `us-east-1`:

- Exact test-target preflight: passed as Aurora PostgreSQL 18.3 in `us-east-1`.
- Full core suite: 218 tests passed, 50 expected live/security skips.
- `make security-schema`: passed with managed `pg_columnmask` 1.1.0.
- Supervised-execution suite under security mode: 39 tests passed, zero skips.
- G-34 focused suite: 11 tests passed; the gate passed directly and through
  `gates/checks.sh G-34`.
- B1 bootstrap: 32.13 seconds on `db.r8g.2xlarge`; 3,000,000 canonical orders,
  5,000 customers, 248,193,024 bytes, fresh `ANALYZE`, no `priority_tier` or
  `updated_at`, and zero evidence rows.
- B1a migration acceptance: `ADD COLUMN` left no `AccessExclusiveLock`;
  `open_backfill()` updated exactly 3,000,000 rows in 22.266 seconds and left
  its backend `idle in transaction`; a concurrent write to `order_id = 1`
  waited on `Lock:Transactionid` with the backfill PID in
  `pg_blocking_pids()`, then drained after commit. The test database was
  reset, fully re-schematized, and re-bootstrapped afterward.
- B2 endpoint acceptance: with `LAB_ENDPOINTS_ENABLED=1` and
  `DB_POOL_MIN_SIZE=DB_POOL_MAX_SIZE=10`, a 23.151-second open backfill and 12
  distinct HTTP hot writes produced 10 `Lock:Transactionid` sessions blocked
  by the backfill PID, two `pool_timeout` responses at 3.001-3.002 seconds,
  and 10 drained `committed` responses at 3.456-3.465 seconds. The pool-status
  route returned the proven state (`pool_size=10`, `pool_available=0`,
  `requests_waiting=2`) in 1.51ms. A first run with the default one-connection
  minimum grew only to nine slots before checkout timeouts, producing eight
  blocked sessions and four pool timeouts; this is why the equal
  minimum/maximum precondition is enforced, not merely documented.
- B3 controller acceptance: the real 3M-row backfill updated all rows in
  22.749 seconds. The 12-request collision collected 42 raw 250ms polls,
  emitted one state transition, proved the combined condition, then returned
  10 `committed` and two `pool_timeout` results. The deliberate seven-request
  probe failed after its bounded proving period with `only 7 of 10 tagged
  sessions were ever blocked on the backfill`; cleanup left zero tagged lock
  waiters. The test database was reset and re-bootstrapped afterward.
- B4 recovery acceptance: two consecutive clean runs of the final verifier
  completed against Aurora PostgreSQL 18.3. The 3M-row backfills took 22.664s
  and 22.453s; each run proved the hold in 43–44 polls, then returned exactly
  10 `committed` outcomes and two `pool_timeout` outcomes. All seven recovery
  assertions passed, including a fresh post-recovery write. The deliberate
  3-second statement-timeout run failed only on `blocked_writers_drained` and
  left zero tagged lock waiters. A direct clean-state probe with ten commits
  and no pool timeouts failed only on `pool_timeout_observed`, proving the two
  retrospective assertions are independent.
- B5 query-regression acceptance: the full collision orchestrator completed
  with a 23.108s backfill and all seven recovery assertions true, then captured
  Wave A as `Seq Scan` at 473.911ms / 47,062 buffers before `ANALYZE` and
  `Seq Scan` at 229.169ms / 47,059 buffers after it. The
  participant-equivalent index produced the sole Wave B checkpoint:
  `Index Scan`, 2.581ms, 26 buffers, and zero rows removed by filter. Both Wave
  A scans removed 2,400,000 rows. These are measurements, not timing
  thresholds.
- B6 acceptance: `make doctor`, the full core suite, and the full core schema
  bundle all passed against `dat410_review_remediation_test` on Aurora
  PostgreSQL 18.3. The focused B6 suite covers CloudWatch success, unavailable
  capture, transaction-ID readiness, explicit `cloudwatch_status` admission,
  and removal of Performance Insights dependencies. C2 then proved the
  end-to-end two-wave path with PostgreSQL and pool evidence; CloudWatch remains
  supplemental rather than an admission or recovery gate.
- C1 acceptance: the pure evidence-builder and incident-contract suites pass
  (39 tests, 71 subtests). The full core suite passes on the dedicated Aurora
  PostgreSQL 18.3 test target (238 tests, 50 expected live/security skips).
  `make security-schema` applied cleanly; G-27 then correctly failed on the
  empty evidence store with the new source-provenance remediation, proving its
  classifier query compiles without pretending an unmixed corpus is a security
  success. This is not optional-security release evidence: C2 must first admit
  a real mixed-visibility capture, then the security gates must run against it.
- C2 live rehearsal: Wave A `CAP-3861DBEE` / capture
  `f387931b-60cb-4b19-a955-55153861dbee` and Wave B `CAP-DC80FBB0` / capture
  `7b2ffabd-6882-4a73-9667-8343dc80fbb0` attach to `INC-3861DBEE`. The indexed
  corpus has 57 documents and chunks: 54 Wave A and 3 Wave B, including 52
  telemetry documents. Wave A captured 308 activity rows, 1,792 lock rows,
  280 blocker-chain rows, three statement samples, and five CloudWatch samples.
  Replaying Wave B returned `idempotent_replay: true`, inserted zero new
  documents, and reused all 57 embeddings. The workload retained 2,999,989
  `created` rows and exactly 11 `touched` rows (the ten drained writers plus the
  recovery probe), with no unexpected statuses.
- C2 focused validation: `make doctor` passed against the two-wave Aurora
  PostgreSQL 18.3 capture (frontend intentionally unavailable warning only);
  G-32 passed with `Wave A 54 + Wave B 3 current documents`; all five
  `backend.tests.test_retrieval_integration` contracts passed; the admission
  static suite passed with its expected gated skips; and the API reported two
  capture keys, 57 current documents/chunks, 52 telemetry documents, and a
  fully available 10-slot pool.
- C3 replay-window validation: the static graph guard failed before the scope
  existed and passed after it. A fresh Aurora PostgreSQL 18.3 rehearsal reset
  `dat410_review_remediation_test`, bootstrapped 5,000 customers and 3,000,000
  orders, admitted Wave A (54 documents), created the participant-equivalent
  composite index, and admitted Wave B (3 documents). Wave A's persisted graph
  was byte-identical before and after Wave B (31 nodes, 58 edges), its document
  hashes were unchanged, and G-32 passed. The deliberately unscoped traversal
  would have returned 34 nodes including all 3 Wave B nodes, proving the
  hazard and the boundary. The five live retrieval integration contracts and
  `make doctor` passed; doctor reported only the intentionally stopped
  frontend warning.
- C4 corpus-diversity validation: a clean, fresh Aurora PostgreSQL 18.3
  two-wave rehearsal produced 57 documents (54 Wave A, 3 Wave B), all six
  signal types, and all four phases. G-33 measured 99 near-duplicate pairs out
  of 1,596 (6.20%), passed, and G-32 still passed. The deliberate red-path
  proof added 20 copies of the most-similar document only in the disposable
  `_test` database; G-33 correctly failed at 489/2,926 pairs (16.71%). The
  database was then reset, re-schematized, re-bootstrapped, and given a fresh
  two-wave capture. Focused tests (12 passed, 20 expected skips, 42 subtests),
  `make doctor` (frontend warning only), and the safe core subset G-11, G-14,
  G-17, G-21, G-23, G-32, G-33, and G-34 all passed.
- D1 retrieval-arm validation: `make smoke` passed with Bedrock synthesis
  required. Exact and fuzzy both recovered `CHG-37AF2D23-01`, while full text
  ranked `LOCK-37AF2D23-01` and semantic ranked `TEL-37AF2D23-R01`, satisfying
  the three-distinct-candidate contract. The causal hybrid question produced a
  different reranked top five while all shared candidates retained their
  PostgreSQL RRF and final scores. G-13 then replayed the fresh smoke answer
  `c37e283a-b874-4546-a8fa-985932384df6` through the API: receipt panels,
  63 graph edges, and 34 timeline events all matched their published
  `_verify_sql` results.
- D2/D3 rehearsal: Wave A `CAP-07E0FE86` and Wave B `CAP-EE15C094` were
  admitted on the dedicated Aurora PostgreSQL 18.3 test database. The
  historical Lab 3 run `c4e6c439-10bf-405d-81e1-b00fccb42605` replayed through
  the HTTP API five times with an identical 31-node, 58-edge graph and
  identical eight-citation set; neither contained Wave B evidence. The
  participant created the approved index under their own role, the recorder
  captured the catalog-derived match and attached the Wave B receipt, `doctor`
  passed with 57 documents and all required phases and signal types, and G-13
  plus G-34 passed. Focused Aurora suites passed before the final
  proposal-to-incident guard: `test_admission` 17 passed with 11 expected
  live-payload skips, and `test_incident_lab` 32 passed with six expected
  privilege skips before the optional security identities were provisioned.
  The new guard's database-backed contract needs a fresh run against this
  Aurora target; it is intentionally not marked as live-proven from the
  preceding rehearsal.
- E1 source validation: `cd frontend && npm run build` passed; the focused
  configuration and observability tests passed (8 tests); and the API imports
  with a retired `WORKBENCH_DBI_URL_TEMPLATE` still set, proving the key is
  ignored. The source-level suite passed 175 tests with 110 expected skips
  because this shell has no resettable test DSN or live capture. Its local port
  55432 has no server, and the installed client is PostgreSQL 18.4, so it is
  not an allowed substitute for the required Aurora or local PostgreSQL 18.3
  test target. The E1 live UI check and G-13 replay remain owed to the next
  Aurora rehearsal.
- E2 source validation: `cd frontend && npm run build` passed; 22 focused
  Python contracts passed; and G-11, G-14, and G-23 passed. G-13 now discovers
  the smoke run ID and reaches the new Corpus replay branch, but remains blocked
  before any database read because `DATABASE_URL` is unset. On the next Aurora
  rehearsal, apply the view to the dedicated PostgreSQL 18.3 test database,
  record the pre- and post-view document/chunk sums, verify Wave-A-only then
  two-wave rendering, and run G-13 to replay the distribution query.
- E3 source validation: `cd frontend && npm run build` and
  `backend/tests/test_insights.py` both passed. The live visual confirmation
  remains owed to the Aurora rehearsal: verify the retrieval scan note appears
  only for `retrieval.*`, the incident note only for `workbench_lab.orders`, and
  neither note appears for index scans or unrecognized relations.
- E4 source validation: `cd frontend && npm run build` passed; 18 focused
  `backend.tests.test_verify_sql` and `backend.tests.test_insights` contracts
  passed; G-11, G-14, and G-23 passed. G-13 and G-34 remain blocked here because
  no approved Aurora PostgreSQL 18.3 `DATABASE_URL` is configured. In the full
  rehearsal, use a proposal-bearing run to replay proposal, citations, execution,
  and verdict descriptors; capture the pending and validated screens and prove
  the pre-execution verdict remains byte-identical across them.
- F2 source budget: three clean Aurora PostgreSQL 18.3 `db.r8g.2xlarge` cycles
  rebuilt the 3,000,000-row workload and completed Wave A in 121.38s
  (33.86s + 87.52s), 115.72s (34.17s + 81.55s), and 115.19s
  (33.49s + 81.70s). The 121.38-second slowest observed source path is not a
  fully cold Workshop Studio account measurement: package installation,
  CloudFormation startup, and first-account Bedrock behavior remain for the
  final Workshop Studio rehearsal. The sibling
  `BootstrapWaitCondition.Timeout` is already 2,400 seconds, or 19.77x that
  observed path, so no timeout increase is justified. Its SSM custom-resource
  handler is Create-only; stack updates acknowledge success without rebuilding
  schema or workload, so a new stack or documented reset/recreate path is
  required for fresh substrate.

The test database is disposable and never a participant database. The earlier
local PostgreSQL 18.4 run was diagnostic only and is not release evidence.

The last D3 rehearsal used the dedicated Aurora PostgreSQL 18.3 test target
and its state may be reset by a later contract suite. Reapply
`make security-schema` before security-only checks, then recreate the
three-million-row workload and capture a fresh incident before treating any
result as rehearsal evidence.

## Next Task

Start G1: run all four labs from a participant seat against a fresh,
Aurora PostgreSQL 18.3 capture. Record the participant-visible Bedrock wait,
non-concurrent index-build time, Wave B admission time, pre- and
post-execution autonomy verdicts, agent-role DDL refusal, API-pool privileges,
and every point where a participant can get stuck. Before release, also close
F1's live proof by running `make live-workshop` with Performance Insights
disabled on a disposable cluster or `pi:GetResourceMetrics` revoked from the
caller. Keep CloudWatch supplemental, preserve the PostgreSQL and app-pool
evidence boundary, and do not package or publish the sibling Workshop Studio
repository before its user-owned work is ready.

### Workshop Studio Changes Required For F1

The sibling repository is user-owned and has not been changed from this
worktree. Apply these exact changes there before its release rehearsal:

1. In `assets/hybrid-retrieval-code-editor.yml`, change the
   `DBInstanceIdentifier` parameter description from "Aurora writer identifier
   used for live Database Insights capture" to "Aurora writer identifier used
   for live PostgreSQL and CloudWatch capture."
2. In the Code Editor task role policy in the same file, remove only
   `pi:GetResourceMetrics` from the statement that also grants
   `cloudwatch:GetMetricStatistics` and `sts:GetCallerIdentity`. Keep the
   CloudWatch and STS actions.
3. Update the Workshop Studio scenario, evidence-journey, troubleshooting,
   facilitator, optional-security, and asset README content that currently
   requires a PI wait, a `Lock:relation` dimension, a concurrent-index repair,
   or 25,000 operational orders. Point it to the source docs above:
   transaction-ID blocking, app-pool timeouts, 3,000,000 orders, Wave A, and
   Wave B.
4. Leave `EnablePerformanceInsights: true`,
   `PerformanceInsightsRetentionPeriod: 7`, and its KMS property in
   `assets/hybrid-retrieval-database.yml` unchanged. The core path does not
   depend on that service; disabling it is only an acceptance-test option.

The load-bearing reason for the IAM removal is that no source path reads PI,
and ASH does not sample the idle-in-transaction backfill state this scenario
holds. Revoking the permission makes that claim testable rather than
documentary. Preserve `proof.observability_refs`,
`WORKBENCH_DB_RESOURCE_ID`, and `WORKBENCH_LOCK_URL_TEMPLATE`: they are an
optional configured investigation link, not a retrieval dependency.

### F1 Live Proof Still Owed

No approved Aurora test `DATABASE_URL` is configured in this worktree, so F1
has not run its definitive acceptance: a complete `make live-workshop` against
a cluster with PI disabled, or with `pi:GetResourceMetrics` revoked from the
calling principal. Do not mark that result passed until the command exits zero
and admits a full current corpus. If it raises an authorization error naming
`pi:`, find the remaining caller; do not restore the permission.

Current maintenance hazards:

- `casework.telemetry_evidence` stores the signal value in
  `structured.telemetry_type`, not `structured.signal_type` and not a
  `signal_type` column. Doctor, G-32, and the live retrieval test use the
  correct key. Psycopg parameterized SQL literals containing `%` must use `%%`.
- Keep Bedrock in `us-east-1` for this workshop. Cohere Rerank 3.5 is active
  there and unavailable in `us-east-2`; an `AWS_REGION=us-east-2` shell makes
  the rerank doctor check fail even though embedding and synthesis can pass.

`make test` now fails before discovery unless `TEST_DATABASE_URL` names a
resettable `_test` database on exactly PostgreSQL 18.3. Accepted targets are
Aurora PostgreSQL in `us-east-1` or a loopback PostgreSQL 18.3 server; remote
non-Aurora PostgreSQL and the installed local PostgreSQL 18.4 are rejected.

## Database Hazard

The ignored `.env` may target the old `retrieval` database, which contains
legacy authored evidence. Never apply schema, run tests, or run the orchestrator
there.

Always inline-prefix `DATABASE_URL` on database-writing commands and verify
`current_database()` first. Resettable tests require a database name ending in
`_test` plus `ALLOW_TEST_DATABASE_RESET=1`.

## Release Validation

Before publishing:

```bash
make doctor
make smoke
make test
gates/checks.sh
cd frontend && npm run build
git diff --check
```

Also inspect the source archive and fail if it contains `seed/`,
`data/generated/`, a dump, capture JSON, embedding cache, database file, or
proof receipt. Workshop Studio bootstrap must end at `awaiting_incident` with
the 3,000,000-row workload ready, no target incident index, and zero evidence.

Do not commit generated live exports, credentials, local databases, logs,
`node_modules`, `.claude/settings.local.json`, `?/`, or `mockups/`.
