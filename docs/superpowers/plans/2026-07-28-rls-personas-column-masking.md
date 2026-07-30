# RLS Personas + Column Masking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PostgreSQL Row-Level Security the enforced, demonstrable entitlement
mechanism for the DAT410 workshop — three real personas (`persona_analyst`,
`persona_admin`, `persona_auditor`) whose row visibility and column masking are
enforced by Aurora at the table, not by application code.

**Architecture:** A new idempotent `sql/11_roles_rls.sql` creates one clearance
group (`can_see_restricted`), three NOLOGIN persona roles, two LOGIN roles
(`workshop_app` for the pool, `workshop_participant` for terminals), then enables
**and forces** RLS on the three read-path tables (`casework.evidence_items`,
`retrieval.documents`, `retrieval.chunks`) with one identical predicate. A
separate `sql/12_masking.sql` adds `pg_columnmask` policies bound to
`persona_auditor`. The app pool connects as `workshop_app` (which holds no table
grants, so a forgotten role fails **closed** with `permission denied`) and issues
exactly one `SET LOCAL ROLE persona_<persona>` per request transaction. The
teaching predicate a participant hand-writes in the Lab-3 H2 hole is the
**byte-identical expression** the RLS policy uses.

**Tech Stack:** Aurora PostgreSQL 18.3, pgvector 0.8.1, `pg_trgm`,
`pg_columnmask` (Aurora-managed), psycopg 3 + `psycopg_pool`, FastAPI, React +
Vite (TypeScript), Python 3.12, `make`-driven SQL sequence.

## Global Constraints

Copy these verbatim into every subagent dispatch. Every task's requirements
implicitly include this section.

**Amendment vocabulary (A7 — supersedes the design doc's two-axis model):**
- ONE identity axis: the **persona**. Values: `analyst`, `admin`, `auditor`.
- Data classification axis: `acl_visibility ∈ {'workshop', 'restricted'}`.
- The `workbench.role` GUC is **DELETED**. It was never implemented in code; do
  not add it. Zero code consumers verified.
- The token `support-lead` is **retired everywhere** and joins `principal` on the
  G-11 banned list.
- The clearance group is named `can_see_restricted` (A8), never
  `workshop_restricted_reader`.
- The ONE predicate expression, used byte-identically by the RLS policy, the H2
  participant hole, and the guide:
  ```sql
  acl_visibility = 'workshop' OR pg_has_role(current_user, 'can_see_restricted', 'USAGE')
  ```
  `'USAGE'` not `'MEMBER'` **in the policy**: `MEMBER` ignores `INHERIT`, so it
  reports true for a persona the login can merely assume; `USAGE` asks about
  passive inheritance, which is the effective-role question RLS must key on and
  exactly the key `can_see_restricted` withholds. The two modes are not
  interchangeable and each layer needs a different one — G-30's ceremony probe
  correctly uses `MEMBER` (`gates/participant_ceremony.py`, group 1d) because
  "can this login `SET ROLE` to this persona?" *is* the membership question. Both
  measured on PostgreSQL 17; see the divergence entry under Codebase traps. A
  `MEMBER` in the policy or a `USAGE` in the ceremony probe is a defect.
- Grant direction is additive and deliberate: `can_see_restricted` is GRANTed to
  `persona_admin` and `persona_auditor`, **never** to `persona_analyst`.
  Additive grants fail closed; subtractive markers would fail open.

**Copy rules:**
- Chip copy is **"Viewing as"**, never "Sign in as". The chip is a mirror, never
  a power (A4).
- The word `principal` is banned from every participant-facing surface (D22,
  enforced by G-11). Code renames to `role` end-to-end.
- Guide sequencing: the app flip is first (the moment), the psql coda second
  (the proof).

**Identity / connection rules:**
- **The persona roles are `persona_analyst`, `persona_admin`, `persona_auditor` —
  NOT `workshop_*`.** This is not cosmetic. The sibling Workshop Studio repo
  provisions Aurora with the **master username `workshop_admin`**
  (`assets/hybrid-retrieval-database.yml:157`,
  `SecretStringTemplate: '{"username": "workshop_admin"}'`, consumed by
  `MasterUsername` at `:186`), and this repo's `.env.example:2` documents that DSN.
  A persona named `workshop_admin` would collide with the cluster master on every
  provisioned account, and `ALTER ROLE workshop_admin NOLOGIN` (Task 5) would
  **lock every participant out of their own database**. It would also make the
  "admin persona" an `rds_superuser` member, so it would see restricted rows by
  *RLS bypass* rather than by clearance — silently falsifying G-27(b) and the
  entire teaching claim. Never name a role `workshop_admin`. The `persona_` prefix
  also reads correctly in the psql coda: `SET LOCAL ROLE persona_admin`.
- Personas are **NOLOGIN** (A2). Nothing ever connects as a persona. The app
  reaches them via `SET ROLE` from `workshop_app`; participants via `SET ROLE`
  from `workshop_participant`. The two LOGIN roles keep the `workshop_` prefix:
  they are new names that collide with nothing.
- `retrieval_admin` **reads every row**, so its credential lives only in the
  bootstrap environment (schema build, seed, index build) and never in the app pool.
  Get the MECHANISM right, because two later tasks depend on which one it is:
  - It is **not** an inherited RLS bypass. Role attributes are not inherited through
    role membership. Measured read-only on the live cluster: `retrieval_admin` is
    `rolsuper=false, rolbypassrls=false`, and `rds_superuser` itself is
    `rolbypassrls=false`. There is nothing to inherit, and the owner **is** subject
    to `FORCE ROW LEVEL SECURITY` on Aurora exactly as on a local cluster. An early
    spike concluded otherwise; that spike's owner was a genuine local superuser, and
    the conclusion does not transfer. Any text in this plan claiming an
    `rds_superuser` member bypasses RLS is wrong — fix it, do not propagate it.
  - It reads every row **by clearance**: Task 5 grants the owner
    `can_see_restricted` and names `CURRENT_USER` in all three policies' `TO` lists,
    which is what keeps `make seed` and the index build from silently projecting a
    truncated corpus. Both halves are mandatory (Task 5 Step 1, Task 12 Step 3).
  - The consequence for the app pool is unchanged and is the reason this constraint
    exists: an identity that holds the clearance key sees restricted rows, so the
    request pool must be `workshop_app`, which does not hold it.
- `workshop_app`: LOGIN, owns nothing, **no direct table grants**, not in
  `rds_superuser`, no `BYPASSRLS`, GRANTed the three personas
  `WITH INHERIT FALSE`. With no role set, a `SELECT` raises `permission denied`.
- `workshop_participant`: LOGIN, GRANTed the three personas `WITH INHERIT FALSE`,
  explicit `EXECUTE` on `casework.admit_evidence` only, and **no** SELECT on
  casework/retrieval — bare `SELECT` on evidence must raise `permission denied`
  (A1: fail-closed is the free first lesson).
- All role switching uses `SET LOCAL ROLE` — transaction-scoped (the T8 pattern),
  so nothing leaks across pooled checkouts.

**Verify-SQL envelope (A3):** every `_verify_sql` for a role-sensitive panel emits
```sql
BEGIN; SET LOCAL ROLE persona_<persona>; <SELECT>; ROLLBACK;
```
`ROLLBACK` always — read-only, idempotent pastes. G-13 and G-29 must be able to
execute these under **any** connection identity.

**Gate contract:** `gates/_common.py` defines `PASS=0`, `FAIL=1`, `BLOCKED=2`.
BLOCKED means the subject under test does not exist yet — reported honestly,
never a pass. Gates never write to or run DDL against any database.

**Database safety (non-negotiable):**
- `.env` holds a **live Aurora credential**. Never commit, log, echo, or paste it.
- `backend/scripts/run_sql.py` and `get_conn` read `DATABASE_URL`, **not**
  `TEST_DATABASE_URL`. Always prefix `DATABASE_URL=…` inline for disposable work,
  and assert `current_database()` before any destructive statement.
- Roles are **cluster-global**, not database-scoped. Disposable verification uses
  prefixed role names and drops them in a `finally`.
- Never run schema/seed/reset against live `retrieval` without explicit go-ahead.

**Repo invariants:** `casework.*` is authoritative; `retrieval.*` is derived and
never hand-edited. Both `SPEC-session.md` copies stay byte-identical. Commits use
`shayons@amazon.com` only, with **no** Claude co-author trailer (public
aws-samples repo). Use `trash`, never `rm -rf`.

**Codebase traps:**
- `verity` is a substring of **`severity`**, a real incident column
  (`casework.incidents.severity`, `casework.support_cases.severity`,
  `retrieval.documents.severity`, `retrieval.chunks.severity`). Every rename must
  be word-boundary anchored (`\bverity`). A naive replace corrupts `severity` →
  `sWorkbenchy`.
- `retrieval.acl_visible` is currently `IMMUTABLE PARALLEL SAFE`
  (`sql/03_search_functions.sql:3-5`). `pg_has_role` is `STABLE`, so any
  predicate that calls it forces `acl_visible` to `STABLE`.
- **`casework.admit_evidence` is not `SECURITY DEFINER` today**
  (`sql/10_admission.sql:36-39`), so its body runs with the caller's privileges and
  its first statement reads `casework.ingest_receipts` (`:78`). `GRANT EXECUTE`
  alone therefore does **not** let `workshop_participant` run `./admit.sh` — it
  raises `permission denied for table ingest_receipts` while a
  `has_function_privilege` probe still reports true. Task 5 resolves this with
  `ALTER FUNCTION ... SECURITY DEFINER` plus a pinned `search_path`, which is what
  keeps the participant's reach at exactly one function and preserves the
  fail-closed `SELECT` lesson. Granting table DML instead would hand over the
  `SELECT` the lesson depends on.
- **A `SECURITY DEFINER` function must pin `search_path`.** The participant controls
  their own, and an unqualified name resolved through it is the classic
  privilege-escalation vector. G-30 asserts both `prosecdef` and a `search_path`
  entry in `proconfig`.
- **Definer rights end at the function boundary.** `admission/admit.sh:25-29` runs a
  bare `SELECT external_key FROM casework.evidence_items` *after* the
  `admit_evidence` call — outside the function, at the caller's privileges. It is
  the only participant-facing statement outside `sql/` that reads a read-path table
  (`grep -rln 'FROM casework\.\|FROM retrieval\.'` outside `sql/` returns that file
  alone). Task 5 Step 2 wraps it in the A3 envelope under `persona_analyst`. Do not
  "fix" this by granting the participant `SELECT`: that grant is exactly what the A1
  fail-closed lesson asserts is absent, and G-30's assertion group (2) would fail.
- **`SET ROLE` needs the grant even for the owner.** The bootstrap owner
  (`retrieval_admin` locally, `workshop_admin` on a provisioned cluster) is an
  `rds_superuser` member and can read everything, but `SET ROLE persona_analyst`
  still raises `permission denied to set role` without membership. PostgreSQL 16+
  auto-grants a `CREATEROLE` role admin membership on roles it creates, which masks
  this on the first run and exposes it on an idempotent re-run by a different owner.
  `sql/11` therefore GRANTs the three personas to `current_user WITH INHERIT FALSE`
  explicitly — otherwise `admit.sh` works for participants and fails for developers.
- **The two LOGIN roles' attributes are asserted, never `ALTER`ed.** Changing
  `SUPERUSER`/`BYPASSRLS` needs a true superuser; `retrieval_admin` is an
  `rds_superuser` **member**, not a superuser, so `ALTER ROLE … NOBYPASSRLS
  NOSUPERUSER` succeeds on a local cluster and raises on Aurora — a failure that
  surfaces only at deployment. `CREATE ROLE` already defaults them false.
- **`pg_has_role(current_user, '<name>', …)` raises `UndefinedObject` (42704) at
  PLAN time when the role does not exist.** Measured on PostgreSQL 17: the error
  is not a runtime NULL and not short-circuitable — no `AND`/`OR` ordering, `CASE`
  arm, or `EXISTS` guard suppresses it, because the name→OID lookup happens while
  the statement is being planned. Any probe for a role that may be absent must go
  through a `pg_roles` subselect that returns no row instead:
  ```sql
  SELECT coalesce(
    (SELECT pg_has_role(current_user, oid, 'USAGE') FROM pg_roles WHERE rolname = %s),
    false)
  ```
  This is load-bearing for `rds_superuser`, which exists **only** on Aurora/RDS: a
  literal-name probe turns every local gate run into a traceback instead of an
  honest PASS/FAIL/BLOCKED. It does not apply to the RLS policy expression itself —
  `can_see_restricted` is created by `sql/11` in the same file as the policy.
- **`USAGE` and `MEMBER` genuinely diverge, and each layer needs the other one.**
  Measured on PostgreSQL 17 under `GRANT persona_analyst TO login WITH INHERIT
  FALSE`: `pg_has_role(login, 'persona_analyst', 'USAGE')` is **false**,
  `'MEMBER'` is **true**, and `SET LOCAL ROLE persona_analyst` succeeds. So
  `MEMBER` is the correct mode for "can this login assume this persona?" (G-30's
  ceremony probe), and `USAGE` is the correct mode inside the policy, where the
  question is passive inheritance — exactly the key `can_see_restricted` withholds.
  Swapping them silently inverts both meanings without erroring.
- **`retrieval.chunks` has no `external_key` column** (`sql/01_schema.sql:951-999`).
  `evidence_id` is the only identity column present on all three read-path tables,
  so any probe that must span `casework.evidence_items`, `retrieval.documents`, and
  `retrieval.chunks` keys on `evidence_id` — with `DISTINCT`, because the derived
  tables hold one row per indexed version. A probe written against `external_key`
  raises `UndefinedColumn` at the chunks table rather than measuring anything, and
  a gate that aborts there asserts nothing about the table it was written to check.
- **There is no pytest in this repo.** `backend/requirements.txt` does not list
  it, `.venv/bin/` has no pytest binary, all ten existing test files subclass
  `unittest.TestCase`, and `make test` runs
  `python -m unittest discover -s backend/tests`. Every new test in this plan is a
  `unittest.TestCase`; a module-level `def test_*()` is **invisible** to unittest
  discovery, so a pytest-style file would silently never run — the worst failure
  mode possible for a security test. Do not add pytest as a dependency.
  Skips are per-class `@unittest.skipUnless(...)`; loop assertions use
  `with self.subTest(...)` so one failing case does not hide the rest.
- Run a single new file with the dotted module path, not the file path:
  `.venv/bin/python -m unittest backend.tests.test_db_persona -v`. There is no
  `backend/__init__.py` (only `backend/tests/__init__.py`), and the dotted form
  is what resolves; a bare path argument does not.
- Coding standards: ≤100 lines/function, complexity ≤8, ≤5 positional params,
  100-char lines, absolute imports only, Google-style docstrings on non-trivial
  public APIs, zero warnings.

---

## File Structure

Every row names its **owning task**. A deliverable with no owning task is a plan
defect; there are none.

**New files**

| Path | Owner | Responsibility |
|---|---|---|
| `gates/rls_enforcement.py` | Task 1 | G-27 a/b/c: fail-closed, row filtering, replay determinism. |
| `gates/masking_determinism.py` | Task 2 | G-29: masking + Law-2 determinism + A5 generated pattern set + corpus-wide leak scan. |
| `gates/participant_ceremony.py` | Task 3 | G-30: A1 zero-ceremony — participant identity runs every Lab-1 snippet, and bare SELECT on casework denies. |
| `gates/persona_equivalence.py` | Task 4 | G-31: A7 golden equivalence — analyst results byte-identical to the pre-collapse `role=workshop` baseline. |
| `sql/11_roles_rls.sql` | Task 5 | Roles, grants, RLS enable+force, the three row policies. Idempotent. |
| `sql/12_masking.sql` | Task 6 | `pg_columnmask` extension guard, masking functions, auditor masking policies. Idempotent. |
| `backend/tests/test_db_persona.py` | Task 7 | Persona checkout contract; extended by Task 10 with the view-hole assertions. |
| `frontend/src/persona.ts` | Task 11 | Pure persona enum + label/DB-role helpers consumed by `route.ts` and the app. |
| `backend/tests/test_rls_personas.py` | Task 16 | Live end-to-end row filtering, masking, and fail-closed coverage. |

**There is no `backend/app/personas.py`.** An earlier draft of this plan listed one
as "the single persona registry" while Task 7 put `PERSONAS` / `Persona` /
`persona_role()` in `backend/app/db.py` and Task 10 put a second `Persona` Literal in
`backend/app/models.py`. Three declaration sites for one three-value enum is the
dual-vocabulary problem A7 exists to kill. Resolution: **`db.py` is the registry**
(it owns `persona_role()` because the role name is a connection concern), `models.py`
re-declares only the `Literal` because it must not import the database layer
(`agent_tools` loads `models` in the MCP adapters, which have no pool), and Task 10
Step 12's `test_the_two_persona_literals_agree` binds the two together in CI. The
H2 predicate's SQL literal lives in `sql/11_roles_rls.sql` and the guide, not in
Python — nothing in Python needs to emit it.

**Modified files**

| Path | Owner | Change |
|---|---|---|
| `gates/checks.sh:33-41` | Tasks 1-4 | Register G-27, G-29, G-30, G-31 (one line per task). |
| `Makefile:17-28` | Tasks 5, 6 | `SQL_FILES` gains `sql/11_roles_rls.sql` and `sql/12_masking.sql`. |
| `backend/app/db.py:29-102` | Task 7 | `get_conn` / `get_dict_conn` require a persona; emit one `SET LOCAL ROLE`; new `get_owner_conn`. |
| `backend/app/config.py:49-70` | Task 7 | `workshop_app_database_url` setting. |
| `frontend/src/VerityApp.tsx` → `frontend/src/WorkbenchApp.tsx` | Task 8 rename; Task 11 content | Verity purge, then chip + receipt rendering + 20 identity sites. |
| `frontend/src/verity.css` → `frontend/src/workbench.css` | Task 8 rename; Task 11 content | 10 `verity-*` classes → `workbench-*`, then the chip's styles. |
| `frontend/src/main.tsx:3-8` | Task 8 | Import renames (`WorkbenchApp`, `workbench.css`). |
| `gates/noun_lint.py` | Task 8 | `support-lead` + `principal` banned-identity scan. |
| `admission/admit.sh:24-35` | Task 5 | Exact-arm checkpoint reads inside the A3 envelope as `persona_analyst`; REMEDY line names the RLS cause. |
| `admission/README.md:96-100,129-130` | Task 5 | The checkpoint's identity and why the `workshop` ACL default makes the analyst the right persona for it. |
| `sql/03_search_functions.sql:1-5` | Task 9 | `acl_visible` volatility `IMMUTABLE` → `STABLE`; `p_principal` dropped. |
| `sql/01_schema.sql`, `sql/04_diagnostics.sql`, `sql/05_evaluation.sql`, `sql/06_receipts.sql`, `sql/09_traverse_evidence.sql` | Tasks 9, 10 | `principal` → `role` column + `security_invoker` on the six content views. |
| `backend/app/models.py:21,49,77,87,92,116` | Task 10 | `principal` → `role`; `workshop_principal()` → `Persona` + `DEFAULT_ROLE`. |
| `backend/app/{search,agent,insights,evaluation,contracts,main,agent_tools,strands_agent}.py` | Task 10 | 37 persona-threaded checkouts + the `principal` → `role` wire rename. |
| `agent/registry.py`, `agent/generate_mcp_server.py` + both generated adapters | Task 10 | `_PRINCIPAL_PARAM` → `_ROLE_PARAM`; regenerate, never hand-edit. |
| `frontend/src/route.ts:21,27,45-48,67-72,98-100,125-127` | Task 11 | `PrincipalKey` → `PersonaKey`; `?principal=` → `?role=` with three values. |
| `gates/route_contract.py:79-80,90` | Task 11 | `?role=` contract routes; persona bundle literals. |
| `backend/app/verify_sql.py:129-160` | Task 12 | `_descriptor` gains the A3 identity envelope. |
| `gates/verify_sql_golden.py:110-122` | Task 12 | `_replay` splits the envelope instead of executing it as one statement. |
| `seed/corpus.py:12-16` + new block | Task 13 | `RESTRICTED_ACL` visibility flips to `'restricted'`, `principals` emptied; ~6 restricted objects across 3 systems. |
| `backend/scripts/doctor.py:206-221,306` | Tasks 10, 13 | ACL fixture check rewritten for `acl_visibility='restricted'`. |
| `backend/scripts/smoke_test.py:66,110-133` | Tasks 10, 13 | Persona-based ACL smoke by disagreement. |
| `backend/tests/test_retrieval_integration.py:301-315,391-452,544-552` | Tasks 10, 13 | Persona/RLS assertions replacing the `principals` array checks. |
| Sibling repo `content/` (Workshop Studio) | Task 14 | Guide snippets: the psql coda, the H2 hole, the M3 checkpoint copy. |
| `design/SPEC-session.md` + `design/verity-handoff/docs/SPEC-session.md` | Task 15 | A6 spec sync, byte-identical. |
| `docs/superpowers/specs/2026-07-28-rls-personas-column-masking-design.md` | Task 15 | A7/A8 reconciliation. |

**Gate numbering:** existing gates run G-1…G-29 (G-29 reserved by the design doc
for masking). This plan adds **G-30** (participant ceremony) and **G-31** (persona
equivalence). Verified: no G-30/G-31 exists anywhere in `design/SPEC-session.md`,
`gates/`, or the design doc.

**Task order** (the BUILD ORDER the amendments bind): 1-4 gates → 5 roles+RLS →
6 masking → 7 checkout → 8 Verity purge → 9 SQL collapse → 10 Python collapse →
11 frontend persona → 12 verify-SQL envelope → 13 seed expansion → 14 guide →
15 spec sync → 16 end-to-end tests. Gates come first so every later task has a
failing assertion to turn green; the purge sits at 8 because Tasks 10-12 edit the
file it renames.

---

## Task 1: G-27 RLS enforcement gate (fail-closed / row filtering / replay)

Ships **BLOCKED** — the roles do not exist yet. That is the point: the gate is
built before its subject, per SPEC-session Section 10.

**Files:**
- Create: `gates/rls_enforcement.py`
- Modify: `gates/checks.sh:33-41`

**Interfaces:**
- Consumes: `gates/_common.py` — `PASS`, `FAIL`, `BLOCKED`, `repo_root()`,
  `print_header()`, `finish()`, `read_env_value()`, `redact_dsn()`, `require()`,
  `main_guard()`.
- Produces: gate id `G-27`, script `gates/rls_enforcement.py`. Reads **two
  independent DSNs** and the three persona role names `persona_analyst` /
  `persona_admin` / `persona_auditor`.
  - `DATABASE_URL` — the bootstrap owner. Used only to *measure* (RLS state, the
    restricted cohort, the derived projection, the owner's own exposure).
  - `WORKSHOP_APP_DATABASE_URL` — the `workshop_app` pool login. Used for every
    *assertion* — groups (a), (b) and (c).

  **The app DSN must never fall back to `DATABASE_URL`.** Unlike
  `backend/app/db.py:_pool_conninfo` (Task 7), which falls back with a WARNING so a
  one-DSN developer can still boot, this gate treats a missing
  `WORKSHOP_APP_DATABASE_URL` as **BLOCKED**. A fallback here would run the
  fail-closed probe as the bootstrap owner — an `rds_superuser` member on Aurora
  that FORCE does not subject — so group (a) would report "no standing privilege
  path" about the one identity that has every privilege, and (b) would compare a
  bypassing role against itself. The gate would go green on a cluster with no
  enforcement whatsoever. Verified absent from the Step 1 code: `read_env_value`
  is called once per DSN with no `or` chain.

- [ ] **Step 1: Write the gate**

Create `gates/rls_enforcement.py`:

```python
#!/usr/bin/env python3
"""G-27 - RLS enforcement assertion (D24, A1/A2/A7/A8).

Three parts, in the order a reader should trust them, preceded by a precondition
that has to come first:

(0) the corpus can prove something. Restricted rows exist in
    ``casework.evidence_items`` AND survived into both derived tables, measured on
    the engine rather than hand-typed. This is not bookkeeping: (b) below asserts
    that ``persona_analyst`` sees zero restricted rows, which is trivially true of
    an empty set. The owner's own RLS exposure is measured alongside it, because
    the owner writes every derived projection and a filtered owner truncates them
    while reporting success. A gate that goes green over an empty enforcement claim
    is worse than one that goes red.

(a) fail-closed. Connected as ``workshop_app`` with **no role set**, a SELECT on
    each of the three read-path tables raises ``permission denied``. An error is
    strictly stronger than "returns zero rows": it proves the pool identity has no
    standing privilege path at all, so a forgotten ``SET ROLE`` cannot leak.

(b) row filtering. Under ``SET LOCAL ROLE persona_analyst`` every restricted row
    returns zero rows at each of ``casework.evidence_items``,
    ``retrieval.documents`` and ``retrieval.chunks`` - the raw tables, no arm, no
    application predicate. Under ``persona_admin`` the same rows are present.
    Both retrieval tables matter: ``vector_search`` reads ``retrieval.chunks``
    standalone and ``fuzzy_search`` reads ``retrieval.documents`` standalone, so a
    policy on ``casework.evidence_items`` alone would leak restricted body text
    while headers stayed filtered.

(c) replay determinism. The same query re-run in a second transaction under the
    same persona returns an identical row set, and the ``SET LOCAL ROLE`` does not
    survive the transaction (``current_user`` is back to the login role after
    ROLLBACK). Transaction-scoped, never session-scoped - the T8 pattern.

The gate is read-only: it issues SELECT, ``SET LOCAL ROLE`` and ROLLBACK only, and
never DDL (the ``_common.py`` contract). Roles absent, psycopg absent, or the
engine unreachable -> BLOCKED, never FAIL.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    BLOCKED,
    PASS,
    finish,
    main_guard,
    print_header,
    read_env_value,
    redact_dsn,
    require,
)

GATE_ID = "G-27"
TITLE = "RLS enforcement (D24)"

READ_PATH_TABLES = (
    "casework.evidence_items",
    "retrieval.documents",
    "retrieval.chunks",
)

# The evidence detail tables: keyed 1:1 on casework.evidence_items.evidence_id and
# reachable through section 2's schema-wide GRANT SELECT. RLS on the three
# read-path tables above does not cover them, and the sensitive text lives HERE,
# not in the header table -- an analyst denied at casework.evidence_items could
# read CASE-7421's account_name and customer_commitment straight out of
# casework.support_cases. Enumerated from sql/01_schema.sql (:65, :81, :96, :111,
# :163, :340, :352), not from the current restricted cohort: the bypass is the
# schema-wide grant, so any evidence_id-keyed table is a door.
DETAIL_TABLES = (
    "casework.incidents",
    "casework.changes",
    "casework.support_cases",
    "casework.runbooks",
    "casework.lock_evidence",
    "casework.customer_commitments",
    "casework.postmortems",
)

PERSONA_ROLES = ("persona_analyst", "persona_admin", "persona_auditor")
CLEARANCE_GROUP = "can_see_restricted"

# The canonical restricted noun (D22 / M3). Row filtering is asserted against
# every restricted row, but this one must always be among them.
CANONICAL_RESTRICTED_KEY = "CASE-7421"

# Restricted rows are measured, never hand-typed: the gate asks the engine which
# rows are restricted, as the owner, then asserts the persona views against that
# measured set.
#
# Both columns, because the two are needed for different jobs. ``evidence_id`` is
# the only identity column present on all three read-path tables --
# ``retrieval.chunks`` has NO ``external_key`` (sql/01_schema.sql:951-999; the key
# lives on ``retrieval.documents``:895 and ``casework.evidence_items``:34), so a
# probe written against ``external_key`` raises UndefinedColumn at the chunks table
# instead of measuring anything. ``external_key`` is what a human can act on, so it
# is what gets printed.
RESTRICTED_KEYS_SQL = """
SELECT external_key, evidence_id
  FROM casework.evidence_items
 WHERE coalesce(acl ->> 'visibility', 'restricted') = 'restricted'
   AND NOT is_deleted
 ORDER BY external_key
"""

# Probed by evidence_id for the reason above. DISTINCT because retrieval.documents
# and retrieval.chunks hold one row per version per evidence item, not one row per
# item (UNIQUE (evidence_id, search_index_version, search_document_hash) at :921).
VISIBLE_IDS_SQL = """
SELECT DISTINCT evidence_id
  FROM {table}
 WHERE evidence_id = ANY(%s)
"""

# The two derived tables the search arms actually read. Written by the owner, so
# they inherit whatever the owner could see at build time - which is the whole
# reason this gate measures the owner's own RLS exposure below.
DERIVED_TABLES = ("retrieval.documents", "retrieval.chunks")

PROJECTED_RESTRICTED_SQL = """
SELECT count(*) FROM {table} WHERE is_current AND acl_visibility = 'restricted'
"""

# Per-table restricted-row counts, measured AS THE OWNER. This is the independent
# oracle group (b') needs: persona_admin's own view cannot be used to decide
# whether a table "has no restricted rows of this kind", because that view is the
# fact under test. An empty admin result means either the kind genuinely has none
# or admin's visibility is broken, and those need opposite verdicts.
#
# Safe to run as the owner for the reason _diagnose_empty_restricted() documents:
# run() has already proven the owner is either a bypassing role or named by every
# policy AND holding the clearance group, so this count is unfiltered. If that were
# not true the gate would have failed before reaching group (b').
#
# Joined against the measured restricted evidence_ids rather than re-deriving
# "restricted" from the acl, so this count and group (b')'s probes are measuring
# the same row set by construction.
DETAIL_RESTRICTED_COUNT_SQL = """
SELECT count(*) FROM {table} WHERE evidence_id = ANY(%s)
"""

# The owner's own exposure to the policies it created. ``listed_on`` is the set of
# read-path tables whose policy names this role (directly or through PUBLIC);
# ``has_clearance`` is the second half. Neither is cosmetic: see
# _diagnose_empty_restricted.
OWNER_EXPOSURE_SQL = """
SELECT
    current_user::text AS owner,
    coalesce((SELECT rolsuper      FROM pg_roles WHERE rolname = current_user), false)
      AS is_super,
    coalesce((SELECT rolbypassrls  FROM pg_roles WHERE rolname = current_user), false)
      AS bypasses_rls,
    coalesce((
      SELECT array_agg(DISTINCT schemaname || '.' || tablename)
        FROM pg_policies
       WHERE schemaname || '.' || tablename = ANY(%s)
         AND (current_user = ANY(roles) OR 'public' = ANY(roles))
    ), '{}'::text[]) AS listed_on
"""

# Membership resolved through pg_roles by OID, never by naming the role inside
# pg_has_role() directly.
#
# ``pg_has_role(current_user, 'some_role', 'USAGE')`` raises UndefinedObject (42704)
# when the role does not exist, and it raises at PLAN time -- so no boolean
# short-circuit, CASE arm or EXISTS guard can save it; the whole statement dies
# before a row is produced. The subselect form yields NULL instead, which coalesce
# turns into false. This matters most for ``rds_superuser``, which exists ONLY on
# Aurora/RDS: measured on PG17, the bare call turned this gate's honest report into
# an unhandled traceback (`role "rds_superuser" does not exist`) on every local
# cluster and disposable test database.
MEMBER_OF_SQL = """
SELECT coalesce(
  (SELECT pg_has_role(current_user, oid, 'USAGE') FROM pg_roles WHERE rolname = %s),
  false
)
"""


def _roles_present(cur, names: tuple[str, ...]) -> list[str]:
    cur.execute(
        "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname",
        [list(names)],
    )
    return [row[0] for row in cur.fetchall()]


def _rls_state(cur) -> dict[str, tuple[bool, bool]]:
    """Return {qualified_table: (relrowsecurity, relforcerowsecurity)}."""
    cur.execute(
        """
        SELECT n.nspname || '.' || c.relname, c.relrowsecurity, c.relforcerowsecurity
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname || '.' || c.relname = ANY(%s)
        """,
        [list(READ_PATH_TABLES + DETAIL_TABLES)],
    )
    return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def _member_of(cur, role: str) -> bool:
    """Return whether ``current_user`` is a USAGE member of ``role``.

    False when ``role`` does not exist on this cluster. See MEMBER_OF_SQL.
    """
    cur.execute(MEMBER_OF_SQL, [role])
    return cur.fetchone()[0]


def _ids_under_persona(conn, persona: str, table: str, ids: list) -> set:
    """Return which of ``ids`` ``persona`` can see at ``table``. Read-only."""
    with conn.cursor() as cur:
        cur.execute("BEGIN")
        try:
            cur.execute(f"SET LOCAL ROLE {persona}")
            cur.execute(VISIBLE_IDS_SQL.format(table=table), [ids])
            return {row[0] for row in cur.fetchall()}
        finally:
            cur.execute("ROLLBACK")


def _denied_without_role(conn, table: str) -> str | None:
    """Return the SQLSTATE raised by a bare SELECT, or None if it succeeded."""
    import psycopg

    with conn.cursor() as cur:
        cur.execute("BEGIN")
        try:
            cur.execute(f"SELECT 1 FROM {table} LIMIT 1")
            return None
        except psycopg.errors.InsufficientPrivilege as exc:
            return exc.sqlstate
        finally:
            cur.execute("ROLLBACK")


def _owner_exposure(cur) -> dict:
    """Measure the owner's own exposure to the policies it created."""
    cur.execute(OWNER_EXPOSURE_SQL, [list(READ_PATH_TABLES)])
    owner, is_super, bypasses_rls, listed_on = cur.fetchone()
    return {
        "owner": owner,
        "is_super": is_super,
        "bypasses_rls": bypasses_rls,
        "has_clearance": _member_of(cur, CLEARANCE_GROUP),
        "listed_on": list(listed_on),
    }


def _diagnose_empty_restricted(exposure: dict) -> str:
    """Name the cause when the owner measures zero restricted rows.

    "No restricted rows" has two entirely different causes and reporting the
    wrong one sends the fix to the wrong file:

    * the seed genuinely has none -> fix ``seed/corpus.py``;
    * the owner is being filtered by the policies it created -> fix
      ``sql/11_roles_rls.sql``.

    The second is the dangerous one. Every derived projection is written by this
    identity, so a filtered owner silently truncates ``retrieval.documents`` and
    ``retrieval.chunks`` while reporting success (measured on PG17: 1 of 2 rows
    copied, exit 0). The row-filtering assertions below would then be true and
    meaningless. A superuser or ``BYPASSRLS`` owner cannot be in that state, which
    is what makes the first branch safe to attribute to the seed.
    """
    if exposure["is_super"] or exposure["bypasses_rls"]:
        return (
            f"the seed holds no restricted evidence. {exposure['owner']} bypasses "
            f"RLS (rolsuper={exposure['is_super']}, "
            f"rolbypassrls={exposure['bypasses_rls']}), so it read the table "
            f"unfiltered and the absence is real: reseed with seed/corpus.py's "
            f"RESTRICTED_ACL cohort"
        )
    unlisted = [t for t in READ_PATH_TABLES if t not in exposure["listed_on"]]
    if unlisted:
        return (
            f"{exposure['owner']} is not named by the policy on "
            f"{', '.join(unlisted)} and is subject to FORCE, so it sees ZERO rows "
            f"there -- this measurement is of a table the owner cannot read, not of "
            f"the seed. Add CURRENT_USER to those policies' TO lists "
            f"(sql/11_roles_rls.sql; Task 12 Step 3)"
        )
    if not exposure["has_clearance"]:
        return (
            f"{exposure['owner']} is named by every policy but does NOT hold "
            f"{CLEARANCE_GROUP}, so it reads workshop rows only. The restricted "
            f"cohort exists and is invisible to the identity that writes every "
            f"derived projection. Restore the "
            f"GRANT {CLEARANCE_GROUP} TO current_user block in sql/11_roles_rls.sql"
        )
    return (
        f"{exposure['owner']} is named by every policy and holds "
        f"{CLEARANCE_GROUP}, so it is reading unfiltered: the seed holds no "
        f"restricted evidence. Reseed with seed/corpus.py's RESTRICTED_ACL cohort"
    )


def run() -> int:  # noqa: C901 - four independent assertion groups, read top to bottom
    print_header(GATE_ID, TITLE)

    owner_dsn = read_env_value("DATABASE_URL")
    app_dsn = read_env_value("WORKSHOP_APP_DATABASE_URL")
    if not owner_dsn:
        return finish(
            GATE_ID,
            BLOCKED,
            "DATABASE_URL is not set (env or .env); cannot reach the engine",
        )

    try:
        import psycopg
    except ImportError:
        return finish(
            GATE_ID, BLOCKED, "psycopg is not importable in this interpreter"
        )

    print(f"  engine: {redact_dsn(owner_dsn)}")

    try:
        with psycopg.connect(owner_dsn, connect_timeout=15, autocommit=True) as conn:
            with conn.cursor() as cur:
                present = _roles_present(cur, PERSONA_ROLES + (CLEARANCE_GROUP,))
                missing = sorted(
                    set(PERSONA_ROLES + (CLEARANCE_GROUP,)) - set(present)
                )
                if missing:
                    return finish(
                        GATE_ID,
                        BLOCKED,
                        f"roles not created yet: {', '.join(missing)}",
                    )
                state = _rls_state(cur)
                exposure = _owner_exposure(cur)
                cur.execute(RESTRICTED_KEYS_SQL)
                rows = cur.fetchall()
                restricted = [row[0] for row in rows]
                restricted_ids = [row[1] for row in rows]
                projected = {}
                for table in DERIVED_TABLES:
                    cur.execute(PROJECTED_RESTRICTED_SQL.format(table=table))
                    projected[table] = cur.fetchone()[0]
                # Measured here, in the owner connection, for the same reason
                # `projected` is: group (b') runs on the app connection under
                # SET LOCAL ROLE, where every count is by definition filtered.
                detail_restricted = {}
                for table in DETAIL_TABLES:
                    cur.execute(
                        DETAIL_RESTRICTED_COUNT_SQL.format(table=table),
                        [restricted_ids],
                    )
                    detail_restricted[table] = cur.fetchone()[0]
    except psycopg.OperationalError as exc:
        return finish(GATE_ID, BLOCKED, f"cannot reach the engine: {exc}")

    print("\n  RLS state (relrowsecurity / relforcerowsecurity):")
    for table in READ_PATH_TABLES:
        enabled, forced = state.get(table, (None, None))
        print(f"    {table}: enabled={enabled} forced={forced}")
    # Both tuples: a detail table without ENABLE+FORCE is the bypass this gate's
    # (b') group exists to catch, and reporting it as BLOCKED here names the
    # missing DDL instead of failing later with a confusing row count.
    unprotected = [
        table
        for table in READ_PATH_TABLES + DETAIL_TABLES
        if state.get(table) != (True, True)
    ]
    if unprotected:
        return finish(
            GATE_ID,
            BLOCKED,
            f"RLS not enabled+forced yet on: {', '.join(unprotected)}",
        )

    # Everything below was measured as the owner, so print what the owner could
    # actually see while measuring it. Without this line a zero count reads as "the
    # seed has no restricted evidence" when the truth may be "the writer is blind".
    print(
        f"\n  measuring as: {exposure['owner']} "
        f"(rolsuper={exposure['is_super']} rolbypassrls={exposure['bypasses_rls']} "
        f"{CLEARANCE_GROUP}={exposure['has_clearance']} "
        f"named by {len(exposure['listed_on'])}/{len(READ_PATH_TABLES)} policies)"
    )

    print(f"\n  restricted rows measured on the engine: {len(restricted)}")
    for key in restricted:
        print(f"    {key}")
    # Not "no restricted rows found" -- that names a symptom and sends the fix to
    # the wrong file half the time. _diagnose_empty_restricted names the cause.
    require(restricted, _diagnose_empty_restricted(exposure))
    require(
        CANONICAL_RESTRICTED_KEY in restricted,
        f"{CANONICAL_RESTRICTED_KEY} is not restricted; M3's flip noun is broken",
    )

    # The projection must carry the restricted rows too, and this is NOT redundant
    # with (b). A non-superuser owner that is subject to FORCE but holds no clearance
    # reads a silently truncated source: the search-index build then projects only
    # workshop rows, and (b) below reports "analyst sees 0 restricted rows" -- a PASS
    # for the wrong reason, because there is nothing there to filter. Measured on
    # PG17: that configuration copied 1 of 2 rows and reported success. Assert the
    # restricted cohort SURVIVED into both derived tables before proving it is hidden.
    #
    # Counted with count(*) over is_current, not over external_key: retrieval.chunks
    # has no external_key column (sql/01_schema.sql:951-999) -- the key lives on
    # retrieval.documents (:895) and on casework.evidence_items (:34).
    print("\n  current restricted rows in the derived projection:")
    for table in DERIVED_TABLES:
        print(f"    {table}: {projected[table]}")
        require(
            projected[table] > 0,
            f"{table} holds no current restricted rows while "
            f"casework.evidence_items holds {len(restricted)}. The projection is "
            f"written by {exposure['owner']}, so either the search index has not "
            f"been rebuilt since the reseed, or that identity could not see the "
            f"restricted rows when it built it (named by "
            f"{len(exposure['listed_on'])}/{len(READ_PATH_TABLES)} policies, "
            f"{CLEARANCE_GROUP}={exposure['has_clearance']}) and truncated them "
            f"silently. Either way the row-filtering assertions below would hold "
            f"over an empty set",
        )

    # --- (a) fail-closed: the app login has no standing privilege path. ---
    if not app_dsn:
        print(
            "\n  (a) fail-closed: SKIPPED - WORKSHOP_APP_DATABASE_URL not set;"
            " cannot connect as the pool identity"
        )
        return finish(
            GATE_ID,
            BLOCKED,
            "WORKSHOP_APP_DATABASE_URL is not set; (a) fail-closed unprovable",
        )

    print("\n  (a) fail-closed - bare SELECT as the pool login:")
    with psycopg.connect(app_dsn, connect_timeout=15, autocommit=True) as app_conn:
        with app_conn.cursor() as cur:
            cur.execute("SELECT current_user")
            login = cur.fetchone()[0]
            # Resolved through pg_roles: rds_superuser exists only on Aurora/RDS and
            # naming it inside pg_has_role() aborts the statement elsewhere. See
            # MEMBER_OF_SQL.
            is_master = _member_of(cur, "rds_superuser")
        print(f"    connected as: {login} (rds_superuser member: {is_master})")
        require(
            not is_master,
            f"{login} is an rds_superuser member; a cluster-master identity can "
            f"grant itself the clearance key at will, so the pool must not be one",
        )
        with app_conn.cursor() as cur:
            cur.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
            require(
                cur.fetchone()[0] is False,
                f"{login} has BYPASSRLS; the pool identity must not",
            )
        for table in READ_PATH_TABLES:
            sqlstate = _denied_without_role(app_conn, table)
            print(f"    {table}: sqlstate={sqlstate or 'NONE (query succeeded)'}")
            require(
                sqlstate == "42501",
                f"bare SELECT on {table} as {login} did not raise permission denied "
                f"(got {sqlstate or 'success'}); the pool fails OPEN",
            )

        # --- (b) row filtering at the raw tables. ---
        # Probed by evidence_id, the only identity column on all three tables.
        print("\n  (b) row filtering at the raw tables:")
        for table in READ_PATH_TABLES:
            analyst = _ids_under_persona(
                app_conn, "persona_analyst", table, restricted_ids
            )
            admin = _ids_under_persona(
                app_conn, "persona_admin", table, restricted_ids
            )
            auditor = _ids_under_persona(
                app_conn, "persona_auditor", table, restricted_ids
            )
            print(
                f"    {table}: analyst={len(analyst)} admin={len(admin)} "
                f"auditor={len(auditor)} (of {len(restricted_ids)} restricted)"
            )
            require(
                analyst == set(),
                f"persona_analyst saw restricted rows at {table}: "
                f"{sorted(str(i) for i in analyst)}",
            )
            require(
                admin,
                f"persona_admin saw no restricted rows at {table}; the clearance "
                f"grant is missing",
            )
            require(
                auditor,
                f"persona_auditor saw no restricted rows at {table}; masking needs "
                f"the row present",
            )

        # --- (b') row filtering at the evidence detail tables. ---
        # The policies here clear through the parent, so this group measures a
        # DIFFERENT mechanism than (b): (b) proves the parent's predicate works,
        # this proves the children inherit it. A table holding no restricted
        # evidence is skipped rather than asserted on -- runbooks, lock_evidence,
        # customer_commitments and postmortems hold none in the current cohort, and
        # asserting "admin sees restricted rows" there would fail for a reason that
        # has nothing to do with RLS. The skip is driven by the OWNER's count, never
        # by persona_admin's: admin's own empty view cannot tell "this kind has no
        # restricted rows" apart from "admin's visibility is broken", and those two
        # need opposite verdicts. The analyst assertion runs on every table
        # regardless, because "the analyst sees nothing" holds either way.
        print("\n  (b') row filtering at the evidence detail tables:")
        for table in DETAIL_TABLES:
            analyst = _ids_under_persona(
                app_conn, "persona_analyst", table, restricted_ids
            )
            admin = _ids_under_persona(
                app_conn, "persona_admin", table, restricted_ids
            )
            auditor = _ids_under_persona(
                app_conn, "persona_auditor", table, restricted_ids
            )
            print(
                f"    {table}: analyst={len(analyst)} admin={len(admin)} "
                f"auditor={len(auditor)}"
            )
            require(
                analyst == set(),
                f"persona_analyst read restricted rows out of {table}: "
                f"{sorted(str(i) for i in analyst)}. RLS on the three read-path "
                f"tables does not cover the detail tables, and section 2 of "
                f"sql/11_roles_rls.sql grants every persona SELECT ON ALL TABLES "
                f"IN SCHEMA casework -- so the analyst is denied at "
                f"casework.evidence_items and then reads the same evidence body "
                f"here. Add the EXISTS-on-parent policy for this table "
                f"(sql/11_roles_rls.sql section 5)",
            )
            # The OWNER's count decides whether to skip, not persona_admin's. An
            # empty admin view is the failure this group exists to catch when the
            # rows are actually there, and a legitimate skip when they are not --
            # persona_admin cannot distinguish those two states about itself.
            if detail_restricted[table] == 0:
                print("      (no restricted evidence of this kind; analyst-only check)")
                continue
            require(
                admin,
                f"persona_admin saw none of the {detail_restricted[table]} restricted "
                f"rows the owner measured at {table}. Either persona_admin is missing "
                f"from that table's policy TO list or the EXISTS predicate is wrong "
                f"(sql/11_roles_rls.sql section 5). Without this assertion the gate "
                f"would have skipped the auditor check and reported PASS over a "
                f"policy that denies every persona",
            )
            require(
                auditor,
                f"persona_auditor saw no restricted rows at {table} while "
                f"persona_admin saw {len(admin)}; masking needs the row present",
            )

        # --- (c) replay determinism + transaction scope. ---
        print("\n  (c) replay determinism and transaction scope:")
        first = _ids_under_persona(
            app_conn, "persona_admin", READ_PATH_TABLES[0], restricted_ids
        )
        second = _ids_under_persona(
            app_conn, "persona_admin", READ_PATH_TABLES[0], restricted_ids
        )
        print(f"    replay 1: {len(first)} rows / replay 2: {len(second)} rows")
        require(
            first == second,
            f"replay under the same persona diverged: {first} vs {second}",
        )
        with app_conn.cursor() as cur:
            cur.execute("SELECT current_user")
            after = cur.fetchone()[0]
        print(f"    current_user after ROLLBACK: {after}")
        require(
            after == login,
            f"SET LOCAL ROLE leaked past the transaction: current_user={after}",
        )

    return finish(
        GATE_ID,
        PASS,
        f"fail-closed on {len(READ_PATH_TABLES)} tables; {len(restricted)} restricted "
        f"rows hidden from analyst, visible to admin+auditor; replay deterministic",
    )


if __name__ == "__main__":
    main_guard(run)
```

- [ ] **Step 2: Register it and run it — expect BLOCKED**

Edit `gates/checks.sh`, replacing the `GATES=(...)` array (lines 33-41) with:

```bash
GATES=(
  "G-11|noun_lint.py|Law 1 noun lint"
  "G-13|verify_sql_golden.py|Verify-SQL golden test"
  "G-14|empty_db_ui_test.py|Empty-database UI test"
  "G-17|registry_drift.py|Registry drift"
  "G-21|fixture_arithmetic.py|Fixture arithmetic (D14) on the engine"
  "G-23|route_contract.py|Route contract (D16)"
  "G-25|admission_determinism.py|Admission determinism (D21)"
  "G-27|rls_enforcement.py|RLS enforcement (D24)"
)
```

Run: `gates/checks.sh G-27`

Expected: the gate prints its banner, the engine DSN redacted, then
`[BLOCKED] G-27: roles not created yet: can_see_restricted, persona_admin,
persona_analyst, persona_auditor` and the orchestrator summary reports
`BLOCKED(1): G-27` with `RESULT: no failures; 1 gate(s) blocked on unbuilt deps`
and exit 0.

- [ ] **Step 3: Commit**

```bash
git add gates/rls_enforcement.py gates/checks.sh
git commit -m "Add G-27 RLS enforcement gate (ships BLOCKED)"
```

---

## Task 2: G-29 masking + Law-2 determinism gate (with A5 leak scan)

Ships **BLOCKED**. Detects masking **behaviourally** (admin raw vs auditor masked)
rather than by reading a `pg_columnmask` catalog table, so the gate does not depend
on an internal catalog name and proves the thing that actually matters.

**Plan decision recorded here (deviates from the design doc's "all masking
functions are `IMMUTABLE`"):** A5 requires the blob pattern set to be *generated*
from the seed's restricted values, and a function that reads a table cannot
honestly be `IMMUTABLE`. Resolution: `retrieval.mask_blob(text)` stays `IMMUTABLE`
with the literals **baked into its body**, and `retrieval.refresh_mask_blob()`
(Task 5) regenerates that body from the live restricted rows via
`format()` + `EXECUTE`. Generated, not hand-written; still `IMMUTABLE`; still
byte-stable. The pre-refresh placeholder masks the **whole** blob, so a skipped
refresh over-masks (fails closed) instead of leaking.

**Files:**
- Create: `gates/masking_determinism.py`
- Modify: `gates/checks.sh` (registry array)

**Interfaces:**
- Consumes: `gates/_common.py` helpers; the persona role names from Task 1;
  `WORKSHOP_APP_DATABASE_URL`.
- Produces: gate id `G-29`, script `gates/masking_determinism.py`.

- [ ] **Step 1: Write the gate**

Create `gates/masking_determinism.py`:

```python
#!/usr/bin/env python3
"""G-29 - Column masking and Law-2 determinism (A3/A5, design 2026-07-28).

Four assertions:

1. Masking is real. Under ``persona_auditor`` the sensitive columns on a
   restricted support case (``account_name``, ``customer_commitment``,
   ``description``) and the denormalized ``retrieval.chunks.chunk_text`` blob come
   back masked; under ``persona_admin`` the same columns come back raw. Masking is
   detected by comparing the two views, not by reading a ``pg_columnmask`` catalog
   table - behaviour is what the workshop claims, so behaviour is what is asserted.

2. Law 2 determinism. The same SELECT, issued twice in separate transactions under
   the same persona, returns byte-identical values. This is what lets a panel and
   the pasted ``_verify_sql`` agree: both run the identical masked expression.

3. A5 pattern provenance. The sensitive literals are **read from the engine** (the
   restricted rows' own typed values), never hand-written in this gate. If the seed
   changes, the gate's expectations change with it.

4. A5 corpus-wide leak scan. Every restricted sensitive literal is searched for
   across the entire auditor-visible corpus - all of ``retrieval.chunks.chunk_text``
   and the typed case columns - and must return zero hits. A mask that covers the
   canonical row but misses a paraphrase elsewhere in the corpus is a leak, and only
   a corpus-wide scan catches it.

Read-only: SELECT, ``SET LOCAL ROLE``, ROLLBACK. Roles or masking absent -> BLOCKED.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    BLOCKED,
    PASS,
    finish,
    main_guard,
    print_header,
    read_env_value,
    redact_dsn,
    require,
)

GATE_ID = "G-29"
TITLE = "Column masking + Law-2 determinism"

AUDITOR = "persona_auditor"
ADMIN = "persona_admin"
COLUMNS = ("account_name", "customer_commitment", "description")

# The typed sensitive columns, read from the engine to build the pattern set (A5).
SENSITIVE_SQL = """
SELECT e.external_key, c.account_name, c.customer_commitment, c.description
  FROM casework.support_cases c
  JOIN casework.evidence_items e USING (evidence_id)
 WHERE coalesce(e.acl ->> 'visibility', 'restricted') = 'restricted'
   AND NOT e.is_deleted
 ORDER BY e.external_key
"""

CASE_VIEW_SQL = """
SELECT e.external_key, c.account_name, c.customer_commitment, c.description
  FROM casework.support_cases c
  JOIN casework.evidence_items e USING (evidence_id)
 WHERE e.external_key = ANY(%s)
 ORDER BY e.external_key
"""

# retrieval.chunks has NO external_key (see Codebase traps). Reach the label
# through the document_version_id foreign key -- documents' primary key, so the
# join cannot fan out -- and filter on the chunk's own is_current flag.
CHUNK_VIEW_SQL = """
SELECT d.external_key, c.chunk_ordinal, c.chunk_text
  FROM retrieval.chunks c
  JOIN retrieval.documents d ON d.document_version_id = c.document_version_id
 WHERE d.external_key = ANY(%s)
   AND c.is_current
 ORDER BY d.external_key, c.chunk_ordinal
"""

LEAK_SCAN_SQL = """
SELECT count(*)
  FROM retrieval.chunks
 WHERE is_current
   AND chunk_text ILIKE '%%' || %s || '%%'
"""


def _as_persona(conn, persona: str, sql: str, params: list) -> list[tuple]:
    """Run one read-only SELECT under ``persona`` and roll the transaction back."""
    with conn.cursor() as cur:
        cur.execute("BEGIN")
        try:
            cur.execute(f"SET LOCAL ROLE {persona}")
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.execute("ROLLBACK")


def _owner_chunks(owner_dsn: str, psycopg, keys: list[str]) -> list[tuple]:
    """Return the stored chunk blobs for ``keys``, read as the bootstrap owner.

    The owner is an ``rds_superuser`` member, so this is the ground truth the
    persona views are judged against. Read-only.
    """
    with psycopg.connect(owner_dsn, connect_timeout=15, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(CHUNK_VIEW_SQL, [keys])
            return cur.fetchall()


def _literals(rows: list[tuple]) -> list[str]:
    """Return the distinct non-empty sensitive literals from measured rows."""
    out: set[str] = set()
    for _key, account, commitment, description in rows:
        for value in (account, commitment, description):
            if value and len(value.strip()) >= 6:
                out.add(value.strip())
    return sorted(out)


def run() -> int:  # noqa: C901 - four assertion groups, read top to bottom
    print_header(GATE_ID, TITLE)

    owner_dsn = read_env_value("DATABASE_URL")
    app_dsn = read_env_value("WORKSHOP_APP_DATABASE_URL")
    if not owner_dsn:
        return finish(GATE_ID, BLOCKED, "DATABASE_URL is not set (env or .env)")
    if not app_dsn:
        return finish(
            GATE_ID, BLOCKED, "WORKSHOP_APP_DATABASE_URL is not set; cannot SET ROLE"
        )

    try:
        import psycopg
    except ImportError:
        return finish(GATE_ID, BLOCKED, "psycopg is not importable")

    print(f"  engine: {redact_dsn(owner_dsn)}")

    try:
        with psycopg.connect(owner_dsn, connect_timeout=15, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT extversion FROM pg_extension WHERE extname = 'pg_columnmask'"
                )
                ext = cur.fetchone()
                if ext is None:
                    return finish(
                        GATE_ID, BLOCKED, "pg_columnmask is not installed yet"
                    )
                print(f"  pg_columnmask: {ext[0]}")
                cur.execute(
                    "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
                    [[AUDITOR, ADMIN]],
                )
                found = {row[0] for row in cur.fetchall()}
                if {AUDITOR, ADMIN} - found:
                    return finish(
                        GATE_ID,
                        BLOCKED,
                        f"persona roles missing: {sorted({AUDITOR, ADMIN} - found)}",
                    )
                cur.execute(SENSITIVE_SQL)
                sensitive = cur.fetchall()
    except psycopg.OperationalError as exc:
        return finish(GATE_ID, BLOCKED, f"cannot reach the engine: {exc}")

    if not sensitive:
        return finish(
            GATE_ID, BLOCKED, "no restricted support cases seeded; nothing to mask"
        )

    keys = [row[0] for row in sensitive]
    literals = _literals(sensitive)
    print("\n  (3) A5 pattern provenance - read from the engine, not hand-written:")
    print(f"    restricted cases: {', '.join(keys)}")
    print(f"    sensitive literals: {len(literals)}")
    for value in literals:
        print(f"      {value!r}")
    require(literals, "restricted cases carry no maskable sensitive values")

    with psycopg.connect(app_dsn, connect_timeout=15, autocommit=True) as app:
        # A missing SELECT grant is an unbuilt dependency, not a masking failure.
        # main_guard only translates AssertionError, so an escaping
        # InsufficientPrivilege would be a traceback where the contract demands an
        # honest BLOCKED. sql/11 grants SELECT ON ALL TABLES IN SCHEMA casework to
        # each persona; this catch names the table when that has not run yet.
        try:
            admin_cases = _as_persona(app, ADMIN, CASE_VIEW_SQL, [keys])
            auditor_cases = _as_persona(app, AUDITOR, CASE_VIEW_SQL, [keys])
            admin_chunks = _as_persona(app, ADMIN, CHUNK_VIEW_SQL, [keys])
            auditor_chunks = _as_persona(app, AUDITOR, CHUNK_VIEW_SQL, [keys])
        except psycopg.errors.InsufficientPrivilege as exc:
            return finish(
                GATE_ID, BLOCKED, f"a persona lacks SELECT on the read path: {exc}"
            )

        print("\n  (1) masking is real - admin raw vs auditor masked:")
        require(
            len(auditor_cases) == len(admin_cases) and auditor_cases,
            f"auditor row count {len(auditor_cases)} != admin {len(admin_cases)}; "
            f"masking needs the row PRESENT, not filtered",
        )
        # Ground truth read as the bootstrap owner, keyed by external_key. "Masked
        # for the auditor" is only meaningful against the real stored value: two
        # differently-masked views also differ from each other, so comparing the
        # admin view to the auditor view alone cannot tell "admin is raw" from
        # "admin is masked differently". Anchor on truth, not on the other view.
        truth = {row[0]: row[1:] for row in sensitive}
        for admin_row, auditor_row in zip(admin_cases, auditor_cases):
            key = admin_row[0]
            for column, raw, masked, stored in zip(
                COLUMNS, admin_row[1:], auditor_row[1:], truth[key]
            ):
                if stored is None:
                    continue
                print(f"    {key}.{column}: admin={raw!r} auditor={masked!r}")
                require(
                    raw == stored,
                    f"{key}.{column} is masked for persona_admin too "
                    f"(admin={raw!r} != stored {stored!r}); the mask is not "
                    f"auditor-scoped and 'admin raw vs auditor masked' proves nothing",
                )
                require(
                    masked != stored,
                    f"{key}.{column} is NOT masked for the auditor "
                    f"(identical to the stored value)",
                )
        require(
            admin_chunks and len(auditor_chunks) == len(admin_chunks),
            "chunk_text row counts differ between admin and auditor",
        )
        # Same anchor for the blob: the admin view must equal what is stored.
        owner_blobs = _owner_chunks(owner_dsn, psycopg, keys)
        require(
            owner_blobs and len(admin_chunks) == len(owner_blobs),
            f"admin sees {len(admin_chunks)} restricted chunks, the owner sees "
            f"{len(owner_blobs)}; compare like with like before judging the mask",
        )
        require(
            [row[2] for row in admin_chunks] == [row[2] for row in owner_blobs],
            "chunk_text is masked for persona_admin too; a blob that differs "
            "between admin and auditor then proves nothing about the auditor",
        )
        blob_masked = sum(
            1 for a, b in zip(admin_chunks, auditor_chunks) if a[2] != b[2]
        )
        print(
            f"    chunk_text: {blob_masked} of {len(admin_chunks)} restricted chunks "
            f"differ under the auditor"
        )
        require(
            blob_masked > 0,
            "no restricted chunk_text differs under the auditor; the blob is unmasked",
        )

        print("\n  (2) Law 2 determinism - same persona, two transactions:")
        replay_cases = _as_persona(app, AUDITOR, CASE_VIEW_SQL, [keys])
        replay_chunks = _as_persona(app, AUDITOR, CHUNK_VIEW_SQL, [keys])
        print(f"    typed columns identical: {replay_cases == auditor_cases}")
        print(f"    chunk blobs identical:   {replay_chunks == auditor_chunks}")
        require(
            replay_cases == auditor_cases,
            "auditor typed columns are not byte-stable across transactions; the panel "
            "and the pasted verify-SQL would disagree (Law 2 violation)",
        )
        require(
            replay_chunks == auditor_chunks,
            "auditor chunk_text is not byte-stable across transactions (Law 2)",
        )

        print("\n  (4) A5 corpus-wide leak scan as the auditor:")
        leaks: list[tuple[str, int]] = []
        for value in literals:
            hits = _as_persona(app, AUDITOR, LEAK_SCAN_SQL, [value])[0][0]
            print(f"    {value!r}: {hits} chunk hit(s)")
            if hits:
                leaks.append((value, hits))
        require(
            not leaks,
            "restricted literals still visible to the auditor somewhere in the corpus: "
            + "; ".join(f"{v!r} x{n}" for v, n in leaks),
        )

    return finish(
        GATE_ID,
        PASS,
        f"{len(literals)} restricted literals masked for the auditor, byte-stable "
        f"across transactions, zero corpus-wide leaks",
    )


if __name__ == "__main__":
    main_guard(run)
```

- [ ] **Step 2: Register and run — expect BLOCKED**

Add to the `GATES=(...)` array in `gates/checks.sh`, after the `G-27` line:

```bash
  "G-29|masking_determinism.py|Column masking + Law-2 determinism"
```

Run: `gates/checks.sh G-29`

Expected: `[BLOCKED] G-29: pg_columnmask is not installed yet` (or
`persona roles missing: [...]` if the extension is already present on the target
cluster). Exit 0 from the orchestrator with `BLOCKED(1): G-29`.

- [ ] **Step 3: Commit**

```bash
git add gates/masking_determinism.py gates/checks.sh
git commit -m "Add G-29 masking + Law-2 determinism gate (ships BLOCKED)"
```

---

## Task 3: G-30 participant zero-ceremony gate (A1)

A1's assertion in gate form: every Lab-1 snippet must run under
`workshop_participant` with **zero ceremony** (no `SET ROLE`, no extra grants
step), and a bare `SELECT` on casework/retrieval from that same identity must
raise `permission denied` — the free first lesson.

**Files:**
- Create: `gates/participant_ceremony.py`
- Modify: `gates/checks.sh` (registry array)

**Interfaces:**
- Consumes: `gates/_common.py` helpers; `WORKSHOP_PARTICIPANT_DATABASE_URL`.
- Produces: gate id `G-30`, script `gates/participant_ceremony.py`.

- [ ] **Step 1: Write the gate**

Create `gates/participant_ceremony.py`:

```python
#!/usr/bin/env python3
"""G-30 - Participant zero-ceremony identity (A1, 2026-07-28).

The Lab-1 terminal identity is ``workshop_participant``. Two claims:

1. Zero ceremony. Every statement a Lab-1 snippet issues runs as-is under this
   identity: the monitoring views (``pg_stat_activity``, ``pg_locks``,
   ``pg_stat_progress_create_index``) are readable, the exercise schema is readable,
   and ``casework.admit_evidence`` is EXECUTE-able. No ``SET ROLE`` first, no grant
   step, no sudo. If a participant has to type anything the guide does not show, the
   guide is wrong.

2. Fail-closed first lesson. A bare ``SELECT`` on ``casework.evidence_items`` /
   ``retrieval.documents`` / ``retrieval.chunks`` from the same identity raises
   ``permission denied`` (SQLSTATE 42501). Evidence reads require assuming a persona;
   the denial is the lesson, not a bug.

Monitoring-view caveat asserted explicitly: without ``pg_monitor`` membership,
``pg_stat_activity`` silently shows only the participant's OWN backend rows. The
gate asserts membership rather than merely that the view is selectable, because
"selectable but empty" is the failure mode that survives a naive check.

Read-only: SELECT and catalog reads only. ``casework.admit_evidence`` is probed for
EXECUTE privilege via ``has_function_privilege``, never actually invoked - the gate
contract forbids writes.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    BLOCKED,
    PASS,
    finish,
    main_guard,
    print_header,
    read_env_value,
    redact_dsn,
    require,
)

GATE_ID = "G-30"
TITLE = "Participant zero-ceremony identity (A1)"

PARTICIPANT_ROLE = "workshop_participant"
PERSONA_ROLES = ("persona_analyst", "persona_admin", "persona_auditor")

# Monitoring reads every Lab-1 watch.sql snippet performs.
MONITORING_VIEWS = (
    "pg_stat_activity",
    "pg_locks",
    "pg_stat_progress_create_index",
)

DENIED_TABLES = (
    "casework.evidence_items",
    "retrieval.documents",
    "retrieval.chunks",
)

ADMIT_FUNCTION = "casework.admit_evidence(jsonb)"


def _probe_select(conn, statement: str) -> str | None:
    """Return the SQLSTATE raised by ``statement``, or None when it succeeded."""
    import psycopg

    with conn.cursor() as cur:
        cur.execute("BEGIN")
        try:
            cur.execute(statement)
            cur.fetchall()
            return None
        except psycopg.errors.InsufficientPrivilege as exc:
            return exc.sqlstate
        finally:
            cur.execute("ROLLBACK")


def run() -> int:  # noqa: C901 - four assertion groups, read top to bottom
    print_header(GATE_ID, TITLE)

    dsn = read_env_value("WORKSHOP_PARTICIPANT_DATABASE_URL")
    if not dsn:
        return finish(
            GATE_ID,
            BLOCKED,
            "WORKSHOP_PARTICIPANT_DATABASE_URL is not set; the participant identity "
            "is provisioned by the sibling Workshop Studio repo",
        )

    try:
        import psycopg
    except ImportError:
        return finish(GATE_ID, BLOCKED, "psycopg is not importable")

    print(f"  engine: {redact_dsn(dsn)}")

    try:
        with psycopg.connect(dsn, connect_timeout=15, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_user")
                login = cur.fetchone()[0]
            print(f"    connected as: {login}")
            if login != PARTICIPANT_ROLE:
                return finish(
                    GATE_ID,
                    BLOCKED,
                    f"connected as {login}, expected {PARTICIPANT_ROLE}",
                )

            print("\n  (1a) monitoring visibility - pg_monitor membership:")
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_has_role(current_user, 'pg_monitor', 'USAGE')"
                )
                is_monitor = cur.fetchone()[0]
            print(f"    pg_monitor member: {is_monitor}")
            require(
                is_monitor,
                f"{login} is not a pg_monitor member; pg_stat_activity will show only "
                f"its own backend and every Lab-1 watch snippet reads as empty",
            )

            print("\n  (1b) zero-ceremony monitoring reads:")
            for view in MONITORING_VIEWS:
                sqlstate = _probe_select(conn, f"SELECT * FROM {view} LIMIT 1")
                print(f"    {view}: {sqlstate or 'readable'}")
                require(
                    sqlstate is None,
                    f"{login} cannot read {view} (sqlstate {sqlstate}); the Lab-1 "
                    f"snippet needs a grant the guide does not show",
                )

            # The catalog read comes FIRST, and its absence is BLOCKED rather than
            # FAIL. has_function_privilege() resolves its text argument to an OID
            # while the statement is planned, so it raises UndefinedFunction (42883)
            # on a cluster where sql/10 has not run -- a traceback, not a verdict,
            # exactly like the pg_has_role trap under (1d). Catalog read only; the
            # gate never invokes the writer.
            print("\n  (1c) admission function shape (catalog read):")
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner)
                      FROM pg_proc p
                      JOIN pg_namespace n ON n.oid = p.pronamespace
                     WHERE n.nspname = 'casework'
                       AND p.proname = 'admit_evidence'
                       AND pg_get_function_identity_arguments(p.oid) = 'payload jsonb'
                    """
                )
                row = cur.fetchone()
            if row is None:
                return finish(
                    GATE_ID, BLOCKED, f"{ADMIT_FUNCTION} does not exist yet"
                )
            secdef, proconfig, owner = row
            print(f"    prosecdef={secdef} owner={owner} proconfig={proconfig}")
            require(
                secdef,
                f"{ADMIT_FUNCTION} is not SECURITY DEFINER; its body runs as the "
                f"caller, so ./admit.sh raises permission denied on "
                f"casework.ingest_receipts for {login}",
            )
            has_search_path = any(
                entry.startswith("search_path=") for entry in (proconfig or [])
            )
            require(
                has_search_path,
                f"{ADMIT_FUNCTION} is SECURITY DEFINER with no pinned search_path; a "
                f"participant-controlled search_path is a privilege-escalation vector",
            )

            # EXECUTE is necessary and NOT sufficient, which is why it is checked
            # after the shape above and not instead of it: admit_evidence would run
            # with the CALLER's privileges without prosecdef, and its body reads and
            # writes five tables the participant holds no grant on, so ./admit.sh
            # would die on "permission denied for table ingest_receipts" while this
            # probe still reports true. Safe to run only now that the function is
            # known to exist -- the text argument resolves to an OID at plan time.
            print("\n  (1c') admission EXECUTE privilege (probed, never invoked):")
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT has_function_privilege(current_user, %s, 'EXECUTE')",
                    [ADMIT_FUNCTION],
                )
                can_admit = cur.fetchone()[0]
            print(f"    {ADMIT_FUNCTION}: EXECUTE={can_admit}")
            require(
                can_admit,
                f"{login} cannot EXECUTE {ADMIT_FUNCTION}; ./admit.sh would fail",
            )

            # 'MEMBER', not 'USAGE' -- the one place in this plan where MEMBER is the
            # right mode. The question here is "can this login SET ROLE to the
            # persona?", and the grants are WITH INHERIT FALSE. Measured on PG17
            # against exactly that grant: USAGE reports false, MEMBER reports true,
            # and SET LOCAL ROLE succeeds. USAGE would fail this assertion on a
            # correctly-provisioned cluster. The policy expression still uses USAGE,
            # because it asks the opposite question -- whether privileges are
            # inherited passively -- and that is what withholding the key means.
            print("\n  (1d) persona roles grantable (SET ROLE available):")
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
                    [list(PERSONA_ROLES)],
                )
                existing = {row[0] for row in cur.fetchall()}
            absent = [p for p in PERSONA_ROLES if p not in existing]
            if absent:
                # Not a FAIL, and not probed either: pg_has_role() raises
                # UndefinedObject on a missing role, which would turn this gate's
                # report into a traceback. BLOCKED is the honest answer for a subject
                # that has not been built.
                return finish(
                    GATE_ID,
                    BLOCKED,
                    f"persona roles not created yet: {', '.join(absent)}",
                )
            for persona in PERSONA_ROLES:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_has_role(current_user, %s, 'MEMBER')", [persona])
                    member = cur.fetchone()[0]
                print(f"    {persona}: grantable={member}")
                require(
                    member,
                    f"{login} is not granted {persona}; the psql persona coda cannot run",
                )

            print("\n  (2) fail-closed first lesson - bare SELECT on evidence:")
            for table in DENIED_TABLES:
                sqlstate = _probe_select(conn, f"SELECT 1 FROM {table} LIMIT 1")
                print(f"    {table}: sqlstate={sqlstate or 'NONE (query succeeded)'}")
                require(
                    sqlstate == "42501",
                    f"bare SELECT on {table} as {login} did not raise permission "
                    f"denied (got {sqlstate or 'success'}); the first lesson is gone",
                )
    except psycopg.OperationalError as exc:
        return finish(GATE_ID, BLOCKED, f"cannot reach the engine: {exc}")

    return finish(
        GATE_ID,
        PASS,
        f"{PARTICIPANT_ROLE} reads {len(MONITORING_VIEWS)} monitoring views with zero "
        f"ceremony, can EXECUTE admission, and is denied on all "
        f"{len(DENIED_TABLES)} evidence tables",
    )


if __name__ == "__main__":
    main_guard(run)
```

- [ ] **Step 2: Register and run — expect BLOCKED**

Add to the `GATES=(...)` array in `gates/checks.sh`, after the `G-29` line:

```bash
  "G-30|participant_ceremony.py|Participant zero-ceremony identity (A1)"
```

Run: `gates/checks.sh G-30`

Expected: `[BLOCKED] G-30: WORKSHOP_PARTICIPANT_DATABASE_URL is not set; the
participant identity is provisioned by the sibling Workshop Studio repo`.

- [ ] **Step 3: Commit**

```bash
git add gates/participant_ceremony.py gates/checks.sh
git commit -m "Add G-30 participant zero-ceremony gate (ships BLOCKED)"
```

---

## Task 4: G-31 persona equivalence gate (A7 safety assertion)

A7's binding STOP condition: the vocabulary collapse must not alter semantics. The
analyst persona must reproduce, byte-identically, what the pre-collapse
`role=workshop` identity produced. This gate compares against a **committed
baseline file** captured before any semantic change lands, so it can still fail
after the old code path is deleted.

**Files:**
- Create: `gates/persona_equivalence.py`
- Create: `gates/baselines/analyst_equivalence.json` (captured in Step 2)
- Modify: `gates/checks.sh` (registry array)

**Interfaces:**
- Consumes: `gates/_common.py` helpers; `DATABASE_URL` for the baseline capture;
  `WORKSHOP_APP_DATABASE_URL` for the analyst comparison.
- Produces: gate id `G-31`; the baseline JSON contract
  `{"captured_under": str, "eval_goldens": [...], "claim_coverage": [...]}`.

- [ ] **Step 1: Write the gate**

Create `gates/persona_equivalence.py`:

```python
#!/usr/bin/env python3
"""G-31 - Persona equivalence after the A7 vocabulary collapse.

A7 retired the two-axis identity model: ``support-lead`` is gone, the
``workbench.role`` GUC is deleted, and one persona now drives everything. That
collapse is only safe if it changed **vocabulary**, not **semantics**. The
observable contract is: whatever the old ``role=workshop`` identity could retrieve
and cite, the new ``persona_analyst`` persona retrieves and cites - byte-identically.

The gate compares live analyst results against ``gates/baselines/analyst_equivalence.json``,
a baseline captured on the pre-collapse corpus and committed to the repo. A
committed baseline (rather than a live A/B against the old code) is what lets this
assertion survive the deletion of the old path: after ``support-lead`` no longer
exists anywhere, the file is the only remaining witness to what it used to return.

Two comparisons:

1. Eval goldens - the judged relevance set the Lab-2 checkpoints score against.
   Any drift here moves a golden, which moves a checkpoint number in the guide.
2. Claim coverage - how many current chunks the identity can reach per document.
   Not the citation list: ``proof.answer_citations`` holds that and needs a
   persisted run, which a read-only gate must not create. Drift here means the
   evidence available to support a claim changed, which is what moves the room's
   headline answer.

A mismatch is a FAIL, not a warning: A7 says "any diff means the collapse altered
semantics: STOP and report."

**The two sides are asymmetric on purpose, and that asymmetry is the assertion.**
The baseline side replays the OLD rule explicitly, because the old rule is what is
being deleted: ``retrieval.acl_visible(acl, '{"scopes":["workshop"],"principals":[]}')``
(sql/03_search_functions.sql:1-29) resolved to *visibility is in my scopes AND the
row names no principal I lack*. The live side applies NO visibility predicate at
all - it issues a bare SELECT under the persona and lets RLS do the filtering.

That is the only shape in which this gate asserts anything. An earlier draft
filtered BOTH sides on ``acl_visibility = 'workshop'``; that version is vacuous -
drop every RLS policy and it still PASSes, because the explicit WHERE performs the
filtering the policies were supposed to prove. The live side must be a bare SELECT
so that a missing, mis-scoped, or non-FORCEd policy shows up as a row-count diff.

The corollary is that the pre-collapse rule must be replayed EXACTLY, including the
principals leg. ``CASE-7421`` today carries ``{"visibility": "workshop",
"principals": ["support-lead"]}`` (seed/corpus.py:13-16), so the pre-collapse
identity - empty ``principals`` - could NOT read it. Capturing on visibility alone
would record it as visible, and after Task 13 reclassifies it to
``visibility='restricted'`` the analyst correctly cannot see it, so the gate would
FAIL and report "the collapse altered semantics" for a row whose semantics the
collapse faithfully PRESERVED (denied before, denied after).

Background filler is excluded from claim coverage. ``_background_rows`` generates
``background_documents`` synthetic rows (default 15,000 - seed/corpus.py:1148,
200 under the local Makefile target), every one of them ``WORKSHOP_ACL`` and
one-chunk, so including them buries the ~17 canonical rows this assertion cares
about under 15k rows of the constant 1, ties the committed baseline to a seeding
knob, and inflates the file to ~900 kB. ``*-BG-*`` is the documented filler marker
(gates/noun_lint.py:19,122).

Read-only. Baseline absent, persona not created yet, or engine unreachable ->
BLOCKED.

Usage:
    gates/persona_equivalence.py             # compare live analyst vs baseline
    gates/persona_equivalence.py --capture   # write the baseline (pre-collapse only)
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    BLOCKED,
    FAIL,
    PASS,
    finish,
    main_guard,
    print_header,
    read_env_value,
    redact_dsn,
    repo_root,
)

GATE_ID = "G-31"
TITLE = "Persona equivalence after the A7 collapse"

BASELINE_PATH = Path("gates/baselines/analyst_equivalence.json")
ANALYST = "persona_analyst"

# The judged relevance set: (query_id, evidence_kind, external_key, relevance)
# tuples the Lab-2 checkpoints score against. The grade column is named `relevance`
# (sql/01_schema.sql:1512) -- there is no `grade` column, and naming one would
# raise UndefinedColumn 42703 at PLAN time, which main_guard turns into a
# traceback rather than a verdict.
#
# `evidence_kind` is in the key because external_key alone is NOT unique:
# casework.evidence_items is UNIQUE (evidence_kind, external_key) (:44). Keying on
# external_key alone would silently collapse two graded rows that share a key
# across kinds, and _diff_summary's dict build would keep only the last one.
#
# {vis} is substituted with a per-side visibility predicate: the OLD rule for the
# baseline, TRUE for the live side (RLS filters it). Never with anything derived
# from input -- these are two module constants, not a query builder.
EVAL_GOLDENS_SQL = """
SELECT j.query_id, e.evidence_kind, e.external_key, j.relevance
  FROM proof.relevance_judgments j
  JOIN casework.evidence_items e USING (evidence_id)
 WHERE NOT e.is_deleted
   AND {vis}
 ORDER BY j.query_id, e.evidence_kind, e.external_key
"""

# Claim coverage: current reachable chunks per current non-filler document.
# retrieval.chunks has no external_key (it is on documents), and
# documents.document_version_id is that table's PRIMARY KEY which chunks carries as
# a NOT NULL FK, so this join is many-to-one and cannot fan the count out.
CLAIM_COVERAGE_SQL = """
SELECT d.evidence_kind, d.external_key, count(*) AS reachable_chunks
  FROM retrieval.documents d
  JOIN retrieval.chunks c ON c.document_version_id = d.document_version_id
 WHERE d.is_current
   AND c.is_current
   AND d.external_key NOT LIKE '%-BG-%'
   AND {vis}
 GROUP BY d.evidence_kind, d.external_key
 ORDER BY d.evidence_kind, d.external_key
"""

# The pre-collapse rule, replayed verbatim so the baseline records what the OLD
# identity could actually read. retrieval.acl_visible(acl, principal) is still the
# two-jsonb signature at capture time (sql/03_search_functions.sql:1; Task 9 is what
# drops it for the (jsonb, name) form), and the workshop principal is the literal
# the API sent (backend/app/models.py:22). Calling the live function rather than
# restating its logic means the baseline cannot drift from the rule it claims to
# record. Both `acl` columns are jsonb, on evidence_items (:29) and documents (:900).
OLD_RULE_EVIDENCE = (
    """retrieval.acl_visible(e.acl, '{"scopes":["workshop"],"principals":[]}'::jsonb)"""
)
OLD_RULE_DOCUMENT = (
    """retrieval.acl_visible(d.acl, '{"scopes":["workshop"],"principals":[]}'::jsonb)"""
)

# The live side asserts nothing itself -- RLS is the subject under test. A
# visibility predicate here would make this gate vacuous: it would PASS with every
# policy dropped.
RLS_FILTERS = "true"


def _fetch(conn, sql: str, persona: str | None) -> list[list]:
    """Run ``sql`` (optionally under ``persona``) and return JSON-comparable rows."""
    with conn.cursor() as cur:
        cur.execute("BEGIN")
        try:
            if persona:
                cur.execute(f"SET LOCAL ROLE {persona}")
            cur.execute(sql)
            return [list(row) for row in cur.fetchall()]
        finally:
            cur.execute("ROLLBACK")


def _diff_summary(label: str, expected: list[list], actual: list[list]) -> list[str]:
    """Return human-readable diff lines for two ordered row lists."""
    lines: list[str] = []
    exp = {tuple(row[:-1]): row[-1] for row in expected}
    act = {tuple(row[:-1]): row[-1] for row in actual}
    for key in sorted(set(exp) - set(act)):
        lines.append(f"    {label}: MISSING {key} (baseline value {exp[key]})")
    for key in sorted(set(act) - set(exp)):
        lines.append(f"    {label}: UNEXPECTED {key} (live value {act[key]})")
    for key in sorted(set(exp) & set(act)):
        if exp[key] != act[key]:
            lines.append(
                f"    {label}: CHANGED {key} baseline={exp[key]} live={act[key]}"
            )
    return lines


def _capture(owner_dsn: str, path: Path) -> tuple[int, str]:
    """Write the pre-collapse baseline. Refuses to overwrite an existing one.

    Overwriting is the one irreversible thing this gate could do. Once the
    collapse lands, a re-capture would record post-collapse semantics under a
    pre-collapse label, and the gate would compare the new world against itself
    and PASS - destroying the only witness A7 has. Delete the file deliberately
    if you really mean to re-baseline.

    Returns ``(code, summary)`` rather than a bare code because this function has
    three distinct refusal paths - the file already exists, the pre-collapse rule
    is gone, the engine is unreachable - and the caller cannot tell them apart
    from an exit code. A caller that guesses gets it wrong: an earlier draft
    reported "already exists; delete it to re-baseline" for every non-PASS,
    including the Task-9 refusal, which sends the reader to delete the one
    artifact the refusal exists to protect.
    """
    import psycopg

    if path.exists():
        print(f"  refusing to overwrite the existing baseline at {path}")
        return FAIL, f"{BASELINE_PATH} already exists; delete it to re-baseline"

    # Unreachable engine -> BLOCKED, not a traceback. main_guard translates only
    # AssertionError, so an unguarded connect() reports this gate as a raw
    # OperationalError stack with a bare exit 1 that the wrapper then prints as a
    # FAIL. Measured: pointing --capture at a dead port produced exactly that.
    # The comparison path below already guards its own connect; this one is the
    # same hazard on the other side of the branch.
    try:
        conn_ctx = psycopg.connect(owner_dsn, connect_timeout=15, autocommit=True)
    except psycopg.OperationalError as exc:
        return BLOCKED, f"cannot reach the engine: {exc}"

    with conn_ctx as conn:
        # The two-jsonb acl_visible must still exist, or this capture is recording
        # the wrong world. After Task 9 it is DROPped in favour of (jsonb, name),
        # and the call below would raise UndefinedFunction 42883 at plan time --
        # main_guard translates only AssertionError, so that is a traceback rather
        # than a verdict. Refuse instead: a baseline captured post-Task-9 is
        # worthless, because the rule it claims to witness is already gone.
        #
        # to_regprocedure, NOT pg_get_function_identity_arguments. Measured on
        # PG17: identity_arguments returns 'p_acl jsonb, p_principal jsonb' --
        # it includes PARAMETER NAMES, so comparing it to 'jsonb, jsonb' can never
        # match and this guard would refuse every capture on a healthy cluster.
        # (That is exactly why G-30's probe compares against 'payload jsonb' and
        # not 'jsonb'.) to_regprocedure resolves by type signature, ignores
        # parameter names, discriminates (jsonb,jsonb) from Task 9's (jsonb,name),
        # and returns NULL instead of raising when the function or schema is
        # absent -- so it cannot become the 42883 traceback it exists to prevent.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT to_regprocedure('retrieval.acl_visible(jsonb, jsonb)')"
            )
            if cur.fetchone()[0] is None:
                print(
                    "  retrieval.acl_visible(jsonb, jsonb) is gone; the pre-collapse "
                    "rule can no longer be replayed, so this baseline would be a "
                    "forgery. Capture must happen before Task 9."
                )
                return FAIL, (
                    "retrieval.acl_visible(jsonb, jsonb) is gone; the pre-collapse "
                    "rule cannot be replayed, so no honest baseline is possible"
                )
        payload = {
            "captured_under": (
                "pre-A7 role=workshop semantics, replayed via "
                "retrieval.acl_visible(acl, {\"scopes\":[\"workshop\"],\"principals\":[]})"
            ),
            "eval_goldens": _fetch(
                conn, EVAL_GOLDENS_SQL.format(vis=OLD_RULE_EVIDENCE), None
            ),
            "claim_coverage": _fetch(
                conn, CLAIM_COVERAGE_SQL.format(vis=OLD_RULE_DOCUMENT), None
            ),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"  captured baseline: {len(payload['eval_goldens'])} goldens, "
        f"{len(payload['claim_coverage'])} covered documents -> {path}"
    )
    return PASS, f"baseline written to {BASELINE_PATH}"


def run() -> int:  # noqa: C901 - two modes plus their guards, read top to bottom
    print_header(GATE_ID, TITLE)
    root = repo_root()
    baseline_path = root / BASELINE_PATH

    owner_dsn = read_env_value("DATABASE_URL")
    if not owner_dsn:
        return finish(GATE_ID, BLOCKED, "DATABASE_URL is not set (env or .env)")

    try:
        import psycopg
    except ImportError:
        return finish(GATE_ID, BLOCKED, "psycopg is not importable")

    if "--capture" in sys.argv:
        print(f"  engine: {redact_dsn(owner_dsn)}")
        code, summary = _capture(owner_dsn, baseline_path)
        return finish(GATE_ID, code, summary)

    if not baseline_path.exists():
        return finish(
            GATE_ID,
            BLOCKED,
            f"{BASELINE_PATH} not captured yet; run with --capture before the collapse",
        )

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    app_dsn = read_env_value("WORKSHOP_APP_DATABASE_URL")
    if not app_dsn:
        return finish(
            GATE_ID, BLOCKED, "WORKSHOP_APP_DATABASE_URL is not set; cannot SET ROLE"
        )

    print(f"  engine: {redact_dsn(app_dsn)}")
    print(f"  baseline captured under: {baseline['captured_under']}")

    try:
        with psycopg.connect(app_dsn, connect_timeout=15, autocommit=True) as conn:
            # Existence check BEFORE the SET LOCAL ROLE. Task 5 creates the
            # persona; until then SET ROLE raises UndefinedObject (42704), and
            # main_guard translates only AssertionError -- so an unguarded
            # SET ROLE reports this gate as a traceback instead of the honest
            # BLOCKED that an unbuilt dependency deserves.
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [ANALYST])
                if cur.fetchone() is None:
                    return finish(
                        GATE_ID, BLOCKED, f"{ANALYST} does not exist yet"
                    )
            # A persona the app login is not granted raises InsufficientPrivilege
            # (42501) on SET ROLE, and a missing SELECT grant raises it on the
            # read. Both are unbuilt Task 5 grants, not semantic drift: FAILing
            # here would claim the A7 collapse changed semantics when the truth
            # is that nothing is wired up yet.
            try:
                live_goldens = _fetch(
                    conn, EVAL_GOLDENS_SQL.format(vis=RLS_FILTERS), ANALYST
                )
                live_coverage = _fetch(
                    conn, CLAIM_COVERAGE_SQL.format(vis=RLS_FILTERS), ANALYST
                )
            except psycopg.errors.InsufficientPrivilege as exc:
                return finish(
                    GATE_ID,
                    BLOCKED,
                    f"{ANALYST} cannot be assumed or cannot read the corpus: {exc}",
                )
    except psycopg.OperationalError as exc:
        return finish(GATE_ID, BLOCKED, f"cannot reach the engine: {exc}")

    print(
        f"\n  eval goldens:   baseline={len(baseline['eval_goldens'])} "
        f"live={len(live_goldens)}"
    )
    print(
        f"  claim coverage: baseline={len(baseline['claim_coverage'])} "
        f"live={len(live_coverage)}"
    )

    diffs = _diff_summary("goldens", baseline["eval_goldens"], live_goldens)
    diffs += _diff_summary("coverage", baseline["claim_coverage"], live_coverage)

    if diffs:
        print("\n  DIFFS (A7 STOP condition):")
        for line in diffs:
            print(line)
        return finish(
            GATE_ID,
            FAIL,
            f"{len(diffs)} semantic difference(s) between the baseline and the analyst "
            f"persona; the A7 collapse altered semantics - STOP and report",
        )

    return finish(
        GATE_ID,
        PASS,
        f"analyst persona reproduces the baseline byte-identically "
        f"({len(live_goldens)} goldens, {len(live_coverage)} covered documents)",
    )


if __name__ == "__main__":
    main_guard(run)
```

- [ ] **Step 2: Capture the pre-collapse baseline against the LIVE corpus**

This must happen **now**, and the deadline is set by **two** later tasks:

- **Task 9** DROPs `retrieval.acl_visible(jsonb, jsonb)`. The capture calls that
  function to replay the pre-collapse rule, so once Task 9 lands the rule cannot be
  replayed at all. `_capture` checks the catalog for the two-jsonb signature and
  FAILs rather than record a baseline it cannot honestly label.
- **Task 13** reclassifies the restricted cohort. A baseline captured after it
  would record post-flip semantics under a pre-flip label.

(Task 8 is the `verity` identifier rename and touches no data, so it is not a
deadline.)

The capture is **read-only**: two SELECTs as the owner, no DDL, no writes. It is
the one step in Tasks 1-4 that connects to the live cluster, and it must stay
read-only.

The row counts are small on purpose - claim coverage excludes `*-BG-*` background
filler, so the file records the canonical corpus rather than 15k synthetic rows of
the constant 1. If `M` comes back in the thousands, the exclusion is not working
and the baseline is pinned to whatever `--background-documents` this cluster was
seeded with.

Run:
```bash
gates/persona_equivalence.py --capture
```

Expected: `captured baseline: <N> goldens, <M> covered documents ->
/…/gates/baselines/analyst_equivalence.json` then
`[PASS] G-31: baseline written to gates/baselines/analyst_equivalence.json`.

Re-running `--capture` with the file already present is a **FAIL**, on purpose:
overwriting the baseline destroys the only witness to pre-collapse semantics.

Do **not** hand-type N or M anywhere. Read them out of the written file:
```bash
python3 -c "import json;d=json.load(open('gates/baselines/analyst_equivalence.json'));print(len(d['eval_goldens']),len(d['claim_coverage']))"
```

- [ ] **Step 3: Register and run the comparison — expect BLOCKED**

Add to the `GATES=(...)` array in `gates/checks.sh`, after the `G-30` line:

```bash
  "G-31|persona_equivalence.py|Persona equivalence after the A7 collapse"
```

Run: `gates/checks.sh G-31`

Expected: `[BLOCKED] G-31: WORKSHOP_APP_DATABASE_URL is not set; cannot SET ROLE`.

- [ ] **Step 4: Run the whole harness and record the tri-state**

Run: `gates/checks.sh`

Expected summary: the seven pre-existing gates keep their current verdicts, and
`BLOCKED` now includes `G-27 G-29 G-30 G-31`. `RESULT: no failures; N gate(s)
blocked on unbuilt deps`, exit 0. Paste the summary block into the task report.

- [ ] **Step 5: Commit**

```bash
git add gates/persona_equivalence.py gates/baselines/analyst_equivalence.json gates/checks.sh
git commit -m "Add G-31 persona equivalence gate + pre-collapse baseline"
```

---

## Task 5: Roles, grants, and RLS policies (`sql/11_roles_rls.sql`)

The substrate. One idempotent file, added to `make schema`, verified end-to-end on
a **disposable** database with prefixed roles before it ever runs against live.

**Files:**
- Create: `sql/11_roles_rls.sql`
- Modify: `sql/03_search_functions.sql:1-5` (volatility)
- Modify: `admission/admit.sh:24-35` (exact-arm checkpoint runs under a persona)
- Modify: `admission/README.md:96-100,129-130` (the checkpoint's identity)
- Modify: `Makefile:17-28` (`SQL_FILES`)
- Modify: `.env.example` (two new DSN keys)

**Interfaces:**
- Consumes: `casework.evidence_items` (`acl jsonb`, `sql/01_schema.sql:40`),
  `retrieval.documents.acl_visibility` (`:901`), `retrieval.chunks.acl_visibility`
  (`:968`), `casework.admit_evidence(jsonb)` (`sql/10_admission.sql:36`).
- Produces: roles `can_see_restricted`, `persona_analyst`, `persona_admin`,
  `persona_auditor`, `workshop_app`, `workshop_participant`; policies
  `rls_evidence_items_visibility`, `rls_documents_visibility`,
  `rls_chunks_visibility`; `casework.admit_evidence(jsonb)` becomes
  `SECURITY DEFINER` with `search_path` pinned to
  `pg_catalog, casework, retrieval`; env keys `WORKSHOP_APP_DATABASE_URL`,
  `WORKSHOP_PARTICIPANT_DATABASE_URL`. The three personas are also GRANTed to
  `current_user` (the bootstrap owner) `WITH INHERIT FALSE`, so `admit.sh` runs
  identically for a participant and for a developer.

**The second half of `admit.sh` is a privilege problem too, and the fix is not
another grant.** Step 1's definer rights cover the function *call*
(`admit.sh:14-17`). They do nothing for the **exact-arm checkpoint** at `:25-29`,
which is a bare `SELECT external_key FROM casework.evidence_items` issued by the
same `psql` process — outside the function, at the caller's privileges, on a table
`workshop_participant` deliberately holds no grant on. Lab 1's finale would print
the ingest receipt and then die on `permission denied for table evidence_items`
one line later. Granting the participant `SELECT` would destroy the A1 lesson that
the whole identity model is built on, so Step 2 wraps the checkpoint in the A3
envelope (`BEGIN; SET LOCAL ROLE persona_analyst; SELECT …; ROLLBACK;`) instead.
That is strictly better than a grant: the participant's own admission comes back
visible **through a persona under live RLS**, which is the same enforcement path
Lab 3 later takes apart — and because `promote_pg_incident.py:41` defaults `acl` to
`{"visibility": "workshop"}`, the analyst is the correct persona for it.

**Predicate asymmetry (deliberate, not an oversight):** `casework.evidence_items`
has no `acl_visibility` column — its classification lives in `acl->>'visibility'`
(`sql/01_schema.sql:40`). Only the two derived `retrieval.*` tables carry the
denormalized scalar (`:901`, `:968`). So the policy on casework reads
`coalesce(acl ->> 'visibility', 'restricted')` while the retrieval policies read
`acl_visibility` directly. Both resolve to the same value for the same row (the
backfill at `:942-949` and `search_index.py:521-525` guarantee it), and both
default to `'restricted'` when absent — fail closed. The **teaching** expression
handed to participants is the `retrieval.*` form, because that is the table the
Lab-3 H2 hole queries.

- [ ] **Step 1: Write the SQL file**

Create `sql/11_roles_rls.sql`:

```sql
-- sql/11_roles_rls.sql - workshop identities and RLS enforcement (D24, A1/A2/A7/A8).
--
-- Runs after every table it references exists. Idempotent: safe to re-run on a
-- cluster where some or all of these roles already exist, PROVIDED the role running
-- it holds ADMIN OPTION on them -- which the role that created them does, and which
-- section 1 asserts up front rather than discovering at the first GRANT. Roles are
-- CLUSTER-GLOBAL, so CREATE ROLE is guarded and never dropped here.
--
-- The identity model has exactly one axis: the persona. Data classification is a
-- stamp on the row (acl_visibility in {'workshop','restricted'}), never an identity.
--
--   can_see_restricted     NOLOGIN clearance group. A key, not a limitation:
--                          granted to admin and auditor, never to analyst. Additive
--                          grants fail closed; a subtractive marker would fail open.
--   persona_analyst       NOLOGIN persona. Workshop rows only.
--   persona_admin         NOLOGIN persona. All rows, unmasked.
--   persona_auditor       NOLOGIN persona. All rows, sensitive columns masked
--                          (sql/12_masking.sql).
--   workshop_app           LOGIN. The API pool identity. Owns nothing, holds NO
--                          direct table grants, is granted the personas WITH INHERIT
--                          FALSE. With no role set a SELECT raises permission denied:
--                          a forgotten SET ROLE fails CLOSED. This is why the pool
--                          must not be retrieval_admin: the owner holds
--                          can_see_restricted (granted below, so the seed and index
--                          build can project the whole corpus), and a pool holding
--                          the clearance key would serve restricted rows to everyone.
--   workshop_participant   LOGIN. The Lab terminal identity. Same INHERIT FALSE
--                          persona grants, EXECUTE on admission, pg_monitor for the
--                          watch snippets, and NO evidence SELECT: the permission
--                          denied on a bare evidence SELECT is the first lesson.

-- ---------------------------------------------------------------------------
-- 1. Roles.
-- ---------------------------------------------------------------------------

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'can_see_restricted') THEN
    CREATE ROLE can_see_restricted NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'persona_analyst') THEN
    CREATE ROLE persona_analyst NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'persona_admin') THEN
    CREATE ROLE persona_admin NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'persona_auditor') THEN
    CREATE ROLE persona_auditor NOLOGIN;
  END IF;
END
$$;

-- The personas must never acquire LOGIN, even if an earlier build created them
-- differently. This is an ASSERTION, not an ALTER, for the same privilege reason as
-- the login-role assertion in section 3 below -- and here the reason is sharper.
-- ALTER ROLE requires CREATEROLE *plus* ADMIN OPTION on the target role, and PG16+
-- auto-grants ADMIN OPTION only to the role that CREATED it. So on the exact case
-- this block exists to defend -- the roles already exist, created by someone else --
-- `ALTER ROLE persona_analyst NOLOGIN` raises 42501 and aborts the file. Measured on
-- PG17 with a non-superuser owner and pre-existing personas:
--   ERROR: permission denied to alter role
--   DETAIL: Only roles with the CREATEROLE attribute and the ADMIN option on role
--           "persona_analyst" may alter this role.
-- The guarded CREATE above had correctly skipped them, so the "assert the invariant"
-- statement was the only thing that failed, and it failed on a CORRECT cluster.
-- The assertion needs no privilege, covers can_see_restricted the same way, and
-- names the offending role instead of the file that could not alter it.
DO $$
DECLARE
  v_bad text;
BEGIN
  SELECT string_agg(rolname, ', ' ORDER BY rolname)
    INTO v_bad
    FROM pg_roles
   WHERE rolname IN ('persona_analyst', 'persona_admin', 'persona_auditor',
                     'can_see_restricted')
     AND rolcanlogin;

  IF v_bad IS NOT NULL THEN
    RAISE EXCEPTION
      'these personas hold LOGIN: %. A persona is an assumable role, not an '
      'account: a LOGIN persona can be connected to directly, which skips the '
      'SET LOCAL ROLE envelope the whole enforcement story is told through. '
      'Run ALTER ROLE <name> NOLOGIN as a role holding ADMIN OPTION on it, then '
      're-run this file.', v_bad;
  END IF;
END
$$;

-- ADMIN OPTION precondition, checked ONCE here rather than guarded at each of the
-- 13 role-membership GRANTs below.
--
-- Granting a role requires ADMIN OPTION on that role, and PG16+ auto-grants it only
-- to the role that CREATED it. The guarded CREATE block above is therefore a trap on
-- a re-run by a DIFFERENT owner: it correctly skips the existing roles, and then
-- every GRANT below raises 42501. Measured on PG17, owner holding CREATEROLE but not
-- ADMIN OPTION, personas pre-created by another role:
--   ERROR: permission denied to grant role "can_see_restricted"
-- A REDUNDANT grant raises identically -- PG checks the privilege before noticing the
-- membership already exists -- so this is not merely a first-run concern. It breaks
-- the "safe to re-run" property this file's header claims.
--
-- Not a concern on the deploy target, and this states why rather than assuming it:
-- retrieval_admin creates these roles itself on the first `make schema`, and ADMIN
-- OPTION IS inherited through role membership (unlike the role ATTRIBUTES noted in
-- section 3). Measured read-only on the live cluster: retrieval_admin holds
-- ADMIN OPTION on pg_monitor and rds_superuser via its rds_superuser membership, so
-- `GRANT pg_monitor TO workshop_participant` below succeeds. The failing case is a
-- local or shared cluster where the roles outlived the owner that made them.
DO $$
DECLARE
  v_bad text;
BEGIN
  SELECT string_agg(r, ', ' ORDER BY r)
    INTO v_bad
    FROM unnest(ARRAY['can_see_restricted', 'persona_analyst', 'persona_admin',
                      'persona_auditor', 'pg_monitor']) AS r
   WHERE NOT pg_has_role(current_user, r, 'MEMBER WITH ADMIN OPTION');

  IF v_bad IS NOT NULL THEN
    RAISE EXCEPTION
      '% lacks ADMIN OPTION on: %. Every GRANT below would raise 42501, including '
      'a redundant one, so this file cannot complete as this role. These roles are '
      'CLUSTER-GLOBAL and outlive any one database: they were created by a different '
      'role. Either re-run as that role, or have a role holding ADMIN OPTION run '
      'GRANT <role> TO % WITH ADMIN OPTION, INHERIT FALSE for each. INHERIT FALSE '
      'matters: a plain grant would also hand this role the personas PASSIVELY, '
      'and section 2 grants them INHERIT FALSE precisely so the owner reads by '
      'clearance rather than by silently inheriting a persona.',
      current_user, v_bad, quote_ident(current_user);
  END IF;
END
$$;

-- The clearance key. Direction is the whole point: withhold the key from the
-- analyst rather than marking the analyst as limited.
GRANT can_see_restricted TO persona_admin;
GRANT can_see_restricted TO persona_auditor;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
      FROM pg_auth_members m
      JOIN pg_roles grp ON grp.oid = m.roleid
      JOIN pg_roles mem ON mem.oid = m.member
     WHERE grp.rolname = 'can_see_restricted'
       AND mem.rolname = 'persona_analyst'
  ) THEN
    RAISE EXCEPTION
      'persona_analyst holds can_see_restricted; the analyst persona would see '
      'restricted rows and the row-filtering demo is broken';
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. Read grants for the personas.
--
-- The personas need table-level SELECT for RLS to have anything to filter: RLS
-- narrows rows a role can already reach, it does not grant reach. Writes stay with
-- the owner (schema build, seed, index build) and with the API's proof-writing
-- path, which runs under the persona and therefore needs INSERT on proof.*.
-- ---------------------------------------------------------------------------

DO $$
DECLARE
  v_persona text;
BEGIN
  FOREACH v_persona IN ARRAY ARRAY['persona_analyst', 'persona_admin', 'persona_auditor']
  LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA casework, retrieval, proof TO %I', v_persona);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA casework TO %I', v_persona);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA retrieval TO %I', v_persona);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA proof TO %I', v_persona);
    -- The API persists its own receipts (proof.retrieval_runs, candidates, stages,
    -- agent_* and observability_refs) inside the same persona transaction that ran
    -- the search, so the persona needs write access to proof.* and nothing else.
    EXECUTE format(
      'GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA proof TO %I', v_persona
    );
    EXECUTE format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA retrieval TO %I', v_persona);
    EXECUTE format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA proof TO %I', v_persona);
  END LOOP;
END
$$;

-- Future tables created by the owner inherit the same grants, so a later schema
-- addition cannot silently become unreadable to every persona.
ALTER DEFAULT PRIVILEGES IN SCHEMA casework
  GRANT SELECT ON TABLES TO persona_analyst, persona_admin, persona_auditor;
ALTER DEFAULT PRIVILEGES IN SCHEMA retrieval
  GRANT SELECT ON TABLES TO persona_analyst, persona_admin, persona_auditor;
ALTER DEFAULT PRIVILEGES IN SCHEMA proof
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES
  TO persona_analyst, persona_admin, persona_auditor;

-- ---------------------------------------------------------------------------
-- 3. The two LOGIN roles.
--
-- Passwords are NOT set here: this file is committed to a public repository.
-- The sibling Workshop Studio repo provisions credentials (Secrets Manager) and
-- runs ALTER ROLE ... PASSWORD out of band.
-- ---------------------------------------------------------------------------

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'workshop_app') THEN
    CREATE ROLE workshop_app LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'workshop_participant') THEN
    CREATE ROLE workshop_participant LOGIN;
  END IF;
END
$$;

-- Neither login may ever bypass RLS. This is an ASSERTION, not an ALTER, and the
-- distinction is a privilege one: changing the SUPERUSER or BYPASSRLS attribute
-- requires a real superuser, and this file runs as retrieval_admin, which is an
-- rds_superuser MEMBER and not a superuser. `ALTER ROLE ... NOBYPASSRLS
-- NOSUPERUSER` would therefore raise on Aurora while succeeding on a local cluster
-- whose owner is a true superuser -- a failure that only appears at deployment.
-- The assertion gives the same guarantee, needs no privilege, and reads better:
-- CREATE ROLE above already defaults every one of these attributes to false, so
-- the only way to trip this is for someone to have granted them deliberately.
DO $$
DECLARE
  v_bad text;
BEGIN
  SELECT string_agg(
           format('%s(super=%s bypassrls=%s createdb=%s createrole=%s)',
                  rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole),
           ', ' ORDER BY rolname)
    INTO v_bad
    FROM pg_roles
   WHERE rolname IN ('workshop_app', 'workshop_participant')
     AND (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole);

  IF v_bad IS NOT NULL THEN
    RAISE EXCEPTION
      'the workshop login roles hold privileges that defeat RLS: %. A login with '
      'SUPERUSER or BYPASSRLS reads restricted rows regardless of policy, so G-27 '
      'would pass while the enforcement claim is false. Revoke the attributes as a '
      'superuser and re-run.', v_bad;
  END IF;
END
$$;

-- WITH INHERIT FALSE is load-bearing: the login may SET ROLE to a persona but
-- gains no passive access from the grant. Without it, workshop_app would inherit
-- the personas' SELECT and a forgotten SET ROLE would fail OPEN.
GRANT persona_analyst TO workshop_app WITH INHERIT FALSE;
GRANT persona_admin   TO workshop_app WITH INHERIT FALSE;
GRANT persona_auditor TO workshop_app WITH INHERIT FALSE;

GRANT persona_analyst TO workshop_participant WITH INHERIT FALSE;
GRANT persona_admin   TO workshop_participant WITH INHERIT FALSE;
GRANT persona_auditor TO workshop_participant WITH INHERIT FALSE;

-- The bootstrap owner gets the same three grants, for one specific reason:
-- admission/admit.sh's exact-arm checkpoint runs inside the A3 envelope
-- (BEGIN; SET LOCAL ROLE persona_analyst; SELECT; ROLLBACK), and that script is run
-- BOTH by a participant (as workshop_participant) and by a developer or the Step 5
-- scratch verification (as the bootstrap owner). Without this, the developer path
-- raises "permission denied to set role" while the participant path works -- a
-- divergence that only shows up for whoever is not in the room.
--
-- current_user, not a literal: the owner is retrieval_admin locally and
-- workshop_admin on a provisioned Aurora cluster (the sibling repo's MasterUsername).
-- Naming either one hardcodes the wrong cluster.
--
-- Strictly, PostgreSQL 16+ auto-grants a CREATEROLE role membership WITH ADMIN
-- OPTION on roles it creates, so the owner that ran the CREATE ROLE block above can
-- already SET ROLE to them. That implicit path is not good enough: on an idempotent
-- re-run nothing is created, so a DIFFERENT owner applying this file inherits
-- nothing. Explicit and idempotent beats implicit and conditional.
--
-- INHERIT FALSE keeps this from being a privilege change: the grant adds no passive
-- access, it only makes SET ROLE available. And because SET ROLE changes current_user
-- to a persona that does NOT hold can_see_restricted, the checkpoint gets real RLS
-- on both paths -- the owner's own clearance does not follow it into the persona.
DO $$
BEGIN
  EXECUTE format('GRANT persona_analyst TO %I WITH INHERIT FALSE', current_user);
  EXECUTE format('GRANT persona_admin   TO %I WITH INHERIT FALSE', current_user);
  EXECUTE format('GRANT persona_auditor TO %I WITH INHERIT FALSE', current_user);
END
$$;

-- The participant's own privileges: the exercise surface only.
-- pg_monitor is required, not optional: without it pg_stat_activity shows only the
-- participant's own backend and every Lab-1 watch snippet reads as empty.
GRANT pg_monitor TO workshop_participant;

-- ./admit.sh calls casework.admit_evidence. That is the ONLY casework reach the
-- participant gets: USAGE on the schema plus EXECUTE on the one function. No table
-- SELECT, so a bare SELECT on evidence raises permission denied - the first lesson.
--
-- EXECUTE ALONE IS NOT ENOUGH, and this is the trap that would have broken Lab 1.
-- casework.admit_evidence is LANGUAGE plpgsql with NO SECURITY DEFINER clause
-- (sql/10_admission.sql:36-39), so its body runs with the CALLER's privileges. Its
-- first statement reads casework.ingest_receipts (:78) and it then writes
-- evidence_items, lock_evidence, inferred_edges, search_index_queue and
-- ingest_receipts. A participant holding only EXECUTE would get
-- "permission denied for table ingest_receipts" on the Lab-1 finale, while G-30 --
-- which deliberately probes has_function_privilege and never invokes -- still
-- reported PASS. Two grants that would each defeat the lesson, and the fix:
--
--   * Granting the participant direct DML on those five tables would ALSO grant the
--     SELECT that the "permission denied on a bare SELECT" lesson depends on. Fails.
--   * Making the function SECURITY DEFINER keeps the participant's reach at exactly
--     one function while giving the body the owner's privileges. Correct.
--
-- SECURITY DEFINER is applied below rather than in sql/10_admission.sql because
-- sql/10 must stay runnable before roles exist; the ALTER is idempotent and this is
-- the file that owns the privilege model.
GRANT USAGE ON SCHEMA casework TO workshop_participant;
GRANT EXECUTE ON FUNCTION casework.admit_evidence(jsonb) TO workshop_participant;

-- Definer rights + a pinned search_path. The pin is mandatory, not hygiene: a
-- SECURITY DEFINER function that resolves unqualified names through the caller's
-- search_path is the classic privilege-escalation vector, and the participant
-- controls their own search_path. Every reference in the body is already
-- schema-qualified; the pin makes that structural.
ALTER FUNCTION casework.admit_evidence(jsonb) SECURITY DEFINER;
ALTER FUNCTION casework.admit_evidence(jsonb) SET search_path = pg_catalog, casework, retrieval;

-- PUBLIC gets EXECUTE on every new function by default, which for a SECURITY
-- DEFINER writer means any role in the cluster could admit evidence. Revoke it and
-- re-grant only the two identities that need it.
REVOKE ALL ON FUNCTION casework.admit_evidence(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION casework.admit_evidence(jsonb) TO workshop_participant;
GRANT EXECUTE ON FUNCTION casework.admit_evidence(jsonb) TO workshop_app;

-- The definer is the function's owner, the schema owner (retrieval_admin), which
-- holds can_see_restricted and therefore reads and writes every row. That is correct
-- here and must be stated so nobody "fixes" it later: admission is a WRITE path whose
-- ACL is carried in the payload, not a read path. No participant reads a row through
-- it --
-- the function returns only the ingest receipt (sql/10_admission.sql:163), which
-- holds hashes, counts and IDs, never evidence body text.

-- ---------------------------------------------------------------------------
-- 4. RLS on the three read-path tables, plus the evidence detail tables.
--
-- All three, not just casework: retrieval.vector_search reads retrieval.chunks
-- standalone (sql/03_search_functions.sql:488-514) and retrieval.fuzzy_search reads
-- retrieval.documents standalone (:614-634). A policy on casework.evidence_items
-- alone would leak restricted body text through the vector and fuzzy arms while the
-- headers stayed filtered. This is the single most important correctness
-- requirement in this file.
--
-- FORCE is required because the tables are owned by retrieval_admin and owners
-- bypass RLS by default. FORCE still does NOT subject a role holding SUPERUSER or
-- BYPASSRLS, which is why the app pool is workshop_app, not retrieval_admin.
--
-- Note the attribute, not the membership: role attributes are NOT inherited through
-- role membership. Measured read-only on the live cluster: retrieval_admin has
-- rolsuper=false and rolbypassrls=false, and rds_superuser itself has
-- rolbypassrls=false -- so there is no bypass to inherit and the owner IS subject to
-- FORCE on Aurora exactly as it is locally. Any comment claiming otherwise is wrong.
-- ---------------------------------------------------------------------------

ALTER TABLE casework.evidence_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE casework.evidence_items FORCE ROW LEVEL SECURITY;
ALTER TABLE retrieval.documents     ENABLE ROW LEVEL SECURITY;
ALTER TABLE retrieval.documents     FORCE ROW LEVEL SECURITY;
ALTER TABLE retrieval.chunks        ENABLE ROW LEVEL SECURITY;
ALTER TABLE retrieval.chunks        FORCE ROW LEVEL SECURITY;

-- The bootstrap owner needs the clearance key, and this is NOT belt-and-braces.
-- Measured on PostgreSQL 17 against this exact policy shape (four cases):
--
--   owner in policy TO list? | owner holds clearance? | rows the owner sees
--   -------------------------|------------------------|--------------------
--   no                       | no                     | 0  (all rows vanish)
--   no                       | YES                    | 0  (still vanish)
--   YES                      | no                     | workshop rows ONLY
--   YES                      | YES                    | all rows
--
-- Row three is the dangerous one, because nothing fails: the owner reads a
-- SILENTLY TRUNCATED table. The seed, the search-index build and every derived
-- projection run as the owner, and a measured
-- `INSERT INTO projection SELECT ... FROM source` under row three copied 1 of 2
-- rows and reported success. Restricted evidence would simply never reach
-- retrieval.documents/chunks -- and then G-27(b) would "pass" (analyst sees 0
-- restricted rows) for the wrong reason: there would be no restricted rows to see.
-- Both halves are required. This grant is the second half; the FIRST half is naming
-- CURRENT_USER in each policy's TO list below, and it is not optional on ANY cluster.
--
-- This grant alone lands the build in row TWO, not row four. Measured on PG17 with a
-- non-superuser owner, FORCE enabled, this grant applied and the policies listing
-- only the three personas: the owner saw 0 of 2 rows, `INSERT` raised
-- "new row violates row-level security policy", and `INSERT INTO projection SELECT`
-- copied 0 rows and exited 0. A PERMISSIVE policy set that names no applicable role
-- denies every row, and the clearance key cannot rescue a role no policy applies to.
--
-- The persona grants to the owner are WITH INHERIT FALSE, which is why the owner does
-- not reach the policies through them: measured, pg_has_role(owner, 'persona_analyst',
-- 'USAGE') is false, and the TO list is matched by that same USAGE semantics.
--
-- Not an Aurora no-op either. Role attributes are not inherited through membership;
-- measured read-only on the live cluster, retrieval_admin is rolsuper=false
-- rolbypassrls=false and rds_superuser has rolbypassrls=false. Without both halves,
-- `make schema` followed by `make seed` breaks on the deploy target, not just on the
-- disposable test databases.
--
-- Deliberately NOT the personas' clearance path: the owner is the writer, and the
-- teaching claim is about readers.
DO $$
BEGIN
  EXECUTE format('GRANT can_see_restricted TO %I', current_user);
END
$$;

DROP POLICY IF EXISTS rls_evidence_items_visibility ON casework.evidence_items;
DROP POLICY IF EXISTS rls_documents_visibility      ON retrieval.documents;
DROP POLICY IF EXISTS rls_chunks_visibility         ON retrieval.chunks;

-- casework.evidence_items keeps its classification inside the acl jsonb
-- (sql/01_schema.sql:40); the two retrieval tables carry the denormalized scalar
-- (:901, :968). Same value for the same row, same fail-closed default.
--
-- CURRENT_USER in the TO list is the first half of the owner fix above, and it is
-- safe: PostgreSQL resolves it to an OID at CREATE POLICY time and stores that OID in
-- pg_policy.polroles -- it is NOT re-evaluated per query. Measured on PG17: the
-- stored roles read {persona_admin, persona_analyst, persona_auditor,
-- retrieval_admin}, and `SET LOCAL ROLE persona_analyst` still saw 1 of 3 rows. If it
-- were dynamic it would match every persona and hand the analyst the clearance
-- disjunct, which is exactly the failure G-27(b) exists to catch. It does not.
CREATE POLICY rls_evidence_items_visibility ON casework.evidence_items
  FOR ALL
  TO persona_analyst, persona_admin, persona_auditor, CURRENT_USER
  USING (
    coalesce(acl ->> 'visibility', 'restricted') = 'workshop'
    OR pg_has_role(current_user, 'can_see_restricted', 'USAGE')
  );

-- THE teaching expression. Byte-identical to the Lab-3 H2 predicate and to the
-- guide snippet. "The predicate teaches, RLS enforces" is the same expression at
-- two layers - if you change one, change all three.
CREATE POLICY rls_documents_visibility ON retrieval.documents
  FOR ALL
  TO persona_analyst, persona_admin, persona_auditor, CURRENT_USER
  USING (
    acl_visibility = 'workshop'
    OR pg_has_role(current_user, 'can_see_restricted', 'USAGE')
  );

CREATE POLICY rls_chunks_visibility ON retrieval.chunks
  FOR ALL
  TO persona_analyst, persona_admin, persona_auditor, CURRENT_USER
  USING (
    acl_visibility = 'workshop'
    OR pg_has_role(current_user, 'can_see_restricted', 'USAGE')
  );

-- ---------------------------------------------------------------------------
-- 5. RLS on the evidence detail tables.
--
-- The three policies above are necessary and NOT sufficient. The sensitive text
-- is not in casework.evidence_items -- that table holds the header (external_key,
-- title, acl). The body lives in per-kind detail tables keyed 1:1 on evidence_id,
-- and section 2 grants every persona SELECT ON ALL TABLES IN SCHEMA casework
-- because RLS narrows reach, it does not grant it. Without the policies below, a
-- participant does this and the whole teaching claim collapses:
--
--   BEGIN; SET LOCAL ROLE persona_analyst;
--   SELECT count(*) FROM casework.evidence_items;   -- restricted rows hidden, correct
--   SELECT account_name, description, customer_commitment
--     FROM casework.support_cases;                   -- CASE-7421 in full. Measured.
--   ROLLBACK;
--
-- psql is the workshop's primary surface, not a back door: Lab 1's first lesson is
-- that a bare SELECT is denied. A participant who is denied at evidence_items and
-- then reads Northstar Foods' customer commitment one query later has been taught
-- the opposite of the intended lesson.
--
-- The predicate is a bare EXISTS back to the parent, NOT a copy of the clearance
-- expression. Three reasons: the detail tables have no acl column to read; one
-- definition of clearance beats seven; and the parent is already RLS-filtered, so
-- the child inherits the parent's visibility for free. Measured on PG17 with the
-- parent policy active: analyst saw 1 of 2 parent rows and 1 of 2 child rows with
-- the restricted account_name denied, while admin saw 2 and 2 unmasked. Graded,
-- not deny-all.
--
-- The dependency on the parent's RLS is load-bearing and was verified by negative
-- control: with ALTER TABLE casework.evidence_items DISABLE ROW LEVEL SECURITY,
-- the analyst saw every child row again. The EXISTS is not self-sufficient -- it
-- is filtered by the parent's policy. If a future change disables RLS on
-- casework.evidence_items, every table below silently opens. G-27 asserts
-- enabled+forced on the parent, which is what keeps that from happening quietly.
--
-- FOR ALL with USING only, matching the policies above. WITH CHECK defaults to
-- USING when omitted, and the foreign key guarantees the parent row exists, so
-- seed INSERTs still pass -- measured: the owner inserted a new restricted parent
-- and child under FORCE, and INSERT INTO projection SELECT copied 3 of 3 rows with
-- no silent truncation. FOR SELECT would be wrong: FORCE subjects the owner to
-- INSERT policies too, and with no INSERT-applicable policy every seed write is
-- denied.
--
-- CURRENT_USER in each TO list for the same reason as the policies above, which is
-- not optional on any cluster: it is stored as an OID in pg_policy.polroles at
-- CREATE POLICY time, and without it the owner reads zero rows and every derived
-- projection truncates while reporting success.
--
-- All seven evidence-keyed detail tables, not only the three the current
-- restricted cohort touches. The bypass class is "the grant is schema-wide, so any
-- evidence_id-keyed table is a door" -- an allowlist tracking today's cohort
-- re-opens the hole the moment a later cohort adds a kind. The junction tables
-- (incident_changes, incident_support_cases, incident_runbooks, change_runbooks,
-- support_case_commitments) are deliberately excluded: they carry no evidence body,
-- only a rationale, and they are read solely through
-- casework.v_evidence_documents, which Task 10 makes security_invoker so the
-- caller's policies apply.
-- ---------------------------------------------------------------------------

DO $$
DECLARE
  v_table text;
BEGIN
  FOREACH v_table IN ARRAY ARRAY['incidents', 'changes', 'support_cases', 'runbooks',
                                 'lock_evidence', 'customer_commitments', 'postmortems']
  LOOP
    EXECUTE format('ALTER TABLE casework.%I ENABLE ROW LEVEL SECURITY', v_table);
    EXECUTE format('ALTER TABLE casework.%I FORCE  ROW LEVEL SECURITY', v_table);
    EXECUTE format('DROP POLICY IF EXISTS rls_%s_visibility ON casework.%I',
                   v_table, v_table);
    EXECUTE format($fmt$
      CREATE POLICY rls_%s_visibility ON casework.%I
        FOR ALL
        TO persona_analyst, persona_admin, persona_auditor, CURRENT_USER
        USING (EXISTS (SELECT 1
                         FROM casework.evidence_items parent
                        WHERE parent.evidence_id = casework.%I.evidence_id))
    $fmt$, v_table, v_table, v_table);
  END LOOP;
END
$$;
```

- [ ] **Step 2: Run `admit.sh`'s exact-arm checkpoint under a persona**

The checkpoint is the one participant-facing SQL statement outside `sql/` that
touches a read-path table (verified: `grep -rln 'FROM casework\.\|FROM retrieval\.'`
outside `sql/` returns `admission/admit.sh` and nothing else). It must go through a
persona, for the reason in the note above this step.

In `admission/admit.sh`, replace lines 24-29:

```bash
echo "── exact-arm checkpoint ───────────────────────"
hit="$(psql "$DATABASE_URL" -X -q -t -A -v ON_ERROR_STOP=1 -v key="$key" <<'SQL'
SELECT external_key FROM casework.evidence_items
 WHERE external_key = :'key' AND available_at <= now();
SQL
)"
```

with:

```bash
echo "── exact-arm checkpoint ───────────────────────"
# Read as a persona, not as the connected login. Three reasons, in order of how
# badly each bites if you skip it:
#
#  1. workshop_participant holds no SELECT on casework.evidence_items -- by design
#     (A1: a bare SELECT raising permission denied is the first lesson). The
#     admit_evidence call above works because that function is SECURITY DEFINER;
#     this statement is outside it, so without SET LOCAL ROLE the Lab 1 finale
#     prints the receipt and then dies on "permission denied for table
#     evidence_items".
#  2. RLS is enforced on this table. Reading as a persona means the checkpoint
#     proves the admitted row is retrievable THROUGH the same enforcement path the
#     workshop later takes apart, not merely that a row was written.
#  3. persona_analyst specifically -- the least-privileged of the three. Payloads
#     default to acl {"visibility": "workshop"} (promote_pg_incident.py:41), so the
#     analyst can see them. If a future capture ships a restricted ACL, this
#     checkpoint SHOULD report not-visible: that is the enforcement working.
#
# SET LOCAL + ROLLBACK, never a session-level SET: read-only and self-undoing, and
# the same A3 envelope every _verify_sql in the app emits.
hit="$(psql "$DATABASE_URL" -X -q -t -A -v ON_ERROR_STOP=1 -v key="$key" <<'SQL'
BEGIN;
SET LOCAL ROLE persona_analyst;
SELECT external_key FROM casework.evidence_items
 WHERE external_key = :'key' AND available_at <= now();
ROLLBACK;
SQL
)"
```

`-t -A` prints only the row, so `BEGIN`/`SET`/`ROLLBACK` add no output and the
existing `[ "$hit" = "$key" ]` comparison at `:30` still holds. Then extend the
REMEDY line at `:33` so a privilege failure is not misread as an admission failure:

```bash
  echo "REMEDY: ${key} not visible as-of now(); check available_at, that admit succeeded, and that sql/11_roles_rls.sql has been applied (this read runs as persona_analyst)" >&2
```

Also correct `admission/README.md`. Replace the `admit.sh` bullet at `:96-100`:

```markdown
- `admit.sh` — the Lab 1 finale script. Requires `DATABASE_URL` in the
  environment, runs the promoter, pipes the resulting payload into
  `casework.admit_evidence` via `psql`, prints the ingest receipt, and then
  runs the exact-arm checkpoint (confirms the admitted `external_key` is
  immediately selectable from `casework.evidence_items` as of `now()`, read as
  `persona_analyst` inside a rolled-back transaction so the check passes through
  live RLS rather than around it).
```

and the trailing ACL note at `:129-130`:

```markdown
Payloads default `acl` to `{"visibility": "workshop"}`, matching the
corpus-wide default scope documented in `docs/data-model.md`. That default is
what makes `persona_analyst` the right identity for the exact-arm checkpoint: a
payload admitted with `{"visibility": "restricted"}` is invisible to the analyst
by RLS, and the checkpoint reporting it as not-visible is correct behavior, not a
failed admission.
```

- [ ] **Step 3: Change `acl_visible` volatility**

`pg_has_role` is `STABLE`, so any predicate that reaches it cannot live inside an
`IMMUTABLE` function. `acl_visible` does not call `pg_has_role` today, but the H2
teaching predicate (Task 9) shares its shape, and mislabelling volatility lets the
planner constant-fold a role-dependent result across a role change.

In `sql/03_search_functions.sql`, replace lines 1-5:

```sql
CREATE OR REPLACE FUNCTION retrieval.acl_visible(p_acl jsonb, p_principal jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
```

with:

```sql
-- STABLE, not IMMUTABLE: identity-dependent predicates (pg_has_role) are STABLE,
-- and an IMMUTABLE label would license the planner to constant-fold a result that
-- is only valid for the role that was current when it was folded.
CREATE OR REPLACE FUNCTION retrieval.acl_visible(p_acl jsonb, p_principal jsonb)
RETURNS boolean
LANGUAGE sql
STABLE
PARALLEL SAFE
```

Do the same for `retrieval.acl_scalars_visible` at `sql/03_search_functions.sql:31`
onward — find its `IMMUTABLE` line and change it to `STABLE`, keeping
`PARALLEL SAFE`.

- [ ] **Step 4: Add both files to `make schema`**

In `Makefile`, replace the `SQL_FILES` block (lines 17-28):

```make
SQL_FILES := \
	sql/00_extensions.sql \
	sql/01_schema.sql \
	sql/02_indexes.sql \
	sql/03_search_functions.sql \
	sql/04_diagnostics.sql \
	sql/05_evaluation.sql \
	sql/06_receipts.sql \
	sql/07_search_index_verification.sql \
	sql/08_query_runtime.sql \
	sql/09_traverse_evidence.sql \
	sql/10_admission.sql \
	sql/11_roles_rls.sql \
	sql/12_masking.sql
```

`sql/12_masking.sql` is created in Task 6. Until then `make schema` would fail on
the missing file, so **Task 5 adds only the `11_` line** and Task 6 adds the `12_`
line. Write the block with `sql/11_roles_rls.sql` as the last entry for now.

- [ ] **Step 5: Add the new DSN keys to `.env.example`**

After the existing `DATABASE_URL` / `DATABASE_CONNECT_TIMEOUT_SECONDS` lines,
insert:

```
# The API pool identity. Fails CLOSED: workshop_app holds no table grants, so a
# request that forgets SET LOCAL ROLE raises permission denied instead of leaking.
# DATABASE_URL above stays the OWNER/bootstrap identity: schema, seed, index build.
WORKSHOP_APP_DATABASE_URL=postgresql://workshop_app:password@example.cluster.us-east-1.rds.amazonaws.com:5432/workshop_db
# The Lab terminal identity. Reads monitoring views with zero ceremony; a bare
# SELECT on evidence raises permission denied by design.
WORKSHOP_PARTICIPANT_DATABASE_URL=postgresql://workshop_participant:password@example.cluster.us-east-1.rds.amazonaws.com:5432/workshop_db
```

- [ ] **Step 6: Verify on a disposable database — never live**

Roles are cluster-global, so this uses a prefixed throwaway set and drops them in a
`finally`. Create `/tmp/verify_rls_task5.sh`:

```bash
#!/usr/bin/env bash
# Disposable verification for sql/11_roles_rls.sql. Creates a scratch database and
# prefixed scratch roles, applies the schema sequence, asserts the three claims,
# then drops everything. Never touches the live retrieval database.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

: "${ADMIN_DATABASE_URL:?set ADMIN_DATABASE_URL to a maintenance DSN (postgres db)}"
SCRATCH_DB="rls_verify_$$"

# Guard: the maintenance connection must NOT be pointed at the live retrieval DB.
current="$(psql "$ADMIN_DATABASE_URL" -X -q -t -A -c 'SELECT current_database()')"
if [ "$current" = "retrieval" ]; then
  echo "REFUSING: maintenance DSN resolves to the live 'retrieval' database" >&2
  exit 1
fi
echo "maintenance database: $current (scratch: $SCRATCH_DB)"

cleanup() {
  psql "$ADMIN_DATABASE_URL" -X -q -v ON_ERROR_STOP=0 <<SQL || true
DROP DATABASE IF EXISTS ${SCRATCH_DB} WITH (FORCE);
SQL
  echo "cleaned up $SCRATCH_DB"
}
trap cleanup EXIT

psql "$ADMIN_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${SCRATCH_DB}"
SCRATCH_URL="$(python3 - "$ADMIN_DATABASE_URL" "$SCRATCH_DB" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit
parts = urlsplit(sys.argv[1])
print(urlunsplit(parts._replace(path="/" + sys.argv[2])))
PY
)"

DATABASE_URL="$SCRATCH_URL" .venv/bin/python backend/scripts/run_sql.py --files \
  sql/00_extensions.sql sql/01_schema.sql sql/02_indexes.sql \
  sql/03_search_functions.sql sql/04_diagnostics.sql sql/05_evaluation.sql \
  sql/06_receipts.sql sql/07_search_index_verification.sql \
  sql/08_query_runtime.sql sql/09_traverse_evidence.sql sql/10_admission.sql \
  sql/11_roles_rls.sql

echo "--- idempotency: re-run 11 ---"
DATABASE_URL="$SCRATCH_URL" .venv/bin/python backend/scripts/run_sql.py \
  --files sql/11_roles_rls.sql

echo "--- assertions ---"
psql "$SCRATCH_URL" -X -q -v ON_ERROR_STOP=1 <<'SQL'
\echo 1. personas are NOLOGIN and analyst lacks the clearance key
SELECT rolname, rolcanlogin, rolbypassrls,
       pg_has_role(rolname, 'can_see_restricted', 'USAGE') AS has_clearance
  FROM pg_roles
 WHERE rolname IN ('persona_analyst','persona_admin','persona_auditor',
                   'workshop_app','workshop_participant','can_see_restricted')
 ORDER BY rolname;

\echo 2. RLS is enabled AND forced on all three read-path tables
SELECT n.nspname||'.'||c.relname AS tbl, c.relrowsecurity, c.relforcerowsecurity
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname||'.'||c.relname IN
       ('casework.evidence_items','retrieval.documents','retrieval.chunks')
 ORDER BY tbl;

\echo 3. one policy per table, applied to the three personas AND the owner
SELECT schemaname||'.'||tablename AS tbl, policyname, roles
  FROM pg_policies
 WHERE schemaname||'.'||tablename IN
       ('casework.evidence_items','retrieval.documents','retrieval.chunks')
 ORDER BY tbl;

\echo 4. the personas hold no INHERITed access from the logins
SELECT grp.rolname AS granted_role, mem.rolname AS member, m.inherit_option
  FROM pg_auth_members m
  JOIN pg_roles grp ON grp.oid=m.roleid
  JOIN pg_roles mem ON mem.oid=m.member
 WHERE mem.rolname IN ('workshop_app','workshop_participant')
 ORDER BY member, granted_role;

\echo 5. admission is SECURITY DEFINER with a pinned search_path
SELECT p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner) AS owner,
       has_function_privilege('workshop_participant',
                              'casework.admit_evidence(jsonb)', 'EXECUTE') AS participant_execute,
       has_table_privilege('workshop_participant',
                           'casework.ingest_receipts', 'SELECT') AS participant_reads_receipts
  FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='casework' AND p.proname='admit_evidence';
SQL
echo "OK: sql/11_roles_rls.sql applied twice, all assertions printed"

echo "--- behavioural: the participant can actually admit ---"
# The EXECUTE privilege check above is necessary and not sufficient: a non-definer
# body raises permission denied on ingest_receipts. This actually calls the writer on
# the scratch database (never live -- the guard at the top of this script refuses
# 'retrieval') and asserts the contract error, not a privilege error. An unseeded
# scratch DB has no incident to reference, so the CORRECT outcome is the 23503
# 'referenced incident not found' contract raise. 42501 means the definer rights are
# missing and Lab 1 is broken.
psql "$SCRATCH_URL" -X -q -v ON_ERROR_STOP=0 <<'SQL'
SET ROLE workshop_participant;
SELECT casework.admit_evidence(jsonb_build_object(
  'schema', 'admission payload v1',
  'kind', 'lock_evidence',
  'external_key', 'PRIVILEGE-PROBE-1',
  'title', 'privilege probe',
  'body', 'privilege probe',
  'occurred_at', '2026-01-01T00:00:00Z',
  'source', jsonb_build_object('uri', 'probe://privilege', 'system', 'probe'),
  'structured', jsonb_build_object('incident_external_key', 'NO-SUCH-INCIDENT')
));
RESET ROLE;
SQL

echo "--- behavioural: admit.sh's checkpoint envelope works for BOTH identities ---"
# Step 2 rewrote the exact-arm checkpoint to read as persona_analyst. Two ways that
# can be wrong, and this probe catches both:
#   * the participant path: without the persona, permission denied on evidence_items
#   * the developer path:   without the current_user grant, "permission denied to
#                           set role" -- which only bites whoever is not in the room
# Zero rows is the expected result on an unseeded scratch DB. What matters is that
# neither statement RAISES. Run as the owner first, then as the participant.
psql "$SCRATCH_URL" -X -q -t -A -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
SET LOCAL ROLE persona_analyst;
SELECT count(*) AS owner_path_rows FROM casework.evidence_items
 WHERE external_key = 'LOCK-LIVE-001' AND available_at <= now();
ROLLBACK;
SQL

psql "$SCRATCH_URL" -X -q -t -A -v ON_ERROR_STOP=1 <<'SQL'
SET ROLE workshop_participant;
BEGIN;
SET LOCAL ROLE persona_analyst;
SELECT count(*) AS participant_path_rows FROM casework.evidence_items
 WHERE external_key = 'LOCK-LIVE-001' AND available_at <= now();
ROLLBACK;
RESET ROLE;
SQL
echo "OK: both checkpoint paths ran without a privilege error"

echo "--- negative control: the same read WITHOUT the persona must be denied ---"
# Proves the A1 lesson is intact and that the envelope in Step 2 is load-bearing
# rather than decorative. ON_ERROR_STOP=0: the raise IS the expected outcome.
psql "$SCRATCH_URL" -X -q -v ON_ERROR_STOP=0 <<'SQL'
SET ROLE workshop_participant;
SELECT count(*) FROM casework.evidence_items;
RESET ROLE;
SQL
```

Run:
```bash
chmod +x /tmp/verify_rls_task5.sh
ADMIN_DATABASE_URL="postgresql://localhost:55432/postgres?sslmode=disable" /tmp/verify_rls_task5.sh
```

Expected: both `run_sql.py` invocations print `Done` (proving idempotency); query 1
shows `rolcanlogin=f` for the three personas and `can_see_restricted`, `t` for the
two logins, `rolbypassrls=f` for every row, and `has_clearance=f` for
`persona_analyst` with `t` for admin and auditor; query 2 shows
`relrowsecurity=t, relforcerowsecurity=t` on all three tables; query 3 shows
exactly three policies, each with **four** roles — the three personas plus the
table owner, because `CURRENT_USER` in the `TO` list resolved to the owner's OID at
`CREATE POLICY` time. `pg_policies.roles` sorts by name, so on the scratch database
the owner sorts wherever its name falls; on the deploy target the array reads
`{persona_admin,persona_analyst,persona_auditor,retrieval_admin}`. Three roles
instead of four means the owner half of the fix is missing and `make seed` will copy
zero rows while exiting 0. Query 4 shows
`inherit_option=f` on all six persona grants; query 5 shows `prosecdef=t`,
`proconfig={search_path=pg_catalog,casework,retrieval}`, `participant_execute=t`
and **`participant_reads_receipts=f`** — the participant can admit without being
able to read. The admission probe must fail with
`ERROR: admission: referenced incident NO-SUCH-INCIDENT not found` (SQLSTATE
23503). If it instead reports `ERROR: permission denied for table ingest_receipts`
(42501), the definer rights did not apply and Lab 1's finale is broken — stop and
fix `sql/11_roles_rls.sql` before continuing.

The two checkpoint-envelope probes must both print `0` and exit 0
(`ON_ERROR_STOP=1`, so any raise aborts the script). `permission denied to set role
"persona_analyst"` on the first means the `current_user` grant block is missing;
`permission denied for table evidence_items` on the second means `SET LOCAL ROLE`
is not taking effect. The negative control must print
`ERROR: permission denied for table evidence_items` — if it returns a count
instead, the participant has a `SELECT` grant it must never have and the A1 lesson
is gone. The trap drops the scratch database.

- [ ] **Step 7: Run G-27 — expect BLOCKED on the missing app DSN, not on roles**

Run: `gates/checks.sh G-27`

Against the **live** cluster (where Task 5's SQL has not been applied yet) this
still reports `roles not created yet`. That is correct and expected: the roles exist
only on the scratch database, which was dropped. Record the output verbatim; do not
apply this file to live until the user gives explicit go-ahead (Task 14).

- [ ] **Step 8: Commit**

```bash
git add sql/11_roles_rls.sql sql/03_search_functions.sql admission/admit.sh \
        admission/README.md Makefile .env.example
git commit -m "Add workshop identities and RLS policies on all read-path tables"
```

---

## Task 6: Column masking for the auditor (`sql/12_masking.sql`)

RLS decides which rows exist for a persona. Masking decides which *columns* a row
shows. The auditor is the only persona with a masking policy: it sees the
restricted row (proving the case exists and process was followed) with the customer
identity redacted.

**Files:**
- Create: `sql/12_masking.sql`
- Modify: `Makefile` (append `sql/12_masking.sql` to `SQL_FILES`)

**Interfaces:**
- Consumes: roles from Task 5; `casework.support_cases` (`sql/01_schema.sql:96-109`),
  `retrieval.documents.account_name` (`:905`), `retrieval.chunks.account_name` and
  `.chunk_text` (`:956`, `:968`).
- Produces: `casework.mask_redact(text)`, `retrieval.mask_blob(text)`,
  `retrieval.refresh_mask_blob()`, and masking policies bound to
  `persona_auditor`.

**Mask surface, measured against the projections (this is why the design's
"typed columns" list is not sufficient on its own):**

| Column | Why it must be masked | Mask |
|---|---|---|
| `casework.support_cases.account_name` | authoritative customer identity | `pgcolumnmask.mask_text` |
| `casework.support_cases.description` | narrative naming the account's regulated flow | `casework.mask_redact` |
| `casework.support_cases.customer_commitment` | the disclosure commitment itself | `casework.mask_redact` |
| `retrieval.documents.account_name` | **denormalized copy**, projected by every arm (`sql/03_search_functions.sql:170,416,534,673,928`) and filterable via `p_account_name` (`:304,343,376,505,626`) | `pgcolumnmask.mask_text` |
| `retrieval.chunks.account_name` | same copy on the chunk row, read by `vector_search` (`:505`) | `pgcolumnmask.mask_text` |
| `retrieval.chunks.chunk_text` | the rendered body, sliced into `snippet` by every arm (`:423,541,680,935`) and into `_candidate_document` (`backend/app/search.py:517-527`) | `retrieval.mask_blob` |

`retrieval.documents` has **no body column** — the design doc's phrase "the
`retrieval.documents` rendered body" refers to `casework.v_evidence_documents.body`
(`sql/01_schema.sql:534-545`), which is a view over casework and is not stored on
`documents`. The stored blob lives only on `retrieval.chunks.chunk_text`. Mask
scope B is therefore: three casework columns, two `account_name` copies, one blob.

**Recorded deviation from the design doc (A5 vs. `IMMUTABLE`)**, restated here
because this task implements it: A5 requires the blob pattern set be *generated*
from the seed's restricted sensitive values, while the design requires
`mask_blob` be `IMMUTABLE` — and an `IMMUTABLE` function may not read tables.
Resolution: `retrieval.mask_blob(text)` stays `IMMUTABLE` with the literals baked
into its body, and `retrieval.refresh_mask_blob()` (`VOLATILE`) regenerates that
body from the live restricted rows. The initial body masks the **whole** blob, so
a build that never calls the refresh over-masks rather than under-masks.

- [ ] **Step 1: [VERIFY] Discover the extension's policy inventory — BLOCKING**

The spike confirmed `pgcolumnmask.create_masking_policy(name, regclass, jsonb,
name[], int)`. It did **not** record how an existing policy is replaced, and this
file must be re-runnable. Measure it; do not guess.

On a **disposable** database (the Task 5 Step 6 scratch pattern, on the Aurora
cluster — `pg_columnmask` is Aurora-managed and is not available on local
Postgres):

```sql
CREATE EXTENSION IF NOT EXISTS pg_columnmask;

-- every function the extension ships
SELECT p.proname,
       pg_get_function_identity_arguments(p.oid) AS args,
       CASE p.provolatile WHEN 'i' THEN 'IMMUTABLE'
                          WHEN 's' THEN 'STABLE'
                          ELSE 'VOLATILE' END AS volatility
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'pgcolumnmask'
 ORDER BY p.proname, args;

-- every relation the extension ships (its policy catalog is in here)
SELECT c.relname, c.relkind
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'pgcolumnmask'
 ORDER BY c.relname;
```

Record the output verbatim in the task report. Then pick the branch:

- **Branch A — a drop/delete procedure exists** (a `proname` matching
  `drop%polic%`): the file calls it before each `create_masking_policy`, ignoring
  a not-found condition.
- **Branch B — no drop procedure exists**: the file reads the policy catalog
  relation found above and skips creation only when a policy of the same name
  already exists, and **raises** if it exists with different expressions, so a
  stale policy can never survive silently.

Both branches are written out in full in Step 2. Delete the branch you did not
measure; do not ship both.

- [ ] **Step 2: Write `sql/12_masking.sql`**

```sql
-- sql/12_masking.sql - column masking for the auditor persona (design "scope B").
--
-- RLS (sql/11_roles_rls.sql) decides which ROWS a persona sees. This file decides
-- which COLUMNS the auditor sees inside a row it is allowed to see. Analyst never
-- reaches a restricted row, admin is the unmasked baseline, auditor is the point.
--
-- Requires the cluster parameter pgcolumnmask.policy_admin_rolname to name the role
-- running this file. Without it create_masking_policy cannot be called, and this
-- file must FAIL LOUDLY rather than leave an unmasked cluster that looks configured.

CREATE EXTENSION IF NOT EXISTS pg_columnmask;

DO $$
DECLARE
  v_admin text := current_setting('pgcolumnmask.policy_admin_rolname', true);
BEGIN
  IF v_admin IS NULL OR v_admin = '' THEN
    RAISE EXCEPTION
      'pgcolumnmask.policy_admin_rolname is not set in the DB cluster parameter '
      'group; masking policies cannot be created. Set it to the schema owner and '
      're-run. Refusing to leave the auditor persona unmasked.';
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 1. Masking functions.
--
-- IMMUTABLE and deterministic: the auditor's masked value must be byte-identical
-- in the app panel and in the pasted verify-SQL (Law 2, asserted by G-29).
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION casework.mask_redact(p_value text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT CASE WHEN p_value IS NULL THEN NULL ELSE '[REDACTED]' END
$$;

COMMENT ON FUNCTION casework.mask_redact(text) IS
  'Whole-value redaction for masking policies. A bare literal is rejected by '
  'pgcolumnmask ("Invalid masking function"), so the constant needs a function.';

-- Initial body: mask the WHOLE blob. refresh_mask_blob() narrows it to the
-- sensitive substrings. A build that skips the refresh therefore OVER-masks, which
-- fails closed; the reverse default would leak.
CREATE OR REPLACE FUNCTION retrieval.mask_blob(p_value text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT CASE WHEN p_value IS NULL THEN NULL ELSE '[REDACTED]' END
$$;

COMMENT ON FUNCTION retrieval.mask_blob(text) IS
  'Substring redaction inside the rendered chunk_text. Body is GENERATED by '
  'retrieval.refresh_mask_blob() from the restricted rows sensitive values (A5): '
  'never hand-write the pattern set. Ships masking the whole blob so a skipped '
  'refresh over-masks rather than leaks.';

-- ---------------------------------------------------------------------------
-- 2. Pattern generation (A5): the pattern set is measured from the corpus.
--
-- Regex metacharacters in the literals are escaped before they become patterns.
-- This is not hypothetical: the canonical restricted account is
-- 'Northstar Foods (fictional)', and unescaped parentheses would compile as a
-- capture group that matches 'Northstar Foods fictional' and misses the real value.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION retrieval.sensitive_literals()
RETURNS TABLE (literal text)
LANGUAGE sql
STABLE
AS $$
  SELECT DISTINCT v.literal
    FROM casework.support_cases sc
    JOIN casework.evidence_items e ON e.evidence_id = sc.evidence_id
    CROSS JOIN LATERAL (
      VALUES (sc.account_name), (sc.customer_commitment), (sc.description)
    ) AS v(literal)
   WHERE coalesce(e.acl ->> 'visibility', 'restricted') = 'restricted'
     AND v.literal IS NOT NULL
     AND length(v.literal) > 0
   ORDER BY 1
$$;

COMMENT ON FUNCTION retrieval.sensitive_literals() IS
  'The single source of the mask pattern set and of the G-29 leak-scan needle set. '
  'Both the generator and the gate read this, so they cannot disagree.';

CREATE OR REPLACE FUNCTION retrieval.refresh_mask_blob()
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
  v_expression text := 'p_value';
  v_literal    text;
  v_count      integer := 0;
BEGIN
  FOR v_literal IN SELECT literal FROM retrieval.sensitive_literals()
  LOOP
    v_expression := format(
      'regexp_replace(%s, %L, %L, %L)',
      v_expression,
      regexp_replace(v_literal, '([.^$*+?()\[\]{}|\\-])', '\\\1', 'g'),
      '[REDACTED]',
      'g'
    );
    v_count := v_count + 1;
  END LOOP;

  IF v_count = 0 THEN
    RAISE EXCEPTION
      'no restricted sensitive literals found; retrieval.mask_blob would become a '
      'no-op and the auditor would read customer identity in chunk_text. Seed the '
      'restricted rows before refreshing the mask.';
  END IF;

  EXECUTE format(
    $fn$
      CREATE OR REPLACE FUNCTION retrieval.mask_blob(p_value text)
      RETURNS text
      LANGUAGE sql
      IMMUTABLE
      PARALLEL SAFE
      AS $body$
        SELECT CASE WHEN p_value IS NULL THEN NULL ELSE %s END
      $body$
    $fn$,
    v_expression
  );

  RETURN v_count;
END
$$;

COMMENT ON FUNCTION retrieval.refresh_mask_blob() IS
  'Regenerates retrieval.mask_blob from retrieval.sensitive_literals(). Run after '
  'every seed or admission that adds a restricted row. Raises if the corpus holds '
  'no restricted literals rather than generating a no-op mask.';

-- Bootstrap refresh, GUARDED. It must be guarded because `make schema` runs before
-- `make seed-casework`: on a freshly provisioned account the corpus is empty, so an
-- unconditional call would hit the "no restricted sensitive literals" raise above
-- and fail the schema build for every workshop account. Skipping is safe in exactly
-- one direction: the shipped mask_blob body redacts the WHOLE blob, so a database
-- whose refresh has not run yet over-masks. The search-index build calls the refresh
-- inside the build transaction (Step 4), which is the point at which a corpus
-- exists.
DO $$
DECLARE
  v_count integer;
BEGIN
  SELECT count(*) INTO v_count FROM retrieval.sensitive_literals();
  IF v_count = 0 THEN
    RAISE NOTICE
      'no restricted literals in the corpus yet (pre-seed); retrieval.mask_blob '
      'stays at its whole-blob default and the search-index build will refresh it';
  ELSE
    PERFORM retrieval.refresh_mask_blob();
    RAISE NOTICE 'retrieval.mask_blob regenerated from % literals', v_count;
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 3. Masking policies, bound to persona_auditor only.
-- ---------------------------------------------------------------------------
```

Then append the branch measured in Step 1.

**Branch A** (a drop procedure exists — substitute the exact name and argument
list measured in Step 1 for `pgcolumnmask.drop_masking_policy(name)`):

```sql
DO $$
DECLARE
  v_policy text;
BEGIN
  FOREACH v_policy IN ARRAY ARRAY['mask_support_cases','mask_documents','mask_chunks']
  LOOP
    BEGIN
      CALL pgcolumnmask.drop_masking_policy(v_policy);
    EXCEPTION
      WHEN undefined_object OR no_data_found THEN
        NULL;  -- first run: nothing to drop
    END;
  END LOOP;
END
$$;

CALL pgcolumnmask.create_masking_policy(
  'mask_support_cases',
  'casework.support_cases',
  jsonb_build_object(
    'account_name',        'pgcolumnmask.mask_text(account_name)',
    'description',         'casework.mask_redact(description)',
    'customer_commitment', 'casework.mask_redact(customer_commitment)'
  ),
  ARRAY['persona_auditor']::name[],
  100
);

CALL pgcolumnmask.create_masking_policy(
  'mask_documents',
  'retrieval.documents',
  jsonb_build_object('account_name', 'pgcolumnmask.mask_text(account_name)'),
  ARRAY['persona_auditor']::name[],
  100
);

CALL pgcolumnmask.create_masking_policy(
  'mask_chunks',
  'retrieval.chunks',
  jsonb_build_object(
    'account_name', 'pgcolumnmask.mask_text(account_name)',
    'chunk_text',   'retrieval.mask_blob(chunk_text)'
  ),
  ARRAY['persona_auditor']::name[],
  100
);
```

**Branch B** (no drop procedure — substitute the catalog relation and its column
names measured in Step 1 for `pgcolumnmask.masking_policies(policy_name)`):

```sql
DO $$
DECLARE
  v_existing integer;
BEGIN
  SELECT count(*) INTO v_existing
    FROM pgcolumnmask.masking_policies
   WHERE policy_name IN ('mask_support_cases','mask_documents','mask_chunks');

  IF v_existing > 0 THEN
    RAISE EXCEPTION
      'masking policies already exist (% found) and this extension build offers no '
      'drop procedure. Remove them as the policy admin before re-running '
      'sql/12_masking.sql; silently keeping a stale policy could leave a column '
      'unmasked.', v_existing;
  END IF;
END
$$;
```

followed by the same three `CALL pgcolumnmask.create_masking_policy(...)`
statements shown in Branch A.

Whether a `CALL` or `SELECT` is correct depends on whether Step 1 reports these as
procedures or functions. Use whichever the measured `pg_proc` rows require; if they
are functions, wrap each in `PERFORM`/`SELECT` instead of `CALL`.

- [ ] **Step 3: Add the file to `make schema`**

Append `sql/12_masking.sql` after `sql/11_roles_rls.sql` in the `Makefile`
`SQL_FILES` list (Task 5 Step 4 left `11_` last).

- [ ] **Step 4: Call the refresh after the search index build**

The blob literals come from casework, but the blob itself is rebuilt by the index
build. A rebuilt `chunk_text` with a stale `mask_blob` body is still safe (the
literals did not change), but a *new* restricted row admitted through
`casework.admit_evidence` adds a literal the baked body does not know.

In `backend/app/search_index.py`, at the end of the build transaction — the same
transaction that flips `is_current` — add:

```python
        cursor.execute("SELECT retrieval.refresh_mask_blob()")
```

Find the statement that marks the build `ready` (search for `index_state` set to
`'ready'`) and place the refresh immediately after it, inside the same `with
conn.transaction()` block, so a failed refresh rolls the build back rather than
publishing an index whose blob mask is behind the corpus.

- [ ] **Step 5: Verify masking behaviourally on a disposable database**

Extend the Task 5 scratch script: after applying `sql/11` and `sql/12`, seed the
scratch database (`make seed-local` against the scratch DSN) and run:

```sql
BEGIN;
SET LOCAL ROLE persona_admin;
SELECT case_id, account_name, left(customer_commitment, 24) AS commitment
  FROM casework.support_cases WHERE case_id = 'CASE-7421';
ROLLBACK;

BEGIN;
SET LOCAL ROLE persona_auditor;
SELECT case_id, account_name, left(customer_commitment, 24) AS commitment
  FROM casework.support_cases WHERE case_id = 'CASE-7421';
ROLLBACK;
```

Expected: the admin row shows `Northstar Foods (fictional)` and
`Support leadership approv`; the auditor row shows an `X`-run of the same length
for `account_name` and `[REDACTED]` for the commitment, with `case_id` identical in
both — the row is present, the identity is not.

- [ ] **Step 6: Run G-29**

Run: `gates/checks.sh G-29`

Against live (nothing applied yet) this still reports BLOCKED on missing roles.
Against the scratch database — with `DATABASE_URL` pointed at it inline — it must
report PASS on all four assertion groups, including the corpus-wide leak scan.
Record the gate's own output; do not summarize it.

- [ ] **Step 7: Commit**

```bash
git add sql/12_masking.sql Makefile backend/app/search_index.py
git commit -m "Mask customer identity for the auditor persona"
```

---

## Task 7: Persona-required connection checkout (`backend/app/db.py`)

The enforcement point in Python. After this task it is **impossible to reach the
database from request code without naming a persona**, because the parameter is
positional and required — a forgotten persona is a `TypeError` at import/call time,
not a silent full-privilege read.

**Files:**
- Modify: `backend/app/db.py:29-102`
- Modify: `backend/app/config.py:49-70` (one new setting)
- Test: `backend/tests/test_db_persona.py` (create)

**Interfaces:**
- Consumes: `sql/11_roles_rls.sql` roles; `WORKSHOP_APP_DATABASE_URL` from Task 5.
- Produces:
  - `PERSONAS: tuple[str, ...] = ("analyst", "admin", "auditor")`
  - `Persona = Literal["analyst", "admin", "auditor"]`
  - `persona_role(persona: str) -> str` → `"persona_analyst"` etc.
  - `get_conn(persona: Persona, *, row_factory=None)` — context manager yielding a
    connection inside an open transaction with `SET LOCAL ROLE` already issued
  - `get_dict_conn(persona: Persona)` — same, `dict_row`
  - `get_owner_conn(*, row_factory=None)` — the un-personified checkout, for the
    index build and bootstrap scripts only
  - `settings.workshop_app_database_url`

**Why the persona checkout must own the transaction:** `SET LOCAL` is discarded at
transaction end, and the pool runs `autocommit=True` (`db.py:26`), where every bare
statement is its own transaction. Issuing `SET LOCAL ROLE` on an autocommit
connection would set the role for the duration of *that statement only* and the
next `SELECT` would run as `workshop_app` — which now raises permission denied.
So the persona checkout opens `conn.transaction()` itself and yields inside it.

**Consequence for callers (this is the part that breaks existing code):** two
`get_dict_conn()` sites already open `with connection.transaction():` themselves
(`backend/app/search.py:654,647`). psycopg treats a nested `transaction()` as a
SAVEPOINT, which is correct and harmless — the inner block commits to the outer,
the outer commits at checkout exit. Leave those blocks alone.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_db_persona.py`:

**This repo has no pytest.** All ten existing test files are `unittest.TestCase`
subclasses, `backend/requirements.txt` lists no pytest, `.venv/bin/` has no pytest
binary, and `make test` runs `python -m unittest discover -s backend/tests`. Write
`unittest`, not pytest: a module-level `def test_*()` is **invisible** to unittest
discovery, so a pytest-style file would silently never run — the worst possible
failure mode for a security test. Do not add pytest to `requirements.txt`; it is a
new dependency on a public workshop repo for zero gain.

```python
"""The persona contract on the connection checkout.

These tests need a live database because the whole point is that Postgres, not
Python, is the enforcement point. They are skipped without TEST_DATABASE_URL,
matching backend/tests/test_retrieval_integration.py.
"""

from __future__ import annotations

import os
import unittest

from backend.app import db


@unittest.skipUnless(
    os.environ.get("TEST_DATABASE_URL"),
    "set TEST_DATABASE_URL for the persona checkout contract",
)
class PersonaCheckoutTests(unittest.TestCase):
    def test_personas_are_the_three_bound_values(self) -> None:
        self.assertEqual(db.PERSONAS, ("analyst", "admin", "auditor"))

    def test_persona_role_prefixes_the_database_role(self) -> None:
        self.assertEqual(db.persona_role("analyst"), "persona_analyst")
        self.assertEqual(db.persona_role("admin"), "persona_admin")
        self.assertEqual(db.persona_role("auditor"), "persona_auditor")

    def test_persona_role_rejects_an_unknown_persona(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown persona"):
            db.persona_role("support-lead")

    def test_get_conn_requires_a_persona(self) -> None:
        with self.assertRaises(TypeError):
            with db.get_conn():  # type: ignore[call-arg]
                pass

    def test_checkout_runs_as_the_persona_not_the_login(self) -> None:
        with db.get_dict_conn("analyst") as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_user AS role")
                self.assertEqual(cursor.fetchone()["role"], "persona_analyst")

    def test_role_does_not_leak_to_the_next_checkout(self) -> None:
        with db.get_dict_conn("admin") as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_user AS role")
                self.assertEqual(cursor.fetchone()["role"], "persona_admin")

        with db.get_dict_conn("auditor") as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_user AS role")
                self.assertEqual(cursor.fetchone()["role"], "persona_auditor")

    def test_owner_checkout_is_not_a_persona(self) -> None:
        with db.get_owner_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_user AS role")
                self.assertNotIn(
                    cursor.fetchone()[0],
                    {"persona_analyst", "persona_admin", "persona_auditor"},
                )
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
TEST_DATABASE_URL="postgresql://localhost:55432/retrieval_test?sslmode=disable" \
  DATABASE_URL="postgresql://localhost:55432/retrieval_test?sslmode=disable" \
  .venv/bin/python -m unittest backend.tests.test_db_persona -v
```
`DATABASE_URL` is set alongside it because `db.py` reads `DATABASE_URL`, never
`TEST_DATABASE_URL` — the trap recorded in Global Constraints.

Expected: FAIL — `AttributeError: module 'backend.app.db' has no attribute
'PERSONAS'`.

- [ ] **Step 3: Add the app-login setting**

In `backend/app/config.py`, immediately after the `database_url` field
(`:50-52`), add:

```python
    workshop_app_database_url: str = Field(
        default_factory=lambda: os.environ.get("WORKSHOP_APP_DATABASE_URL", "")
    )
```

Match the surrounding fields' `default_factory` idiom exactly — read the existing
`database_url` field and copy its style rather than introducing a second pattern.

- [ ] **Step 4: Rewrite the checkout API**

Replace `backend/app/db.py:29-102` with:

```python
PERSONAS: tuple[str, ...] = ("analyst", "admin", "auditor")
Persona = Literal["analyst", "admin", "auditor"]

_DEFAULT_PERSONA: Persona = "analyst"


def persona_role(persona: str) -> str:
    """Map a persona name to its database role.

    Args:
        persona: One of PERSONAS.

    Returns:
        The role name to SET LOCAL ROLE to.

    Raises:
        ValueError: The persona is not one of the three bound values. Raised
            rather than defaulted: guessing an identity is how a fail-open bug
            gets shipped.
    """
    if persona not in PERSONAS:
        raise ValueError(
            f"unknown persona {persona!r}; expected one of {', '.join(PERSONAS)}"
        )
    return f"persona_{persona}"


def _pool_conninfo() -> str:
    """The DSN the request pool connects with.

    Prefers WORKSHOP_APP_DATABASE_URL (workshop_app, which holds no clearance) and
    falls back to DATABASE_URL so a local developer with one DSN still runs. The
    fallback is logged at WARNING because under it row filtering does not hold: the
    bootstrap identity is granted can_see_restricted by sql/11 so that the seed and
    the index build can project the whole corpus, and the clearance disjunct in every
    policy is therefore true for it on every row.
    """
    settings = get_settings()
    if settings.workshop_app_database_url:
        return settings.workshop_app_database_url
    if not settings.database_url:
        raise RuntimeError(
            "Neither WORKSHOP_APP_DATABASE_URL nor DATABASE_URL is set. For local "
            "development use postgresql://localhost:55432/retrieval?sslmode=disable"
        )
    logger.warning(
        "WORKSHOP_APP_DATABASE_URL is not set; the request pool is falling back to "
        "DATABASE_URL. That identity holds can_see_restricted, so every RLS policy's "
        "clearance disjunct is true for it and persona row filtering is not enforced."
    )
    return settings.database_url


def _build_pool() -> ConnectionPool:
    settings = get_settings()
    pool = ConnectionPool(
        conninfo=_pool_conninfo(),
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        max_idle=settings.db_pool_max_idle_seconds,
        kwargs={"connect_timeout": settings.database_connect_timeout_seconds},
        configure=_configure_connection,
        open=False,
        name="workbench-pg",
    )
    return pool


def get_pool() -> ConnectionPool:
    """Return the process-wide connection pool, opening it on first use.

    open_pool() during app startup is the normal path; this lazy fallback keeps
    scripts and tests that touch the DB without a FastAPI lifespan working.
    """
    global _pool
    if _pool is None:
        _pool = _build_pool()
    if _pool.closed:
        _pool.open()
    return _pool


def open_pool() -> None:
    """Open the pool and block until min_size connections are established."""
    pool = get_pool()
    pool.wait(timeout=get_settings().database_connect_timeout_seconds)
    logger.info(
        "Opened Postgres pool (min=%s max=%s)",
        get_settings().db_pool_min_size,
        get_settings().db_pool_max_size,
    )


def close_pool() -> None:
    """Close the pool and drain its connections. Safe to call more than once."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_conn(persona: Persona, *, row_factory=None) -> Iterator[psycopg.Connection]:
    """Check out a connection running as `persona` for the `with` block.

    The persona is positional and required. A caller that forgets it raises
    TypeError here rather than reaching the database as workshop_app, which holds
    no read-path grants and would raise permission denied at the first SELECT.

    The checkout owns a transaction because SET LOCAL is transaction-scoped: the
    pool is autocommit, so outside an explicit transaction the role would apply to
    the SET statement alone. Callers may still open their own nested
    `conn.transaction()` — psycopg maps that to a SAVEPOINT.

    Args:
        persona: One of PERSONAS. Selects the database role.
        row_factory: Applied per checkout so a dict_row caller does not mutate the
            pooled connection's default for the next borrower.

    Yields:
        A pooled connection inside an open transaction, running as the persona.
    """
    role = persona_role(persona)
    pool = get_pool()
    with pool.connection() as conn:
        if row_factory is not None:
            conn.row_factory = row_factory
        try:
            with conn.transaction():
                with conn.cursor() as cursor:
                    # sql.Identifier, not an f-string: the role name is derived from
                    # a validated persona, but SET ROLE takes no parameter markers
                    # and this is the one place a literal would be interpolated.
                    cursor.execute(
                        psycopg.sql.SQL("SET LOCAL ROLE {}").format(
                            psycopg.sql.Identifier(role)
                        )
                    )
                yield conn
        finally:
            if row_factory is not None:
                conn.row_factory = tuple_row


def get_dict_conn(persona: Persona):
    return get_conn(persona, row_factory=dict_row)


@contextmanager
def get_owner_conn(*, row_factory=None) -> Iterator[psycopg.Connection]:
    """Check out a connection with NO persona, for owner-privileged work.

    The search index build writes retrieval.* and the bootstrap scripts run DDL;
    neither is a persona operation. Named distinctly so a request-path caller
    cannot reach it by leaving an argument off get_conn().

    Connects with DATABASE_URL (the owner DSN) rather than the pool's app login,
    because the pool identity deliberately holds no write grants on retrieval.*.
    """
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set; owner operations need it")
    with psycopg.connect(
        settings.database_url,
        autocommit=True,
        connect_timeout=settings.database_connect_timeout_seconds,
    ) as conn:
        if row_factory is not None:
            conn.row_factory = row_factory
        yield conn
```

Add `Literal` to the `typing` import on line 5 and import `psycopg.sql`:

```python
from typing import Iterator, Literal

import psycopg
from psycopg import sql as pgsql
```

and use `pgsql.SQL` / `pgsql.Identifier` in the body rather than
`psycopg.sql.*`, matching how the rest of the codebase imports submodules. Keep
one style; do not mix.

- [ ] **Step 5: Run the test to verify it passes**

Run:
```bash
TEST_DATABASE_URL="postgresql://localhost:55432/retrieval_test?sslmode=disable" \
  DATABASE_URL="postgresql://localhost:55432/retrieval_test?sslmode=disable" \
  .venv/bin/python -m unittest backend.tests.test_db_persona -v
```
Expected: `Ran 7 tests … OK`. If `test_checkout_runs_as_the_persona_not_the_login`
fails with `permission denied to set role "persona_analyst"`, the test database has
not had `sql/11_roles_rls.sql` applied — apply it to the test database (not live)
and re-run.

- [ ] **Step 6: Point the bootstrap scripts at the owner checkout**

Four scripts use the raw no-arg `get_conn()`. They are owner operations and must
not acquire a persona. Change each import and call:

- `backend/scripts/check_postgres.py:24`
- `backend/scripts/run_sql.py:14`
- `backend/scripts/check_pgvector.py:25`
- `backend/scripts/build_search_index.py:140`

In each file replace `get_conn` with `get_owner_conn` in both the `from
backend.app.db import ...` line and the `with ... as conn:` call. `get_owner_conn`
takes no positional argument, so the call sites need no other change.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db.py backend/app/config.py backend/tests/test_db_persona.py \
        backend/scripts/check_postgres.py backend/scripts/run_sql.py \
        backend/scripts/check_pgvector.py backend/scripts/build_search_index.py
git commit -m "Require a persona on every request-path connection checkout"
```

Note: after this commit the app does **not** run — the 37 request-path
`get_dict_conn()` call sites are still no-arg. Task 10 threads the persona through
them. (Measured: `grep -rc 'get_dict_conn()' backend --include="*.py"` gives 40
total — minus the definition in `db.py` and the two script callers in
`smoke_test.py` and `doctor.py`, which Task 13 converts, leaving
`evaluation.py` 5, `agent.py` 15, `contracts.py` 1, `search.py` 5,
`insights.py` 10, `main.py` 1.) This is a deliberate two-commit split: the enforcement point lands with its
own tests, then the callers are updated mechanically.

---

## Task 8: Purge the remaining `verity` identifiers

Sequenced here, before the frontend persona work, because Tasks 10 and 11 edit the
same file this task renames. Doing it after would mean editing `VerityApp.tsx` and
then renaming it, producing a diff no reviewer can read.

**Scope, measured (not estimated).** `git ls-files | grep -i verity` returns 82
tracked paths, of which **80 are under `design/`** — a design archive with its own
internal build chain (`design/verity/ui/build.py` writes
`design/verity/ui/verity-workbench.html`, `manifest.json` names the package
`verity-codex-final-package`, `verify_contract_parity.py` reads the generated
model). The two live application files are `frontend/src/VerityApp.tsx` and
`frontend/src/verity.css`.

**`\bverity` — the mandatory grep anchor.** `verity` is a substring of `severity`,
which is a real column on `casework.incidents:70`, `casework.support_cases:101`,
`retrieval.documents:906`, `retrieval.chunks:970` and a field on
`frontend/src/VerityApp.tsx:208`. An unanchored `s/verity/workbench/` corrupts
`severity` into `sworkbenchy` across the schema. **Every command in this task uses
`\bverity` or an explicit token list. Never a bare substring.**

**Files:**
- Rename: `frontend/src/VerityApp.tsx` → `frontend/src/WorkbenchApp.tsx`
- Rename: `frontend/src/verity.css` → `frontend/src/workbench.css`
- Modify: `frontend/src/main.tsx:3-8`
- Modify: `gates/noun_lint.py:14` (docstring path) and its SCAN_ROOTS / denylist
- Modify: `design/SPEC-session.md` and `design/verity-handoff/docs/SPEC-session.md`
  (3 machine tokens; both copies stay byte-identical)

**Interfaces:**
- Produces: `WorkbenchApp` default export; the `WorkbenchMark` component (renamed
  from `VerityMark`, defined at `VerityApp.tsx:1107`, used at `:4150`, `:4309`,
  `:4481` — Tasks 11 and 12 reference it by the new name); CSS classes `workbench-shell`,
  `workbench-footer`, `workbench-home`, `workbench-mark`, `workbench-mark-frame`,
  `workbench-mark-thread`, `workbench-mark-source`, `workbench-mark-answer`,
  `workbench-mark-check`; localStorage key `workbench-nav-collapsed`.

- [ ] **Step 1: Record the pre-state so the rename is auditable**

```bash
git ls-files | grep -i verity | wc -l
grep -rn '\bverity' --include="*.ts" --include="*.tsx" --include="*.css" \
  frontend/src | wc -l
grep -rc '\bverity' --include="*.ts" --include="*.tsx" --include="*.css" frontend/src
grep -rohi '\bverity[a-zA-Z0-9_-]*' frontend/src | sort | uniq -c | sort -rn
```

Expected: 82 tracked paths; **37** lowercase-anchored frontend hits, distributed
`frontend/src/verity.css` 23, `frontend/src/VerityApp.tsx` 13,
`frontend/src/main.tsx` 1; and this exact **case-insensitive** token census —
`verity-shell` 10, `verity-footer` 6, `VerityMark` 4, `VerityApp` 4,
`verity-mark-source` 4, `verity-mark` 4, `verity-nav-collapsed` 2,
`verity-mark-thread` 2, `verity-mark-frame` 2, `verity-mark-check` 2,
`verity-mark-answer` 2, `verity-home` 2, bare `verity` **1** (the
`import './verity.css'` line in `main.tsx`; `verity.css` has **no** header
comment — it opens directly on `:root {`, so there is no filename self-reference
inside it to rewrite).

The census must be taken **case-insensitively**. A lowercase-only `\bverity` scan
cannot see `VerityMark` (4 sites) or `VerityApp` (4 sites), and the user's
instruction is "no more Verity references anywhere" — identifiers included. If the
census differs, Codex has landed further UI edits — re-derive it and use the
measured set; do not proceed against a stale list.

- [ ] **Step 2: Rename the two files with git mv**

```bash
git mv frontend/src/VerityApp.tsx frontend/src/WorkbenchApp.tsx
git mv frontend/src/verity.css frontend/src/workbench.css
```

`git mv` (not `mv`) so the rename is recorded and `git log --follow` still works.

- [ ] **Step 3: Rewrite the identifiers inside the three frontend files**

The `-i ''` form is required on macOS (BSD sed); GNU sed takes bare `-i`.

```bash
sed -i '' -E 's/\bverity-(shell|footer|home|mark-frame|mark-thread|mark-source|mark-answer|mark-check|mark|nav-collapsed)\b/workbench-\1/g' \
  frontend/src/WorkbenchApp.tsx frontend/src/workbench.css
sed -i '' -E -e 's/\bVerityApp\b/WorkbenchApp/g' \
             -e 's/\bVerityMark\b/WorkbenchMark/g' \
             -e "s|import './verity\.css'|import './workbench.css'|" \
  frontend/src/WorkbenchApp.tsx frontend/src/main.tsx
```

Two things make this safe and complete:

**The kebab alternation is ordered longest-first** (`mark-frame` before `mark`)
because sed alternation is leftmost-first, not longest-match: with `mark` first,
`verity-mark-frame` would become `workbench-mark-frame` only by luck of the `\b`
boundary — do not rely on it, keep the order.

**The PascalCase pass is case-sensitive on purpose.** `Severity` contains the
substring `verity` but not `Verity` (capital V), so `\bVerityApp\b` and
`\bVerityMark\b` cannot corrupt the `severity` column. `VerityMark` is the
component defined at `VerityApp.tsx:1107` and used at `:4150`, `:4309`, `:4481` —
4 sites the kebab pass and a lowercase-only grep both miss entirely. `VerityApp`
covers the default export at `:3123` plus `main.tsx:3` (twice, both the binding
and the module path) and `main.tsx:8`.

There is no separate `workbench.css` self-reference to rewrite: the stylesheet has
no header comment, and a `grep -n -E '\bverity([^-a-zA-Z0-9_]|$)'
frontend/src/verity.css` returns nothing.

- [ ] **Step 4: Verify zero `verity` in any case remains in the app, and `severity` is intact**

```bash
grep -rni '\bverity' frontend/src backend seed sql gates admission scripts \
  mcp-server/src lambda_mcp 2>/dev/null
grep -rn 'sworkbenchy\|sWorkbenchy' . --include="*.py" --include="*.sql" \
  --include="*.ts" --include="*.tsx" 2>/dev/null | grep -v node_modules
grep -c 'severity' frontend/src/WorkbenchApp.tsx sql/01_schema.sql
```

The first grep is `-i`. A lowercase-only scan here is the exact failure mode that
lets `VerityMark` survive a "purge" and still report success — the task would
false-pass against the standing instruction "no more Verity references anywhere."

Expected: the first two commands print **nothing** (`grep` exits 1); the third
prints a nonzero count for both files — `severity` survived. The path list
deliberately omits `guide` (no such directory in this repo; guide content lives in
the sibling Workshop Studio repo — see Task 14) and `design/` (the design archive
keeps its `verity-*` asset names by decision).

If `sworkbenchy` appears anywhere, revert with `git checkout -- <file>` and redo
Step 3 with the anchored patterns.

- [ ] **Step 5: Typecheck and build**

```bash
cd frontend && npx tsc --noEmit && npx vite build && cd ..
```

Expected: `tsc` silent, `vite build` reports `✓ built in …`. A `Cannot find module
'./VerityApp'` means Step 3's `main.tsx` edit did not apply — check that file by
hand.

- [ ] **Step 6: Extend G-11 with the banned identity tokens (A7)**

`gates/noun_lint.py` is an ID denylist scanner keyed on evidence IDs, so
`support-lead` and `principal` are a **structural** addition, not new dict entries:
they are identity vocabulary, and `principal` legitimately appears inside
`acl_principals` and `pg_has_role`-adjacent prose. Add a second, separately-anchored
scan.

After `ROUND_NUMBER_RE` (`gates/noun_lint.py:124-126`) insert:

```python
# A7 vocabulary collapse: one identity axis, the persona. These tokens named the
# retired second axis. Anchored so acl_principals / p_principal / pg_has_role and
# the RLS predicate's own text are not hits: only the bare participant-facing
# nouns are banned.
BANNED_IDENTITY_RE = re.compile(
    r"(?<![\w.\-])(?:support-lead|support_lead)(?![\w\-])"
    r"|(?<![\w.\-_])principal(?![\w\-_])"
)

# Lines that legitimately carry a banned token: the RLS/ACL predicate path keeps
# acl_principals and the p_principal parameter until the wire rename lands, and
# this gate's own source names the tokens it bans.
BANNED_IDENTITY_ALLOW = re.compile(
    r"acl_principals|p_principal|BANNED_IDENTITY|required_principals"
)
```

and in `_scan_line`, before `return hits`:

```python
    if BANNED_IDENTITY_RE.search(line) and not BANNED_IDENTITY_ALLOW.search(line):
        token = BANNED_IDENTITY_RE.search(line).group(0)
        hits.append((token, "the persona (analyst/admin/auditor); A7 retired this"))
```

Fix the stale docstring path at `gates/noun_lint.py:14` in the same edit:
`design/verity/fixtures/id-migration.json` still exists (it is in the design
archive, which this task does not rename), so **leave that path as written** —
confirm with `ls design/verity/fixtures/id-migration.json` and only change it if
the file has moved.

- [ ] **Step 7: Run G-11 and expect it to FAIL, listing the work Tasks 9-12 do**

Run: `gates/checks.sh G-11`

Expected: FAIL. The hits are the real remaining `principal` / `support-lead`
surface — `backend/app/models.py:21,49,77,87,92,116`,
`backend/app/agent_tools.py:59,79-104`, `frontend/src/route.ts:21,45-48,67-72`,
`frontend/src/WorkbenchApp.tsx` (the `supportLead` control and `principalLabel`),
`backend/scripts/doctor.py`, `backend/scripts/smoke_test.py`. Save the list; it is
the checklist Tasks 9-12 work through. **A failing G-11 at this point is the
expected state**, not a defect: the gate now measures the vocabulary collapse that
has not happened yet.

- [ ] **Step 8: Sync the three machine tokens in both SPEC copies**

`design/SPEC-session.md` and `design/verity-handoff/docs/SPEC-session.md` must stay
byte-identical. Three live machine tokens remain (`/etc/verity/env`,
`PGDATABASE=verity`, `/var/log/verity-bootstrap.log` + `/var/lib/verity/stage`,
`verity-schemas`, `verity-loadgen-*`); the rest of the `verity` hits in those files
name design *assets* (`verity-scale.html`, `verity-ui-design-system.md`) that still
exist under that name and must not be renamed.

```bash
for f in design/SPEC-session.md design/verity-handoff/docs/SPEC-session.md; do
  sed -i '' -e 's|/etc/verity/env|/etc/workbench/env|g' \
           -e 's|PGDATABASE=verity\b|PGDATABASE=workbench|g' \
           -e 's|/var/log/verity-bootstrap\.log|/var/log/workbench-bootstrap.log|g' \
           -e 's|/var/lib/verity/stage|/var/lib/workbench/stage|g' \
           -e 's|\bverity-schemas\b|workbench-schemas|g' \
           -e 's|\bverity-loadgen|workbench-loadgen|g' \
           -e 's|\bverity-session/|workbench-session/|g' \
           -e 's|\bverity-mcp\b|workbench-mcp|g' "$f"
done
diff design/SPEC-session.md design/verity-handoff/docs/SPEC-session.md && \
  echo "SPEC copies byte-identical"
grep -n '\bverity' design/SPEC-session.md
```

Expected: `diff` silent, the echo prints; the final `grep` shows **only**
`verity-ui-design-system.md` (line 6), `verity-scale.html` (line 827), and the
concept-screen references — asset filenames, which are correct as-is.

`/etc/workbench/env` and `PGDATABASE=workbench` are consumed by the **sibling**
Workshop Studio repo's bootstrap. This edit changes the contract those scripts
implement; record it in the task report as a sibling-repo coupling that must land
before the next bootstrap run.

- [ ] **Step 9: Run the full gate suite and the tests**

```bash
gates/checks.sh
.venv/bin/python -m unittest discover -s backend/tests -q
```

Expected: G-11 FAIL (Step 7, expected), G-23 route contract PASS (the router file
is untouched by this task), everything else unchanged from before. Tests: the same
pass count as the pre-task baseline — this task renames identifiers no test
imports. Record both outputs.

- [ ] **Step 10: Commit**

```bash
git add -A frontend/src gates/noun_lint.py design/SPEC-session.md \
        design/verity-handoff/docs/SPEC-session.md
git commit -m "Rename remaining verity identifiers to workbench"
```

---

## Task 9: Collapse the SQL identity vocabulary to one axis (A7)

A7 deletes the second identity axis. Today `retrieval.acl_visible(p_acl,
p_principal)` takes a caller-supplied jsonb bag with `scopes` and `principals`;
after this task the predicate reads **the database role**, so the app cannot claim
an identity it does not hold, and the predicate the participant writes by hand in
Lab 3 H2 is the same expression the RLS policy enforces.

**The shape (this is the whole task in one line):**

```sql
-- before: caller asserts its identity
retrieval.acl_visible(d.acl, p_principal)          -- p_principal jsonb from the wire
-- after: the engine already knows the identity
retrieval.acl_visible(d.acl)                       -- defaults to current_user
retrieval.acl_visible(item.acl, run.role::name)    -- replay, under the stored role
```

**Files:**
- Modify: `sql/03_search_functions.sql:1-59` (both predicates), `:220-233`,
  `:300,339,372`, `:445-458`, `:497-500`, `:556-570`, `:618-621`, `:700-715`,
  `:774,826,858`
- Modify: `sql/09_traverse_evidence.sql:6,36,61`
- Modify: `sql/05_evaluation.sql:19,115,168`
- Modify: `sql/01_schema.sql` (`proof.retrieval_runs.principal:1268`,
  `proof.agent_runs.principal:1367`)
- Modify: `sql/04_diagnostics.sql:382` (`proof.v_run_receipts` projects
  `run.principal`; the column ceases to exist in Step 4)
- Modify: `sql/11_roles_rls.sql` (grants on the renamed functions)

**Interfaces:**
- Produces:
  - `retrieval.acl_visible(p_acl jsonb, p_role name DEFAULT current_user) → boolean`, STABLE
  - `retrieval.acl_scalars_visible(p_visibility text, p_role name DEFAULT current_user) → boolean`, STABLE
  - all four arm functions with `p_principal jsonb` **removed**
  - `retrieval.traverse_evidence(uuid[], integer, p_role name DEFAULT current_user)`
  - `proof.retrieval_runs.role text NOT NULL DEFAULT 'analyst'`,
    `proof.agent_runs.role text NOT NULL DEFAULT 'analyst'`

**Why `DROP FUNCTION` is mandatory, not optional:** `CREATE OR REPLACE FUNCTION`
matches on the argument list. Removing `p_principal jsonb` creates a **second
overload** rather than replacing the first, and the old one keeps running with its
fail-open jsonb semantics — a caller that still passes `p_principal` would silently
get the old, weaker predicate. Every changed signature gets an explicit
`DROP FUNCTION IF EXISTS ... (exact old arg list)` immediately before its
`CREATE`, and Step 6 asserts the old overloads are gone.

**`principals` disappears entirely.** Blocker 1 resolved to option (a):
`RESTRICTED_ACL` becomes `{"visibility": "restricted", "principals": []}`, so
`acl->>'visibility'` is the real classification and the `principals` array is
always empty. `acl_scalars_visible`'s `p_required_principals text[]` parameter and
the `acl_principals` column reads in the predicate therefore have nothing left to
test. The **columns** `acl_principals` and their GIN indexes
(`sql/02_indexes.sql:67-68,119-120`) stay: they are populated by the projection
(`backend/app/search_index.py:521-525`) and dropping them is schema churn outside
this task's scope. They simply stop being read by the predicate. Record that in
the task report as deliberate, so a reviewer does not read the unused column as an
oversight.

- [ ] **Step 1: Rewrite both predicates in `sql/03_search_functions.sql`**

Replace lines 1-59 (both `CREATE OR REPLACE FUNCTION` blocks, through the second
`$$;`) with:

```sql
-- One identity axis: the database role (A7). The predicate reads the role rather
-- than a caller-supplied identity bag, so the app cannot assert an identity it
-- does not hold — the strongest form of "the engine is the enforcement point."
--
-- This expression is byte-identical to the USING clause of the three RLS policies
-- in sql/11_roles_rls.sql and to the predicate participants write by hand in Lab 3.
-- Three copies of one expression is deliberate: the arms keep an explicit,
-- readable filter (so the ACL is visible in the SQL a participant reads), RLS
-- enforces it even when a query forgets, and the hand-written version is the
-- exercise. If you change one, change all three.
--
-- STABLE, not IMMUTABLE: pg_has_role is STABLE, and an IMMUTABLE label would let
-- the planner fold a result that is only valid for one role.
DROP FUNCTION IF EXISTS retrieval.acl_visible(jsonb, jsonb);

CREATE OR REPLACE FUNCTION retrieval.acl_visible(
  p_acl jsonb,
  p_role name DEFAULT current_user
)
RETURNS boolean
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
  SELECT coalesce(p_acl ->> 'visibility', 'restricted') = 'workshop'
    OR pg_has_role(p_role, 'can_see_restricted', 'USAGE')
$$;

COMMENT ON FUNCTION retrieval.acl_visible(jsonb, name) IS
  'Visibility of one evidence ACL to one role. p_role defaults to current_user; '
  'replay passes the run''s stored role explicitly. USAGE not MEMBER: MEMBER '
  'ignores INHERIT and would report a clearance the effective role does not have.';

-- The scalar twin, for the projected retrieval.* tables that carry acl_visibility
-- as a column instead of the jsonb. p_required_principals is gone: after the
-- Blocker-1 resolution acl.principals is always empty and visibility is the only
-- classification axis.
DROP FUNCTION IF EXISTS retrieval.acl_scalars_visible(text, text[], jsonb);

CREATE OR REPLACE FUNCTION retrieval.acl_scalars_visible(
  p_visibility text,
  p_role name DEFAULT current_user
)
RETURNS boolean
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
  SELECT coalesce(p_visibility, 'restricted') = 'workshop'
    OR pg_has_role(p_role, 'can_see_restricted', 'USAGE')
$$;
```

Note the semantic change beyond the signature: the old predicate treated
`visibility = 'public'` as universally visible and matched `visibility` against the
caller's `scopes` array. Neither survives. `'public'` was never seeded (the only
values are `workshop` and, after the reseed, `restricted`), and `scopes` was the
second axis A7 deletes. **Verify before you rely on that claim:**

```bash
grep -rn "'public'" seed/corpus.py sql/*.sql | grep -i "visib"
```
Expected: no output. If `'public'` appears as a seeded visibility, stop and report
— the predicate rewrite would change which rows are visible.

- [ ] **Step 2: Drop `p_principal` from the four arm functions**

In `sql/03_search_functions.sql`, for each of the four arms:

1. `retrieval.full_text_search` — delete `  p_principal jsonb DEFAULT NULL,` at
   `:233`; change the three call sites `:300,339,372` from
   `retrieval.acl_visible(d.acl, p_principal)` to `retrieval.acl_visible(d.acl)`.
2. `retrieval.vector_search` — delete `  p_principal jsonb DEFAULT NULL,` at
   `:458`; replace the call at `:497-500`:
   ```sql
       AND retrieval.acl_scalars_visible(c.acl_visibility)
   ```
   (was a three-argument call spanning `:497-500` — delete the
   `c.acl_principals,` and `p_principal` argument lines).
3. `retrieval.fuzzy_search` — delete `  p_principal jsonb DEFAULT NULL,` at
   `:570`; replace `:618-621` with
   `    AND retrieval.acl_scalars_visible(d.acl_visibility)`.
4. `retrieval.hybrid_search` — delete `  p_principal jsonb DEFAULT NULL,` at
   `:715`; delete the three `    p_principal,` argument lines at `:774,826,858`
   where it forwards to the arms.

Prepend a `DROP FUNCTION IF EXISTS` for each old signature, immediately before its
`CREATE OR REPLACE`. The exact old argument lists (measured, not retyped from
memory):

```sql
DROP FUNCTION IF EXISTS retrieval.full_text_search(
  text, text[], text, text, text, text[], text, text, text, text,
  timestamptz, timestamptz, jsonb, integer
);

DROP FUNCTION IF EXISTS retrieval.vector_search(
  vector(1024), text[], text, text, text, text[], text, text, text, text,
  timestamptz, timestamptz, jsonb, integer, integer
);

DROP FUNCTION IF EXISTS retrieval.fuzzy_search(
  text[], real, text[], text, text, text, text[], text, text, text, text,
  timestamptz, timestamptz, jsonb, integer
);

DROP FUNCTION IF EXISTS retrieval.hybrid_search(
  text, vector(1024), text[], text[], text, text, text, text[], text, text,
  text, text, timestamptz, timestamptz, jsonb, integer, integer, integer,
  numeric, numeric, numeric, real
);
```

Confirm each list against the live catalog before running, because a wrong list
makes the DROP a silent no-op and leaves the old overload in place:

```bash
DATABASE_URL="$SCRATCH_URL" psql "$SCRATCH_URL" -X -q -c "
SELECT p.proname, pg_get_function_identity_arguments(p.oid)
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'retrieval'
   AND p.proname IN ('acl_visible','acl_scalars_visible','full_text_search',
                     'vector_search','fuzzy_search','hybrid_search','traverse_evidence')
 ORDER BY p.proname;"
```

- [ ] **Step 3: `sql/09_traverse_evidence.sql`**

Replace `  p_principal jsonb DEFAULT NULL` (`:6`) with
`  p_role name DEFAULT current_user`, and both call sites (`:36`, `:61`) with
`retrieval.acl_visible(seed_item.acl, p_role)` and
`retrieval.acl_visible(neighbor_item.acl, p_role)`.

This file already opens with a DROP (`:1`) — but for the *two*-argument signature
that predates `p_principal`, which is why the current three-argument overload
survives every re-run. Extend it rather than replacing it:

```sql
DROP FUNCTION IF EXISTS retrieval.traverse_evidence(uuid[], integer);
DROP FUNCTION IF EXISTS retrieval.traverse_evidence(uuid[], integer, jsonb);
```

The stale two-arg DROP is a live demonstration of the overload trap this task
guards against: it has been a no-op since `p_principal` was added.

- [ ] **Step 4: `sql/01_schema.sql` — the persisted identity column**

`proof.retrieval_runs.principal` (`:1268`) and `proof.agent_runs.principal`
(`:1367`) persist the identity a run executed under; replay re-issues it. One
string replaces the jsonb bag.

In the `CREATE TABLE proof.retrieval_runs` body replace
```sql
  principal jsonb NOT NULL DEFAULT '{}'::jsonb,
```
with
```sql
  role text NOT NULL DEFAULT 'analyst'
    CHECK (role IN ('analyst', 'admin', 'auditor')),
```
and in `CREATE TABLE proof.agent_runs` replace
```sql
  principal jsonb NOT NULL,
```
with
```sql
  role text NOT NULL DEFAULT 'analyst'
    CHECK (role IN ('analyst', 'admin', 'auditor')),
```

The CHECK is the schema-level half of the vocabulary collapse: `support-lead`
cannot be persisted even by a hand-written INSERT.

Then add the migration ALTERs after each table, matching the file's existing
additive-ALTER idiom (`sql/01_schema.sql:925-949`):

```sql
ALTER TABLE proof.retrieval_runs
  ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'analyst';

ALTER TABLE proof.agent_runs
  ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'analyst';

-- Pre-collapse receipts carried a jsonb identity bag. The only two values ever
-- written were the workshop default and the support-lead pair, which map onto the
-- analyst and admin personas respectively (admin, not auditor: the old
-- support-lead saw the restricted row UNMASKED).
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_schema = 'proof' AND table_name = 'retrieval_runs'
       AND column_name = 'principal'
  ) THEN
    UPDATE proof.retrieval_runs
    SET role = CASE
      WHEN principal -> 'principals' ? 'support-lead' THEN 'admin'
      ELSE 'analyst'
    END;
    ALTER TABLE proof.retrieval_runs DROP COLUMN principal;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_schema = 'proof' AND table_name = 'agent_runs'
       AND column_name = 'principal'
  ) THEN
    UPDATE proof.agent_runs
    SET role = CASE
      WHEN principal -> 'principals' ? 'support-lead' THEN 'admin'
      ELSE 'analyst'
    END;
    ALTER TABLE proof.agent_runs DROP COLUMN principal;
  END IF;
END
$$;

ALTER TABLE proof.retrieval_runs
  DROP CONSTRAINT IF EXISTS retrieval_runs_role_check;
ALTER TABLE proof.retrieval_runs
  ADD CONSTRAINT retrieval_runs_role_check
  CHECK (role IN ('analyst', 'admin', 'auditor'));

ALTER TABLE proof.agent_runs
  DROP CONSTRAINT IF EXISTS agent_runs_role_check;
ALTER TABLE proof.agent_runs
  ADD CONSTRAINT agent_runs_role_check
  CHECK (role IN ('analyst', 'admin', 'auditor'));
```

The CHECK is added *after* the backfill so an existing row with an unmappable
value fails the constraint loudly instead of blocking the `ADD COLUMN`.

**The dropped column has a downstream reader.** `proof.v_run_receipts`
(`sql/04_diagnostics.sql:382`) projects `run.principal` as its last column. A view
column referencing a dropped table column makes `DROP COLUMN` fail outright
(Postgres refuses rather than cascading silently), so the view must be redefined in
the same apply. `make schema` runs `01` before `04`, meaning the DROP in Step 4
executes while the *old* view still exists on a re-applied database. Two
consequences, both handled here:

1. Change `sql/04_diagnostics.sql:382` from `  run.principal` to `  run.role`.
   `CREATE OR REPLACE VIEW` cannot change an existing column's name or type, so
   prepend a drop above the `CREATE OR REPLACE VIEW proof.v_run_receipts` at
   `sql/04_diagnostics.sql:357`:

   ```sql
   -- The receipt view's last column changed from principal jsonb to role text
   -- (A7). CREATE OR REPLACE VIEW cannot rename or retype a column, so the view
   -- is dropped first. It carries no grants of its own (sql/11 grants by schema).
   DROP VIEW IF EXISTS proof.v_run_receipts;
   ```

2. In `sql/01_schema.sql`, inside the `DO $$` block from this step, drop the view
   *before* the two `ALTER TABLE ... DROP COLUMN principal` statements, as the
   first statement in the block:

   ```sql
     DROP VIEW IF EXISTS proof.v_run_receipts;
   ```

   `sql/04_diagnostics.sql` recreates it later in the same `make schema` run. If
   you skip this, a re-apply against a pre-collapse database fails with
   `cannot drop column principal of table retrieval_runs because other objects
   depend on it`.

Verify no other view or function reads the column before relying on that list of
one:

```bash
grep -rn "\.principal\b\|run\.principal\|principal jsonb" sql/
```
Expected: only the sites this task edits — `sql/01_schema.sql:1268,1367`,
`sql/04_diagnostics.sql:382`, `sql/05_evaluation.sql:19,115,168`. Anything else is
a reader this plan has not accounted for: stop and report.

- [ ] **Step 5: `sql/05_evaluation.sql` — replay under the stored role**

Three sites read the run's identity back (`:19,115,168`). Replace each
`retrieval.acl_visible(item.acl, run.principal)` with:

```sql
    AND retrieval.acl_visible(item.acl, ('persona_' || run.role)::name)
```

This is why `acl_visible` keeps a second parameter: evaluation scores a stored run
under the identity that run used, which is not the identity the evaluator is
connected as. Without it, an eval executed as admin would score an analyst's run
against admin-visible ground truth and silently inflate recall.

- [ ] **Step 6: Grant EXECUTE on the new signatures**

`sql/11_roles_rls.sql` grants `EXECUTE ON ALL FUNCTIONS IN SCHEMA retrieval`, which
covers functions existing when that file runs. `make schema` runs `03` before `11`,
so ordering is already correct — but re-running only `03` after `11` would leave the
new signatures ungranted. Add to the end of `sql/03_search_functions.sql`:

```sql
-- Re-grant after a signature change: DROP FUNCTION discards the old grants, and
-- sql/11_roles_rls.sql may already have run. Guarded so a fresh database (where
-- the personas do not exist yet) still applies this file.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'persona_analyst') THEN
    GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA retrieval
      TO persona_analyst, persona_admin, persona_auditor;
  END IF;
END
$$;
```

- [ ] **Step 7: Apply and assert on a disposable database**

Re-run the Task 5 scratch script (it applies `00`-`12` in order), then:

```sql
\echo old overloads must be GONE, not shadowed
SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS args
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'retrieval'
   AND pg_get_function_identity_arguments(p.oid) LIKE '%jsonb%'
 ORDER BY 1, 2;

\echo the predicate must disagree between two roles on the same row
BEGIN;
SET LOCAL ROLE persona_analyst;
SELECT retrieval.acl_visible('{"visibility":"restricted"}'::jsonb) AS analyst_sees;
ROLLBACK;
BEGIN;
SET LOCAL ROLE persona_admin;
SELECT retrieval.acl_visible('{"visibility":"restricted"}'::jsonb) AS admin_sees;
ROLLBACK;
```

Expected: the first query returns **zero rows** for the arm and predicate functions
(a `jsonb` argument surviving on `acl_visible`, `acl_scalars_visible`, or any arm
means a DROP list was wrong; `p_query_embedding vector` and the `metadata jsonb`
columns are unrelated and will not appear here because this filters on the argument
list). Second query: `analyst_sees = f`, `admin_sees = t`.

Then assert the receipt view carries the new column, because a stale view is the
failure mode Step 4's DROP exists to prevent:

```sql
SELECT column_name FROM information_schema.columns
 WHERE table_schema = 'proof' AND table_name = 'v_run_receipts'
   AND column_name IN ('role', 'principal');
```
Expected: exactly one row, `role`. A `principal` row means `sql/04_diagnostics.sql`
was applied before the column change, or the `DROP VIEW` was skipped.

Also re-apply the whole script a second time against the same database. The
migration path (drop view → backfill → drop column → recreate view) must be
idempotent, and the `DO $$` guard's `information_schema` check is what makes the
second run a no-op. A failure on the second apply and not the first is the signature
of a missing guard.

- [ ] **Step 8: Commit**

```bash
git add sql/03_search_functions.sql sql/09_traverse_evidence.sql \
        sql/05_evaluation.sql sql/01_schema.sql sql/04_diagnostics.sql
git commit -m "Key the ACL predicate on the database role, not a caller identity"
```

The Python callers still pass `p_principal` after this commit and the API is
broken until Task 10. Same deliberate split as Task 7: the engine-side contract
lands with its own assertions, then the callers follow.

---

## Task 10: Thread the persona through Python and finish the A7 collapse

Task 7 made the persona a required argument. Task 9 removed `p_principal` from the
SQL. This task makes the Python side agree with both, in one commit, because the
app is un-runnable between them: `get_dict_conn()` is now a `TypeError` and
`retrieval.acl_visible(acl, %s::jsonb)` no longer resolves.

**Measured scope** (not estimated — from `grep -c`):

| Site class | Count | Files |
|---|---|---|
| `get_dict_conn()` checkouts | 37 | agent.py 15, insights.py 11, evaluation.py 5, search.py 5, contracts.py 1, main.py 1 |
| `get_dict_conn()` in scripts | 2 | smoke_test.py:66, doctor.py:306 |
| `principal` kwarg / field / column | ~45 | models.py 6, agent.py 18, agent_tools.py 8, evaluation.py 5, insights.py 4, search.py 4, main.py 3, strands_agent.py 2 |

The earlier count of 44 came from an unfiltered grep that included `db.py`'s own
definitions and the script call sites. 37 is the request-path number.

**Files:**
- Modify: `backend/app/models.py:21-22,49,77,87,92,116`
- Modify: `backend/app/search.py:90,99,118,139,179,245,308,332,456,646`
- Modify: `backend/app/agent.py` (15 checkouts + 18 principal sites, listed per step)
- Modify: `backend/app/insights.py:82,94,125,163,187,197,349,353,429-441,459-461,514,565`
- Modify: `backend/app/evaluation.py:22,55,59,76,97,103,113,117,199`
- Modify: `backend/app/contracts.py:112`
- Modify: `backend/app/main.py:54,256,273,378-392,380`
- Modify: `backend/app/agent_tools.py:11-12,42,51,79-104,252,274,314,346,378,577`
- Modify: `backend/app/strands_agent.py:236,277`
- Modify: `agent/registry.py:82,102,169,271-274,312,330,346,410`
- Modify: `agent/generate_mcp_server.py:126-127`
- Regenerate: `mcp-server/src/server.generated.ts`, `lambda_mcp/generated_dispatch.py`
- Modify: `backend/scripts/smoke_test.py:66,114-128`, `backend/scripts/doctor.py:217,306`
- Test: `backend/tests/test_agent_tools.py:93-111`, `test_mcp_contract.py:62`,
  `test_strands_agent.py:253-267`, `test_retrieval_integration.py:192-193,298-305,544`

**Interfaces:**
- Consumes: `db.get_dict_conn(persona)`, `db.Persona`, `db.PERSONAS`,
  `db.persona_role()` (Task 7); the argument-free SQL predicates (Task 9).
- Produces:
  - `models.DEFAULT_ROLE: Persona = "analyst"`
  - `role: Persona = "analyst"` on the five request models (replacing `principal`)
  - every `*_impl(..., role: str = "analyst")` — the registry's identity param
  - `agent_tools.start_run(role: str | None)`, `agent_tools._role() -> str`
  - `registry._ROLE_PARAM` (replacing `_PRINCIPAL_PARAM`), `ToolParam.identity_bound`
    (replacing `principal_bound`)

**The rule for picking a persona at each checkout** — three cases, and the third is
the one that gets got wrong:

1. **Request path** (search, agent, traverse, compare, plan): the persona comes
   from the request model. Thread it.
2. **Replay path** (`explain_ranking`, `run_graph`, `run_timeline`,
   `observability_ref`, `latest_cited_run`): the persona comes from the *stored
   run's* `role` column, not the caller's. A receipt must render as the identity
   that produced it or replay is a lie. `_run_principal()` becomes `_run_role()`
   and its result selects the checkout — which means the run row must be read
   before the persona is known, so these functions need **two** checkouts: an
   `"analyst"` read of `proof.retrieval_runs.role` (proof tables carry no RLS
   policy, so any persona can read them), then the content read under that role.
3. **Cluster-metadata path** (`search_index_health`, `fusion_sql`,
   `search_index_diagnostics`, `index_usage`, `slow_queries`): reads
   `pg_stat_*`, `pg_proc`, `pg_indexes`, `retrieval.v_*` aggregate views. No
   evidence rows. These take `"analyst"` — the least-privileged persona — because a
   diagnostic surface must never be the thing that shows a restricted row.

### [VERIFY] BLOCKING: owner-rights views defeat RLS

**Do not skip this step. The rest of the task's correctness depends on it.**

PostgreSQL views run with the *owner's* permissions unless created with
`security_invoker = true` (PG 15+). No view in `sql/` sets it — verified:

```bash
grep -rn "security_invoker" sql/    # expect: no output
```

The owner is the bootstrap role, which Task 5 grants `can_see_restricted` so the
seed and the index build can project the whole corpus. Every policy's clearance
disjunct is therefore true for it on every row, so an owner-rights view returns
restricted rows to whoever can select from the view. **Every view over a read-path
table is therefore an RLS hole**, no matter how correct the policies are. (Not a
bypass: the owner is fully subject to `FORCE`, it simply satisfies the predicate.
Same hole either way.)

Measured inventory of views and their exposure:

| View | Reads a read-path table? | Returns evidence content? | Action |
|---|---|---|---|
| `casework.v_evidence_documents` | yes (`casework.*` incl. `support_cases`) | **yes** — `body` concat of subject/description/customer_commitment | `security_invoker = true` |
| `retrieval.v_current_chunks` | yes (`documents` + `chunks`) | **yes** — `chunk_text` | **DROP** — zero consumers |
| `retrieval.evidence_edges` | yes (`casework.incident_*` join tables) | no — IDs, relation, rationale | `security_invoker = true` |
| `proof.v_answer_receipts` | joins `casework.evidence_items` | title + quote_text | `security_invoker = true` |
| `proof.v_candidate_receipts` | joins `casework.evidence_items` | title + `evidence_snapshot` | `security_invoker = true` |
| `proof.v_evaluation_results` | joins `casework.evidence_items` | no (aggregates) | `security_invoker = true` |
| `proof.v_traversal_evaluation_results` | joins judgments | no | `security_invoker = true` |
| `proof.v_run_receipts` | `proof.*` only | no | leave |
| `retrieval.v_search_index_health` | `casework.evidence_items` + both retrieval tables | no — counts only | **leave, deliberately** |
| `retrieval.v_search_index_drift` | `v_evidence_documents` + `documents` | hashes + external_key | **leave, deliberately** |
| `retrieval.v_corpus_distribution` | both retrieval tables | no — counts | **leave, deliberately** |
| `retrieval.v_embedding_spaces` | both retrieval tables | no — counts | **leave, deliberately** |
| `retrieval.v_index_usage`, `v_index_definitions` | `pg_*` catalogs | no | leave |
| `casework.v_release_capture_validation` | `casework.fixture_captures`, sample tables | no | leave |

**Why four `retrieval.v_*` views deliberately keep owner rights:** they are the
health and corpus surfaces, and their honesty depends on counting *every* row.
Under `security_invoker` an auditor's `/ready` would report a chunk count short by
the restricted rows and G-11/G-23 receipts would disagree with the build receipt —
the workbench would appear to have lost data. They expose counts and hashes, never
text, so this is a defensible boundary. **Record it in the task report and in the
G-29 leak scan's exclusion list, with this reasoning.** If a later change adds a
content column to any of them, that view moves to `security_invoker`.

**`retrieval.v_current_chunks` is dropped, not fixed.** It exposes `chunk_text` and
`acl` for every current chunk and has exactly one occurrence in the entire
repository — its own `CREATE`. An unreferenced view over the blob column is pure
attack surface; the coding standard is replace, don't deprecate.

- [ ] **Step 1: Close the view hole (`sql/01_schema.sql`, `sql/03`, `sql/04`, `sql/05`, `sql/06`)**

Add `WITH (security_invoker = true)` to the six views in the "yes" rows. The syntax
goes between the view name and `AS`:

```sql
CREATE OR REPLACE VIEW casework.v_evidence_documents
WITH (security_invoker = true) AS
```

Apply the same edit at `sql/01_schema.sql:1121` (`retrieval.evidence_edges`),
`sql/06_receipts.sql:1` (`proof.v_answer_receipts`), `sql/06_receipts.sql:41`
(`proof.v_candidate_receipts`, which is `CREATE VIEW` after a `DROP` — same
placement), `sql/05_evaluation.sql:136` (`proof.v_evaluation_results`), and
`sql/05_evaluation.sql:207` (`proof.v_traversal_evaluation_results`).

`CREATE OR REPLACE VIEW ... WITH (...)` sets the option on an existing view, so no
DROP is needed.

Then delete `retrieval.v_current_chunks` — the whole block at
`sql/03_search_functions.sql:156` through its terminating `;` — and add above where
it stood:

```sql
-- retrieval.v_current_chunks was removed with the RLS work: it exposed chunk_text
-- and acl for every current chunk, had zero consumers, and as a non-security_invoker
-- view it read those tables as the owner, which holds the clearance key and so
-- satisfies every policy's second disjunct on every row.
DROP VIEW IF EXISTS retrieval.v_current_chunks;
```

Confirm the drop is safe one more time before running it (the earlier grep is a
measurement, this is the guard):

```bash
grep -rn "v_current_chunks" . --exclude-dir=node_modules --exclude-dir=.git \
  | grep -v "sql/03_search_functions.sql"
```
Expected: no output. Any hit means stop and re-scope.

- [ ] **Step 2: Write the failing tests**

Add to `backend/tests/test_db_persona.py` (created in Task 7) — a second
`unittest.TestCase` class alongside `PersonaCheckoutTests`, carrying the same
`@unittest.skipUnless` guard, because these tests also need a live database:

```python
CONTENT_VIEWS = (
    "casework.v_evidence_documents",
    "retrieval.evidence_edges",
    "proof.v_answer_receipts",
    "proof.v_candidate_receipts",
    "proof.v_evaluation_results",
    "proof.v_traversal_evaluation_results",
)

# Counted, never content: these read the read-path tables as the owner on purpose,
# so /ready and the corpus panels report the true row counts for every persona.
COUNT_ONLY_VIEWS = (
    "retrieval.v_search_index_health",
    "retrieval.v_search_index_drift",
    "retrieval.v_corpus_distribution",
    "retrieval.v_embedding_spaces",
)

_RELOPTIONS_SQL = """
SELECT 'security_invoker=true' = ANY(coalesce(c.reloptions, '{}')) AS invoker
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND c.relname = %s
"""


@unittest.skipUnless(
    os.environ.get("TEST_DATABASE_URL"),
    "set TEST_DATABASE_URL for the view security_invoker contract",
)
class ContentViewRlsTests(unittest.TestCase):
    def test_content_views_are_security_invoker(self) -> None:
        """A view that returns evidence text must be subject to the caller's RLS."""
        with db.get_dict_conn("analyst") as conn:
            with conn.cursor() as cursor:
                for qualified in CONTENT_VIEWS:
                    with self.subTest(view=qualified):
                        schema, name = qualified.split(".")
                        cursor.execute(_RELOPTIONS_SQL, (schema, name))
                        row = cursor.fetchone()
                        self.assertIsNotNone(row, f"{qualified} does not exist")
                        self.assertTrue(
                            row["invoker"],
                            f"{qualified} runs with owner rights and leaks "
                            f"restricted rows",
                        )

    def test_count_only_views_are_deliberately_owner_rights(self) -> None:
        """The health surfaces count every row on purpose; assert that stays true."""
        with db.get_dict_conn("analyst") as conn:
            with conn.cursor() as cursor:
                for qualified in COUNT_ONLY_VIEWS:
                    with self.subTest(view=qualified):
                        schema, name = qualified.split(".")
                        cursor.execute(_RELOPTIONS_SQL, (schema, name))
                        self.assertFalse(
                            cursor.fetchone()["invoker"],
                            f"{qualified} became security_invoker; if that is "
                            "intended, its counts now differ per persona — update "
                            "the G-29 exclusion list and the health-surface honesty "
                            "claim first",
                        )

    def test_the_dropped_chunk_view_is_gone(self) -> None:
        with db.get_dict_conn("analyst") as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT to_regclass('retrieval.v_current_chunks') AS oid")
                self.assertIsNone(cursor.fetchone()["oid"])
```

`subTest` is what makes the loop honest: without it the first failing view aborts
the loop and hides the rest, so a reviewer would see one failure where there are
six. `unittest` reports every subTest failure separately.

Run:
```bash
TEST_DATABASE_URL="postgresql://localhost:55432/retrieval_test?sslmode=disable" \
  DATABASE_URL="postgresql://localhost:55432/retrieval_test?sslmode=disable" \
  .venv/bin/python -m unittest backend.tests.test_db_persona.ContentViewRlsTests -v
```
Expected: the two `security_invoker` tests FAIL (`runs with owner rights and leaks
restricted rows`) until
Step 1's SQL is applied to the scratch database; the drop test FAILS too.

- [ ] **Step 3: `backend/app/models.py` — one identity field**

Replace `workshop_principal()` (`:21-22`) with:

```python
Persona = Literal["analyst", "admin", "auditor"]
DEFAULT_ROLE: Persona = "analyst"
```

Then on each of `SearchRequest` (`:49`), `AgentAnswerRequest` (`:77`),
`TraverseRequest` (`:87`), `CompareRequest` (`:92`), `QueryPlanRequest` (`:116`),
replace

```python
    principal: dict[str, Any] = Field(default_factory=workshop_principal)
```

with

```python
    role: Persona = DEFAULT_ROLE
```

Pydantic validates the `Literal`, so an unknown role is a 422 at the HTTP boundary
rather than a role name reaching `SET LOCAL ROLE`. That is the second half of the
CHECK constraint added in Task 9 Step 4.

`Persona` is declared here rather than imported from `db` because `models` must not
depend on the database layer — `db` imports `config`, and `models` is imported by
`agent_tools`, which the MCP adapters load without a pool. Task 7 declares the same
three-value `Literal` in `db`; a divergence is caught by a test in Step 12.

If `Any` becomes unused in the imports after this edit, remove it (zero-warnings
policy). Check with `grep -c "Any" backend/app/models.py` before deciding.

- [ ] **Step 4: `backend/app/search.py`**

Five checkouts, all request path — the persona is `request.role`:

- `:90` (`_create_run`) → `get_dict_conn(request.role)`
- `:179` (`_resolve_fuzzy_probe_tokens`) → this function takes `request`; use
  `request.role`
- `:245` (`_mark_run_failed`) → takes `run_id`, not a request. Add a `role: str`
  parameter and pass it from the caller at `run_hybrid_search`; a failure receipt
  must be written by the same identity that attempted the run.
- `:456` (`_run_sql_search`) → `request.role`
- `:646` (`_persist_success`) → this one already opens
  `with connection.transaction():` inside; that becomes a SAVEPOINT (Task 7).
  Use `request.role`.

Then the SQL:
- `:99` — replace the `principal,` column with `role,` in the
  `INSERT INTO proof.retrieval_runs` column list
- `:118` — replace `%(principal)s::jsonb,` with `%(role)s,`
- `:139` — replace `"principal": _json(request.principal),` with
  `"role": request.role,`
- `:308` — in `_common_params`, delete the `"principal": _json(request.principal),`
  entry outright
- `:332` — in `_FILTER_ARGUMENTS`, delete the `p_principal => %(principal)s::jsonb,`
  line

Deleting from `_FILTER_ARGUMENTS` is what makes the four arm calls match Task 9's
signatures. `_common_params` feeds every arm statement, so the dict entry must go
with it or psycopg raises on an unused named parameter... actually it does not —
psycopg ignores extra keys in a mapping. Delete it anyway: a dangling identity value
in the params dict is exactly the residue that makes a future reader think the
identity still travels on the wire.

- [ ] **Step 5: `backend/app/agent.py` — request path**

Signature changes (`principal: dict[str, Any] | None = None` → `role: str = "analyst"`):
- `search_evidence_impl` `:262`
- `follow_evidence_links_impl` `:307`
- `compare_sources_impl` `:388`
- `answer_with_citations_impl` `:2016`

At `:288` and `:2058`, `principal=principal or workshop_principal()` becomes
`role=role`. The `or default` idiom disappears everywhere: the default now lives in
one place (the `Literal` default on the model / the `= "analyst"` on the impl), not
at each call site. That collapse is the point of A7 — three defaulting sites were
three chances to default differently.

Checkouts and their personas:

| Line | Function | Persona |
|---|---|---|
| `:75` | `_reachable_by_kind` | `role` — add a `role: str = "analyst"` param; it is called from the plan path |
| `:315` | `follow_evidence_links_impl` | `role` |
| `:394` | `compare_sources_impl` | `role` |
| `:461` | (read) | trace the enclosing function; if it takes a request, `request.role`, else add a `role` param |
| `:646` | (read) | same rule |
| `:910` | `explain_ranking_impl` | **replay** — see Step 7 |
| `:1143`, `:1202`, `:1273`, `:1302`, `:1324`, `:1396`, `:1431`, `:1461` | agent-run writes | `request.role` (or the `role` threaded into the helper) |
| `:1695` | subquestion search | `request.role` |

Do not guess a persona for `:461` and `:646`. Read each enclosing function
signature and follow the rule table at the top of this task: request path → the
request's role; replay → the stored role; metadata → `"analyst"`.

SQL edits in this file:
- `:82-96` — `retrieval.traverse_evidence(ARRAY(...)::uuid[], 2, %(principal)s::jsonb)`
  becomes `retrieval.traverse_evidence(ARRAY(...)::uuid[], 2)`; delete the
  `"principal": _json(workshop_principal()),` bind
- `:326` — `AND retrieval.acl_visible(acl, %s::jsonb)` → `AND retrieval.acl_visible(acl)`;
  the parameter tuple `(keys, _json(resolved_principal))` becomes `(keys,)`
- `:360` — `retrieval.traverse_evidence(%s::uuid[], %s, %s::jsonb)` →
  `retrieval.traverse_evidence(%s::uuid[], %s)`; drop the third bind
- `:420` — same as `:326`
- `:943` — `AND retrieval.acl_visible(document.acl, run.principal)` →
  `AND retrieval.acl_visible(document.acl, ('persona_' || run.role)::name)`
  (explicit, because this row is being rendered under the *stored* run's identity —
  the same reason sql/05 keeps the argument)
- `:1209`/`:1226` — the `proof.agent_runs` INSERT: column `principal` → `role`,
  bind `_json(request.principal)` → `request.role`, and the `%s::jsonb` placeholder
  for it becomes plain `%s`
- `:1602` — `"principal": agent_run["principal"],` → `"role": agent_run["role"],`
- `:1722`, `:1912`, `:1940` — `principal=request.principal` → `role=request.role`

Delete `workshop_principal` from the `:12` import. Verify nothing else in the file
uses it: `grep -c "workshop_principal" backend/app/agent.py` must reach 0.

- [ ] **Step 6: `backend/app/evaluation.py`**

The A7 safety assertion depends on this file being exactly right, so it gets its own
treatment. Five checkouts, all `"analyst"`:

`:22` (`_queries`), `:59` and `:117` (metric writes), `:76`
(`_retrieval_metrics`), `:199` (`_traversal_metrics`).

**Why every eval checkout is `analyst` and not configurable:** Lab 2's goldens were
computed against the workshop-visible corpus. Scoring under `admin` would let a
restricted row enter a judged result set and silently change recall. The eval is a
fixed, comparable measurement, so its identity is fixed too — the same reasoning
that already forces `rerank=False` here.

- `:55` — `principal=filters.get("principal") or workshop_principal(),` becomes
  `role="analyst",`
- `:97` — `principal = filters.get("principal") or workshop_principal()` is deleted
- `:103` — `principal=principal,` → `role="analyst",`
- `:113` — `principal=principal,` → `role="analyst",`
- delete `workshop_principal` from the `:8` import

`filters.get("principal")` was a per-query identity override read from
`proof.evaluation_queries.filters`. Confirm no seeded query uses it before deleting
the read:

```bash
grep -n "principal" seed/*.py sql/05_evaluation.sql
```
If a seeded evaluation query carries a `principal` key in its filters, **stop and
report** — dropping it would change that query's judged set, which is exactly what
the A7 safety assertion is built to catch.

- [ ] **Step 7: `backend/app/insights.py` — the replay path**

`_run_principal` (`:429-437`) becomes `_run_role`, and it is the one place the
stored identity is read:

```python
def _run_role(run_id: str) -> str:
    """Read the persona a run executed under.

    Replay renders under the run's own identity, not the viewer's, so a receipt
    shows what the run actually saw. proof.retrieval_runs carries no RLS policy,
    so the least-privileged persona can read this row.

    Args:
        run_id: The run whose stored identity is needed.

    Returns:
        One of PERSONAS.

    Raises:
        ValueError: No such run.
    """
    with get_dict_conn("analyst") as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT role FROM proof.retrieval_runs WHERE run_id = %s",
                (run_id,),
            )
            row = cursor.fetchone()
    if not row:
        raise ValueError(f"retrieval run {run_id} was not found")
    return row["role"]
```

It takes `run_id` instead of a cursor now, because it owns its own checkout. That is
the two-checkout shape the rule table calls for.

`run_graph` (`:440`) becomes:

```python
def run_graph(run_id: str) -> dict[str, Any]:
    role = _run_role(run_id)
    with get_dict_conn(role) as connection:
        ...
```
and the `traverse_evidence` call at `:459-461` loses its third argument and its
`json.dumps(principal)` bind:

```python
            cursor.execute(
                """
                SELECT *
                FROM retrieval.traverse_evidence(%s::uuid[], 2)
                """,
                (seeds,),
            )
```

`run_timeline` (`:560`) calls `run_graph` first, then opens its own checkout at
`:565` for `TIMELINE_EVENT_BATCH_SQL`. Reuse the role:

```python
def run_timeline(run_id: str) -> dict[str, Any]:
    graph = run_graph(run_id)
    ids = [row["evidence_id"] for row in graph["nodes"]]
    if not ids:
        return {"run_id": run_id, "events": [], "edge_count": 0}
    with get_dict_conn(_run_role(run_id)) as connection:
```

`observability_ref` (`:514`) reads only `proof.observability_refs` → `"analyst"`.
`latest_cited_run` (`:163`) reads only `proof.*` → `"analyst"`.

`query_plan` (`:331,353`) is request path: `request.role`, and delete
`principal=request.principal` from the `SearchRequest(...)` it builds at `:349`
(the model no longer has the field; leaving it is a Pydantic validation error under
`model_config` defaults, and a silently-ignored field if extras are permitted —
either way it is wrong).

Metadata path → `"analyst"`: `search_index_health` (`:82`), `fusion_sql` (`:94`),
`search_index_diagnostics` (`:125`), `index_usage` (`:187`), `slow_queries`
(`:197`).

If `json` becomes unused after removing the `json.dumps(principal)` bind, remove the
import. Check first — `grep -c "json\." backend/app/insights.py`.

- [ ] **Step 8: `backend/app/contracts.py` and `backend/app/main.py`**

`contracts.py:112` writes `proof.transport_invocations`, a receipt table with no
RLS policy → `get_dict_conn("analyst")`.

`main.py`:
- delete `workshop_principal` from the `:44-55` import block
- `:256` `principal=request.principal` → `role=request.role`
- `:273` `principal=request.principal` → `role=request.role`
- `:378` delete `principal = json.dumps(workshop_principal())`
- `:380` `get_dict_conn()` → `get_dict_conn(role)` where the role comes from a new
  query parameter on the endpoint (below)
- `:390` `AND retrieval.acl_visible(source.acl, %s::jsonb)` →
  `AND retrieval.acl_visible(source.acl)`; the parameter tuple `(evidence_id,
  principal)` becomes `(evidence_id,)`

`/v1/evidence/{evidence_id}` is a GET with no request body, so its persona arrives
as a query parameter. Give it the same validated type as the models:

```python
@app.get("/v1/evidence/{evidence_id}")
def evidence_detail(evidence_id: str, role: Persona = DEFAULT_ROLE):
    # Enforce the same ACL every retrieval arm and traversal hop applies, so a
    # direct by-ID read cannot bypass visibility. Evidence outside the caller's
    # scope is reported as not found rather than acknowledged as restricted —
    # and now RLS enforces that even if this predicate were removed.
    try:
        with get_dict_conn(role) as connection:
```

Import `DEFAULT_ROLE` and `Persona` from `.models` in the same block the deleted
`workshop_principal` came from. FastAPI reads the `Literal` annotation and returns
422 for an unknown role, matching the body-model behaviour exactly.

The `retrieval.chunks` and `retrieval.evidence_edges` reads later in the same
function (`:397-423`) inherit the persona from the checkout — no predicate needed,
because RLS is on `retrieval.chunks` (Task 5) and `evidence_edges` became
`security_invoker` (Step 1). That is the payoff: the second and third queries in
this handler never had an ACL predicate and were relying on the first query's
filter for safety.

If `json` becomes unused in `main.py` after deleting the `json.dumps` call, keep it
— it is used by the SSE encoders at `:202,339,343`. Verify rather than assume.

- [ ] **Step 9: `backend/app/agent_tools.py` and `strands_agent.py`**

The ContextVar holds the identity the model cannot set. One string replaces the bag:

```python
def start_run(role: str | None) -> dict[str, Any]:
    """Begin an agent run: bind its persona and start recording tool calls.

    Args:
        role: The resolved caller persona, or None for the workshop default.

    Returns:
        The live run state. ``trace`` grows and ``answer_of_record`` is filled as
        tools execute, so a caller can read progress while the loop is running.
    """
    run: dict[str, Any] = {
        "role": role or DEFAULT_ROLE,
        "trace": [],
        "answer_of_record": None,
    }
    _RUN.set(run)
    return run


def _role() -> str:
    run = _run()
    return (run and run["role"]) or DEFAULT_ROLE
```

Rename the ContextVar's label too: `ContextVar("workbench_tool_run", default=None)`
already carries no identity noun, so it is unchanged.

Call sites: `:252`, `:314`, `:378` — `principal=_principal()` → `role=_role()`.
Import `DEFAULT_ROLE` from `backend.app.models` at `:42` in place of
`workshop_principal`.

Docstring prose at `:11-12`, `:51`, `:274`, `:346`, `:577` says "principal". Rewrite
in persona nouns — and note these lines are why G-11's extended banned-identity
scan (Task 8) will fail until this task lands:

- `:11-12` → "1. The caller's persona is bound server-side by :func:`start_run` and
  is not a tool parameter. A model that could pass its own persona could escalate
  past the ACL, so it is bound from the request, never from the model."
- `:51` → "Per-run state: the caller's persona, the tool-call trace, and the last"
- `:274` → "...or the analyst persona cannot see it. Retry without filters before
  concluding." — do **not** hardcode "analyst" here; use `_role()` in the f-string
  so the message names the actual persona:
  `f"exist, or the {_role()} persona cannot see them."`
- `:346` → same treatment
- `:577` → "(persona binding, row" 

`strands_agent.py:236,277`: `agent_tools.start_run(request.principal)` →
`agent_tools.start_run(request.role)`.

- [ ] **Step 10: `agent/registry.py` + regenerate both adapters**

The registry is the single definition; the two adapters are generated. Hand-editing
either one fails G-17.

In `agent/registry.py`:
- `:82` docstring: `principal_bound: When true, the parameter is the caller
  identity. It is` → `identity_bound: When true, the parameter is the caller
  persona. It is`
- `:102` field: `principal_bound: bool = False` → `identity_bound: bool = False`
- `:169`: `not p.principal_bound` → `not p.identity_bound`
- `:271-274`:

```python
_ROLE_PARAM = ToolParam(
    "role", "string", model_visible=False, identity_bound=True,
    enum=("analyst", "admin", "auditor"), default="analyst",
    description="Caller persona; bound server-side, never set by the model.",
)
```

- `:312`, `:330`, `:346`, `:410`: `_PRINCIPAL_PARAM,` → `_ROLE_PARAM,`

In `agent/generate_mcp_server.py:126-127`: `p.principal_bound` → `p.identity_bound`
(both occurrences).

The type change from `object` to `string` with an `enum` is deliberate and changes
the generated code in a way you should verify rather than trust:

- `mcp-server/src/server.generated.ts`: `principal: z.record(z.unknown()).optional(),`
  becomes `role: z.enum(["analyst", "admin", "auditor"]).default("analyst"),`
  — `_zod_expr` renders `.default()` for a param with a non-None default, and
  `_zod_scalar` renders the enum branch. Both paths already exist; no generator
  change beyond the rename.
- `lambda_mcp/generated_dispatch.py`: `principal=args.get("principal"),` becomes
  `role=str(args.get("role")) if args.get("role") is not None else "analyst",`
  — `_read_expr`'s string-with-default branch.

Regenerate and diff:
```bash
.venv/bin/python -m agent.generate_mcp_server
.venv/bin/python -m agent.generate_gateway_dispatch
git diff --stat mcp-server/src/server.generated.ts lambda_mcp/generated_dispatch.py
.venv/bin/python gates/registry_drift.py
```
Expected: both files change; G-17 PASS. If G-17 fails, you hand-edited a generated
file — revert it and regenerate.

Then confirm the model still cannot see the identity parameter:
```bash
.venv/bin/python -c "
from agent.registry import TOOLS
for name, spec in TOOLS.items():
    names = [p.name for p in spec.model_params()]
    assert 'role' not in names, (name, names)
print('role is model-invisible in all', len(TOOLS), 'tools')
"
```

- [ ] **Step 11: Scripts — `doctor.py`, `smoke_test.py`**

`doctor.py:306` → `get_dict_conn("analyst")`. `smoke_test.py:66` → `get_dict_conn("analyst")`.

`doctor.py:217` currently asserts restrictedness through the principals array:

```python
        "support-lead" not in restricted["acl"].get("principals", [])
```

Read the full check first (`sed -n '205,230p' backend/scripts/doctor.py`) — it is a
fail-open detector, and its replacement must assert the *new* invariant:

```python
        restricted["acl"].get("visibility") != "restricted"
```

`smoke_test.py:114-128` is the ACL smoke assertion. Read it, then rewrite it to
issue the restricted read under two personas and assert they disagree — the
behavioural form, which is what actually proves enforcement:

```python
    # The ACL is enforced by the engine, so prove it by disagreement: the same
    # query under two personas must return different row counts.
    with get_dict_conn("analyst") as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*) AS visible
                FROM casework.evidence_items
                WHERE coalesce(acl ->> 'visibility', 'restricted') = 'restricted'
                """
            )
            analyst_visible = cursor.fetchone()["visible"]
    with get_dict_conn("admin") as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*) AS visible
                FROM casework.evidence_items
                WHERE coalesce(acl ->> 'visibility', 'restricted') = 'restricted'
                """
            )
            admin_visible = cursor.fetchone()["visible"]
    assert analyst_visible == 0, (
        f"analyst saw {analyst_visible} restricted evidence rows; RLS is not enforced"
    )
    assert admin_visible > 0, (
        "admin saw no restricted evidence rows; either the seed has none or "
        "can_see_restricted is not granted"
    )
```

This is the same shape as G-27(b), on purpose: the gate is the authority and the
smoke test is the fast local signal.

- [ ] **Step 12: Rewrite the identity-based tests**

`backend/tests/test_agent_tools.py:93-111` — read the whole test, then replace the
`start_run` argument:

```python
        agent_tools.start_run("admin")
```

and whatever it asserted about the forwarded principal becomes an assertion that
`role="admin"` reached the impl. The test's purpose (the model cannot override the
bound identity) is unchanged.

`test_mcp_contract.py:62`, `test_strands_agent.py:253-267`,
`test_retrieval_integration.py:192-193,298-305,544` — read each, then apply the
mechanical mapping: `principal={"scopes": [...], "principals": [...]}` → `role="<persona>"`,
`"support-lead"` → `"admin"`, `workshop_principal()` → `"analyst"`.

Add the divergence guard the two `Literal` declarations need. It gets its **own**
`unittest.TestCase` class in `backend/tests/test_db_persona.py` with **no**
`@unittest.skipUnless` decorator — it needs no database, and this is exactly the
assertion that must run where `TEST_DATABASE_URL` is absent:

```python
class PersonaLiteralAgreementTests(unittest.TestCase):
    def test_the_two_persona_literals_agree(self) -> None:
        """models.Persona and db.PERSONAS are declared separately; keep them equal."""
        from typing import get_args

        from backend.app.models import Persona

        self.assertEqual(get_args(Persona), db.PERSONAS)
```

The skip guards are per-class (Task 7 put them on `PersonaCheckoutTests` and
`ContentViewRlsTests`), which is why this needs no restructuring — an undecorated
class simply runs.

- [ ] **Step 13: Run the suite**

```bash
.venv/bin/python -m unittest discover -s backend/tests -q 2>&1 | tail -30
TEST_DATABASE_URL="postgresql://localhost:55432/retrieval_test?sslmode=disable" \
  DATABASE_URL="postgresql://localhost:55432/retrieval_test?sslmode=disable" \
  .venv/bin/python -m unittest backend.tests.test_db_persona -v
.venv/bin/python gates/noun_lint.py
.venv/bin/python gates/registry_drift.py
.venv/bin/python gates/route_contract.py
```

Expected: all pass. G-11 (`noun_lint.py`) now passes for the first time since Task 8
extended it — Task 8's report noted its failure as expected, and this task is what
clears it. If G-11 still fails, read its output: every remaining hit is a real
`principal`/`support-lead` occurrence this task missed.

`route_contract.py` will still fail on the `?role=` param until Task 11. Note it,
do not fix it here.

- [ ] **Step 14: Run the A7 SAFETY ASSERTION**

This is the amendment's own blocker: the vocabulary collapse must not have changed
what any persona sees. It runs after the code lands and before anything is committed
to the live path.

```bash
# On the scratch database, seeded and indexed.
DATABASE_URL="$SCRATCH_URL" .venv/bin/python -c "
import json
from backend.app.evaluation import run_evaluation
result = run_evaluation(None, 10)
print(json.dumps(result, default=str, sort_keys=True, indent=2))
" > /tmp/eval_after_collapse.json
```

Compare against the pre-collapse goldens. The comparison target is measured, never
retyped: check out the pre-Task-9 tree into a second worktree, run the identical
command there, and diff.

```bash
git worktree add .local/worktrees/pre-collapse <sha-before-task-9>
# seed a second scratch DB from that tree, run the same command, then:
diff <(jq -S 'del(.runs[].run_id, .runs[].created_at)' /tmp/eval_before.json) \
     <(jq -S 'del(.runs[].run_id, .runs[].created_at)' /tmp/eval_after_collapse.json)
```

Expected: empty diff after removing the non-deterministic keys. **Any surviving
difference in a metric value means the collapse altered retrieval semantics: STOP
and report, do not proceed to Task 11.** A7 says so explicitly.

Inspect the actual key names in the payload before writing the `jq` filter — the
`del()` path above is a template, and a wrong path silently deletes nothing and
makes the diff noisy rather than wrong.

Do the same for the canonical question's claim coverage:

```bash
curl -s localhost:8000/v1/agent/answer -H 'content-type: application/json' \
  -d '{"question":"<the canonical question, read from the guide>","role":"analyst"}' \
  | jq -S '{answer, citations: [.citations[] | {external_key, claim, quote_text}]}' \
  > /tmp/canonical_after.json
```
and diff against the same call in the pre-collapse worktree. Byte-identical
citations and claims, or stop.

Clean up:
```bash
git worktree remove --force .local/worktrees/pre-collapse
git worktree prune
```

- [ ] **Step 15: Commit**

```bash
git add backend/app backend/scripts backend/tests agent lambda_mcp mcp-server sql
git commit -m "Thread the persona through the request path; retire the identity bag"
```

---

## Task 11: Frontend persona — route, chip, receipt

The moment (A4). Three personas replace the boolean, the chip is a mirror of the
identity the request carried, and every flip's receipt renders the **one**
`SET LOCAL ROLE` it caused. Copy is **"Viewing as"**, never "Sign in as".

**Files:**
- Create: `frontend/src/persona.ts`
- Modify: `frontend/src/route.ts:20-27,44-48,60-72,95-104,109-127`
- Modify: `frontend/src/WorkbenchApp.tsx` (the 20 identity sites + 5 prose sites
  listed per step; renamed in Task 8)
- Modify: `frontend/src/workbench.css` (chip styles; renamed in Task 8)
- Modify: `gates/route_contract.py:22-23,66-90`

**Interfaces:**
- Consumes: `models.Persona` values `analyst | admin | auditor` and the wire field
  `role` (Task 10); `db.persona_role()`'s `persona_<persona>` naming (Task 7).
- Produces:
  - `persona.ts`: `PersonaKey`, `PERSONA_KEYS`, `PERSONA_LABELS`,
    `PERSONA_DB_ROLES`, `DEFAULT_PERSONA`, `isPersonaKey()`, `personaLabel()`,
    `personaSetRoleSql()`
  - `route.ts`: `Route.role?: PersonaKey` (replacing `Route.principal`), and the
    `?role=` param
  - `WorkbenchApp.tsx`: `Controls.role: PersonaKey` (replacing
    `Controls.supportLead: boolean`)

**Naming trap — do not name anything `role` in `WorkbenchApp.tsx` scope.**
`sourceRole(citation)` already exists at `WorkbenchApp.tsx:886` (the file Task 8
renamed from `VerityApp.tsx`; line numbers are unchanged by a pure rename) and returns a
citation's *evidentiary* role ("primary cause", "corroborating") — a completely
different concept, used at `:2969`. The new identity concept is **persona**
everywhere in the component: `Controls.role` is the field name (matching the wire),
but every local, helper, and label uses `persona`. Confirm the collision is still
one function before you start:

```bash
grep -n 'sourceRole\|function .*[Rr]ole' frontend/src/WorkbenchApp.tsx
```

- [ ] **Step 1: Write the failing route test**

`route.ts` has no test file today — G-23 is its test, and it executes the real
module. So the failing test is the gate. Update
`gates/route_contract.py` first, run it, and watch it fail.

Replace `CONTRACT_ROUTES`' two agent entries (`gates/route_contract.py:74-81`):

```python
    (
        "#/agent?role=analyst",
        {"surface": "agent", "role": "analyst"},
    ),
    (
        "#/agent?role=admin",
        {"surface": "agent", "role": "admin"},
    ),
    (
        "#/agent?role=auditor",
        {"surface": "agent", "role": "auditor"},
    ),
```

and `BUNDLE_LITERALS` (`:90`):

```python
BUNDLE_LITERALS = ["exact", "fuzzy", "semantic", "analyst", "admin", "auditor"]
```

and the docstring at `:22-23`:

```python
   participants to - /overview, /retrieval?preset={exact|fuzzy|semantic},
   /agent?role={analyst|admin|auditor}, /proof/{run_id} (SPEC-session:457) -
```

plus `:5` (`prefilled (preset, principal, run_id)` → `prefilled (preset, role,
run_id)`) and `:30` (`the preset and principal enum literals` → `the preset and
persona enum literals`). Both are prose in a gate this task is editing anyway, and
G-11's banned-identity scan (Task 8) reads `gates/` — leaving them is a G-11 hit.

- [ ] **Step 2: Run G-23 to verify it fails**

Run: `gates/checks.sh G-23`

Expected: FAIL on the first agent route —
`#/agent?role=analyst parsed to {'surface': 'agent'}, expected {'surface':
'agent', 'role': 'analyst'}`. The router still reads `?principal=`, so `?role=` is
dropped and the parse degrades to a bare surface. That is exactly the tolerant
behaviour `parseRoute`'s docstring promises, which is why the gate — not a
`try/catch` — is what catches this.

- [ ] **Step 3: Create `frontend/src/persona.ts`**

```ts
// The persona vocabulary, in one place (A7: one identity axis). Pure data and
// pure functions — no React, no fetch — so route.ts, the app, and the G-23 gate
// harness can all import it without pulling in the component tree.
//
// These three values are the SAME enum as backend/app/models.py's Persona and
// backend/app/db.py's PERSONAS. A fourth value here without the matching
// GRANT in sql/11_roles_rls.sql produces a request that fails with
// `permission denied to set role`, which is the correct failure: the database
// is the authority on which identities exist.

export type PersonaKey = 'analyst' | 'admin' | 'auditor';

export const PERSONA_KEYS: readonly PersonaKey[] = [
  'analyst',
  'admin',
  'auditor',
];

export const DEFAULT_PERSONA: PersonaKey = 'analyst';

// Chip copy (A4). "Viewing as" is the frame; these are the values inside it.
// Never "Sign in as" — the chip mirrors the identity the request carried, it
// does not grant one.
export const PERSONA_LABELS: Record<PersonaKey, string> = {
  analyst: 'Analyst',
  admin: 'Admin',
  auditor: 'Auditor',
};

// What the app asked Postgres to become. Rendered in the receipt so a
// participant can paste the same statement into psql and see the same rows.
export const PERSONA_DB_ROLES: Record<PersonaKey, string> = {
  analyst: 'persona_analyst',
  admin: 'persona_admin',
  auditor: 'persona_auditor',
};

export function isPersonaKey(value: string): value is PersonaKey {
  return (PERSONA_KEYS as string[]).includes(value);
}

export function personaLabel(value?: string): string {
  return value && isPersonaKey(value)
    ? PERSONA_LABELS[value]
    : PERSONA_LABELS[DEFAULT_PERSONA];
}

/**
 * The one statement the app issued for this persona. Rendered verbatim in the
 * flip receipt: the app's claim about what it did must be the pasteable proof
 * of what it did.
 */
export function personaSetRoleSql(value: PersonaKey): string {
  return `SET LOCAL ROLE ${PERSONA_DB_ROLES[value]};`;
}
```

- [ ] **Step 4: Rewrite the identity half of `frontend/src/route.ts`**

Five edits. The module keeps its shape; only the identity type and param name
change.

At `:20-21`, delete the local `PrincipalKey` and import the shared type:

```ts
import { PERSONA_KEYS, type PersonaKey, isPersonaKey } from './persona';

export type PresetKey = 'exact' | 'fuzzy' | 'semantic';
export type { PersonaKey };
```

Re-exporting `PersonaKey` keeps `WorkbenchApp.tsx`'s existing
`import { …, type PrincipalKey } from './route'` shape working after a one-word
rename, rather than forcing a second import line into a file this task already
edits 20 times.

At `:27`, in `interface Route`:

```ts
  role?: PersonaKey;
```

At `:45-48`, delete `PRINCIPAL_KEYS` entirely — `PERSONA_KEYS` from `persona.ts`
replaces it. Check for consumers first:

```bash
grep -rn 'PRINCIPAL_KEYS' frontend/src gates
```
Expected: only `route.ts` itself. If `WorkbenchApp.tsx` imports it, the import
becomes `PERSONA_KEYS` from `./persona` in Step 6.

At `:67-72`, replace `readPrincipal`:

```ts
function readRole(params: URLSearchParams): PersonaKey | undefined {
  const role = params.get('role');
  return role && isPersonaKey(role) ? role : undefined;
}
```

`isPersonaKey` is a type guard, so the `as PersonaKey` cast the old function
needed is gone. That is the small win from putting the enum in one module.

At `:98-100` in `parseRoute`:

```ts
  } else if (surface === 'agent') {
    const role = readRole(params);
    if (role) route.role = role;
```

At `:125-127` in `formatRoute`:

```ts
  if (route.surface === 'agent' && route.role) {
    params.set('role', route.role);
  }
```

And the two docstrings — `:76` (`lens, preset, or principal is dropped` → `lens,
preset, or role is dropped`) and `:112` (`a fixed order (preset, principal, lens)`
→ `a fixed order (preset, role, lens)`). The emission order in `formatRoute` is
unchanged (preset, then role, then lens), so the docstring stays true.

- [ ] **Step 5: Run G-23 to verify it passes**

```bash
cd frontend && npx tsc --noEmit && cd ..
gates/checks.sh G-23
```

Expected: `tsc` silent; G-23 reports round-trip on 9 contract routes. The bundle
check will report BLOCKED or FAIL on the missing `analyst`/`admin`/`auditor`
literals until Step 9 rebuilds — that is expected here and cleared in Step 9. Note
which it was in the task report.

- [ ] **Step 6: Replace the boolean control with the persona in `WorkbenchApp.tsx`**

`Controls.supportLead: boolean` becomes `Controls.role: PersonaKey`. The field is
named `role` because it goes on the wire as `role` (Task 10's model field) and a
second name for a value that travels unchanged is the dual vocabulary A7 removes.

- `:49` — the import: `type PrincipalKey,` → `type PersonaKey,`
- `:571` — `supportLead: boolean;` → `role: PersonaKey;`
- `:596` — `supportLead: false,` → `role: DEFAULT_PERSONA,`
- `:615` — in `retrievalRequestKey`: `supportLead: controls.supportLead,` →
  `role: controls.role,`

Add to the imports at the top of the file:

```ts
import {
  DEFAULT_PERSONA,
  PERSONA_KEYS,
  PERSONA_LABELS,
  personaLabel,
  personaSetRoleSql,
  type PersonaKey,
} from './persona';
```

`retrievalRequestKey` is the cache key for a retrieval request. Changing a
boolean to a three-value string there is what makes an analyst→admin flip a
**new** request rather than a cache hit — verify by reading the function
(`:614-632`) and confirming the key is used for memoization before moving on. If
the persona were left out of the key, the flip would render the previous
persona's rows under the new chip: the exact dishonesty this whole plan exists to
prevent.

- [ ] **Step 7: Thread the persona through the three request bodies**

All three currently build the identity bag inline. Replace each with the one
field (`:3533-3536`, `:3596-3599`, `:3706-3709`):

```ts
      role: sourceControls.role,
```
```ts
          role: controls.role,
```
```ts
          role: controls.role,
```

The first is inside the retrieval request builder (which takes `sourceControls`);
the second is the query-plan POST; the third is the agent-answer POST. Read each
enclosing function to confirm which controls object is in scope — `sourceControls`
vs `controls` is not interchangeable there (the builder is called with a
baseline copy).

`beginInvestigation` (`:3660`) resets the baseline: `supportLead: false,` →
`role: DEFAULT_PERSONA,`. It resets to the *least-privileged* persona on purpose —
an investigation that starts as admin would show the restricted row before the
participant learns why it is restricted, which spoils M3.

`goTo`'s retrieval case (`:3364`) does the same reset: `setControl('supportLead',
false)` → `setControl('role', DEFAULT_PERSONA)`. The retrieval surface has no
persona chip in this plan (the flip is the Agent surface's moment, A4), so
arriving there must not carry a stale admin identity into an unlabelled surface.

- [ ] **Step 8: Route ↔ state wiring**

- `:3303-3304` (mount):
```ts
    if (initialRoute.surface === 'agent' && initialRoute.role) {
      setControl('role', initialRoute.role);
    }
```
- `:3435-3436` (derived): the whole `activePrincipal` binding collapses to a read —
```ts
  const activePersona: PersonaKey = controls.role;
```
  Keep it as a named binding rather than inlining `controls.role` at the two use
  sites: it is the value the URL-sync effect lists in its dependency array, and a
  named binding is what makes that dependency legible.
- `:3466-3467` (`applyRoute`):
```ts
    if (route.surface === 'agent' && route.role) {
      setControl('role', route.role);
    }
```
- `:3485` (URL sync): `if (activeSurface === 'agent') route.principal =
  activePrincipal;` → `if (activeSurface === 'agent') route.role = activePersona;`
- `:3496` (dep array): `activePrincipal,` → `activePersona,`
- `:3451` (comment): `preset/principal set controls` → `preset/role set controls`

- [ ] **Step 9: The "Viewing as" chip in `JourneyStrip`**

**Why `JourneyStrip` and not `header.chrome`.** SPEC-session:464 puts the role chip
in the header on **all surfaces**. Measured: `<header className="chrome">`
(`:4301`) renders only when
`module !== 'home' && module !== 'retrieve' && activeSurface !== 'agent' &&
activeSurface !== 'proof'` — it is suppressed on four of seven surfaces, including
the Agent surface where the flip happens. `<JourneyStrip />` (`:4287`) is the only
element in `app-column` rendered unconditionally. The chip goes there. Confirm this
is still true before implementing:

```bash
grep -n 'className="chrome"' -B6 frontend/src/WorkbenchApp.tsx
grep -n '<JourneyStrip' -A10 frontend/src/WorkbenchApp.tsx
```

Extend the component signature (`:2893-2899`) and add a third grid cell:

```tsx
function JourneyStrip({
  steps,
  onNavigate,
  persona,
  onPersona,
}: {
  steps: JourneyStep[];
  onNavigate: (surface: JourneySurface) => void;
  persona: PersonaKey;
  onPersona: (next: PersonaKey) => void;
}) {
  return (
    <nav className="journey-strip" aria-label="Investigation progress">
      <span className="journey-strip-title">
        <GitMerge size={14} />
        Evidence journey
      </span>
      <ol>
        {/* unchanged */}
      </ol>
      <div className="persona-chip">
        <span className="section-label">Viewing as</span>
        <div className="segmented" role="group" aria-label="Viewing as">
          {PERSONA_KEYS.map((key) => (
            <button
              key={key}
              type="button"
              className={key === persona ? 'active' : ''}
              aria-pressed={key === persona}
              onClick={() => onPersona(key)}
            >
              {PERSONA_LABELS[key]}
            </button>
          ))}
        </div>
      </div>
    </nav>
  );
}
```

The `<ol>` body is unchanged — do not retype it; leave those lines alone and add
only the new sibling `<div>`.

At the call site (`:4287-4296`) add the two props:

```tsx
        <JourneyStrip
          steps={journeySteps}
          onNavigate={(surface) =>
            goTo(
              surface,
              PRIMARY_NAV.find((item) => item.surface === surface)?.lenses[0]
                ?.key,
            )
          }
          persona={controls.role}
          onPersona={(next) => setControl('role', next)}
        />
```

The chip is a **mirror, never a power** (A4): `onPersona` writes one control and
nothing else. It does not fetch, does not clear the receipt, does not navigate. The
next request carries the new persona because `retrievalRequestKey` changed
(Step 6); the currently-displayed receipt keeps rendering the persona it was
produced under (Step 10). A chip that silently re-fetched would make the receipt
and the chip disagree for the duration of the request.

CSS — append to `frontend/src/workbench.css`, immediately after the
`.journey-strip-title svg` rule (measured at `verity.css:8571-8573` pre-rename):

```css
.journey-strip {
  grid-template-columns: auto minmax(0, 1fr) auto;
}

.persona-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}
```

The `grid-template-columns` override repeats the property from the base
`.journey-strip` rule (`:8548-8558`) with a third track. Put it in the base rule
instead if you prefer — one declaration, one place. Do **not** leave both: a
duplicate property in the same stylesheet is the dead-CSS pattern this repo has
already swept twice.

`.segmented` (`:2063-2081`) and `.section-label` already exist and already carry
the active-state treatment (`color: var(--paper); background: var(--ink)`), so the
chip needs no new visual vocabulary — which is the point. It looks like every other
three-way toggle in the app because it *is* one.

- [ ] **Step 10: Receipt rendering — the one `SET LOCAL ROLE`**

Six sites render the old identity bag. The receipt must show **the persona the run
executed under**, read from the run row (Task 10 renamed
`proof.retrieval_runs.principal` → `role`, a plain text column), not the chip.

- `:318-321` — `interface PrincipalReceipt { scopes?: string[]; principals?:
  string[] }` is **deleted**. The wire type is a string now.
- `:346` — `principal?: PrincipalReceipt;` → `role?: string;` on `RunSummary`
- `:1021-1025` — `principalLabel()` is **deleted**; `personaLabel()` from
  `persona.ts` replaces it. It reads a plain string and falls back to the default
  persona's label, so the `named.length ? … : scopes.length ? … : 'workshop'`
  cascade disappears with the bag it was decoding.
- `:2968` — `const principal = principalLabel(receipt.run.principal);` →
  `const persona = personaLabel(receipt.run.role);`
- `:3004` — `` meta: `${validationStatus} · principal ${principal}` `` →
  `` meta: `${validationStatus} · viewing as ${persona}` ``
- `:3093-3095` — `<dt>Principal</dt><dd>{principal}</dd>` →
```tsx
            <div>
              <dt>Viewing as</dt>
              <dd>{persona}</dd>
            </div>
```
- `:4113-4117` — the `persistedPrincipal` fallback object collapses:
```ts
  const persistedPersona = receipt?.run.role || controls.role;
  const persistedPersonaLabel = personaLabel(persistedPersona);
```
- `:6082-6100` — the graph boundary section: class
  `graph-principal-boundary` → `graph-persona-boundary` (rename the CSS rule
  too — `grep -n 'graph-principal-boundary\|graph-scope-principal'
  frontend/src/workbench.css`), label `Principal scope boundary` → `Entitlement
  boundary`, `persisted principal` → `persisted persona`, both
  `{persistedPrincipalLabel}` → `{persistedPersonaLabel}`.
- `:6408-6412` — the replay timeline's first row. This is the **flip receipt**:
  it is the line that must render the one statement the app issued.
```tsx
                          <span>
                            {personaSetRoleSql(
                              (receipt?.run.role as PersonaKey) ??
                                controls.role,
                            )}{' '}
                            cluster {controls.clusterId || 'all'}.
                          </span>
```
  Reading the persona from `receipt.run.role` and not from `controls.role` is the
  whole point: a replayed run shows the `SET LOCAL ROLE` **it** issued, even if the
  chip now says something else. The `?? controls.role` covers the pre-first-run
  render where there is no receipt yet.

Prose sites, five, all of which G-11's banned-identity scan (Task 8) currently
fails on:
- `:837` — `the caller principal stayed fixed.` → `the persona stayed fixed.`
- `:897` — `Visible customer impact under the workshop principal.` → `Visible
  customer impact under the analyst persona.`
- `:5544` — `The caller principal is unchanged.` → `The persona is unchanged.`
- `:5575` — `CASE-7419 under the workshop principal` → `CASE-7419 under the
  analyst persona`
- `:5900` — `<small>principal unchanged</small>` → `<small>persona
  unchanged</small>`

- [ ] **Step 11: Typecheck, build, and run the gates**

```bash
cd frontend && npx tsc --noEmit && npx vite build && cd ..
gates/checks.sh G-23
gates/checks.sh G-14
gates/checks.sh G-11
grep -rn 'supportLead\|PrincipalKey\|principalLabel\|PrincipalReceipt' frontend/src
```

Expected: `tsc` silent; `vite build` succeeds; **G-23 PASS** including the bundle
literals (the three persona strings are now in the built JS); G-14 PASS (the
persona labels are not fixture numerals); the final grep prints **nothing**. G-11
should now pass on `frontend/src` — if it still reports hits there, they are prose
this step missed; fix them rather than widening the allowlist.

G-11 may still fail on the sibling-repo guide content and the SPEC copies; those
are Tasks 14 and 15. Record which files remain.

- [ ] **Step 12: Commit**

```bash
git add frontend/src/persona.ts frontend/src/route.ts \
        frontend/src/WorkbenchApp.tsx frontend/src/workbench.css \
        gates/route_contract.py
git commit -m "Replace the identity boolean with the three-persona Viewing-as chip"
```

---

## Task 12: The A3 identity envelope in `_verify_sql`, and the gate that replays it

A3: every `_verify_sql` for a role-sensitive panel emits
`BEGIN; SET LOCAL ROLE persona_<persona>; <SELECT>; ROLLBACK;`. This is what makes
Law 2 hold under RLS: a participant who pastes a panel's SQL into psql must see the
**same rows the panel showed**, which is only true if the paste assumes the panel's
identity.

**The blocker this task exists to solve.** `gates/verify_sql_golden.py:118-122`
replays each descriptor like this:

```python
def _replay(cur, descriptor: dict[str, Any]) -> Any:
    """Execute one ``_verify_sql`` descriptor and return its encoded rows."""
    cur.execute(descriptor["statement"], descriptor["binds"])
    rows = [dict(row) for row in cur.fetchall()]
    return _encode(rows)
```

inside a connection opened `autocommit=False` (`:218-220`) that has already issued
`SET TRANSACTION READ ONLY` (`:222`) and ends in `conn.rollback()` (`:246`). Handing
that a four-statement string breaks it three ways: psycopg's client-side parameter
binding cannot bind `%(run_id)s` across statements it did not parse individually;
`fetchall()` sees only the first result set; and a nested `BEGIN`/`ROLLBACK` inside
an open transaction is a warning-and-no-op, so the gate's own read-only guarantee
would silently depend on a `ROLLBACK` that did nothing.

**The resolution: the envelope is a rendered field, not the executed statement.**
`_descriptor` keeps `statement` as the single, parameterized `SELECT` — the thing
machines execute — and gains `set_role` plus `rendered`, the copy-paste text a human
takes to psql. The gate executes `statement` (unchanged mechanics) and separately
issues `SET LOCAL ROLE` from `set_role` inside its existing transaction, which is
where a `SET LOCAL` belongs anyway.

That keeps one source of truth: the SQL a participant pastes and the SQL the gate
replays are the same `statement` text, wrapped for the human and parameterized for
the machine. If they were two strings, they would drift, and G-13 would be
certifying a statement nobody pastes.

**Files:**
- Modify: `backend/app/verify_sql.py:1-26,129-161`
- Modify: `gates/verify_sql_golden.py:110-130,214-250`
- Test: `backend/tests/test_verify_sql.py` (create)

**Interfaces:**
- Consumes: `db.persona_role()` semantics (Task 7) — but **not** the module:
  `verify_sql.py` must stay import-free of `db` (it is pure string construction and
  is imported by `agent.py` and `insights.py`, both of which already import `db`).
  The role name is derived locally by the same `f"persona_{persona}"` rule, and a
  test asserts the two agree.
- Produces: `_descriptor(statement, binds, *, persona)` → `{"statement", "binds",
  "set_role", "rendered"}`; `receipt_verify_sql(run_id, persona)`,
  `edge_verify_sql(edge_key, persona)`, `event_verify_sql(evidence_id, persona)`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_verify_sql.py`. `unittest.TestCase`, no pytest — see the
note in Task 7 Step 1; `make test` runs `unittest discover`, which cannot see
module-level `def test_*` functions. Unlike Task 7's file, this one carries **no**
skip guard: it is pure string construction and must run everywhere.

```python
"""The _verify_sql descriptor contract (A3 identity envelope).

Pure string construction — no database. These assertions are the reason the
envelope can be trusted: they prove the pasted text and the replayed statement
carry the same SELECT and the same identity.
"""

from __future__ import annotations

import unittest

from backend.app import db, verify_sql


class VerifySqlEnvelopeTests(unittest.TestCase):
    def test_descriptor_carries_the_statement_binds_role_and_rendering(self) -> None:
        descriptor = verify_sql.receipt_verify_sql("rr_9b41d7", "admin")["run"]
        self.assertEqual(descriptor["binds"], {"run_id": "rr_9b41d7"})
        self.assertEqual(descriptor["set_role"], "SET LOCAL ROLE persona_admin")
        self.assertNotIn("SET LOCAL ROLE", descriptor["statement"])
        self.assertTrue(descriptor["statement"].lstrip().upper().startswith("SELECT"))

    def test_rendered_text_is_the_pasteable_envelope(self) -> None:
        rendered = verify_sql.receipt_verify_sql("rr_9b41d7", "auditor")["run"][
            "rendered"
        ]
        lines = [line for line in rendered.splitlines() if line.strip()]
        self.assertEqual(lines[0], "BEGIN;")
        self.assertEqual(lines[1], "SET LOCAL ROLE persona_auditor;")
        self.assertEqual(lines[-1], "ROLLBACK;")

    def test_rendered_text_inlines_the_binds_so_a_paste_runs_as_is(self) -> None:
        rendered = verify_sql.receipt_verify_sql("rr_9b41d7", "analyst")["run"][
            "rendered"
        ]
        self.assertIn("'rr_9b41d7'", rendered)
        self.assertNotIn("%(run_id)s", rendered)

    def test_every_persona_is_accepted_and_nothing_else_is(self) -> None:
        for persona in ("analyst", "admin", "auditor"):
            with self.subTest(persona=persona):
                verify_sql.receipt_verify_sql("rr_1", persona)
        with self.assertRaisesRegex(ValueError, "unknown persona"):
            verify_sql.receipt_verify_sql("rr_1", "support-lead")

    def test_the_role_naming_rule_matches_the_connection_layer(self) -> None:
        """verify_sql derives the role name without importing db; keep them equal."""
        for persona in db.PERSONAS:
            with self.subTest(persona=persona):
                self.assertEqual(
                    verify_sql.persona_role(persona),
                    db.persona_role(persona),
                )

    def test_element_grain_descriptors_carry_the_envelope_too(self) -> None:
        edge = verify_sql.edge_verify_sql("edge-1", "admin")
        event = verify_sql.event_verify_sql(
            "11111111-1111-1111-1111-111111111111", "admin"
        )
        for descriptor in (edge, event):
            with self.subTest(descriptor=descriptor["statement"][:40]):
                self.assertEqual(
                    descriptor["set_role"], "SET LOCAL ROLE persona_admin"
                )
                self.assertEqual(descriptor["rendered"].splitlines()[0], "BEGIN;")
```

Importing `db` at module scope is safe here: `backend/app/db.py` builds its pool
lazily, so the import touches no socket. `test_db_persona.py` (Task 7) already
imports it the same way at module scope and still skips cleanly without a database.

Run:
```bash
.venv/bin/python -m unittest backend.tests.test_verify_sql -v
```
Expected: FAIL — `TypeError: receipt_verify_sql() takes 1 positional argument but 2
were given`.

- [ ] **Step 2: Implement the envelope in `backend/app/verify_sql.py`**

Replace `_descriptor` (`:129-131`) with:

```python
PERSONAS: tuple[str, ...] = ("analyst", "admin", "auditor")


def persona_role(persona: str) -> str:
    """Map a persona to its database role.

    Duplicated from backend.app.db by design: this module is pure string
    construction and is imported by the MCP-facing tool layer, so it must not
    pull in the connection pool. test_verify_sql.py asserts the two agree.

    Args:
        persona: One of PERSONAS.

    Returns:
        The role name the envelope will SET LOCAL ROLE to.

    Raises:
        ValueError: The persona is not one of the three bound values.
    """
    if persona not in PERSONAS:
        raise ValueError(
            f"unknown persona {persona!r}; expected one of {', '.join(PERSONAS)}"
        )
    return f"persona_{persona}"


def _render(statement: str, binds: dict[str, Any], set_role: str) -> str:
    """Render the copy-pasteable envelope for a human (A3).

    The statement is parameterized for psycopg; a paste has no bind mechanism, so
    the values are inlined here — quoted with psycopg's own literal quoting, not
    string formatting, because a bind value can contain a quote.

    ROLLBACK, always: the paste is read-only and idempotent, so a participant can
    run it in the middle of anything without consequence.
    """
    inlined = statement
    for name, value in binds.items():
        inlined = inlined.replace(f"%({name})s", sql.Literal(value).as_string(None))
    body = inlined.strip().rstrip(";")
    return f"BEGIN;\n{set_role};\n{body};\nROLLBACK;"


def _descriptor(
    statement: str,
    binds: dict[str, Any],
    persona: str,
) -> dict[str, Any]:
    """Return one ``_verify_sql`` descriptor.

    Four fields, two audiences. ``statement`` + ``binds`` are what a machine
    executes (G-13 replays them and diffs against the API JSON). ``set_role`` is
    the one identity statement the app issued, which the replayer must issue too.
    ``rendered`` is the pasteable envelope a participant takes to psql.

    Keeping ``statement`` single and parameterized is deliberate: a multi-statement
    string cannot be client-side bound and yields only its first result set, so a
    replayer would silently verify nothing.

    Args:
        statement: One parameterized SELECT.
        binds: Its named parameters.
        persona: The persona whose rows this panel showed.

    Returns:
        The descriptor dict serialized into the API payload as ``_verify_sql``.
    """
    set_role = f"SET LOCAL ROLE {persona_role(persona)}"
    return {
        "statement": statement,
        "binds": binds,
        "set_role": set_role,
        "rendered": _render(statement, binds, set_role),
    }
```

Add the import at the top of the file:

```python
from psycopg import sql
```

`sql.Literal(...).as_string(None)` quotes without a connection — psycopg 3 permits
`None` as the context for literal quoting, which is what makes this usable in a
module that never opens a connection. Verify in the REPL before trusting it:

```bash
.venv/bin/python -c "
from psycopg import sql
print(sql.Literal(\"rr_9b41'd7\").as_string(None))
"
```
Expected: `'rr_9b41''d7'` — the embedded quote doubled. If this raises on the
installed psycopg version, pass the module-level `sql.Literal(value).as_string()`
form the version supports and record which you used; do **not** fall back to
f-string quoting.

Then thread `persona` through the three builders (`:134-160`), each of which gains
a second required parameter and passes it to every `_descriptor` call:

```python
def receipt_verify_sql(run_id: str, persona: str) -> dict[str, dict[str, Any]]:
```
```python
def edge_verify_sql(edge_key: str, persona: str) -> dict[str, Any]:
```
```python
def event_verify_sql(evidence_id: str, persona: str) -> dict[str, Any]:
```

Required, not defaulted. A defaulted persona here would let a panel emit an
`analyst` envelope for rows an `admin` fetched — the panel and the paste would
disagree, which is precisely the Law-2 violation A3 closes.

Update the module docstring (`:1-26`) to name the fourth field. Add after the
existing three-grain description:

```
Every descriptor carries an identity envelope (A3): ``set_role`` is the single
``SET LOCAL ROLE`` the app issued for this panel, and ``rendered`` is the
``BEGIN; SET LOCAL ROLE …; SELECT …; ROLLBACK;`` text a participant pastes. Under
row-level security a SELECT without the role is a different query, so a paste that
omitted it would return different rows than the panel — the pasted proof has to
carry the identity, not just the query.
```

- [ ] **Step 3: Run the test to verify it passes**

Run: `.venv/bin/python -m unittest backend.tests.test_verify_sql -v`
Expected: `Ran 6 tests … OK`.

- [ ] **Step 4: Update the two callers**

```bash
grep -rn 'receipt_verify_sql\|edge_verify_sql\|event_verify_sql' backend gates
```

`backend/app/agent.py` and `backend/app/insights.py` each import from this module
(`agent.py:14`, `insights.py:14`). At every call site pass the persona already in
scope — after Task 10 that is `role` on the request path and `_run_role(run_id)`'s
result on the replay path. The rule is the same as Task 10's checkout rule, and for
the same reason: **the envelope's identity must equal the checkout's identity**, or
the panel and its paste were produced by two different roles.

Read each call site and pass the variable that selected the checkout it sits in.
Do not introduce a new default.

- [ ] **Step 5: Teach G-13 to replay the envelope**

In `gates/verify_sql_golden.py`, replace `_replay` (`:117-122`):

```python
def _replay(cur, descriptor: dict[str, Any]) -> Any:
    """Execute one ``_verify_sql`` descriptor under its own identity.

    The descriptor's ``set_role`` is issued before its ``statement`` so the replay
    runs as the persona the panel ran as. Under RLS the same SELECT returns
    different rows per role, so replaying without the role would diff the API's
    rows against a *different* query's rows and call the mismatch a defect.

    SET LOCAL, not SET: the caller's transaction is rolled back at the end
    (:246), so the role never outlives this descriptor.
    """
    set_role = descriptor.get("set_role")
    if set_role:
        # A savepoint per descriptor: SET LOCAL ROLE persists to the end of the
        # transaction, and the next descriptor may need a different persona.
        cur.execute("SAVEPOINT verify_role")
        cur.execute(set_role)
    try:
        cur.execute(descriptor["statement"], descriptor["binds"])
        rows = [dict(row) for row in cur.fetchall()]
    finally:
        if set_role:
            cur.execute("ROLLBACK TO SAVEPOINT verify_role")
    return _encode(rows)
```

`ROLLBACK TO SAVEPOINT` is what un-does a `SET LOCAL ROLE` mid-transaction —
Postgres restores configuration parameters set inside an aborted subtransaction.
Without it, the first `admin` descriptor would leave the role set for every
descriptor after it, and an `analyst` panel would be verified as `admin`.

Also add an assertion that the envelope is present and single-statement — the gate
should catch a regression that puts a multi-statement string back in `statement`.
After the `_smoke_run_id()` resolution and before the replay loop (around `:230`):

```python
    for panel, descriptor in receipt_sql.items():
        require(
            descriptor["statement"].count(";") == 0,
            f"{panel} _verify_sql.statement contains a ';' — it must be one "
            "parameterized SELECT; the multi-statement envelope belongs in "
            "'rendered', which humans paste and machines never execute",
        )
        require(
            descriptor.get("set_role", "").startswith("SET LOCAL ROLE persona_"),
            f"{panel} _verify_sql is missing its A3 identity envelope",
        )
```

Read the surrounding code to place this correctly — `receipt_sql` is the local name
in `_check_receipt` (`:143-157`), so the loop may belong there rather than at module
scope in `run()`. Put it where `receipt_sql` is actually in scope; do not add a
second fetch.

- [ ] **Step 6: Run G-13**

Run: `gates/checks.sh G-13`

Against a database without `sql/11_roles_rls.sql` applied this reports FAIL with
`permission denied to set role "persona_analyst"` — which is honest, not a gate
bug: the gate is now asserting an identity the database does not have. Against the
scratch database with Task 5 applied it must PASS. Record both outputs, and note in
the report that G-13 has become dependent on the roles existing.

- [ ] **Step 7: Commit**

```bash
git add backend/app/verify_sql.py backend/tests/test_verify_sql.py \
        backend/app/agent.py backend/app/insights.py gates/verify_sql_golden.py
git commit -m "Carry the persona in every verify-SQL descriptor"
```

---

## Task 13: Flip `RESTRICTED_ACL` and seed the restricted cohort (`seed/corpus.py`)

This is Blocker-1 option (a), the resolution the user chose. A7's predicate reads
`acl_visibility = 'workshop' OR pg_has_role(...)`. Today **both** seed constants
carry `visibility: "workshop"` (`seed/corpus.py:12-16`) and restrictedness lives
only in `principals: ["support-lead"]`, so A7's first disjunct would be true for
every row and CASE-7421 would leak to the analyst. This task makes
`acl_visibility` the real classification axis, then grows the restricted cohort
from one row to seven so row filtering and masking are visibly non-trivial.

**Files:**
- Modify: `seed/corpus.py:12-16` (both ACL constants), `:467` (the `support-lead`
  prose), new block after `:545` (the restricted cohort), `:993`
  (background `acl`, unchanged — verified below)
- Modify: `backend/app/search.py:164-232` (`_resolve_fuzzy_probe_tokens`)
- Modify: `backend/scripts/doctor.py:206-221`
- Modify: `backend/scripts/smoke_test.py:110-133`
- Modify: `backend/tests/test_retrieval_integration.py:301-315,544-552`
- Modify: `gates/noun_lint.py` (`SYNONYM_TO_CANONICAL` unchanged; see Step 9)
- Modify: `seed/README.md:14`

**Interfaces:**
- Consumes: `retrieval.sensitive_literals()` and `retrieval.refresh_mask_blob()`
  (Task 6); `get_dict_conn(persona)` (Task 7); `acl_scalars_visible(text, name)`
  (Task 9); `role=` on `SearchRequest` (Task 10).
- Produces:
  - `RESTRICTED_ACL = {"visibility": "restricted", "principals": []}`
  - seven restricted `external_key`s: `CASE-7421` (canonical, unchanged) plus
    `CASE-8102`, `CASE-8137`, `INC-3162`, `INC-4117`, `CHG-6213`, `CHG-3309`
  - three new restricted `account_name` literals, which become
    `retrieval.sensitive_literals()` rows and therefore the A5 mask pattern set

### The measured ID set (do not substitute your own)

Every ID below was measured on the live engine (`pg_trgm` via `show_limit() = 0.3`)
before being written into this plan. **Re-measure if you change one.** The
constraint the design doc states is "no new ID in `CHG-1842`'s trigram
neighborhood — nothing shaped like `CHG-18xx` / `CGH-18xx`", and the runnable form
is G-21 plus `test_fuzzy_arm_recovers_mistyped_identifier`.

Measured against the canonical `CGH-1842` probe:

| New ID | sim to `CGH-1842` | `%` match | Max sim to any canonical noun | nearest |
|---|---|---|---|---|
| `CHG-6213` | 0.0588 | no | 0.2857 | `CHG-1840` |
| `CHG-3309` | 0.0588 | no | 0.2857 | `CHG-1842` |
| `CASE-8102` | 0.0556 | no | 0.3333 | `CASE-7421` |
| `CASE-8137` | 0.0556 | no | 0.3333 | `CASE-7421` |
| `INC-3162` | 0.0000 | no | 0.2857 | `INC-1980` |
| `INC-4117` | 0.0000 | no | 0.2857 | `INC-1980` |

Adding all six (lowercased) to the G-21 gate's self-contained universe and
re-running its two probes on the engine returns **exactly** the values the gate
asserts today: `cgh-1842` → 1 candidate ≥ 0.30 (`chg-1842` at 0.5000, runner-up
`chg-1801` at 0.2000), and `chg-1482` → a 12-way tie in which `chg-1842` (0.3846)
is beaten by `chg-1408` and `chg-1428` (0.5000). G-21 stays green **unchanged** —
this task adds nothing to `gates/fixture_arithmetic.py`, whose universe is
deliberately self-contained (`:18-20`).

**Rejected candidates, and why** — record this in the task report so a reviewer
does not "improve" the set back into a hazard:

- `INC-2093`: 0.5000 similarity and a `%`-match to **both** `INC-2047` and
  `INC-2044`. That is the same magnitude as the canonical `CGH-1842` → `CHG-1842`
  signal (0.5000). A probe near `INC-2047` would return a restricted row's near
  neighbour at the exact score the workshop teaches as "the typo resolved."
- `CASE-74xx` of any number: 0.5385 to every canonical case.
- `CHG-5148`: 0.3846 similarity and a `%`-match to the **D14-banned**
  `CHG-1482`, which would put a new row inside the banned probe's tie set.

`CASE-8102` / `CASE-8137` sit at 0.3333 with a `%`-match to `CASE-7421`. That is
**accepted, not overlooked**, and the reason is measured: the canonical cases
already do this to each other (`CASE-7421` vs `CASE-7424` = 0.6667,
`CASE-7419` vs either = 0.5385), and `CASE-7421` already `%`-matches **45** live
documents. Prefix-sharing similarity within one evidence kind is a pre-existing
property of the corpus, not something these two rows introduce; the invariant that
matters is the `CGH-1842`/`CHG-1842` uniqueness, where both score 0.0556.

Verified on the engine before writing: none of the six keys exists in
`casework.evidence_items`, and none matches G-11's round-number regex
(`gates/noun_lint.py:120-122`).

- [ ] **Step 1: Flip the two ACL constants**

Replace `seed/corpus.py:12-16` with:

```python
# The only classification axis (A7). acl_visibility carries it; the predicate in
# sql/03_search_functions.sql and the RLS policies in sql/11_roles_rls.sql both
# read 'workshop' vs anything-else, and the fail-closed schema default is
# 'restricted' (sql/01_schema.sql:926,942,948,1010).
#
# 'principals' stays as an empty list rather than being deleted: the
# retrieval.documents.acl_principals column and its GIN indexes
# (sql/02_indexes.sql:67-68,119-120) are still populated by the projection at
# backend/app/search_index.py:525, and dropping them is schema churn outside this
# plan. Nothing reads them after Task 9.
WORKSHOP_ACL = {"visibility": "workshop", "principals": []}
RESTRICTED_ACL = {"visibility": "restricted", "principals": []}
```

Then fix the CASE-7421 description at `:465-468`, which names the retired identity:

```python
            "description": (
                "This fictional restricted case shares the incident interval and is "
                "visible only to a role holding the can_see_restricted clearance."
            ),
```

This string is corpus content, so it is indexed and searchable — leaving
`support-lead` in it would keep the retired word alive in the corpus body and fail
G-11 after Task 8 extends it.

- [ ] **Step 2: Verify the background corpus is untouched**

`_background_rows` stamps `"acl": WORKSHOP_ACL` at `:993`, which is now
`{"visibility": "workshop", "principals": []}` — the same value it had before
(only `RESTRICTED_ACL` changed). Confirm no second restricted stamp hides in the
background generator:

```bash
grep -n "RESTRICTED_ACL\|WORKSHOP_ACL" seed/corpus.py
```

Expected exactly four hits: the two definitions, `:152` (`acl or WORKSHOP_ACL`),
`:452` (`acl=RESTRICTED_ACL`), and `:993`. If `RESTRICTED_ACL` appears inside
`_background_rows`, stop — ~15k restricted rows would make the analyst persona see
nothing at all.

- [ ] **Step 3: Add the restricted cohort**

Insert after the `case_commitments` append that closes the commitment block
(`seed/corpus.py:545`, before `postmortem = add_evidence(`). Read that boundary
first (`sed -n '536,550p' seed/corpus.py`) so the insertion lands between two
top-level statements, not inside a literal.

The cohort spans three systems and three evidence kinds, matching the design's
"~6 restricted objects across 2-3 systems / clusters, mixing incident / change /
case kinds". Two cases carry the customer identity that masking redacts; the
incidents and changes carry operator identity, which is the second sensitive class
the design names.

```python
    # ------------------------------------------------------------------
    # Restricted cohort (design section "Restricted-evidence seed").
    #
    # CASE-7421 above remains THE canonical M3 flip noun; these are supporting
    # cast and are never named in a guide checkpoint, a slide, or the canonical
    # question. They exist so row filtering and masking are visibly non-trivial:
    # analyst sees none of the seven, admin sees all seven unmasked, auditor sees
    # all seven with customer identity redacted.
    #
    # Every key here was measured against the CGH-1842 trigram probe before being
    # chosen (max similarity 0.0588, no % match), so D14/G-21 are unaffected.
    # ------------------------------------------------------------------
    restricted_case_regulated = add_evidence(
        "support_case",
        "CASE-8102",
        "Restricted payment-processor escalation",
        "synthetic_support_system",
        incident_declared + timedelta(minutes=21),
        revision="case-8102-update-1",
        acl=RESTRICTED_ACL,
    )
    rows["cases"].append(
        {
            "evidence_id": restricted_case_regulated,
            "case_id": "CASE-8102",
            "account_name": "Cascade Financial (fictional)",
            "support_tier": "Enterprise",
            "severity": "urgent",
            "status": "resolved",
            "opened_at": incident_declared + timedelta(minutes=9),
            "sla_due_at": incident_declared + timedelta(minutes=39),
            "subject": "Restricted settlement write failures",
            "description": (
                "This fictional restricted case reports settlement writes queued "
                "on checkout-prod-cluster-01 during the incident window."
            ),
            "customer_commitment": (
                "Regulator notification is required before any external disclosure."
            ),
        }
    )
    rows["incident_cases"].append(
        {
            "incident_evidence_id": incident,
            "case_evidence_id": restricted_case_regulated,
            "impact": "affected",
            "rationale": "Settlement writes share the cluster and the incident interval.",
        }
    )

    restricted_case_health = add_evidence(
        "support_case",
        "CASE-8137",
        "Restricted clinical-tenant checkout escalation",
        "synthetic_support_system",
        incident_declared + timedelta(minutes=24),
        revision="case-8137-update-1",
        acl=RESTRICTED_ACL,
    )
    rows["cases"].append(
        {
            "evidence_id": restricted_case_health,
            "case_id": "CASE-8137",
            "account_name": "Meridian Health Group (fictional)",
            "support_tier": "Enterprise",
            "severity": "high",
            "status": "pending_customer",
            "opened_at": incident_declared + timedelta(minutes=11),
            "sla_due_at": incident_declared + timedelta(hours=2),
            "subject": "Restricted appointment-booking write failures",
            "description": (
                "This fictional restricted case reports booking writes queued on "
                "checkout-prod-cluster-01 while reads continued."
            ),
            "customer_commitment": (
                "Patient-data handling review must complete before disclosure."
            ),
        }
    )
    rows["incident_cases"].append(
        {
            "incident_evidence_id": incident,
            "case_evidence_id": restricted_case_health,
            "impact": "potentially_affected",
            "rationale": "Booking writes target the same cluster in the same window.",
        }
    )

    restricted_incident_identity = add_evidence(
        "incident",
        "INC-3162",
        "Restricted identity-service credential rotation incident",
        "synthetic_incident_management",
        incident_resolved + timedelta(hours=2),
        revision="inc-3162-final-1",
        acl=RESTRICTED_ACL,
    )
    rows["incidents"].append(
        {
            "evidence_id": restricted_incident_identity,
            "incident_id": "INC-3162",
            "cluster_id": "checkout-prod-cluster-01",
            "severity": "SEV-2",
            "status": "resolved",
            "started_at": incident_started - timedelta(hours=6),
            "mitigated_at": incident_started - timedelta(hours=5),
            "resolved_at": incident_started - timedelta(hours=4),
            "summary": (
                "A restricted credential rotation was executed by on-call operator "
                "Priya Raghavan (fictional) ahead of the checkout incident window."
            ),
            "customer_impact": (
                "No fictional customer-visible impact; the record is restricted "
                "because it names the operator and the rotation procedure."
            ),
            "resolution": (
                "The rotation completed and the superseded credential was revoked."
            ),
        }
    )

    restricted_incident_fraud = add_evidence(
        "incident",
        "INC-4117",
        "Restricted fraud-review queue backlog",
        "synthetic_incident_management",
        incident_resolved + timedelta(hours=3),
        revision="inc-4117-final-1",
        acl=RESTRICTED_ACL,
    )
    rows["incidents"].append(
        {
            "evidence_id": restricted_incident_fraud,
            "incident_id": "INC-4117",
            "cluster_id": "checkout-prod-cluster-01",
            "severity": "SEV-3",
            "status": "resolved",
            "started_at": incident_started - timedelta(hours=3),
            "mitigated_at": incident_started - timedelta(hours=2),
            "resolved_at": incident_started - timedelta(hours=1),
            "summary": (
                "A restricted fraud-review queue backed up while operator "
                "Daniel Okafor (fictional) held the review console open."
            ),
            "customer_impact": (
                "No fictional customer-visible impact; the record is restricted "
                "because it names the reviewer and the detection thresholds."
            ),
            "resolution": "The queue drained after the console session was closed.",
        }
    )

    restricted_change_keys = add_evidence(
        "change",
        "CHG-6213",
        "Restricted key-management configuration change",
        "synthetic_change_management",
        incident_started - timedelta(hours=5),
        revision="chg-6213-closed-1",
        acl=RESTRICTED_ACL,
    )
    rows["changes"].append(
        {
            "evidence_id": restricted_change_keys,
            "change_id": "CHG-6213",
            "cluster_id": "checkout-prod-cluster-01",
            "change_type": "configuration",
            "status": "completed",
            "started_at": incident_started - timedelta(hours=6),
            "completed_at": incident_started - timedelta(hours=5),
            "owner_team": "platform-security",
            "execution_sql": None,
            "description": (
                "Restricted key-management parameter change approved by operator "
                "Priya Raghavan (fictional); the record is restricted because it "
                "names the approver and the parameter."
            ),
            "rollback_plan": "Restore the previous parameter group and restart.",
        }
    )
    rows["incident_changes"].append(
        {
            "incident_evidence_id": restricted_incident_identity,
            "change_evidence_id": restricted_change_keys,
            "relationship": "confirmed",
            "rationale": "The rotation incident was opened for this change.",
        }
    )

    restricted_change_audit = add_evidence(
        "change",
        "CHG-3309",
        "Restricted audit-logging retention change",
        "synthetic_change_management",
        incident_started - timedelta(hours=2),
        revision="chg-3309-closed-1",
        acl=RESTRICTED_ACL,
    )
    rows["changes"].append(
        {
            "evidence_id": restricted_change_audit,
            "change_id": "CHG-3309",
            "cluster_id": "checkout-prod-cluster-01",
            "change_type": "configuration",
            "status": "completed",
            "started_at": incident_started - timedelta(hours=3),
            "completed_at": incident_started - timedelta(hours=2),
            "owner_team": "platform-security",
            "execution_sql": None,
            "description": (
                "Restricted audit-log retention change executed by operator "
                "Daniel Okafor (fictional) before the checkout incident window."
            ),
            "rollback_plan": "Restore the previous retention window.",
        }
    )
    rows["incident_changes"].append(
        {
            "incident_evidence_id": restricted_incident_fraud,
            "change_evidence_id": restricted_change_audit,
            "relationship": "suspected",
            "rationale": "The retention change preceded the review-queue backlog.",
        }
    )
```

**Why the two restricted incidents link only to restricted changes, and never to
`INC-2047`:** `casework.incident_changes` is a canonical edge and
`retrieval.traverse_evidence` walks it. An edge from `INC-2047` to a restricted
change would put a restricted node one hop from the canonical seed. The ACL is
applied per hop, so it would not leak — but the **admin** traversal would then
return a different graph shape than the analyst's for the canonical question, and
the design's constraint 3 (canonical claim coverage stays byte-identical) is easier
to hold and to verify when the restricted subgraph is a separate component. The
restricted **cases** do attach to `INC-2047` through `incident_support_cases`,
exactly as `CASE-7421` already does — that edge is the point of the M3 flip.

Note the `status` and `impact` values: `pending_customer` and
`potentially_affected` are drawn from the CHECK constraints at
`sql/01_schema.sql:104` and `:118`. Using a value outside those sets fails at
insert with a constraint violation, not at review.

- [ ] **Step 4: Fix the fuzzy existence probe — a real leak this seed widens**

`backend/app/search.py:164-232` (`_resolve_fuzzy_probe_tokens`) decides which
identifier tokens get fuzzed. Its docstring (`:168-175`) states the rule:

> Existence is deliberately evaluated without the caller's ACL. Fuzzing a token
> the caller may not read would let the trigram arm return its visible near
> neighbours, which tells the caller that a restricted identifier is indexed.

That reasoning is right and the test at
`test_retrieval_integration.py:411-422` asserts it. **The mechanism breaks under
RLS.** After Task 5, `retrieval.documents` has `FORCE ROW LEVEL SECURITY` and this
query runs under the request persona (Task 10 Step 4 converts `:179` to
`get_dict_conn(request.role)`). RLS filters the `EXISTS` subquery, so for an
analyst the restricted key stops existing, the token becomes a fuzz probe, and the
arm returns its visible near neighbours — precisely the disclosure the docstring
forbids.

This is measured, not theoretical. On the live corpus, fuzzing `CASE-7421`
returns 10 rows, top `CASE-7424` at 0.6667 — and this task adds
`CASE-8102`/`CASE-8137` to that neighbourhood, so the leak gets wider, which is
why the fix lands in this task rather than being deferred.

The fix is to evaluate existence as the **owner**, matching what the docstring
already promises. `get_owner_conn` is Task 7's un-personified checkout; it reads every row because
the owner holds the clearance key:

```python
    # Existence is evaluated as the owner, not as the caller. RLS (sql/11) filters
    # restricted rows out of a persona's view of retrieval.documents, so asking
    # this question as the caller would report a restricted identifier as absent,
    # promote it to a fuzz probe, and let the trigram arm answer with its visible
    # near neighbours. Measured: fuzzing 'CASE-7421' returns CASE-7424 at 0.6667.
    # The arms still apply the ACL to every row they return, so an unreadable
    # exact match yields no rows rather than a near-miss substitute.
    with get_owner_conn(row_factory=dict_row) as connection:
```

Replace the `with get_dict_conn(...) as connection:` line at `:179` with the
above. Import `get_owner_conn` alongside the existing `db` imports and
`dict_row` from `psycopg.rows` if it is not already imported — check first:

```bash
grep -n "^from\|^import" backend/app/search.py | head -20
```

**This supersedes Task 10 Step 4's instruction for `:179`.** Task 10 says
"this function takes `request`; use `request.role`". That is wrong for this one
checkout, for the reason above. When you reach this step, if Task 10 already
applied `request.role` there, change it. Record the supersession in the task
report so the reviewer sees it as deliberate.

Add the regression test to `backend/tests/test_retrieval_integration.py`, beside
the existing probe test:

```python
    def test_restricted_identifier_is_not_fuzzed_under_the_analyst_persona(self) -> None:
        """A restricted key must not become a fuzz probe just because RLS hides it.

        If existence were evaluated under the caller's persona, RLS would report
        the key as absent, the trigram arm would fuzz it, and the caller would
        receive its visible near neighbours -- disclosing that the identifier is
        indexed.
        """
        from backend.app.models import SearchRequest
        from backend.app.search import _resolve_fuzzy_probe_tokens

        for key in ("CASE-7421", "CASE-8102", "INC-3162", "CHG-6213"):
            request = SearchRequest(query=f"What happened on {key}?", role="analyst")
            self.assertEqual(
                _resolve_fuzzy_probe_tokens(request, [key]),
                [],
                f"{key} is restricted and must never be fuzzed",
            )
```

- [ ] **Step 5: Rewrite the `doctor.py` ACL fixture check**

`backend/scripts/doctor.py:206-221` asserts restrictedness through the retired
array. Read the whole check first (`sed -n '205,230p' backend/scripts/doctor.py`).
Replace the query and the condition with:

```python
    cursor.execute(
        """
        SELECT external_key, coalesce(acl ->> 'visibility', 'restricted') AS visibility
        FROM casework.evidence_items
        WHERE coalesce(acl ->> 'visibility', 'restricted') = 'restricted'
          AND NOT is_deleted
        ORDER BY external_key
        """
    )
    restricted = cursor.fetchall()
    restricted_keys = [row["external_key"] for row in restricted]
    if "CASE-7421" not in restricted_keys:
        doctor.fail(
            "ACL fixture",
            "CASE-7421 is not marked restricted; the M3 role flip has nothing to show",
        )
    elif len(restricted_keys) < 2:
        doctor.fail(
            "ACL fixture",
            "only CASE-7421 is restricted; reseed to load the restricted cohort",
        )
    else:
        doctor.ok(
            "ACL fixture",
            f"{len(restricted_keys)} restricted evidence items "
            f"({', '.join(restricted_keys)}) before retrieval and traversal",
        )
```

Two assertions, not one: the canonical noun must be restricted (the flip depends
on it), and the cohort must have loaded (a partial seed that dropped the new rows
is a silent regression). It deliberately does **not** hard-code 7 — this check runs
against whatever the account seeded, and `casework.admit_evidence` can legitimately
add more.

Note `doctor.py` reads casework as the owner today, and Task 10 Step 11 converts
`:306` to `get_dict_conn("analyst")`. **Under the analyst persona this query
returns zero rows** — RLS is doing its job. Keep this check on the owner
connection: `doctor` is a build-time readiness tool that must see the corpus as it
was seeded. Verify which connection the check runs on before editing, and if it
sits inside the analyst-persona block, move it into a `get_owner_conn()` block.
Record which you did.

- [ ] **Step 6: Rewrite the `smoke_test.py` ACL assertion**

`backend/scripts/smoke_test.py:110-133` builds two `SearchRequest`s that differ by
`principal`. Task 10 Step 11 replaces it with a two-persona count comparison
against `casework.evidence_items`. That is the right shape; this step extends it to
cover the arms too, because a count on the base table proves RLS while the workshop
claim is about **retrieval**:

```python
    # The ACL is enforced by the engine, so prove it by disagreement: the same
    # query under two personas must return different results. The count proves RLS
    # at the table; the search proves it survives the arms and fusion.
    restricted_keys_seen = {}
    for persona in ("analyst", "admin"):
        result = run_hybrid_search(
            SearchRequest(
                query="restricted regulated account checkout escalation",
                mode="lexical",
                role=persona,
                rerank=False,
                limit=20,
            )
        )
        restricted_keys_seen[persona] = _keys(result)
        receipts.setdefault("acl_run_ids", []).append(result["run_id"])

    _require(
        "CASE-7421" not in restricted_keys_seen["analyst"],
        "restricted case leaked to the analyst persona",
    )
    _require(
        "CASE-7421" in restricted_keys_seen["admin"],
        "the admin persona could not retrieve the restricted case",
    )
    _require(
        restricted_keys_seen["admin"] > restricted_keys_seen["analyst"],
        "the admin result set does not strictly contain the analyst's; "
        "row filtering is not the only difference between the personas",
    )
```

`>` on two sets is Python's proper-superset operator, which is the assertion that
matters: admin sees strictly more, and everything the analyst sees is also visible
to admin. A plain count comparison would pass even if the two personas saw
disjoint sets.

Read the surrounding function before editing to confirm `_keys` returns a set and
that `receipts` is in scope (`sed -n '55,140p' backend/scripts/smoke_test.py`). If
`_keys` returns a list, wrap both sides in `set(...)`.

- [ ] **Step 7: Rewrite the two integration assertions**

`test_retrieval_integration.py:301-315` (traversal) and `:544-552` (lexical arm)
both build the retired identity bag. Task 10 Step 12 gives the mechanical mapping
(`principal={...}` → `role="<persona>"`, `"support-lead"` → `"admin"`). Apply it,
then extend each to the cohort so the tests fail if the seed silently regresses:

```python
    def test_relationship_traversal_enforces_acl(self) -> None:
        from backend.app.agent import follow_evidence_links_impl

        analyst = follow_evidence_links_impl(["INC-2047"], role="analyst", max_depth=2)
        admin = follow_evidence_links_impl(["INC-2047"], role="admin", max_depth=2)

        analyst_keys = {row["external_key"] for row in analyst["reached"]}
        admin_keys = {row["external_key"] for row in admin["reached"]}

        for key in ("CASE-7421", "CASE-8102", "CASE-8137"):
            self.assertNotIn(key, analyst_keys)
            self.assertIn(key, admin_keys)
        self.assertTrue(
            analyst_keys < admin_keys,
            "the analyst's reachable set must be a strict subset of the admin's",
        )
```

`CASE-8102` and `CASE-8137` are reachable from `INC-2047` through
`incident_support_cases` (Step 3 links both), so they belong in the traversal
assertion. The restricted incidents and changes are **not** reachable from
`INC-2047` by design (Step 3's note), so they are deliberately absent here — do not
add them, the test would fail and the fix would be to add the very edge Step 3
argues against.

For the lexical arm at `:544-552`, the call loses `p_principal` entirely (Task 9
dropped the parameter) and the identity comes from the role the test's connection
holds. Replace the two-query block with:

```python
        def visible_keys(persona: str) -> set[str]:
            with self.conn.cursor() as cursor:
                cursor.execute(f"SET LOCAL ROLE persona_{persona}")
                cursor.execute(
                    """
                    SELECT external_key
                    FROM retrieval.full_text_search(%s, p_limit => 50)
                    """,
                    (query,),
                )
                return {row["external_key"] for row in cursor.fetchall()}

        with self.conn.transaction():
            analyst = visible_keys("analyst")
        with self.conn.transaction():
            admin = visible_keys("admin")

        self.assertNotIn("CASE-7421", analyst)
        self.assertIn("CASE-7421", admin)
```

`SET LOCAL ROLE` requires a transaction — outside one it silently behaves as a
session `SET ROLE` and leaks the role into the next test through the shared
connection. The `with self.conn.transaction():` wrappers are what scope it. Read
the test's existing setup to confirm `self.conn` is autocommit; if it is, each
`with ... transaction()` opens a real block and the `SET LOCAL` is correctly
scoped.

- [ ] **Step 8: Reseed a disposable database and verify end to end**

Never against live. Use the scratch pattern from Task 5 Step 6 and the hash
embedding provider, so this costs no Bedrock calls:

```bash
SCRATCH_URL="postgresql://localhost:55432/rls_seed_scratch?sslmode=disable"
createdb -h localhost -p 55432 rls_seed_scratch
DATABASE_URL="$SCRATCH_URL" make schema
DATABASE_URL="$SCRATCH_URL" .venv/bin/python backend/scripts/build_search_index.py \
  --load-casework --offline-capture --provider hash --embed-missing \
  --background-documents 200
```

`--background-documents 200` is `LOCAL_BACKGROUND_DOCUMENTS` (`Makefile:15`); the
full 15k adds nothing this step measures. Then assert the cohort landed and the
mask regenerated:

```bash
DATABASE_URL="$SCRATCH_URL" .venv/bin/python -c "
from backend.app.db import get_owner_conn
from psycopg.rows import dict_row
with get_owner_conn(row_factory=dict_row) as conn, conn.cursor() as cur:
    cur.execute('''
      SELECT external_key, evidence_kind
        FROM casework.evidence_items
       WHERE coalesce(acl->>'visibility','restricted') = 'restricted'
         AND NOT is_deleted ORDER BY external_key''')
    rows = cur.fetchall()
    print(f'restricted evidence items: {len(rows)}')
    for r in rows: print('  ', r['external_key'], r['evidence_kind'])
    cur.execute('SELECT literal FROM retrieval.sensitive_literals() ORDER BY 1')
    lits = [r['literal'] for r in cur.fetchall()]
    print(f'sensitive literals: {len(lits)}')
    for l in lits: print('  ', l[:60])
    cur.execute('''
      SELECT count(*)::int AS n FROM retrieval.documents
       WHERE is_current AND acl_visibility = %s''', ('restricted',))
    print('projected restricted documents:', cur.fetchone()['n'])
"
```

Expected: **7** restricted evidence items (`CASE-7421`, `CASE-8102`, `CASE-8137`,
`CHG-3309`, `CHG-6213`, `INC-3162`, `INC-4117`); **9** sensitive literals (three
`account_name`, three `customer_commitment`, three `description` values from the
three restricted **cases** — `sensitive_literals()` reads
`casework.support_cases` only, so the restricted incidents and changes contribute
none); **7** projected restricted documents.

**The literal count is the tell for a real gap, so read it rather than tick it.**
`retrieval.sensitive_literals()` (Task 6) selects from `support_cases` alone, but
this task seeds operator names into `casework.incidents.summary` and
`casework.changes.description`, which the projection renders into
`chunk_text`. `retrieval.mask_blob` therefore will **not** redact
"Priya Raghavan (fictional)" or "Daniel Okafor (fictional)" from the auditor's
`chunk_text`. Two ways to close it:

- **(a) Extend `sensitive_literals()`** to union the incident and change columns.
  Correct, and it makes the operator names maskable. It edits a Task 6
  deliverable, so record it as a cross-task change in both reports.
- **(b) Drop the operator names** from the four restricted incident/change strings,
  leaving those rows sensitive by classification rather than by content.

**Take (a).** The design's constraint 4 names "on-call / operator identities on
incident records" as a mask target explicitly, so (b) would silently drop a stated
requirement. Extend the function in `sql/12_masking.sql`:

```sql
CREATE OR REPLACE FUNCTION retrieval.sensitive_literals()
RETURNS TABLE (literal text)
LANGUAGE sql
STABLE
AS $$
  SELECT DISTINCT v.literal
    FROM casework.evidence_items e
    LEFT JOIN casework.support_cases sc ON sc.evidence_id = e.evidence_id
    LEFT JOIN casework.incidents i      ON i.evidence_id = e.evidence_id
    LEFT JOIN casework.changes ch       ON ch.evidence_id = e.evidence_id
    CROSS JOIN LATERAL (
      VALUES (sc.account_name), (sc.customer_commitment), (sc.description),
             (i.summary), (i.customer_impact),
             (ch.description)
    ) AS v(literal)
   WHERE coalesce(e.acl ->> 'visibility', 'restricted') = 'restricted'
     AND NOT e.is_deleted
     AND v.literal IS NOT NULL
     AND length(v.literal) > 0
   ORDER BY 1
$$;
```

Then re-run the check: **15** literals (9 case + 4 incident + 2 change), and
`SELECT retrieval.refresh_mask_blob();` returns 15. The whole-string literals are
what get redacted, which over-masks (the auditor sees `[REDACTED]` for an entire
summary rather than just the name) — that is the correct direction of error for a
governance demo, and it is why `refresh_mask_blob`'s initial body masks everything.

- [ ] **Step 9: Confirm G-11 and G-21 both stay green**

```bash
.venv/bin/python gates/noun_lint.py
DATABASE_URL="$SCRATCH_URL" .venv/bin/python gates/fixture_arithmetic.py
```

G-11: the six new keys are not in `SYNONYM_TO_CANONICAL` and none matches
`ROUND_NUMBER_RE` (verified on the engine before this plan was written), so this
gate needs **no edit**. If it fails, the failure is the `support-lead` string in
Step 1's description edit — read the hit rather than adding an exemption.

G-21: measures its own self-contained universe (`gates/fixture_arithmetic.py:55-68`)
and never reads the corpus, so it is unaffected by the seed. It must still report
PASS with `'cgh-1842'->chg-1842 unique at 0.5000`. Run it anyway: it is the
cheapest possible proof that the reseed did not disturb `pg_trgm`.

Then the live-arm form of the same invariant, which **does** read the corpus:

```bash
DATABASE_URL="$SCRATCH_URL" .venv/bin/python -c "
from backend.app.db import get_owner_conn
from psycopg.rows import dict_row
with get_owner_conn(row_factory=dict_row) as conn, conn.cursor() as cur:
    cur.execute('SELECT external_key, round(score,4) AS score '
                'FROM retrieval.fuzzy_search(%s::text[], p_limit => 5)',
                (['CGH-1842'],))
    rows = cur.fetchall()
    for r in rows: print(r['external_key'], r['score'])
    assert len(rows) == 1, f'expected 1 candidate, got {len(rows)}'
    assert rows[0]['external_key'] == 'CHG-1842'
    print('OK: CGH-1842 still resolves uniquely to CHG-1842 on the enlarged corpus')
"
```

Expected: one row, `CHG-1842 0.5000`. This is the assertion the design's
constraint 1 actually demands, measured against the enlarged corpus. Baseline for
comparison, measured on live before this task: one row, `CHG-1842 0.5000`.

- [ ] **Step 10: Verify the canonical answer is byte-identical (design constraint 3)**

Every new row is restricted, so nothing the analyst sees can change. Prove it
rather than assert it. With the API running against the scratch database:

```bash
curl -s localhost:8000/v1/agent/answer -H 'content-type: application/json' \
  -d '{"question":"<the canonical question, read from the guide>","role":"analyst"}' \
  | jq -S '{answer, citations: [.citations[] | {external_key, claim, quote_text}]}' \
  > /tmp/canonical_after_seed.json
diff /tmp/canonical_after_collapse.json /tmp/canonical_after_seed.json
```

`/tmp/canonical_after_collapse.json` is the artifact Task 10 Step 14 produced. An
empty diff is the pass. **Any difference means a restricted row entered the
analyst's answer: stop and report** — that is a genuine ACL failure, not a golden
that needs updating.

- [ ] **Step 11: Update `seed/README.md`**

`seed/README.md:14` reads `- CASE-7421: relevant evidence restricted to support-lead.`
Replace with:

```markdown
- `CASE-7421`: relevant evidence classified `restricted`, plus a six-object
  restricted cohort (`CASE-8102`, `CASE-8137`, `INC-3162`, `INC-4117`,
  `CHG-6213`, `CHG-3309`) spanning three evidence kinds. Visibility is decided by
  `acl.visibility` and the `can_see_restricted` clearance, never by a
  caller-supplied identity.
```

- [ ] **Step 12: Drop the scratch database and commit**

```bash
dropdb -h localhost -p 55432 rls_seed_scratch
git add seed/corpus.py seed/README.md sql/12_masking.sql backend/app/search.py \
        backend/scripts/doctor.py backend/scripts/smoke_test.py \
        backend/tests/test_retrieval_integration.py
git commit -m "Classify restricted evidence by visibility and seed the cohort"
```

**Live deployment is NOT part of this task.** The live `retrieval` database holds
the shipped corpus and its 192 MB Bedrock embedding cache; reseeding it needs a
`--verify-cache` run whose manifest (`entry_count: 15017`) will no longer match a
corpus with seven more documents. Task 16 owns the live sequence and the
explicit go-ahead gate. Record in the task report that live is untouched and that
`seed/artifacts/casework-embeddings.jsonl.manifest.json` will need regenerating
with `--write-cache-manifest --embed-missing` (7 new documents → a small number of
new Bedrock embedding calls, since chunk text is deduplicated by hash).

---
## Task 14: Rewrite the participant-facing narrative (app-repo docs + sibling guide)

Every earlier task changed a mechanism. This task changes what a participant is
**told** — and it is where the vocabulary collapse either lands or fails, because
five app-repo documents still describe the retired two-axis model in prose that
G-11 scans.

The design doc's guide requirements are: the app flip is first and the psql coda
second (A4); the coda is A3's transaction envelope, not the deleted GUC; the
teaching line is *"You never grant a limitation — you withhold a key"* (A8); and
the M3 checkpoint copy says "Viewing as", never "Sign in as".

**Files:**
- Modify: `SECURITY_REVIEW.md:71-86`
- Modify: `docs/data-model.md:91,107-120`
- Modify: `docs/architecture.md:88,96-98`
- Modify: `docs/implementation-spec.md:69,76,152-162,281,419,561,706-707`
- Modify: `docs/builder-session-flow.md:34,121`
- Modify (sibling repo `build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql/`):
  `content/00-introduction/index.en.md:66-82`,
  `content/40-module-3-prove-portable-tool-contract/index.en.md` (new section),
  `content/index.en.md` (session-map row + module-3 outcome),
  `content/90-appendix/02-facilitator-notes/index.en.md:19` (pacing row),
  `FACILITATOR_GUIDE.md:20,146-154`

**Interfaces:**
- Consumes: the persona names and predicate from Task 5, the masking behaviour
  from Task 6, `?role=` from Task 11, the A3 envelope from Task 12, and the seven
  restricted keys from Task 13.
- Produces: no code. The guide snippets it writes are what G-11 and a facilitator
  read; there is nothing downstream but the room.

### The trap this task exists to catch

`gates/noun_lint.py:47-63` lists `docs` in `SCAN_ROOTS` and scans `.md`
recursively (`:75-90`). Task 8 Step 6 adds `BANNED_IDENTITY_RE` matching a bare
`principal` and `support-lead`. Task 8 Step 7 therefore predicts a FAIL and lists
the code sites — **but its list is backend/frontend only.** Verified by
word-boundary grep before writing this task, these five documents also carry live
hits:

| File | Hits | Nature |
|---|---|---|
| `docs/implementation-spec.md` | 8 | Sections 2, 4 (ACL fixture), 6, 9 (proof tables), 12 (Investigate controls), 15 (acceptance) |
| `docs/data-model.md` | 4 | proof-table row + the whole "ACL Model" section |
| `SECURITY_REVIEW.md` | 4 | the "Evidence ACLs" section |
| `docs/architecture.md` | 2 | proof-layer question + retrieval-path predicate |
| `docs/builder-session-flow.md` | 2 | minute-by-minute row + expected-outputs line |

So **G-11 cannot go green until this task runs**, and this task is #14 of 16. That
is intentional and must be stated in the task report: G-11 stays FAIL from Task 8
through Task 13, and Task 14 is what turns it green. If a reviewer sees a red G-11
after Task 12 and "fixes" it by adding `docs/` to an allow-list, the vocabulary
collapse silently stops at the code boundary and the participant still reads
`support-lead`. Do not do that.

`docs/superpowers/plans/*.md` and `docs/superpowers/specs/*.md` also carry the
tokens — including this plan. Handle that in Step 6, not by weakening the scan.

- [ ] **Step 1: Rewrite the app-repo ACL prose (5 files)**

These read as reference material, not participant copy, but they are the
canonical description of the mechanism and G-11 scans them.

`SECURITY_REVIEW.md` — replace the "Evidence ACLs" body (`:71-86`) with:

```markdown
Each evidence item and indexed document carries an `acl` JSONB whose
`visibility` is either `workshop` or `restricted`. Enforcement is layered:

- **Row-level security** (`sql/11_roles_rls.sql`) is enabled and **forced** on
  `casework.evidence_items`, `retrieval.documents`, and `retrieval.chunks`. One
  policy expression governs all three:
  `acl_visibility = 'workshop' OR pg_has_role(current_user, 'can_see_restricted', 'USAGE')`.
- **The explicit predicate** `retrieval.acl_visible(acl)` runs inside every
  retrieval arm and at every traversal hop, so the planner filters early and a
  pasted verify-SQL statement returns the same rows without a hidden session
  prerequisite.
- **Column masking** (`sql/12_masking.sql`) redacts customer and operator
  identity for `persona_auditor` only.

Identity is a **persona**, one of `analyst`, `admin`, or `auditor`. Personas are
`NOLOGIN` database roles; the app pool connects as `workshop_app`, which holds no
table grants, and issues one `SET LOCAL ROLE persona_<persona>` per request
transaction. With no role set, a `SELECT` raises `permission denied` — the pool
identity has no standing privilege path.

Clearance is additive: the `can_see_restricted` role is GRANTed to
`persona_admin` and `persona_auditor`, never to `persona_analyst`. Restricted
evidence — `CASE-7421` and six supporting objects — is invisible to the analyst
at the table, not merely absent from a result set.

This is a teaching policy, not a complete enterprise authorization system. RLS
moves *enforcement* into the database; **which persona a request assumes is still
asserted by the application**, because this workshop ships no authentication. A
production system must authenticate the caller, map current source-system
authorization into the persona decision, and revalidate live when indexed ACL
metadata may be stale.
```

The last paragraph is load-bearing and comes from the design's non-goals: RLS
strengthens enforcement, not authentication. Do not let the rewrite drift into
implying the workshop authenticates anyone.

`docs/data-model.md` — `:91` `principal` → `persona` in the `retrieval_runs` row;
replace the "ACL Model" section (`:107-120`) with:

```markdown
## ACL Model

Every evidence item carries:

```json
{
  "visibility": "workshop"
}
```

`visibility` is the only classification axis. It is projected to the sargable
column `retrieval.documents.acl_visibility` (and `retrieval.chunks`), which both
the RLS policy and `retrieval.acl_visible` read. Anything other than `'workshop'`
is restricted, and the schema default is `'restricted'` so an unclassified row
fails closed.

Identity is the caller's persona — `analyst`, `admin`, or `auditor` — carried as a
database role, never as a value in the request body. `CASE-7421` and the six
restricted objects seeded alongside it are visible only to a persona holding the
`can_see_restricted` clearance, and they must not enter any retrieval arm,
traversal hop, comparison, or answer for the analyst.

The JSONB policy is intentionally small for teaching. A production design should
map authenticated identity and source-system authorization into a reviewed policy,
and revalidate permissions live when indexed ACL metadata is not sufficient.
```

`docs/architecture.md` — `:88` "Which query, filters, principal, model space" →
"Which query, filters, persona, model space"; `:96-98`
`retrieval.acl_visible(document.acl, principal)` → `retrieval.acl_visible(document.acl)`
with one added sentence: *"The predicate reads the caller's effective database
role, so nothing in the request body can widen it."*

`docs/implementation-spec.md` — eight sites, each a token swap plus one block:
- `:69` "hidden from the default principal" → "hidden from the analyst persona"
- `:76` "filters, principal, retrieval controls" → "filters, persona, retrieval controls"
- `:152-162` replace the whole "ACL fixture" subsection:

```markdown
### ACL fixture

The default evidence ACL is:

```json
{"visibility":"workshop","principals":[]}
```

`principals` is retained as an empty list only because
`retrieval.documents.acl_principals` and its GIN indexes are still projected; no
code reads it. `visibility` is the classification.

Seven objects are `{"visibility":"restricted"}`: `CASE-7421` (the canonical ACL
proof), `CASE-8102`, `CASE-8137`, `INC-3162`, `INC-4117`, `CHG-6213`, and
`CHG-3309`. They are visible only to a persona holding `can_see_restricted`
(`admin`, `auditor`), never to `analyst`. RLS enforces this at the three read
tables; `retrieval.acl_visible` applies the same expression inside every arm and
at every traversal hop.
```

- `:281` "caller principal" → "caller persona"
- `:419` "filters, principal, models" → "filters, persona, models"
- `:561` "model-rerank and support-lead toggles" → "model-rerank control and the
  Viewing-as persona selector"
- `:706-707` replace both lines:

```markdown
- `CASE-7421` and the six supporting restricted objects never enter analyst
  retrieval or traversal, and return zero rows at the raw table.
- The `admin` persona retrieves the restricted fixtures; the `auditor` persona
  retrieves them with customer and operator identity masked.
```

`docs/builder-session-flow.md` — `:34` "apply `cluster_id` and ACL before ranking"
is already clean; `:121` becomes:

```markdown
- The `analyst` persona cannot retrieve or traverse `CASE-7421`, and the row is
  invisible to it at `casework.evidence_items` itself.
```

- [ ] **Step 2: Fix the sibling guide's introduction SQL shape**

`content/00-introduction/index.en.md:66-82` prints the fusion CTE with
`p_principal => p_principal` twice. Task 9 removes that parameter, so the guide
would print a signature the engine rejects. Replace both call sites:

```sql
  FROM retrieval.full_text_search(
    p_query,
    p_limit => 50
  )
```

```sql
  FROM retrieval.vector_search(
    p_query_embedding,
    p_limit => 50
  )
```

Then add one sentence after the CTE's closing prose, where the page already says
"The production function applies filters and ACLs inside each arm before this
fusion step":

```markdown
The ACL is not a parameter. Each arm reads the caller's effective database role,
so a request cannot widen its own visibility by editing a field.
```

Verify the edit against the real function signature rather than trusting this
plan — Task 9 is the authority:

```bash
grep -n "CREATE OR REPLACE FUNCTION retrieval.full_text_search" -A 8 \
  ../sample-agentic-hybrid-retrieval-aurora-postgresql/sql/03_search_functions.sql
```

- [ ] **Step 3: Write the M3 persona beat into Module 3**

Module 3 today is entirely AgentCore Gateway
(`content/40-module-3-prove-portable-tool-contract/index.en.md`, 10 min). The M3
ACL flip is a **protected moment** in SPEC-session D18 and currently appears in no
guide page at all. Insert this as a new section between the existing "3. Inspect
the contract you can take with you" and "## Checkpoint".

The order is A4's: app flip first (the moment), psql coda second (the proof).

```markdown
## 4. Change who is asking

Entitlements do not live in the agent, the API, or the prompt. They live in the
database, and they apply at every retrieval arm and every traversal hop.

In **`WorkbenchURL`**, search for:

```text
Northstar premium checkout escalation
```

Note the evidence rail. Then use the **Viewing as** selector to switch from
**Analyst** to **Admin** and run the same search again.

A support case appears — `CASE-7421` — that the analyst could not see. Nothing
about the query changed. The only difference is which database role the request
assumed.

Switch once more to **Auditor**. `CASE-7421` is still there, but the account name
and the customer commitment now read `[REDACTED]`. The auditor is cleared to know
the case exists and cleared to read its technical content; it is not cleared to
read the customer's identity.

:::alert{type="info" header="Viewing as is a mirror, not a power"}
The selector does not grant you anything. It tells the application which persona
to assume, and the database decides what that persona may read. This workshop
ships no authentication — a production system authenticates the caller and derives
the persona. What RLS moves into the database is *enforcement*, not *identity*.
:::

### The coda: prove it at the table

The app could be lying to you. Check the database directly. Every statement below
is read-only and rolls back.

```bash
psql "$DATABASE_URL" <<'SQL'
BEGIN;
SET LOCAL ROLE persona_analyst;
SELECT external_key, evidence_kind
  FROM casework.evidence_items
 WHERE external_key = 'CASE-7421';
ROLLBACK;

BEGIN;
SET LOCAL ROLE persona_admin;
SELECT external_key, evidence_kind
  FROM casework.evidence_items
 WHERE external_key = 'CASE-7421';
ROLLBACK;
SQL
```

Expected:

```text
 external_key | evidence_kind
--------------+---------------
(0 rows)

 external_key | evidence_kind
--------------+---------------
 CASE-7421    | support_case
(1 row)
```

No retrieval arm. No API. No agent. A bare `SELECT` on the authoritative table,
and the database returns nothing to the analyst. That is
`FORCE ROW LEVEL SECURITY` plus one policy:

```bash
psql "$DATABASE_URL" -c "
  SELECT tablename, policyname, qual
    FROM pg_policies
   WHERE schemaname IN ('casework','retrieval')
   ORDER BY tablename;
"
```

Read the `qual` column. It is the same expression in all three policies:

```sql
acl_visibility = 'workshop'
  OR pg_has_role(current_user, 'can_see_restricted', 'USAGE')
```

`SET LOCAL`, never a session `SET`: the role is scoped to the transaction and
cannot leak to the next request that borrows the same pooled connection.

Now look at how the analyst is denied:

```bash
psql "$DATABASE_URL" -c "
  SELECT r.rolname,
         pg_has_role(r.rolname, 'can_see_restricted', 'USAGE') AS has_clearance
    FROM pg_roles r
   WHERE r.rolname LIKE 'persona_%'
   ORDER BY r.rolname;
"
```

`persona_analyst` is `false`. There is no rule anywhere that says "the analyst
cannot see restricted evidence." There is only a key the analyst was never given.

:::alert{type="info" header="You never grant a limitation — you withhold a key"}
A deny marker has to be remembered on every new table, every new query, every new
arm. A missing grant is enforced by absence. When you design entitlements, make
the safe state the one that requires no action.
:::

The explicit predicate and RLS are both present on purpose. The predicate is how
the arm filters — it is index-sargable, visible in `EXPLAIN`, and it makes a
pasted verify-SQL statement self-contained. RLS is why you cannot leak even when
you forget one. Real systems want both.
```

Two things to check while writing this, because both are dependencies on earlier
tasks and both would produce a guide that lies:

1. **The search query must actually surface `CASE-7421` for admin.** Task 13
   Step 6's smoke assertion uses "restricted regulated account checkout
   escalation". The query above ("Northstar premium checkout escalation") is the
   one `smoke_test.py:100-130` uses today, and it is a proven hit for CASE-7421.
   Run it under both personas before shipping the copy:

```bash
for persona in analyst admin auditor; do
  echo "--- $persona ---"
  curl -s localhost:8000/v1/search -H 'content-type: application/json' \
    -d "{\"query\":\"Northstar premium checkout escalation\",\"role\":\"$persona\",\"limit\":10}" \
    | jq -r '.results[] | .external_key'
done
```

   Expected: `CASE-7421` absent for analyst, present for admin and auditor. If it
   is absent for admin too, the query is wrong for the enlarged corpus — find one
   that works and update the copy. Do not ship a checkpoint you did not run.

2. **`$DATABASE_URL` in the participant's shell is `workshop_app`**, which is
   `NOLOGIN`-adjacent by design: it can log in but holds no table grants. Both
   `SET LOCAL ROLE` blocks work because `workshop_app` is GRANTed the personas.
   But the participant terminal may instead hold `workshop_participant` (A1).
   Confirm which DSN the guide's `.env` exposes, and if it is
   `workshop_participant`, verify it too is GRANTed all three personas — Task 5
   grants them `WITH INHERIT FALSE`, which permits `SET ROLE`. Record which
   identity you verified against.

- [ ] **Step 4: Reconcile the timing, in four places**

Module 3 is 10 minutes and the required blocks total **exactly** 60. The new
section is a ~4-minute beat: two searches in the app, one heredoc, two catalog
queries. It has to come out of somewhere.

Take it from Module 3's own control-plane inspection, which is already the
designated cut (`FACILITATOR_GUIDE.md:153`: "Module 3: run
`scripts/invoke_agentcore_gateway.py --assert-orion`; skip the control-plane
inspection"). The persona beat is a protected moment (D18) and the control-plane
check is not, so the persona beat is strictly more important than the section it
displaces.

Update all four surfaces that publish the timing — they are separate files and
they drift silently:

1. `content/index.en.md` session-map row for Module 3: outcome becomes "Return a
   real Aurora retrieval run through AgentCore Gateway, then change who is asking
   and watch the database refuse". Keep `10 min`.
2. `content/40-module-3-prove-portable-tool-contract/index.en.md:6` info-box
   header: "~10 min - cross a real AgentCore Gateway boundary, then prove
   entitlements live in the database".
3. `content/90-appendix/02-facilitator-notes/index.en.md:19` Module 3 pacing row:
   "Must land" gains "`CASE-7421` appears for admin and returns 0 rows for analyst
   at the raw table"; "Cut rule" becomes "run the managed client; skip the
   control-plane inspection and the `pg_policies` query — never cut the persona
   flip".
4. `FACILITATOR_GUIDE.md:20` exact-timing row for `00:45-00:55` and the cut rule
   at `:153`, matching (3).

**Verify the arithmetic after editing** — the guide asserts "exactly 60 minutes"
in three places and a stale sum is the kind of error a room notices:

```bash
grep -rn "exactly 60 minutes\|total exactly" content/ FACILITATOR_GUIDE.md
```

5 + 6 + 17 + 17 + 10 + 5 = 60. Module 3's internal budget changes; the block
total does not.

- [ ] **Step 5: Add the checkpoint bullets**

Module 3's `## Checkpoint` list gains three lines, and the closing success box
gains one clause:

```markdown
- switching **Viewing as** from Analyst to Admin makes `CASE-7421` appear, with
  no change to the query
- the Auditor persona sees the case with customer identity `[REDACTED]`
- a bare `SELECT` on `casework.evidence_items` returns 0 rows for
  `persona_analyst` and 1 row for `persona_admin`
```

```markdown
:::alert{type="success" header="Managed contract proved"}
You invoked the Aurora retrieval contract through a real AgentCore Gateway and
kept the same run receipt, ranked rows, and scores — then proved that the rows any
caller may see are decided by the database, not by the application. Continue to
the [Summary: What you take with you](/50-summary/).
:::
```

- [ ] **Step 6: Run G-11 and expect it to go GREEN for the first time since Task 8**

```bash
gates/checks.sh G-11
```

This is the moment the vocabulary collapse completes. If it still FAILs, read
every hit before touching the gate:

- **Hits in `docs/superpowers/plans/*.md` or `docs/superpowers/specs/*.md`** —
  including this plan file and the RLS design doc. These are engineering
  artifacts, not participant surfaces, and they must keep the retired tokens to
  stay readable as history (the design doc's own argument for the collapse names
  `support-lead` a dozen times). Add `docs/superpowers` to `SKIP_DIR_NAMES`
  (`gates/noun_lint.py:66-73`) or, better, exclude it in `_iter_files`, with this
  comment:

```python
    # docs/superpowers/ holds design specs and implementation plans -- engineering
    # history that must be free to name retired vocabulary in order to explain why
    # it was retired. Participant-facing docs are scanned; these are not.
```

  Verify the scope of the exclusion is exactly that directory and nothing above
  it: `docs/architecture.md` and friends must stay scanned.
- **Any other hit** is real remaining work. Fix the document, not the gate.

Then the full suite:

```bash
gates/checks.sh
.venv/bin/python -m unittest discover -s backend/tests -q
```

Expected: G-11 PASS, no other verdict changed. Tests untouched — this task edits
only Markdown.

- [ ] **Step 7: Render-check the guide and commit both repos**

Markdown that renders wrong in Workshop Studio is invisible until the room sees
it. The nested fenced blocks in Step 3 are the risk: a ```` ```sql ```` inside a
`:::alert` block, and a `<<'SQL'` heredoc containing SQL that itself contains
`;`. Check by eye, then confirm the fence count is even:

```bash
cd ../build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql
for f in content/40-module-3-prove-portable-tool-contract/index.en.md \
         content/00-introduction/index.en.md content/index.en.md; do
  printf '%s: %s fences\n' "$f" "$(grep -c '^```' "$f")"
done
```

Each count must be even. An odd count means an unclosed block, which swallows the
rest of the page.

Commit the app repo:

```bash
cd ../sample-agentic-hybrid-retrieval-aurora-postgresql
git add SECURITY_REVIEW.md docs/architecture.md docs/data-model.md \
        docs/implementation-spec.md docs/builder-session-flow.md gates/noun_lint.py
git commit -m "Describe entitlements as personas enforced by row-level security"
```

Commit the sibling repo separately — it is a different repository with its own
history:

```bash
cd ../build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql
git add content FACILITATOR_GUIDE.md
git commit -m "Add the persona flip and RLS coda to Module 3"
```

**Do not push either.** Workshop Studio pushes are user-managed
(`WORKSHOP_GUIDE_TODO.md:4`), and the sibling repo's packaged source revision is
frozen against a specific app commit — publishing guide copy that describes RLS
before the app revision containing RLS is packaged would break a live workshop.
Record in the task report that both commits are local and that
`assets/hybrid-retrieval-source.zip` plus the immutable source revision must be
rebuilt from the post-Task-16 app commit before the guide ships.

---
## Task 15: Sync both `SPEC-session.md` copies and the design doc (A6)

The SPEC is the coding agent's contract. Six of its statements are now false: D22
enumerates the retired role values, D24 specifies the deleted GUC as the coda
mechanism, G-27 asserts against that GUC, the route contract publishes
`?role={workshop|support-lead}`, the Lab-3 checkpoint names `support-lead`, and
G-29 (masking) does not exist in the SPEC at all — the design doc reserved the
number but never wrote the gate into Section 10.

**Files:**
- Modify: `design/SPEC-session.md` (lines 4, 96, 98, 482, 589, 766-770, 608)
- Modify: `design/verity-handoff/docs/SPEC-session.md` (the same edits, byte-identical)
- Modify: `docs/superpowers/specs/2026-07-28-rls-personas-column-masking-design.md`
  (the A7/A8 reconciliation)

**Interfaces:**
- Consumes: every decision Tasks 1-14 implemented.
- Produces: no code. The SPEC is read by the next agent to touch this repo, so a
  stale D24 is a defect that manifests as a future agent rebuilding the GUC.

### The two copies are byte-identical today

Verified before writing this task:

```
d0601f060aec30e264e36c44356e5b4f097e88e79055181423edc73ca5d19663  design/SPEC-session.md
d0601f060aec30e264e36c44356e5b4f097e88e79055181423edc73ca5d19663  design/verity-handoff/docs/SPEC-session.md
```

That hash matches the design doc's recorded `d0601f06…`, and Task 8 Step 8 edits
both. **Re-baseline before you start** — if Task 8's machine-token sync landed, the
hash has moved and the two copies must still agree with each other:

```bash
shasum -a 256 design/SPEC-session.md design/verity-handoff/docs/SPEC-session.md
diff design/SPEC-session.md design/verity-handoff/docs/SPEC-session.md && echo "in sync"
```

If they differ **before** your edits, stop and reconcile them first — you cannot
tell which is authoritative from inside this task, and guessing silently forks the
contract.

**Method: edit one file, then copy it over the other.** Do not hand-apply the same
seven edits twice; that is how the copies drift.

- [ ] **Step 1: Rewrite D22 (`:96`)**

The current text enumerates `workshop` and `support-lead` as the role values.
Replace the whole D22 row with (one line, as the table requires):

```markdown
| **D22** | **The word "principal" is banned from every participant-facing surface** (UI, guide, slides, script output — enforced by G-11). The concept is **persona**, values `analyst`, `admin`, and `auditor`, rendered as a "Viewing as" chip; routes use `?role=`, tool arguments and env use `role`, renamed end-to-end so no dual vocabulary survives. `support-lead` is retired and joins `principal` on the G-11 denylist. The mechanism is strengthened: the persona is a real PostgreSQL role, and switching it changes which rows the database lets **every retrieval arm, traversal hop, and raw table read** see — CASE-7421 and six supporting restricted objects are visible only to a persona holding the `can_see_restricted` clearance. This is protected moment M3. | "Principal" is IAM jargon that made the session's best moment harder to read. "Viewing as: Admin → a case appears" needs no glossary — and the lesson underneath ("entitlements live in the database") is Lab 3's takeaway sentence, so the label must never be the obstacle. Three personas rather than two give masking a home: the auditor is cleared to see the row and not its customer. |
```

Note what did **not** change: `?role=` stays the route param and `role` stays the
wire field. A7 collapsed the *values*, not the field name — D22 already bound the
field name and this plan does not reopen it.

- [ ] **Step 2: Rewrite D24 (`:98`)**

This is the substantive edit. The current row specifies RLS as "added once in the
schema as default-deny and **demonstrated, never built**" with
`SET LOCAL workbench.role` as the mechanism. Both halves are now wrong: the GUC is
deleted, and RLS is fully built with three policies, five roles, and a masking
layer. Replace the whole row:

```markdown
| **D24** | **RLS as the enforcement layer (belt and suspenders, upgraded 2026-07-28).** The explicit `acl_visible()` predicate remains the arm/hop mechanism and the Lab 3 participant hole (self-contained verify-SQL, planner-controllable, index-sargable per the D21 column rule). RLS is **built**, not merely demonstrated: `sql/11_roles_rls.sql` creates three NOLOGIN persona roles (`persona_analyst`, `persona_admin`, `persona_auditor`), one clearance role (`can_see_restricted`, GRANTed to admin and auditor and never to analyst), two LOGIN roles (`workshop_app` for the pool, `workshop_participant` for terminals), and enables **and forces** RLS on `casework.evidence_items`, `retrieval.documents`, and `retrieval.chunks` under one policy expression: `acl_visibility = 'workshop' OR pg_has_role(current_user, 'can_see_restricted', 'USAGE')` — byte-identical to the H2 participant hole. `sql/12_masking.sql` adds `pg_columnmask` policies so the auditor reads the restricted row with customer and operator identity redacted. Identity is carried by `SET LOCAL ROLE`, transaction-scoped (the T8 pattern) — a session-level `SET` under connection pooling leaks roles across requests; `workshop_app` holds no table grants, so a forgotten `SET LOCAL ROLE` raises `permission denied` rather than returning rows. The M3 coda is raw SQL at the table under two personas: analyst → 0 rows, admin → 1 row; no arm, no app, the database itself refuses. Teaching lines: *"The predicate is how the arm filters. RLS is why you can't leak even when you forget. Real systems want both."* and *"You never grant a limitation — you withhold a key."* | Converts the room's most predictable attack question into a scripted strength. Building RLS rather than demonstrating it costs one SQL file and two gates, and buys three things the GUC could not: a `permission denied` failure mode instead of a silent zero-row one, a masking layer that needs a third persona to be legible, and a coda whose predicate the participant already hand-wrote. `USAGE` not `MEMBER` in `pg_has_role`: `MEMBER` is transitive and ignores `INHERIT`, so it reports true for any transitively-granted role. |
```

The recorded fallback ("drop to predicate-only if rehearsal shows fragility") is
deliberately **removed**: RLS is now built and its gates are green, so a fallback
to predicate-only would mean deleting shipped code. If a reviewer asks for the
fallback back, the answer is that G-27's fail-closed assertion is what de-risks it,
not a retreat path.

- [ ] **Step 3: Fix the route contract (`:482`) and the Lab-3 checkpoint (`:589`)**

`:482`:

```markdown
  `/agent?role={analyst|admin|auditor}` · `/proof/{run_id}`.
```

`:589`:

```markdown
                     [checkpoint: admin adds CASE-7421; analyst shows nothing;
                     auditor shows it with customer identity masked]
```

Verify `:482` against `gates/route_contract.py` after Task 11 rather than trusting
this plan — G-23 executes the route contract, so the SPEC and the gate must agree:

```bash
grep -n "role" gates/route_contract.py
```

- [ ] **Step 4: Rewrite G-27 and add G-29, G-30, G-31 to Section 10 (`:766-775`)**

Replace the G-27 bullet and append three new ones, in the existing bullet style:

```markdown
- **G-27** FORCE-RLS assertion (D24), three parts: (a) **fail-closed** — connected as
  `workshop_app` with **no role set**, a `SELECT` on `casework.evidence_items`,
  `retrieval.documents`, and `retrieval.chunks` raises `permission denied`; an error is
  a stronger proof than zero rows, because it shows the pool identity has no standing
  privilege path. (b) **row filtering** — under `SET LOCAL ROLE persona_analyst`,
  CASE-7421 and every restricted object return **zero rows at each of the three raw
  tables**, proving RLS is not silently bypassed by ownership. (c) **replay
  determinism** — a run replayed under the receipt's recorded persona reproduces
  identical candidates (`SET LOCAL ROLE`, transaction-scoped, never session-scoped).
- **G-29** Masking + Law-2 determinism (RLS design 2026-07-28): under
  `persona_auditor`, CASE-7421 is visible but `account_name`, `customer_commitment`,
  and the `chunk_text` blob return **masked**, and the value rendered in the app panel
  is **byte-identical** to the value the pasted verify-SQL returns in psql;
  `persona_admin` sees all three unmasked. The mask pattern set is **generated** from
  the seed's own restricted literals (`retrieval.sensitive_literals()`), never
  hand-written, and a corpus-wide scan as the auditor asserts zero occurrences of any
  restricted literal.
- **G-30** Participant ceremony (A1): the `workshop_participant` identity runs every
  Lab-1 snippet the guide publishes, and a bare `SELECT` on casework/retrieval raises
  `permission denied` — the fail-closed first lesson is real, not narrated.
- **G-31** Persona golden equivalence (A7): analyst results are byte-identical to the
  pre-collapse `role=workshop` baseline, so collapsing two identity axes into one
  changed no participant-visible number.
```

Then the version line at `:4`:

```markdown
Version: draft-21 · Jul 29 2026 — RLS built as the enforcement layer (D24 rewritten; three persona roles + clearance + column masking; G-27 rewritten, G-29/G-30/G-31 added); identity vocabulary collapsed to one persona axis (D22; `support-lead` and `workbench.role` retired)
```

- [ ] **Step 5: Fix the H2 description (`:608`)**

`acl_visible(role)` no longer takes a role argument — Task 9's signature is
`acl_visible(p_acl jsonb, p_role name DEFAULT current_user)`, and the H2 hole's
whole point is that the predicate reads the effective role rather than an argument.
Replace the H2 sentence:

```markdown
`acl_visible()` applied *at the traversal hop*, checkpointed by the M3 persona flip,
with the D24 RLS coda after — and the predicate the participant writes is the same
expression the RLS policy enforces, so the hole and the backstop are literally one
line of SQL.
```

That last clause is the pedagogical payoff of the whole plan and it belongs in the
SPEC: the participant hand-writes the expression, then sees the identical text in
`pg_policies.qual`.

- [ ] **Step 6: Copy over the twin and verify byte-identity**

```bash
cp design/SPEC-session.md design/verity-handoff/docs/SPEC-session.md
diff design/SPEC-session.md design/verity-handoff/docs/SPEC-session.md && \
  echo "SPEC copies byte-identical"
shasum -a 256 design/SPEC-session.md
```

`cp` in this direction is safe **only** because Step 0 confirmed they matched
before you started. If they did not, you have just overwritten the other copy's
divergent content — which is why Step 0 is a hard stop, not a formality.

Record the new hash in the task report; the design doc cites the old one and Step 7
updates it.

- [ ] **Step 7: Reconcile the design doc with A7/A8**

`docs/superpowers/specs/2026-07-28-rls-personas-column-masking-design.md` is the
approved spec, and the amendments A7/A8 supersede parts of it. **Do not rewrite
the argument** — the doc's value is the reasoning that produced the decisions,
including the reasoning that was later amended. Add a superseding block instead, so
a reader sees both what was designed and what was bound.

Insert immediately after the `## Purpose` section (`:12-22`):

```markdown
## Superseded by binding amendments (2026-07-28)

This design was approved with amendments A1-A8, which supersede the sections named
below. The original text is retained because the reasoning still explains *why*;
the amendments are what was built.

| Superseded | Section | Bound outcome |
|---|---|---|
| Two identity axes (persona role + `workbench.role` GUC) | "Two identity axes and how they reconcile (M3 preserved)" (`:142`) | **A7:** one axis, the persona. The `workbench.role` GUC is deleted — it had zero code consumers and existed only in the two SPEC copies and this doc. |
| `workshop_restricted_reader` | "Persona model" (`:117`), "Bootstrap / idempotency" (`:334`) | **A8:** renamed `can_see_restricted`. "Restricted reader" misparses as "a reader who is restricted"; the role is a clearance. |
| Personas as connectable roles (`\c`-as-persona demo) | "App runtime plumbing" (`:221`) | **A2/A3:** personas are NOLOGIN. The demo is a transaction envelope — `BEGIN; SET LOCAL ROLE …; <SELECT>; ROLLBACK;` — which is also the shape every role-sensitive `_verify_sql` now emits. |
| "matches existing seed constants" | "Persona model" (`:117`) | **Corrected:** it did not. Both `WORKSHOP_ACL` and `RESTRICTED_ACL` carried `visibility: "workshop"`; restrictedness lived only in `principals: ["support-lead"]`, so the predicate as written would have failed **open**. Resolved by flipping `RESTRICTED_ACL` to `{"visibility": "restricted", "principals": []}` (Task 13). |
| "~6 restricted objects" (count and keys open, `:418`) | "Restricted-evidence seed" (`:291`) | **Locked:** six new keys — `CASE-8102`, `CASE-8137`, `INC-3162`, `INC-4117`, `CHG-6213`, `CHG-3309` — each measured against the `CGH-1842` trigram probe (max similarity 0.0588, no `%` match) before selection. `INC-2093` and any `CASE-74xx` were measured and **rejected**. |
| Mask scope reading `support_cases` only | "Column masking (auditor)" (`:178`) | **Extended:** `retrieval.sensitive_literals()` unions `casework.incidents` and `casework.changes`, because the restricted cohort seeds operator identity there and the design's own constraint 4 names operator identity as a mask target. |
| SPEC hash `d0601f06…` | "Spec + gate impact" (`:388`) | Re-baselined; see the implementation plan's Task 15 report for the current hash. |
```

Then update the two open items the plan closed — replace items 1 and 6 of
`## Open items carried to the plan` (`:404`, `:418`) with strikethrough-resolved
forms matching the style already used there:

```markdown
6. ~~Exact restricted-row count and their `external_key`s / systems~~ —
   **resolved:** seven restricted objects total (`CASE-7421` plus the six above),
   spanning three evidence kinds and three source systems, measured against G-21
   before selection.
```

- [ ] **Step 7b: Do not run G-11 against these files and expect green**

Both SPEC copies live under `design/`, which `gates/noun_lint.py:47-63`
deliberately excludes from `SCAN_ROOTS` ("the spec workspace: it holds the
migration map and intentional negative examples"). The design doc lives under
`docs/superpowers/`, which Task 14 Step 6 excluded for the same reason. So G-11
does not read anything this task edits. That is correct and it is also why the
`support-lead` mentions retained in the design doc's superseding table are safe.

Run the gate anyway, to prove this task changed nothing:

```bash
gates/checks.sh G-11 G-23
```

Expected: both PASS, unchanged from Task 14's result.

- [ ] **Step 8: Commit**

```bash
git add design/SPEC-session.md design/verity-handoff/docs/SPEC-session.md \
        docs/superpowers/specs/2026-07-28-rls-personas-column-masking-design.md
git commit -m "Bind the SPEC to built RLS and one persona axis"
```

---

## Task 16: End-to-end enforcement tests and the live deployment sequence

Fifteen tasks built the mechanism and proved each piece on a scratch database. This
task does the two things none of them could: it puts the enforcement claim under
the repeatable test suite, and it applies the whole thing to the live cluster —
behind an explicit go-ahead gate that the implementer must not open on their own.

**Files:**
- Create: `backend/tests/test_rls_personas.py`
- Modify: `backend/tests/test_retrieval_integration.py:76-84` (`_apply_schema` glob)
- Modify: `README.md:239-252` (the disposable-database recipe gains the RLS caveat)
- Modify: `seed/README.md:56-70` (regeneration recipe gains the count)
- Modify: `seed/artifacts/casework-embeddings.jsonl` and
  `seed/artifacts/casework-embeddings.jsonl.manifest.json` (regenerated, Step 8)

**Interfaces:**
- Consumes: `db.get_dict_conn(persona)`, `db.get_owner_conn()`, `db.PERSONAS`,
  `db.persona_role()` (Task 7); the roles and policies from Task 5; `mask_redact`,
  `mask_blob`, `sensitive_literals()`, `refresh_mask_blob()` (Task 6); the seven
  restricted keys from Task 13; `WORKSHOP_APP_DATABASE_URL` (Task 5 Step 5).
- Produces: no importable API. The last deliverable in the plan; nothing consumes
  it but `make test` and the facilitator.

### The collision this task must resolve first

`backend/tests/test_retrieval_integration.py:76-84` applies **every**
`sql/[0-9][0-9]_*.sql` except `99`, by glob:

```python
    files = sorted(
        path
        for path in (REPOSITORY_ROOT / "sql").glob("[0-9][0-9]_*.sql")
        if not path.name.startswith("99")
    )
```

Task 6 creates `sql/12_masking.sql`, whose first statement is
`CREATE EXTENSION IF NOT EXISTS pg_columnmask`. That extension is **Aurora-managed
and does not exist on local PostgreSQL**. So the moment Task 6 lands, this glob
makes all 24 existing integration tests fail at `setUpClass` on the local path —
the path the README documents as the default (`README.md:232-236`) and the one a
contributor runs first.

Three ways to resolve it, and only one is honest:

- **(a) Make `sql/12` no-op when the extension is unavailable.** Rejected: that
  file's whole design is to `RAISE EXCEPTION` rather than leave a cluster that looks
  configured and is not (Task 6, `pgcolumnmask.policy_admin_rolname` guard). A
  silent skip is exactly the failure mode it was written to prevent.
- **(b) Drop the glob and hardcode the file list.** Rejected: the glob exists so
  that adding a SQL file is enough to make the suite exercise it — the docstring at
  `:63-70` says so. Hardcoding reintroduces the drift the glob removed.
- **(c) Keep the glob, skip only files the cluster cannot host, and name them.**
  Correct. The skip is data-driven (query `pg_available_extensions`), it prints what
  it skipped, and the RLS tests that *can* run locally still run.

Take (c).

- [ ] **Step 1: Make `_apply_schema` skip only what the cluster cannot host**

In `backend/tests/test_retrieval_integration.py`, replace `_apply_schema`
(`:63-86`) with:

```python
def _unavailable_extensions(connection: psycopg.Connection) -> set[str]:
    """Return the extension names this cluster cannot install.

    ``pg_columnmask`` is Aurora-managed and absent from local PostgreSQL. Asking
    the cluster is the only honest test: hardcoding "skip 12 locally" would also
    skip it on Aurora, where it must run.

    Args:
        connection: An open connection to the disposable test database.

    Returns:
        The subset of REQUIRED_EXTENSIONS that ``pg_available_extensions`` does not
        offer.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT name FROM pg_available_extensions WHERE name = ANY(%s)",
            [list(SQL_FILE_EXTENSIONS.values())],
        )
        available = {row[0] if not isinstance(row, dict) else row["name"] for row in cursor}
    return set(SQL_FILE_EXTENSIONS.values()) - available


def _apply_schema(connection: psycopg.Connection) -> None:
    """Apply every versioned SQL file the cluster can host, before seeding.

    Retrieval, ranking, and ACL enforcement live in SQL, so a test that runs
    against whatever was last applied by hand is testing an unknown revision. The
    files are idempotent (CREATE OR REPLACE, IF NOT EXISTS), and applying them
    here means editing SQL is enough to make the suite exercise the change.

    One file is conditional. ``sql/12_masking.sql`` requires ``pg_columnmask``,
    which Aurora manages and local PostgreSQL does not ship. Rather than weaken
    that file -- it deliberately raises rather than leave a cluster unmasked -- this
    skips it where the extension is unavailable and PRINTS the skip, so a local run
    cannot be mistaken for full coverage. On Aurora nothing is skipped.

    Args:
        connection: An open connection to the disposable test database.

    Raises:
        RuntimeError: If no versioned SQL files were found at all.
    """
    files = sorted(
        path
        for path in (REPOSITORY_ROOT / "sql").glob("[0-9][0-9]_*.sql")
        if not path.name.startswith("99")
    )
    if not files:
        raise RuntimeError(f"no versioned SQL files found in {REPOSITORY_ROOT / 'sql'}")

    missing = _unavailable_extensions(connection)
    skipped = [
        path.name
        for path in files
        if SQL_FILE_EXTENSIONS.get(path.name) in missing
    ]
    if skipped:
        print(
            f"\n  NOTE: skipping {', '.join(skipped)} -- this cluster does not offer "
            f"{', '.join(sorted(missing))}. Column-masking behaviour is NOT covered "
            f"by this run; run the suite against Aurora to cover it."
        )

    with connection.cursor() as cursor:
        for path in files:
            if path.name in skipped:
                continue
            cursor.execute(path.read_text(encoding="utf-8"))
    connection.commit()
```

Add the mapping above `_apply_schema`, next to `REPOSITORY_ROOT`:

```python
# SQL files that need an extension the cluster may not offer. pg_columnmask is
# Aurora-managed; local PostgreSQL does not ship it. Keep this keyed by filename so
# a new conditional file is one line, not a new code path.
SQL_FILE_EXTENSIONS = {"12_masking.sql": "pg_columnmask"}
```

- [ ] **Step 2: Confirm the existing suite still passes locally**

Start local PostgreSQL first (`pg_isready -h localhost -p 55432`; if it does not
answer, the whole step is BLOCKED — say so rather than skipping silently).

```bash
createdb -h localhost -p 55432 workbench_test 2>/dev/null || true
TEST_DATABASE_URL='postgresql://localhost:55432/workbench_test?sslmode=disable' \
DATABASE_URL='postgresql://localhost:55432/workbench_test?sslmode=disable' \
ALLOW_TEST_DATABASE_RESET=1 \
  .venv/bin/python -m unittest backend.tests.test_retrieval_integration -v
```

Expected: the `NOTE: skipping 12_masking.sql` line, then `Ran 24 tests … OK`.
**24, not fewer.** If a test errors on `permission denied`, `sql/11`'s FORCE RLS is
subjecting the local owner: see Step 3.

- [ ] **Step 3: Verify the owner is not filtered by its own policies**

`sql/11` sets `FORCE ROW LEVEL SECURITY` on the three read-path tables. FORCE
subjects the table **owner** to the policies, and a `PERMISSIVE` policy set that does
not list the owner's role denies it **every row**. Task 5 Step 1 therefore ships
*both* halves of the fix — `GRANT can_see_restricted TO current_user` **and**
`CURRENT_USER` in all three policies' `TO` lists. This step is verification, not
repair.

It is unconditional, and an earlier draft of this step had that wrong in two ways.
It gated the first half on the local owner's `rolsuper` and claimed Aurora was
unaffected because `retrieval_admin` is an `rds_superuser` member. **Role attributes
are not inherited through role membership.** Measured read-only against the live
cluster: `retrieval_admin` is `rolsuper=false, rolbypassrls=false`, and
`rds_superuser` itself is `rolbypassrls=false`. There is no bypass to inherit, so the
deploy target is subject to FORCE exactly as a local cluster is, and a conditional
local fix would have shipped a broken `make schema`/`make seed` to Aurora.

**Measured on PostgreSQL 17 against this exact policy shape** (a scratch cluster,
non-superuser owner, `ENABLE` + `FORCE`, policy `TO` the personas, one `workshop` row
and one `restricted` row):

| Owner in the policy `TO` list? | Owner holds `can_see_restricted`? | Rows the owner sees |
|---|---|---|
| no | no | **0** — every row vanishes |
| no | yes | **0** — still vanishes |
| yes | no | **workshop only** — silent truncation |
| yes | yes | **all rows** — correct |

Both halves are required. Row three does not fail; it *lies*. A measured `INSERT INTO projection SELECT … FROM
source` under that configuration copied 1 of 2 rows and reported success — which is
exactly the shape of the seed and the search-index build. Restricted evidence would
never reach `retrieval.documents`/`chunks`, and G-27(b) would then report PASS for the
wrong reason: the analyst sees zero restricted rows because there are none. A green
gate over an empty enforcement claim is worse than a red one.

Row two is the one the earlier conditional draft would have shipped. Measured with the
clearance grant applied but the policies listing only the three personas: the owner
saw **0 of 2** rows, `INSERT` raised `new row violates row-level security policy for
table "documents"`, and `INSERT INTO projection SELECT` copied **0** rows and exited
0. The clearance key cannot rescue a role no policy applies to. Note also that the
owner's persona grants are `WITH INHERIT FALSE`, so they do not reach the `TO` list
either: measured, `pg_has_role(owner, 'persona_analyst', 'USAGE')` is false.

Confirm the owner reads the whole table (`sql/11` has already been applied by this
point in the sequence):

```bash
psql 'postgresql://localhost:55432/workbench_test?sslmode=disable' -X -q -t -A -c \
  "SELECT current_user, count(*) FROM retrieval.documents WHERE is_current"
```

Expected: a non-zero count. **Zero means the `TO` list or the clearance grant did not
land** — do not weaken FORCE and do not drop either half; re-check that all three
`CREATE POLICY` statements in `sql/11` carry `CURRENT_USER` in the `TO` list.

`CURRENT_USER` is resolved at `CREATE POLICY` time to an OID and stored in
`pg_policy.polroles`; it is not re-evaluated per query. Verify that, because a
dynamic reading would match every persona and hand the analyst the clearance
disjunct:

```bash
psql 'postgresql://localhost:55432/workbench_test?sslmode=disable' -X -q -t -A -c \
  "SELECT policyname, roles FROM pg_policies WHERE policyname LIKE 'rls_%_visibility' ORDER BY policyname"
```

Expected: each row lists the three personas plus the owner's literal role name. One
consequence to know: a *different* owner re-running `sql/11` rewrites the policy to
itself and the previous owner loses access.

Then confirm the personas are still filtered under the widened policy — the measured
result is analyst 1 of 2 with the owner at 2 of 2, so widening the `TO` list does
not weaken the demo:

```bash
psql 'postgresql://localhost:55432/workbench_test?sslmode=disable' -X -q -t -A <<'SQL'
BEGIN; SET LOCAL ROLE persona_analyst;
SELECT count(*) FROM retrieval.documents WHERE is_current AND acl_visibility='restricted';
ROLLBACK;
SQL
```
Expected: `0`. If the owner-widening leaked restricted rows to the analyst, the
policy was edited wrongly — the `TO` list gains a role, the `USING` expression does
not change.

State which branch applied and the measured `rolsuper` value in the report. This is
a behavioural fork, not a style choice.

- [ ] **Step 4: Write the failing end-to-end test**

Create `backend/tests/test_rls_personas.py`:

```python
"""End-to-end persona enforcement: row filtering, masking, and fail-closed.

Every other test in this repo proves retrieval behaviour. This one proves the
enforcement claim the workshop makes out loud -- that the database refuses, not the
application -- and it proves it through the same connection path a request uses
(``db.get_dict_conn``), not through a hand-rolled psql session.

Requires a cluster where sql/11_roles_rls.sql has been applied and the persona
roles exist. Masking coverage additionally requires pg_columnmask, so those
assertions live in their own class and skip where the extension is absent rather
than failing a local run.
"""

from __future__ import annotations

import os
import unittest

import psycopg

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from backend.app import db

RESTRICTED_KEYS = (
    "CASE-7421",
    "CASE-8102",
    "CASE-8137",
    "CHG-3309",
    "CHG-6213",
    "INC-3162",
    "INC-4117",
)


def _roles_exist() -> bool:
    """True when the persona roles and the clearance role are on the cluster."""
    if not TEST_DATABASE_URL:
        return False
    try:
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_roles WHERE rolname = ANY(%s)",
                [["persona_analyst", "persona_admin", "persona_auditor",
                  "can_see_restricted"]],
            )
            return cursor.fetchone()[0] == 4
    except (psycopg.OperationalError, RuntimeError):
        return False


def _extension_available(name: str) -> bool:
    """True when the cluster has ``name`` installed (not merely available)."""
    try:
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_extension WHERE extname = %s", [name]
            )
            return cursor.fetchone()[0] == 1
    except (psycopg.OperationalError, RuntimeError):
        return False


ROLES_PRESENT = _roles_exist()
COLUMNMASK_PRESENT = ROLES_PRESENT and _extension_available("pg_columnmask")


@unittest.skipUnless(
    ROLES_PRESENT,
    "apply sql/11_roles_rls.sql to TEST_DATABASE_URL for persona enforcement tests",
)
class RowFilteringTests(unittest.TestCase):
    """RLS decides which rows exist for a persona."""

    def _restricted_count(self, persona: str) -> int:
        with db.get_dict_conn(persona) as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)::int AS n
                  FROM retrieval.documents
                 WHERE is_current AND acl_visibility = 'restricted'
                """
            )
            return cursor.fetchone()["n"]

    def test_analyst_sees_no_restricted_documents(self) -> None:
        self.assertEqual(self._restricted_count("analyst"), 0)

    def test_admin_and_auditor_see_the_restricted_cohort(self) -> None:
        for persona in ("admin", "auditor"):
            with self.subTest(persona=persona):
                self.assertEqual(self._restricted_count(persona), len(RESTRICTED_KEYS))

    def test_workshop_rows_are_visible_to_every_persona(self) -> None:
        counts = {}
        for persona in db.PERSONAS:
            with db.get_dict_conn(persona) as conn, conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT count(*)::int AS n
                      FROM retrieval.documents
                     WHERE is_current AND acl_visibility = 'workshop'
                    """
                )
                counts[persona] = cursor.fetchone()["n"]
        self.assertGreater(counts["analyst"], 0, "no workshop rows: corpus not seeded")
        self.assertEqual(len(set(counts.values())), 1, counts)

    def test_chunks_are_filtered_too_not_just_documents(self) -> None:
        """The vector arm reads retrieval.chunks standalone; a documents-only
        policy would leak restricted body text through it."""
        for persona, expect_zero in (("analyst", True), ("admin", False)):
            with self.subTest(persona=persona):
                with db.get_dict_conn(persona) as conn, conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT count(*)::int AS n
                          FROM retrieval.chunks
                         WHERE is_current AND acl_visibility = 'restricted'
                        """
                    )
                    n = cursor.fetchone()["n"]
                self.assertEqual(n == 0, expect_zero, f"{persona} saw {n}")

    def test_casework_evidence_is_filtered_by_the_jsonb_form(self) -> None:
        """casework carries visibility in acl->>'visibility', not a scalar column.
        Both predicate forms must agree or the two layers disagree on one row."""
        with db.get_dict_conn("analyst") as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT count(*)::int AS n FROM casework.evidence_items "
                "WHERE external_key = ANY(%s)",
                [list(RESTRICTED_KEYS)],
            )
            self.assertEqual(cursor.fetchone()["n"], 0)

    def test_restricted_keys_are_absent_from_every_analyst_arm(self) -> None:
        """The enforcement claim is about retrieval, not just SELECT. Query each
        arm by the restricted identifier itself -- the strongest possible probe.

        The two arms take different parameter shapes, which is why this is a list of
        (statement, argument) pairs rather than one loop: the lexical arm is
        retrieval.full_text_search(p_query text, ...) and the fuzzy arm is
        retrieval.fuzzy_search(p_probe_tokens text[], ...). There is no
        retrieval.lexical_search.
        """
        arms = (
            ("full_text", "SELECT external_key FROM retrieval.full_text_search("
                          "%s, p_limit => 25)", lambda key: (key,)),
            ("fuzzy", "SELECT external_key FROM retrieval.fuzzy_search("
                      "%s::text[], p_limit => 25)", lambda key: ([key],)),
        )
        with db.get_dict_conn("analyst") as conn:
            for name, statement, params in arms:
                for key in RESTRICTED_KEYS:
                    with self.subTest(arm=name, key=key):
                        with conn.cursor() as cursor:
                            cursor.execute(statement, params(key))
                            found = [row["external_key"] for row in cursor.fetchall()]
                        self.assertNotIn(key, found)


@unittest.skipUnless(
    ROLES_PRESENT,
    "apply sql/11_roles_rls.sql to TEST_DATABASE_URL for persona enforcement tests",
)
class FailClosedTests(unittest.TestCase):
    """A forgotten SET LOCAL ROLE must deny, never return rows."""

    def test_the_pool_login_holds_no_read_grant(self) -> None:
        """The check that makes the whole design fail-closed. If workshop_app can
        read a table directly, a forgotten persona returns rows instead of raising,
        and every other assertion in this file is decorative."""
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT has_table_privilege('workshop_app', t, 'SELECT') AS granted, t
                  FROM unnest(ARRAY['casework.evidence_items',
                                    'retrieval.documents',
                                    'retrieval.chunks']) AS t
                """
            )
            for row in cursor.fetchall():
                with self.subTest(table=row[1]):
                    self.assertFalse(row[0], f"workshop_app can SELECT {row[1]}")

    def test_role_is_scoped_to_the_transaction(self) -> None:
        """SET LOCAL, not SET: a session-scoped role would leak to the next
        borrower of this pooled connection."""
        with db.get_dict_conn("admin") as conn, conn.cursor() as cursor:
            cursor.execute("SELECT current_user AS role")
            self.assertEqual(cursor.fetchone()["role"], "persona_admin")
        with db.get_dict_conn("analyst") as conn, conn.cursor() as cursor:
            cursor.execute("SELECT current_user AS role")
            self.assertEqual(cursor.fetchone()["role"], "persona_analyst")

    def test_clearance_is_withheld_from_the_analyst_not_marked_on_it(self) -> None:
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            for persona, expected in (
                ("persona_analyst", False),
                ("persona_admin", True),
                ("persona_auditor", True),
            ):
                with self.subTest(persona=persona):
                    cursor.execute(
                        "SELECT pg_has_role(%s, 'can_see_restricted', 'USAGE')",
                        [persona],
                    )
                    self.assertEqual(cursor.fetchone()[0], expected)

    def test_rls_is_enabled_and_forced_on_all_three_read_path_tables(self) -> None:
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT n.nspname || '.' || c.relname AS tbl,
                       c.relrowsecurity, c.relforcerowsecurity
                  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname || '.' || c.relname = ANY(%s)
                """,
                [["casework.evidence_items", "retrieval.documents", "retrieval.chunks"]],
            )
            rows = cursor.fetchall()
        self.assertEqual(len(rows), 3, rows)
        for tbl, enabled, forced in rows:
            with self.subTest(table=tbl):
                self.assertTrue(enabled, f"{tbl}: RLS not enabled")
                self.assertTrue(forced, f"{tbl}: RLS not forced; the owner is unfiltered")


@unittest.skipUnless(
    COLUMNMASK_PRESENT,
    "pg_columnmask is Aurora-managed; run against Aurora to cover masking",
)
class ColumnMaskingTests(unittest.TestCase):
    """Masking decides which columns a visible row shows."""

    def _case_row(self, persona: str) -> dict:
        with db.get_dict_conn(persona) as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT case_id, account_name, customer_commitment
                  FROM casework.support_cases WHERE case_id = %s
                """,
                ["CASE-7421"],
            )
            return cursor.fetchone()

    def test_admin_reads_the_restricted_case_unmasked(self) -> None:
        row = self._case_row("admin")
        self.assertIsNotNone(row, "CASE-7421 missing: corpus not seeded")
        self.assertNotIn("REDACTED", row["customer_commitment"])

    def test_auditor_reads_the_same_row_with_identity_redacted(self) -> None:
        admin_row = self._case_row("admin")
        auditor_row = self._case_row("auditor")
        self.assertIsNotNone(auditor_row, "auditor cannot see CASE-7421 at all")
        self.assertEqual(auditor_row["case_id"], admin_row["case_id"])
        self.assertEqual(auditor_row["customer_commitment"], "[REDACTED]")
        self.assertNotEqual(auditor_row["account_name"], admin_row["account_name"])

    def test_no_sensitive_literal_survives_anywhere_in_the_auditor_corpus(self) -> None:
        """The leak scan. Masking one column is easy; the claim is corpus-wide."""
        with db.get_owner_conn() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT literal FROM retrieval.sensitive_literals()")
            literals = [row[0] for row in cursor.fetchall()]
        self.assertGreater(len(literals), 0, "no sensitive literals: mask is a no-op")

        with db.get_dict_conn("auditor") as conn:
            for literal in literals:
                with self.subTest(literal=literal[:40]):
                    with conn.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT count(*)::int AS n FROM retrieval.chunks
                             WHERE is_current AND chunk_text LIKE '%%' || %s || '%%'
                            """,
                            [literal],
                        )
                        self.assertEqual(cursor.fetchone()["n"], 0)

    def test_masking_is_deterministic_across_checkouts(self) -> None:
        """Law 2: the value in the panel and the value in a pasted verify-SQL must
        be byte-identical, which requires the mask functions be IMMUTABLE."""
        first = self._case_row("auditor")
        second = self._case_row("auditor")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: Run it against a scratch database that has the roles — expect FAIL first**

The skip guards mean a bare run reports skips, not failures, and a skipped security
test is worthless as a TDD signal. So build the substrate, then run:

```bash
createdb -h localhost -p 55432 rls_e2e_test
DATABASE_URL='postgresql://localhost:55432/rls_e2e_test?sslmode=disable' make schema
DATABASE_URL='postgresql://localhost:55432/rls_e2e_test?sslmode=disable' \
  .venv/bin/python backend/scripts/build_search_index.py \
  --load-casework --offline-capture --provider hash --embed-missing \
  --background-documents 200

TEST_DATABASE_URL='postgresql://localhost:55432/rls_e2e_test?sslmode=disable' \
DATABASE_URL='postgresql://localhost:55432/rls_e2e_test?sslmode=disable' \
WORKSHOP_APP_DATABASE_URL='postgresql://workshop_app@localhost:55432/rls_e2e_test?sslmode=disable' \
  .venv/bin/python -m unittest backend.tests.test_rls_personas -v
```

Expected on a local cluster: `RowFilteringTests` and `FailClosedTests` run,
`ColumnMaskingTests` reports `skipped 'pg_columnmask is Aurora-managed…'`. That
skip is the honest local outcome and is exactly why Step 7 exists.

Two failures are *expected* here and are the point of running before fixing:

1. `test_the_pool_login_holds_no_read_grant` fails if `sql/11` granted the personas
   via a path that also reached `workshop_app`. It should pass — if it fails, the
   fail-closed property is absent and nothing else matters. Fix `sql/11`.
2. Any `permission denied` at `get_dict_conn` means `WORKSHOP_APP_DATABASE_URL`
   points at a role without the persona grants, or `workshop_app` has no local
   password/`trust` entry. Fix the DSN, not the test.

- [ ] **Step 6: Run the whole suite and confirm nothing regressed**

```bash
TEST_DATABASE_URL='postgresql://localhost:55432/rls_e2e_test?sslmode=disable' \
ALLOW_TEST_DATABASE_RESET=1 make test
```

Expected: every previously-passing test still passes, plus the new file. Record the
final `Ran N tests` line verbatim. `make test` sets `DATABASE_URL` from
`TEST_DATABASE_URL` itself (`Makefile:57-61`), which is what keeps the app-resolved
URL and the test target in agreement — the `_assert_disposable_test_database` check.

Then drop the scratch database:

```bash
dropdb -h localhost -p 55432 rls_e2e_test
```

- [ ] **Step 7: Document the local coverage gap in `README.md`**

Local PostgreSQL cannot cover masking, and a reader who runs `make test` and sees
`OK` will believe otherwise. After the existing paragraph at `README.md:239-243`
("`setUpClass` TRUNCATEs every…"), insert:

```markdown
Two things a local run does not prove. `pg_columnmask` is Aurora-managed, so
`sql/12_masking.sql` is skipped locally and `ColumnMaskingTests` reports as
skipped — the run prints both. And `FORCE ROW LEVEL SECURITY` does not subject a
superuser, so a local cluster whose owner is a superuser exercises the policies
only through the persona roles, never through the owner. Run the same suite against
a disposable database on the Aurora cluster to cover both.
```

- [ ] **Step 8: Commit the test work before touching anything live**

```bash
git add backend/tests/test_rls_personas.py \
        backend/tests/test_retrieval_integration.py README.md
git commit -m "Cover persona row filtering, masking, and fail-closed end to end"
```

This is the last commit that can be made without the user's go-ahead. Everything
below changes live state.

---

### The live deployment sequence — GATED

- [ ] **Step 9: STOP and ask for explicit go-ahead**

Do not run any command in Steps 10-13 until the user has said yes to this specific
list. Report the current state and ask:

> Tasks 1-16 are built and committed; every verification ran on scratch databases
> and live is untouched. Applying this to the live `retrieval` cluster means:
> (1) `make schema` with the two new files, which creates six cluster-global roles
> and enables + FORCES RLS on `casework.evidence_items`, `retrieval.documents` and
> `retrieval.chunks`; (2) a full reseed, because the restricted cohort is a corpus
> change; (3) regenerating the 192 MB embedding cache manifest, which costs a small
> number of Bedrock embedding calls. Step (1) is reversible
> (`ALTER TABLE … DISABLE ROW LEVEL SECURITY`, `DROP ROLE`); step (2) rebuilds the
> corpus the shipped release artifacts were cut from. Go ahead?

Three facts to state plainly rather than bury:

- **Roles are cluster-global.** `persona_*`, `can_see_restricted`, `workshop_app`
  and `workshop_participant` become visible to every database on that cluster,
  including any other database an account holds.
- **`workshop_app` and `workshop_participant` have no passwords.** `sql/11`
  deliberately does not set them (public repo). Until the sibling Workshop Studio
  repo runs `ALTER ROLE … PASSWORD` from Secrets Manager, nothing can log in as
  either, so the API keeps running on `DATABASE_URL` and — per Task 7's
  `_pool_conninfo` warning — **RLS is not actually enforced for requests yet**. Say
  this out loud; it is the difference between "built" and "enforcing".
- **The shipped release cache is already stale** for reasons predating this plan
  (the 2026-07-27 reseed), so Step 12 is fixing two divergences at once.

- [ ] **Step 10: Apply the schema to live, roles first**

Only after go-ahead. Confirm the target before running anything:

```bash
psql "$DATABASE_URL" -X -q -t -A -c 'SELECT current_database(), current_user'
```

Expected: `retrieval|<the owner>`. If the database is not `retrieval`, you are not
where you think you are — stop.

```bash
make schema
```

`make schema` reads `DATABASE_URL` from `.env` (`Makefile:1-8`) and applies all
twelve files. It is idempotent, so files 00-10 re-apply as no-ops; 11 and 12 are
new. Watch for the `RAISE NOTICE` from `sql/12`'s guarded refresh: pre-reseed the
corpus has no restricted literals yet, so the expected notice is
`no restricted literals in the corpus yet (pre-seed)`. If instead the build fails
on `pgcolumnmask.policy_admin_rolname is not set`, the cluster parameter group needs
that value set to the schema owner and applied — that is a sibling-repo change and a
reboot; stop and report rather than working around it.

- [ ] **Step 11: Reseed live with the restricted cohort**

```bash
CAPTURE_BUNDLE=<the release bundle path> make seed-casework
```

This is the guarded release path: `--require-release-capture --verify-cache
--background-documents 15000` (`Makefile`). **It will fail on `--verify-cache`**,
and that failure is correct — the manifest's `entry_count: 15017` predates the seven
new documents. Record the exact error, then go to Step 12. Do not pass
`--no-verify-cache` or delete the manifest to get past it.

- [ ] **Step 12: Regenerate the embedding cache and its manifest**

`seed/README.md:56-70` documents the two-step recipe and why the steps cannot be
collapsed (verification runs before indexing, so a run that also embeds would only
verify the file it was about to change). Run it:

```bash
# 1. Embed the new chunks. Billable. Only new content hashes are sent to Bedrock.
.venv/bin/python backend/scripts/build_search_index.py --load-casework \
  --capture-bundle <bundle> --require-release-capture \
  --embed-missing --write-cache-manifest

# 2. Confirm the manifest matches on a clean load.
.venv/bin/python backend/scripts/build_search_index.py --load-casework \
  --capture-bundle <bundle> --require-release-capture --verify-cache
```

Then read the new manifest and check the arithmetic:

```bash
cat seed/artifacts/casework-embeddings.jsonl.manifest.json
```

`entry_count` must be **greater than 15017 and less than 15017 + (new chunks)**,
because the cache is keyed by `sha256(model_id \0 chunk_text_hash)` and chunk text
is deduplicated by hash: seven new documents add one entry per *unique* chunk, not
per chunk. `dimensions` must still be `1024` and `model_id` still
`us.cohere.embed-v4:0` — a change in either means the run used the wrong provider
and the whole cache is now mixed-model, which silently degrades ranking. If that
happens, `git checkout` both artifacts and start over.

Record the before/after `entry_count` and `content_sha256` in the task report.

Then refresh the mask, which the reseed's literals just changed:

```bash
psql "$DATABASE_URL" -X -q -c 'SELECT retrieval.refresh_mask_blob()'
```

Expected: `15` (Task 13 Step 8's count, after `sensitive_literals()` was extended
to the incident and change columns). A different number means the seeded cohort
differs from Task 13's — read it rather than accepting it.

- [ ] **Step 13: Run every gate against live**

```bash
gates/checks.sh
```

Expected, and each expectation is a claim about live state:

| Gate | Expected | Why |
|---|---|---|
| G-27 | PASS if `WORKSHOP_APP_DATABASE_URL` is set and the login has a password; otherwise BLOCKED on the missing DSN | it needs to `SET ROLE` as `workshop_app` |
| G-29 | PASS | `pg_columnmask` and the corpus are both present now |
| G-30 | BLOCKED until the sibling repo provisions the participant password | honest: the identity exists, nothing can log in as it |
| G-31 | PASS | analyst results byte-identical to the pre-collapse baseline |
| G-11, G-13, G-21, G-23, G-25 | PASS | unchanged by this task |

A BLOCKED on G-27/G-30 for a missing password is the correct report, **not** a
reason to set a password from this repo. Record the full output.

- [ ] **Step 14: Confirm the canonical answer is still byte-identical on live**

The one assertion that would catch a restricted row reaching the room:

```bash
curl -s localhost:8000/v1/agent/answer -H 'content-type: application/json' \
  -d '{"question":"<the canonical question, read from the guide>","role":"analyst"}' \
  | jq -S '{answer, citations: [.citations[] | {external_key, claim, quote_text}]}' \
  > /tmp/canonical_live_after.json
diff /tmp/canonical_after_collapse.json /tmp/canonical_live_after.json
```

Empty diff is the pass. A difference means a restricted row entered the analyst's
answer on the live cluster: **stop, report, and do not present**. That is an ACL
failure, not a golden to update.

- [ ] **Step 15: Update `seed/README.md` with the measured count**

`seed/README.md:56` opens the regeneration recipe with "Regenerate after the corpus
changes:". Add, immediately before that line:

```markdown
The restricted cohort is part of the corpus, so a change to it changes the cache.
As of the RLS reseed the manifest records the count measured in step 2 below;
`--verify-cache` fails loudly when the two disagree, which is what a stale manifest
should do.
```

- [ ] **Step 16: Commit the regenerated artifacts**

```bash
git add seed/artifacts/casework-embeddings.jsonl \
        seed/artifacts/casework-embeddings.jsonl.manifest.json seed/README.md
git commit -m "Regenerate the embedding cache for the restricted cohort"
```

The cache and its manifest go in **one** commit. A commit with only one of them
fails every account's load — which `seed/README.md:72-73` says is the intended
outcome, and is also why they must never be split.

- [ ] **Step 17: Final report**

State, in this order: which gates PASS and which are BLOCKED and on what; the
before/after `entry_count` for the cache; the `refresh_mask_blob()` count; whether
the canonical diff was empty; the `rolsuper` branch taken in Step 3; and the two
things that are built but **not yet enforcing** — the app pool still connects as
`DATABASE_URL` until the sibling repo provisions `workshop_app`'s password, and
`workshop_participant` cannot log in until the same happens. Enforcement is
complete when those two passwords exist, and that is a sibling-repo task.

---

## Self-Review

Run against the spec (`docs/superpowers/specs/2026-07-28-rls-personas-column-masking-design.md`,
commit 1b0c90e) and amendments A1-A8.

**1. Spec coverage.** Every requirement maps to an owning task:

| Requirement | Task |
|---|---|
| A1 `workshop_participant`, zero-ceremony, fail-closed first lesson | 3 (gate), 5 (roles + admission definer rights) |
| A2 personas are NOLOGIN | 5 |
| A3 verify-SQL transaction envelope | 12 |
| A4 chip is a mirror; "Viewing as"; app flip first | 11, 14 |
| A5 mask patterns generated, corpus-wide leak scan | 2 (gate), 6, 13 Step 8 |
| A6 both SPEC copies byte-identical | 15 |
| A7 one persona axis, `workbench.role` GUC deleted, `support-lead` retired | 4 (gate), 9, 10, 11, 14, 15 |
| A8 `can_see_restricted`, granted to admin+auditor only | 5 |
| Blocker 1 option (a): `RESTRICTED_ACL` visibility flips | 13 |
| Blocker 3: no `Verity` identifiers anywhere | 8 |
| D24 RLS built, FORCE on all three read-path tables | 5 |
| Masking scope B (three casework columns, two `account_name`, one blob) | 6 |
| G-27, G-29, G-30, G-31 | 1, 2, 3, 4 |
| Canonical answer unchanged | 10 Step 14, 13 Step 10, 16 Step 14 |
| Live deployment behind an explicit gate | 16 Steps 9-17 |

No requirement is unowned.

**2. Placeholder scan.** Four intentional `<placeholder>`s remain, each a value
that cannot be known when the plan is written and each with the command that
produces it named in the same step: `<the canonical question, read from the guide>`
(Task 13 Step 10, Task 16 Step 14), `<bundle>` / `<the release bundle path>` (Task
16 Steps 11-12), and the SPEC hash re-baseline in Task 15. Two steps are marked
`[VERIFY]` and are BLOCKING by design — Task 6 Step 1 (the `pg_columnmask` policy
inventory: the extension's replace semantics are unmeasured, and both branches are
written out in full so the implementer deletes one rather than inventing one) and
Task 16 Step 3 (the local `rolsuper` fork, with both branches written out). No
"TBD", no "add error handling", no "similar to Task N".

**3. Type consistency.** Checked across task boundaries:
`PERSONAS: tuple[str, ...]` and `Persona = Literal["analyst","admin","auditor"]`
live in `backend/app/db.py` (Task 7); `models.py` declares its own `Persona`
Literal and Task 10 Step 12 adds `PersonaLiteralAgreementTests` to keep the two
equal. `persona_role(persona) -> str` returns `persona_<name>`, and every SQL
literal in Tasks 5, 6, 12 and 16 uses that exact prefixed form. `get_conn(persona,
*, row_factory)`, `get_dict_conn(persona)`, `get_owner_conn(*, row_factory)` are
used with those signatures in Tasks 10, 13 and 16. The predicate expression
`acl_visibility = 'workshop' OR pg_has_role(current_user, 'can_see_restricted',
'USAGE')` appears byte-identically in `sql/11` (Task 5), the H2 hole (Task 9), and
the guide (Task 14). Gate exit codes are `PASS=0 / FAIL=1 / BLOCKED=2` throughout.
The restricted key set is the same seven keys in Tasks 13, 14 and 16.

**Nine defects found and fixed during review, each recorded in Global Constraints
so no implementer re-introduces it. Every one is the same class of mistake — code
written against a mental model of the schema, the privilege system, or the build
order instead of against the thing itself — which is why each now has a
behavioural probe rather than an assertion. Defects 1-7 were found by reading;
defects 8 and 9 were found by *running* G-27 against a real PostgreSQL cluster,
and neither was reachable by review:**

1. **Task 7/10/12 wrote pytest-style tests into a repo with no pytest.** All ten
   existing test files are `unittest.TestCase`, `make test` runs `unittest
   discover`, and a module-level `def test_*()` is invisible to it — the new
   security tests would have silently never run while their "Expected: FAIL" steps
   read as satisfied. Converted to `unittest`; all nine `python -m pytest`
   invocations replaced with the dotted-module form.
2. **`GRANT EXECUTE` alone would not let a participant run `./admit.sh`.**
   `casework.admit_evidence` is `plpgsql` with no `SECURITY DEFINER`
   (`sql/10_admission.sql:36-39`), so its body runs as the caller and its first
   statement reads `casework.ingest_receipts`. Lab 1's finale would die on
   `permission denied` while G-30's `has_function_privilege` probe still reported
   PASS. Task 5 now applies definer rights with a pinned `search_path` and revokes
   PUBLIC; G-30 asserts `prosecdef` and `proconfig`; Task 5 Step 6 actually invokes
   the writer and distinguishes 23503 (correct) from 42501 (broken).
3. **Definer rights fix the first half of `admit.sh` and not the second.** The
   exact-arm checkpoint at `admission/admit.sh:25-29` is a bare `SELECT` on
   `casework.evidence_items` outside the function, so Lab 1 would print the ingest
   receipt and die one line later — the *same* defect as (2), one statement further
   on, and it survived the fix for (2). Task 5 Step 2 wraps the checkpoint in the A3
   envelope under `persona_analyst`, which is better than the grant that would have
   silenced it: the participant's own admission now comes back through live RLS.
   A grant would have destroyed the A1 lesson G-30 asserts.
4. **`SET ROLE` needed an explicit grant to the bootstrap owner.** With the
   checkpoint now inside the envelope, `admit.sh` run by a developer (as the owner)
   raised `permission denied to set role`, while the participant path worked — a
   divergence visible only to whoever is not in the room. `sql/11` GRANTs the three
   personas to `current_user WITH INHERIT FALSE`; Step 6 probes both identities and
   keeps a negative control proving the bare read is still denied.
5. **`sql/12`'s unconditional `SELECT retrieval.refresh_mask_blob()` would break
   `make schema` on a fresh account.** `make schema` runs before `make
   seed-casework`, so the corpus is empty, so the function's own "no restricted
   literals" raise fires and fails the schema build. Now guarded: it skips with a
   `RAISE NOTICE` when the corpus has no literals, which is safe in exactly one
   direction because the shipped `mask_blob` body redacts the whole blob.
6. **Task 16's analyst-arm probe called a function that does not exist.** A defect
   in this plan's own test code rather than in the design: `retrieval.lexical_search(text[])`
   is not a thing. The lexical arm is `retrieval.full_text_search(p_query text, …)`
   (`sql/03_search_functions.sql:220-236`) and only the fuzzy arm takes `text[]`
   (`:556-571`). Corrected to a per-arm (statement, argument) pair list.
7. **Task 5 asserted the login roles' attributes with `ALTER ROLE`.** Changing
   `NOBYPASSRLS`/`NOSUPERUSER` needs a true superuser. `retrieval_admin` is an
   `rds_superuser` *member*, so the statement succeeds on a local cluster and raises
   on Aurora — a deployment-only failure, the worst kind to discover live. It is now
   a `pg_roles` assertion that needs no privilege.
8. **G-27's `rds_superuser` probe crashed the gate on every non-Aurora cluster.**
   Found by execution, not by reading. `pg_has_role(current_user, 'rds_superuser',
   'USAGE')` raises `psycopg.errors.UndefinedObject: role "rds_superuser" does not
   exist` — at *plan* time, so no boolean short-circuit, `CASE` arm, or `EXISTS`
   guard can save it. The exception escaped `run()` and turned an honest
   PASS/FAIL/BLOCKED report into a traceback with exit 1, meaning the gate could
   never run locally at all. Fixed with a `pg_roles`-subselect-by-OID helper
   (`_member_of`) used for both `rds_superuser` and `can_see_restricted`.
9. **G-27's central row-filtering probe read a column `retrieval.chunks` does not
   have.** Found by execution. The probe selected `external_key`; chunks carries
   `evidence_id` only (`sql/01_schema.sql:951-999`), so the query raised
   `UndefinedColumn` at the third table and group (b) — the assertion the entire
   enforcement claim rests on — asserted nothing there. Fixed by keying the probe on
   `evidence_id`, the only identity column common to all three read-path tables,
   with `DISTINCT` for the per-version rows. Two review passes over this gate had
   read straight past it.

**What was actually executed, and what was not.** G-27 (`gates/rls_enforcement.py`,
Task 1) was extracted from this plan and run against a throwaway PostgreSQL 17
cluster carrying a miniature three-table read path with the real RLS shape — enable
+ force, the three policies, `can_see_restricted`, NOLOGIN personas granted `WITH
INHERIT FALSE`, and a non-superuser owner. It reaches PASS on the healthy shape, and
it was then driven through every failure and BLOCKED path below by breaking the
cluster one way at a time. Each was caught with the right message and the right exit
code:

| Scenario | Result |
|---|---|
| Healthy | PASS, exit 0 |
| Clearance revoked from the measuring owner | FAIL, names the `GRANT can_see_restricted` block |
| Owner absent from a policy's `TO` list | FAIL, names "add CURRENT_USER to those policies' TO lists" |
| Cleared owner, but absent from the `documents` policy | FAIL on the projection check (`retrieval.documents: 0`) — the silent-truncation case |
| Genuinely empty restricted cohort | FAIL, blames the seed |
| Superuser owner + empty cohort | FAIL via the bypass branch, still blames the seed |
| `can_see_restricted` granted to `persona_analyst` (fail-open leak) | FAIL at group (b), prints the leaked `evidence_id` |
| Pool login given a standing `SELECT` | FAIL, "the pool fails OPEN" |
| RLS `FORCE` dropped / no app DSN | BLOCKED, exit 2, names the table or the missing DSN |

That is one gate of four. Tasks 2, 3, 4 and every SQL and application step remain
instructions to the implementer, measured only against the schema and source they
cite. Two `[VERIFY]` steps are blocking for exactly that reason, and one genuinely
unmeasurable thing remains unmeasured: `pg_columnmask` is Aurora-managed and cannot
be installed locally, so its policy-replacement semantics are unknown. Task 6 Step 1
measures them on the target cluster, with both branches written out, before a line of
`sql/12` is trusted.

---

## Execution Handoff

Plan complete and saved to
`docs/superpowers/plans/2026-07-28-rls-personas-column-masking.md`. Two execution
options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review
between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch
execution with checkpoints.

Which approach?
