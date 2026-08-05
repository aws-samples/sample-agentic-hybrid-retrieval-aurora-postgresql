# Handoff

Current DAT410 redesign state as of August 5, 2026.

## Read This First

The branch `worktree-dat410-review-remediation` is implementing the approved
four-phase online-migration scenario. The redesign is not release-complete.
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
| `sample-agentic-hybrid-retrieval-aurora-postgresql` | `worktree-dat410-review-remediation` | implementation worktree; do not edit the concurrent primary checkout |
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

Not yet implemented: the migration driver, pool-collision orchestration and
evidence builder, final retrieval corpus, revised agent, participant UI and labs,
remaining documentation cleanup,
infrastructure packaging, and live rehearsal.
Until those tasks land, `make live-workshop` is not evidence that the approved
scenario is complete.

## Latest Validation

The branch was validated on August 5 against the dedicated
`dat410_review_remediation_test` database on the `agenticretrieval...` Aurora
PostgreSQL 18.3 cluster in `us-east-1`:

- Exact test-target preflight: passed as Aurora PostgreSQL 18.3 in `us-east-1`.
- Full core suite: 202 tests passed, 50 expected live/security skips.
- `make security-schema`: passed with managed `pg_columnmask` 1.1.0.
- Supervised-execution suite under security mode: 39 tests passed, zero skips.
- G-34 focused suite: 11 tests passed; the gate passed directly and through
  `gates/checks.sh G-34`.
- B1 bootstrap: 32.13 seconds on `db.r8g.2xlarge`; 3,000,000 canonical orders,
  5,000 customers, 248,193,024 bytes, fresh `ANALYZE`, no `priority_tier` or
  `updated_at`, and zero evidence rows.

The test database contains disposable contract fixtures and is not a
participant database. The earlier local PostgreSQL 18.4 run was diagnostic only
and is not release evidence.

Current disposable-database state after B1 validation: core schema plus the
3,000,000-row `workbench_lab` workload, zero evidence, and no optional security
module. Reapply `make security-schema` before security-only checks.

## Next Task

Start B1a: create `labs/incident/migration.py`, then replace the retired
ordinary-index hold mechanism with the separate committed `ADD COLUMN` and
open unbatched backfill. A pre-implementation probe on Aurora 18.3 confirmed
that `SELECT 7 % 5` returns `2`, while `SELECT 7 %% 5` fails with `42883`; use a
single `%` in the unparameterized backfill `UPDATE`. Keep `%%` only in SQL that
is passed through psycopg parameter interpolation.

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
