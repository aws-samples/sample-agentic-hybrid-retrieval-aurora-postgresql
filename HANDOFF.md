# Handoff

Current DAT410 redesign state as of August 5, 2026.

## Read This First

The `main` branch is implementing the approved four-phase online-migration
scenario. The redesign is not release-complete.
Do not extend the retired ordinary-`CREATE INDEX` / concurrent-index-repair
mechanism that still exists in portions of the runtime, tests, UI, and docs.

The binding implementation plan is
`docs/superpowers/plans/2026-08-04-dat410-incident-scenario-redesign-plan.md`.
Tasks A1-C4 are complete. Tasks D1-G3 own the remaining retrieval, agent, UI,
documentation, infrastructure, and rehearsal work. The plan's repository-wide
alignment audit assigns every known stale surface to an explicit task; finding an
unassigned stale surface is a plan defect and should be corrected before
implementation continues.

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

Not yet implemented: revised retrieval exercises and agent; participant UI and
labs; remaining documentation cleanup; infrastructure packaging; and the
complete rehearsal.
Until those tasks land, `make live-workshop` is not evidence that the approved
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

The test database contains disposable contract fixtures and is not a
participant database. The earlier local PostgreSQL 18.4 run was diagnostic only
and is not release evidence.

Current disposable-database state after C4 validation: core schema plus the
3,000,000-row `workbench_lab` workload, the participant-created
`idx_orders_priority_tier_created_at` index, two fresh live capture waves for
`INC-37AF2D23`, and no optional security module. Reapply
`make security-schema` before security-only checks.

## Next Task

Start D1: re-confirm that exact, full-text, semantic, and fuzzy retrieval
actually differentiate on the new capture-derived corpus. Preserve the
canonical Aurora PostgreSQL search functions; update the smoke assertion and
live-key discovery rather than manufacturing a corpus or making hybrid
retrieval a presumed winner. Read Task D1 in the binding plan before editing.

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
