# Verity → Workbench Machine-Token Migration

**Goal:** Purge the remaining `verity` machine tokens (env-var prefix, wire
headers, service identifiers, DB objects, runtime paths, physical test
databases) and replace them with a `workbench` scheme, as one reviewed change
across this repo and the sibling Workshop Studio repo.

**Status:** SPEC — execution gated on Codex landing its UI-rename commits.

**Scope note:** The *participant-visible* name is already "Hybrid Retrieval
Workbench" everywhere (backend `app_display_name` default, both `.env.example`
files, and — in flight via Codex — the UI prose and CSS vars). This migration
covers ONLY the machine layer that a participant never sees but that other
systems bind to.

---

## Target scheme (decided)

| Class | From | To |
|---|---|---|
| Env-var prefix | `VERITY_` | `WORKBENCH_` |
| Config Field names | `verity_*` | `workbench_*` |
| Wire header | `X-Verity-Transport` | `X-Workbench-Transport` |
| Service/app identifiers | `verity-*` | `workbench-*` |
| Python identifiers | `verity_tool_run` | `workbench_tool_run` |
| DB schema | `verity_capture` | `workbench_capture` |
| Runtime path | `/run/verity` | `/run/workbench` |
| JSON-Schema `$id` | `verity.workshop` | `workbench.workshop` |
| Physical test DBs | `verity_*_test` | `workbench_*_test` |

## Execution gate (HARD)

Do NOT begin until Codex has committed its UI-rename work and the working tree
is clean of these paths:

- `frontend/src/VerityApp.tsx`
- `frontend/src/verity.css`
- `design/SPEC-session.md`
- `design/verity-handoff/docs/SPEC-session.md`
- `design/verity-html-mockups/` (untracked)

Reason: (1) the env-var contract is documented inside both `SPEC-session.md`
copies — renaming the env vars in code while the spec still says `VERITY_*`
desyncs code from spec; (2) `frontend/src/main.tsx` imports `./VerityApp` and
`./verity.css`, so those files must be renamed together with Codex's edits, not
out from under them.

`git status --porcelain=v1 | grep -iE 'verity|SPEC-session'` must be empty
before starting.

## Standing constraints (verbatim)

- Commits authored `shayons@amazon.com`, NO Claude co-author trailer (public
  aws-samples repo).
- `.env` holds a live Aurora credential — never commit/log/echo/paste it.
- Every destructive DB command sets `DATABASE_URL=` INLINE and asserts the
  resolved db name before running (the run_sql DSN trap).
- Never touch the live `retrieval` database destructively.
- Keep the two `SPEC-session.md` copies byte-identical.
- `casework.*` authoritative, `retrieval.*` derived/never hand-edited.

---

## Migration units

### Unit A — Backend env contract + config

**Files:** `backend/app/config.py`, `backend/app/insights.py`,
`backend/app/search.py`, `backend/scripts/smoke_test.py`,
`gates/verify_sql_golden.py`

- `config.py` Field names + env keys: `verity_cluster_id`/`VERITY_CLUSTER_ID`,
  `verity_db_resource_id`/`VERITY_DB_RESOURCE_ID`,
  `verity_region`/`VERITY_REGION`,
  `verity_dbi_url_template`/`VERITY_DBI_URL_TEMPLATE`,
  `verity_lock_url_template`/`VERITY_LOCK_URL_TEMPLATE` → `workbench_*` /
  `WORKBENCH_*`.
- Consumers of those Fields: `insights.py` (`verity_cluster_id`,
  `verity_region`, `verity_dbi_url_template`, `verity_lock_url_template`),
  `search.py:782` (`verity_db_resource_id`).
- `smoke_test.py:26` reads `VERITY_READINESS_FILE`; `verify_sql_golden.py` reads
  `VERITY_SMOKE_RUN_ID` + `VERITY_READINESS_FILE` (lines 28-29, 84-88, 193) →
  `WORKBENCH_*`.
- Test after: `python -m backend.tests.test_admission`; `make smoke` writes
  READINESS; `gates/verify_sql_golden.py` reads it.

### Unit B — Wire header (two-sided, atomic)

**Files:** `mcp-server/src/server.ts:10`, `backend/app/main.py:102,107`

- `X-Verity-Transport` (set by mcp-server) and `x-verity-transport` +
  `x-verity-transport-trace-id` (read by main.py) → `X-Workbench-Transport` /
  `x-workbench-transport` / `x-workbench-transport-trace-id`.
- MUST change both ends in the same commit — a one-sided rename silently drops
  the transport trace.
- Test after: stdio MCP round-trip sets and reads the header.

