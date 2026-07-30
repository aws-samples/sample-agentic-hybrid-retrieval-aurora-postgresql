# RLS personas + column masking — design

Date: 2026-07-28
Status: draft for review. Upgrades SPEC decisions **D24 / G-27**, extends
**G-26** (and re-measures **G-21**) over an enlarged seed, and adds **G-29**;
does not reverse them, and leaves G-28 hole integrity unchanged. Companion and
authority:
`docs/superpowers/specs/2026-07-28-dat410-participant-exercises-design.md`
(the "belt and suspenders" backstop rationale) and `SPEC-session.md` draft-20.
This doc is the long-form rationale; the SPEC remains authoritative once synced.

## Purpose

Make Row-Level Security the credible headline of the entitlement story, backed
by three realistic personas and role-driven column masking, **without removing
the explicit `acl_visible` predicate**. The predicate stays as the arm/hop
mechanism and the Lab 3 participant hole (H2); RLS moves from a single-role GUC
demo to real PostgreSQL login roles enforced at the base tables. The result is
strictly stronger than the committed design: the database refuses restricted
rows even when a caller connects directly as a persona role and skips the app
and the predicate entirely.

## Why this is an upgrade, not a reversal

The committed participant-exercises design bound **D24 direction C**: keep the
explicit predicate as the mechanism and the hole; add RLS "once in the schema
as a default-deny backstop," demonstrated in a ~45s coda with a session GUC
(`SET LOCAL verity.role`). That decision protects three things this design also
protects:

1. **Lab 3 H2 hole** — participants still hand-write `acl_visible` at the hop.
   Deleting the predicate would delete one of only three hands-on SQL holes.
2. **Self-contained verify-SQL (M2 / Law 2)** — a pasted `SELECT` returns the
   same rows with no hidden session-variable prerequisite. The predicate
   preserves this; RLS-only would require a hidden `SET ROLE` before every
   verify snippet.
3. **Planner-early filtering** — the predicate is sargable against the
   `acl_visibility` / `acl_principals` scalar columns and their indexes.

This design changes exactly one thing in D24: the backstop's identity mechanism
becomes **three real login roles** instead of one session GUC. That is a
strengthening (real roles are a genuine trust boundary a GUC is not) and it is
*required* by the persona/masking goal, because `pg_columnmask` binds masking
policies to roles.

## Verified ground truth (live cluster + feasibility spike, 2026-07-28)

Read-only checks ran against the live `retrieval` database on Aurora
PostgreSQL 18.3 (`agenticretrievalcorestack-…-rxrppbdex0nu`). Behavioural
claims (RLS enforcement, masking, fail-closed) were proven on five disposable
databases (`rls_spike…`), each created and dropped inside the spike; every
spike role was prefixed and dropped in a `finally`, and the live `retrieval`
database was asserted present and untouched after each run.

- **`pg_columnmask` is available** on this cluster (in `pg_available_extensions`
  alongside `pgcrypto`; `anon` is not available). It is an Aurora-managed
  extension that binds column-masking policies to **roles**, with built-ins
  `mask_email` / `mask_text` / `mask_timestamp` plus custom functions and
  per-role weights. Spike-confirmed: `CREATE EXTENSION pg_columnmask` succeeds
  when run as `retrieval_admin`.
- **`retrieval_admin` bypasses RLS — this is the load-bearing correction.**
  It owns all 22 `casework`, 5 `retrieval`, and 14 `proof` tables, and
  although `rolsuper=false` / `rolbypassrls=false` / `is_superuser=off`, it is
  a **member of `rds_superuser`** (the RDS master identity). The spike proved
  every RLS policy is silently bypassed by a bare `retrieval_admin` connection:
  under a policy admitting only `vis='workshop'`, the owner still saw both
  rows (`owner=2`) even when the policy predicate evaluated to `False` — it is
  not the predicate failing, it is RLS not applying to the master. `FORCE ROW
  LEVEL SECURITY` does **not** subject the RDS master. The spike also proved
  the escape: the instant the connection issues `SET ROLE` to any non-master
  role, enforcement snaps on (a plain persona role sees exactly one row). This
  refutes the earlier draft's "FORCE is sufficient" claim and drives the
  connection-identity decision below.
- **The persona roles do not exist yet.** Only `retrieval_admin` +
  `rdswriteforwarduser` + RDS system roles are present.
- **All retrieval functions are `SECURITY INVOKER`** (no `SECURITY DEFINER`
  anywhere under `sql/`). RLS therefore evaluates against the connected role,
  and no `SET ROLE` tricks inside function bodies are needed.

