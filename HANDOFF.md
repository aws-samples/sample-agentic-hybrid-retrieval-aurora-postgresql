# Handoff

State of the two DAT410 repositories as of August 1, 2026, and what a new
maintainer needs to know before changing either one.

Read `AGENTS.md` first for the architecture and editing boundaries. This file
covers what those documents cannot: which work is finished, which is
deliberately deferred, and which traps have already cost someone a day.

## The two repositories

| Repository | Path | Branch | Remote | Contains |
|---|---|---|---|---|
| Application (this one) | `sample-agentic-hybrid-retrieval-aurora-postgresql` | `main` | GitHub `aws-samples`, currently **private** | Schema, retrieval SQL, API, frontend, gates, seed, tests |
| Workshop guide (sibling) | `build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql` | `mainline` | `workshopstudio://ws-content-d2acf248-...` | Workshop Studio participant content, facilitator guide, assets |

They are coupled in one direction: the guide publishes an immutable source
revision of the application. Freeze the application revision first, then update
the guide to match. Doing it the other way produces a guide whose commands do
not match the packaged source.

The sibling repo has five local commits on `mainline` that have not been pushed,
plus the uncommitted release-label and archive-validation edits described below.
**Workshop Studio pushes are user-managed.** Do not push that repo without
asking.

## Status

The required application path is feature-complete for the session: diagnose the
controlled incident through hybrid retrieval, fusion and reranking, agent
tools, cited synthesis, and persisted diagnostics and replay. That path runs
with the default App Engineer persona and does not depend on persona switching
or `pg_columnmask`.

The current worktree also contains the optional persona appendix implementation.
It has three NOLOGIN persona roles (`persona_app_engineer`,
`persona_auditor`, `persona_dba`), one clearance role
(`can_see_restricted`) granted to Auditor and DBA and never to App Engineer, two
LOGIN roles (`workshop_app` for the pool, `workshop_participant` for terminals),
RLS enabled and forced on the three read-path tables, generated reachability
policies on every detail and junction table beneath
`casework.evidence_items`, and `pg_columnmask` masking for Auditor. This is a
real implementation boundary, but its App Engineer, Auditor, DBA comparison is
an optional appendix rather than the workshop's central claim.

## First hour

Read `AGENTS.md`, then `README.md`'s local runbook, then the Hazards section
below before running anything that writes.

```bash
make install
pg_isready -h localhost -p 5432          # see hazard 3 about the port
createdb wb_onboard_test
DATABASE_URL='postgresql://localhost:5432/wb_onboard_test?sslmode=disable' make schema
DATABASE_URL='postgresql://localhost:5432/wb_onboard_test?sslmode=disable' make seed-local
DATABASE_URL='postgresql://localhost:5432/wb_onboard_test?sslmode=disable' \
TEST_DATABASE_URL='postgresql://localhost:5432/wb_onboard_test?sslmode=disable' \
  ALLOW_TEST_DATABASE_RESET=1 make test
gates/checks.sh G-11 G-17 G-23           # the three that need no database
dropdb wb_onboard_test
```

`make schema` applies only the core SQL files, `sql/00_extensions.sql` through
`sql/10_admission.sql`; it does not apply either optional security migration.
`make seed-local` uses hash embeddings and an offline capture, so it needs no
AWS credentials. If you separately run `make security-schema`,
`sql/11_roles_rls.sql` creates six cluster-global roles
(`can_see_restricted`, three `persona_*`, `workshop_app`,
`workshop_participant`) that outlive the database. Only in that case, drop those
roles when you drop the database or the next run inherits them.

## Hazards that have already caused damage

**1. `DATABASE_URL` points at live Aurora, and the tooling reads it, not
`TEST_DATABASE_URL`.** `scripts/run_sql.py` and `backend/app/db.get_conn` both
resolve `DATABASE_URL` from `.env`. Exporting only `TEST_DATABASE_URL` does not
scope them. This dropped the live database once. Before any destructive
statement: inline-prefix `DATABASE_URL=...` on the command itself, and assert
`current_database()` first. Never run schema, seed, or reset against the live
`retrieval` database.

**2. `make test` needs a disposable database whose name ends in `_test`.** The
suite refuses otherwise. It also needs `ALLOW_TEST_DATABASE_RESET=1`. One
integration test deletes `CASE-7424` and leaves it deleted, which invalidates
G-31 afterwards, so run gates before `make test` or after a reseed.

**3. The documented local port is wrong on at least one dev machine.**
`Makefile:8` and `README.md:233` both say `55432`. Measured on the maintainer's
laptop, `pg_isready -p 55432` gets no response and `-p 5432` accepts. Neither
line has been corrected because the right value depends on how you run local
PostgreSQL. Check with `pg_isready` before believing a connection failure.

**4. `make schema` requires PostgreSQL >= 18.3** (`Makefile:11`, enforced by
`backend/scripts/check_postgres.py`). A local 17.x cluster cannot host the
substrate, and `seed/capture.py` additionally needs `pg_stat_statements` in
`shared_preload_libraries`. Both failures look like DSN problems and are not.