### Unit C — Service / app identifiers

**Files:** `backend/app/main.py:115` (`verity-incident-evidence`),
`mcp-server/src/server.ts:33` (same name), `backend/app/db.py:44`
(`verity-pg`), `backend/app/agent_tools.py:59` (`verity_tool_run` ContextVar),
`scripts/invoke_agentcore_gateway.py:58` (`verity-{method}`),
`seed/capture.py` (`verity-lock-capture-v1`, `verity-offline-writer-1/2`,
`verity-offline-capture`, `verity-offline-index-build`).

- CAUTION `seed/capture.py`: the offline-writer application_name values are
  self-referenced by the `pg_stat_activity` ILIKE filter and the
  `verity_capture.orders` query. Rename the literals AND their matching filter
  together.

### Unit D — DB schema + runtime path

**Files:** `seed/capture.py` (`verity_capture.orders`, `FIXTURE_SCHEMA =
"verity_capture"`), `admission/promote_pg_incident.py:50`
(`--capture-dir` default `/run/verity`), `admission/README.md:93`,
`admission/payload_v1.schema.json:3` (`$id` `https://verity.workshop/...`).

- `verity_capture` schema is created transiently by the offline seed (NOT
  resident on the live cluster now — confirmed), so renaming the literal is
  sufficient; no live `ALTER SCHEMA` needed unless a stale copy exists at
  execution time (check first).
- `/run/verity` → `/run/workbench`: this is a deployed filesystem path. The
  sibling bootstrap systemd units write PID files there (spec §4). Coordinate
  with the sibling: the path must match on both sides.

### Unit E — Physical test databases (live infra ops)

Confirmed resident: `verity_admission_test`, `verity_test`,
`verity_journey_20260728_test`.

- `ALTER DATABASE verity_admission_test RENAME TO workbench_admission_test;`
  (and the other two). Requires no active connections to the target DB.
- `README.md:233,249,250,251` reference `verity_test` in the local-Postgres
  test recipe → `workbench_test`.
- `.superpowers/sdd/progress.md` references `verity_admission_test` (ledger
  scratch, git-ignored — update in place, not a commit).
- Guard: run each RENAME with `DATABASE_URL=` inline pointing at the cluster's
  default DB (NOT `retrieval`), assert the target name exists before renaming.

### Unit F — Sibling Workshop Studio repo

**Repo:** `/Users/shayons/Desktop/Workshops/build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql`

- `assets/hybrid-retrieval-code-editor.yml:1176` (`VERITY_API_BASE_URL` CFN
  env) + `:1187` (bootstrap `os.environ["VERITY_API_BASE_URL"]`) →
  `WORKBENCH_API_BASE_URL`. Both in the same commit.
- Any `/run/verity` path the sibling systemd units write must move to
  `/run/workbench` in lockstep with Unit D.
- Orion-era stale assets (packaged source, guides, screenshots) are a SEPARATE
  larger workstream — flagged here, not executed as part of the token rename.
  This migration only touches the coupling token + the runtime path.

---

## Execution order

1. Confirm Codex landed (gate above). Confirm `retrieval` DB untouched.
2. Unit E first (live DB renames) — independent of code, lowest coupling, and
   frees the ledger reference. Assert names before/after.
3. Units A–D as one code commit (env + header + identifiers + schema/path).
   Two-sided header (B) in the same commit as its readers.
4. Frontend file rename: `VerityApp.tsx` → the new name + `verity.css` → new
   name + `main.tsx` imports, in the same commit as Codex's landed edits are
   already in the tree (safe now that Codex is clean).
5. Both `SPEC-session.md` copies: env-var + path references, kept byte-identical.
6. Unit F (sibling repo) as its own commit in its own repo.
7. Full verification: `make schema` (disposable DB), `test_admission`,
   `test_retrieval_integration`, `make smoke`, `gates/checks.sh`, stdio MCP
   header round-trip, sibling CFN lint.

## Verification checklist

- `git -P grep -iE 'verity' -- . ':(exclude)design/verity*'` returns only
  intentional historical references (e.g. app-name-history prose), zero live
  machine tokens.
- `test_admission` 8/8, `test_retrieval_integration` green.
- `make smoke` PASS; READINESS written; `verify_sql_golden` reads new env keys.
- stdio MCP round-trip: header set by server is read by backend under the new
  name.
- Sibling CFN: `WORKBENCH_API_BASE_URL` set and read; no `VERITY_` remains.
- Live DBs: `SELECT datname FROM pg_database WHERE datname LIKE '%verity%'`
  returns zero rows.