## Enforcement topology (the load-bearing finding)

RLS on `casework.evidence_items` alone is **insufficient and unsafe**: the two
highest-volume arms never read that table.

- `retrieval.vector_search` reads `retrieval.chunks` **standalone** and returns
  `chunk_text` from the chunk row before any join, filtering on the chunk's own
  `acl_visibility` / `acl_principals` scalar columns
  (`sql/03_search_functions.sql:488-514`).
- `retrieval.fuzzy_search` reads `retrieval.documents` standalone, filtering on
  the document's own `acl_visibility` / `acl_principals`
  (`sql/03_search_functions.sql:614-634`).
- `retrieval.full_text_search`'s three CTEs filter on `retrieval.documents.acl`
  (`sql/03_search_functions.sql:300,339,372`).
- `retrieval.traverse_evidence` (both hops) and the first `evidence_detail`
  query filter on `casework.evidence_items.acl`
  (`sql/09_traverse_evidence.sql:36,61`; `backend/app/main.py:390`).

The `acl` value is denormalized onto the retrieval tables at index-build time
(`casework.evidence_items.acl` → `retrieval.documents.acl` /`.acl_visibility` /
`.acl_principals` at `sql/01_schema.sql:900-902`, → `retrieval.chunks.acl*` at
`:967-969`, kept in sync by the backfill at `:1039-1074` and
`backend/app/search_index.py:521-525`).

**Therefore RLS policies attach to all three read-path tables:**
`casework.evidence_items`, `retrieval.documents`, `retrieval.chunks`. Each gets
`ENABLE` **and** `FORCE ROW LEVEL SECURITY`. Missing any one of the retrieval
tables leaks restricted body text through vector/fuzzy while headers stay
filtered — this is the single most important correctness requirement in this
design.

**And to the evidence detail tables.** The three read-path tables above are the
*header* and the *derived index*. The sensitive text — `account_name`,
`description`, `customer_commitment` — lives in the per-kind detail tables keyed
1:1 on `casework.evidence_items.evidence_id`
(`casework.incidents`, `.changes`, `.support_cases`, `.runbooks`,
`.lock_evidence`, `.customer_commitments`, `.postmortems`). Personas hold
`SELECT ON ALL TABLES IN SCHEMA casework` because RLS narrows reach rather than
granting it, so without policies there an analyst is denied at
`casework.evidence_items` and then reads CASE-7421's customer commitment out of
`casework.support_cases` one query later. Each detail table gets `ENABLE` and
`FORCE` plus a policy whose predicate is a bare `EXISTS` back to the parent —
not a second copy of the clearance expression, which the detail tables have no
`acl` column to evaluate anyway. The parent is already RLS-filtered, so the
child inherits the parent's visibility; this dependency is load-bearing and
verified by negative control (with the parent's RLS disabled, the analyst sees
every child row again). The junction tables are excluded: they carry no evidence
body and are read only through `casework.v_evidence_documents`.

The one remaining un-predicated read — the standalone `retrieval.chunks` fetch
in `evidence_detail`'s second query (`backend/app/main.py:397-412`, no ACL
predicate, safe today only because its `document_version_id` came from the
ACL-checked first query) — is covered structurally once `retrieval.chunks`
carries RLS. This is a real hardening win beyond the workshop story.

## Persona model

Three login roles plus one group role for the restricted grant. The existing
seed's `principals:["support-lead"]` becomes membership in
`workshop_restricted_reader`; the restricted row's data is unchanged.

| Role | Row visibility | Column visibility | Story |
|---|---|---|---|
| `workshop_admin` | All rows incl. CASE-7421 | All unmasked | On-call lead, full access |
| `workshop_analyst` | Workshop rows only — CASE-7421 **vanishes** | Unmasked (workshop rows hold nothing sensitive) | Read-only IC; regulated cases invisible |
| `workshop_auditor` | All rows incl. CASE-7421 | Sensitive columns **masked** | Compliance auditor; confirms the case exists and process was followed, without customer PII |

- `workshop_restricted_reader` (NOLOGIN group): granted to `admin` + `auditor`;
  **not** to `analyst`. RLS row policy: `acl_visibility = 'workshop' OR
  pg_has_role(current_user, 'workshop_restricted_reader', 'USAGE')`. The
  `'USAGE'` mode (not `'MEMBER'`) is deliberate: `'MEMBER'` is transitive and
  ignores `INHERIT` / the active `SET ROLE`, so it would report `true` for any
  role transitively granted the group; `'USAGE'` respects the effective role,
  which is what RLS must key on. Spike-confirmed against the connected role.