**5. Masking cannot be verified locally.** `pg_columnmask` is Aurora-managed.
`sql/12_masking.sql` is skipped on local clusters and `ColumnMaskingTests` in
`backend/tests/test_rls_personas.py` skips with it. A local `OK` is not
coverage of masking. Run that suite against a disposable database on Aurora to
cover it.

**6. `FORCE ROW LEVEL SECURITY` does not subject a superuser.** A local cluster
whose owner is a superuser exercises the policies only through the persona
roles. A green local run does not verify the owner-side policy `TO`-list fix.

**7. Never `git add -A` from the repo root.** Untracked directories here must
not be committed.

## Invariants that must not regress

These are load-bearing implementation and security boundaries. Violating any of
them makes the optional persona appendix dishonest, and several have been
broken and repaired already.

- **Fail-closed.** `workshop_app` holds no read grant on
  `casework.evidence_items`, `retrieval.documents`, or `retrieval.chunks`. A
  forgotten `SET LOCAL ROLE` must raise `permission denied`, never return rows.
  If the pool login can read a table directly, every row-filtering test in the
  repo becomes decorative.
- **`SET LOCAL ROLE`, never session `SET`.** The pool is shared; a
  session-scoped role leaks to the next borrower.
- **RLS enabled and forced on all three read-path tables.** The vector and
  fuzzy arms read `retrieval.chunks` standalone, so a documents-only policy
  leaks restricted body text.
- **Two predicate forms, one rule.** `retrieval.documents` and
  `retrieval.chunks` carry a scalar `acl_visibility` column.
  `casework.evidence_items` has no such column, only `acl jsonb`, so its policy
  reads `coalesce(acl ->> 'visibility', 'restricted')`. Applying the scalar form
  to `evidence_items` errors. This mistake has been introduced and corrected
  twice; do not make it a third time.
- **Default closed.** A missing or unrecognized visibility value resolves to
  restricted, never to visible.
- **Law 2, byte-identity.** A value shown in the app must be byte-identical to
  what the panel's pasteable `_verify_sql` returns in psql. Role-sensitive
  verify-SQL carries the envelope
  `BEGIN; SET LOCAL ROLE <persona>; <SELECT>; ROLLBACK;`.
- **Canonical retrieval stays in SQL.** No ranking, fusion, or ACL logic
  duplicated into prompts, the frontend, MCP adapters, or agent harnesses.
  `casework.*` is authoritative; `retrieval.*` is derived and never hand-edited.
- **Generated files are generated.** `lambda_mcp/generated_dispatch.py` and
  `mcp-server/src/server.generated.ts` come from `agent/registry.py`. Edit the
  registry and regenerate; gate G-17 fails on drift.
- **Both SPEC copies stay byte-identical:** `design/SPEC-session.md` and
  `design/verity-handoff/docs/SPEC-session.md`. Edit one, copy over the other.
- **Em-dash policy is per-file-family.** `README.md` and `docs/` are
  zero-em-dash. `design/` and `docs/superpowers/` use them legitimately.

## Gates

Eleven gates are registered in `gates/checks.sh`. A no-argument
`gates/checks.sh` runs the seven core retrieval gates. `make security-checks`,
or explicit IDs, runs the four optional security gates. Exit codes are 0 PASS,
1 FAIL, 2 BLOCKED, where BLOCKED means the subject under test does not exist yet
and is reported honestly rather than as a pass. The orchestrator fails only on
FAIL.

**Never run `gates/checks.sh` with no arguments unless you intend to touch
live.** The default core set includes database-backed gates, and
`gates/_common.py:read_env_value()` falls back to `.env`.

G-11, G-14, G-17, and G-23 are static and need no database. The optional
security gates are G-27 (`rls_enforcement.py`), G-29
(`masking_determinism.py`), G-30 (`participant_ceremony.py`), and G-31
(`persona_equivalence.py`). They may report BLOCKED against live until the
appendix DDL is deployed. That does not block the default incident-diagnosis
release path.

## Completed in the current worktree

**Persona rename.** The approved July 31 vocabulary change is implemented:
`analyst` became `app_engineer`, `admin` became `dba`, and `auditor` is
unchanged. Labels and comparison order are App Engineer, Auditor, DBA. The
rename covers wire values, database roles, proof receipts, API contracts,
frontend routes, generated adapters, gates, tests, and upgrade DDL. The access
model is unchanged: Auditor and DBA hold clearance, and masking applies only to
Auditor.

**Participant incident lab.** `labs/incident/` now contains the exact
three-terminal SQL workflow for the session spine. It creates only
`workbench_lab`, proves the ordinary `CREATE INDEX` `ShareLock` against a
waiting writer `RowExclusiveLock`, writes a measured lock snapshot, rolls the
ordinary build back, then proves fresh DML succeeds beside
`CREATE INDEX CONCURRENTLY` and verifies the final index. The exact scripts pass
through `backend/tests/test_incident_lab.py` on PostgreSQL 18.4. The measured
capture can be promoted through `admission/admit.sh`; admission queues search
projection and does not claim immediate hybrid retrieval.

