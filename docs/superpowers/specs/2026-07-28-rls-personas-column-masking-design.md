# RLS personas + column masking — design

Date: 2026-07-28
Status: draft for review. Upgrades SPEC decisions **D24 / G-27 / G-28** and adds
**G-29**; does not reverse them. Companion and authority:
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

## Verified ground truth (live cluster, 2026-07-28)

All checks run read-only against the live `retrieval` database on Aurora
PostgreSQL 18.3 (`agenticretrievalcorestack-…-rxrppbdex0nu`).

- **`pg_columnmask` is available** on this cluster (in `pg_available_extensions`
  alongside `pgcrypto`; `anon` is not available). It is an Aurora-managed
  extension that binds column-masking policies to **roles**, with built-ins
  `mask_email` / `mask_text` / `mask_timestamp` plus custom functions and
  per-role weights.
- **The app role owns every table.** `retrieval_admin` owns all 22 `casework`,
  5 `retrieval`, and 14 `proof` tables. It is **not** `rolsuper` and **not**
  `rolbypassrls`. Because **table owners bypass RLS by default**, every policy
  must be paired with `FORCE ROW LEVEL SECURITY` or it silently does nothing for
  the app connection. FORCE is sufficient here (no superuser/bypass to strip).
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
  pg_has_role('workshop_restricted_reader','MEMBER')`.
- This exercises **both** distinct RLS capabilities the request asked for:
  analyst demonstrates **row filtering** (the row disappears), auditor
  demonstrates **column masking** (the row is present, PII is not). Auditor must
  see the row for masking to be meaningful, so it is not a redundant analyst;
  admin is the unmasked baseline that makes both visible by contrast.

The restricted row (`seed/corpus.py:445-471`, CASE-7421) carries genuinely
sensitive typed columns on `casework.support_cases`: `account_name`
("Northstar Foods (fictional)"), `description`, `customer_commitment`
("Support leadership approval required before disclosure"). These are the
masking targets — real fields, not contrived.

## Column masking (auditor)

One-time cluster setup: `CREATE EXTENSION pg_columnmask;` (per-database) and set
`pgcolumnmask.policy_admin_rolname` in the **custom DB cluster parameter group**
(no reboot required). Masking policies bind to `workshop_auditor`:

- `account_name` → `pgcolumnmask.mask_text` (partial: `Northstar F***`).
- `customer_commitment`, `description` → custom `mask_redact` returning
  `[REDACTED]`.
- Admin unaffected (sees whole); analyst unaffected (never sees the row).

**Open feasibility question, resolved at plan time (per decision this turn).**
`pg_columnmask` masks whole *typed column values* natively. The restricted body
is also denormalized as a free-text blob into `retrieval.documents`/`chunks`
(what vector/fuzzy actually return). Masking a substring inside a rendered blob
is not what `pg_columnmask` does natively. The plan will run a feasibility spike
against a **disposable** database and choose between:

- **(A) Typed columns only** — mask `casework.support_cases` columns where
  `pg_columnmask` is native; on the retrieval tables the auditor gets RLS *row*
  visibility, and the sensitive blob is either excluded from the auditor's
  retrieval projection or accepted as visible-in-search / masked-in-detail.
  Clean and honest.
- **(B) Full masking incl. blobs** — a custom masking function over the rendered
  text column (or per-role re-render) so search snippets are redacted too. More
  realistic, higher complexity, needs the spike to confirm.

The persona model is identical either way; only the auditor's reach into the
denormalized blob differs.

## App runtime plumbing (`SET LOCAL ROLE` per transaction)

- **Single `psycopg_pool` stays**, still connecting as `retrieval_admin`
  (`backend/app/db.py:15-46`). `retrieval_admin` is `GRANT`ed all three persona
  roles so it can assume them.
- New `get_conn(role=…)` (and `get_dict_conn(role=…)`) wrapper opens a
  transaction and issues `SET LOCAL ROLE workshop_<persona>` as the **first
  statement** in the transaction. Transaction-scoped so it cannot leak across
  pooled checkouts — the spec's **T8 pattern**, now with a real role instead of
  a GUC. `SET LOCAL ROLE` reverts at transaction end regardless of commit/abort.
- **Connection method decision (from the prior turn):** psycopg3 remains the
  runtime driver; **RDS Data API is rejected** (pgvector embeddings serialize as
  strings over Data API, ~1 MB result cap, higher per-call latency, would force
  a full `db.py` rewrite for zero benefit on a single pooled local cluster).
  **psql is the demonstration surface** (`\c workshop_analyst`, rerun the
  identical query, rows vanish) — the "aha," reachable even when the app is
  skipped.

## Removal / rewrite inventory (what the request touches, beyond additive RLS)

The predicate stays, so nothing in the ACL predicate path is deleted. What
*does* change is the **identity vocabulary**: `workshop` / `support-lead` →
`admin` / `analyst` / `auditor`. This is repo-wide, not backend-only:

- **Python:** `workshop_principal()` and the `principal` field on 5 request
  models (`SearchRequest`, `AgentAnswerRequest`, `TraverseRequest`,
  `CompareRequest`, `QueryPlanRequest`, `backend/app/models.py:21,49,77,87,92,116`);
  the per-run ContextVar that binds identity so the model cannot pick its own
  (`backend/app/agent_tools.py:59,79-104`); persisted identity in
  `proof.retrieval_runs.principal` / `proof.agent_runs.principal`
  (`sql/01_schema.sql:1268,1367`) read back for replay
  (`backend/app/agent.py:943`, `backend/app/insights.py:459-462`).
- **Frontend:** the "Viewing as" toggle and `?principal=` route param
  (`frontend/src/route.ts:21,27,47,68-70`; `frontend/src/VerityApp.tsx` request
  builders and receipt rendering) map to three personas.
- **Tests / scripts:** `backend/scripts/doctor.py:205-221`,
  `backend/scripts/smoke_test.py:110-133`, and ~10 assertions in
  `backend/tests/test_retrieval_integration.py` are rewritten to assert on the
  three roles + RLS + masking rather than the two-principal jsonb.

Decision to carry into the plan: whether the wire keeps `principal` as the field
name (three enumerated values) or renames to `role`. D22 bans the word
"principal" from *participant surfaces* only; the code may keep it. Recommend
keeping the field name to minimize contract churn, surface label = "Viewing as".

## Bootstrap / idempotency

- Roles, grants, `CREATE EXTENSION`, RLS enable/force, policies, and masking
  policies are all authored idempotently (`DO` blocks guarding `CREATE ROLE`;
  `DROP POLICY IF EXISTS` before `CREATE POLICY`; `CREATE EXTENSION IF NOT
  EXISTS`). They live in a new numbered SQL file in the `make schema` sequence
  (`Makefile` SQL_FILES), after the tables they reference exist.
- The `pgcolumnmask.policy_admin_rolname` parameter-group change is
  **infrastructure**, owned by the sibling Workshop Studio repo (CFN /
  parameter group), not this app repo. Flagged for that repo, consistent with
  the ownership boundary.
- Role creation on the shared live cluster is a privileged operation; the plan
  runs all destructive/DDL verification against a **disposable** database first
  and never against live `retrieval` without explicit go-ahead.

## Spec + gate impact

- **D24** edited in place: "single-role `SET LOCAL verity.role` GUC" → "three
  real login roles + `SET LOCAL ROLE`, transaction-scoped." Direction C intact;
  predicate still kept; mechanism strengthened.
- **G-27** (FORCE-RLS assertion) extended: assert on all three tables
  (`casework.evidence_items`, `retrieval.documents`, `retrieval.chunks`) and
  that `workshop_analyst` returns zero CASE-7421 rows at each raw table.
- **G-29 (new):** masking assertion — `workshop_auditor` sees the CASE-7421 row
  but `account_name` / `customer_commitment` return masked; `workshop_admin`
  sees them unmasked.
- All three `SPEC-session.md` copies re-synced byte-identical to a new draft.

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

1. Mask scope A vs B (feasibility spike, disposable DB) — decided at plan time.
2. Wire field name `principal` (3 values) vs rename to `role` — recommend keep.
3. Parameter-group change for `pgcolumnmask.policy_admin_rolname` — sibling repo.
4. Two-artifact packaging (frozen reference vs participant start) already
   flagged by the participant-exercises design; the H2 hole is unchanged by this
   design, so no new packaging burden beyond what that doc carries.