- This exercises **both** distinct RLS capabilities the request asked for:
  analyst demonstrates **row filtering** (the row disappears), auditor
  demonstrates **column masking** (the row is present, PII is not). Auditor must
  see the row for masking to be meaningful, so it is not a redundant analyst;
  admin is the unmasked baseline that makes both visible by contrast.

### Two identity axes and how they reconcile (M3 preserved)

The design carries two orthogonal identity axes that a single "Viewing as" chip
selection sets together:

1. **Predicate axis** — the `workbench.role` GUC ∈ {`workshop`, `support-lead`},
   unchanged from D22/D24. It drives `acl_visible(role)` inside every arm and
   hop, and it is the mechanism behind protected moment **M3** (the ACL flip
   that reveals CASE-7421). This axis is what a participant hand-writes in the
   Lab 3 H2 hole and verifies in one self-contained pasted `SELECT` (M2/Law 2).
2. **Role axis** — the PostgreSQL login role ∈ {`workshop_analyst`,
   `workshop_admin`, `workshop_auditor`}, new here. It drives RLS enforcement at
   the base tables and `pg_columnmask` masking.

The chip shows the three personas; each persona **derives both axis values** in
the same request transaction:

| Persona (chip) | `SET LOCAL ROLE` | `SET LOCAL workbench.role` | Effect |
|---|---|---|---|
| Analyst | `workshop_analyst` | `workshop` | RLS + predicate both hide CASE-7421 (row filtering) |
| Admin | `workshop_admin` | `support-lead` | Sees CASE-7421, unmasked (baseline) |
| Auditor | `workshop_auditor` | `support-lead` | Sees CASE-7421, PII masked (column masking) |

This is why M3 is preserved verbatim: the flip that reveals CASE-7421 is still
"the `support-lead` predicate value makes a case appear," and the participant
still hand-writes `acl_visible` at the hop. RLS and masking ride the same chip
selection as strengthening enforcement, never replacing the taught mechanism.
D22's ban on the word "principal" on participant surfaces holds: the chip and
routes use "role" / persona nouns end-to-end.

