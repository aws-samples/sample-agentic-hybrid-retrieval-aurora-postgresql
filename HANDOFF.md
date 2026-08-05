# Handoff

Current DAT410 redesign state as of August 5, 2026.

## Read This First

The `main` branch is implementing the approved four-phase online-migration
scenario. The redesign is not release-complete.
Do not extend the retired ordinary-`CREATE INDEX` / concurrent-index-repair
mechanism that still exists in portions of the runtime, tests, UI, and docs.

The binding implementation plan is
`docs/superpowers/plans/2026-08-04-dat410-incident-scenario-redesign-plan.md`.
Tasks A1-B1 are complete. Tasks B1a-G3 own the remaining runtime, retrieval,
agent, UI, documentation,
infrastructure, and rehearsal work. The plan's repository-wide alignment audit
assigns every known stale surface to an explicit task; finding an unassigned
stale surface is a plan defect and should be corrected before implementation
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

Not yet implemented: query-regression checkpoints, evidence builder and
admission, final retrieval corpus, revised agent,
participant UI and labs, remaining documentation cleanup, infrastructure
packaging, and live rehearsal. Until those tasks land, `make live-workshop` is
not evidence that the approved scenario is complete.

## Latest Validation

The branch was validated on August 5 against the dedicated
`dat410_review_remediation_test` database on the `agenticretrieval...` Aurora
PostgreSQL 18.3 cluster in `us-east-1`:

- Exact test-target preflight: passed as Aurora PostgreSQL 18.3 in `us-east-1`.
- Full core suite: 216 tests passed, 50 expected live/security skips.
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

The test database contains disposable contract fixtures and is not a
participant database. The earlier local PostgreSQL 18.4 run was diagnostic only
and is not release evidence.

Current disposable-database state after B4 validation: core schema plus the
3,000,000-row `workbench_lab` workload, zero evidence, and no optional security
module. Reapply `make security-schema` before security-only checks.

## Next Task

Start B5: build the query-regression driver with its before-`ANALYZE`,
after-`ANALYZE`, and post-index plan checkpoints. Wave A may capture only the
first two, and the post-index checkpoint must not exist until the participant
applies the supervised recommendation in Lab 4. Task F1 owns the
workshop-environment wiring for the lab variables.

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
