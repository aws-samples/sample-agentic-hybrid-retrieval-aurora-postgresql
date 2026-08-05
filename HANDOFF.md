# Handoff

Current DAT410 redesign state as of August 5, 2026.

## Read This First

The branch `worktree-dat410-review-remediation` is implementing the approved
four-phase online-migration scenario. The redesign is not release-complete.
Do not extend the retired ordinary-`CREATE INDEX` / concurrent-index-repair
mechanism that still exists in portions of the runtime, tests, UI, and docs.

The binding implementation plan is
`docs/superpowers/plans/2026-08-04-dat410-incident-scenario-redesign-plan.md`.
Tasks A1-A5 are the completed schema/admission/proof foundation. Tasks A6-G3 own
the remaining gate, runtime, retrieval, agent, UI, documentation,
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

Not yet implemented: G-34's retroactive-safety gate, the new orchestration and
evidence builder, final retrieval corpus, revised agent, participant UI and
labs, documentation cleanup, infrastructure packaging, and live rehearsal.
Until those tasks land, `make live-workshop` is not evidence that the approved
scenario is complete.

## Latest Validation

Task A5 was validated on August 5 against the dedicated
`dat410_review_remediation_test` database on the `agenticretrieval...` Aurora
PostgreSQL 18.3 cluster in `us-east-1`:

- `make schema`: passed with Aurora PostgreSQL 18.3 and pgvector 0.8.1.
- Full core suite: 189 tests passed, 50 expected live/security skips.
- `make security-schema`: passed with managed `pg_columnmask` 1.1.0.
- Supervised-execution suite under security mode: 39 tests passed, zero skips.

The test database contains disposable contract fixtures and is not a
participant database. The earlier local PostgreSQL 18.4 run was diagnostic only
and is not release evidence.

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
