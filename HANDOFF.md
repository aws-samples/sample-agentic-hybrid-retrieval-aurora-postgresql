# Handoff

State of the two DAT410 repositories as of July 31, 2026, and what a new
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

The sibling repo has four local commits on `mainline` that have not been pushed.
**Workshop Studio pushes are user-managed.** Do not push that repo without
asking.

## Status

The application is feature-complete for the session and reviewed. The most
recent unit of work built row-level security as the real enforcement layer: 30
commits, `1b0c90e..ca7df80`, all pushed. A whole-branch review returned ready to
merge with no findings.

What that means concretely: the workshop's central claim, that the database
refuses rather than the application, is now true and tested rather than
narrated. Three NOLOGIN persona roles (`persona_analyst`, `persona_admin`,
`persona_auditor`), one clearance role (`can_see_restricted`) granted to admin
and auditor and never to analyst, two LOGIN roles (`workshop_app` for the pool,
`workshop_participant` for terminals), RLS enabled and forced on the three
read-path tables, generated reachability policies on every detail and junction
table beneath `casework.evidence_items`, and `pg_columnmask` masking for the
auditor.

## First hour

Read `AGENTS.md`, then `README.md`'s local runbook, then the Hazards section
below before running anything that writes.

```bash
make install
pg_isready -h localhost -p 5432          # see hazard 3 about the port
createdb wb_onboard_test
DATABASE_URL='postgresql://localhost:5432/wb_onboard_test?sslmode=disable' make schema
DATABASE_URL='postgresql://localhost:5432/wb_onboard_test?sslmode=disable' make seed-local
TEST_DATABASE_URL='postgresql://localhost:5432/wb_onboard_test?sslmode=disable' \
  ALLOW_TEST_DATABASE_RESET=1 make test
gates/checks.sh G-11 G-17 G-23           # the three that need no database
dropdb wb_onboard_test
```

`make seed-local` uses hash embeddings and an offline capture, so it needs no
AWS credentials. `sql/11_roles_rls.sql` creates six cluster-global roles
(`can_see_restricted`, three `persona_*`, `workshop_app`,
`workshop_participant`), which outlive the database. Drop them when you drop the
database, or the next run inherits them.

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

These are load-bearing. Violating any of them breaks the session's central
claim, and several have been broken and repaired already.

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

Eleven gates, registered in `gates/checks.sh`. `gates/checks.sh` runs
everything; `gates/checks.sh G-11 G-23` runs a subset. Exit codes are 0 PASS,
1 FAIL, 2 BLOCKED, where BLOCKED means the subject under test does not exist yet
and is reported honestly rather than as a pass. The orchestrator fails only on
FAIL.

**Never run `gates/checks.sh` with no arguments unless you intend to touch
live.** `gates/_common.py:read_env_value()` falls back to `.env`.

G-11, G-17, and G-23 are static and need no database. The four RLS gates
(`rls_enforcement.py`, `masking_determinism.py`, `participant_ceremony.py`,
`persona_equivalence.py`) will report BLOCKED against live until the deploy
below runs.

## Deferred work, in the order it should be picked up

**1. Apply the new DDL to live Aurora.** `sql/11_roles_rls.sql` and
`sql/12_masking.sql` have never been applied to the live cluster, so `make
schema` must be re-run there before this code ships. This was deliberately
deferred, not forgotten.

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

**2. Rename the personas to database-oriented names.** Approved July 31, 2026.
`analyst` becomes `app_engineer`, `admin` becomes `dba`, `auditor` is unchanged.
Labels: App Engineer, Auditor, DBA. This is a full rename including wire values,
not labels only, so that the word on screen matches the word in the pasteable
proof.

The access model does not change: clearance already goes to the two upper
personas and masking already applies only to the auditor. This is vocabulary.

Footprint is roughly 603 occurrences of `analyst` and 124 word-boundary `admin`
across about 50 files, plus five parts that are not text substitution:

- `admin` is a substring, not a word. `retrieval_admin` is the schema owner,
  `workshop_admin` is the Aurora cluster master set by the sibling repo's
  CloudFormation template, and `policy_admin_rolname` plus several
  `admin_*` gate-local variables are unrelated. Use `\badmin\b` and check every
  hit. `analyst` is safe: all occurrences are one sense, no plurals.
- `sql/01_schema.sql:1445,1451` pin the old values in CHECK constraints on
  `proof.retrieval_runs` and `proof.agent_runs`, with `DEFAULT 'analyst'`.
  Existing receipt rows need a backfill, in the same idempotent style as the
  `retrieval_runs.principal` to `role` collapse already in that file.
- `agent/registry.py:272-273` holds the enum; regenerate both generated files
  afterwards.
- G-23 parses the `/agent?role={...}` literals and scans the built
  `frontend/dist` bundle, so rebuild the frontend or the gate blocks.
- The live `ALTER ROLE ... RENAME` belongs with the deploy above.

This breaks `?role=analyst` deep links in the guide, so it ships together with
the sibling-repo updates.

**3. Rewrite the Workshop Studio guide.** This is the largest remaining piece
and it belongs in the sibling repo, gated on freezing the application revision.
`WORKSHOP_GUIDE_TODO.md` there tracks it. Two requirements are not obvious from
that checklist:

- Module names must align with the application's surfaces (Overview, Hybrid
  Retrieval, Agentic Retrieval, Proof) rather than the retired Orion-era task
  framing. A participant navigates by surface name, so a module called "Audit
  cited answer provenance" gives them no way to know which tab to click. Do not
  rename titles alone: the module bodies are still the retired Orion and `ops.*`
  workshop, so a rename without a body rewrite makes the mismatch worse.
- Keep the incident as the spine for the full 60 minutes. RLS should be one
  memorable three-way comparison on a single query, App Engineer then Auditor
  then DBA, not a third workshop. Gateway deployment, connectors, extensive
  tuning, and production identity architecture belong in the appendix.

## Things that look like bugs but are not

- Gates reporting BLOCKED against live. Expected until the deploy runs.
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
- `design/SPEC-session.md` sections 6.x, the session contract.

`.superpowers/sdd/` holds the execution ledger, per-task briefs, reports, and
review packages. It is gitignored (`.superpowers/sdd/.gitignore` is `*`), so it
exists only on the machine that ran the plan and will not arrive with a clone.
If you need the execution history and do not have that directory, `git log
1b0c90e..ca7df80` is the durable record.

## Conventions

Commits are authored `shayons@amazon.com` with no AI co-attribution trailer, in
imperative mood, one logical change each. `README.md` and `docs/` take no
em-dashes. Do not push either repository without explicit authorization.