The restricted rows (see the Seed section below; the canonical one is
`seed/corpus.py:447`, CASE-7421) carry genuinely sensitive typed columns on
`casework.support_cases`: `account_name` ("Northstar Foods (fictional)"),
`description`, `customer_commitment` ("Support leadership approval required
before disclosure"). These are the masking targets — real fields, not contrived.

## Column masking (auditor) — scope B, spike-resolved

One-time cluster setup: `CREATE EXTENSION pg_columnmask;` (per-database) and set
`pgcolumnmask.policy_admin_rolname` in the **custom DB cluster parameter group**
(no reboot required). Masking policies bind to `workshop_auditor`.

**Mask scope is resolved to B (mask typed columns AND the denormalized blob).**
The prior draft left A-vs-B open pending a spike; the spike settled it. Two
spike findings drive the design:

1. **Masking expressions must be function calls, not literals.** The exact
   procedure signature is
   `pgcolumnmask.create_masking_policy(policy_name name, table_name regclass,
   masking_expressions jsonb, roles name[], weight int)`. A bare string literal
   as an expression (e.g. `'[REDACTED]'`) is rejected with "Invalid masking
   function." A constant redaction therefore needs a **custom SQL function**.
2. **Because the expression is any function call, blob substring redaction is
   feasible.** The built-ins (`mask_text`, `mask_email`) replace the whole
   column value, but a custom `regexp_replace`-based function masks a *substring
   inside* the rendered `chunk_text` blob. The spike proved this end to end: as
   `workshop_auditor`, `chunk_text` returned
   `'[REDACTED] regulated checkout failure; leadership approval required'` —
   the sensitive entity redacted, the rest intact — while `workshop_admin` saw
   the full text. Scope A would leave that same PII visible in vector/fuzzy
   snippets, so there is no reason to ship the weaker option.

Masking functions (created in the same bootstrap SQL file, before the policies):

- Typed `account_name` → `pgcolumnmask.mask_text(account_name)` (built-in,
  whole-value). Spike output: `Northstar Foods` → `XXXXXXXXXXXXXXX`.
- Typed `customer_commitment`, `description` → custom
  `casework.mask_redact(text) RETURNS text` returning `'[REDACTED]'`.
- Blob `retrieval.chunks.chunk_text` (and the `retrieval.documents` rendered
  body) → custom `retrieval.mask_blob(text) RETURNS text` doing
  `regexp_replace(t, '<sensitive-entity-pattern>', '[REDACTED]', 'g')`. The
  pattern set is derived from the restricted rows' sensitive typed values so the
  mask is deterministic per role.
- Admin unaffected (whole values); analyst unaffected (never sees the row).

All custom masking functions are `IMMUTABLE` and deterministic so that the
auditor's masked output is byte-stable — required by the Law 2 assertion in
G-29 (the pasted verify-SQL must reproduce the panel's masked values exactly).

## App runtime plumbing (dedicated non-bypass login + `SET LOCAL ROLE`)

The trust boundary decision (2026-07-28): **the pool connects as a dedicated
non-bypass `workshop_app` login, not as `retrieval_admin`.** This is forced by
the spike finding that `retrieval_admin` bypasses RLS (via `rds_superuser`
membership): a pool that stayed `retrieval_admin` and ever forgot `SET ROLE`
would fail **open** — the exact "must remember to enforce" weakness RLS is
meant to remove, merely relocated from the predicate to the connection. The
dedicated login fails **closed** instead.

- **New `workshop_app` LOGIN role:** owns nothing, holds **no direct table
  grants**, is not a member of `rds_superuser`, lacks `BYPASSRLS`. It is
  `GRANT`ed the three persona roles (`WITH INHERIT FALSE` — it may `SET ROLE`
  to them but gains no passive access). With no role set, `workshop_app` has no
  privilege path to the read tables, so a `SELECT` **errors with permission
  denied** — strictly stronger than "returns zero rows."
- **`retrieval_admin` stays the owner/DDL/seed identity only.** Its credential
  lives **only in the bootstrap environment** (schema build, seed S1–S8, search
  index build). It never appears in the app's `.env` or the runtime pool. The
  app's `DATABASE_URL` points at `workshop_app`.
- **Single `psycopg_pool` stays** (`backend/app/db.py:15-46`), now connecting as
  `workshop_app`. `get_conn(role=…)` / `get_dict_conn(role=…)` **require** a
  persona and open a transaction whose first statements are `SET LOCAL ROLE
  workshop_<persona>` **and** `SET LOCAL workbench.role = '<workshop|
  support-lead>'` (the derived predicate value from the two-axis table). Both
  are `SET LOCAL`, transaction-scoped — the **T8 pattern** — so neither leaks
  across pooled checkouts and both revert at transaction end regardless of
  commit/abort. There is no code path that opens a request connection without a
  persona: the fail-closed login is the suspenders, the mandatory `SET LOCAL` is
  the belt.
- **Connection method decision (from the prior turn):** psycopg3 remains the
  runtime driver; **RDS Data API is rejected** (pgvector embeddings serialize as
  strings over Data API, ~1 MB result cap, higher per-call latency, would force
  a full `db.py` rewrite for zero benefit on a single pooled local cluster).
  **psql is the demonstration surface** (`\c` as a persona role, rerun the
  identical query, rows vanish / values mask) — the "aha," reachable even when
  the app is skipped.

## Removal / rewrite inventory (what the request touches, beyond additive RLS)

The predicate stays, so nothing in the ACL predicate path is deleted. What
*does* change is the **identity vocabulary**. The persona names are
participant-facing, so **D22 governs**: D22 already bound the rename of
`principal` → `role` "end-to-end so no dual vocabulary survives," and the
personas are the enumerated `role` values rendered in the "Viewing as" chip.
The earlier draft's "recommend keep `principal` as the field name" is withdrawn
— it contradicts a bound decision. The wire field, route param, env var, and
tool argument are all `role`; the persisted replay column is `role`. This is
repo-wide, not backend-only:

- **Python:** rename `workshop_principal()` and the `principal` field on the 5
  request models (`SearchRequest`, `AgentAnswerRequest`, `TraverseRequest`,
  `CompareRequest`, `QueryPlanRequest`, `backend/app/models.py:21,49,77,87,92,116`)
  to `role`; the per-run ContextVar that binds identity so the model cannot pick
  its own (`backend/app/agent_tools.py:59,79-104`); persisted identity in
  `proof.retrieval_runs.principal` / `proof.agent_runs.principal`
  (`sql/01_schema.sql:1268,1367`) read back for replay
  (`backend/app/agent.py:943`, `backend/app/insights.py:459-462`). The `role`
  value now selects **both** identity axes (persona DB role + derived
  `workbench.role` predicate value) per the two-axis table above.
- **Frontend:** the "Viewing as" toggle and `?role=` route param map to the
  three personas (`frontend/src/route.ts`; the app's request builders and
  receipt rendering). Verify against the current `route.ts` at plan time — the
  route state is `?page=&run=` today, so `role` is an addition to the param set.
- **Tests / scripts:** `backend/scripts/doctor.py:205-221`,
  `backend/scripts/smoke_test.py:110-133`, and the ACL/identity assertions in
  `backend/tests/test_retrieval_integration.py` (the two-principal jsonb tests
  at `:391-452`, `test_evidence_detail_endpoint_enforces_acl`, and the fuzzy
  probe tests) are rewritten to assert on the three roles + RLS + masking.

## Restricted-evidence seed (representative enforcement)

Today the corpus has **exactly one** restricted object: `RESTRICTED_ACL`
(`seed/corpus.py:13`, `principals:["support-lead"]`) is used once, for
`case_restricted` / CASE-7421 (`:447`). The ~15k-row background corpus
(`_background_rows`, `:900`) is uniformly `WORKSHOP_ACL`. So analyst-vs-admin
differs by a single row — thin for a headline enforcement demo.

Decision (2026-07-28): **seed ~6 restricted objects across 2–3 systems /
clusters, mixing incident / change / case kinds**, so row-filtering and masking
are visibly non-trivial. Binding constraints:

1. **New `external_key`s enter through the live seed** (`seed/corpus.py`),
   **not** `design/verity/fixtures/generate.py` — that file is **vestigial**
   (old `CHG-1000` mockup scheme, superseded by
   `design/verity/docs/ID-STANDARDIZATION.md`; it feeds no live code). The
   G-21 fixture-arithmetic invariant must be **re-measured against the enlarged
   corpus**: no new ID may enter `CHG-1842`'s trigram neighborhood (nothing
   shaped like `CHG-18xx` / `CGH-18xx`), and the `CGH-1842` → `CHG-1842`
   uniqueness + no-tie behaviour must stay green. The runnable assertions live
   in `backend/tests/test_retrieval_integration.py:391-452`
   (`test_fuzzy_arm_recovers_mistyped_identifier`,
   `test_restricted_identifier_never_enters_fuzzy_probes`,
   `test_restricted_identifier_yields_no_visible_evidence`) and the eval
   goldens at `seed/corpus.py:1681-1696`.
2. **CASE-7421 remains THE canonical M3 flip noun.** The new rows are supporting
   cast, never referenced in guide checkpoints, slides, or the canonical
   question.
3. **Canonical-question claim coverage under `role=workshop` stays
   byte-identical** (G-26 extends over this seed change). This is safe because
   every new row is restricted — invisible to `workshop` — so Lab 2 goldens,
   computed under `role=workshop`, cannot shift. The plan verifies this by
   re-running the canonical replay before and after the seed change.
4. **Masked columns are plausibly sensitive per kind:** customer-contact fields
   on cases (`account_name`, `customer_commitment`), on-call / operator
   identities on incident records. Masking reads as governance only when the
   masked field is something a real auditor would be denied.
5. **Law 2 under the auditor view:** the panel and the pasted verify-SQL show
   the **same** masked values (deterministic per role). Asserted in G-29
   alongside the FORCE-RLS checks.

## Bootstrap / idempotency

- The `workshop_app` login, the three persona roles, the
  `workshop_restricted_reader` group, all grants (`workshop_app` gets the
  personas `WITH INHERIT FALSE`), `CREATE EXTENSION`, RLS enable/force, the
  masking functions, the RLS policies, and the masking policies are all authored
  idempotently (`DO` blocks guarding `CREATE ROLE`; `CREATE OR REPLACE FUNCTION`;
  `DROP POLICY IF EXISTS` before `CREATE POLICY`; masking-policy re-creation
  guarded on the `pgcolumnmask` catalog; `CREATE EXTENSION IF NOT EXISTS`). They
  live in a new numbered SQL file in the `make schema` sequence (`Makefile`
  SQL_FILES), after the tables they reference exist.
- **Credential split:** `retrieval_admin` owns the schema and runs the seed and
  index build; its DSN lives only in the bootstrap environment. `workshop_app`
  is the app pool identity; its DSN is the app's `DATABASE_URL`. Both are
  provisioned by the sibling Workshop Studio repo (Secrets Manager + the local
  `.env`); the app repo consumes them.
- The `pgcolumnmask.policy_admin_rolname` parameter-group change is
  **infrastructure**, owned by the sibling Workshop Studio repo (CFN /
  parameter group), not this app repo. Flagged for that repo, consistent with
  the ownership boundary. Without it, `create_masking_policy` cannot be called;
  the bootstrap SQL must fail loudly (not silently skip masking) if the setting
  is absent.
- Role creation on the shared live cluster is a privileged operation, and roles
  are **cluster-global** (not database-scoped); the plan runs all
  destructive/DDL verification against a **disposable** database with
  disposable, prefixed roles first, and never touches live `retrieval` without
  explicit go-ahead.

## Spec + gate impact

- **D24** edited in place: "single-role `SET LOCAL workbench.role` GUC" → "three
  real login roles behind a non-bypass `workshop_app` login + `SET LOCAL ROLE`
  and `SET LOCAL workbench.role`, transaction-scoped." Direction C intact;
  predicate still kept; mechanism strengthened. Note the GUC token is
  `workbench.role` (the Verity→Workbench rename already landed), not
  `verity.role`.
- **G-27** (FORCE-RLS assertion) extended, three parts:
  (a) **fail-closed:** connected as `workshop_app` with **no role set**, a
  `SELECT` on `casework.evidence_items` / `retrieval.documents` /
  `retrieval.chunks` **raises permission denied** — an error, stronger than zero
  rows, proving the pool identity has no standing privilege path;
  (b) **row filtering:** under `SET LOCAL ROLE workshop_analyst` +
  `SET LOCAL workbench.role='workshop'`, CASE-7421 (and every new restricted
  row) returns **zero rows at each of the three raw tables** — proving RLS is
  not silently bypassed by ownership;
  (c) **replay determinism:** a replayed run under the receipt's recorded role
  reproduces identical candidates (both `SET LOCAL`, transaction-scoped, never
  session-scoped).
- **G-29 (new):** masking + Law-2 determinism — under `workshop_auditor`,
  CASE-7421 is visible but `account_name` / `customer_commitment` / the
  `chunk_text` blob return **masked**, and the value shown in the app panel is
  **byte-identical** to the value returned by the pasted verify-SQL run in psql
  (deterministic per role); `workshop_admin` sees all three unmasked. Because
  masking functions are `IMMUTABLE`, the two surfaces cannot diverge.
- Both `SPEC-session.md` copies re-synced byte-identical to a new draft
  (`design/SPEC-session.md` and `design/verity-handoff/docs/SPEC-session.md`;
  verified the only two in the tree, currently at sha256 `d0601f06…`).

## Deliberate non-goals

- **No auth middleware.** The persona is still app-asserted (the unauthenticated
  "Viewing as" picker chooses which role a request assumes). RLS strengthens
  *enforcement* (structural, un-forgettable at the table), not *authentication*
  (still absent by documented teaching policy, SECURITY_REVIEW.md). The workshop
  claim is stated precisely: "RLS moves enforcement into the database; which
  persona you are is still asserted by the app." Overclaiming this as
  authentication would be dishonest and is out of scope.
- **No removal of the predicate** (per decision this turn).
- **No Data API adoption** (per decision the prior turn).

## Open items carried to the plan

1. ~~Mask scope A vs B~~ — **resolved to B** by the feasibility spike (custom
   `regexp_replace` masking function redacts substrings inside the `chunk_text`
   blob; proven on a disposable DB).
2. ~~Wire field name `principal` vs `role`~~ — **resolved to `role`** (D22
   already bound the end-to-end rename; the earlier "keep principal"
   recommendation is withdrawn).
3. Parameter-group change for `pgcolumnmask.policy_admin_rolname` — sibling repo
   (bootstrap SQL must fail loudly if absent, not silently skip masking).
4. Provisioning of the `workshop_app` credential (Secrets Manager + local
   `.env` `DATABASE_URL`) and the `retrieval_admin` bootstrap-only DSN — sibling
   Workshop Studio repo. The app repo consumes both; it does not create them.
5. Two-artifact packaging (frozen reference vs participant start) already
   flagged by the participant-exercises design; the H2 hole is unchanged by this
   design, so no new packaging burden beyond what that doc carries.
6. Exact restricted-row count and their `external_key`s / systems (target ~6
   across 2–3 systems) — chosen at plan time under the G-21 re-measurement
   constraint, then locked in the seed.