**Session and Workshop Studio narrative.** `design/SPEC-session.md` and its
handoff copy now describe only the shipped 60-minute contract. The old
25-million-row `shop.orders`, pgbench services, 3 GB working-set claim, and
240-420 second timing gates are explicitly deferred. The sibling guide is
rewritten around the same spine: observe, reproduce, retrieve, investigate,
prove, and replay. RLS/masking and AgentCore remain optional top-level modules.
The required pacing uses clean clock boundaries: 5 minutes context, 5
readiness, 10 incident reproduction, 20 retrieval, 10 agent investigation, 5
proof and replay, and 5 summary.

**Release artifact producer.** `seed/dump.sh` requires
`ALLOW_SEED_DUMP=1` and a server-reported database name ending in `_test`.
It writes `.revision` and `.sha256` sidecars. `seed/load.sh` refuses checksum
drift. `scripts/build_source_archive.sh` requires all nine incident SQL files,
verifies revision and checksum parity, verifies the three dump schemas, and
packages a custom `SEED_ARTIFACT` under the canonical v2 name. The sibling
templates and facilitator checks now name `hybrid-retrieval-seed-v2.dump`.
Workshop Studio keeps `SourceRevision=UNRELEASED` and bootstrap rejects both
that sentinel and any zip-comment mismatch, so the retained v1 archive cannot
silently provision. Checksum helpers prefer Linux `sha256sum` and fall back to
macOS `shasum`, so the integrity check works in both release and participant
environments.

## Deferred work, in the order it should be picked up

**1. Freeze and package the application.** The real v2 dump does not exist yet.
Create a seeded disposable database whose name ends in `_test`, run
`ALLOW_SEED_DUMP=1 make seed-dump`, then build the source archive from the same
committed revision. Do not use the live Aurora database as the dump source.

**2. Complete a fresh-account target rehearsal.** Provision the Workshop Studio
stack in `us-east-1` on the representative `db.r8g.2xlarge`, run all nine
incident scripts with the participant role, and validate exact, fuzzy,
semantic, hybrid, rerank fallback, cited answer, graph, timeline, evaluation,
and replay. Resolve the known live search-index drift before using that cluster
as release evidence.

**3. Apply and validate the optional appendix DDL on live Aurora.**
`sql/11_roles_rls.sql` and `sql/12_masking.sql` have not been applied to the
live cluster. Run `make security-schema` there and the four optional security
gates before publishing the App Engineer, Auditor, DBA comparison. This is not
a prerequisite for the default core release.

The sequence is written out step by step at
`docs/superpowers/plans/2026-07-28-rls-personas-column-masking.md:8496-8663`
(Task 16, Steps 9 to 17). Step 9 is a deliberate stop-and-ask gate. Three
defects in that text must be corrected before executing it:

- The `pgcolumnmask.policy_admin_rolname` warning is contradicted by
  `sql/12_masking.sql`'s own measured header.
- The `refresh_mask_blob() -> 15` expectation rests on a false claim that
  `sensitive_literals()` was extended to incidents and changes. It was not; it
  reads `casework.support_cases` only.
- Step 14 diffs against `/tmp/canonical_after_collapse.json`, an artifact that
  never existed because the task that would have produced it was BLOCKED.

## Things that look like bugs but are not

- Optional security gates reporting BLOCKED against live. Expected until the
  appendix deploy runs.
- `ColumnMaskingTests` skipping. Expected on any local cluster.
- `retrieval.acl_principals` columns and their GIN index being populated but
  unread. Kept deliberately to avoid schema churn; documented in
  `docs/data-model.md`.
- `# noqa: C901` on the RLS gates' `run()` functions. The gates are written as
  a top-to-bottom narrative on purpose, and the repo configures no linter.
- `couldn't stop thread 'workbench-pg-worker-N'` on test teardown. A pre-existing
  `psycopg_pool` shutdown message; it does not affect results.

## Where the reasoning lives

The design and plan documents are tracked, and they carry the argument behind
every decision above:

- `docs/superpowers/specs/2026-07-28-rls-personas-column-masking-design.md`, the
  approved design, including its open items.
- `docs/superpowers/plans/2026-07-28-rls-personas-column-masking.md`, the 16-task
  plan with the Global Constraints block that bound every task.
- `design/SPEC-session.md`, the current session and release contract.

`.superpowers/sdd/` holds the execution ledger, per-task briefs, reports, and
review packages. It is gitignored (`.superpowers/sdd/.gitignore` is `*`), so it
exists only on the machine that ran the plan and will not arrive with a clone.
If you need the execution history and do not have that directory, `git log
1b0c90e..ca7df80` is the durable record.

## Conventions

Commits are authored `shayons@amazon.com` with no AI co-attribution trailer, in
imperative mood, one logical change each. `README.md` and `docs/` take no
em-dashes. Do not push either repository without explicit authorization.
