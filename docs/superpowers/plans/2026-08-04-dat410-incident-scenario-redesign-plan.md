# DAT410 Incident Scenario Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Lab 1's broken, Performance-Insights-dependent single-incident mechanism with a real, measured, production-representative four-phase incident (unbatched migration backfill → connection-pool exhaustion → query-plan regression, diagnosed before remediation), producing a two-wave evidence corpus (expected 50–80 searchable documents per run, gated on behavioral coverage rather than a document count) that gives Labs 2–4's retrieval/agent/citation mechanics genuine material to work with.

**Architecture:** A new orchestration driver in `labs/incident/` runs four phases against a real 3,000,000-row `workbench_lab.orders` table: (1) an unbatched backfill left open in an explicit transaction, (2) 12–14 tagged hot-write requests through the existing FastAPI connection pool, of which 10 obtain connections and block inside PostgreSQL on distinct rows while the remaining 2–4 never obtain a connection and exhaust their checkout timeout — proving row-lock blocking and pool exhaustion as two separately measured signals, via condition-based polling (not fixed sleeps), (3) commit, drain, and recovery verification, (4) — deferred to Lab 4 — the participant's own `CREATE INDEX` fixing a query-plan regression that `ANALYZE` alone does not fix. Evidence is admitted in two waves: Wave A (diagnostic, end of Lab 1) and Wave B (remediation, end of Lab 4, additive not replacing). The full design rationale, real measurements, and every rejected alternative are in `docs/superpowers/specs/2026-08-04-dat410-incident-scenario-redesign-design.md` — read it before starting any task below; this plan does not repeat that reasoning.

**Tech Stack:** Python 3.13 (`labs/incident/`, `backend/app/`), PL/pgSQL (`sql/`), FastAPI/`psycopg_pool`, Cohere Embed v4 via Bedrock, existing 7-tool agent registry (`agent/registry.py`), React/TypeScript frontend (`frontend/src/`), Workshop Studio content (sibling repo).

## Global Constraints

- **Session thesis — the outcome every participant-facing surface must express.** The outcome is **not** "participants fixed a missing index"; that is the mechanism. The thesis, verbatim, is: *At fleet scale, telemetry is abundant; trustworthy context is scarce. Participants build the database-native evidence layer an operational agent needs: live signals become versioned, searchable evidence; Aurora PostgreSQL retrieves, combines, ranks, relates, and cites that evidence; and a human validates the recommendation before any action is taken.* The closing message, verbatim: *you built the trusted context layer required by a fleet-scale database agent.* Full rationale and the five theme mappings are in the design spec's "Session Thesis and Closing Message" section, which governs copy wherever this plan and that spec appear to disagree. Three rules follow and bind every task in Phases D, E, and G:
  - **Signal-to-noise → hybrid retrieval and reranking (Lab 2); the expertise gap → a cited, replayable recommendation (Labs 3–4); human-in-the-loop → "recommend, don't execute" (Lab 4); semantic/context layers → casework/retrieval/proof (Labs 1–4); fleet expansion → the "Take it home" architecture discussion, in the closing only.**
  - **Fleet expansion never becomes lab scope.** No task may add a second cluster, a multi-tenant dimension, or cross-fleet aggregation to any lab. The theme is satisfied by explaining how the evidence layer scales, not by scaling it live inside a 60-minute budget.
  - **The closing claim must be literally true of the participant's own run.** A participant whose Wave B admission failed did not build a validated evidence layer; the closing surface must not tell them they did. This is the live-data-only rule applied to the summary text, not only to the data. It follows that the closing message is emitted by `labs/incident/run_live_workshop.py`'s `--wave B` path after a successful admission (Task D3), never printed unconditionally on a static content page, which renders identically for a failed run.
- **Terminology, exact and non-negotiable in all participant-facing content and code comments:**
  - "migration" always means an application-level **online schema and data migration** (`ADD COLUMN` + backfill) — never Aurora engine-version migration. Say "online schema and data migration" or "the migration," never bare "upgrade."
  - This is a **real, measured, production-representative incident** — not "a production incident." It did not occur in an actual production system; it is a widely-recognized failure pattern reproduced live on a real Aurora cluster. Never write "production incident."
  - Participant-facing terminology: "incident diagnosis" → "evidence-backed finding"; "remediation delta" → "validation evidence"; "incident agent" → "hybrid retrieval agent"; "remediate" → "apply and validate the recommendation." Internal package/schema/ID names (`labs/incident/`, `casework.*`, `INC-<run-suffix>`, etc.) do NOT change.
  - Participant-facing agent name: **Hybrid Retrieval Agent**, described as a **read-only database-evidence agent** — distinct from the app's own name "Hybrid Retrieval Workbench" (`backend/app/config.py`'s `APP_DISPLAY_NAME`, unchanged).
  - Lab titles: Lab 1 "Capture and admit live evidence"; Lab 2 "Build hybrid retrieval in SQL"; Lab 3 "Build the hybrid retrieval agent"; Lab 4 "Validate, prove, and replay."
- **Scale, exact numbers, do not round or approximate:** `workbench_lab.orders` = 3,000,000 rows (`LAB_ROWS` constant, currently 25,000). `workbench_lab.customers` stays 5,000. Corpus expectation = **50–80 searchable documents** per incident run (DECIDED 2026-08-04 after Gate 5, replacing the 180–250 figure from this plan's earlier drafts — Gate 5 measured that one honestly-constructed document per genuinely distinct event across all six signal types totals 51 documents, and that padding beyond the natural event count reintroduces the near-duplicate problem). This is an **expected range, not a hard acceptance gate** — corpus adequacy is gated on the behavioral coverage criteria in `docs/superpowers/specs/2026-08-04-dat410-incident-scenario-redesign-design.md`'s "Corpus Adequacy" section (every phase and signal type represented; the four arms produce meaningfully different top candidates; fusion/rerank reorder for defensible reasons; Wave B adds genuinely new facts; near-duplicate rate under 15%; citations and replay resolve to exact document versions). Documents must come from genuinely distinct signal types — never from denser time-sampling of the same signal. CloudWatch documents do not count toward this range. **Never inflate the count to hit a number**; that is manufacturing evidence, which the live-data-only rule forbids however it is dressed up.
- **Sequential scans are correct at this corpus size, and participant-facing content says so plainly.** At 50–80 documents PostgreSQL's planner may correctly prefer a sequential scan over an HNSW index scan on some retrieval arms. Do not apologize for it, do not engineer around it, and do not inflate the corpus to change it. Production-scale ANN behavior belongs in an appendix note, never folded into a core lab's numbers.
- **Live-data-only, unchanged from the existing project rule:** zero fixtures/mocks/dummy/offline/canned records anywhere in the participant path, ever. Every document in both Wave A and Wave B must derive from genuinely measured observations of that participant's own run.
- **Concurrency contract, exact and load-bearing — `REQUEST_COUNT` is deliberately greater than `DB_POOL_MAX_SIZE`.** The hot-write driver launches **12–14 concurrent requests** (`LAB_HOT_WRITE_REQUEST_COUNT`, default 12) against a pool of `DB_POOL_MAX_SIZE = 10`. Exactly **10 obtain a connection** and block inside PostgreSQL on **distinct** `order_id`s (`Lock:transactionid`, backfill PID in `pg_blocking_pids()`); the remaining **2–4 never obtain a connection at all** and exhaust their 3-second checkout timeout, producing `PoolTimeout`. These are two different signals measured on two different populations, and the plan never conflates them. **The arithmetic must close:** requests that hold a slot cannot simultaneously be waiting for one, so a run of exactly 10 requests can produce at most 9 blocked sessions plus 1 `PoolTimeout` — which is precisely what Gate 1 measured, and precisely why 10 was the wrong request count. Launching more requests than slots is the only way to observe a fully-blocked pool *and* a non-empty wait queue at the same instant.
- **Timeout policy, three separate bounds, never collapsed:** checkout timeout **3s** (`LAB_HOT_WRITE_CHECKOUT_TIMEOUT_SECONDS`) bounds only the wait for a free slot and is what the queued extras hit; blocked-statement timeout **30–45s** (`LAB_HOT_WRITE_STATEMENT_TIMEOUT`, default `'40s'`) bounds a connected writer's row-lock wait and must comfortably exceed backfill-completion time plus the 10–15s observation hold, so that blocked writers are still blocked when the hold is proven and still alive to drain after the commit; and `max_attempt_seconds` (**90s**) bounds the controller's own proving loop. A 3-second statement timeout cannot sustain a 10–15s hold — the writers would all cancel themselves before the hold began, leaving nothing blocked to observe.
- **The hold is condition-based, never a fixed sleep.** The hold controller polls `get_pool().get_stats()` plus `pg_stat_activity`/`pg_locks` every 250ms and only begins the 10–15s observation hold after 3 consecutive samples simultaneously prove the **combined** condition: `pool_size = pool_max = 10`, `pool_available = 0`, `requests_waiting >= 2`, and exactly `DB_POOL_MAX_SIZE` (10) tagged sessions show `wait_event_type = 'Lock'` with the backfill PID in `pg_blocking_pids()`. The blocked-session expectation is `DB_POOL_MAX_SIZE`, **not** the launched request count.
- **The first 10 writes drain successfully after the commit; the queued extras are the `PoolTimeout` evidence.** When the backfill commits, the 10 blocked writers acquire their row locks and commit — a real, observable recovery, and the honest end of the incident. The 2–4 queued requests have already returned `pool_timeout` and stay that way. A run where **zero** writes ever commit means the statement timeout fired too early (Phase B regression, see the timeout policy above); a run with **zero** `pool_timeout` means the pool never saturated and the incident did not happen.
- **The 250ms poll is control, not document generation.** Persist every raw poll sample (matching the existing `casework.*_samples` pattern). Create a searchable document only on a state change or a meaningful interval boundary — never one document per poll tick.
- **The agent never gets DDL privilege or an execution path.** This is already true today (all 7 tools in `agent/registry.py` are read/synthesis-only) — no task in this plan may add a write-capable tool. The participant executes `CREATE INDEX` themselves in Code Editor after reviewing the agent's recommendation.
- **Supervised execution is proven by rows, not asserted by copy, and the proof is separated in time.** Tasks A5, A6, D2a, D3, E4, and G1–G3 implement one model together, and five of its properties bind every task that touches it:
  - **The agent proposes structured fields; code renders the SQL.** A model-authored DDL string handed to a human to run is an injection sink with a human as the executor, and a free-text statement can contradict the fields stored beside it. The proposal carries action type, schema, table, index method, ordered key columns, and included columns; `render_create_index()` builds the statement from those fields, and every identifier is checked against `^[a-z_][a-z0-9_]*$`. **A partial-index predicate is rejected, not rendered** — it is the one field that would reach emitted DDL without passing that check, and it also cannot be fingerprinted consistently because the catalog rewrites it through `pg_get_expr()`. Both halves are enforced: `ValueError` in Task D2a's parser, `CHECK (predicate IS NULL)` in `proof.action_proposals`. If a future action type needs free-form SQL, it does not get to reuse this path.
  - **Equality is answered by a canonical structured fingerprint, never by comparing SQL text.** Whitespace, quoting, casing, and equivalent PostgreSQL syntax make a hash of the statement worthless as an equality test. `proof.canonical_index_key()` normalizes both sides and `proof.observed_index_fingerprint()` reads what PostgreSQL actually built. Raw SQL hashes are stored for audit only and must never gate a decision. **Case folding is one rule in one function, `proof.canonical_sql_name()`, applied to every name-shaped field on both sides: fold only when the whole string matches `^[A-Za-z_][A-Za-z0-9_]*$`, preserve everything else byte-exact.** Measured on PostgreSQL 17.10: a per-field `lower(btrim(...))` made an index on `workbench_lab."ORDERS"` fingerprint identically to the proposal for `workbench_lab.orders`, and a `LIKE '%"%'` test collapsed two expression indexes differing only in a string literal. A field that skips this function is a defect regardless of whether its current inputs happen to be lower-case.
  - **The two verdicts are computed, not narrated, and neither may read the other's inputs.** `proof.autonomy_readiness()` returns `pre_execution_eligible` and `post_execution_validated` with explicit reasons for each. Successful post-execution evidence must never retroactively make a proposal look safe beforehand — this is enforced in the function (A5), proven absent rather than merely unused by G-34 (A6), diffed live against a real participant's run (G1), and preserved in the UI contract (E4, where no conditional may read the execution row to decide what to say about pre-execution eligibility).
  - **The proposal and execution tables are INSERT-only for every non-owner role, and their verdict columns are immutable even for the owner.** No task may grant `UPDATE` on `proof.action_proposals` or `proof.action_executions`. `UPDATE` on the first would let a proposal be edited to match what was executed; `UPDATE` on the second would let a failed outcome be rewritten as success. A proposal that needs amending is a new proposal, and an execution that did not match must be recorded, not skipped. Privilege alone does not carry this rule: the recorder runs as the owner, which holds `UPDATE` inherently, so `proof.action_executions` also carries the `action_executions_append_only` trigger (Task A5 step 3, code in Task D3 step 8). It permits exactly one mutation — attaching the two Wave B receipt identifiers once, via `proof.attach_wave_b_receipt()` — and raises on any attempt to change `outcome`, `fingerprint_matches`, `observed_fingerprint`, `observed_index_definition`, `executed_sql`, `executed_sql_sha256`, `approved_by`, `approved_at`, or either key.
  - **The claim is autonomy *readiness*, never autonomous execution.** No participant-facing surface may describe the workshop as demonstrating autonomous remediation or an agent that fixed the database. A human approved and executed; the verdict assesses whether that action would have been safe unattended, judged only on what was known before it was taken.
- **Wave B is additive, never a replacement.** Before-`ANALYZE`, after-`ANALYZE`, and post-index plan checkpoints all remain separate, permanently retrievable documents. Never tombstone or supersede Wave A evidence because Wave B exists. Version (`is_current`) only genuinely mutable facts (e.g., incident status `investigating`→`resolved`), never the observations themselves.
- **No new fragile external dependency.** Reuse the existing FastAPI pool (`backend/app/db.py`, `DB_POOL_MAX_SIZE=10`) for pool exhaustion. Do not add RDS Proxy, PgBouncer, pgbench, JMeter, or ECS/Lambda-driven load generation. CloudWatch stays best-effort, non-gating, never blocking the pipeline.
- **Participant-facing incident time (Lab 1's induce/capture) stays under the 5–8 minute ceiling.** Bootstrap (3M-row table creation) is pre-session Workshop Studio provisioning time, not counted against this ceiling.
- **Preserve the optional RLS/masking lab and AgentCore lab** unless a task below finds a specific, concrete incompatibility (none anticipated — neither touches `workbench_lab` or the incident-generation code path today).
- **The optional security module is never on the one-hour critical path, and the gate split that enforces this already exists.** `gates/checks.sh` keeps G-27, G-29, G-30, and G-31 in `SECURITY_GATES`; the evolving `CORE_GATES` registry is the source of truth for the default retrieval sweep. Running `gates/checks.sh` with no arguments populates `WANT` from `CORE_GATES` only *and* forces `export WORKBENCH_SECURITY_ENABLED=0`, so the core sweep cannot be turned into a security sweep by an environment variable. The original seven-gate measurement confirmed that boundary; Tasks A4 and A6 deliberately add core gates without changing it. The security gates run only when named by ID (`gates/checks.sh G-27 G-29 G-30 G-31`). Three rules follow, and they bind every task in this plan:
  - **No task may move a security gate into `CORE_GATES`, and no task may describe G-27, G-29, G-30, or G-31 as blocking core participant readiness.** A red security gate means the optional RLS lab is not releasable; it does not mean the workshop is not releasable.
  - **Lab 3 stays retrieval-first.** No task may make persona switching, `SET LOCAL ROLE`, a restricted citation, or any `acl_visible`/`acl_scalars_visible` behaviour a requirement of Labs 1–4's core path. Phase D contains no such requirement today (verified by grep across the whole phase) and must not acquire one. The canonical Lab 3 answer must resolve identically on a database that has never run `make security-schema`.
  - **The optional RLS lab is releasable only against a real mixed-visibility capture** — see the optional-security release criteria below. This is a separate, later gate on a separate deliverable, not a precondition for freezing the core workshop.
- **Optional-security release criteria (separate from core participant readiness).** The core workshop is releasable when Task G3 Step 1's default sweep is green. The *optional RLS/masking lab* is releasable only when all three of the following hold, and none of them is a precondition for the core freeze:
  1. `WORKBENCH_SECURITY_ENABLED=1 FAIL_ON_BLOCKED=1 gates/checks.sh G-27 G-29 G-30 G-31` exits 0 against a database that has had `make security-schema` applied.
  2. That database holds a **real mixed-visibility capture** produced by an actual `make live-workshop` run: at least one `casework.evidence_items` row with `acl ->> 'visibility' = 'restricted'` **and** at least one with `'workshop'`, both classified by Task C1's classifier from the participant's own measured statement text. A corpus that is uniformly `workshop` or uniformly `restricted` proves nothing about row filtering, and a hand-labelled row is authored data — forbidden by live-data-only however it is dressed up.
  3. The recorded evidence names the counts, not just the verdicts: the restricted row count, the workshop row count, and the classifier version that produced them. "G-27 PASS" without a count cannot distinguish a working mechanism from one that happened to fire.
  Until (2) exists, G-27 and G-29 have nothing to judge and their result is not release evidence for the optional lab in either direction. Say so plainly rather than recording a green sweep against an unmixed corpus.
- **Every classification is replayable: version, reason, and sources travel with the row.** Any code in this plan that assigns `acl.visibility` must record, alongside the value, the classifier version that produced it, the machine-readable reason it fired, and the identifiers of the measured samples the decision was read from. Task C1 defines the fields, Task C2 threads them into the admission payload, Task A2 makes the ACL explicit and required at the admission boundary. A visibility label with no recorded reason cannot be audited, cannot be replayed, and cannot be distinguished from a hand-labelled one — which is exactly the accusation live-data-only exists to defeat.
- **`casework.admit_evidence` must require an explicit ACL and never silently default one.** `sql/10_admission.sql:418` currently reads `coalesce(v_record -> 'acl', '{"visibility":"workshop"}'::jsonb)`, so a producer that forgets the field gets a silently unrestricted corpus and no error anywhere. Task A2 replaces that default with a `RAISE`-guarded requirement. Silence at a classification boundary is the failure mode; a loud rejection is the fix.
- **Aurora PostgreSQL owns ranking.** This redesign changes evidence generation shape; it never moves fusion/rerank logic out of `sql/03_search_functions.sql` or into the agent/frontend.
- **New gate IDs start at G-32** (G-31 is the highest existing gate anywhere in the codebase, confirmed via `gates/*.py` and `gates/checks.sh`).
- **Test convention, matching existing files exactly:** `TEST_DATABASE_URL` + `ALLOW_TEST_DATABASE_RESET=1`, database name must end in `_test`, `_apply_schema(connection, reset=True)` pattern from `backend/tests/test_admission.py`/`test_incident_lab.py`. Never run destructive tests against `DATABASE_URL` alone — always verify `current_database()` first.
- **Every task that runs SQL/Python against a real database must inline-set `DATABASE_URL` to the disposable test database and assert `current_database()` before any write** — this project has a documented prior incident (`run-sql-dsn-trap-live-drop` memory) where a script defaulted to the wrong DSN and dropped a live database.
- **Ad-hoc SQL runs use `psql`, not `run_sql.py`.** `backend/scripts/run_sql.py` accepts **only** `--files` (see `run_sql.py:47`); it has no `--statement` flag and never has. Every verification and cleanup step in this plan that runs one-off SQL uses the following exact shape, which was measured against a real PostgreSQL server on 2026-08-04:

```bash
/opt/homebrew/opt/libpq/bin/psql -X -v ON_ERROR_STOP=1 \
  "postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" <<'SQL'
DO $guard$ BEGIN
  IF current_database() <> 'dat410_review_remediation_test' THEN
    RAISE EXCEPTION 'SAFETY ABORT: connected to %', current_database();
  END IF;
END $guard$;
-- statements go here
SQL
```

  Four properties of this shape are load-bearing and each was verified, not assumed:
  - `-X` skips `~/.psqlrc`. Without it a personal startup file changes the output format and can silently break an expected-output comparison; this machine's `.psqlrc` sets `\timing` and a null display, both of which appeared in measured output until `-X` was added.
  - `-v ON_ERROR_STOP=1` makes a mid-script error exit non-zero and skip the remaining statements. Measured: the guard failing aborted with `exit=3` and the following `CREATE TABLE` did not run (`to_regclass(...) IS NULL` returned true afterward). Without it, `psql` reports the error and keeps going.
  - The `DO $guard$` block is what enforces the disposable-database rule *inside the same connection that performs the write*, so there is no window between checking and writing. Verified in both directions: it aborted before the write on the wrong database, and it allowed the write through when the name matched.
  - Use a **quoted** heredoc (`<<'SQL'`). Unquoted, the shell expands `$guard$` and `$1`, corrupting the SQL.

  Do not substitute `psql -U <user>` for the connection URI: `-U` does **not** override a user embedded in the URI (measured — `-U nosuchuser` still connected as the URI's user, in either argument order), so a `-U` flag reads as an effective control while doing nothing. Put the user in the URI. If `psql` is not at the path above, use `command -v psql`; do not rely on a shell alias, which is not visible to non-interactive scripts.

---

## Gate Tasks (Risk-Reduction, Must Pass Before Proceeding to Implementation)

These six gates exist because further design discussion cannot reduce the remaining risk — only working prototypes can. Each gate task produces a small, throwaway or semi-throwaway script proving one specific claim against the real Aurora cluster, before any schema/orchestration/UI work begins. If a gate fails, STOP and return to design — do not patch around a failed gate to keep moving.

**Historical execution record:** all six gates have run. The tracked `_gate*.py`
throwaways were removed from `labs/incident/` after the repository audit so the
participant lab directory contains only supported runtime assets. The Files,
write, and run steps below explain how the measurements were produced; they are
not current commands. Use
`docs/superpowers/specs/2026-08-04-dat410-gate-results.md` and the named historical
commits when implementation needs to inspect a prototype.

### Gate 1: Prove all 10 API sessions block directly on the backfill while the pool-status endpoint remains responsive

**Files:**
- Create: `labs/incident/_gate1_pool_block.py` (throwaway prototype script, not shipped — delete or move to `labs/incident/` proper only if Task "Hot-write driver" below reuses its logic verbatim)

**Interfaces:**
- Consumes: `backend/app/db.py`'s real `get_pool()`/`get_conn()` (the actual FastAPI pool, imported directly, not reimplemented)
- Produces: a pass/fail report (printed, not a test-framework assertion) proving the exact behavioral claim below

This gate closes the one unverified claim from the design spec's "Measured Baseline — New 3M-Row Mechanism" section: the earlier live test used direct short-lived `psycopg` connections with a `statement_timeout`, not the real `psycopg_pool.ConnectionPool`. This gate must use the real pool.

**Retrospective note (added during the 2026-08-04 correction pass, after this gate had already run and passed):** this gate did exercise the real pool, and that claim is closed. It did **not** exercise the real HTTP endpoint, which Task B2 now owes separately. It also ran with `REQUEST_COUNT = DB_POOL_MAX_SIZE = 10` and a 3-second statement timeout, both of which the corrected concurrency and timeout contracts in Global Constraints supersede. Gate 1's outcome distribution (nine `statement_timeout`, one `pool_timeout`) is therefore a property of the gate script, not the target mechanism — the shipped mechanism launches 12 requests and expects ten `committed` plus two `pool_timeout`. The gate's two HC findings are unaffected and remain binding; only its counts and timeout value are stale. Do not use this gate's numbers as acceptance values anywhere downstream.

**The code block in Step 2 below is the pre-fix draft, deliberately left as written.** It has no statement timeout and issues `SET LOCAL application_name` as a bare `conn.execute()` — the exact two defects HC-1 and HC-2 were discovered by running it. The passing prototype is preserved in historical commit `2c8c1cb` and its findings are recorded in `docs/superpowers/specs/2026-08-04-dat410-gate-results.md`; it was removed from `labs/incident/` after the repository audit because throwaway executables are not participant assets. Any implementer copying Step 2's code verbatim into shipped code would reintroduce both hard contracts as bugs.

- [ ] **Step 1: Read the design spec's Two-Wave Evidence Model and Components sections again for the exact hold-controller contract**

Re-read `docs/superpowers/specs/2026-08-04-dat410-incident-scenario-redesign-design.md`'s "Hold controller," "Hot-write driver," and "Timeout policy" component descriptions before writing any code — the exact 250ms/3-consecutive-sample/`pool.connection(timeout=3.0)`/`PoolTimeout` contract must match precisely, not be approximated.

- [ ] **Step 2: Write `labs/incident/_gate1_pool_block.py`**

```python
#!/usr/bin/env python3
"""Gate 1: prove all 10 API sessions block directly on the backfill while the
pool-status endpoint remains responsive. Throwaway prototype -- not shipped.
Run against a disposable _test database only.
"""
from __future__ import annotations

import concurrent.futures
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import psycopg
import psycopg_pool

from backend.app import db as app_db
from backend.app.config import get_settings


def safety_check() -> None:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        name = conn.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY ABORT: {name} does not end in _test")
    print(f"safety check passed: {name}")


def build_3m_orders(conn: psycopg.Connection) -> None:
    conn.execute("DROP SCHEMA IF EXISTS workbench_lab CASCADE")
    conn.execute("CREATE SCHEMA workbench_lab")
    conn.execute(
        """
        CREATE TABLE workbench_lab.orders (
          order_id bigint PRIMARY KEY,
          status text NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO workbench_lab.orders(order_id, status)
        SELECT value, 'created' FROM generate_series(1, 3000000) value
        """
    )
    conn.execute("ANALYZE workbench_lab.orders")


def main() -> int:
    safety_check()
    settings = get_settings()

    with psycopg.connect(settings.database_url, autocommit=True) as setup_conn:
        t0 = time.monotonic()
        build_3m_orders(setup_conn)
        print(f"bootstrap: {time.monotonic() - t0:.2f}s")

    # Open the backfill in an explicit transaction, left uncommitted.
    backfill_conn = psycopg.connect(
        settings.database_url,
        autocommit=False,
        application_name="workbench-lab-backfill",
    )
    t0 = time.monotonic()
    with backfill_conn.cursor() as cur:
        cur.execute("UPDATE workbench_lab.orders SET status = 'backfilled'")
    print(f"backfill (left open): {time.monotonic() - t0:.2f}s")
    with backfill_conn.cursor() as cur:
        cur.execute("SELECT pg_backend_pid()")
        backfill_pid = cur.fetchone()[0]
    print(f"backfill PID: {backfill_pid}")

    # Drive 10 hot-write requests through the REAL app pool (backend/app/db.py),
    # not a direct connection -- this is what Gate 1 exists to verify.
    app_db.open_pool()
    hot_ids = list(range(1, 11))

    def hot_write(order_id: int) -> tuple[str, float]:
        t0 = time.monotonic()
        try:
            with app_db.get_pool().connection(timeout=3.0) as conn:
                conn.execute(
                    "SET LOCAL application_name = 'workbench-lab-api-hot-write'"
                )
                conn.execute(
                    "UPDATE workbench_lab.orders SET status = 'touched' WHERE order_id = %s",
                    (order_id,),
                )
            return ("ok", time.monotonic() - t0)
        except psycopg_pool.PoolTimeout:
            return ("pool_timeout", time.monotonic() - t0)

    # While the 10 writers are blocked, repeatedly hit a pool-status check that
    # performs NO checkout -- this is the exact claim Gate 1 must prove: the
    # pool-status path stays responsive even while every real slot is blocked.
    status_results: list[tuple[float, dict]] = []

    def poll_status_no_checkout() -> None:
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            t0 = time.monotonic()
            stats = app_db.get_pool().get_stats()
            elapsed = time.monotonic() - t0
            status_results.append((elapsed, stats))
            time.sleep(0.25)

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        status_future = pool.submit(poll_status_no_checkout)
        write_futures = [pool.submit(hot_write, oid) for oid in hot_ids]
        outcomes = [f.result() for f in write_futures]
        status_future.result()

    backfill_conn.rollback()
    backfill_conn.close()

    print()
    print("=== Hot-write outcomes (expect all pool_timeout) ===")
    all_blocked = all(status == "pool_timeout" for status, _ in outcomes)
    for i, (status, dur) in enumerate(outcomes, 1):
        print(f"  writer {i}: {status} after {dur:.2f}s")
    print(f"ALL 10 BLOCKED VIA PoolTimeout: {all_blocked}")

    print()
    print("=== Pool-status responsiveness while blocked (expect all fast, low ms) ===")
    max_status_latency = max(elapsed for elapsed, _ in status_results) if status_results else None
    print(f"samples collected: {len(status_results)}")
    print(f"max status-check latency: {max_status_latency:.4f}s" if max_status_latency else "NO SAMPLES")
    saturated_samples = [
        s for _, s in status_results
        if s.get("pool_available", -1) == 0 and s.get("requests_waiting", 0) >= 2
    ]
    print(f"samples showing pool_available=0 and requests_waiting>=2: {len(saturated_samples)}")

    gate_passed = (
        all_blocked
        and status_results
        and max_status_latency < 0.5
        and len(saturated_samples) >= 3
    )
    print()
    print(f"GATE 1 {'PASSED' if gate_passed else 'FAILED'}")

    with psycopg.connect(settings.database_url, autocommit=True) as cleanup_conn:
        cleanup_conn.execute("DROP SCHEMA IF EXISTS workbench_lab CASCADE")
    app_db.close_pool()

    return 0 if gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Run the gate against the disposable test database**

```bash
export TEST_DATABASE_URL="<your Aurora cluster's disposable _test database DSN>"
DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/python labs/incident/_gate1_pool_block.py
```

Expected: `GATE 1 PASSED` — every writer is genuinely blocked (by checkout timeout *or* statement timeout, which are different outcomes and must be counted separately), the pool-status endpoint's max latency stays well under 0.5s even while the pool is fully saturated, and at least 3 samples show the pool genuinely exhausted (`pool_available=0`, `requests_waiting>=2`).

**Actual result, for the record:** nine `statement_timeout` (3.19–6.15s) and one `pool_timeout` (3.01s) — not ten `pool_timeout`. An earlier draft of this step predicted all ten would be `pool_timeout`; that prediction was wrong for a mechanical reason worth keeping visible. With ten requests against ten slots, nine requests obtain connections and block in PostgreSQL, so only the tenth can ever see an empty pool. This is the arithmetic that drove the corrected 12-request contract in Global Constraints.

- [ ] **Step 4: If the gate fails, diagnose before retrying**

If some writer neither blocks nor times out: check `DB_POOL_MAX_SIZE` is actually 10 in the test environment's config (`backend/app/config.py`), and that `hot_write`'s row selection (IDs 1–10) matches the backfill's actual scan order — re-verify with a smaller writer count first if this fails, don't assume the earlier session's "lowest IDs collide first" finding transfers unchanged to the real pool path.

Do **not** "fix" a split of `statement_timeout` and `pool_timeout` outcomes — that split is the correct behavior and is what the shipped mechanism measures deliberately. Only a writer that returns `ok` during the hold, or one that hangs with no bound at all, indicates a real failure here.

If the pool-status check shows high latency or blocks: this means `get_stats()` itself may be acquiring a lock shared with checkout — this would be a genuine design problem requiring escalation back to the spec, not a bug to patch silently.

- [ ] **Step 5: Record the result**

Append the gate's actual output (pass/fail, latencies, sample counts) to a new file `docs/superpowers/specs/2026-08-04-dat410-gate-results.md` — this becomes the running record all six gates write to, read by later tasks instead of re-running gates to check their own prior results.

---

### Gate 2: Prove Wave A replay remains unchanged after Wave B admission

**Files:**
- Create: `backend/tests/_gate2_replay_isolation.py` (throwaway prototype, not a shipped test — the real test class comes later in the "Schema and Admission" phase)

**Interfaces:**
- Consumes: existing `casework.admit_evidence` (unmodified at this point — this gate tests today's function twice, simulating Wave A/Wave B by admitting two different capture payloads under the same `capture_id`'s incident identity, since the real follow-up admission contract doesn't exist yet)
- Produces: pass/fail proving `proof.retrieval_candidates` rows written by a run against the first admission are byte-identical after a second, later admission touching the same evidence items

- [ ] **Step 1: Read `backend/app/agent.py`'s `explain_ranking_impl` and `backend/tests/test_admission.py`'s existing fixtures**

Confirm the exact query shape `explain_ranking_impl` uses against `proof.retrieval_candidates` (already read once during design — re-confirm signature hasn't drifted before writing the gate).

- [ ] **Step 2: Write the throwaway isolation test**

```python
#!/usr/bin/env python3
"""Gate 2: prove a retrieval run's replayed candidates are unaffected by a later
admission touching the same evidence. Throwaway prototype against a real _test DB.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import psycopg

from backend.app import db as app_db
from backend.app.agent import explain_ranking_impl, search_evidence_impl
from backend.app.config import get_settings


def safety_check() -> str:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        name = conn.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY ABORT: {name}")
        return name


def main() -> int:
    safety_check()
    # Precondition: this gate assumes a real live-workshop run has already been
    # admitted (Wave A equivalent) against this test database, producing at
    # least one evidence document. Run `make live-workshop` against
    # TEST_DATABASE_URL first if evidence_items is empty.
    with app_db.get_owner_conn() as conn:
        count = conn.execute("SELECT count(*) FROM casework.evidence_items").fetchone()[0]
        if count == 0:
            print("SKIP: no evidence admitted yet -- run the live orchestrator against "
                  "this test database first, then re-run this gate")
            return 2

    role = "app_engineer"
    search_result = search_evidence_impl(query="INC-", limit=5, role=role)
    run_id = search_result["run_id"]
    before = explain_ranking_impl(run_id, role=role)
    before_candidates = json.dumps(before["candidates"], sort_keys=True, default=str)

    # Simulate a "later admission touching the same evidence" by re-admitting
    # something that writes to casework/retrieval without altering the specific
    # candidates the run already saw -- the real Wave B admission contract does
    # not exist yet, so this gate proves the REPLAY PATH's isolation property in
    # isolation from the not-yet-built admission contract.
    with app_db.get_owner_conn() as conn:
        conn.execute(
            "UPDATE casework.evidence_items SET updated_at = now() "
            "WHERE evidence_id = (SELECT evidence_id FROM casework.evidence_items LIMIT 1)"
        )

    after = explain_ranking_impl(run_id, role=role)
    after_candidates = json.dumps(after["candidates"], sort_keys=True, default=str)

    identical = before_candidates == after_candidates
    print(f"GATE 2 {'PASSED' if identical else 'FAILED'}: replayed candidates "
          f"{'unchanged' if identical else 'CHANGED'} after a later write")
    return 0 if identical else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Run against a test database with at least one real admitted run**

```bash
export TEST_DATABASE_URL="<disposable _test DSN>"
# If evidence_items is empty, run the live orchestrator once first:
DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/python labs/incident/prepare_workload.py
DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/python labs/incident/run_live_workshop.py \
  --db-cluster-identifier <your-cluster-id> --db-instance-identifier <your-instance-id> --region us-east-1
DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/python backend/tests/_gate2_replay_isolation.py
```

Expected: `GATE 2 PASSED`. This confirms the design spec's claim (`explain_ranking_impl` reads a persisted snapshot, immune to later writes) holds against the real database, not just against reading the SQL text.

- [ ] **Step 4: Record the result in `docs/superpowers/specs/2026-08-04-dat410-gate-results.md`**

---

### Gate 3: Confirm pre-remediation evidence remains additive rather than incorrectly superseded

**Files:**
- Create: `backend/tests/_gate3_additive_evidence.py` (throwaway prototype)

**Interfaces:**
- Consumes: `casework.evidence_items.is_current`, `retrieval.documents.is_current` (existing versioning columns)
- Produces: pass/fail proving that inserting a new evidence record referencing the same incident does NOT flip `is_current=false` on any existing, unrelated evidence record

This gate exists because "additive, not replacing" is a design intent stated in the spec, not yet mechanically enforced or tested against the real versioning columns. The risk: if any existing trigger or admission logic treats "new evidence about the same incident" as "supersede the old row," Wave B would silently break Wave A's retrievability.

- [ ] **Step 1: Inspect every trigger/function that sets `is_current`**

```bash
grep -n "is_current" sql/*.sql
```

Read every result — confirm exactly which functions can set `is_current = false` on an existing row, and under what condition. This determines what Gate 3 needs to provoke and check.

- [ ] **Step 2: Write the throwaway test**

```python
#!/usr/bin/env python3
"""Gate 3: prove admitting new evidence for an incident does not flip
is_current=false on unrelated existing evidence. Throwaway, real _test DB only.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import psycopg

from backend.app import db as app_db
from backend.app.config import get_settings


def main() -> int:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        name = conn.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY ABORT: {name}")

    with app_db.get_owner_conn() as conn:
        before = conn.execute(
            "SELECT evidence_id, is_current FROM casework.evidence_items "
            "WHERE is_current = true ORDER BY evidence_id"
        ).fetchall()
        if not before:
            print("SKIP: no current evidence -- admit a live run first")
            return 2
        before_ids = {row[0] for row in before}

        # Insert a synthetic new evidence row referencing the SAME source_system,
        # simulating "Wave B adds a record" without going through the not-yet-built
        # follow-up admission contract. If any admission-adjacent trigger reacts to
        # new rows by demoting existing ones, this will surface it.
        conn.execute(
            """
            INSERT INTO casework.evidence_items
              (evidence_id, external_key, evidence_kind, source_system, source_uri,
               content_hash, is_current, is_deleted, acl)
            VALUES
              (gen_random_uuid(), 'GATE3-PROBE-01', 'telemetry', 'pg_incident_capture',
               'workshop://gate3-probe', 'gate3-probe-hash', true, false,
               '{"visibility":"workshop"}'::jsonb)
            """
        )

        after = conn.execute(
            "SELECT evidence_id, is_current FROM casework.evidence_items "
            "WHERE evidence_id = ANY(%s)",
            (list(before_ids),),
        ).fetchall()
        after_current = {row[0] for row in after if row[1]}

        # Clean up the probe row.
        conn.execute(
            "DELETE FROM casework.evidence_items WHERE external_key = 'GATE3-PROBE-01'"
        )

    unaffected = after_current == before_ids
    print(f"GATE 3 {'PASSED' if unaffected else 'FAILED'}: existing is_current rows "
          f"{'unaffected' if unaffected else 'CHANGED'} by inserting a new evidence row")
    return 0 if unaffected else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Run against the test database used in Gate 2 (evidence already present)**

```bash
DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/python backend/tests/_gate3_additive_evidence.py
```

Expected: `GATE 3 PASSED`.

- [ ] **Step 4: If it fails, identify the exact trigger/function responsible before designing the real follow-up admission contract** — this would be a Critical finding requiring the "Schema and Admission" phase below to fix the root cause, not route around it.

- [ ] **Step 5: Record the result in `docs/superpowers/specs/2026-08-04-dat410-gate-results.md`**

---

### Gate 4: Add fail-safe cleanup for timeouts, abandoned transactions, load generators, pool recovery, and reruns

**Files:**
- Create: `labs/incident/_gate4_cleanup_probe.py` (throwaway prototype proving the cleanup mechanism, not the shipped cleanup code itself — that lands in the Orchestration phase)

**Interfaces:**
- Consumes: `pg_terminate_backend`, `pg_stat_activity` (standard PostgreSQL), `app_db.close_pool()`/`open_pool()`
- Produces: pass/fail proving that a deliberately abandoned backfill transaction, a deliberately hung hot-write driver, and a deliberately exhausted pool can all be detected and cleanly recovered without requiring a fresh database

This gate exists because Gates 1–3 all assume the happy path. A real participant session WILL produce abandoned transactions (a participant's Code Editor tab closes mid-hold, a network blip kills a connection) — if there's no tested recovery path, one participant's crash blocks that whole account's remaining session.

- [ ] **Step 1: Enumerate the failure modes this gate must prove recoverable**

From the task title, four distinct failure modes, each needs its own probe:
1. A hot-write request that times out (already proven recoverable by Gate 1's `PoolTimeout` handling — cross-reference, don't re-prove).
2. An abandoned backfill transaction (the orchestrator process crashes or is killed after opening the backfill but before committing).
3. A hung/crashed hot-write driver (the thread pool doesn't exit cleanly).
4. Rerunning the whole scenario against a database that still has state from a previous, abandoned run.

- [ ] **Step 2: Write the abandoned-transaction recovery probe**

```python
#!/usr/bin/env python3
"""Gate 4: prove abandoned backfill transactions, hung load generators, and
pool exhaustion all recover cleanly without a fresh database. Throwaway,
real _test DB only.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import psycopg

from backend.app.config import get_settings


def safety_check(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        name = conn.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY ABORT: {name}")
        print(f"safety check passed: {name}")


def probe_abandoned_transaction(dsn: str) -> bool:
    """Simulate a crashed orchestrator: open a transaction, hold a lock, kill the
    process hard (SIGKILL, not close()), then prove a cleanup routine can find
    and terminate the orphaned backend."""
    proc = subprocess.Popen(
        [sys.executable, "-c", f"""
import psycopg
conn = psycopg.connect({dsn!r}, autocommit=False, application_name='gate4-orphan')
conn.execute("SELECT pg_sleep(60)")
"""],
    )
    time.sleep(2)  # let it start the sleep

    with psycopg.connect(dsn, autocommit=True) as check_conn:
        orphan = check_conn.execute(
            "SELECT pid FROM pg_stat_activity WHERE application_name = 'gate4-orphan'"
        ).fetchone()
        if not orphan:
            print("probe_abandoned_transaction: FAILED to even start the orphan")
            proc.kill()
            return False
        orphan_pid = orphan[0]

    proc.send_signal(signal.SIGKILL)  # simulate a hard crash, not graceful close
    proc.wait(timeout=5)

    # The orphaned backend is still alive server-side even though the client
    # process is dead -- prove a cleanup routine can find and terminate it.
    with psycopg.connect(dsn, autocommit=True) as cleanup_conn:
        still_there = cleanup_conn.execute(
            "SELECT pid FROM pg_stat_activity WHERE application_name = 'gate4-orphan'"
        ).fetchone()
        if not still_there:
            print("probe_abandoned_transaction: orphan already gone (TCP keepalive "
                  "cleaned it up faster than expected -- not a failure, just fast)")
            return True
        cleanup_conn.execute(
            "SELECT pg_terminate_backend(%s)", (still_there[0],)
        )
        time.sleep(1)
        gone = cleanup_conn.execute(
            "SELECT pid FROM pg_stat_activity WHERE application_name = 'gate4-orphan'"
        ).fetchone()

    success = gone is None
    print(f"probe_abandoned_transaction: {'PASSED' if success else 'FAILED'}")
    return success


def probe_pool_recovery(dsn: str) -> bool:
    """Prove the app pool recovers to full availability after a saturation
    episode ends, with no manual intervention."""
    sys.path.insert(0, str(REPO_ROOT))
    from backend.app import db as app_db

    app_db.open_pool()
    stats_before = app_db.get_pool().get_stats()

    # Saturate briefly with real checkouts held open, then release.
    import concurrent.futures
    def hold_briefly():
        with app_db.get_pool().connection(timeout=3.0) as conn:
            conn.execute("SELECT pg_sleep(1)")

    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as pool:
        futures = [pool.submit(hold_briefly) for _ in range(15)]
        for f in futures:
            try:
                f.result()
            except Exception:
                pass  # some will legitimately PoolTimeout -- expected

    time.sleep(1)
    stats_after = app_db.get_pool().get_stats()
    recovered = stats_after.get("pool_available", -1) == stats_after.get("pool_size", -2)
    print(f"probe_pool_recovery: {'PASSED' if recovered else 'FAILED'} "
          f"(before={stats_before}, after={stats_after})")
    app_db.close_pool()
    return recovered


def probe_rerun_against_dirty_state(dsn: str) -> bool:
    """Prove workbench_lab can be rebuilt cleanly even if a prior run left it
    in a non-canonical state (matches the DROP SCHEMA ... CASCADE pattern
    already in run_live_workshop.py's _create_lab_workload)."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS workbench_lab CASCADE")
        conn.execute("CREATE SCHEMA workbench_lab")
        conn.execute("CREATE TABLE workbench_lab.orders (order_id bigint PRIMARY KEY)")
        conn.execute("INSERT INTO workbench_lab.orders VALUES (999999)")  # dirty/non-canonical row
        # Simulate the real rebuild path.
        conn.execute("DROP SCHEMA IF EXISTS workbench_lab CASCADE")
        conn.execute("CREATE SCHEMA workbench_lab")
        conn.execute(
            "CREATE TABLE workbench_lab.orders (order_id bigint PRIMARY KEY, status text NOT NULL)"
        )
        count = conn.execute("SELECT count(*) FROM workbench_lab.orders").fetchone()[0]
        clean = count == 0
        conn.execute("DROP SCHEMA IF EXISTS workbench_lab CASCADE")
    print(f"probe_rerun_against_dirty_state: {'PASSED' if clean else 'FAILED'}")
    return clean


def main() -> int:
    settings = get_settings()
    dsn = settings.database_url
    safety_check(dsn)

    results = {
        "abandoned_transaction": probe_abandoned_transaction(dsn),
        "pool_recovery": probe_pool_recovery(dsn),
        "rerun_dirty_state": probe_rerun_against_dirty_state(dsn),
    }
    all_passed = all(results.values())
    print()
    print(f"GATE 4 {'PASSED' if all_passed else 'FAILED'}: {results}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Run the gate**

```bash
DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/python labs/incident/_gate4_cleanup_probe.py
```

Expected: `GATE 4 PASSED` across all three probes.

- [ ] **Step 4: If `probe_abandoned_transaction` fails**, this means orphaned backends from a crashed orchestrator are NOT automatically cleaned up by connection-level mechanisms alone — the Orchestration phase below must add an explicit `pg_terminate_backend` sweep (matching the existing `_assert_no_live_lab_sessions` pattern in `run_live_workshop.py`, which already checks for and rejects stale `workbench-live-*` sessions before starting — extend that pattern to actively terminate, not just reject).

- [ ] **Step 5: Record the result in `docs/superpowers/specs/2026-08-04-dat410-gate-results.md`**, including specifically which of the three probes needed a design change vs. passed on the first attempt.

---

### Gate 5: Validate corpus diversity and deduplication before freezing document-count expectations

**Files:**
- Create: `labs/incident/_gate5_corpus_diversity.py` (throwaway prototype)

**Interfaces:**
- Consumes: a real Wave-A-shaped set of documents (constructed from Gate 1/4's real backfill+hold+query-regression run, not synthetic text)
- Produces: a report of near-duplicate document pairs (via `pg_trgm` similarity or embedding cosine distance) at the then-current 180–250 target scale, informing whether that range is actually achievable without the near-duplicate problem the design spec explicitly wants to avoid

This gate exists because the 180–250 target and its six signal-type categories are a design intent, not yet validated against real generated text. The risk: even "distinct signal types" could still produce near-duplicate document bodies if the text-generation templates are too similar across state-change events (e.g., many pool-saturation snapshots that differ only in a timestamp).

**Outcome, and why 180–250 no longer appears in Global Constraints:** the gate answered its own question with "no." A 148-document sample built by cycling numbers through fixed sentence templates failed at a 20.65% near-duplicate rate; a 51-document sample with one document per genuinely distinct event passed at 6.43%. The corpus expectation is now **50–80 documents**, DECIDED 2026-08-04. Every 180–250 reference inside this gate task is preserved as the historical target the gate was measuring against — do not treat it as a live requirement, and do not "update" it to 50–80, which would erase the evidence for the decision.

- [ ] **Step 1: Generate a realistic sample set of Wave-A-shaped document bodies**

Using the six signal-type categories from the design spec's Evidence builder component (lock/blocking-state transitions, pool saturation/recovery, request latency/timeout aggregates, WAL/statement deltas, backfill/recovery/index metadata, three query-plan checkpoints), hand-write ~30–40 representative document bodies per category using REAL data from Gate 1's actual run output (the printed pool stats, lock states, timing numbers) — not lorem-ipsum placeholders. This is the first real content-shape test.

- [ ] **Step 2: Write the diversity-check script**

```python
#!/usr/bin/env python3
"""Gate 5: check near-duplicate rate across a realistic sample corpus before
freezing the 180-250 document count target. Throwaway prototype."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from itertools import combinations

import psycopg

from backend.app.config import get_settings


def main() -> int:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        name = conn.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY ABORT: {name}")

        # documents: list[tuple[str, str]] of (external_key, body) built in Step 1,
        # loaded here from a JSON file written during that step.
        import json
        documents = json.loads(Path("/tmp/gate5_sample_documents.json").read_text())

        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        near_dupes = []
        for (key_a, body_a), (key_b, body_b) in combinations(documents, 2):
            similarity = conn.execute(
                "SELECT similarity(%s, %s)", (body_a, body_b)
            ).fetchone()[0]
            if similarity > 0.6:
                near_dupes.append((key_a, key_b, similarity))

    print(f"documents checked: {len(documents)}")
    print(f"near-duplicate pairs (trigram similarity > 0.6): {len(near_dupes)}")
    for key_a, key_b, sim in sorted(near_dupes, key=lambda x: -x[2])[:20]:
        print(f"  {key_a} <-> {key_b}: {sim:.3f}")

    dupe_rate = len(near_dupes) / max(1, len(documents))
    gate_passed = dupe_rate < 0.15  # threshold: fewer than 15% of all pairs near-duplicate
    print()
    print(f"GATE 5 {'PASSED' if gate_passed else 'FAILED'} (near-dupe rate: {dupe_rate:.1%})")
    return 0 if gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Run the gate**

```bash
DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/python labs/incident/_gate5_corpus_diversity.py
```

- [ ] **Step 4: If the gate fails**, identify which signal-type category is producing the near-duplicates and redesign that category's document-body template (e.g., include more of the actual varying measurement in the body text, not just the timestamp) before locking the corpus expectation — do not silently widen the similarity threshold to force a pass. (This is exactly what happened: the first attempt failed at 20.65%, the fix was per-event structural variation, and the outcome was the 50–80 expected range now recorded in Global Constraints.)

- [ ] **Step 5: Record the result, including the actual measured dupe rate, in `docs/superpowers/specs/2026-08-04-dat410-gate-results.md`** — this number directly informs whether the Evidence builder tasks later in this plan need a design adjustment before implementation.

---

### Gate 6: Run one complete Aurora rehearsal before broad Workshop Studio and participant-copy updates

**Files:** none created — this gate is a checkpoint, not a script.

**Interfaces:** consumes the combined output of Gates 1–5.

- [ ] **Step 1: Confirm Gates 1–5 all show PASSED in `docs/superpowers/specs/2026-08-04-dat410-gate-results.md`** before proceeding. If any gate is still FAILED, stop — do not begin the Orchestration/Corpus/Labs/UI/Infrastructure phases below with an unresolved gate.

- [ ] **Step 2: Report the consolidated gate results to the user** and get explicit go-ahead before starting the "Schema and Admission" phase. This is a deliberate human checkpoint, not an automatic pass-through — the six gates de-risk the mechanism, but committing to the full schema/orchestration/UI/infrastructure build is a bigger investment the user should explicitly approve seeing the real gate evidence first.

- [ ] **Step 3 (after all remaining implementation phases land, referenced here for sequencing only — do not execute yet):** the final "Rehearsal" phase at the end of this plan is Gate 6's real completion — one full, timed, end-to-end run of the finished mechanism against the real Aurora cluster, before any broad Workshop Studio content or participant-copy changes ship. This early Gate 6 step is the checkpoint; the full rehearsal task is defined in this plan's final phase.

---

## Hard Contracts Carried Forward From Gate 1

Two findings from Gate 1 are **hard contracts**, not advice. Every task below that
touches the pooled write path must satisfy both, and every reviewer must check
both. They were each found by a real hang against the real cluster, not reasoned
out on paper.

**Contract HC-1 — pool checkout timeout and blocked-statement timeout are
separate.** `pool.connection(timeout=3.0)` bounds only the *checkout* wait — how
long a caller waits for a free pool slot. A writer that obtains a connection
*before* the pool saturates then has **no bound at all** on its row-lock wait.
Gate 1 attempt 1 hung indefinitely with `pg_stat_activity` showing sessions
`active`/`wait_event = 'Lock:Transactionid'` for 50+ seconds and no timeout
firing. Therefore: the hot-write path must set **both** a checkout timeout
(`pool.connection(timeout=...)`) **and** a statement-level timeout
(`SET LOCAL statement_timeout`). Neither alone is sufficient. Both timeout values
are configuration, and the two are never collapsed into one setting.

**The two values are not equal, and this is the part Gate 1 got wrong.** Gate 1
used `3s` for both, which is correct for the checkout bound and wrong for the
statement bound: with a 3-second statement timeout every connected writer cancels
itself roughly 3 seconds into the backfill, so by the time a 10–15 second
observation hold would begin there is nothing left blocked to observe. The
shipped policy is **checkout 3s, statement 30–45s** (default `'40s'`) — long
enough that blocked writers survive the backfill's remaining runtime plus the
full hold and then drain on commit. Gate 1's nine `statement_timeout` outcomes
are therefore an **artifact of the gate's own 3-second setting**, not the
target behavior; the shipped mechanism expects those same ten writers to end in
`committed`.

**Contract HC-2 — `SET LOCAL` and the update must execute inside one explicit
transaction on the same pooled connection.** Pooled connections run
`autocommit=True` (`backend/app/db.py`'s `_configure_connection`), so a bare
`conn.execute("SET LOCAL ...")` runs in its own implicit transaction that ends
immediately, silently resetting the setting to its default before the `UPDATE`
runs in a fresh transaction. Gate 1 attempt 2 still hung for exactly this reason.
Therefore: `SET LOCAL application_name`, `SET LOCAL statement_timeout`, and the
`UPDATE` must all execute inside one `with conn.transaction():` block on one
checked-out connection. Never as separate bare `execute()` calls, never split
across two checkouts, and never via `get_conn()` (which opens its own transaction
for persona role-setting and is not the lab hot-write path).

---

## Repository-wide alignment audit (2026-08-05)

The post-A3 audit reviewed all 146 tracked files at `108e604`, including runtime
code, SQL, gates, tests, exercises, frontend, root documentation, and packaging.
The branch is intentionally not narrative-complete while Phases B-G remain
unimplemented. The audit found no reason to change the approved scenario, but it
did find stale surfaces that the original Files blocks did not own. They are now
assigned as follows:

| Owner | Alignment work added by the audit |
|---|---|
| A4 | Wave-A identity after Wave B in G-21; schema-correct G-32; payload-derived G-25 counts |
| B1 / B6 | `prepare_workload.py`; final transaction-ID lock constraints; diagnostics/readiness; admission and release-capture fixtures |
| C1 / C2 | Masking/classifier narrative; doctor and latest-run two-wave identity; retrieval integration |
| D2 | Agent decomposition, registry descriptions, generated MCP adapters, AgentCore invocation, exercises, checkpoints, and their tests |
| E1 / E2 | Entire visible UI scenario and wire shape; provenance-derived Wave A/B corpus grouping |
| F1 | Root docs, architecture/session docs, incident README, environment prerequisites, and source-archive completeness |
| G3 | Final measured values, terminology sweep, core-gate registry truth, and both source/Workshop Studio thesis checks |

Historical gate notes and this design plan may still name the retired mechanism
when explaining why it was removed. Executable code, current contracts, tests,
participant exercises, UI copy, and source-of-record documentation may not. No
stale runtime or participant-facing surface found by this audit remains without
an owning task.

---

## Phase A — Schema and Admission

Owning schema: `casework` (authoritative) plus the `retrieval` relationship
constraint. This phase makes the database able to accept the new incident's shape
and, for the first time, accept a **second, later admission against an existing
incident identity** (Wave B). Nothing in this phase produces evidence; it only
makes the contracts correct. Gate 3 explicitly left "genuinely new Wave B
admission works end to end" owed to this phase.

### Task A1: Delete the Performance Insights admission surface

**Owning schema/module:** `casework` schema; `sql/10_admission.sql`,
`sql/01_schema.sql`.

**Files:** dropping this table breaks four separate `CREATE`/`ALTER` statements at
**apply** time, in three files this task must therefore also edit. Every one was
measured on PostgreSQL 17.10 against a schema with the table absent, and every one
is a hard `ERROR: relation "casework.database_insights_samples" does not exist`
that stops `make schema` dead. `IF NOT EXISTS` and `OR REPLACE` do not save any of
them — those clauses guard the *object being created*, never the relation it
references:

```
sql/02_indexes.sql:42   CREATE INDEX IF NOT EXISTS idx_database_insights_capture_type   -> ERROR
sql/04_diagnostics.sql:282,294  CREATE OR REPLACE VIEW casework.v_live_capture_validation -> ERROR
sql/11_roles_rls.sql:705        ALTER TABLE ... ENABLE ROW LEVEL SECURITY                 -> ERROR
sql/12_masking.sql:266          'casework.database_insights_samples'::regclass in the
                                drop-policy loop -> ERROR, sqlstate 42P01, and the loop's
                                `EXCEPTION WHEN undefined_object` handler (42704) does NOT
                                catch it. Measured both codes explicitly.
```

`sql/02_indexes.sql` and `sql/04_diagnostics.sql` are in `CORE_SQL_FILES`
(`Makefile:15-26`), so **A1's own Step 5 `make schema` fails** if they are left
alone. `sql/11` and `sql/12` are `SECURITY_SQL_FILES`, so their breakage surfaces
one target later at `make security-schema` — still this task's doing, and still
this task's job.

- Modify: `sql/10_admission.sql` — three sites, not one: the
  `casework.database_insights_samples` insert (`:824-847`), the validation block
  requiring an `evidence_type='top_wait'` / `dimension_value='lock:relation'` row
  (`:220-231`), and the `v_rows` accumulator's
  `+ jsonb_array_length(v_telemetry -> 'database_insights')` (`:889`). Leaving
  `:889` behind is not cosmetic: `jsonb_array_length(NULL)` is NULL, NULL + integer
  is NULL, and the function's returned row count silently becomes NULL for every
  admission
- Modify: `sql/01_schema.sql` — the table definition (`:480-495`) and the
  `telemetry_type` CHECK constraint's `'database_insights'` enum value (`:514`).
  **Keep** `casework.database_clusters.database_insights_mode` (`:10-11`, `:26`)
  and `casework.lock_evidence.database_insights_slice` (`:244`, `:300`): both are
  columns on tables this workshop still uses, both are nullable-or-defaulted, and
  `10_admission.sql:315`/`:341` still writes the former. Removing a column is a
  separate, wider change than removing this table, and nothing in this redesign
  requires it. Do **not** touch the legacy `DROP TABLE IF EXISTS
  casework.database_insights_samples CASCADE` at `:170` — that is a
  migration-cleanup branch for pre-existing databases and must keep dropping the
  table it is there to drop
- Modify: `sql/02_indexes.sql:42-43` — delete
  `idx_database_insights_capture_type` entirely. Verified it is named nowhere else
  in the repository
- Modify: `sql/04_diagnostics.sql` — delete the `top_wait_lock_relation` check
  (`:281-286`) and the `top_sql_contains_index_build` check (`:291-298`) from
  `casework.v_live_capture_validation`, **and** remove `top_wait_lock_relation`
  from the `live_ready` AND-chain (`:313`). `top_sql_contains_index_build` is
  computed but deliberately not in the chain today; leave that asymmetry alone by
  deleting both check expressions. Also update the `SECURITY DEFINER` rationale
  comment at `:325-330`, which cites the now-deleted masked-column predicate as
  the reason for owner rights — the function stays `SECURITY DEFINER` (`make
  doctor` and `test_retrieval_integration.py:43` call it as a persona), but the
  stated reason changes to `pg_stat_activity_samples.query` /
  `pg_stat_statements_samples.queries`, which are still masked
- Modify: `sql/11_roles_rls.sql` — delete the `ENABLE`/`FORCE ROW LEVEL
  SECURITY`, the `DROP POLICY IF EXISTS`, and the
  `rls_database_insights_samples_visibility` policy (`:705-724`). Rewrite
  section 6's header comment (`:650-702`), which is 50 lines built on this table
  as its worked example — including the measured fail-open story. That story is
  load-bearing for the next reader; re-anchor it on
  `casework.pg_stat_statements_samples`, which keeps the same capture-keyed
  mechanism, rather than deleting it
- Modify: `sql/12_masking.sql` — remove the `('mask_insights_statement',
  'casework.database_insights_samples')` tuple from the drop-policy loop (`:266`),
  the whole `mask_insights_statement` `create_masking_policy` call (`:310-328`),
  and the trailing rationale comment that explains this table's
  `predicate_allow_list` (`:396-404`)
- Modify: `backend/scripts/doctor.py:33` (`REQUIRED_TABLES`) — remove
  `casework.database_insights_samples`
- Modify: `gates/masking_determinism.py:114` (`MASKED_FOR`) — remove the same
  table. Do **not** add it to `MUST_NOT_BE_MASKED`: that list means "this table
  exists and must carry no policy," and a nonexistent table cannot satisfy it
- Modify: `gates/rls_enforcement.py:314,324` — `EVIDENCE_VISIBLE_SQL` hardcodes
  `telemetry_type = 'database_insights'`. **The brief's earlier claim that this
  gate hardcodes the table name is wrong, verified:** `_measure_by_mechanism`
  (`:800-833`) discovers `capture_tables` from the catalog via `CAPTURE_ONLY_SQL`,
  and `CAPTURE_MECHANISM_SQL` takes the list as a parameter — so the table
  disappears from this gate automatically. Only the `telemetry_type` literal is a
  real dependency. `EVIDENCE_VISIBLE_SQL` becomes dead once no evidence-row-gated
  table remains; leave the constant in place and record in the report that A1
  leaves the repo with zero `evidence_row`-mechanism tables, so
  `_measure_capture_keyed`'s `evidence_row` branch is now unexercised. Do not
  delete it — Task C2's new telemetry types may re-populate it, and that call is
  C2's, not A1's
- Modify: `backend/tests/test_rls_personas.py:549-550` — remove the two
  `casework.database_insights_samples` entries from `MASKED_COLUMNS`, and update
  the comment above it that says "ALL SIX masked columns" (it becomes four)
- Modify: `backend/tests/test_retrieval_integration.py:218-219,229,261` — the
  `database_insights` count assertion and the capture-id subquery
- Modify: `backend/app/insights.py:167-172` — `_latest_live_run` sums a
  `count(*)` over this table into `raw_telemetry_rows`. Delete that addend. This is
  **not** a documentation nicety: `_latest_live_run` backs `search_index_health()`,
  `latest_live_run()`, and `search_index_diagnostics()`, and
  `search_index_health()` is called from `backend/app/main.py:105`, `:133`, and
  `:466`. Measured against a database with the table dropped, all three raise
  `psycopg.errors.UndefinedTable: relation "casework.database_insights_samples"
  does not exist` — so omitting this leaves the app's health and readiness
  endpoints broken on exactly the schema this task produces. No test covered it,
  which is why Step 1 below adds one that scans the Python read paths as well as
  `sql/*.sql`
- Modify: `labs/incident/run_live_workshop.py:1583-1619` — `_verify_live_run`
  counts the same table as `insight_rows`. Delete the subquery, its **positional
  `capture_id` parameter**, and the `insight_rows` entry in the `zip()` key tuple.
  The parameter list is positional: dropping the subquery alone shifts every
  following bind silently. After the edit the query has 7 `%s` placeholders and 7
  arguments, down from 8 and 8. This is the one file B6 also owns; take only these
  three lines here, because the whole file is otherwise B6's, and leaving a
  guaranteed `UndefinedTable` in the verification path until B6 lands would make
  every intervening live run fail at its last step
- Test: `backend/tests/test_admission.py`

**Out of scope, deliberately, with the owning task named.** Do not widen into
these — each is another task's deliverable and touching it here creates a
merge conflict with that task:
- `labs/incident/capture_observability.py`,
  `backend/tests/test_release_capture.py` (which imports
  `_wait_for_database_insights` and will fail to import once B6 deletes it) →
  **Task B6**. `labs/incident/run_live_workshop.py` is B6's too, **except** for
  the three-line `insight_rows` deletion in `_verify_live_run` named in the Files
  block above — that one query would otherwise raise `UndefinedTable` on every
  live run between A1 and B6
- `backend/app/config.py:152`, `backend/app/search.py:726`,
  `backend/app/verify_sql.py:61`, `backend/app/main.py:487`,
  `frontend/src/WorkbenchApp.tsx:1430` (the `observability_refs` Database Insights
  hand-off) → **Task E1**
- The `admit_evidence` payload's remaining stale scale checks → **Task A2**

Because `test_release_capture.py` still imports the PI helper that B6 deletes, and
because A2 owns the payload fixtures, **the test suite is expected to be red
between A1 and A2/B6.** Report exactly which tests fail and why; do not repair
them here and do not skip them.

**Interfaces:**
- Consumes: nothing from earlier phases (Gates 1–6 are complete).
- Produces: a `casework.admit_evidence(jsonb)` payload contract with **no**
  `database_insights` key and no `database_insights_samples` writes. Later tasks
  build payloads against this contract.

**Migration and compatibility implications:** dropping a table is irreversible on
a database that already holds admitted evidence. `dat410_live` is deliberately
**not** migrated (see the `security-module-deleted-then-recommitted` decision) —
this change lands on a fresh schema apply only. `sql/01_schema.sql` is applied by
`make schema` in `CORE_SQL_FILES` order, so the table must disappear from
`01_schema.sql` in the same commit as the insert disappears from
`10_admission.sql`; a half-applied pair leaves `admit_evidence` referencing a
missing relation and every admission fails at runtime, not at apply time.
`gates/masking_determinism.py` names the table in a Python constant, so a
schema-only change turns G-29 red. Every file in the Files block moves in one
commit; a partial application is what produces the four measured apply-time
errors.

- [ ] **Step 1: Write the failing test.** Add to `backend/tests/test_admission.py`:

```python
    def test_no_sql_file_references_the_deleted_insights_table(self) -> None:
        """Every applied SQL file, not just the two that define the table.

        sql/02_indexes.sql, sql/04_diagnostics.sql, sql/11_roles_rls.sql and
        sql/12_masking.sql each CREATE or ALTER an object that references this
        table, and a missing relation is a hard apply-time ERROR in all four --
        `IF NOT EXISTS` and `OR REPLACE` guard the object being created, never
        the relation it references. Measured on PostgreSQL 17.10. A test naming
        only 01 and 10 passes while `make schema` fails.
        """
        for name in sorted(p.name for p in (REPO_ROOT / "sql").glob("*.sql")):
            sql = (REPO_ROOT / "sql" / name).read_text(encoding="utf-8")
            if name == "01_schema.sql":
                # The legacy migration-cleanup branch must keep dropping it.
                sql = sql.replace(
                    "DROP TABLE IF EXISTS casework.database_insights_samples CASCADE;",
                    "",
                )
            with self.subTest(sql_file=name):
                self.assertNotIn("database_insights_samples", sql)

    def test_admission_payload_has_no_database_insights_key(self) -> None:
        """The payload key and the telemetry_type enum value are both gone.

        Scoped to the two things this task removes rather than to the substring:
        `database_insights_mode` and `database_insights_slice` are retained
        columns on tables the workshop still uses, and a bare
        assertNotIn("database_insights", ...) would demand their removal too.
        """
        admission_sql = (REPO_ROOT / "sql" / "10_admission.sql").read_text(encoding="utf-8")
        schema_sql = (REPO_ROOT / "sql" / "01_schema.sql").read_text(encoding="utf-8")
        self.assertNotIn("-> 'database_insights'", admission_sql)
        self.assertNotIn("'database_insights',", schema_sql)
        self.assertIn("database_insights_mode", admission_sql)

    def test_no_python_read_path_references_the_deleted_insights_table(self) -> None:
        """The SQL-only test above is not sufficient, measured.

        `backend/app/insights.py` sums a count over this table into
        `raw_telemetry_rows`, and `labs/incident/run_live_workshop.py` counts it
        as `insight_rows`. Neither is a SQL file, so the per-file test above
        stays green while `search_index_health()` -- called from three
        `main.py` endpoints -- raises `UndefinedTable` on the very schema this
        task produces.
        """
        for relative_dir in ("backend/app", "labs/incident"):
            for path in sorted((REPO_ROOT / relative_dir).rglob("*.py")):
                source = path.read_text(encoding="utf-8")
                with self.subTest(source_file=str(path.relative_to(REPO_ROOT))):
                    self.assertNotIn("database_insights_samples", source)
```

- [ ] **Step 2: Run it and confirm it fails.**

```bash
.venv/bin/python -m pytest backend/tests/test_admission.py -k insights -v
```

Expected: all three new tests FAIL. The per-SQL-file test must report **six**
failing subtests — `01_schema.sql`, `02_indexes.sql`, `04_diagnostics.sql`,
`10_admission.sql`, `11_roles_rls.sql`, `12_masking.sql`. Measured reference
counts at this commit: 1, 1, 3, 1, 11, 4. The Python read-path test must report
**two** failing subtests: `backend/app/insights.py` and
`labs/incident/run_live_workshop.py`. If only two SQL subtests fail, you are
running a stale checkout — stop and check `git status`.

- [ ] **Step 3: Delete the surface.** Work the Files block above top to bottom;
  it names every site with a line number and states what to keep. Two rules while
  you do it:

  **Do not delete by pattern.** Run `grep -n database_insights <file>` per file
  and read each hit. The same substring covers three unrelated things: the table
  being deleted, the `telemetry_type` enum value being deleted, and the two
  retained columns (`database_insights_mode`, `database_insights_slice`) that must
  survive. A blanket `sed` removes the retained columns and breaks
  `10_admission.sql:315`'s `INSERT INTO casework.database_clusters`.

  **Rewrite the comments you invalidate; do not orphan them.** Three of these
  files carry long measured rationale anchored on this table —
  `sql/11_roles_rls.sql:650-702` (section 6's fail-open story),
  `sql/12_masking.sql:396-404` (the `predicate_allow_list` finding), and
  `sql/04_diagnostics.sql:325-330` (the `SECURITY DEFINER` reason). Each documents
  a real measurement that still applies to `pg_stat_statements_samples` or
  `pg_stat_activity_samples`. Re-anchor them on the surviving table. A comment
  explaining a policy on a table that no longer exists is worse than no comment,
  and deleting the measurement loses knowledge that cost an instance crash to
  acquire.

- [ ] **Step 4: Run the test again plus the whole admission suite.**

```bash
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
ALLOW_TEST_DATABASE_RESET=1 \
.venv/bin/python -m pytest backend/tests/test_admission.py -v
```

Expected: PASS on both new tests. Some pre-existing admission tests will fail here
because the payload fixtures still carry `database_insights` — that is Task A2's
job; note the failures and do not paper over them.

Then run the two other suites this task edits, plus the one it knowingly breaks:

```bash
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
WORKBENCH_SECURITY_ENABLED=1 \
.venv/bin/python -m pytest backend/tests/test_rls_personas.py \
  backend/tests/test_retrieval_integration.py backend/tests/test_release_capture.py -v
```

`test_release_capture.py` fails at **import** (`from ... import
_wait_for_database_insights`) once Task B6 deletes that helper — but B6 has not run
yet, so at A1 it should still import and pass. If it fails here, something in this
task reached into `labs/incident/`, which is out of scope. Report the exact
failure list with a one-line cause each.

- [ ] **Step 5: Live-Aurora acceptance criteria.** Apply the schema to the
  disposable database and confirm the table is gone and `admit_evidence` still
  compiles:

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python -c "
from backend.app.db import get_owner_conn
with get_owner_conn() as conn:
    name = conn.execute('SELECT current_database()').fetchone()[0]
    assert name.endswith('_test'), f'SAFETY ABORT: {name}'
    print('database:', name)
"
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" make schema
psql -X -v ON_ERROR_STOP=1 \
  "postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" <<'SQL'
DO $guard$ BEGIN
  IF current_database() <> 'dat410_review_remediation_test' THEN
    RAISE EXCEPTION 'SAFETY ABORT: connected to %', current_database();
  END IF;
END $guard$;
SELECT to_regclass('casework.database_insights_samples') IS NULL AS table_gone,
       (SELECT count(*) FROM pg_proc WHERE proname = 'admit_evidence') AS admit_fns,
       (SELECT count(*) FROM pg_class
         WHERE relname = 'idx_database_insights_capture_type') AS stale_index,
       to_regclass('casework.v_live_capture_validation') IS NOT NULL AS validation_view,
       (SELECT count(*) FROM pg_policies
         WHERE policyname = 'rls_database_insights_samples_visibility') AS stale_policy;
SQL
```

Expected: `table_gone = t`, `admit_fns = 1`, `stale_index = 0`,
`validation_view = t`, `stale_policy = 0`.

`make schema` applying cleanly is the load-bearing assertion here, not the row it
prints. `make schema` runs `sql/02_indexes.sql` and `sql/04_diagnostics.sql`; both
reference the dropped table at HEAD, and both were measured to raise a hard
`ERROR: relation ... does not exist`. If this step's `make schema` succeeds, those
two files were edited correctly. If it fails, read the error — it names the file
and the statement.

- [ ] **Step 5a: Apply the security module too.** `sql/11` and `sql/12` are not in
  `CORE_SQL_FILES`, so Step 5 does not exercise them, and both were measured to
  fail on the missing table. `sql/12`'s failure is the subtle one: its drop-policy
  loop casts the table name to `regclass` inside a `BEGIN ... EXCEPTION WHEN
  undefined_object` block, and a missing table raises **42P01
  (`undefined_table`)**, not 42704 (`undefined_object`) — measured both codes. The
  handler does not catch it and the whole `DO` block aborts.

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  make security-schema
```

Expected: applies cleanly. Then confirm the two gates that name the table are
green rather than merely quiet:

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
WORKBENCH_SECURITY_ENABLED=1 \
  .venv/bin/python gates/masking_determinism.py
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
WORKBENCH_SECURITY_ENABLED=1 \
  .venv/bin/python gates/rls_enforcement.py
```

G-29 must report **four** masked columns across **two** tables, not six across
three. A G-29 that still says six means `MASKED_FOR` was not edited and the gate
is asserting a policy on a table that no longer exists. Record both gates' exact
summary lines in the report.

- [ ] **Step 6: Cleanup and failure recovery.** `make schema` is idempotent and
  drops/recreates; if step 5 fails partway, re-run `make schema` against the same
  `_test` database — there is no partial state to hand-unwind. If the apply fails
  because a dependent object still references the dropped table, the error names
  it: fix that reference rather than re-adding the table.

- [ ] **Step 7: Participant-facing changes.** None in this task. Performance
  Insights disappears from participant-facing content in Phase F (Infrastructure)
  and the sibling Workshop Studio repo, not here.

- [ ] **Step 8: Commit.**

```bash
git add sql/01_schema.sql sql/02_indexes.sql sql/04_diagnostics.sql \
  sql/10_admission.sql sql/11_roles_rls.sql sql/12_masking.sql \
  backend/scripts/doctor.py gates/masking_determinism.py gates/rls_enforcement.py \
  backend/tests/test_admission.py backend/tests/test_rls_personas.py \
  backend/tests/test_retrieval_integration.py \
  backend/app/insights.py labs/incident/run_live_workshop.py
git commit -m "Remove the Performance Insights admission surface"
```

One commit. The `git add` list names fourteen paths; the commit will contain
thirteen if `gates/rls_enforcement.py` needs no edit (it names the table only in
comments, and its table list is catalog-discovered — see the Files block). Adding
an unmodified path is a harmless no-op; do not treat a thirteen-file commit as a
missed file. Splitting the SQL files across commits leaves an
intermediate commit where `make schema` fails, which the pre-push hook and
`make doctor` both surface later at a point where the cause is no longer obvious.
Do not pass `--no-verify`: this repo routes `core.hooksPath` to git-defender, a
bypass is logged as "Pre-commit hook bypass detected" and owes a written
justification, and the scan is fast.

**Dependencies:** none beyond Gates 1–6 being complete.

### Task A2: Re-derive the admission capture contract for the four-phase incident

**Owning schema/module:** `casework`; `sql/10_admission.sql` only.

**Files:**
- Modify: `sql/10_admission.sql` — the hardcoded scale checks
  (`observation_count <> 30`, `writer_count <> 6`, `reader_count <> 2` at
  `:134-136`), the telemetry floors (`pg_stat_activity < 270`, `pg_locks < 270`,
  `pg_blocking_pids < 180`), the "30 distinct observation numbers per series"
  checks, the two array-length bounds inside the same `OR` chain
  (`pg_stat_statements ... )) <> 3` at `:214-216` and
  `cloudwatch_metrics ... )) <> 5` at `:217-219` — **these two checks only, not the
  `INSERT`s at `:764` and `:789` that persist the same arrays**), the
  `100 OR > 120` telemetry-document bound, the "exactly 30 each of
  `activity_window` / `lock_topology` / `blocking_chain`" checks, **and the silent
  ACL default at `:418`** (`coalesce(v_record -> 'acl', '{"visibility":"workshop"}'::jsonb)`)
- Modify: `backend/scripts/doctor.py:383-389` — the `104 <= total <= 124`,
  `100 <= telemetry <= 120`, `changes != 2`, `incidents != 1`, `locks != 1`
  bounds
- Test: `backend/tests/test_admission.py`

**Interfaces:**
- Consumes: Task A1's payload contract (no `database_insights` key).
- Produces: the exact payload shape the Phase B orchestrator must emit —
  `request_count = 12`, `blocked_writer_count = 10`, `reader_count = 0`, four named
  phases, behavior-derived document counts rather than fixed ones, and a **required,
  explicit four-key `acl` object on every record** (`visibility`,
  `classifier_version`, `classification_reason`, `classification_sources`). Phase B's
  payload builder and Task C2's admission wiring are written against this and
  nothing else.

**The ACL becomes explicit and required, replacing a silent default.** Line 418 today
reads `coalesce(v_record -> 'acl', '{"visibility":"workshop"}'::jsonb)`. That
`coalesce` is a classification decision made by the database on behalf of a producer
that forgot to make one, and it fails in the most expensive direction: a whole corpus
comes out unrestricted, no error is raised anywhere, and the only downstream signal is
an optional-security gate that the default sweep does not run. Two things change here,
and they are independent:

1. **The `acl` object is required** — a record without one is a rejection, not a
   `workshop` row.
2. **The classification must be replayable** — per the Global Constraints
   replayability rule, `classifier_version`, `classification_reason`, and
   `classification_sources` are required alongside `visibility`, and a `restricted`
   label with an empty `classification_sources` array is rejected because nothing can
   re-derive it.

`visibility` is constrained to exactly `workshop` or `restricted`. Do not accept a
third value "for future use": `retrieval.acl_visible` and
`retrieval.acl_scalars_visible` both compute
`coalesce(... , 'restricted') = 'workshop'` (`sql/03_search_functions.sql:13,34`), so
any unrecognized value silently reads as restricted and the row vanishes from every
retrieval arm with no error. Reject it at admission, where the message can name the
offending value.

**This is the admission boundary's job, not the builder's.** Task C1's classifier is
what produces the values and Task C2 is what sends them, but neither can protect
against a *future* producer — an exercise script, a replay harness, a sibling repo's
tooling — that writes a bundle by hand. `admit_evidence` is the single write boundary
(`sql/11_roles_rls.sql:398` grants `workshop_participant` execute on it and nothing
else in `casework`), so it is the only place the requirement holds for every producer
that will ever exist.

**The payload carries two distinct counts, and collapsing them is a defect.**
`request_count` is how many hot-write requests were launched
(`LAB_HOT_WRITE_REQUEST_COUNT`, 12); `blocked_writer_count` is how many obtained a
connection and blocked in PostgreSQL (`DB_POOL_MAX_SIZE`, 10). The old single
`writer_count` field cannot express the incident: it has no way to say that some
requests never reached the database at all, which is the entire pool-exhaustion
signal. The admission contract asserts `request_count > blocked_writer_count`
because a run where they are equal produced no queue and therefore no pool
exhaustion.

**Migration and compatibility implications:** these are `RAISE`-guarded checks
inside a `SECURITY DEFINER` function, so a mismatch fails the participant's run
at admission time with a specific message — loud, not silent. The counts are the
one place the old mechanism's shape is welded into the database; every stale
number left behind becomes a guaranteed live failure. The bounds must be
**derived from the new mechanism's actual behavior**, not guessed: exactly
`DB_POOL_MAX_SIZE` (10) writers can block because that is how many connections
exist, the driver deliberately launches more (12) so that some queue, and the
document counts come from Phase C's real generator. So this task sets *structural*
assertions (every phase present, every signal type present, blocked writers equal
the pool max, requests exceed blocked writers) and defers *count* assertions to
Task C4, which recalibrates them against a real run. Do not invent a replacement
magic number here.

- [ ] **Step 1: Write the failing test.**

**The stale-contract strings must be copied out of the file, not paraphrased, and
they must not over-match.** Two traps, both measured against `sql/10_admission.sql`
at the commit this task starts from:

1. **A paraphrase makes the assertion vacuous.** The file does not contain
   `observation_count <> 30`; it contains
   `(v_capture ->> 'observation_count')::integer <> 30` (`:134-136`), and the
   CloudWatch check is `jsonb_array_length(coalesce(\n v_telemetry -> 'cloudwatch_metrics', '[]'::jsonb\n )) <> 5` split across lines (`:217-219`), so
   `cloudwatch_metrics <> 5` never matches either. `assertNotIn` on a string that is
   already absent passes before you change anything and passes forever after — it is a
   test that cannot fail. Verify each string with
   `grep -F "<string>" sql/10_admission.sql` and confirm it matches **now**, before
   writing the assertion. A stale-contract assertion that does not match today is a
   defect in the test, not a pass.
2. **A bare substring over-matches and would delete live code.**
   `pg_stat_statements` appears four times in the file: the scale bound at `:214-216`
   (in scope for deletion) and the `INSERT INTO casework.pg_stat_statements_samples`
   block plus its row accumulator at `:764`, `:787`, `:854` (**not** in scope). That
   table survives — `sql/11_roles_rls.sql:701-716` FORCEs RLS on it,
   `sql/12_masking.sql:328-330` masks its `queries` column,
   `gates/masking_determinism.py:114` reads it, and the design retargets the
   statement-delta signal onto it rather than deleting it. Banning the bare substring
   would force the implementer to delete the only writer of a still-RLS'd,
   still-masked, still-gated table, making those policies vacuous. Assert on the
   comparison, never on the table or payload key name.

Both count checks are inside a multi-line `OR` chain, so anchor the assertion on the
one-line fragment that is unique to the check:

```python
    def test_admission_contract_matches_the_four_phase_mechanism(self) -> None:
        sql = (REPO_ROOT / "sql" / "10_admission.sql").read_text(encoding="utf-8")
        for stale in (
            "(v_capture ->> 'observation_count')::integer <> 30",
            "(v_capture ->> 'writer_count')::integer <> 6",
            "(v_capture ->> 'reader_count')::integer <> 2",
            "v_telemetry -> 'pg_stat_statements', '[]'::jsonb\n     )) <> 3",
            "v_telemetry -> 'cloudwatch_metrics', '[]'::jsonb\n     )) <> 5",
        ):
            self.assertNotIn(stale, sql, f"stale contract still present: {stale}")
        self.assertIn("v_blocked_writer_count <> 10", sql)
        self.assertIn("v_request_count <= v_blocked_writer_count", sql)
        for phase in ("backfill", "pool_exhaustion", "recovery", "plan_regression"):
            self.assertIn(phase, sql)

    def test_admission_does_not_collapse_requests_into_blocked_writers(self) -> None:
        """A single writer_count field cannot express pool exhaustion: it has no
        way to say some requests never reached the database. Both counts must
        survive into the contract.
        """
        sql = (REPO_ROOT / "sql" / "10_admission.sql").read_text(encoding="utf-8")
        self.assertNotIn("v_writer_count", sql)
        self.assertIn("v_request_count", sql)
        self.assertIn("v_blocked_writer_count", sql)

    def test_admission_never_defaults_a_missing_acl(self) -> None:
        """A silent default is a classification the database invented for a
        producer that made none, and it fails unrestricted: the whole corpus comes
        out 'workshop' with no error on any surface the default gate sweep runs.
        """
        sql = (REPO_ROOT / "sql" / "10_admission.sql").read_text(encoding="utf-8")
        self.assertNotIn("""coalesce(v_record -> 'acl'""", sql)
        self.assertIn("v_record -> 'acl' IS NULL", sql)
```

  These three are static file assertions and run without a database. The next four
  exercise the live function and belong in the existing DSN-gated admission class
  (`AdmissionTests`, the one with `setUp` applying the schema), because a rejection
  message is only worth asserting on the engine that raises it:

```python
    def test_record_without_an_acl_is_rejected(self) -> None:
        payload = self._payload_copy()
        del payload["records"]["lock_evidence"]["acl"]
        with self.assertRaises(psycopg.errors.RaiseException) as caught:
            self._admit(payload)
        self.assertIn("acl", str(caught.exception))
        self.assertEqual(
            self.connection.execute(
                "SELECT count(*) FROM casework.evidence_items"
            ).fetchone()[0],
            0,
            "a rejected bundle must leave zero rows",
        )

    def test_unknown_visibility_value_is_rejected(self) -> None:
        """retrieval.acl_visible computes coalesce(..., 'restricted') = 'workshop',
        so an unrecognized value reads as restricted and the row silently vanishes
        from every retrieval arm. Reject it where the message can name it.
        """
        payload = self._payload_copy()
        payload["records"]["lock_evidence"]["acl"]["visibility"] = "internal"
        with self.assertRaises(psycopg.errors.RaiseException) as caught:
            self._admit(payload)
        self.assertIn("internal", str(caught.exception))

    def test_record_missing_classification_provenance_is_rejected(self) -> None:
        for absent in (
            "classifier_version",
            "classification_reason",
            "classification_sources",
        ):
            with self.subTest(absent=absent):
                payload = self._payload_copy()
                del payload["records"]["lock_evidence"]["acl"][absent]
                with self.assertRaises(psycopg.errors.RaiseException) as caught:
                    self._admit(payload)
                self.assertIn(absent, str(caught.exception))

    def test_restricted_without_sources_is_rejected(self) -> None:
        payload = self._payload_copy()
        acl = payload["records"]["lock_evidence"]["acl"]
        acl["visibility"] = "restricted"
        acl["classification_reason"] = "statement_text_present"
        acl["classification_sources"] = []
        with self.assertRaises(psycopg.errors.RaiseException) as caught:
            self._admit(payload)
        self.assertIn("classification_sources", str(caught.exception))
```

- [ ] **Step 2: Run it and confirm it fails.**

```bash
.venv/bin/python -m pytest backend/tests/test_admission.py -k "four_phase_mechanism or never_defaults_a_missing_acl" -v
```

Expected: both FAIL — `stale contract still present: observation_count <> 30` and
`'coalesce(v_record -> \'acl\'' unexpectedly found in ...`. The four live tests
require `TEST_DATABASE_URL` and a payload whose records already carry the four-key
`acl` object; until Task C2 produces one they will error on the `_payload_copy()`
fixture rather than fail on the assertion. Run them at Step 5 against the real
payload, not here — and say so in the report rather than deleting them to get a
clean run.

- [ ] **Step 3: Rewrite the contract.** In `sql/10_admission.sql`, replace the
  scale block with structural checks. The writer count is pinned to the pool max
  (a real contract, not a magic number); readers are gone because the new
  mechanism has no reader sessions; the phase set is closed.

  **First declare and assign the five values, because none of them exists yet.**
  Today's scale block reads the capture object inline
  (`(v_capture ->> 'observation_count')::integer <> 30`, `sql/10_admission.sql:134-136`)
  and the function's `DECLARE` block has no `v_writer_count`, `v_reader_count`, or
  anything like them (verified by grep). The checks below name variables, so add them
  to the `DECLARE` block alongside `v_capture` and its siblings, assigned from the
  capture object the same way the existing declarations are:

```sql
  v_request_count integer := (v_capture ->> 'request_count')::integer;
  v_blocked_writer_count integer := (v_capture ->> 'blocked_writer_count')::integer;
  v_reader_count integer := (v_capture ->> 'reader_count')::integer;
  v_phases jsonb := v_capture -> 'phases';
  v_signal_types jsonb := v_capture -> 'signal_types';
```

  A non-integer in one of the three count fields raises `invalid_text_representation`
  from the `DECLARE` block, before any check runs, with a message that does not name
  the field. Guard the three of them first so the failure is legible, then run the
  structural checks:

```sql
  IF v_request_count IS NULL
     OR v_blocked_writer_count IS NULL
     OR v_reader_count IS NULL
     OR jsonb_typeof(v_phases) IS DISTINCT FROM 'array'
     OR jsonb_typeof(v_signal_types) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION
      'admission rejected: capture must carry integer request_count, '
      'blocked_writer_count, and reader_count plus phases and signal_types arrays'
      USING ERRCODE = '22023';
  END IF;

  IF v_blocked_writer_count <> 10 THEN
    RAISE EXCEPTION
      'admission rejected: blocked_writer_count must equal DB_POOL_MAX_SIZE (10), got %',
      v_blocked_writer_count
      USING ERRCODE = '22023';
  END IF;

  IF v_request_count <= v_blocked_writer_count THEN
    RAISE EXCEPTION
      'admission rejected: request_count (%) must exceed blocked_writer_count (%); '
      'a run where every request obtained a connection produced no wait queue and '
      'therefore no pool exhaustion',
      v_request_count, v_blocked_writer_count
      USING ERRCODE = '22023';
  END IF;

  IF v_reader_count <> 0 THEN
    RAISE EXCEPTION
      'admission rejected: the four-phase mechanism has no reader sessions, got %',
      v_reader_count
      USING ERRCODE = '22023';
  END IF;

  IF NOT (
    v_phases @> '["backfill","pool_exhaustion","recovery","plan_regression"]'::jsonb
  ) THEN
    RAISE EXCEPTION
      'admission rejected: missing incident phases, got %', v_phases
      USING ERRCODE = '22023';
  END IF;
```

  Every one of the function's 19 `RAISE EXCEPTION` statements sets an explicit
  `ERRCODE` — 17 use `'22023'` (`invalid_parameter_value`) for contract violations and
  two use `'23505'` for external-key collisions (`:374`, `:391`) — so the new checks
  must set one too. Contract violations take `'22023'`. The SQLSTATE is what
  distinguishes a contract rejection from an internal error; omitting it on the new
  checks alone would leave them raising the default `P0001` in a function where
  nothing else does.

  Delete three more bounds outright: the `pg_stat_statements` array-length check
  (`sql/10_admission.sql:214-216`), the `cloudwatch_metrics` array-length check
  (`:217-219`), and the `100 OR > 120` telemetry-document bound. CloudWatch is
  best-effort per Global Constraints and cannot be a hard admission floor, and the
  document bound is recalibrated in Task C4.

  **Delete the two array-length checks only — not the code that persists those
  arrays.** `v_telemetry -> 'pg_stat_statements'` and
  `v_telemetry -> 'cloudwatch_metrics'` are each read three times: once in the scale
  block you are deleting (`:215`, `:218`), once in an `INSERT` that persists the
  samples (`INSERT INTO casework.pg_stat_statements_samples` at `:764`, feeding from
  `:787`; `INSERT INTO casework.cloudwatch_metric_samples` at `:789`), and once in the
  `v_rows` accumulator (`:854-855`). Only the first read is in scope. Those inserts
  stay.
  `casework.pg_stat_statements_samples` in particular is load-bearing for the optional
  security module — `sql/11_roles_rls.sql:701-716` FORCEs row-level security on it,
  `sql/12_masking.sql:328-330` masks its `queries` column, and
  `gates/masking_determinism.py:114` reads it — and Task C1's classifier reads its
  `queries` column to derive `acl.visibility`. Deleting its only writer would leave an
  empty table with policies that pass because there is nothing to filter, and would
  silently starve the classifier. Removing a floor on how much telemetry a run must
  produce is not the same as removing the telemetry.

  Replace the "exactly 30 each of `activity_window` / `lock_topology` /
  `blocking_chain`" checks with a presence-per-signal-type check:

```sql
  IF NOT (v_signal_types @> '["lock","pool","request","wal","meta","plan"]'::jsonb) THEN
    RAISE EXCEPTION
      'admission rejected: every signal type must be represented, got %',
      v_signal_types;
  END IF;
```

  In `backend/scripts/doctor.py:383-389`, replace the fixed bounds with the same
  structural shape: assert at least one document per signal type and at least one
  document per phase, and drop the `changes != 2` / `incidents != 1` /
  `locks != 1` equalities. **Do not add a persona, RLS, or masking check to
  `doctor.py`** — it is persona-free today (verified by grep) and it runs on the
  default participant path, where the optional module does not exist.

- [ ] **Step 3a: Make the ACL explicit and required.** This edit is inside the
  `FOR v_kind, v_record IN ... LOOP` body that starts at `sql/10_admission.sql:337`,
  in the existing required-field validation block at `:353-362` — the same block that
  already rejects a missing `external_key`, `title`, `occurred_at`, or `structured`.
  Put the ACL checks there rather than in a new block: one rejection site for
  malformed records means one place to read, and the surrounding transaction
  guarantees zero rows on any raise:

```sql
    IF v_record -> 'acl' IS NULL THEN
      RAISE EXCEPTION
        'admission rejected: % record % carries no acl; visibility must be '
        'classified by the producer, never defaulted here',
        v_kind, v_external_key
        USING ERRCODE = '22023';
    END IF;

    v_acl := v_record -> 'acl';
    IF v_acl ->> 'visibility' NOT IN ('workshop', 'restricted') THEN
      RAISE EXCEPTION
        'admission rejected: % record % has acl.visibility %; the only values are '
        'workshop and restricted, and any other value reads as restricted in '
        'retrieval.acl_visible and silently removes the row from every arm',
        v_kind, v_external_key, coalesce(v_acl ->> 'visibility', '<null>')
        USING ERRCODE = '22023';
    END IF;

    IF v_acl ->> 'classifier_version' IS NULL
       OR v_acl ->> 'classification_reason' IS NULL
       OR jsonb_typeof(v_acl -> 'classification_sources') IS DISTINCT FROM 'array' THEN
      RAISE EXCEPTION
        'admission rejected: % record % is missing acl classification provenance; '
        'classifier_version, classification_reason, and a classification_sources '
        'array are all required so the label can be replayed',
        v_kind, v_external_key
        USING ERRCODE = '22023';
    END IF;

    IF v_acl ->> 'visibility' = 'restricted'
       AND jsonb_array_length(v_acl -> 'classification_sources') = 0 THEN
      RAISE EXCEPTION
        'admission rejected: % record % is restricted with an empty '
        'classification_sources array; a label nothing can re-derive is '
        'indistinguishable from a hand-written one',
        v_kind, v_external_key
        USING ERRCODE = '22023';
    END IF;
```

  Declare `v_acl jsonb;` alongside the function's other loop locals. Then replace
  line 418's `coalesce(v_record -> 'acl', '{"visibility":"workshop"}'::jsonb)` in the
  `INSERT INTO casework.evidence_items` column list with the bare `v_acl`.

  Two things this step must **not** do:
  - **Do not change `casework.evidence_items.acl`'s column default**
    (`sql/01_schema.sql:44`, `DEFAULT '{"visibility":"workshop"}'::jsonb`). That
    default serves inserts that name no `acl` column at all —
    `backend/tests/test_admission.py:419`'s collision fixture is one — and this task
    owns the admission contract, not the table's shape. The requirement belongs at
    the write boundary every producer must pass through.
  - **Do not reject the retired `acl.principals` key if a payload still carries it.**
    `sql/01_schema.sql:91-101` normalizes the one legacy stamp
    (`principals ? 'support-lead'`) into `visibility='restricted'` on every schema
    apply. Rejecting it would make that migration unreachable; ignoring it is
    correct, because `visibility` is the single classification axis now.

- [ ] **Step 4: Run the test plus the admission suite.**

```bash
.venv/bin/python -m pytest backend/tests/test_admission.py -v
```

Expected: PASS on the three static tests. The four ACL rejection tests need
`TEST_DATABASE_URL` plus a payload carrying the four-key `acl` object and will skip
or error until Task C2 emits one — report which, and do not weaken them to get green.

**Ordering consequence to record, not to fix here.** Between this task and Task C2
the repository is in a deliberately inconsistent state: `admit_evidence` requires the
four-key `acl` object, and `labs/incident/run_live_workshop.py:927` still emits only
`{"visibility": _measured_visibility(structured)}`. A live `make live-workshop` run in
that window is rejected at admission with the provenance message. That is the correct
failure — loud, specific, and naming the missing keys — and it is strictly better than
the alternative ordering, where C2 emits provenance that nothing validates. Two things
follow: do **not** add a compatibility shim that accepts a `visibility`-only ACL, and
do state the window explicitly in the commit message so whoever bisects a failing live
run in it knows why.

- [ ] **Step 5: Live-Aurora acceptance criteria.** Apply and confirm the function
  rejects an old-shaped payload with the *new* message (proving the new contract
  is live, not just present in the file):

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" make schema
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python -c "
import json, psycopg
from psycopg.types.json import Jsonb
from backend.app.config import get_settings
dsn = get_settings().database_url
with psycopg.connect(dsn, autocommit=True) as conn:
    name = conn.execute('SELECT current_database()').fetchone()[0]
    assert name.endswith('_test'), f'SAFETY ABORT: {name}'
    payload = json.loads(open('/tmp/old_shaped_payload.json').read())
    try:
        conn.execute('SELECT casework.admit_evidence(%s::jsonb)', (Jsonb(payload),))
    except psycopg.errors.RaiseException as exc:
        print('rejected as expected:', exc)
    else:
        raise SystemExit('FAILED: old-shaped payload was accepted')
"
```

Expected: the printed rejection names `blocked_writer_count must equal
DB_POOL_MAX_SIZE (10)`. Build `/tmp/old_shaped_payload.json` by dumping the
payload the current orchestrator emits (`--output-dir` receipt) before Phase B
changes it; delete the file afterward.

  **That first check does not prove the ACL contract, so prove it separately.** The
  capture-level scale block runs before the `FOR v_kind, v_record IN ... LOOP` at
  `sql/10_admission.sql:337`, so an old-shaped payload is rejected on
  `blocked_writer_count` and never reaches step 3a's validation — a passing step-5
  run says nothing about the ACL. Take the same payload, patch the capture object so
  it satisfies step 3, and strip the `acl` from the one record that reaches the loop
  first. The records live under `payload['records']`, which is an **object** with the
  keys `incident`, `changes` (an array), `lock_evidence`, and `telemetry_documents`
  (an array) — read from `payload #> '{records,incident}'` and siblings in the
  `DECLARE` block (`:44-48`) — and the loop's `UNION ALL` puts `incident` first:

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python -c "
import json, psycopg
from psycopg.types.json import Jsonb
from backend.app.config import get_settings
dsn = get_settings().database_url
with psycopg.connect(dsn, autocommit=True) as conn:
    name = conn.execute('SELECT current_database()').fetchone()[0]
    assert name.endswith('_test'), f'SAFETY ABORT: {name}'
    payload = json.loads(open('/tmp/old_shaped_payload.json').read())
    capture = payload['capture']
    capture['request_count'] = 12
    capture['blocked_writer_count'] = 10
    capture['reader_count'] = 0
    capture['phases'] = ['backfill', 'pool_exhaustion', 'recovery', 'plan_regression']
    capture['signal_types'] = ['lock', 'pool', 'request', 'wal', 'meta', 'plan']
    payload['records']['incident'].pop('acl', None)
    try:
        conn.execute('SELECT casework.admit_evidence(%s::jsonb)', (Jsonb(payload),))
    except psycopg.errors.RaiseException as exc:
        print('rejected as expected:', exc)
    else:
        raise SystemExit('FAILED: a record with no acl was accepted')
"
```

  Expected: the rejection names the incident record and says its visibility must be
  classified by the producer and never defaulted here. If it instead names
  `blocked_writer_count`, a phase, or a signal type, the capture patch above did not
  cover every check step 3 added — read the message, extend the patch, and re-run. If
  it names a *different* missing field (`source_uri`, `occurred_at`), the dumped
  payload predates more than the ACL change; regenerate it rather than hand-editing
  further. Two independent rejections, one per contract, are the acceptance bar. One
  rejection cannot prove both, because the checks are ordered and the first one wins.

- [ ] **Step 6: Cleanup and failure recovery.** `admit_evidence` already wraps
  every insert in one transaction with an advisory lock and a receipt lookup, so
  a rejected payload leaves zero rows — Gate-style verification is a row count,
  not a manual unwind. Confirm after a rejection:

```bash
psql -X -v ON_ERROR_STOP=1 \
  "postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  -c "SELECT count(*) AS receipts FROM casework.ingest_receipts;"
```

  This one needs no `DO $guard$` block: it is a read with no write to guard.

Expected: unchanged from before the rejection. Remove
`/tmp/old_shaped_payload.json` when done.

- [ ] **Step 7: Participant-facing changes.** None directly, but the rejection
  messages are participant-visible when a run fails. They must name the specific
  violated condition and the observed value (as above) — never a bare
  "admission rejected." The ACL rejections in step 3a are held to the same standard:
  each names the record, the offending key, and why the requirement exists, because
  a participant seeing `admission rejected: acl` has been told nothing.

  The ACL requirement adds **no** participant ceremony. It constrains what the
  orchestrator emits, not anything the participant types, and it does not require
  `make security-schema`, a persona, or the optional module — the four keys are
  present on the default path because Task C1's classifier always produces them.

- [ ] **Step 8: Commit.**

```bash
git add sql/10_admission.sql backend/scripts/doctor.py backend/tests/test_admission.py
git commit -m "Re-derive the admission capture contract for four phases"
```

**Dependencies:** Task A1 (the `database_insights` key must already be gone from
the contract, or this task's structural checks fight the old validation block).

**Downstream consequences of the explicit-ACL requirement, all four verified against
the current tree — an implementer who ignores them ships a green suite and a broken
live run:**
- **Task C2** must emit the four-key `acl` object per record (its Interfaces block
  carries the shape). This is the only producer on the participant path.
- **Task C1** must produce the values; its classifier returns all four.
- **G-25** (`gates/admission_determinism.py:97`) replays a real participant payload
  through `admit_evidence`. It is a **core** gate, so a payload captured before this
  change fails the core sweep — correctly, since that payload no longer conforms.
  G-25 reads `LIVE_CAPTURE_PAYLOAD` from the current run, so the fix is to re-capture,
  never to relax the contract.
- **`backend/tests/test_admission.py`'s live classes** load the same payload via
  `_load_live_payload()`. Same resolution: re-capture, do not weaken.

### Task A3: Add the follow-up admission contract for Wave B

**Owning schema/module:** `casework`; `sql/10_admission.sql` plus a new
`casework.incident_capture_runs` conflict path.

**Files:**
- Modify: `sql/10_admission.sql` — the identity derivation
  (`v_incident_key := 'INC-' || v_run_suffix`), the `run_suffix` cross-validation
  against the capture ID, and the `casework.incident_capture_runs` plain INSERT
- Modify: `sql/01_schema.sql` — add a `wave` column to
  `casework.incident_capture_runs` and widen the `incident_changes`
  `relationship` CHECK
- Test: `backend/tests/test_admission.py`

**Interfaces:**
- Consumes: Task A2's contract.
- Produces: `casework.admit_evidence(payload)` accepting
  `payload->>'wave'` of `'A'` or `'B'`, where wave `'B'` **attaches to an
  existing incident identity** instead of deriving a new one. Phase B's Wave B
  admission call and Phase C's index rebuild both depend on this signature.

**Migration and compatibility implications:** this is the load-bearing gap Gate 3
identified and could not close. Today `v_incident_key := 'INC-' || v_run_suffix`
means **the incident key is always derived from the capture ID, so no caller can
attach a second admission to an existing incident** — Wave B is structurally
impossible. `casework.incident_capture_runs` is a plain INSERT with no
`ON CONFLICT`, so reusing an identity raises `23505`. Both must change together.
Separately, `sql/01_schema.sql:537-542` constrains
`CHECK (relationship IN ('suspected','confirmed','ruled_out','remediated'))`,
which has no value for "Wave B validates a Wave A finding." Widen the CHECK to
include `'validates'` rather than routing through `retrieval.inferred_edges` —
`inferred_edges` has a free-text `relation` and no CHECK, so putting a
first-class, measured relationship there would misrepresent a real observation as
an inference. Adding a CHECK value is backward-compatible (existing rows still
satisfy it); the `wave` column must be `NOT NULL DEFAULT 'A'` so any existing row
remains valid.

- [ ] **Step 1: Write the failing test.**

```python
    def test_wave_b_attaches_to_an_existing_incident_identity(self) -> None:
        with self._connect() as conn:
            self._apply_schema(conn, reset=True)
            wave_a = self._payload(wave="A")
            conn.execute("SELECT casework.admit_evidence(%s::jsonb)", (Jsonb(wave_a),))
            incident_key = conn.execute(
                "SELECT external_id FROM casework.evidence_items "
                "WHERE evidence_kind = 'incident'"
            ).fetchone()[0]

            wave_b = self._payload(wave="B", incident_key=incident_key)
            conn.execute("SELECT casework.admit_evidence(%s::jsonb)", (Jsonb(wave_b),))

            incidents = conn.execute(
                "SELECT count(*) FROM casework.evidence_items WHERE evidence_kind = 'incident'"
            ).fetchone()[0]
            waves = conn.execute(
                "SELECT array_agg(wave ORDER BY wave) FROM casework.incident_capture_runs"
            ).fetchone()[0]
            validates = conn.execute(
                "SELECT count(*) FROM casework.incident_changes WHERE relationship = 'validates'"
            ).fetchone()[0]

        self.assertEqual(incidents, 1, "Wave B must not create a second incident")
        self.assertEqual(waves, ["A", "B"])
        self.assertGreaterEqual(validates, 1)
```

- [ ] **Step 2: Run it and confirm it fails.**

```bash
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
ALLOW_TEST_DATABASE_RESET=1 \
.venv/bin/python -m pytest backend/tests/test_admission.py::AdmissionTests::test_wave_b_attaches_to_an_existing_incident_identity -v
```

Expected: FAIL — either a `23505` unique violation on
`casework.incident_capture_runs`, or two incident rows because Wave B derived its
own key.

- [ ] **Step 3: Implement the follow-up contract.** In `sql/01_schema.sql`:

```sql
ALTER TABLE casework.incident_capture_runs
  ADD COLUMN wave text NOT NULL DEFAULT 'A'
  CHECK (wave IN ('A', 'B'));
```

  (Write it into the table definition directly, not as a trailing `ALTER` — this
  file is a fresh-apply schema, and `make schema` recreates it.) Widen the
  relationship CHECK at `sql/01_schema.sql:537-542`:

```sql
  CHECK (relationship IN ('suspected','confirmed','ruled_out','remediated','validates'))
```

  In `sql/10_admission.sql`, make identity derivation wave-aware:

```sql
  v_wave := coalesce(payload->>'wave', 'A');
  IF v_wave NOT IN ('A', 'B') THEN
    RAISE EXCEPTION 'admission rejected: wave must be A or B, got %', v_wave;
  END IF;

  IF v_wave = 'A' THEN
    v_incident_key := 'INC-' || v_run_suffix;
  ELSE
    v_incident_key := payload->>'incident_key';
    IF v_incident_key IS NULL THEN
      RAISE EXCEPTION
        'admission rejected: wave B must name the incident_key it attaches to';
    END IF;
    PERFORM 1 FROM casework.evidence_items
      WHERE external_id = v_incident_key AND evidence_kind = 'incident';
    IF NOT FOUND THEN
      RAISE EXCEPTION
        'admission rejected: wave B names incident % which does not exist',
        v_incident_key;
    END IF;
  END IF;
```

  and give `casework.incident_capture_runs` a wave-aware key so the second
  admission is a new row against the same incident, not a conflicting one:

```sql
  INSERT INTO casework.incident_capture_runs (
    capture_id, capture_key, run_suffix, wave, incident_key,
    steady_state_connections, observation_window_start, observation_window_end
  )
  VALUES (
    v_capture_id, v_capture_key, v_run_suffix, v_wave, v_incident_key,
    1 + v_blocked_writer_count + v_reader_count, v_window_start, v_window_end
  );
```

  `steady_state_connections` counts **connections**, so it sums the backfill plus
  the writers that actually held a pooled connection — `blocked_writer_count`, not
  `request_count`. The 2–4 queued requests held no connection and must not be
  counted here; including them would overstate the observed connection count by
  the size of the wait queue.

  Each wave carries its **own** capture ID, capture key, run suffix, observation
  window, and receipt — only `incident_key` is shared. That is what makes Wave B
  a genuinely new admission rather than an amendment.

- [ ] **Step 4: Run the test and the suite.**

```bash
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
ALLOW_TEST_DATABASE_RESET=1 \
.venv/bin/python -m pytest backend/tests/test_admission.py -v
```

Expected: PASS, all tests including the nine pre-existing ones.

- [ ] **Step 5: Live-Aurora acceptance criteria.** Against the disposable
  database, prove all four properties Gate 3 could not: (a) Wave B admits without
  a `23505`; (b) exactly one incident row exists afterward; (c) both waves have
  distinct receipts in `casework.ingest_receipts`; (d) re-admitting the identical
  Wave B payload returns `idempotent_replay: true` and adds no rows.

```bash
psql -X -v ON_ERROR_STOP=1 \
  "postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" <<'SQL'
SELECT (SELECT count(*) FROM casework.evidence_items WHERE evidence_kind='incident') AS incidents,
       (SELECT count(*) FROM casework.incident_capture_runs) AS capture_runs,
       (SELECT count(DISTINCT content_hash) FROM casework.ingest_receipts) AS receipts,
       (SELECT count(*) FROM casework.incident_changes WHERE relationship='validates') AS validates;
SQL
```

Expected: `incidents = 1`, `capture_runs = 2`, `receipts = 2`, `validates >= 1`.

- [ ] **Step 6: Cleanup and failure recovery.** If Wave B admission fails
  mid-transaction, `admit_evidence`'s existing single-transaction + advisory-lock
  structure rolls the whole wave back and leaves Wave A intact — verify by
  re-running the step 5 query and confirming `capture_runs = 1`. That partial-fail
  case is the behavior Lab 4 depends on: a failed validation admission must never
  damage the diagnostic corpus. To reset entirely, re-run `make schema` against
  the `_test` database.

- [ ] **Step 7: Participant-facing changes.** None in the database layer, but this
  task is what makes Lab 4's "validate and prove" step possible at all. The
  participant sees two receipts for one incident: a diagnostic receipt at the end
  of Lab 1 and a validation receipt at the end of Lab 4.

- [ ] **Step 8: Commit.**

```bash
git add sql/01_schema.sql sql/10_admission.sql backend/tests/test_admission.py
git commit -m "Add the Wave B follow-up admission contract"
```

**Dependencies:** Tasks A1 and A2 (the contract must already be re-derived, or
the wave branch is written against checks that are about to be deleted).

### Task A4: Extend G-25 to cover two-wave additivity, and add G-32

**Owning schema/module:** `gates/`.

**Files:**
- Modify: `gates/admission_determinism.py` — `SCHEMA_FILES`, the hardcoded
  `queued = 4 + len(payload["records"]["telemetry_documents"])`, and the
  single-receipt assertion
- Modify: `gates/live_fuzzy_retrieval.py` — resolve the Wave A identity from the
  capture named by `LIVE_CAPTURE_RUN_ID` instead of assuming the latest capture
  owns the unsafe-change key
- Create: `gates/wave_additivity.py` (G-32)
- Modify: `gates/checks.sh` — add `G-32` to `CORE_GATES`
- Test: the gates are themselves the test; run them.

**Interfaces:**
- Consumes: Task A3's wave-aware `admit_evidence`.
- Produces: `G-32` in `CORE_GATES`, runnable via `gates/checks.sh G-32`.

**Migration and compatibility implications:** G-25 hardcodes
`queued = 4 + len(payload["records"]["telemetry_documents"])`, which bakes in
"exactly 1 incident + 2 changes + 1 lock" and breaks the moment Phase C changes
document composition — derive the expected count from the payload's real shape:
`incident` and `lock_evidence` are optional objects, while `changes` and
`telemetry_documents` are arrays. G-25 also asserts exactly one
`ingest_receipts` row after an identical replay; that assertion stays correct
**per wave** but must not be read as "one receipt per incident," so scope it by
`source_uri`.

G-21 has the same single-wave assumption in a different form. After Wave B,
`ORDER BY capture_started_at DESC LIMIT 1` selects Wave B and derives a change key
that does not name Wave A's unsafe backfill. Resolve the expected capture by ID,
follow its `incident_evidence_id` to Wave A, and pass that incident as
`p_incident_id` to `retrieval.fuzzy_search`.

G-32 must obey `gates/_common.py`'s
contract exactly: exit 0/1/2, `print_header`/`finish`, DSN via
`read_env_value("DATABASE_URL")` wrapped in `redact_dsn()` before logging, and
**read-only** — `_common.py`'s docstring states database-backed gates open a
read-only session (`SELECT` / `SET LOCAL` only). G-32 therefore *observes* an
already-admitted two-wave corpus; it never admits one itself. Per the
`gate-self-reference-fail-open` hazard, G-32 must not derive its expectations
from the same schema it judges: hardcode the four phase names and six signal
types as literals in the gate, so a schema that silently loses one turns the gate
red instead of green.

- [ ] **Step 1: Write G-32 as a failing gate.** Create `gates/wave_additivity.py`:

```python
#!/usr/bin/env python3
"""G-32 - two-wave evidence additivity.

Read-only. Confirms an admitted incident carries both waves, that Wave A's
documents all remain current after Wave B, and that Wave B contributes
genuinely new validation evidence rather than restating Wave A.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import psycopg

from _common import (
    BLOCKED,
    FAIL,
    PASS,
    finish,
    main_guard,
    print_header,
    read_env_value,
    redact_dsn,
    require,
)

GATE_ID = "G-32"
TITLE = "two-wave evidence additivity"

EXPECTED_PHASES = ("backfill", "pool_exhaustion", "recovery", "plan_regression")
EXPECTED_SIGNAL_TYPES = ("lock", "pool", "request", "wal", "meta", "plan")
EXPECTED_WAVE_B_SIGNALS = ("meta", "plan")


def run() -> int:
    print_header(GATE_ID, TITLE)
    dsn = read_env_value("DATABASE_URL")
    if not dsn:
        return finish(GATE_ID, BLOCKED, "DATABASE_URL is not set")
    print(f"database: {redact_dsn(dsn)}")

    with psycopg.connect(
        dsn, options="-c default_transaction_read_only=on"
    ) as conn:
        incident = conn.execute(
            """
            SELECT incident_evidence_id
            FROM casework.incident_capture_runs
            WHERE capture_origin = 'participant_induced'
            GROUP BY incident_evidence_id
            HAVING bool_or(wave = 'A') AND bool_or(wave = 'B')
            ORDER BY max(capture_ended_at) DESC
            LIMIT 1
            """
        ).fetchone()
        if incident is None:
            waves = [
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT wave FROM casework.incident_capture_runs ORDER BY wave"
                ).fetchall()
            ]
            return finish(
                GATE_ID,
                BLOCKED,
                f"needs a completed two-wave run; found waves {waves}",
            )

        incident_id = incident[0]
        bundles = dict(
            conn.execute(
                """
                SELECT wave, source_bundle_uri
                FROM casework.incident_capture_runs
                WHERE incident_evidence_id = %s
                ORDER BY wave
                """,
                (incident_id,),
            ).fetchall()
        )
        require(
            set(bundles) == {"A", "B"},
            "the selected incident does not have exactly one capture per wave",
        )

        coverage = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                """
                SELECT
                  capture.wave,
                  count(DISTINCT item.evidence_id) AS evidence_items,
                  count(DISTINCT document.evidence_id)
                    FILTER (
                      WHERE document.is_current
                        AND document.index_state = 'ready'
                    ) AS current_documents
                FROM casework.incident_capture_runs capture
                JOIN casework.evidence_items item
                  ON item.source_uri LIKE capture.source_bundle_uri || '/%'
                 AND NOT item.is_deleted
                LEFT JOIN retrieval.documents document
                  ON document.evidence_id = item.evidence_id
                WHERE capture.incident_evidence_id = %s
                GROUP BY capture.wave
                ORDER BY capture.wave
                """,
                (incident_id,),
            ).fetchall()
        }
        for wave in ("A", "B"):
            require(wave in coverage, f"wave {wave} contributed no evidence")
            evidence_items, current_documents = coverage[wave]
            require(
                evidence_items == current_documents,
                f"wave {wave} has {evidence_items} evidence items but "
                f"{current_documents} current ready documents",
            )

        validates = conn.execute(
            """
            SELECT count(*)
            FROM casework.incident_changes relation
            JOIN casework.evidence_items change_item
              ON change_item.evidence_id = relation.change_evidence_id
            WHERE relation.incident_evidence_id = %s
              AND relation.relationship = 'validates'
              AND change_item.source_uri LIKE %s || '/%%'
            """,
            (incident_id, bundles["B"]),
        ).fetchone()[0]
        require(validates >= 1, "Wave B contributed no validates relationship")

        for phase in EXPECTED_PHASES:
            found = conn.execute(
                """
                SELECT count(*)
                FROM casework.telemetry_evidence
                WHERE incident_evidence_id = %s
                  AND structured ->> 'phase' = %s
                """,
                (incident_id, phase),
            ).fetchone()[0]
            require(found > 0, f"no evidence for phase {phase}")

        for signal in EXPECTED_SIGNAL_TYPES:
            found = conn.execute(
                """
                SELECT count(*)
                FROM casework.telemetry_evidence
                WHERE incident_evidence_id = %s
                  AND structured ->> 'signal_type' = %s
                """,
                (incident_id, signal),
            ).fetchone()[0]
            require(found > 0, f"no evidence for signal type {signal}")

        wave_b_signals = {
            row[0]
            for row in conn.execute(
                """
                SELECT DISTINCT telemetry.structured ->> 'signal_type'
                FROM casework.telemetry_evidence telemetry
                JOIN casework.incident_capture_runs capture
                  ON capture.capture_id = telemetry.capture_id
                WHERE capture.incident_evidence_id = %s
                  AND capture.wave = 'B'
                  AND telemetry.structured ->> 'signal_type' IS NOT NULL
                """,
                (incident_id,),
            ).fetchall()
        }
        missing_wave_b = sorted(set(EXPECTED_WAVE_B_SIGNALS) - wave_b_signals)
        require(
            not missing_wave_b,
            f"Wave B is missing validation signal types: {missing_wave_b}",
        )

    return finish(GATE_ID, PASS, "both waves present and fully current")


if __name__ == "__main__":
    main_guard(run)
```

- [ ] **Step 2: Run it and confirm it BLOCKS (not FAILs) on a single-wave
  database.**

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python gates/wave_additivity.py; echo "exit=$?"
```

Expected: `[BLOCKED] G-32: needs a completed two-wave run; found waves ['A']`,
`exit=2`. BLOCKED is correct here — "no two-wave run exists yet" is an honest
unbuilt-dependency state, matching G-13's and G-14's precedent, not a defect.

- [ ] **Step 3: Fix G-25's hardcoded counts.** In
  `gates/admission_determinism.py`, replace

```python
    queued = 4 + len(payload["records"]["telemetry_documents"])
```

  with a payload-derived count:

```python
    records = payload["records"]
    queued = (
        int(isinstance(records.get("incident"), dict))
        + len(records.get("changes", []))
        + int(isinstance(records.get("lock_evidence"), dict))
        + len(records.get("telemetry_documents", []))
    )
```

  and scope the receipt assertion to the wave under test:

```python
    receipts = conn.execute(
        "SELECT count(*) FROM casework.ingest_receipts WHERE source_uri = %s",
        (bundle_uri,),
    ).fetchone()[0]
    require(receipts == 1, f"expected one receipt for {bundle_uri}, found {receipts}")
```

  The rollback probe must also be wave-aware. Wave A corrupts the measured lock
  mode; Wave B, which correctly has no `lock_evidence`, corrupts its validation
  change relationship. Both branches must prove that a rejected revision leaves
  the already-admitted wave unchanged.

  Update `SCHEMA_FILES` if Task A1/A3 changed which SQL files G-25 must load.

- [ ] **Step 4: Register G-32 and run the core gates.** Add `G-32` to
  `CORE_GATES` in `gates/checks.sh`, then:

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  gates/checks.sh
```

Expected: G-11, G-13, G-14, G-17, G-21, G-23, G-25 behave as before; G-32 reports
BLOCKED until a real two-wave run exists (Phase B). Do **not** set
`FAIL_ON_BLOCKED=1` for this run — that flag exists for release verification,
and G-32 is legitimately blocked until Phase B lands.

- [ ] **Step 5: Live-Aurora acceptance criteria.** Prove G-32 can go red, not just
  green (per the `gate-self-reference-fail-open` hazard — a gate that has never
  failed has not been tested). Against the disposable database, manually demote
  one Wave A document and confirm G-32 FAILs:

```bash
psql -X -v ON_ERROR_STOP=1 \
  "postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" <<'SQL'
DO $guard$ BEGIN
  IF current_database() <> 'dat410_review_remediation_test' THEN
    RAISE EXCEPTION 'SAFETY ABORT: connected to %', current_database();
  END IF;
END $guard$;
UPDATE retrieval.documents document
SET is_current = false
WHERE document.document_version_id = (
  SELECT candidate.document_version_id
  FROM retrieval.documents candidate
  JOIN casework.evidence_items item
    ON item.evidence_id = candidate.evidence_id
  JOIN casework.incident_capture_runs capture
    ON item.source_uri LIKE capture.source_bundle_uri || '/%'
  WHERE capture.wave = 'A'
    AND candidate.is_current
  LIMIT 1
);
SQL
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python gates/wave_additivity.py; echo "exit=$?"
```

Expected: `assertion failed: wave A has ... evidence items but ... current ready
documents`, `exit=1`. Then
restore with `make schema` + a fresh run, or re-set `is_current = true` on that
row. Record the measured red-and-green pair in the gate-results document — a gate
with no proven red state is not evidence.

- [ ] **Step 6: Cleanup and failure recovery.** The deliberate demotion in step 5
  is a write against a `_test` database only; it must never be run against
  `dat410_live`. Re-assert `current_database()` before the `UPDATE` (the
  `run-sql-dsn-trap-live-drop` incident happened exactly here — `run_sql.py` reads
  `DATABASE_URL`, not `TEST_DATABASE_URL`). Restore `is_current` immediately
  afterward.

- [ ] **Step 7: Participant-facing changes.** None. Gates run in CI and
  facilitator verification, never in the participant path.

- [ ] **Step 8: Commit.**

```bash
git add gates/wave_additivity.py gates/admission_determinism.py \
  gates/live_fuzzy_retrieval.py gates/checks.sh
git commit -m "Add G-32 wave additivity and de-hardcode G-25 counts"
```

**Dependencies:** Task A3 (G-32 reads the `wave` column and the `validates`
relationship, neither of which exists before A3).

### Task A5: Add the supervised-execution proof schema

**Owning schema/module:** `proof` schema; new `sql/13_supervised_execution.sql`.

**Files:**
- Create: `sql/13_supervised_execution.sql`
- Modify: `sql/11_roles_rls.sql` — two separate edits, both required:
  the persona write-surface `GRANT` block at lines 243–257 (step 11), and two new
  `ENABLE`/`FORCE`/`CREATE POLICY` loops appended after the
  `agent_subquestions`/`agent_escalations` loop that ends at line 1058 (step 12).
  Without the second edit G-27 blocks on measured evidence, not on prediction
- Modify: `Makefile:15-26` — add `sql/13_supervised_execution.sql` to
  `CORE_SQL_FILES`. There is no `apply_schema.py` in this repository; `make
  schema` and `make security-schema` both call `backend/scripts/run_sql.py
  --files $(CORE_SQL_FILES)`, and that Make variable is the only schema-file
  list either target reads.
- Modify: `scripts/build_live_source_archive.sh:40-62` — add the new file to the
  `required` array
- Modify: `backend/tests/test_release_artifact_scripts.py:45-56` — assert the new
  file appears in the archive script, so the archive assertion cannot silently
  regress
- Modify: `backend/tests/test_admission.py` — restore
  `sql/06_receipts.sql` and `sql/13_supervised_execution.sql` after its
  disposable-database reset. Without this, the full `make test` run deletes the
  functions and tables required by the later supervised-execution tests.
- Test: `backend/tests/test_supervised_execution.py` (new)

**Interfaces:**
- Consumes: `proof.agent_runs(agent_run_id)`, `proof.retrieval_runs(run_id)`,
  `proof.answer_citations(run_id, citation_number)`, and
  `proof.validate_answer_citations(uuid)` — all already exist.
- Produces:
  - `proof.action_proposals` and `proof.action_executions` tables.
  - `proof.action_proposal_citations(proposal_id uuid, run_id uuid,
    citation_number integer, claim text)`, primary key
    `(proposal_id, citation_number)` — the join table recording which validated
    citations of the Lab 3 answer support the proposal. It carries no quote
    column: the composite foreign key `(run_id, citation_number)` references
    `proof.answer_citations(run_id, citation_number)`, so the quote and source
    URI are read through that row and `proof.validate_answer_citations()`
    already governs them. Both foreign keys are `ON DELETE CASCADE` for the
    measured reason documented at step 13 — re-answering a run deletes and
    rewrites its `proof.answer_citations` rows, and `RESTRICT` here wedges that
    path permanently. Task D2a's `persist_action_proposal()` writes it and Task
    E4's `PROPOSAL_CITATION_SQL` reads it, so it is part of this task's
    published interface, not an implementation detail of the two tables above.
  - `proof.canonical_sql_name(p_text text) RETURNS text` — IMMUTABLE. The single
    case-folding rule, used by every name-shaped field on both sides. Folds a
    string only when the WHOLE string is a bare identifier
    (`^[A-Za-z_][A-Za-z0-9_]*$`); anything else — a quoted identifier, an
    expression, a `COLLATE` clause — is preserved byte-exact after whitespace
    collapse. Task E4 and Task D2a both depend on this being one function, not a
    rule reimplemented per field.
  - `proof.canonical_index_key(p_expression text, p_direction text,
    p_nulls text, p_opclass text) RETURNS text` — IMMUTABLE.
  - `proof.index_action_fingerprint(p_action_type text, p_schema_name text,
    p_table_name text, p_index_method text, p_is_unique boolean,
    p_key_columns text[], p_included_columns text[], p_predicate text)
    RETURNS text` — IMMUTABLE.
  - `proof.observed_index_fingerprint(p_index_oid oid) RETURNS TABLE
    (fingerprint text, schema_name text, table_name text, index_name text,
    index_method text, is_unique boolean, key_columns text[],
    included_columns text[], predicate text, index_definition text)` — STABLE.
    `schema_name` and `table_name` are `quote_ident()`-rendered, so a normal
    lower-case name comes back bare (`orders`) and only a name that genuinely
    requires quoting carries quotes (`"ORDERS"`). Consumers that display these
    (Task E4) render them as-is; nothing re-quotes or re-folds them.
  - `proof.autonomy_readiness(p_proposal_id uuid) RETURNS TABLE
    (pre_execution_eligible boolean, pre_execution_reasons text[],
    post_execution_validated boolean, post_execution_reasons text[])` — STABLE.
  - `proof.attach_wave_b_receipt(p_execution_id uuid, p_capture_id uuid,
    p_ingest_id uuid) RETURNS void` — `SECURITY INVOKER`, granted to nobody, and
    both facts are deliberate (see step 3's pointer and Task D3 step 8). Task D3
    calls it on its owner connection as the final step of the Wave B path. It
    raises if the execution does not exist or already carries a receipt.
    "Granted to nobody" takes **two** statements to hold, not one: `sql/13`'s
    `REVOKE ... FROM PUBLIC`, and step 11a's targeted `REVOKE` inside `sql/11`'s
    persona loop, which undoes the blanket `GRANT EXECUTE ON ALL FUNCTIONS IN
    SCHEMA proof` that would otherwise re-grant it (measured f → t). Step 11b
    asserts the end state.
  - The `action_executions_append_only` trigger on `proof.action_executions`.
    Task D3 and Task E4 both depend on its guarantee rather than on a privilege
    check: no code path anywhere, owner included, can change a recorded
    `outcome`, `fingerprint_matches`, `observed_fingerprint`,
    `observed_index_definition`, `executed_sql*`, `approved_by`, `approved_at`,
    or either key. A `DELETE` is still possible for the owner; that is stated in
    D3 step 8 and left open on purpose so A5 step 16's cleanup works.

**Migration and compatibility implications:** this task adds tables and functions
and changes nothing that exists, so it is additive on a live database. Two rules
from the design spec's Supervised Execution Model are load-bearing here and the
reviewer must check them against the SQL rather than the prose:

1. **The canonical fingerprint is the equality test; raw SQL hashes are audit
   only.** `proposed_sql_sha256` and `executed_sql_sha256` are stored and never
   compared to decide whether the participant executed the proposed action.
2. **`post_execution_validated` must never feed `pre_execution_eligible`.** The
   two verdicts are computed from disjoint inputs in one function, and the
   pre-execution branch reads no column of `proof.action_executions`.

**The SQL below was prototyped and measured against a real PostgreSQL 17 server
before being written into this plan.** Four defects were found and fixed during
that prototype; all four are already corrected in the code here, and each is
called out in a comment so nobody "simplifies" them back:
- Joining key columns with a comma let two different key lists serialize
  identically (`['a,b','c']` vs `['a','b,c']`). Serialization is `jsonb`.
- `indisunique` was missing, so a `UNIQUE` index and a plain index on the same
  column produced one fingerprint.
- Folding every identifier to lower case would merge two genuinely different
  quoted columns. Quoted identifiers stay byte-exact; unquoted ones fold. (The
  prototype's fix for this was itself wrong — see the fold-rule paragraph below.)
- Appending a bare string literal to a `text[]` in PL/pgSQL raises `malformed
  array literal` — every literal append needs an explicit `::text`.

Measured behavior of the prototype, to be re-confirmed by this task's tests:
`(priority_tier, created_at DESC)` spelled with different casing, spacing, and
line breaks produced one fingerprint while the two raw SQL hashes differed; the
reversed key order produced a different fingerprint.

**A fifth defect was found later, by review, and it changed the schema.** The
earlier draft of this plan claimed "four spellings of the same partial-index
predicate all collapsed to one fingerprint because `pg_get_expr` normalizes them
in the catalog." That measurement was real but it tested the wrong comparison:
it compared four *observed* indexes against each other, all four of which pass
through `pg_get_expr`. It never compared the observed side against the
*proposal* side, which does not. Re-measured on PostgreSQL 17.10, proposal
predicate `status = 'open'` against the identical executed index gives catalog
text `(status = 'open'::text)` and two different fingerprints — a false mismatch
that tells a correct participant they executed the wrong action. Partial-index
predicates are therefore rejected by a `CHECK (predicate IS NULL)` in
`proof.action_proposals` and by a `ValueError` in Task D2a's parser. With the
predicate NULL, the plain Lab 4 index, an `INCLUDE` index, and a `UNIQUE` index
were each verified to produce identical proposal-side and catalog-side
fingerprints. The lesson generalizes: **when two derivations must agree, measure
them against each other, not each against itself.**

**Four more defects were found by the same review, all in the case-folding rule,
and three of them reproduced on PostgreSQL 17.10.** The prototype's third fix
above — "quoted identifiers stay byte-exact; unquoted ones fold" — was the right
principle implemented by the wrong test. It asked *does this string contain a
double quote* when the question is *is this whole string a bare identifier*, and
it was applied to key expressions only while schema, table, and INCLUDE columns
got a bare `lower(btrim(...))`. Measured consequences:

1. **False match on a different table, the most serious of the four.** With
   `lower(btrim(relname))` on the observed side, an index built on
   `workbench_lab."ORDERS"` fingerprinted *identically* to the proposal for
   `workbench_lab.orders`. The workshop would report a clean match for an action
   performed against the wrong relation. Fixed by `quote_ident()` on the observed
   side plus `proof.canonical_sql_name()` on both.
2. **False mismatch on INCLUDE columns.** They were sorted but never folded, so a
   proposal naming `Created_At` never matched the catalog's `created_at`. Fixed by
   canonicalizing before sorting, and sorting on the canonical form.
3. **False match on expression indexes.** `LIKE '%"%'` never fires on a
   single-quoted literal, so `regexp_replace(note,'A','B')` and
   `regexp_replace(note,'a','b')` — different indexes — folded to one
   fingerprint. Fixed by the whole-string identifier test, which refuses to fold
   any expression at all.
4. **False mismatch on `COLLATE`, not fixed, and honestly so.** `name COLLATE
   "C"` contains a double quote, so the old rule preserved the entire expression
   including the column name and `NAME COLLATE "C"` never matched. The new rule
   also declines to fold it, because folding an expression is what caused defect
   3. This one is unreachable: Task D2a's parser accepts only bare identifiers as
   key columns, so no `COLLATE` clause can reach a proposal. An honest
   limitation on an unreachable input beats a fold rule that produces false
   matches on reachable ones.

The fix is one function, `proof.canonical_sql_name()`, called by every
name-shaped field on both sides. Defects 1–3 each have a test that was **proven
red against the pre-fix definitions and green against the fixed ones**, not merely
observed green once.

- [ ] **Step 1: Write the failing test.** Create
  `backend/tests/test_supervised_execution.py`:

```python
"""Supervised-execution schema tests.

Every interesting property here is a negative one: the fingerprint must NOT
change across formatting variance, must NOT match on reversed key order, and a
successful execution must NOT make an ineligible proposal eligible.
"""
from __future__ import annotations

import os
import unittest

import psycopg

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

CANON = (
    "SELECT proof.canonical_index_key(%s, %s, NULL, NULL)"
)
FINGERPRINT = (
    "SELECT proof.index_action_fingerprint("
    "'create_index', 'workbench_lab', 'orders', 'btree', false, %s, '{}', NULL)"
)


@unittest.skipUnless(TEST_DATABASE_URL, "requires TEST_DATABASE_URL")
class FingerprintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.conn = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
        name = cls.conn.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY ABORT: refusing to run against {name}")
        # The fingerprint tests need real indexes to read back out of the catalog,
        # and they build them in their own throwaway schema rather than touching
        # workbench_lab -- an index created here on the real lab table would change
        # the plan Lab 4 is supposed to measure.
        cls.conn.execute("DROP SCHEMA IF EXISTS fp_check CASCADE")
        cls.conn.execute("CREATE SCHEMA fp_check")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.execute("DROP SCHEMA IF EXISTS fp_check CASCADE")
        cls.conn.close()

    def _fingerprint(self, keys: list[tuple[str, str]]) -> str:
        canonical = [
            self.conn.execute(CANON, (expression, direction)).fetchone()[0]
            for expression, direction in keys
        ]
        return self.conn.execute(FINGERPRINT, (canonical,)).fetchone()[0]

    def test_formatting_variance_produces_one_fingerprint(self) -> None:
        plain = self._fingerprint([("priority_tier", "asc"), ("created_at", "desc")])
        noisy = self._fingerprint(
            [("  PRIORITY_TIER ", "ASC"), ("created_at\n", "DESC")]
        )
        self.assertEqual(
            plain, noisy,
            "casing and whitespace must not change the canonical fingerprint",
        )

    def test_reversed_key_order_produces_a_different_fingerprint(self) -> None:
        forward = self._fingerprint([("priority_tier", "asc"), ("created_at", "desc")])
        reversed_ = self._fingerprint([("created_at", "desc"), ("priority_tier", "asc")])
        self.assertNotEqual(
            forward, reversed_,
            "key column order is semantically load-bearing and must change the "
            "fingerprint",
        )

    def test_comma_in_a_key_expression_cannot_forge_a_collision(self) -> None:
        left = self.conn.execute(FINGERPRINT, (["a,b", "c"],)).fetchone()[0]
        right = self.conn.execute(FINGERPRINT, (["a", "b,c"],)).fetchone()[0]
        self.assertNotEqual(
            left, right,
            "a comma inside a key expression must not collapse two different "
            "key lists into one fingerprint",
        )

    def test_no_key_columns_is_rejected(self) -> None:
        with self.assertRaises(psycopg.errors.RaiseException):
            self.conn.execute(FINGERPRINT, ([],)).fetchone()

    def test_proposal_and_catalog_fingerprints_agree(self) -> None:
        """The two derivations must agree for an identical action.

        This is the test whose absence hid a real defect. The earlier draft
        compared observed indexes only against other observed indexes, which
        cannot detect a proposal-side/observation-side disagreement because both
        sides of that comparison pass through pg_get_expr(). Compare ACROSS the
        two derivations or the assertion is vacuous.
        """
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS fp_check.orders ("
            "  order_id bigint, status text, priority_tier text,"
            "  created_at timestamptz)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fp_check_probe"
            "  ON fp_check.orders (priority_tier, created_at DESC)"
        )
        row = self.conn.execute(
            """
            WITH proposed AS (
              SELECT proof.index_action_fingerprint(
                'create_index', 'fp_check', 'orders', 'btree', false,
                ARRAY[
                  proof.canonical_index_key('priority_tier', 'asc', NULL, NULL),
                  proof.canonical_index_key('created_at', 'desc', NULL, NULL)
                ],
                '{}'::text[], NULL) AS fp
            ), observed AS (
              SELECT f.fingerprint AS fp
              FROM pg_class c
              CROSS JOIN proof.observed_index_fingerprint(c.oid) f
              WHERE c.relname = 'idx_fp_check_probe'
            )
            SELECT p.fp, o.fp FROM proposed p CROSS JOIN observed o
            """
        ).fetchone()
        self.assertEqual(
            row[0], row[1],
            "the proposal-side and catalog-side fingerprints must agree for an "
            "identical action; a mismatch tells a correct participant they "
            "executed the wrong thing",
        )

    def test_a_partial_index_predicate_is_rejected(self) -> None:
        """The unfingerprintable case must be unrepresentable, not merely unused.

        Measured on PostgreSQL 17.10: proposed `status = 'open'` reads back from
        the catalog as `(status = 'open'::text)`, so the fingerprints disagree for
        an identical index. The CHECK is what keeps that row from existing.
        """
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.conn.execute(
                "INSERT INTO proof.action_proposals ("
                "  agent_run_id, run_id, action_type, target_schema,"
                "  target_table, key_columns, predicate, proposed_fingerprint,"
                "  proposed_sql, proposed_sql_sha256, preconditions,"
                "  expected_effect, rollback_guidance, statement_timeout,"
                "  lock_timeout)"
                " VALUES (NULL, NULL, 'create_index', 'workbench_lab',"
                "  'orders', ARRAY['created_at asc nulls_last default'],"
                "  'status = ''open''', 'x', 'y', 'z', '[]'::jsonb, 'e', 'r',"
                "  '5s', '5s')"
            )

    def test_a_quoted_relation_does_not_match_the_lower_case_one(self) -> None:
        """A different table must never fingerprint as the proposed one.

        MEASURED FALSE MATCH this guards (PostgreSQL 17.10, 2026-08-04): with
        `lower(btrim(relname))` on the observed side, an index built on
        fp_check."ORDERS" produced the SAME fingerprint as the proposal for
        fp_check.orders. The workshop would report a match for an action taken
        against a different table. quote_ident() on the observed side plus
        proof.canonical_sql_name()'s whole-string test is the fix; this test is
        what keeps either half from being simplified away.
        """
        self.conn.execute(
            'CREATE TABLE IF NOT EXISTS fp_check."ORDERS" ('
            "  priority_tier text, created_at timestamptz)"
        )
        self.conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_fp_check_quoted'
            '  ON fp_check."ORDERS" (priority_tier, created_at DESC)'
        )
        row = self.conn.execute(
            """
            SELECT proof.index_action_fingerprint(
                     'create_index', 'fp_check', 'orders', 'btree', false,
                     ARRAY[
                       proof.canonical_index_key('priority_tier','asc',NULL,NULL),
                       proof.canonical_index_key('created_at','desc',NULL,NULL)
                     ], '{}'::text[], NULL),
                   (SELECT f.fingerprint
                      FROM pg_class c
                      CROSS JOIN proof.observed_index_fingerprint(c.oid) f
                     WHERE c.relname = 'idx_fp_check_quoted')
            """
        ).fetchone()
        self.assertNotEqual(
            row[0], row[1],
            'an index on fp_check."ORDERS" must not fingerprint as the proposal '
            "for fp_check.orders; those are different tables",
        )

    def test_include_columns_match_across_casing(self) -> None:
        """INCLUDE columns must fold the same way key columns do.

        MEASURED FALSE MISMATCH this guards: the earlier draft sorted the INCLUDE
        array but never folded it, so a proposal naming `Created_At` produced a
        different fingerprint from the catalog's `created_at` for the identical
        index. Two columns, not one, because a single-element list also passes if
        the sort key and the stored value are folded inconsistently.
        """
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS fp_check.payload ("
            "  priority_tier text, created_at timestamptz, amount numeric)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fp_check_include"
            "  ON fp_check.payload (priority_tier) INCLUDE (created_at, amount)"
        )
        row = self.conn.execute(
            """
            SELECT proof.index_action_fingerprint(
                     'create_index', 'fp_check', 'payload', 'btree', false,
                     ARRAY[proof.canonical_index_key('priority_tier','asc',NULL,NULL)],
                     ARRAY['Created_At', 'AMOUNT'], NULL),
                   (SELECT f.fingerprint
                      FROM pg_class c
                      CROSS JOIN proof.observed_index_fingerprint(c.oid) f
                     WHERE c.relname = 'idx_fp_check_include')
            """
        ).fetchone()
        self.assertEqual(
            row[0], row[1],
            "mixed-case INCLUDE columns must canonicalize to the catalog's form",
        )

    def test_a_string_literal_in_an_expression_is_not_case_folded(self) -> None:
        """Two expression indexes differing only in a literal are different.

        MEASURED FALSE MATCH this guards: the earlier fold rule tested for a
        double quote anywhere in the string, which never fires on a single-quoted
        literal, so regexp_replace(note,'A','B') and regexp_replace(note,'a','b')
        -- different indexes -- collapsed to one fingerprint.
        """
        upper = self.conn.execute(
            CANON, ("regexp_replace(note,'A','B')", "asc")
        ).fetchone()[0]
        lower = self.conn.execute(
            CANON, ("regexp_replace(note,'a','b')", "asc")
        ).fetchone()[0]
        self.assertNotEqual(
            upper, lower,
            "a case-different string literal is a different index and must not "
            "share a canonical form",
        )

    def test_whitespace_in_a_string_literal_is_not_collapsed(self) -> None:
        """Whitespace inside a literal is data, not SQL formatting."""
        two_spaces = self.conn.execute(
            "SELECT proof.canonical_sql_name(%s)",
            ("regexp_replace(note,'A  B','X')",),
        ).fetchone()[0]
        one_space = self.conn.execute(
            "SELECT proof.canonical_sql_name(%s)",
            ("regexp_replace(note,'A B','X')",),
        ).fetchone()[0]
        self.assertNotEqual(two_spaces, one_space)
```

- [ ] **Step 2: Run it and confirm every test fails on a missing function.**

```bash
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python -m pytest backend/tests/test_supervised_execution.py -v
```

Expected: ten failures, each reporting `function proof.canonical_index_key(...)
does not exist`, `function proof.index_action_fingerprint(...) does not exist`,
or `relation "proof.action_proposals" does not exist`.

**Five of these ten tests were exercised against the pre-fix code rather than
merely observed green against the fixed code** (PostgreSQL 17.10 on 2026-08-04,
plus PostgreSQL 18.4 during the A5 review):
`test_a_quoted_relation_does_not_match_the_lower_case_one`,
`test_include_columns_match_across_casing`, and
`test_a_string_literal_in_an_expression_is_not_case_folded` all fail with the
earlier `lower(btrim(...))` / `LIKE '%"%'` rules. The PostgreSQL 18.4 review
also proved `test_whitespace_in_a_string_literal_is_not_collapsed` red against
the whitespace-collapsing draft. All four pass with
`proof.canonical_sql_name` plus `quote_ident`.
`test_proposal_and_catalog_fingerprints_agree` passes both ways — it is the
regression guard for the primary Lab 4 case, kept because it is the comparison
whose absence hid the predicate defect in the first place.

**`test_a_partial_index_predicate_is_rejected` writes its INSERT with NULL
`agent_run_id`/`run_id` on purpose.** It is asserting a CHECK, not a foreign key,
and a CHECK is evaluated before the FKs; if those columns are `NOT NULL` in the
final DDL, adjust the test to insert real ids rather than weakening the CHECK.
Confirm the failure is `CheckViolation` and not `NotNullViolation` — the latter
means the test passed for the wrong reason and proves nothing about the predicate.

- [ ] **Step 3: Create the two tables.** Create
  `sql/13_supervised_execution.sql` and write the table definitions first:

```sql
-- Supervised execution (design spec, "Supervised Execution Model").
--
-- The agent never executes anything. It writes a structured, cited PROPOSAL;
-- the participant approves and executes it themselves in Code Editor; the
-- execution is recorded here with the index definition read back FROM THE
-- CATALOG, not from the participant's typed text. That read-back is what makes
-- the proposed-vs-executed comparison evidence rather than assertion.
--
-- These tables are an audit trail written ABOUT the agent's output. They are
-- not an agent capability: nothing here is reachable from agent/registry.py,
-- and no task in this plan may make it so.

CREATE TABLE IF NOT EXISTS proof.action_proposals (
  proposal_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_run_id uuid NOT NULL
    REFERENCES proof.agent_runs(agent_run_id) ON DELETE RESTRICT,
  run_id uuid NOT NULL
    REFERENCES proof.retrieval_runs(run_id) ON DELETE RESTRICT,
  -- Allowlist, enforced by the database rather than by the prompt. Widening
  -- this CHECK is a schema change and a review conversation, which is exactly
  -- the friction it is here to create.
  action_type text NOT NULL CHECK (action_type IN ('create_index')),
  target_schema text NOT NULL,
  target_table text NOT NULL,
  index_method text NOT NULL DEFAULT 'btree',
  is_unique boolean NOT NULL DEFAULT false,
  -- Ordered. (priority_tier, created_at DESC) is not the same action as
  -- (created_at DESC, priority_tier), so this is an array and never a set.
  key_columns text[] NOT NULL CHECK (array_length(key_columns, 1) >= 1),
  included_columns text[] NOT NULL DEFAULT '{}',
  -- MEASURED DEFECT, fixed by this CHECK: a partial-index predicate cannot be
  -- fingerprinted consistently, so a non-NULL predicate is rejected outright.
  --
  -- The proposal side stores the predicate as the agent wrote it; the catalog
  -- side reads it back through pg_get_expr(), which REWRITES it. Measured on
  -- PostgreSQL 17.10: proposed `status = 'open'` against the identical executed
  -- index yields catalog text `(status = 'open'::text)`, two different
  -- fingerprints, and `fingerprint_matches = false` for a participant who did
  -- exactly what was asked. That is the worst failure this design can have --
  -- the workshop calling a correct participant wrong -- and it is not fixable by
  -- normalizing strings on the proposal side, because matching pg_get_expr's
  -- output means reimplementing the PostgreSQL expression printer.
  --
  -- The honest fix is to make the unfingerprintable case unrepresentable. Lab 4
  -- proposes a plain composite b-tree index and needs no predicate. Verified on
  -- PostgreSQL 17.10 with predicate NULL: the plain Lab 4 index, an INCLUDE
  -- index, and a UNIQUE index each produced identical proposal-side and
  -- catalog-side fingerprints.
  --
  -- If partial indexes are ever wanted, the correct route is to canonicalize the
  -- proposal side THROUGH the server -- have the proposal store the predicate as
  -- rendered by pg_get_expr() for a trial expression -- and only then relax this
  -- CHECK. Do not relax it and hope.
  predicate text CHECK (predicate IS NULL),
  -- The authoritative equality test. Computed by
  -- proof.index_action_fingerprint() from the structured fields above.
  proposed_fingerprint text NOT NULL,
  -- Audit only. NEVER compared to decide whether the participant executed the
  -- proposed action: whitespace, quoting, and equivalent PostgreSQL syntax make
  -- raw-hash equality brittle, and a participant who typed the recommended
  -- index with different spacing would be wrongly told they executed something
  -- else.
  proposed_sql text NOT NULL,
  proposed_sql_sha256 text NOT NULL,
  preconditions jsonb NOT NULL DEFAULT '[]'::jsonb
    -- Measured on a real server: without this CHECK, storing an OBJECT here
    -- (`'{"satisfied": true}'::jsonb` — a plausible writer bug) makes
    -- proof.autonomy_readiness() raise `cannot get array length of a non-array`
    -- at its jsonb_array_length call instead of returning a verdict. The
    -- proposal is then unjudgeable rather than ineligible, which is the one
    -- outcome this module must never produce. The empty ARRAY stays storable:
    -- with the CHECK in place, `'[]'` inserts and the verdict reports
    -- `no preconditions were recorded`.
    CHECK (jsonb_typeof(preconditions) = 'array'),
  expected_effect text NOT NULL,
  rollback_sql text,
  rollback_guidance text,
  statement_timeout text,
  lock_timeout text,
  created_at timestamptz NOT NULL DEFAULT now(),
  -- One proposal per agent run. A run that produced two conflicting
  -- recommendations is a defect to surface, not a history to accumulate.
  UNIQUE (agent_run_id),
  -- Referenced by proof.action_executions' composite foreign key below.
  -- Redundant with the primary key by design: PostgreSQL requires a UNIQUE
  -- constraint on exactly the referenced column pair, and the primary key alone
  -- does not satisfy a two-column reference.
  UNIQUE (proposal_id, run_id)
  -- Deliberately NO constraint requiring rollback guidance, bounded timeouts,
  -- or satisfied preconditions. An incomplete proposal must be STORABLE so
  -- proof.autonomy_readiness() can report WHY it is ineligible. Rejecting it
  -- at insert time would make the ineligible case unobservable, and the
  -- ineligible case is the teaching point of this whole module.
);

CREATE TABLE IF NOT EXISTS proof.action_proposal_citations (
  -- COMPOSITE, not a bare proposal_id reference, and this is a measured fix.
  -- An earlier draft referenced proof.action_proposals(proposal_id) alone and
  -- left run_id tied only to proof.answer_citations below. Nothing then required
  -- the link's run_id to equal the PROPOSAL's run_id, and measured on
  -- PostgreSQL 17.10, 2026-08-04: a link naming proposal C (of run A) with
  -- run_id = B inserted cleanly (`same_run = f`). Requirement 6 then evaluates
  -- the link against proof.validate_answer_citations(PROPOSAL.run_id) while the
  -- link's own FK was satisfied against run B, so the two sides validate
  -- different rows. Measured verdict for a proposal whose supporting link points
  -- at another run's INVALID citation: `PASSES requirement 6`. With this
  -- composite reference the same INSERT is refused with
  -- `foreign_key_violation`. This is what proof.action_proposals'
  -- UNIQUE (proposal_id, run_id) is for -- it is referenced twice, from here and
  -- from proof.action_executions.
  proposal_id uuid NOT NULL,
  run_id uuid NOT NULL,
  citation_number integer NOT NULL,
  claim text NOT NULL,
  PRIMARY KEY (proposal_id, citation_number),
  FOREIGN KEY (proposal_id, run_id)
    REFERENCES proof.action_proposals(proposal_id, run_id) ON DELETE CASCADE,
  -- The proposal's supporting citations are the SAME rows the answer cited, so
  -- proof.validate_answer_citations() already governs them. A separate quote
  -- column here could drift from the chunk text it claims to quote.
  --
  -- ON DELETE CASCADE, and this is a correction of a measured defect, not a
  -- preference. `backend/app/agent.py:737` runs
  -- `DELETE FROM proof.answer_citations WHERE run_id = %s` on EVERY call to
  -- _persist_answer(), including the second call for a run that already has an
  -- answer (the function's own INSERT is `ON CONFLICT (run_id) DO UPDATE`, so
  -- re-answering the same run is a supported path, not an error path). With
  -- RESTRICT here, the first proposal written against a run permanently
  -- wedges that run's answer: measured on a real server, the re-persist
  -- failed with `update or delete on table "answer_citations" violates
  -- foreign key constraint
  -- "action_proposal_citations_run_id_citation_number_fkey" on table
  -- "action_proposal_citations"`. With CASCADE, the same DELETE succeeded, the
  -- stale link count went 1 -> 0, and the proposal row itself survived
  -- (`proposal row still present: 1`) for Task D2a to relink inside the same
  -- transaction. Note what CASCADE does NOT weaken: it deletes the LINK when
  -- the cited answer citation is replaced, never the proposal. A proposal whose
  -- links are gone reports `the proposal cites no evidence` and is ineligible,
  -- which is the correct verdict for a proposal whose supporting answer was
  -- rewritten.
  FOREIGN KEY (run_id, citation_number)
    REFERENCES proof.answer_citations(run_id, citation_number) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS proof.action_executions (
  execution_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  proposal_id uuid NOT NULL
    REFERENCES proof.action_proposals(proposal_id) ON DELETE RESTRICT,
  -- Denormalized from the proposal so the RLS policy in step 12 can chain this
  -- row's owning persona through proof.retrieval_runs directly. NOT NULL is
  -- load-bearing twice over: the policy predicate needs a non-null key, and
  -- gates/rls_enforcement.py's _run_root() (line 515) RAISES RuntimeError on a
  -- run-gated table whose run key is nullable, because an inner join through a
  -- nullable key silently drops rows and understates the owner's oracle. The
  -- composite foreign key at the bottom of this table makes the denormalization
  -- safe: a run_id that disagrees with the proposal's is refused by the engine.
  run_id uuid NOT NULL,
  -- The tiebreak for "which attempt is the current one". MEASURED on PostgreSQL
  -- 17.10, 2026-08-04: now() is transaction START time, so two rows inserted in
  -- one transaction carry a single identical approved_at (`distinct_timestamps=1`
  -- across 2 rows), and `ORDER BY approved_at DESC LIMIT 1` then returns whichever
  -- row the heap happens to yield first. Reclustering the same two rows returned
  -- 'failed', then 'succeeded', then 'failed' -- three different verdicts from
  -- unchanged data with no write in between. With this tiebreak all three
  -- returned 'succeeded'. An identity column is monotonic in insertion order,
  -- which is exactly the question being asked; execution_id cannot serve because
  -- gen_random_uuid() is unordered.
  recorded_seq bigint GENERATED ALWAYS AS IDENTITY,
  approved_by text NOT NULL,
  approved_at timestamptz NOT NULL DEFAULT now(),
  executed_sql text,
  executed_sql_sha256 text,
  -- Read back from pg_indexes / pg_get_indexdef AFTER the DDL ran, never
  -- parsed from executed_sql. This is the load-bearing column.
  observed_index_definition text,
  observed_fingerprint text,
  fingerprint_matches boolean,
  -- TWO values, not three. An earlier draft allowed 'abandoned' as well, and
  -- review found it unreachable: a proposal that was approved but never executed
  -- is the ABSENCE of a row in this table, which the verdict already reports as
  -- `no execution has been recorded yet`. A third value that can only ever mean
  -- what zero rows already mean is dead schema, and dead schema in a CHECK reads
  -- as a state the system can enter. It cannot.
  --
  -- 'failed' IS reachable, and only became so once step 8's ordering was
  -- corrected to record before admission: a CREATE INDEX that errored or hit its
  -- statement_timeout leaves no index, and Task D3 records that fact rather than
  -- writing nothing.
  outcome text NOT NULL
    CHECK (outcome IN ('succeeded', 'failed')),
  outcome_detail text,
  started_at timestamptz,
  completed_at timestamptz,
  plan_before_checkpoint text,
  plan_after_checkpoint text,
  wave_b_capture_id uuid
    REFERENCES casework.incident_capture_runs(capture_id) ON DELETE SET NULL,
  wave_b_ingest_id uuid
    REFERENCES casework.ingest_receipts(ingest_id) ON DELETE SET NULL,
  CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at),
  -- A succeeded execution must carry the catalog read-back and its verdict.
  -- Without this, a NULL observed_fingerprint would silently read as
  -- "unmatched" and the comparison would be unfalsifiable.
  CHECK (
    outcome <> 'succeeded'
    OR (observed_index_definition IS NOT NULL
        AND observed_fingerprint IS NOT NULL
        AND fingerprint_matches IS NOT NULL)
  ),
  -- Proven on a real server: an execution whose run_id matches its proposal is
  -- accepted, and one pointing at a different run is refused with
  -- `violates foreign key constraint
  -- "action_executions_proposal_id_run_id_fkey"`. Without this, the denormalized
  -- run_id could name a run belonging to another persona and the RLS policy would
  -- hand the row to the wrong one.
  FOREIGN KEY (proposal_id, run_id)
    REFERENCES proof.action_proposals(proposal_id, run_id) ON DELETE RESTRICT
);
```

  **Two more objects belong in this file immediately below this table, and their
  code lives in Task D3's step 8 rather than here**: `proof.attach_wave_b_receipt`
  and the `proof.action_executions_append_only` trigger that guards it. Copy both
  from D3 step 8 verbatim into `sql/13_supervised_execution.sql` at this point —
  a trigger cannot be created before its table, and `sql/13` is this task's file.
  They are written up there because D3's recording-before-admission ordering is
  what requires them, and both were measured against a full-fidelity replica of
  this table (six cases, tabulated in that step). Do not paraphrase the trigger:
  the transition-based receipt rule and the raise-rather-than-revert behaviour are
  each there because a simpler draft was measured broken. Step 9's tests below
  cover both objects.

- [ ] **Step 4: Add the canonicalizer and the fingerprint function.** Append to
  `sql/13_supervised_execution.sql`:

```sql
-- ONE case-folding rule for every name-shaped field on both sides.
--
-- MEASURED DEFECT this replaces (PostgreSQL 17.10, 2026-08-04). The earlier draft
-- inlined the rule as `CASE WHEN expr LIKE '%"%' THEN expr ELSE lower(expr) END`
-- in canonical_index_key only, and applied a bare `lower(btrim(...))` to the
-- schema, table, and INCLUDE columns. That produced four separate defects, three
-- of them measured as reproducing:
--
--   1. FALSE MATCH, the worst kind: `lower(btrim(relname))` on the observed side
--      folds a QUOTED mixed-case relation onto the lower-case one. An index built
--      on workbench_lab."ORDERS" -- a genuinely different table -- fingerprinted
--      IDENTICALLY to the proposal for workbench_lab.orders. The workshop would
--      report a match for an action performed on the wrong table.
--   2. FALSE MISMATCH: INCLUDE columns were sorted but never folded, so a
--      proposal saying `Created_At` never matched the catalog's `created_at`.
--   3. FALSE MATCH: `LIKE '%"%'` tests for a double quote ANYWHERE, so it does not
--      fire on single-quoted string literals inside an expression.
--      regexp_replace(note,'A','B') and regexp_replace(note,'a','b') -- different
--      indexes -- folded to one fingerprint.
--   4. FALSE MISMATCH: the same test fires on `name COLLATE "C"` because of the
--      quoted collation name, so the whole expression including the column name
--      stayed byte-exact and `NAME COLLATE "C"` never matched.
--
-- The rule below fixes all four by asking the right question. Not "does this
-- contain a quote" but "is this WHOLE string a bare identifier". Only a bare
-- identifier is case-insensitive in PostgreSQL, so only a bare identifier may be
-- folded. Everything else -- a quoted identifier, an expression, a COLLATE clause
-- -- is preserved byte-exact. The catalog side reaches this with quote_ident()
-- already applied (see step 6), so both derivations present names the same way.
--
-- Consequence, accepted deliberately: `NAME COLLATE "C"` still does not match
-- `name COLLATE "C"`. That is a false mismatch this rule does not fix, and
-- fixing it means parsing SQL expressions. It is unreachable for this workshop --
-- Task D2a's parser only accepts bare identifiers as key columns, so no COLLATE
-- clause can ever reach a proposal -- and a false mismatch on an unreachable
-- input is an honest limitation, not a live defect. Do not "improve" this by
-- widening the fold; widening it is what produced defects 1 and 3.
CREATE OR REPLACE FUNCTION proof.canonical_sql_name(p_text text)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE
           WHEN t.trimmed ~ '^[A-Za-z_][A-Za-z0-9_]*$' THEN lower(t.trimmed)
           ELSE t.original
         END
  FROM (
    SELECT coalesce(p_text, '') AS original,
           regexp_replace(coalesce(p_text, ''), '^\s+|\s+$', '', 'g') AS trimmed
  ) t
$$;

COMMENT ON FUNCTION proof.canonical_sql_name(text) IS
  'The one case-folding rule for name-shaped fields. Folds only a string that is '
  'entirely a bare identifier; a quoted identifier or an expression is preserved '
  'byte-exact, including whitespace inside string literals. Folding or collapsing '
  'more than this produced measured false matches.';

-- One canonicalizer, called by BOTH sides. The proposal side passes the agent's
-- structured fields; the observation side passes what it read out of the
-- catalog. If each side had its own normalizer, the comparison would be testing
-- two normalizers against each other rather than testing the action.
CREATE OR REPLACE FUNCTION proof.canonical_index_key(
  p_expression text,
  p_direction text,
  p_nulls text,
  p_opclass text
) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT concat_ws(
    ' ',
    proof.canonical_sql_name(p_expression),
    v.direction,
    -- PostgreSQL's own default: NULLS LAST for ASC, NULLS FIRST for DESC. Both
    -- sides must materialize the default identically or an explicit
    -- "DESC NULLS FIRST" would not match a bare "DESC".
    coalesce(
      nullif(lower(btrim(coalesce(p_nulls, ''))), ''),
      CASE WHEN v.direction = 'desc' THEN 'nulls_first' ELSE 'nulls_last' END
    ),
    -- An opclass name in the catalog is always a bare identifier, so folding it
    -- unconditionally is safe here in a way it is NOT for schema/table names.
    coalesce(nullif(lower(btrim(coalesce(p_opclass, ''))), ''), 'default')
  )
  FROM (
    SELECT CASE WHEN lower(btrim(coalesce(p_direction, 'asc'))) = 'desc'
                THEN 'desc' ELSE 'asc' END AS direction
  ) v
$$;

COMMENT ON FUNCTION proof.canonical_index_key(text, text, text, text) IS
  'Canonical form of one index key. Called by both the proposal side and the '
  'catalog-observation side so the comparison tests the action, not two '
  'independent normalizers.';

CREATE OR REPLACE FUNCTION proof.index_action_fingerprint(
  p_action_type text,
  p_schema_name text,
  p_table_name text,
  p_index_method text,
  p_is_unique boolean,
  p_key_columns text[],
  p_included_columns text[],
  p_predicate text
) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  v_canonical jsonb;
BEGIN
  IF p_action_type IS NULL OR p_schema_name IS NULL OR p_table_name IS NULL THEN
    RAISE EXCEPTION
      'index_action_fingerprint requires action type, schema, and table '
      '(got %, %, %)', p_action_type, p_schema_name, p_table_name;
  END IF;
  IF coalesce(array_length(p_key_columns, 1), 0) = 0 THEN
    RAISE EXCEPTION 'index_action_fingerprint requires at least one key column';
  END IF;
  -- jsonb, NOT a delimiter-joined string. A key expression may legitimately
  -- contain a comma -- lower(substr(note, 1, 5)) -- and joining on one would let
  -- ['a,b','c'] and ['a','b,c'] serialize identically. Measured during this
  -- task's prototype; do not "simplify" back to array_to_string.
  v_canonical := jsonb_build_object(
    'version', 1,
    'action_type', lower(btrim(p_action_type)),
    -- canonical_sql_name, NOT lower(btrim(...)). A bare lower() here folded a
    -- quoted mixed-case relation onto the lower-case one, and workbench_lab."ORDERS"
    -- fingerprinted identically to workbench_lab.orders -- a measured FALSE MATCH
    -- reporting success for an action taken on a different table. The observation
    -- side supplies these already quote_ident()-ed (step 6) so the two derivations
    -- agree on how a name is spelled.
    'schema', proof.canonical_sql_name(p_schema_name),
    'table', proof.canonical_sql_name(p_table_name),
    -- An access method name is always a bare identifier, so folding is safe.
    'method', lower(btrim(coalesce(p_index_method, 'btree'))),
    -- A UNIQUE index and a plain index on the same column are different
    -- actions with different semantics. Omitting this collapsed them during
    -- the prototype.
    'unique', coalesce(p_is_unique, false),
    -- Ordered: key order is semantically load-bearing.
    'keys', to_jsonb(p_key_columns),
    -- Unordered: INCLUDE columns are a payload set, so sort for stability. They
    -- are canonicalized BEFORE sorting, and sorted on the canonical form -- the
    -- earlier draft sorted the raw values and folded nothing, so a proposal
    -- naming `Created_At` never matched the catalog's `created_at`. Sorting on
    -- the raw value would also order 'Zebra' before 'apple' by byte value while
    -- the catalog side orders the folded names, reintroducing the mismatch for
    -- multi-column INCLUDE lists.
    'include', to_jsonb(coalesce(
      (SELECT array_agg(proof.canonical_sql_name(c)
                        ORDER BY proof.canonical_sql_name(c))
         FROM unnest(coalesce(p_included_columns, '{}')) AS c),
      '{}'::text[]
    )),
    'predicate', coalesce(btrim(p_predicate), '')
  );
  RETURN encode(sha256(convert_to(v_canonical::text, 'UTF8')), 'hex');
END
$$;

COMMENT ON FUNCTION proof.index_action_fingerprint(
  text, text, text, text, boolean, text[], text[], text
) IS
  'Authoritative equality test for a proposed vs executed index action. Raw SQL '
  'hashes are stored for audit but never compared: whitespace, quoting, and '
  'equivalent PostgreSQL syntax make raw-hash equality brittle.';
```

- [ ] **Step 5: Run the fingerprint tests and confirm they pass.**

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python backend/scripts/run_sql.py --files sql/13_supervised_execution.sql
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python -m pytest backend/tests/test_supervised_execution.py -v
```

Expected: all ten tests PASS. `test_no_key_columns_is_rejected` asserts the
`RAISE EXCEPTION` fires — if it fails with `psycopg.errors.InvalidTextRepresentation`
instead, the empty array reached `array_length` as NULL and the guard used
`array_length(...) = 0` rather than `coalesce(array_length(...), 0) = 0`.

- [ ] **Step 6: Add the catalog read-back function.** Append to
  `sql/13_supervised_execution.sql`:

```sql
-- Reads an index's real shape out of the catalog and fingerprints it with the
-- SAME function the proposal side used. Nothing here parses the participant's
-- typed SQL: reading the definition back from the catalog rather than trusting
-- the input is what makes the comparison evidence rather than assertion.
CREATE OR REPLACE FUNCTION proof.observed_index_fingerprint(p_index_oid oid)
RETURNS TABLE (
  fingerprint text,
  schema_name text,
  table_name text,
  index_name text,
  index_method text,
  is_unique boolean,
  key_columns text[],
  included_columns text[],
  predicate text,
  index_definition text
)
LANGUAGE sql STABLE AS $$
  WITH idx AS (
    SELECT i.indexrelid,
           i.indrelid,
           i.indnkeyatts,
           i.indnatts,
           i.indoption,
           i.indclass,
           i.indpred,
           i.indisunique,
           -- quote_ident, NOT the bare relname. pg_class stores names DECODED:
           -- relname is `ORDERS` for both "ORDERS" and (impossibly) an unquoted
           -- one, and lower()ing it collapsed workbench_lab."ORDERS" onto
           -- workbench_lab.orders -- a measured FALSE MATCH on a different table.
           -- quote_ident renders `orders` as orders and `ORDERS` as "ORDERS", which
           -- is exactly the distinction proof.canonical_sql_name preserves, and it
           -- is how pg_get_indexdef already renders the key and INCLUDE columns.
           -- Both derivations must present names in the same notation.
           quote_ident(ns.nspname) AS schema_name,
           quote_ident(tbl.relname) AS table_name,
           irel.relname AS index_name,
           am.amname AS index_method
    FROM pg_index i
    JOIN pg_class irel ON irel.oid = i.indexrelid
    JOIN pg_class tbl ON tbl.oid = i.indrelid
    JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
    JOIN pg_am am ON am.oid = irel.relam
    WHERE i.indexrelid = p_index_oid
  ),
  keys AS (
    -- The 3-argument pg_get_indexdef returns ONE column's expression, which is
    -- what makes per-key canonicalization possible; the 1-argument form returns
    -- the whole CREATE INDEX statement and would have to be re-parsed.
    -- indoption bit 0 = DESC, bit 1 = NULLS FIRST.
    SELECT k.ord,
           proof.canonical_index_key(
             pg_get_indexdef(idx.indexrelid, k.ord::int, false),
             CASE WHEN (idx.indoption[k.ord - 1] & 1) = 1 THEN 'desc' ELSE 'asc' END,
             CASE WHEN (idx.indoption[k.ord - 1] & 2) = 2
                  THEN 'nulls_first' ELSE 'nulls_last' END,
             -- A default opclass is elided so the observation side does not
             -- require the proposal side to know catalog opclass names.
             CASE WHEN opc.opcdefault THEN NULL ELSE opc.opcname END
           ) AS key_repr
    FROM idx
    CROSS JOIN generate_series(1, idx.indnkeyatts) AS k(ord)
    JOIN pg_opclass opc ON opc.oid = idx.indclass[k.ord - 1]
  ),
  included AS (
    -- Attributes past indnkeyatts are INCLUDE columns. This range is empty for
    -- an index without INCLUDE, which is the expected Lab 4 case.
    SELECT pg_get_indexdef(idx.indexrelid, k.ord::int, false) AS col
    FROM idx
    CROSS JOIN generate_series(idx.indnkeyatts + 1, idx.indnatts) AS k(ord)
  ),
  shaped AS (
    SELECT idx.schema_name,
           idx.table_name,
           idx.index_name,
           idx.index_method,
           idx.indisunique AS is_unique,
           (SELECT array_agg(key_repr ORDER BY ord) FROM keys) AS key_columns,
           coalesce((SELECT array_agg(col ORDER BY col) FROM included), '{}')
             AS included_columns,
           -- pg_get_expr normalizes the predicate in the catalog, so
           -- "where amount > 100", "where (amount>100)", and
           -- "where ((orders.amount) > 100::numeric)" all arrive identical.
           -- Measured in this task's prototype.
           pg_get_expr(idx.indpred, idx.indrelid) AS predicate,
           pg_get_indexdef(idx.indexrelid) AS index_definition
    FROM idx
  )
  SELECT proof.index_action_fingerprint(
           'create_index', schema_name, table_name, index_method,
           is_unique, key_columns, included_columns, predicate
         ),
         schema_name, table_name, index_name, index_method, is_unique,
         key_columns, included_columns, predicate, index_definition
  FROM shaped
$$;

COMMENT ON FUNCTION proof.observed_index_fingerprint(oid) IS
  'Catalog read-back: the real shape of an existing index, fingerprinted with '
  'proof.index_action_fingerprint. Never parses participant-supplied SQL.';
```

- [ ] **Step 7: Write and run the read-back test.** Append to
  `backend/tests/test_supervised_execution.py`:

```python
@unittest.skipUnless(TEST_DATABASE_URL, "requires TEST_DATABASE_URL")
class ObservedFingerprintTests(unittest.TestCase):
    """Round-trip: an index CREATEd from the proposal's fields must observe back
    to the proposal's own fingerprint."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.conn = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
        name = cls.conn.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY ABORT: refusing to run against {name}")
        cls.conn.execute("CREATE SCHEMA IF NOT EXISTS sup_exec_probe")
        cls.conn.execute(
            "CREATE TABLE IF NOT EXISTS sup_exec_probe.orders "
            "(order_id bigint, priority_tier text, created_at timestamptz)"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.execute("DROP SCHEMA IF EXISTS sup_exec_probe CASCADE")
        cls.conn.close()

    def _observe(self, index_name: str) -> str:
        return self.conn.execute(
            "SELECT f.fingerprint FROM pg_class c "
            "CROSS JOIN proof.observed_index_fingerprint(c.oid) f "
            "WHERE c.relname = %s",
            (index_name,),
        ).fetchone()[0]

    def _propose(self, keys: list[tuple[str, str]], *, unique: bool = False) -> str:
        canonical = [
            self.conn.execute(
                "SELECT proof.canonical_index_key(%s, %s, NULL, NULL)",
                (expression, direction),
            ).fetchone()[0]
            for expression, direction in keys
        ]
        return self.conn.execute(
            "SELECT proof.index_action_fingerprint("
            "'create_index', 'sup_exec_probe', 'orders', 'btree', %s, %s, '{}', NULL)",
            (unique, canonical),
        ).fetchone()[0]

    def test_proposed_and_observed_fingerprints_match(self) -> None:
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS probe_match ON sup_exec_probe.orders "
            "(priority_tier, created_at DESC)"
        )
        self.assertEqual(
            self._propose([("priority_tier", "asc"), ("created_at", "desc")]),
            self._observe("probe_match"),
            "a proposal's fingerprint must equal the fingerprint observed from "
            "the catalog after the same index is created",
        )

    def test_reversed_key_order_does_not_match_the_observed_index(self) -> None:
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS probe_order ON sup_exec_probe.orders "
            "(priority_tier, created_at DESC)"
        )
        self.assertNotEqual(
            self._propose([("created_at", "desc"), ("priority_tier", "asc")]),
            self._observe("probe_order"),
            "an index with reversed key order must not be reported as a match",
        )

    def test_unique_index_does_not_match_a_non_unique_proposal(self) -> None:
        self.conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS probe_uniq ON sup_exec_probe.orders "
            "(order_id)"
        )
        self.assertNotEqual(
            self._propose([("order_id", "asc")], unique=False),
            self._observe("probe_uniq"),
            "uniqueness is part of the action; a UNIQUE index must not match a "
            "non-unique proposal",
        )

    def test_raw_sql_hashes_differ_where_the_fingerprint_matches(self) -> None:
        """The contrast that justifies the fingerprint's existence."""
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS probe_spacing ON sup_exec_probe.orders "
            "(  PRIORITY_TIER ,\n   created_at    DESC  )"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS probe_tidy ON sup_exec_probe.orders "
            "(priority_tier, created_at DESC)"
        )
        self.assertEqual(
            self._observe("probe_spacing"),
            self._observe("probe_tidy"),
            "formatting variance must not change the canonical fingerprint",
        )
        raw_a, raw_b = (
            self.conn.execute(
                "SELECT encode(sha256(convert_to(%s, 'UTF8')), 'hex')", (text,)
            ).fetchone()[0]
            for text in (
                "CREATE INDEX i ON sup_exec_probe.orders (priority_tier, created_at DESC)",
                "create index i on sup_exec_probe.orders ( priority_tier , created_at desc )",
            )
        )
        self.assertNotEqual(
            raw_a, raw_b,
            "raw SQL hashes must differ across formatting -- this is precisely "
            "why they are audit-only and not the equality test",
        )
```

Run:

```bash
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python -m pytest backend/tests/test_supervised_execution.py -v
```

Expected: all 14 tests PASS (ten fingerprint and four catalog read-back).
`tearDownClass` drops `sup_exec_probe` — the probe schema must not survive the
run.

- [ ] **Step 8: Add the autonomy-readiness verdict.** Append to
  `sql/13_supervised_execution.sql`:

```sql
-- Computed, never narrated. The participant does not get told "this looks safe";
-- they get two booleans and, when false, the specific reasons.
--
-- THE INVARIANT: post-execution evidence NEVER feeds pre_execution_eligible.
-- The pre-execution branch below reads no column of proof.action_executions.
-- Successful post-execution evidence must not be used retroactively to claim
-- the action was safe beforehand -- this is an autonomy-READINESS assessment,
-- not autonomous execution. G-34 exists to prove that path is absent rather
-- than merely unused.
CREATE OR REPLACE FUNCTION proof.autonomy_readiness(p_proposal_id uuid)
RETURNS TABLE (
  pre_execution_eligible boolean,
  pre_execution_reasons text[],
  post_execution_validated boolean,
  post_execution_reasons text[]
)
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_proposal proof.action_proposals%ROWTYPE;
  v_exec proof.action_executions%ROWTYPE;
  v_pre text[] := '{}';
  v_post text[] := '{}';
  v_cited integer;
  v_validated integer;
BEGIN
  SELECT * INTO v_proposal
    FROM proof.action_proposals WHERE proposal_id = p_proposal_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'no action proposal %', p_proposal_id;
  END IF;

  -- Requirement 1: an allowlisted action.
  IF v_proposal.action_type <> 'create_index' THEN
    v_pre := v_pre || format('action type %L is not allowlisted',
                             v_proposal.action_type);
  END IF;

  -- Requirement 2: an approved target. Hardcoded literals, not a lookup against
  -- the schema being judged -- see the gate-self-reference-fail-open hazard.
  IF (v_proposal.target_schema, v_proposal.target_table)
     <> ('workbench_lab', 'orders') THEN
    v_pre := v_pre || format('target %I.%I is not an approved target',
                             v_proposal.target_schema, v_proposal.target_table);
  END IF;

  -- Requirement 3: preconditions recorded AND all satisfied. An empty list is
  -- its own failure: "nothing was checked" is not "everything passed".
  IF jsonb_array_length(v_proposal.preconditions) = 0 THEN
    v_pre := v_pre || 'no preconditions were recorded'::text;
  ELSIF EXISTS (
    SELECT 1
    FROM jsonb_array_elements(v_proposal.preconditions) AS p
    WHERE coalesce((p.value ->> 'satisfied')::boolean, false) IS NOT TRUE
  ) THEN
    v_pre := v_pre || 'at least one precondition is unsatisfied'::text;
  END IF;

  -- Requirement 4: bounded timeouts. Both, not either.
  IF v_proposal.statement_timeout IS NULL OR v_proposal.lock_timeout IS NULL THEN
    v_pre := v_pre
             || 'statement_timeout and lock_timeout must both be bounded'::text;
  END IF;

  -- Requirement 5: rollback guidance, in either form.
  IF btrim(coalesce(v_proposal.rollback_sql, '')) = ''
     AND btrim(coalesce(v_proposal.rollback_guidance, '')) = '' THEN
    v_pre := v_pre || 'no rollback guidance was recorded'::text;
  END IF;

  -- Requirement 6: validated citations. proof.validate_answer_citations() is the
  -- same function that governs the agent's answer, so a proposal cannot be
  -- supported by a citation the answer layer would have rejected.
  --
  -- COUNT THE VALIDATED ONES AND REQUIRE ALL OF THEM. Counting the INVALID ones
  -- and requiring zero is the same test only when every link actually reaches a
  -- validation row, and a link can fail to reach one WITHOUT being invalid. The
  -- inner join then drops it, `v_invalid` stays 0, and the proposal is called
  -- eligible on evidence that was never checked -- fail-open, in the one function
  -- whose entire purpose is to refuse.
  --
  -- MEASURED on PostgreSQL 17.10, 2026-08-04, against a probe carrying this
  -- schema's real policies. proof.validate_answer_citations (sql/06_receipts.sql:67)
  -- INNER JOINs retrieval.documents and retrieval.chunks, both ENABLE + FORCE
  -- ROW LEVEL SECURITY (sql/11_roles_rls.sql:446-449) with policies keyed on
  -- acl_visibility (lines 522-536); the API runs this function under the
  -- requesting persona, because backend/app/db.py:169 issues SET LOCAL ROLE per
  -- transaction. A restricted document therefore removes the citation's
  -- validation row for that persona while the LINK stays visible -- the link
  -- table has no evidence_id, so step 12's policy is the bare parent-run check,
  -- strictly weaker than proof.answer_citations' policy, which DOES carry the
  -- evidence-reachability clause (lines 963-979). Measured on one proposal whose
  -- citation quote does not appear in its chunk: owner
  -- `INELIGIBLE: 1 cited claims failed`, persona `PASSES requirement 6`, with
  -- `visible_links = 1` and `visible_citations = 0`. Same rows, no tampering,
  -- opposite verdicts. With the count inverted, both roles return
  -- `1 of 1 could not be validated`.
  --
  -- The reason string says "could not be validated", not "failed validation",
  -- because unreachable and invalid are different facts and this branch cannot
  -- tell them apart. Do not narrow it back to "failed".
  SELECT count(*) INTO v_cited
    FROM proof.action_proposal_citations
   WHERE proposal_id = p_proposal_id;
  SELECT count(*) INTO v_validated
    FROM proof.action_proposal_citations pc
    JOIN proof.validate_answer_citations(v_proposal.run_id) v
      ON v.citation_number = pc.citation_number
   WHERE pc.proposal_id = p_proposal_id
     AND v.is_valid;
  IF v_cited = 0 THEN
    v_pre := v_pre || 'the proposal cites no evidence'::text;
  ELSIF v_validated < v_cited THEN
    v_pre := v_pre || format('%s of %s cited claims could not be validated',
                             v_cited - v_validated, v_cited);
  END IF;

  -- Post-execution branch. Reads ONLY the execution record; contributes nothing
  -- to v_pre above.
  -- recorded_seq is the tiebreak, not decoration. Two rows recorded inside one
  -- transaction share an approved_at (now() is transaction start time), and
  -- ordering on approved_at alone would let the verdict differ between two calls
  -- with no intervening write. See the column comment in step 3.
  SELECT * INTO v_exec
    FROM proof.action_executions
   WHERE proposal_id = p_proposal_id
   ORDER BY approved_at DESC, recorded_seq DESC
   LIMIT 1;
  IF NOT FOUND THEN
    v_post := v_post || 'no execution has been recorded yet'::text;
  ELSE
    IF v_exec.outcome <> 'succeeded' THEN
      v_post := v_post || format('execution outcome was %L', v_exec.outcome);
    END IF;
    IF v_exec.fingerprint_matches IS NOT TRUE THEN
      v_post := v_post
                || 'the executed action does not match the proposed action'::text;
    END IF;
    IF v_exec.wave_b_ingest_id IS NULL THEN
      v_post := v_post
                || 'the result was not validated by an admitted Wave B capture'::text;
    END IF;
  END IF;

  -- Each literal append above carries an explicit ::text cast. Without it,
  -- PL/pgSQL resolves a bare string appended to text[] as an ARRAY LITERAL and
  -- raises "malformed array literal". Measured during this task's prototype.
  RETURN QUERY SELECT
    (array_length(v_pre, 1) IS NULL), v_pre,
    (array_length(v_post, 1) IS NULL), v_post;
END
$$;

COMMENT ON FUNCTION proof.autonomy_readiness(uuid) IS
  'Two independent verdicts. pre_execution_eligible is computed WITHOUT reading '
  'any execution record, so a successful execution can never retroactively make '
  'an ineligible proposal eligible.';
```

- [ ] **Step 9: Write the verdict tests — one eligible baseline, eight negative
  cases, the retroactive-safety test, two citation-ownership tests, and six
  covering the append-only rule and the `recorded_seq` tiebreak.** The last eight
  exist because review found five defects in this design and two more in the first
  two attempts to fix them; each test names the defect it guards. Append to
  `backend/tests/test_supervised_execution.py`:

```python
BASE_PROPOSAL = {
    "action_type": "create_index",
    "target_schema": "workbench_lab",
    "target_table": "orders",
    "key_columns": ["priority_tier asc nulls_last default"],
    "preconditions": '[{"check": "no_index_exists", "satisfied": true}]',
    "rollback_sql": "DROP INDEX workbench_lab.idx_orders_priority_created",
    "statement_timeout": "5min",
    "lock_timeout": "5s",
}

INSERT_PROPOSAL = """
INSERT INTO proof.action_proposals(
  agent_run_id, run_id, action_type, target_schema, target_table,
  key_columns, proposed_fingerprint, proposed_sql, proposed_sql_sha256,
  preconditions, expected_effect, rollback_sql, statement_timeout, lock_timeout
) VALUES (
  %(agent_run_id)s, %(run_id)s, %(action_type)s, %(target_schema)s,
  %(target_table)s, %(key_columns)s, 'fp', 'CREATE INDEX ...', 'raw-hash',
  %(preconditions)s::jsonb, 'index scan replaces the sequential scan',
  %(rollback_sql)s, %(statement_timeout)s, %(lock_timeout)s
) RETURNING proposal_id
"""


@unittest.skipUnless(TEST_DATABASE_URL, "requires TEST_DATABASE_URL")
class AutonomyReadinessTests(unittest.TestCase):
    """Every requirement removed in isolation must produce false with a NAMED
    reason. Eight independent negative cases, not one bundled check, plus the
    retroactive-safety test, two covering citation ownership and the
    validated-count polarity, and six covering the append-only rule, the receipt
    attachment, and the recorded_seq tiebreak."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.conn = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
        name = cls.conn.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY ABORT: refusing to run against {name}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def _seed_run(self) -> tuple[str, str]:
        """A real agent run and retrieval run to reference. The FK is not
        optional: a proposal that references no run is not auditable."""
        run_id = self.conn.execute(
            "INSERT INTO proof.retrieval_runs("
            "  query_text, retrieval_mode, rrf_k, text_weight, vector_weight,"
            "  fuzzy_weight) "
            "VALUES ('supervised-execution test', 'hybrid', 60, 1, 1, 1) "
            "RETURNING run_id"
        ).fetchone()[0]
        agent_run_id = self.conn.execute(
            "INSERT INTO proof.agent_runs(question, controls_initial, "
            "  contract_version) "
            "VALUES ('supervised-execution test', '{}'::jsonb, 'test') "
            "RETURNING agent_run_id"
        ).fetchone()[0]
        return str(agent_run_id), str(run_id)

    def _propose(self, **overrides) -> str:
        agent_run_id, run_id = self._seed_run()
        params = dict(BASE_PROPOSAL, agent_run_id=agent_run_id, run_id=run_id)
        params.update(overrides)
        return str(self.conn.execute(INSERT_PROPOSAL, params).fetchone()[0])

    def _verdict(self, proposal_id: str) -> tuple:
        return self.conn.execute(
            "SELECT pre_execution_eligible, pre_execution_reasons, "
            "       post_execution_validated, post_execution_reasons "
            "FROM proof.autonomy_readiness(%s)",
            (proposal_id,),
        ).fetchone()

    def _cite(self, proposal_id: str) -> None:
        """Attach a citation that proof.validate_answer_citations() accepts.
        Uses whatever real indexed evidence the database already holds."""
        row = self.conn.execute(
            "SELECT run_id FROM proof.action_proposals WHERE proposal_id = %s",
            (proposal_id,),
        ).fetchone()
        source = self.conn.execute(
            "SELECT d.evidence_id, d.document_version_id, c.chunk_version_id, "
            "       d.source_uri, d.source_revision, left(c.chunk_text, 200) "
            "FROM retrieval.documents d "
            "JOIN retrieval.chunks c "
            "  ON c.document_version_id = d.document_version_id "
            "WHERE d.is_current LIMIT 1"
        ).fetchone()
        if source is None:
            self.skipTest("needs at least one indexed document to cite")
        self.conn.execute(
            "INSERT INTO proof.answer_citations(run_id, citation_number, "
            "  evidence_id, document_version_id, chunk_version_id, source_uri, "
            "  source_revision, quote_text) "
            "VALUES (%s, 1, %s, %s, %s, %s, %s, %s)",
            (row[0], *source),
        )
        self.conn.execute(
            "INSERT INTO proof.action_proposal_citations(proposal_id, run_id, "
            "  citation_number, claim) VALUES (%s, %s, 1, 'supporting claim')",
            (proposal_id, row[0]),
        )

    def test_complete_proposal_is_eligible(self) -> None:
        proposal_id = self._propose()
        self._cite(proposal_id)
        eligible, reasons, validated, post_reasons = self._verdict(proposal_id)
        self.assertTrue(eligible, f"expected eligible, got reasons {reasons}")
        self.assertEqual(reasons, [])
        self.assertFalse(validated, "nothing has been executed yet")
        self.assertIn("no execution has been recorded yet", post_reasons)

    def test_uncited_proposal_is_ineligible(self) -> None:
        eligible, reasons, _, _ = self._verdict(self._propose())
        self.assertFalse(eligible)
        self.assertIn("the proposal cites no evidence", reasons)

    def test_unapproved_target_is_ineligible(self) -> None:
        proposal_id = self._propose(target_schema="casework")
        self._cite(proposal_id)
        eligible, reasons, _, _ = self._verdict(proposal_id)
        self.assertFalse(eligible)
        self.assertTrue(
            any("not an approved target" in reason for reason in reasons),
            f"expected an approved-target reason, got {reasons}",
        )

    def test_unsatisfied_precondition_is_ineligible(self) -> None:
        proposal_id = self._propose(
            preconditions='[{"check": "no_index_exists", "satisfied": false}]'
        )
        self._cite(proposal_id)
        eligible, reasons, _, _ = self._verdict(proposal_id)
        self.assertFalse(eligible)
        self.assertIn("at least one precondition is unsatisfied", reasons)

    def test_no_preconditions_recorded_is_ineligible(self) -> None:
        proposal_id = self._propose(preconditions="[]")
        self._cite(proposal_id)
        eligible, reasons, _, _ = self._verdict(proposal_id)
        self.assertFalse(eligible, "nothing checked is not everything passed")
        self.assertIn("no preconditions were recorded", reasons)

    def test_object_valued_preconditions_are_refused_at_insert(self) -> None:
        """Measured: without step 3's jsonb_typeof CHECK, an object here makes
        proof.autonomy_readiness() raise `cannot get array length of a
        non-array` instead of returning a verdict — the proposal becomes
        unjudgeable rather than ineligible. The CHECK moves the failure to
        insert time, where it names the column."""
        with self.assertRaises(psycopg.errors.CheckViolation):
            self._propose(preconditions='{"satisfied": true}')

    def test_a_link_cannot_name_a_run_the_proposal_does_not_own(self) -> None:
        """Measured defect, guarded here. With step 3's link table referencing
        proof.action_proposals(proposal_id) ALONE, nothing required the link's
        run_id to equal the proposal's: a link naming this proposal with another
        run's run_id inserted cleanly. Requirement 6 then evaluated it against
        proof.validate_answer_citations(PROPOSAL.run_id) while the link's own FK
        had been satisfied against the OTHER run -- two sides validating
        different rows, measured verdict `PASSES requirement 6` for a proposal
        supported by a foreign run's invalid citation. The composite FK refuses
        the INSERT outright.
        """
        proposal_id = self._propose()
        self._cite(proposal_id)
        foreign_agent_run_id, foreign_run_id = self._seed_run()
        del foreign_agent_run_id
        source = self.conn.execute(
            """
            SELECT evidence_id, document_version_id, chunk_version_id,
                   source_uri, source_revision, quote_text
            FROM proof.answer_citations
            WHERE run_id = (
              SELECT run_id
              FROM proof.action_proposals
              WHERE proposal_id = %s
            )
            """,
            (proposal_id,),
        ).fetchone()
        self.conn.execute(
            """
            INSERT INTO proof.answer_citations(
              run_id, citation_number, evidence_id, document_version_id,
              chunk_version_id, source_uri, source_revision, quote_text
            )
            VALUES (%s, 2, %s, %s, %s, %s, %s, %s)
            """,
            (foreign_run_id, *source),
        )
        with self.assertRaises(psycopg.errors.ForeignKeyViolation) as caught:
            self.conn.execute(
                "INSERT INTO proof.action_proposal_citations(proposal_id, "
                "  run_id, citation_number, claim) VALUES (%s, %s, 2, 'borrowed')",
                (proposal_id, foreign_run_id),
            )
        self.assertEqual(
            caught.exception.diag.constraint_name,
            "action_proposal_citations_proposal_id_run_id_fkey",
            "the test must fail on proposal/run ownership, not another FK",
        )

    def test_a_persona_that_cannot_read_the_citation_gets_the_same_verdict(
        self,
    ) -> None:
        """MEASURED fail-open, and the reason requirement 6 counts VALIDATED
        citations instead of invalid ones.

        Deleting a citation cannot reproduce this: step 3's composite FK to
        proof.answer_citations CASCADEs the link away with it, and re-inserting
        the orphan link is refused with foreign_key_violation (measured) -- an
        unreachable-by-deletion link is unrepresentable. RLS is different: the
        rows all exist and satisfy every constraint, because referential
        integrity checks run with row_security off. Only the READ is filtered.

        proof.validate_answer_citations (sql/06_receipts.sql:67) INNER JOINs
        retrieval.documents and retrieval.chunks, both FORCE RLS with policies on
        acl_visibility (sql/11_roles_rls.sql:522-536), and the API runs the
        verdict under the requesting persona (backend/app/db.py:169 issues
        SET LOCAL ROLE per transaction). So a persona who cannot see the cited
        document loses the validation row while keeping the link -- the link
        table has no evidence_id, so its policy is the bare parent-run check,
        strictly weaker than proof.answer_citations' policy, which carries the
        evidence-reachability clause (lines 963-979).

        Measured before the fix: owner `1 cited claims failed`, persona
        `PASSES requirement 6` -- identical rows, no tampering, opposite
        verdicts. After: both `1 of 1 cited claims could not be validated`.
        """
        proposal_id = self._propose()
        self._cite(proposal_id)
        owner_eligible, _, _, _ = self._verdict(proposal_id)

        with self.conn.cursor() as cursor:
            cursor.execute("BEGIN")
            try:
                cursor.execute("SET LOCAL ROLE persona_app_engineer")
                visible = cursor.execute(
                    "SELECT count(*) FROM proof.validate_answer_citations("
                    "  (SELECT run_id FROM proof.action_proposals "
                    "   WHERE proposal_id = %s))",
                    (proposal_id,),
                ).fetchone()[0]
                persona = cursor.execute(
                    "SELECT pre_execution_eligible, pre_execution_reasons "
                    "FROM proof.autonomy_readiness(%s)",
                    (proposal_id,),
                ).fetchone()
            finally:
                cursor.execute("ROLLBACK")

        if visible:
            # The cited evidence happens to be workshop-visible, so this run
            # cannot exercise the gap. Then the two verdicts must simply agree.
            self.assertEqual(
                persona[0],
                owner_eligible,
                "with the citation readable, both roles must agree",
            )
            return
        self.assertFalse(
            persona[0],
            "a persona that cannot read the citation must never be told the "
            f"proposal is eligible; owner said {owner_eligible}",
        )
        self.assertTrue(
            any("could not be validated" in reason for reason in persona[1]),
            f"expected an unvalidatable-citation reason, got {persona[1]}",
        )

    def test_replacing_the_answer_citations_does_not_wedge_the_run(self) -> None:
        """Measured defect, guarded here. backend/app/agent.py:737 DELETEs a
        run's proof.answer_citations rows on every _persist_answer() call, and
        that function's own INSERT is ON CONFLICT (run_id) DO UPDATE -- so
        re-answering a run is a supported path. With ON DELETE RESTRICT on
        step 3's composite FK, the first proposal written against a run
        permanently wedged that run: the re-persist failed with `violates
        foreign key constraint
        "action_proposal_citations_run_id_citation_number_fkey"`. CASCADE drops
        the stale LINK and keeps the proposal, which then honestly reports
        `the proposal cites no evidence` until Task D2a relinks it.
        """
        proposal_id = self._propose()
        self._cite(proposal_id)
        run_id = self.conn.execute(
            "SELECT run_id FROM proof.action_proposals WHERE proposal_id = %s",
            (proposal_id,),
        ).fetchone()[0]
        eligible, _, _, _ = self._verdict(proposal_id)
        self.assertTrue(eligible, "baseline must be eligible before the re-persist")

        self.conn.execute(
            "DELETE FROM proof.answer_citations WHERE run_id = %s", (run_id,)
        )

        self.assertEqual(
            self.conn.execute(
                "SELECT count(*) FROM proof.action_proposal_citations "
                "WHERE proposal_id = %s",
                (proposal_id,),
            ).fetchone()[0],
            0,
            "the stale citation link must be removed with the citation it names",
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT count(*) FROM proof.action_proposals WHERE proposal_id = %s",
                (proposal_id,),
            ).fetchone()[0],
            1,
            "CASCADE must delete the LINK, never the proposal",
        )
        after_eligible, after_reasons, _, _ = self._verdict(proposal_id)
        self.assertFalse(after_eligible)
        self.assertIn("the proposal cites no evidence", after_reasons)

    def test_unbounded_timeout_is_ineligible(self) -> None:
        proposal_id = self._propose(lock_timeout=None)
        self._cite(proposal_id)
        eligible, reasons, _, _ = self._verdict(proposal_id)
        self.assertFalse(eligible)
        self.assertIn(
            "statement_timeout and lock_timeout must both be bounded", reasons
        )

    def test_missing_rollback_guidance_is_ineligible(self) -> None:
        proposal_id = self._propose(rollback_sql=None)
        self._cite(proposal_id)
        eligible, reasons, _, _ = self._verdict(proposal_id)
        self.assertFalse(eligible)
        self.assertIn("no rollback guidance was recorded", reasons)

    def test_successful_execution_does_not_flip_pre_execution_eligibility(self) -> None:
        """The retroactive-safety test. This is the one test in this class that
        must never be skipped or weakened: it is the only thing standing between
        an autonomy-READINESS assessment and a post-hoc safety claim."""
        proposal_id = self._propose(rollback_sql=None)  # ineligible by construction
        self._cite(proposal_id)
        before_eligible, before_reasons, _, _ = self._verdict(proposal_id)
        self.assertFalse(before_eligible)
        self.assertIn("no rollback guidance was recorded", before_reasons)

        capture_id, ingest_id = self._latest_wave_b_ids()
        # run_id is NOT NULL and composite-FK-bound to this proposal's own
        # run_id (step 3). Reading it back from the proposal rather than
        # inventing one is also what the real Task D3 writer must do.
        self.conn.execute(
            "INSERT INTO proof.action_executions(proposal_id, run_id, "
            "  approved_by, outcome, observed_index_definition, "
            "  observed_fingerprint, fingerprint_matches, wave_b_capture_id, "
            "  wave_b_ingest_id) "
            "SELECT p.proposal_id, p.run_id, 'participant', 'succeeded', "
            "       'CREATE INDEX ...', 'fp', true, %s, %s "
            "FROM proof.action_proposals p WHERE p.proposal_id = %s",
            (capture_id, ingest_id, proposal_id),
        )

        after_eligible, after_reasons, validated, post_reasons = self._verdict(
            proposal_id
        )
        self.assertFalse(
            after_eligible,
            "a successful execution must NOT make an ineligible proposal "
            "eligible; post-execution evidence may never feed "
            "pre_execution_eligible",
        )
        self.assertEqual(
            before_reasons, after_reasons,
            "the pre-execution reasons must be unchanged by the execution",
        )
        self.assertTrue(validated, f"execution succeeded but post said {post_reasons}")

    def _latest_wave_b_ids(self) -> tuple:
        row = self.conn.execute(
            "SELECT r.capture_id, i.ingest_id "
            "FROM casework.incident_capture_runs r "
            "JOIN casework.ingest_receipts i "
            "  ON i.source_uri = r.source_bundle_uri "
            "ORDER BY r.capture_started_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            self.skipTest("needs an admitted capture to reference")
        return row

    def _record(self, proposal_id: str, outcome: str, matches: bool) -> str:
        """One execution row with NULL Wave B identifiers, as Task D3's
        record-before-admission ordering writes it."""
        return str(
            self.conn.execute(
                "INSERT INTO proof.action_executions(proposal_id, run_id, "
                "  approved_by, outcome, observed_index_definition, "
                "  observed_fingerprint, fingerprint_matches) "
                "SELECT p.proposal_id, p.run_id, 'participant', %s, "
                "       'CREATE INDEX ...', 'fp', %s "
                "FROM proof.action_proposals p WHERE p.proposal_id = %s "
                "RETURNING execution_id",
                (outcome, matches, proposal_id),
            ).fetchone()[0]
        )

    def test_wave_b_receipt_attaches_exactly_once(self) -> None:
        """The record-before-admission ordering needs one narrow mutation. It
        must be narrow in both directions: once only, and receipt columns only."""
        proposal_id = self._propose()
        self._cite(proposal_id)
        execution_id = self._record(proposal_id, "succeeded", True)
        _, _, validated, post_reasons = self._verdict(proposal_id)
        self.assertFalse(
            validated,
            "an execution recorded before admission is not yet validated",
        )
        self.assertIn(
            "the result was not validated by an admitted Wave B capture",
            post_reasons,
        )

        capture_id, ingest_id = self._latest_wave_b_ids()
        self.conn.execute(
            "SELECT proof.attach_wave_b_receipt(%s, %s, %s)",
            (execution_id, capture_id, ingest_id),
        )
        _, _, validated, post_reasons = self._verdict(proposal_id)
        self.assertTrue(validated, f"after attach, post said {post_reasons}")

        with self.assertRaises(psycopg.errors.RaiseException) as caught:
            self.conn.execute(
                "SELECT proof.attach_wave_b_receipt(%s, %s, %s)",
                (execution_id, capture_id, ingest_id),
            )
        self.assertIn("already carries a Wave B receipt", str(caught.exception))

    def test_verdict_columns_cannot_be_rewritten(self) -> None:
        """The append-only rule, tested where privilege cannot reach it: this
        connection IS the owner and holds UPDATE. Without the trigger a recorded
        mismatch could be edited into a match, which would make the whole
        fingerprint comparison decorative."""
        proposal_id = self._propose()
        self._cite(proposal_id)
        execution_id = self._record(proposal_id, "succeeded", False)
        for column, value in (
            ("fingerprint_matches", True),
            ("outcome", "failed"),
            ("observed_fingerprint", "forged"),
            ("approved_by", "somebody-else"),
        ):
            with self.subTest(column=column):
                with self.assertRaises(psycopg.errors.RaiseException) as caught:
                    self.conn.execute(
                        f"UPDATE proof.action_executions SET {column} = %s "
                        "WHERE execution_id = %s",
                        (value, execution_id),
                    )
                self.assertIn("append-only", str(caught.exception))
        row = self.conn.execute(
            "SELECT outcome, fingerprint_matches, observed_fingerprint, "
            "       approved_by FROM proof.action_executions "
            "WHERE execution_id = %s",
            (execution_id,),
        ).fetchone()
        self.assertEqual(row, ("succeeded", False, "fp", "participant"))

    def test_bundling_a_receipt_does_not_smuggle_a_verdict_rewrite(self) -> None:
        """The measured defeat of the first trigger draft. That draft reverted
        protected columns silently instead of raising, so this exact statement
        SUCCEEDED, wrote the receipt, kept the honest verdict, and reported no
        error -- leaving the caller believing the rewrite had landed."""
        proposal_id = self._propose()
        self._cite(proposal_id)
        execution_id = self._record(proposal_id, "succeeded", False)
        capture_id, ingest_id = self._latest_wave_b_ids()
        with self.assertRaises(psycopg.errors.RaiseException) as caught:
            self.conn.execute(
                "UPDATE proof.action_executions "
                "   SET fingerprint_matches = true, wave_b_capture_id = %s, "
                "       wave_b_ingest_id = %s "
                " WHERE execution_id = %s",
                (capture_id, ingest_id, execution_id),
            )
        self.assertIn("append-only", str(caught.exception))
        self.assertEqual(
            self.conn.execute(
                "SELECT fingerprint_matches, wave_b_capture_id "
                "FROM proof.action_executions WHERE execution_id = %s",
                (execution_id,),
            ).fetchone(),
            (False, None),
            "the whole statement must roll back, receipt included",
        )

    def test_the_engines_set_null_is_permitted_on_an_attached_row(self) -> None:
        """The measured defeat of the SECOND trigger draft, which refused any
        update to a row already carrying a receipt. `ON DELETE SET NULL` IS an
        UPDATE and fires the same trigger, so that draft made every referenced
        capture undeletable for as long as its execution row existed.

        This test does NOT delete a real capture run: `casework.incident_capture_runs`
        is participant-induced live evidence that other tests and the Proof
        surface read, and `casework.evidence_items` references it ON DELETE
        RESTRICT. It exercises the same trigger path the referential action takes
        -- an UPDATE clearing an attached receipt to NULL -- which is exactly what
        the second draft refused."""
        proposal_id = self._propose()
        self._cite(proposal_id)
        execution_id = self._record(proposal_id, "succeeded", True)
        capture_id, ingest_id = self._latest_wave_b_ids()
        self.conn.execute(
            "SELECT proof.attach_wave_b_receipt(%s, %s, %s)",
            (execution_id, capture_id, ingest_id),
        )
        self.conn.execute(
            "UPDATE proof.action_executions SET wave_b_capture_id = NULL "
            "WHERE execution_id = %s",
            (execution_id,),
        )
        row = self.conn.execute(
            "SELECT wave_b_capture_id, wave_b_ingest_id IS NOT NULL, outcome, "
            "       fingerprint_matches FROM proof.action_executions "
            "WHERE execution_id = %s",
            (execution_id,),
        ).fetchone()
        self.assertEqual(
            row,
            (None, True, "succeeded", True),
            "clearing a receipt to NULL must be permitted, must leave the other "
            "receipt column alone, and must not touch the verdict columns",
        )

    def test_a_receipt_cannot_be_overwritten_with_a_different_one(self) -> None:
        """Clearing to NULL is permitted; substituting a DIFFERENT capture is
        not. Without this half, the transition rule that unblocked the previous
        test would also let an attached receipt be swapped for an unrelated
        one, which is provenance laundering."""
        proposal_id = self._propose()
        self._cite(proposal_id)
        execution_id = self._record(proposal_id, "succeeded", True)
        capture_id, ingest_id = self._latest_wave_b_ids()
        self.conn.execute(
            "SELECT proof.attach_wave_b_receipt(%s, %s, %s)",
            (execution_id, capture_id, ingest_id),
        )
        other = self.conn.execute(
            "SELECT capture_id FROM casework.incident_capture_runs "
            "WHERE capture_id <> %s LIMIT 1",
            (capture_id,),
        ).fetchone()
        if other is None:
            self.skipTest("needs a second capture run to substitute")
        with self.assertRaises(psycopg.errors.RaiseException) as caught:
            self.conn.execute(
                "UPDATE proof.action_executions SET wave_b_capture_id = %s "
                "WHERE execution_id = %s",
                (other[0], execution_id),
            )
        self.assertIn("already carries a different", str(caught.exception))

    def test_two_attempts_in_one_transaction_resolve_deterministically(self) -> None:
        """now() is transaction START time, so two rows recorded in one
        transaction share one approved_at. Ordering on approved_at alone was
        MEASURED non-deterministic: reclustering the same two rows returned
        'failed', 'succeeded', then 'failed' with no write in between. The
        verdict must name the LATER attempt every time."""
        proposal_id = self._propose()
        self._cite(proposal_id)
        with self.conn.transaction():
            self._record(proposal_id, "failed", False)
            later = self._record(proposal_id, "succeeded", True)
        capture_id, ingest_id = self._latest_wave_b_ids()
        self.conn.execute(
            "SELECT proof.attach_wave_b_receipt(%s, %s, %s)",
            (later, capture_id, ingest_id),
        )
        stamps = self.conn.execute(
            "SELECT count(DISTINCT approved_at), count(*) "
            "FROM proof.action_executions WHERE proposal_id = %s",
            (proposal_id,),
        ).fetchone()
        self.assertEqual(
            stamps, (1, 2), "the premise of this test is a shared approved_at"
        )
        reported = self.conn.execute(
            "SELECT execution_id FROM proof.action_executions "
            "WHERE proposal_id = %s "
            "ORDER BY approved_at DESC, recorded_seq DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()[0]
        self.assertEqual(
            str(reported), later, "recorded_seq must break the tie toward the "
            "later attempt, which is the one the verdict and the Proof panel "
            "both report"
        )
        _, _, validated, post_reasons = self._verdict(proposal_id)
        self.assertTrue(
            validated,
            "the verdict must follow the later, succeeded attempt; got "
            f"{post_reasons}",
        )
```

- [ ] **Step 10: Run the verdict tests.**

```bash
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python -m pytest backend/tests/test_supervised_execution.py -v
```

Expected: all 35 tests are discovered (ten fingerprint, four read-back, and 21
verdict); without the security schema, the two persona-specific verdict tests
skip and the other 33 pass. Step 13 adds four more tests for 39 in the finished
file. If
`test_successful_execution_does_not_flip_pre_execution_eligibility` fails, the
pre-execution branch is reading an execution column — that is the exact defect
the design spec forbids, and it must be fixed in the SQL, not in the test.

- [ ] **Step 11: Grant the persona write surface.** Without this step the three
  new tables are readable but not writable by any persona, and Lab 3's proposal
  write fails with `permission denied for table action_proposals`. The cause is
  `sql/11_roles_rls.sql:239-242`, which runs `REVOKE INSERT, UPDATE, DELETE ON ALL
  TABLES IN SCHEMA proof` before granting a narrow write surface, plus
  `ALTER DEFAULT PRIVILEGES IN SCHEMA proof` at lines 270–275, which grants
  `SELECT` only. Reads need no change: line 235 grants `SELECT ON ALL TABLES IN
  SCHEMA proof` before the REVOKE, and the default privileges cover tables created
  later, so the new tables are readable under either file ordering.

  Replace the `INSERT`-only grant at `sql/11_roles_rls.sql:249-253`:

```sql
    EXECUTE format(
      'GRANT INSERT ON proof.retrieval_candidates, proof.run_stages, '
      'proof.agent_escalations, proof.transport_invocations, '
      'proof.action_proposals, proof.action_proposal_citations, '
      'proof.action_executions TO %I',
      v_persona
    );
```

  **`INSERT` only — never add these three to the `INSERT, UPDATE` grant at lines
  243–248.** An `UPDATE` right on `proof.action_proposals` would let the recorded
  proposal be edited after the fact to match whatever was executed, which destroys
  the entire comparison; an `UPDATE` right on `proof.action_executions` would let a
  failed outcome be rewritten as a successful one. A proposal that needs amending
  is a new proposal.

  This makes one design decision explicit for Task D3's implementer: **every
  column that decides a verdict is written by the one `INSERT` that creates the
  row, after the participant has executed the DDL** — approval, outcome, observed
  definition, observed fingerprint, and `fingerprint_matches`, all in that one
  statement. Writing an approval row first and filling in the outcome later would
  require `UPDATE` on a verdict column, which the paragraph above forbids and
  which step 3's `action_executions_append_only` trigger refuses even for the
  owner. If D3 needs to record an approval that was never executed, that is the
  absence of an execution row, and `proof.autonomy_readiness` already reports it
  as `no execution has been recorded yet`.

  **The two Wave B identifiers are the single exception, and they are not verdict
  columns.** Task D3 records the row with both NULL and attaches them afterwards
  through `proof.attach_wave_b_receipt()`, because admission can fail after a
  `CREATE INDEX` has already succeeded and that execution must not vanish. D3 step
  8 sets out the ordering and the measured reason. The exception is narrow by
  construction: the attach function touches only those two columns, refuses a
  second attempt, is granted to nobody, and runs with `INVOKER` rights on the
  owner connection that the recorder already holds — so it widens no persona's
  privilege, and this step's `INSERT`-only grant is unchanged by it.

  **Step 11a: revoke the EXECUTE that the blanket grant hands back.** `sql/13`'s
  `REVOKE ALL ON FUNCTION proof.attach_wave_b_receipt(uuid, uuid, uuid) FROM
  PUBLIC` is not the last word on that function's privileges. `sql/13` is in
  `CORE_SQL_FILES` and therefore applies *before* `sql/11`, and
  `sql/11_roles_rls.sql:259` runs `GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA proof
  TO <persona>` for all three personas. `ON ALL FUNCTIONS` is evaluated at grant
  time over the functions that exist, and by then `attach_wave_b_receipt` exists.

  **Measured on PostgreSQL 17.10, 2026-08-04**, replaying the real file order in a
  probe database:

```
  after sql/13 REVOKE          persona_execute = f
  after sql/11 blanket GRANT   persona_execute = t   persona_update = f
```

  So the function's own `COMMENT` — "no GRANT is needed and none is issued" —
  becomes false the moment `make security-schema` runs. The privilege is not
  currently *exploitable*: the same probe called the function as the persona and
  got `42501 permission denied for table action_executions`, because the function
  is `SECURITY INVOKER` and the persona holds `INSERT` only. That is the entire
  defence, and it is one word in `sql/13` away from collapsing — a later
  maintainer marking the function `SECURITY DEFINER` (the draft this plan already
  rejected once, see step 8's text) would turn a stale grant into an
  arbitrary-row write on every execution row in the table.

  Close it where the widening happens. Add one statement to the persona loop in
  `sql/11_roles_rls.sql`, immediately after the `GRANT EXECUTE ON ALL FUNCTIONS IN
  SCHEMA proof` at line 259 and inside the same `LOOP`:

```sql
    EXECUTE format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA proof TO %I', v_persona);
    -- ...except the Wave B attach function. `ON ALL FUNCTIONS` above is evaluated
    -- over the functions that exist, and sql/13 (core, applied first) has already
    -- created this one -- so the blanket grant silently re-grants the EXECUTE that
    -- sql/13 revoked. Measured: f -> t across these two statements. Its only
    -- caller is the Wave B recorder on the owner connection; no persona has any
    -- reason to hold EXECUTE, and today only the INVOKER rights + INSERT-only
    -- table grant stop the call from writing. Do not rely on that alone.
    EXECUTE format(
      'REVOKE EXECUTE ON FUNCTION proof.attach_wave_b_receipt(uuid, uuid, uuid) '
      'FROM %I',
      v_persona
    );
```

  Measured afterwards in the same probe: `persona_execute = f`, and the owner's own
  call still succeeded and wrote the receipt — the revoke removes the persona
  grant without touching the caller that matters.

  **Do not instead move `sql/13` after `sql/11` in the apply order.** Step 14's
  ordering is load-bearing the other way round: `sql/11`'s `GRANT INSERT ON
  proof.action_proposals, …` names the `sql/13` tables and fails if they do not yet
  exist. And `REVOKE`-after-`GRANT` inside the loop is the shape the file already
  uses at lines 239–242 for exactly this reason.

  **And do not put the persona `REVOKE` in `sql/13` instead**, next to the
  `FROM PUBLIC` one, which is the intuitive place for it. Two measurements kill
  that placement:

  1. It does not work. `sql/13` applies **first**, so `sql/11`'s blanket grant
     runs afterwards and re-grants what `sql/13` just revoked. Measured in the
     probe: persona EXECUTE went `t` → `f` (the `sql/13` revoke) → `t` (the
     `sql/11` blanket grant). Only a revoke that runs *after* the widening
     statement holds, which is why step 11a's goes inside that loop.
  2. It cannot even execute. `REVOKE EXECUTE ON FUNCTION … FROM
     persona_app_engineer` on a core-only database raises `42704 role
     "persona_app_engineer" does not exist` — and `sql/13` is core, applied by
     `make schema` for every participant, whereas the personas only exist after
     the optional `make security-schema`. `sql/13` must not name a persona role at
     all. The `FROM PUBLIC` revoke that is already there is safe precisely because
     `PUBLIC` always exists.

  Prove the revoke red before moving on. Comment out the new `REVOKE`, re-apply
  `sql/11`, and confirm the privilege comes back:

```bash
  psql -X -v ON_ERROR_STOP=1 "$TEST_DATABASE_URL" -c "SELECT
    has_function_privilege('persona_app_engineer',
      'proof.attach_wave_b_receipt(uuid,uuid,uuid)', 'EXECUTE') AS persona_execute"
```

  Expected with the `REVOKE` commented out: `t`. Expected with it restored: `f`. A
  run that reads `f` both times means `sql/13` never applied, and the assertion in
  step 11b is proving nothing.

  **Step 11b: assert it, so the next blanket grant cannot re-open it.** The
  measurement above is a one-time observation; without a test, adding a fourth
  `GRANT ... ON ALL FUNCTIONS` line to that loop re-grants the privilege with
  nothing complaining. Add a new class to `backend/tests/test_supervised_execution.py`,
  the file steps 1, 7 and 9 built up (`FingerprintTests`,
  `ObservedFingerprintTests`, `AutonomyReadinessTests`):

```python
    def test_no_persona_holds_execute_on_the_wave_b_attach_function(self):
        """The blanket `GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA proof` in
        sql/11 re-grants what sql/13 revoked, because sql/13 applies first and
        `ON ALL FUNCTIONS` is evaluated over the functions that exist. Measured
        f -> t across those two statements. sql/11's targeted REVOKE (step 11a)
        is what puts it back to f; this test is what keeps it there."""
        with psycopg.connect(TEST_DSN) as conn:
            for persona in (
                "persona_app_engineer",
                "persona_dba",
                "persona_auditor",
            ):
                with self.subTest(persona=persona):
                    granted = conn.execute(
                        "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                        (
                            persona,
                            "proof.attach_wave_b_receipt(uuid,uuid,uuid)",
                        ),
                    ).fetchone()[0]
                    self.assertFalse(
                        granted,
                        f"{persona} holds EXECUTE on "
                        "proof.attach_wave_b_receipt(). Something re-granted it "
                        "-- check for a new blanket `GRANT ... ON ALL FUNCTIONS "
                        "IN SCHEMA proof` after sql/11 line 259, and add a "
                        "matching REVOKE inside the same loop.",
                    )
```

  This test requires the security module to be applied to `TEST_DATABASE_URL`
  (`make security-schema`), because the personas do not exist otherwise. A
  `has_function_privilege()` call naming an absent role raises `42704 role
  "persona_app_engineer" does not exist`, so on a core-only database this class
  must skip, not error, and must never read as a pass. Use the guard this
  repository already uses for persona-dependent tests —
  `backend/tests/test_rls_personas.py:30-47` — verbatim in shape:

```python
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
SECURITY_ENABLED = os.environ.get("WORKBENCH_SECURITY_ENABLED") == "1"
SECURITY_DATABASE_TESTS = bool(TEST_DATABASE_URL and SECURITY_ENABLED)


@unittest.skipUnless(
    SECURITY_DATABASE_TESTS,
    "set TEST_DATABASE_URL and WORKBENCH_SECURITY_ENABLED=1 for the "
    "persona EXECUTE checks",
)
class WaveBAttachGrantTests(unittest.TestCase):
    ...
```

  Put this test in its own class with that decorator. Do **not** attach the
  decorator to the class step 10 created: those tests assert the tables, the
  fingerprint functions and the verdict, all of which exist on a core-only
  database, and skipping them whenever the security module is absent would hide
  the bulk of A5's coverage from every `make test` run that does not opt in.

- [ ] **Step 12: Put the three tables under RLS, or G-27 blocks.** This step exists
  because it was measured, not predicted. `gates/rls_enforcement.py:133-159`
  (`PROTECTION_RULE_SQL`) derives "needs a policy" **from the catalog**, and any
  table in `casework`, `retrieval`, or `proof` carrying `evidence_id`, `capture_id`,
  `run_id`, `agent_run_id`, `acl`, or `acl_visibility` needs one. All three new
  tables carry `run_id` or `agent_run_id`, so all three are classified
  `needs_policy = true` the moment they exist.

  **Measured on 2026-08-04** by extracting `PROTECTION_RULE_SQL` from the gate and
  running it against a probe database holding exactly Step 3's three tables, with no
  policies yet:

```
  proof.action_executions          needs=True enabled=False forced=False policies=0
  proof.action_proposal_citations  needs=True enabled=False forced=False policies=0
  proof.action_proposals           needs=True enabled=False forced=False policies=0

  G-27 blocked_reason: "RLS not enabled+forced yet on:
    proof.action_proposal_citations, proof.action_proposals"
```

  So skipping this step does not produce a subtle gap — it stops G-27 dead. Append
  to `sql/11_roles_rls.sql`, after the `agent_subquestions`/`agent_escalations` loop
  that ends at line 1058:

```sql
-- Supervised-execution receipts (sql/13_supervised_execution.sql). Two parents,
-- so two loops: a proposal hangs off the AGENT run that produced it, while a
-- citation and an execution hang off the RETRIEVAL run whose citations they
-- reference. Splitting them is not stylistic -- section 8's chain must reach the
-- table that actually carries `role`, and proof.action_proposal_citations has no
-- agent_run_id to reach proof.agent_runs through.
--
-- WHY A BARE PARENT-EXISTENCE PREDICATE IS SUFFICIENT, measured rather than
-- assumed. The predicate below names no persona and compares no role, so it reads
-- as though every persona sees every proposal. It does not, because RLS on the
-- PARENT applies inside this EXISTS: proof.agent_runs carries the persona
-- predicate (sql/11_roles_rls.sql:905-925) and is FORCE ROW LEVEL SECURITY, so a
-- non-BYPASSRLS role's EXISTS sees only its own parent rows and the child row
-- disappears with them. Measured on PostgreSQL 17.10 with this exact two-table
-- shape: persona A selecting the child table returned ONLY A's row, persona B only
-- B's. Do not "improve" this by inlining a role comparison here -- a second
-- predicate on the child would drift from the parent's, and the parent is the
-- table that owns the answer.
--
-- The owner policy's `USING (true)` does not undo that, for a reason also
-- measured: TO CURRENT_USER is resolved at CREATE POLICY time and stored as the
-- concrete role in pg_policy.polroles (verified -- it read back as the bootstrap
-- owner, not as a re-evaluated CURRENT_USER). Permissive policies OR together, so
-- a `USING (true)` policy that applied to the personas WOULD fail open across all
-- of them; it applies to exactly one role, so it does not. This is the same
-- OR-widening hazard sql/11_roles_rls.sql:886 warns about, and it is the reason
-- that comment is worth re-reading before adding any policy to these tables.
DO $$
DECLARE
  v_table text;
BEGIN
  FOREACH v_table IN ARRAY ARRAY['action_proposals']
  LOOP
    EXECUTE format('ALTER TABLE proof.%I ENABLE ROW LEVEL SECURITY', v_table);
    EXECUTE format('ALTER TABLE proof.%I FORCE ROW LEVEL SECURITY', v_table);
    EXECUTE format('DROP POLICY IF EXISTS proof_%s_persona ON proof.%I',
                   v_table, v_table);
    EXECUTE format('DROP POLICY IF EXISTS proof_%s_owner ON proof.%I',
                   v_table, v_table);
    EXECUTE format($fmt$
      CREATE POLICY proof_%s_persona ON proof.%I
        FOR ALL
        TO persona_app_engineer, persona_dba, persona_auditor
        USING (
          EXISTS (
            SELECT 1
            FROM proof.agent_runs parent
            WHERE parent.agent_run_id = proof.%I.agent_run_id
          )
        )
        WITH CHECK (
          EXISTS (
            SELECT 1
            FROM proof.agent_runs parent
            WHERE parent.agent_run_id = proof.%I.agent_run_id
          )
        )
    $fmt$, v_table, v_table, v_table, v_table);
    EXECUTE format($fmt$
      CREATE POLICY proof_%s_owner ON proof.%I
        FOR ALL TO CURRENT_USER
        USING (true)
        WITH CHECK (true)
    $fmt$, v_table, v_table);
  END LOOP;

  FOREACH v_table IN ARRAY ARRAY[
    'action_proposal_citations',
    'action_executions'
  ]
  LOOP
    EXECUTE format('ALTER TABLE proof.%I ENABLE ROW LEVEL SECURITY', v_table);
    EXECUTE format('ALTER TABLE proof.%I FORCE ROW LEVEL SECURITY', v_table);
    EXECUTE format('DROP POLICY IF EXISTS proof_%s_persona ON proof.%I',
                   v_table, v_table);
    EXECUTE format('DROP POLICY IF EXISTS proof_%s_owner ON proof.%I',
                   v_table, v_table);
    EXECUTE format($fmt$
      CREATE POLICY proof_%s_persona ON proof.%I
        FOR ALL
        TO persona_app_engineer, persona_dba, persona_auditor
        USING (
          EXISTS (
            SELECT 1
            FROM proof.retrieval_runs parent
            WHERE parent.run_id = proof.%I.run_id
          )
        )
        WITH CHECK (
          EXISTS (
            SELECT 1
            FROM proof.retrieval_runs parent
            WHERE parent.run_id = proof.%I.run_id
          )
        )
    $fmt$, v_table, v_table, v_table, v_table);
    EXECUTE format($fmt$
      CREATE POLICY proof_%s_owner ON proof.%I
        FOR ALL TO CURRENT_USER
        USING (true)
        WITH CHECK (true)
    $fmt$, v_table, v_table);
  END LOOP;
END
$$;
```

  Two policies per table, one persona and one owner, matching every other loop in
  that file. Do not add a third: `PERMISSIVE` policies combine with `OR`, so a
  second persona policy would admit a row when *either* predicate passed — the file
  says so at lines 884-887 and it is the same trap here.

  Add a test for the isolation the parent-existence predicate delivers, because
  reading these four policies does not reveal that they isolate anything — the
  predicate names no persona, and the property lives one table away, in
  `proof.agent_runs`:

```python
    def test_a_persona_cannot_read_another_personas_proposal(self) -> None:
        """Cross-persona isolation, which the child predicate does not state.

        proof_action_proposals_persona checks only that the parent agent run
        EXISTS. It isolates anyway, because RLS on the parent applies inside that
        EXISTS: proof.agent_runs carries the persona predicate and is FORCE ROW
        LEVEL SECURITY, so a persona's EXISTS matches only its own parent rows and
        the child row vanishes with them. Measured on PostgreSQL 17.10 with this
        two-table shape -- persona A saw only A's child row, persona B only B's.

        This test exists because that behaviour is a property of nested RLS rather
        than of anything visible in the child policy. Someone simplifying the
        parent's policy, or granting a persona BYPASSRLS, breaks isolation on FOUR
        tables without touching any of their policies -- and no other test in this
        file would notice.
        """
        proposal_id = self._propose()
        owning_role = self.conn.execute(
            "SELECT r.role FROM proof.action_proposals p "
            "JOIN proof.agent_runs r ON r.agent_run_id = p.agent_run_id "
            "WHERE p.proposal_id = %s",
            (proposal_id,),
        ).fetchone()[0]
        foreign_personas = {
            "app_engineer": "persona_dba",
            "dba": "persona_app_engineer",
            "auditor": "persona_app_engineer",
        }
        foreign = foreign_personas[owning_role]

        with self.conn.cursor() as cursor:
            cursor.execute("BEGIN")
            try:
                cursor.execute(f"SET LOCAL ROLE {foreign}")
                visible = cursor.execute(
                    "SELECT count(*) FROM proof.action_proposals "
                    "WHERE proposal_id = %s",
                    (proposal_id,),
                ).fetchone()[0]
                executions = cursor.execute(
                    "SELECT count(*) FROM proof.action_executions "
                    "WHERE proposal_id = %s",
                    (proposal_id,),
                ).fetchone()[0]
            finally:
                cursor.execute("ROLLBACK")

        self.assertEqual(
            visible,
            0,
            f"{foreign} can read a proposal owned by the {owning_role} persona; "
            "the parent-existence policy is not isolating, which means RLS on "
            "proof.agent_runs is not being applied inside its EXISTS",
        )
        self.assertEqual(executions, 0, f"{foreign} can read its executions too")
```

  **Prove it can fail before trusting it.** As owner, `ALTER POLICY
  proof_agent_runs_persona ON proof.agent_runs USING (true)` — the parent's
  predicate, not the child's — re-run, and confirm the test FAILS. Then restore the
  policy by re-running `sql/11_roles_rls.sql`'s loop. If the test still passes with
  the parent wide open, it is asserting nothing: most likely the run it created
  belongs to the persona it is testing as, so check `owning_role` first.

  **Three columns in Step 3 exist only for this step, and nothing in Step 3's own
  behaviour explains them.** Do not remove them as redundant: `proof.action_executions`
  declares `run_id uuid NOT NULL` plus `FOREIGN KEY (proposal_id, run_id) REFERENCES
  proof.action_proposals(proposal_id, run_id)`, and `proof.action_proposals` declares
  `UNIQUE (proposal_id, run_id)` alongside its primary key. The denormalized `run_id`
  is what lets the second policy loop above reach `proof.retrieval_runs` in one join;
  the composite foreign key is what stops that denormalized key from naming a run
  belonging to a different persona; the redundant `UNIQUE` exists because PostgreSQL
  refuses a two-column reference unless a unique constraint covers exactly that pair.

  **All four properties below were measured on a real server on 2026-08-04, not
  reasoned about:**
  - Without `run_id` on `proof.action_executions`, the gate classified it
    `needs_policy=False` — meaning it would have been *silently unprotected*, with
    G-27 green. That is worse than the blocking case, and it is the
    `gate-self-reference-fail-open` hazard in a new place: a catalog-derived rule
    only protects what the catalog can see.
  - With `run_id NOT NULL` added, the gate's `RUN_GATED_SQL` classified it
    `(proof.action_executions, role=False, run_id_required=True,
    agent_run_id_required=False, evidence_ref=False)`, which routes `_run_root()`
    to the `proof.retrieval_runs` join — the same parent the policy above uses.
  - `proof.action_proposals` classified `run_id_required=True` **and**
    `agent_run_id_required=True`; `_run_root()` checks `agent_run_id` first, so it
    resolves to `proof.agent_runs`. That is why the proposal loop above joins
    `agent_runs` and not `retrieval_runs`: a policy naming a different parent from
    the one the gate's oracle walks would make the two disagree.
  - The composite FK genuinely refuses divergence. Inserting an execution whose
    `run_id` matched its proposal succeeded; inserting one pointing at a different
    run failed with `insert or update on table "action_executions" violates foreign
    key constraint "action_executions_proposal_id_run_id_fkey"`.

  Then verify the partition holds, which is what G-27's group (b''') asserts:

```bash
psql -X -v ON_ERROR_STOP=1 \
  "postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" <<'SQL'
DO $guard$ BEGIN
  IF current_database() <> 'dat410_review_remediation_test' THEN
    RAISE EXCEPTION 'SAFETY ABORT: connected to %', current_database();
  END IF;
END $guard$;
BEGIN;
SET LOCAL ROLE persona_app_engineer;
SELECT 'app_engineer' AS persona,
       (SELECT count(*) FROM proof.action_proposals) AS proposals,
       (SELECT count(*) FROM proof.action_executions) AS executions;
ROLLBACK;
BEGIN;
SET LOCAL ROLE persona_dba;
SELECT 'dba' AS persona,
       (SELECT count(*) FROM proof.action_proposals) AS proposals,
       (SELECT count(*) FROM proof.action_executions) AS executions;
ROLLBACK;
BEGIN;
SET LOCAL ROLE persona_auditor;
SELECT 'auditor' AS persona,
       (SELECT count(*) FROM proof.action_proposals) AS proposals,
       (SELECT count(*) FROM proof.action_executions) AS executions;
ROLLBACK;
SQL
```

Expected: the persona owning the `app_engineer` agent run reads its own rows; the
other two read `0`. Measured on the probe with one proposal and one execution owned
by `app_engineer`: `app_engineer` read `1/1`, `dba` read `0/0`, `auditor` read
`0/0`, and the owner read `1/1`. `SET LOCAL ROLE` **must** be inside an explicit
transaction — outside one it warns `SET LOCAL can only be used in transaction
blocks` and silently does nothing, which would make all three personas read as the
owner and the check pass while proving nothing.

- [ ] **Step 13: Assert the agent holds no DDL privilege, then run the security
  gates.** The design spec requires this asserted **against the catalog, not
  against the tool registry**, because privilege can be granted without touching
  any Python. Append to `backend/tests/test_supervised_execution.py`:

```python
@unittest.skipUnless(
    SECURITY_DATABASE_TESTS,
    "set TEST_DATABASE_URL and WORKBENCH_SECURITY_ENABLED=1 for the persona "
    "privilege checks",
)
class NoDdlPrivilegeTests(unittest.TestCase):
    """The agent proposes; it never executes. Asserted against pg_catalog,
    because a GRANT can widen privilege without editing agent/registry.py.

    Guarded on SECURITY_DATABASE_TESTS, not on TEST_DATABASE_URL alone. Every
    assertion below names a persona role, and `has_schema_privilege()` /
    `has_table_privilege()` / `pg_has_role()` all RAISE `42704 role "..." does not
    exist` rather than returning false when the role is absent (measured on
    PostgreSQL 17.10). On a core-only database that is an ERROR, not a skip, and
    `test_agent_registry_exposes_exactly_the_seven_readonly_tools` -- which needs no
    database at all -- would be dragged down with it. Same guard, same reason, as
    step 11b's WaveBAttachGrantTests.

    SCOPE, and the boundary is load-bearing: this class checks the three PERSONA
    roles, which is what the agent runs as (the API issues SET LOCAL ROLE per
    transaction, backend/app/db.py:169). It does NOT check `workshop_app`, the pool
    login the persona is set FROM. That gap is not theoretical -- a draft of Task D3
    granted `workshop_app` membership in `workbench_lab_owner`, which handed the pool
    identity passive CREATE INDEX, DROP TABLE and TRUNCATE on the lab table, and
    every assertion in this class still passed: privileges reaching `workshop_app`
    do not flow to the personas, because the personas are not members of it
    (the grant runs the other way, WITH INHERIT FALSE). Task D3 step 1's
    `ApiPoolLabPrivilegeTests` covers that role. Neither class subsumes the other;
    both are required.

    Measured on PostgreSQL 17.10 with that exact grant in place: all four persona
    columns above read `f` (this class green) while `has_schema_privilege('ws_app',
    …, 'CREATE')` and `pg_has_role('ws_app', relowner, 'USAGE')` both read `t`, and
    the pool login then ran `CREATE INDEX` on the lab table successfully. A green run
    of this class is therefore not evidence about the pool -- it is evidence about
    the personas, and only that."""

    PERSONAS = ("persona_app_engineer", "persona_dba", "persona_auditor")

    @classmethod
    def setUpClass(cls) -> None:
        cls.conn = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
        name = cls.conn.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY ABORT: refusing to run against {name}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_no_persona_can_create_an_index_on_the_lab_table(self) -> None:
        """CREATE INDEX requires table OWNERSHIP -- a schema-CREATE check alone
        would miss an ownership grant, and an ownership check alone would miss a
        role that can create its own objects. Both are asserted."""
        for persona in self.PERSONAS:
            with self.subTest(persona=persona):
                row = self.conn.execute(
                    "SELECT has_schema_privilege(%s, 'workbench_lab', 'CREATE'),"
                    "       pg_has_role(%s, c.relowner, 'USAGE'),"
                    "       has_table_privilege(%s, 'workbench_lab.orders', 'INSERT'),"
                    "       has_table_privilege(%s, 'workbench_lab.orders', 'UPDATE')"
                    "  FROM pg_class c WHERE c.oid = 'workbench_lab.orders'::regclass",
                    (persona, persona, persona, persona),
                ).fetchone()
                self.assertFalse(row[0], f"{persona} can CREATE in workbench_lab")
                self.assertFalse(row[1], f"{persona} owns workbench_lab.orders")
                self.assertFalse(row[2], f"{persona} can INSERT into orders")
                self.assertFalse(row[3], f"{persona} can UPDATE orders")

    def test_personas_can_insert_but_not_rewrite_proof(self) -> None:
        """Personas may append proof, but may not rewrite or delete it."""
        for persona in self.PERSONAS:
            for table in (
                "proof.action_proposals",
                "proof.action_proposal_citations",
                "proof.action_executions",
            ):
                with self.subTest(persona=persona, table=table):
                    row = self.conn.execute(
                        "SELECT has_table_privilege(%s, %s, 'UPDATE'),"
                        "       has_table_privilege(%s, %s, 'DELETE'),"
                        "       has_table_privilege(%s, %s, 'INSERT')",
                        (persona, table, persona, table, persona, table),
                    ).fetchone()
                    self.assertFalse(row[0], f"{persona} can UPDATE {table}")
                    self.assertFalse(row[1], f"{persona} can DELETE {table}")
                    self.assertTrue(row[2], f"{persona} cannot INSERT {table}")

class AgentWriteBoundaryTests(unittest.TestCase):
    def test_agent_registry_exposes_exactly_the_seven_readonly_tools(self) -> None:
        """Belt to the catalog's braces. This asserts the exact expected SET,
        hardcoded as literals -- not a name-substring scan. A substring check for
        'execute' would wave through a write tool named apply_recommendation, and
        deriving the expectation from the registry itself would make the
        assertion unfailable (the gate-self-reference-fail-open hazard).

        agent.registry.TOOLS is a dict keyed by tool name, so iterate .keys()."""
        from agent.registry import TOOLS

        self.assertEqual(
            set(TOOLS),
            {
                "answer_with_citations",
                "compare_sources",
                "decompose_question",
                "explain_ranking",
                "follow_evidence_links",
                "search_evidence",
                "synthesize_cited_answer",
            },
            "the agent's tool set changed; a new tool must be proven "
            "read/synthesis-only before this literal set is updated",
        )
```

  Then apply the roles file and run the gates:

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python backend/scripts/run_sql.py --files sql/11_roles_rls.sql
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
WORKBENCH_SECURITY_ENABLED=1 \
  .venv/bin/python -m pytest backend/tests/test_supervised_execution.py -v
WORKBENCH_SECURITY_ENABLED=1 FAIL_ON_BLOCKED=1 \
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  gates/checks.sh G-27 G-29 G-30 G-31
```

Expected: all 39 tests PASS and all four gates PASS. `run_sql.py` takes `--files`
(plural, `nargs='+'`), not `--file`. G-30 asserts the participant privilege model;
a failure there means the new grants reached a role they should not have.

`WORKBENCH_SECURITY_ENABLED=1` on the pytest line is load-bearing here and only
here. This is the one point in Task A5 where the personas exist, so it is the one
run where the two persona verdict tests, `WaveBAttachGrantTests`, and
`NoDdlPrivilegeTests` execute rather than skipping. Step 10 deliberately omits
security mode. Read pytest's summary line: it must say `39 passed` with no
skipped count. A run that reports `34 passed, 5 skipped` means the security
module was never applied to this database and the grant assertions proved
nothing — re-run `make security-schema` against it first.

**Three facts behind the ownership assertion, all measured on 2026-08-04 against a
real PostgreSQL 17.10 server, because getting this check wrong makes it useless.
Re-confirm them on the 18.3 cluster if any behaves differently there:**
  - A role with `SELECT` only, and no `CREATE` on the schema, was refused with
    `ERROR: must be owner of table orders` when it attempted `CREATE INDEX`. So
    ownership, not a table-level privilege, is the operative gate.
  - A role that owned its table succeeded at `CREATE INDEX` **while**
    `has_schema_privilege(role, schema, 'CREATE')` was also true — meaning a check
    of only one of the two conditions can pass while the role can still create the
    index. Both conditions are asserted above for that reason.
  - `MAINTAIN` (PostgreSQL 17+) does **not** grant `CREATE INDEX`; it covers
    `VACUUM`, `ANALYZE`, `REINDEX`, `CLUSTER`, `REFRESH MATERIALIZED VIEW`, and
    `LOCK TABLE`. Verified false for the probe role. Do not add it to the
    assertion list — asserting a privilege that was never the risk reads as
    coverage while proving nothing.

- [ ] **Step 14: Register the new SQL file so `make schema` applies it.** Until
  this step, `sql/13_supervised_execution.sql` exists on disk and is applied by
  nothing. Add it to `CORE_SQL_FILES` in `Makefile:15-26`, after
  `sql/10_admission.sql`:

```make
CORE_SQL_FILES := \
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
	sql/13_supervised_execution.sql
```

  `CORE_SQL_FILES`, not `SECURITY_SQL_FILES`: the supervised-execution schema is
  core to Labs 3–4 and must apply for every participant, whereas the security
  module (`sql/11`, `sql/12`) is optional and applied only by `make
  security-schema`. Both `make schema` and `make security-schema` expand
  `CORE_SQL_FILES`, so one edit covers both. Keep the tab indentation — `Makefile`
  continuation lines here are tab-indented, and spaces will break the build.

  The number 13 follows 12 even though this file lands in the core list ahead of
  11 and 12 in apply order. That is intentional and harmless: `sql/13` depends on
  `proof.*` from `sql/01` and on nothing in `sql/11`/`sql/12`, while `sql/11`'s
  `GRANT` statements name the `sql/13` tables and therefore must run after it. The
  ordering is `01 … 10, 13` then, optionally, `11, 12`. Do not renumber the
  existing files: `sql/11_roles_rls.sql` and `sql/12_masking.sql` are named by
  path in `README.md:140`, `scripts/git-hooks/pre-push:16` (which gates pushes
  touching either file on `make security-checks`),
  `scripts/build_live_source_archive.sh`,
  `backend/tests/test_release_artifact_scripts.py`, and roughly two dozen
  explanatory references across `gates/rls_enforcement.py`,
  `gates/masking_determinism.py`, and `gates/persona_equivalence.py`.

  Then add the file to the participant archive's required list in
  `scripts/build_live_source_archive.sh:40-62`, after `sql/10_admission.sql`:

```bash
  sql/10_admission.sql
  sql/13_supervised_execution.sql
  sql/11_roles_rls.sql
```

  and extend the archive assertion in
  `backend/tests/test_release_artifact_scripts.py:45-56` so a future edit cannot
  silently drop it. Add one line to
  `test_live_archive_requires_every_participant_asset`, next to the existing
  single-path assertions:

```python
        self.assertIn("sql/13_supervised_execution.sql", source)
        self.assertIn(".claude/skills/extend-hybrid-retrieval/SKILL.md", source)
```

  Do not add it to that file's `SECURITY_FILES` set — that set means "files only
  `make security-schema` applies," and `sql/13` is core. Do not introduce a new
  set for one entry either; the file already asserts single paths inline, and a
  Python constant named `CORE_SQL_FILES` beside the identically-named `Makefile`
  variable holding eleven different files is a trap for the next reader.

  Run the archive tests before moving on:

```bash
.venv/bin/python -m pytest backend/tests/test_release_artifact_scripts.py -v
```

Expected: PASS. A failure here means the archive script and its assertion
disagree, which is exactly the `published-archive-ops-only-dump` failure mode:
a shipped archive missing a schema file the labs require.

- [ ] **Step 15: Live-Aurora acceptance criteria.** Against the disposable
  database, confirm the fingerprint agrees with a real index on the real lab
  table, not just on a probe table:

```bash
psql -X -v ON_ERROR_STOP=1 \
  "postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" <<'SQL'
DO $guard$ BEGIN
  IF current_database() <> 'dat410_review_remediation_test' THEN
    RAISE EXCEPTION 'SAFETY ABORT: connected to %', current_database();
  END IF;
END $guard$;
CREATE INDEX IF NOT EXISTS idx_orders_priority_created
  ON workbench_lab.orders (priority_tier, created_at DESC);
SELECT f.index_definition, left(f.fingerprint, 16) AS fingerprint
FROM pg_class c
CROSS JOIN proof.observed_index_fingerprint(c.oid) f
WHERE c.relname = 'idx_orders_priority_created';
SELECT left(proof.index_action_fingerprint(
         'create_index', 'workbench_lab', 'orders', 'btree', false,
         ARRAY[
           proof.canonical_index_key('priority_tier', 'asc', 'nulls_last', NULL),
           proof.canonical_index_key('created_at', 'desc', 'nulls_first', NULL)
         ],
         ARRAY[]::text[], NULL), 16) AS proposal_side_fingerprint;
SQL
```

Expected: the two fingerprints are **byte-identical**. The second query is the
proposal side computed from plain structured field names — exactly what the agent
emits, with no catalog access — and the first is the observation side read out of
`pg_index`. Record both hex values in the gate-results document. This is the pair
Lab 4 depends on, and it must be measured against `workbench_lab.orders` itself
because the table's real column types determine the default opclasses the
fingerprint elides.

**This exact block was run on 2026-08-04 against a real PostgreSQL server** with
`workbench_lab.orders(order_id bigint, priority_tier text, created_at timestamptz,
amount numeric)`. Both sides returned `82d2c73c30ae4f86`. Three further variants
were measured on the same fingerprint, and an implementer should expect the same:
passing `NULL` for both `p_nulls` arguments still yields `82d2c73c30ae4f86` (so
the agent need not reason about NULL ordering at all); upper-casing the schema,
table, and method and padding the expression with spaces still yields
`82d2c73c30ae4f86`; and reversing the two key columns yields `9dddcd52235023e6`,
confirming key order is part of the action. The values above will differ on
`workbench_lab.orders` only if its column names or the index shape differ from
this — a mismatch means the shape changed, not that the function is broken.

- [ ] **Step 16: Cleanup and failure recovery.** The index created in step 15 is
  the same one Lab 4 has the participant create, so drop it before a rehearsal
  run or the Lab 4 precondition `no_index_exists` will be false:

```bash
psql -X -v ON_ERROR_STOP=1 \
  "postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" <<'SQL'
DO $guard$ BEGIN
  IF current_database() <> 'dat410_review_remediation_test' THEN
    RAISE EXCEPTION 'SAFETY ABORT: connected to %', current_database();
  END IF;
END $guard$;
DROP INDEX IF EXISTS workbench_lab.idx_orders_priority_created;
SQL
```

  The `DO $guard$` block is not decoration: it is a `DROP` against a database
  named on a command line. Per the `run-sql-dsn-trap-live-drop` incident, a
  connection string typed one character wrong is how a live database was
  previously lost, and the guard runs on the same connection that performs the
  drop, so there is no window between the check and the write.

  The test classes write real `proof.retrieval_runs` and `proof.agent_runs` rows
  and leave them. Those are honest records of test runs; do not add teardown that
  deletes them, because `ON DELETE RESTRICT` on the referencing tables would make
  the deletion order fragile for no benefit on a disposable database.

- [ ] **Step 17: Participant-facing changes.** None in this task. The schema is
  invisible until Task D2 writes a proposal into it and Task D3 has the
  participant approve and execute it.

- [ ] **Step 18: Commit.**

```bash
git add sql/13_supervised_execution.sql sql/11_roles_rls.sql Makefile \
  scripts/build_live_source_archive.sh \
  backend/tests/test_supervised_execution.py \
  backend/tests/test_release_artifact_scripts.py
git commit -m "Add the supervised-execution proof schema"
```

**Dependencies:** none beyond the existing `proof` schema. This task can run
before or after A1–A4; it is sequenced here so Phase D has the schema to write
into. Step 15's acceptance criterion needs `workbench_lab.orders`, which Task B1
creates — run steps 1–14 now and step 15 after B1, or run the whole task after
B1. Do not substitute a probe table for `workbench_lab.orders` in step 15.

### Task A6: Prove the retroactive-safety path is absent, not merely unused (G-34)

**Owning schema/module:** `gates/`.

**Files:**
- Create: `gates/retroactive_safety.py` (G-34)
- Modify: `gates/checks.sh:36-44` — add
  `"G-34|retroactive_safety.py|Retroactive-safety separation in the autonomy verdict"`
  to `CORE_GATES`
- Test: the gate is the test; step 3 proves it can go red six different ways

**Interfaces:**
- Consumes: Task A5's `proof.autonomy_readiness(uuid)`,
  `proof.action_proposals`, `proof.action_executions`.
- Produces: `G-34` in `CORE_GATES`, runnable via `gates/checks.sh G-34`.

**Migration and compatibility implications:** read-only, so it is safe against
any database including `dat410_live`. It adds no schema and reads no participant
data — only `pg_proc.prosrc` and the proposal rows.

**Why a gate and not just Task A5's test.** A5 step 9's
`test_successful_execution_does_not_flip_pre_execution_eligibility` proves the
retroactive path is *unused* on one constructed row. That is a real assertion and
it stays. It cannot prove the path is *absent*: a future edit could add a branch
that reads `fingerprint_matches` under a condition that row does not hit, and the
test would still pass. G-34 reads the shipped function body and proves the
pre-execution region cannot reach an execution record at all. The design spec
states the invariant in prose and the user's approval named it explicitly —
"successful post-execution evidence must not be used retroactively to claim the
action was safe beforehand" — so it gets a structural gate, not only a row test.

**Three design decisions in this gate, all the result of a measured near-miss.**

1. **`EXECUTION_TOKENS` are hardcoded literals, never derived from
   `proof.action_executions`' catalog entry.** Deriving them would mean a DROPped
   table yields an empty token list and a vacuous pass — the
   `gate-self-reference-fail-open` hazard, which has already produced two
   measured green-on-broken cases in this repository.
2. **The behavioral half is a SUBSET invariant, not a reimplementation of the
   verdict.** A gate that recomputes what it judges is a twin that drifts, and
   when the two agree on a wrong answer it reports green. The scan asks only:
   does any proposal get called eligible while its own row contradicts an
   eligibility requirement?
3. **The eligibility column is checked against an allowlist
   (`ELIGIBILITY_ALLOWED`), not a denylist of declared locals.** A denylist was
   written first and is unsound: PL/pgSQL's assignable names are not confined to
   the `DECLARE` section — this function's own `RETURNS TABLE` columns are
   assignable variables that appear in no declaration the gate can read. The
   allowlist also means an unrecognized construct fails loudly instead of passing
   silently, which is the correct direction for a gate to be wrong in.

**This gate was built and measured against a real PostgreSQL 17 server before
being written into this plan, and the first version of it passed the single most
dangerous regression.** `ret.group(1).split(",")[0]` truncated the first returned
column at `array_length(v_pre, 1)`'s own internal comma, so an injected
`OR v_exec.fingerprint_matches` fell outside the inspected text entirely and the
gate reported PASS on the exact defect it exists to catch. That is why
`split_top_level()` is paren-depth-aware and why its docstring records the
near-miss. Do not simplify it back.

**An independent review of that version then defeated it six more times, and
every defeat was reproduced before being fixed** (2026-08-04, by feeding crafted
`prosrc` through the gate's own `static_problems()`). Each is written up as a
regression in step 3 (R7–R10) or in `pre_region()`'s docstring, and together they
are the reason the gate looks the way it does:

1. A helper reached only from the `RETURN QUERY SELECT` — the walk was seeded
   from the pre-execution region alone.
2. A read hidden in a dynamic-SQL string literal — the literal blanking that
   stops the reason strings from self-flagging is what concealed it. `EXECUTE` is
   now refused, not scanned.
3. A helper in a non-`proof` schema — candidate names came from
   `nspname = 'proof'` and calls were matched only as `proof.<name>(`.
4. A read laundered through a local boolean into the eligibility column — not an
   execution token, and `v_pre` was still present, so every check passed.
5. **The right-hand side of the last `v_pre` assignment sat outside the inspected
   region**, because the region was cut at the end of the `:=` operator rather
   than at the statement's semicolon. This is the worst of the six: it is where a
   post-execution read would most naturally be written, and it also meant the gate
   reported `helpers walked: none` on the real body, silently disarming the
   transitive half on the shipped function.
6. The literal-bearing slice reused a character offset computed on the
   literal-blanked text, which is shorter.

The generalizable point, and it is the same one Task A5 learned: **a gate is only
evidence for the defeats someone actually attempted against it.** Six of the ten
regressions in step 3 exist because someone tried to break this gate on purpose
and succeeded.

- [ ] **Step 1: Write the gate.** Create `gates/retroactive_safety.py`:

```python
#!/usr/bin/env python3
"""G-34 - retroactive-safety separation in proof.autonomy_readiness().

The design spec's Supervised Execution Model requires that successful
post-execution evidence never retroactively make a proposal look safe
beforehand. A test can only show the path is UNUSED on the rows that happen to
exist. This gate shows the path is ABSENT: it reads the shipped function body
out of pg_proc and proves the pre-execution region cannot reach an execution
record, then runs one read-only contradiction scan over the rows that do exist.

Read-only, per gates/_common.py: SELECT only, no DDL, no writes.

Two halves, both needed:

1. Static. Four checks, each closing a measured defeat of an earlier version:

   a. The pre-execution region -- everything up to and including the last v_pre
      assignment STATEMENT, terminating semicolon included -- names no column of
      proof.action_executions.
   b. No function reachable from that region OR from the returned eligibility
      expression, in ANY schema, transitively, names one either.
   c. The function builds no dynamic SQL. EXECUTE is refused rather than
      scanned: literals are blanked before token-scanning (they must be -- the
      reason strings name the executed action), which is exactly what would hide
      a read, and a literal can be assembled at runtime from text no static scan
      can follow.
   d. The returned eligibility expression names nothing but v_pre and pure
      array/boolean constructs. An allowlist, because a local boolean loaded from
      the execution record is neither an execution token nor a missing v_pre.

2. Behavioral. A read-only scan for proposals the function calls eligible while
   the underlying row contradicts an eligibility requirement. This is a SUBSET
   invariant, deliberately not a reimplementation of the verdict: a twin would
   drift, and a gate that recomputes what it judges cannot fail (the
   gate-self-reference-fail-open hazard).

The function absent -> BLOCKED, never FAIL: the subject under test is not built
yet, reported honestly.
"""

from __future__ import annotations

from pathlib import Path
import re
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
)

GATE_ID = "G-34"
TITLE = "Retroactive-safety separation in the autonomy verdict"

SUBJECT = "autonomy_readiness"
PRE_ACCUMULATOR = "v_pre"

# HARDCODED LITERALS, deliberately. Deriving this list from
# proof.action_executions' catalog entry would mean a DROPped table yields an
# empty token list and a vacuous pass -- the gate-self-reference-fail-open
# hazard. If a column is added to the execution record that the pre-execution
# branch must also not read, add it here by hand.
EXECUTION_TOKENS = (
    "action_executions",
    "v_exec",
    "fingerprint_matches",
    "observed_fingerprint",
    "observed_index_definition",
    "wave_b_ingest_id",
    "wave_b_capture_id",
)

# Every bare word in the returned eligibility expression must appear here. The
# shipped expression is `(array_length(v_pre, 1) IS NULL)`, so the allowlist is
# v_pre plus the pure constructs that expression uses. Anything else -- a local
# boolean, an output column, another function call -- fails the gate, because a
# value loaded from the execution record earlier in the body is neither an
# execution token nor a missing v_pre and would otherwise pass both other checks.
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
ELIGIBILITY_ALLOWED = frozenset(
    {PRE_ACCUMULATOR, "array_length", "cardinality", "coalesce",
     "is", "null", "not", "and", "or", "true", "false"}
)

# EVERY schema, not just 'proof'. MEASURED DEFEAT of the earlier 'proof'-only
# version: a helper defined as public.sneaky_lookup(uuid) that reads
# proof.action_executions is invisible to a walk that only knows proof.* names, so
# the gate returned PASS on a real retroactive-safety violation. The walk also
# needs pronamespace back to fetch the right body, since two schemas may define
# the same proname.
ALL_FUNCTIONS = """
SELECT n.nspname, p.proname
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND p.prokind = 'f'
"""

FUNCTION_SRC_QUALIFIED = """
SELECT p.prosrc
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = %s AND p.proname = %s
"""

# Rows the verdict calls eligible while the row itself contradicts requirement
# 3, 4, or 5. Any row returned here is a contradiction between the verdict and
# the data, whichever one is wrong.
CONTRADICTION_SCAN = """
SELECT p.proposal_id,
       (btrim(coalesce(p.rollback_sql, '')) = ''
        AND btrim(coalesce(p.rollback_guidance, '')) = '')  AS no_rollback,
       (jsonb_array_length(p.preconditions) = 0)            AS no_preconditions,
       (p.statement_timeout IS NULL OR p.lock_timeout IS NULL) AS unbounded
FROM proof.action_proposals p
CROSS JOIN proof.autonomy_readiness(p.proposal_id) v
WHERE v.pre_execution_eligible
  AND ((btrim(coalesce(p.rollback_sql, '')) = ''
        AND btrim(coalesce(p.rollback_guidance, '')) = '')
       OR jsonb_array_length(p.preconditions) = 0
       OR p.statement_timeout IS NULL
       OR p.lock_timeout IS NULL)
"""


def strip_comments(body: str) -> str:
    """Remove block and line comments only.

    A comment that merely NAMES an execution column is not a read of one, and the
    function's own reason string mentions the executed action. Scanning raw prosrc
    flags both.
    """
    body = re.sub(r"/\*.*?\*/", " ", body, flags=re.S)
    return re.sub(r"--[^\n]*", " ", body)


def blank_literals(body: str) -> str:
    """Replace single-quoted literals with empty ones.

    Needed because the function's own reason strings name the executed action, and
    a literal is not code. Kept SEPARATE from strip_comments: the caller scans the
    literal-bearing text too, since a literal is exactly where dynamic SQL hides.
    """
    return re.sub(r"'(?:[^']|'')*'", " '' ", body)


def declare_and_body(src: str) -> tuple[str, str]:
    """Split the DECLARE section from the executable body.

    `v_exec proof.action_executions%ROWTYPE` is a DECLARATION, not a read.
    Without this split the gate flags the correct function.
    """
    match = re.search(r"\bBEGIN\b", src, re.I)
    if not match:
        return "", src
    return src[: match.start()], src[match.end():]


def split_top_level(select_list: str) -> list[str]:
    """Split a SELECT list on commas OUTSIDE parentheses.

    A bare `.split(",")` here was measured wrong, and it disarmed the single
    most important assertion in this gate. The correct first returned column is
    `(array_length(v_pre, 1) IS NULL)`, whose own comma truncates it to
    `(array_length(v_pre` -- so an injected `OR v_exec.fingerprint_matches`
    fell outside the inspected text and the gate passed on the exact defect it
    exists to catch. Do not simplify this back.
    """
    columns: list[str] = []
    depth = 0
    current: list[str] = []
    for char in select_list:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            columns.append("".join(current))
            current = []
            continue
        current.append(char)
    columns.append("".join(current))
    return columns


def token_hits(text: str) -> list[str]:
    """Execution-record tokens appearing in ``text`` as whole words."""
    return [
        token
        for token in EXECUTION_TOKENS
        if re.search(rf"\b{re.escape(token)}\b", text, re.I)
    ]


def pre_region(body: str) -> str:
    """``body`` up to the END OF THE LAST ``v_pre`` assignment STATEMENT.

    Cutting at the end of the `:=` OPERATOR was measured wrong, and it left the
    most natural hiding place in the function outside the inspected text -- the
    right-hand side of the very last assignment::

        v_pre := CASE WHEN EXISTS (SELECT 1 FROM proof.action_executions
                                   WHERE proposal_id = p_proposal_id
                                     AND fingerprint_matches)
                      THEN '{}'::text[] ELSE v_pre END;

    That is a post-execution read deciding the pre-execution verdict, and the
    gate reported PASS on it, twice: once with the read inline and once behind
    `public.sneaky_lookup(...)`. The region now extends to the terminating
    semicolon, so the assigned expression is inspected along with everything
    before it.

    The semicolon scan is depth-aware because a `SELECT` inside the assigned
    expression may carry its own parenthesised subquery, and a `$$`-quoted body
    cannot contain a bare unquoted `;` at depth 0 before the statement ends.
    Falling back to the whole body when no terminator is found is deliberate:
    over-inspecting risks a false FAIL that a human reads, while
    under-inspecting risks a false PASS that nobody sees.
    """
    assigns = list(re.finditer(rf"\b{PRE_ACCUMULATOR}\s*:=", body, re.I))
    if not assigns:
        return body
    depth = 0
    for index in range(assigns[-1].end(), len(body)):
        char = body[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == ";" and depth <= 0:
            return body[: index + 1]
    return body


def analyse(conn, schema: str, name: str) -> dict:
    """Fetch ``schema.name``'s body and locate its pre-execution region.

    Returns both the literal-blanked text (for token scanning, so the function's
    own reason strings do not self-flag) and the literal-BEARING text (so the
    caller can scan inside literals, which is where dynamic SQL hides).
    """
    row = conn.execute(FUNCTION_SRC_QUALIFIED, (schema, name)).fetchone()
    if row is None:
        return {"missing": True}
    commentless = strip_comments(row[0])
    _declare, with_literals = declare_and_body(commentless)
    body = blank_literals(with_literals)
    assigns = list(re.finditer(rf"\b{PRE_ACCUMULATOR}\s*:=", body, re.I))
    return {
        "missing": False,
        "assign_count": len(assigns),
        "body": body,
        "body_with_literals": with_literals,
        "pre_region": pre_region(body),
        # The SAME cut applied to the literal-bearing text, recomputed on that
        # text -- NOT the blanked text's offset reused. MEASURED DEFEAT: blanking
        # shortens the string, so every offset after the first literal points
        # earlier in the literal-bearing version. An `EXECUTE`-free read hidden in
        # a literal after a long earlier literal fell outside the reused slice and
        # the gate reported PASS. Two texts, two cuts, one rule.
        "pre_region_with_literals": pre_region(with_literals),
    }


def called_functions(conn, body: str) -> set[tuple[str, str]]:
    """Every user-defined function ``body`` calls, as ``(schema, name)`` pairs.

    Two MEASURED DEFEATS of the earlier version are closed here:

    1. It matched only calls spelled ``proof.<name>(`` and listed only names from
       the ``proof`` schema. ``public.sneaky_lookup(p_proposal_id)``, reading
       proof.action_executions on the caller's behalf, was invisible and the gate
       reported PASS. The name is now matched with an OPTIONAL schema qualifier
       against every user-defined function in the database, so both
       ``public.sneaky_lookup(...)`` and a bare ``sneaky_lookup(...)`` resolved
       through search_path are discovered.
    2. Discovery returned bare names, so two schemas defining the same proname
       were indistinguishable and the wrong body could be fetched. Pairs now.

    One level is not enough: a helper called from the pre-execution region can
    read the execution record on the caller's behalf, which is the same defect
    wearing a different hat.
    """
    return {
        (schema, name)
        for schema, name in conn.execute(ALL_FUNCTIONS).fetchall()
        if re.search(
            rf"\b(?:[a-z_][a-z0-9_]*\s*\.\s*)?{re.escape(name)}\s*\(", body, re.I
        )
    }


def dynamic_sql_defect(label: str, body: str) -> str | None:
    """``EXECUTE`` anywhere in ``body`` is a defect, not something to scan.

    MEASURED DEFEAT of the earlier version, which had no such check::

        v_sql := 'SELECT bool_or(fingerprint_matches) FROM
                  proof.action_executions WHERE proposal_id = $1';
        EXECUTE v_sql INTO v_flag USING p_proposal_id;
        IF v_flag THEN v_pre := '{}'; END IF;

    The gate blanks string literals before token-scanning -- it must, because
    the function's own reason strings name the executed action -- and that is
    exactly what let this read hide. Scanning inside literals instead is not a
    fix either: a literal can be assembled from concatenated fragments,
    fetched from a table, or passed in as a parameter, and no static scan can
    follow that. So the construct is REFUSED rather than verified. A gate that
    cannot prove a property must say so, not pass.
    """
    if re.search(r"\bEXECUTE\b", body, re.I):
        return (
            f"{label} builds dynamic SQL (EXECUTE ...); a string literal can "
            "carry an execution-record read that no static scan can prove "
            "absent, so this gate refuses the construct instead of pretending "
            "to verify it"
        )
    return None


def literal_token_defect(
    label: str, blanked: str, with_literals: str
) -> str | None:
    """Execution tokens that appear ONLY inside string literals in ``label``.

    Belt to the EXECUTE ban's braces. Not sufficient on its own (see
    dynamic_sql_defect), but it catches the lazy version of the same trick and
    costs one extra regex pass. Tokens already reported from the blanked text
    are excluded so a single read is not reported twice.
    """
    already = set(token_hits(blanked))
    extra = [t for t in token_hits(with_literals) if t not in already]
    if extra:
        return (
            f"a string literal in {label} names the execution record: "
            + ", ".join(extra)
        )
    return None


def static_problems(conn) -> tuple[list[str], dict, list[str]]:
    """Return (problems, subject analysis, qualified helper names checked)."""
    subject = analyse(conn, "proof", SUBJECT)
    if subject["missing"]:
        return [], subject, []

    problems: list[str] = []
    if subject["assign_count"] == 0:
        problems.append(
            f"no {PRE_ACCUMULATOR} assignment found; the pre-execution region "
            "cannot be located, so this gate can prove nothing about it"
        )
    hits = token_hits(subject["pre_region"])
    if hits:
        problems.append(
            "the pre-execution region reads the execution record: "
            + ", ".join(hits)
        )
    # The EXECUTE ban covers the WHOLE body, not just the pre-execution region.
    # An `EXECUTE ... INTO v_flag` placed AFTER the last v_pre assignment cannot
    # change v_pre, but `... OR v_flag` in the returned column reaches the same
    # verdict, and v_flag is not an execution token.
    for defect in (
        dynamic_sql_defect("proof.autonomy_readiness()", subject["body"]),
        literal_token_defect(
            "the pre-execution region",
            subject["pre_region"],
            subject["pre_region_with_literals"],
        ),
    ):
        if defect:
            problems.append(defect)

    returned = re.search(
        r"RETURN\s+QUERY\s+SELECT(.*?);", subject["body"], re.I | re.S
    )
    first = ""
    if returned is None:
        problems.append(
            "no `RETURN QUERY SELECT ...;` found; this gate reads the returned "
            "eligibility expression textually and cannot verify another return "
            "style -- change the gate deliberately, do not leave it silent"
        )
    else:
        first = split_top_level(returned.group(1))[0]
        if PRE_ACCUMULATOR not in first.lower():
            problems.append(
                "the first returned column is not derived from "
                f"{PRE_ACCUMULATOR}: {first.strip()!r}"
            )
        first_hits = token_hits(first)
        if first_hits:
            problems.append(
                "the returned eligibility expression reads the execution "
                "record: " + ", ".join(first_hits)
            )
        # `v_pre` present and no execution token present is NOT enough. A local
        # boolean loaded from the execution record earlier in the body launders
        # the read past both checks:
        #   v_flag := (SELECT bool_or(fingerprint_matches) FROM ...);
        #   RETURN QUERY SELECT (array_length(v_pre, 1) IS NULL) OR v_flag, ...
        # `v_flag` is not an execution token and `v_pre` is still present, so
        # both existing checks pass while the verdict is retroactive.
        #
        # ALLOWLIST, not a denylist. A denylist of declared locals was written
        # first and is unsound: PL/pgSQL's assignable names are not confined to
        # the DECLARE section -- this function's own RETURNS TABLE columns
        # (pre_execution_eligible, post_execution_validated) are assignable
        # variables too, and neither is declared anywhere the gate could read.
        # Widening this set is a deliberate gate change, not a formality.
        strays = sorted(
            {
                m.group(0).lower()
                for m in IDENTIFIER.finditer(first)
                if m.group(0).lower() not in ELIGIBILITY_ALLOWED
            }
        )
        if strays:
            problems.append(
                "the returned eligibility expression names something other "
                f"than {PRE_ACCUMULATOR} and pure array/boolean constructs, "
                "which is how a post-execution read gets laundered past the "
                "token scan: " + ", ".join(strays) + " -- if this is a "
                "legitimate rewrite, widen ELIGIBILITY_ALLOWED deliberately"
            )

    # Seed from the pre-execution region AND the returned expression. MEASURED
    # DEFEAT of the earlier pre-region-only seeding: a helper called only from
    # the `RETURN QUERY SELECT` -- `... OR proof.silently_override(p_proposal_id)`
    # -- was never walked, and the gate reported PASS on a genuine
    # retroactive-safety violation.
    checked: set[tuple[str, str]] = set()
    frontier = called_functions(conn, subject["pre_region"]) | called_functions(
        conn, first
    )
    while frontier:
        schema, name = frontier.pop()
        if (schema, name) in checked or (schema, name) == ("proof", SUBJECT):
            continue
        checked.add((schema, name))
        inner = analyse(conn, schema, name)
        if inner["missing"]:
            continue
        qualified = f"{schema}.{name}()"
        inner_hits = token_hits(inner["body"])
        if inner_hits:
            problems.append(
                f"{qualified}, reachable from the eligibility derivation, "
                "reads the execution record: " + ", ".join(inner_hits)
            )
        for defect in (
            dynamic_sql_defect(f"{qualified}, reachable from the eligibility "
                               "derivation,", inner["body"]),
            literal_token_defect(
                qualified, inner["body"], inner["body_with_literals"]
            ),
        ):
            if defect:
                problems.append(defect)
        frontier |= called_functions(conn, inner["body"])

    return problems, subject, [f"{s}.{n}" for s, n in sorted(checked)]


def run() -> int:
    print_header(GATE_ID, TITLE)
    dsn = read_env_value("DATABASE_URL")
    if not dsn:
        return finish(GATE_ID, BLOCKED, "DATABASE_URL is not configured")
    print(f"  database: {redact_dsn(dsn)}")

    try:
        import psycopg
    except ModuleNotFoundError:
        return finish(GATE_ID, BLOCKED, "psycopg is not installed")

    with psycopg.connect(dsn, autocommit=True) as conn:
        problems, subject, checked = static_problems(conn)
        if subject["missing"]:
            return finish(
                GATE_ID,
                BLOCKED,
                "proof.autonomy_readiness() does not exist; apply "
                "sql/13_supervised_execution.sql",
            )
        contradictions = conn.execute(CONTRADICTION_SCAN).fetchall()
        for row in contradictions:
            problems.append(
                f"proposal {row[0]} is reported eligible while the row "
                f"contradicts it (no_rollback={row[1]}, "
                f"no_preconditions={row[2]}, unbounded_timeout={row[3]})"
            )

    for problem in problems:
        print(f"  DEFECT: {problem}")
    if problems:
        return finish(
            GATE_ID, FAIL, f"{len(problems)} retroactive-safety defect(s)"
        )
    return finish(
        GATE_ID,
        PASS,
        f"pre-execution region clean ({subject['assign_count']} "
        f"{PRE_ACCUMULATOR} assignments, helpers checked: "
        f"{checked or 'none'}); contradiction scan clean",
    )


if __name__ == "__main__":
    main_guard(run)
```

- [ ] **Step 2: Run it and confirm it BLOCKS before A5's schema exists, then
  PASSES after.**

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python gates/retroactive_safety.py; echo "exit=$?"
```

Expected before `sql/13_supervised_execution.sql` is applied: `exit=2`,
`[BLOCKED] G-34: proof.autonomy_readiness() does not exist; apply
sql/13_supervised_execution.sql`. Expected after: `exit=0` with the assignment
count and the helper list printed. On the reference prototype the PASS line read:

```
[PASS] G-34: pre-execution region clean (8 v_pre assignments, helpers checked:
['proof.validate_answer_citations']); contradiction scan clean
```

  Both values are measured, not illustrative: `static_problems()` returned
  `assign_count = 8` and `['proof.validate_answer_citations']` when run against
  A5's real function body on 2026-08-04. Names are schema-qualified because the
  walk enumerates every schema.

  `helpers checked: ['proof.validate_answer_citations']` is not decoration. It is
  the evidence that the transitive walk found and inspected the one helper the
  eligibility derivation actually calls. An empty list here on the real schema
  means the call-detection regex stopped matching, and the transitive half of the
  gate has silently disarmed.

- [ ] **Step 3: Prove it can go red — ten regressions, each measured.** A gate
  never seen red is not evidence. Each regression below was run against A5's real
  function body; the measured exit code and the named defect are the acceptance
  criteria. Apply one, run the gate, confirm the result, then restore the correct
  function before the next.

  **R1–R6 were measured against a real PostgreSQL 17 server holding A5's
  function. R7–R10 were measured on 2026-08-04 by feeding crafted `prosrc`
  through the gate's own `static_problems()` with a stub connection** — no
  database, because each one only needs a function body, and a defeat that
  reproduces without a server is cheaper to keep in CI. Every R7–R10 case was
  first confirmed to return **PASS against the pre-fix gate**, which is what
  makes them evidence rather than decoration. The same harness confirms the real
  shipped body still PASSES with `assign_count = 8` and
  `helpers walked = ['proof.validate_answer_citations']`.

  **R1 — the pre-execution branch reads the execution record directly.** Move the
  execution `SELECT ... INTO v_exec` above the post-execution branch and add
  `IF v_exec.fingerprint_matches IS TRUE THEN v_pre := '{}'; END IF;`.
  Measured: `exit=1`, `DEFECT: the pre-execution region reads the execution
  record: action_executions, v_exec, fingerprint_matches`.

  **R2 — a helper reads it on the caller's behalf.** Create
  `proof.looks_safe(uuid)` returning
  `bool_or(fingerprint_matches) FROM proof.action_executions`, and call it from
  inside the pre-execution region. Measured: `exit=1`, `DEFECT:
  proof.looks_safe(), reachable from the eligibility derivation, reads the
  execution record: action_executions, fingerprint_matches`. This is the
  regression a one-level scan misses entirely.

  **R3 — the returned eligibility expression ORs in the post verdict.** Change
  the first returned column to
  `(array_length(v_pre, 1) IS NULL OR v_exec.fingerprint_matches)`. Measured:
  `exit=1`, `DEFECT: the returned eligibility expression reads the execution
  record: v_exec, fingerprint_matches`. **This is the regression the first
  version of this gate passed.** If a future edit to `split_top_level()` makes R3
  go green, that edit is wrong.

  **R4 — the function is absent.** `DROP FUNCTION
  proof.autonomy_readiness(uuid);`. Measured: `exit=2` (BLOCKED, not FAIL) with
  the apply-the-schema message. BLOCKED is correct: there is nothing to judge.

  **R5 — the execution `SELECT` is hoisted above the pre-checks without `v_pre`
  reading it.** Measured: `exit=1`, `DEFECT: the pre-execution region reads the
  execution record: action_executions, v_exec`. This is intentional, not a false
  positive: the gate enforces structural separation, which is stronger than data
  flow and far cheaper to keep true. A reviewer who calls this a false positive
  has misread the invariant.

  **R6 — requirement 5 deleted from the function (the behavioral half).** Remove
  the rollback-guidance check, then store a proposal with no `rollback_sql` and
  no `rollback_guidance`. The static half stays clean — nothing reads the
  execution record — and the contradiction scan catches it. Measured: `exit=1`,
  `DEFECT: proposal <uuid> is reported eligible while the row contradicts it
  (no_rollback=True, no_preconditions=False, unbounded_timeout=False)`.

  **R7 — a helper called ONLY from the returned eligibility expression.** Add
  `proof.silently_override(uuid)` returning
  `EXISTS (SELECT 1 FROM proof.action_executions WHERE proposal_id = p_id AND
  fingerprint_matches)`, and change the first returned column to
  `(array_length(v_pre, 1) IS NULL) OR proof.silently_override(p_proposal_id)`.
  Measured: two defects, `the returned eligibility expression names something
  other than v_pre and pure array/boolean constructs ... p_proposal_id, proof,
  silently_override` and `proof.silently_override(), reachable from the
  eligibility derivation, reads the execution record: action_executions,
  fingerprint_matches`. **The pre-fix gate returned PASS**: it seeded the walk
  from the pre-execution region only, so a helper reached exclusively through the
  `RETURN QUERY SELECT` was never opened.

  **R8 — the read hidden in dynamic SQL.** Replace the pre-check with
  `v_sql := 'SELECT bool_or(fingerprint_matches) FROM proof.action_executions
  WHERE proposal_id = $1'; EXECUTE v_sql INTO v_flag USING p_proposal_id;
  IF v_flag THEN v_pre := '{}'; END IF;`. Measured: `proof.autonomy_readiness()
  builds dynamic SQL (EXECUTE ...)` plus `a string literal in the pre-execution
  region names the execution record`. **The pre-fix gate returned PASS**, and it
  had to: it blanked string literals before token-scanning — which it must, since
  the function's own reason strings name the executed action — and that blanking
  is exactly what hid this read.

  **R9 — a helper in a non-`proof` schema.** Define
  `public.sneaky_lookup(uuid)` with the same body as R7's helper and call it from
  the pre-execution region. Measured: `public.sneaky_lookup(), reachable from the
  eligibility derivation, reads the execution record: action_executions,
  fingerprint_matches`. **The pre-fix gate returned PASS**: it listed candidate
  names from `nspname = 'proof'` and matched only calls spelled `proof.<name>(`,
  so a helper anywhere else was invisible.

  **R10 — the read laundered through a local boolean.** Keep the pre-execution
  region clean, then after the last `v_pre` assignment add
  `SELECT bool_or(fingerprint_matches) INTO v_flag FROM proof.action_executions
  WHERE proposal_id = p_proposal_id;` and return
  `(array_length(v_pre, 1) IS NULL) OR v_flag`. Measured: `the returned
  eligibility expression names something other than v_pre and pure array/boolean
  constructs ... v_flag`. **The pre-fix gate returned PASS**: `v_pre` was present
  and `v_flag` is not an execution token, so both existing checks were satisfied
  while the verdict was fully retroactive. This is why the eligibility column is
  checked against an ALLOWLIST (`ELIGIBILITY_ALLOWED`) rather than a denylist of
  declared locals — a denylist was written first and is unsound, because
  PL/pgSQL's assignable names include the `RETURNS TABLE` output columns, which
  appear in no `DECLARE` section the gate can read.

  Two further defeats were found and closed while measuring R7–R10, and they are
  the reason `pre_region()` is a function rather than a slice:

  - **The right-hand side of the LAST `v_pre` assignment sat outside the
    inspected region**, because the cut was taken at the end of the `:=`
    *operator*. So
    `v_pre := CASE WHEN EXISTS (SELECT 1 FROM proof.action_executions ...) THEN
    '{}'::text[] ELSE v_pre END;` — a post-execution read deciding the
    pre-execution verdict — was never scanned, and the gate reported PASS on it
    both inline and behind a helper. The region now runs to the terminating
    semicolon. Side effect worth noting: before this fix the gate reported
    `helpers walked: none` on the real body, because
    `proof.validate_answer_citations()` is called inside the final assignment's
    own statement. The non-empty helper list in step 2's expected output is
    therefore load-bearing evidence for THIS fix, not just for the regex.
  - **The literal-bearing slice reused an offset computed on the blanked
    text.** Blanking shortens the string, so every offset after the first
    literal pointed earlier in the literal-bearing copy, and a token-naming
    literal placed after a long earlier literal fell outside the slice. Two
    texts now get two independently computed cuts through the same
    `pre_region()`.

  R1–R5 and R7–R10 exercise the static half; R6 is the only one that exercises
  the behavioral half. Both halves must be shown red, or half the gate is
  unproven.

- [ ] **Step 4: Register it and run the core gates.** Add to
  `gates/checks.sh`'s `CORE_GATES` array:

```bash
  "G-34|retroactive_safety.py|Retroactive-safety separation in the autonomy verdict"
```

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  gates/checks.sh
```

Expected: every previously-registered gate behaves as before, and G-34 reports
PASS. The default `gates/checks.sh` run forces `WORKBENCH_SECURITY_ENABLED=0` and
runs core only, so G-34 must not depend on the security module being enabled — it
does not: `proof.autonomy_readiness()` is created by
`sql/13_supervised_execution.sql`, which is in `CORE_SQL_FILES` per A5 step 14,
not in the security module.

- [ ] **Step 5: Live-Aurora acceptance criteria.** Against the disposable
  `dat410_review_remediation_test` database on the real cluster:
  1. G-34 PASSES with a non-empty `helpers checked` list.
  2. All ten regressions in step 3 reproduce their measured exit codes and named
     defects on Aurora, not only on a local server or through the stub-connection
     harness.
  3. `gates/checks.sh` exits 0 with G-34 registered.
  4. Running G-34 against a database with proposals but no executions still
     PASSES — an unexecuted proposal is the normal pre-Lab-4 state, not a defect.

- [ ] **Step 6: Cleanup and failure recovery.** The gate writes nothing, so there
  is nothing to clean up from a normal run. Step 3's regressions replace the
  function body: after each one, re-apply `sql/13_supervised_execution.sql` to
  restore it, and confirm G-34 returns to PASS before moving on. R6 also leaves a
  rollback-less proposal row behind; delete that row, or reset the `_test`
  database with `make schema`, so the contradiction scan is clean for the next
  gate run. R7 and R9 additionally create helper functions — `DROP FUNCTION
  proof.silently_override(uuid)` and `DROP FUNCTION public.sneaky_lookup(uuid)`.
  Leaving either behind is not cosmetic: `called_functions()` now enumerates every
  user-defined function in the database, so an abandoned helper stays a discovery
  candidate for every later run.

- [ ] **Step 7: Participant-facing changes.** None — gates are facilitator and CI
  tooling. The participant sees the *result* of this invariant in Lab 4's verdict
  panel (Task E4), never the gate.

- [ ] **Step 8: Commit.**

```bash
git add gates/retroactive_safety.py gates/checks.sh
git commit -m "Add G-34 retroactive-safety gate for the autonomy verdict"
```

**Dependencies:** Task A5 (the gate judges A5's function; before A5 it correctly
reports BLOCKED, which is a useful state to have registered but not a substitute
for A5 landing).

---

## Phase B — Orchestration

Owning module: `labs/incident/` plus two new lab-only routes in `backend/app/`.
This phase replaces the incident-generation code path entirely. It is a
replacement, not an incremental patch (see the design spec's Out of Scope
section). **Both hard contracts HC-1 and HC-2 above are binding on Tasks B2 and
B3 and must be verified by the reviewer, not assumed.** Task B1a causes the
incident; B2 collides with it; B3 proves the collision; B4 verifies recovery; B5
measures the plan regression; B6 deletes the replaced mechanism's observability
path and its stale tests.

### Task B1: Bootstrap the 3,000,000-row lab workload

**Owning schema/module:** `workbench_lab` schema; `labs/incident/run_live_workshop.py`.

**Files:**
- Modify: `labs/incident/run_live_workshop.py:163-222` (`_create_lab_workload`) and
  the `LAB_ROWS` constant
- Modify: `labs/incident/prepare_workload.py` — update the pre-session bootstrap
  description to 3,000,000 orders
- Modify: `backend/tests/test_incident_lab.py:48`
  (`self.assertEqual(LAB_ROWS, 25_000)`)
- Test: `backend/tests/test_incident_lab.py`

**Interfaces:**
- Consumes: nothing from Phase A (this task touches only `workbench_lab`).
- Produces: `workbench_lab.orders` with 3,000,000 rows, columns
  `(order_id bigint PRIMARY KEY, customer_id bigint, status text NOT NULL,
  created_at timestamptz NOT NULL)` and **no** `priority_tier` column — Task B1a's
  `add_priority_tier_column` adds it, as part of the migration that causes the
  incident. `workbench_lab.customers` stays at 5,000 rows. Tasks B1a, B2, B3, and
  B5 all target this exact shape.

**Migration and compatibility implications:** `LAB_ROWS` moves 25,000 →
3,000,000, a 120× increase. Measured bootstrap cost on `db.r8g.2xlarge` is 27.6s
(design spec's New 3M-Row baseline), which is **pre-session Workshop Studio
provisioning time**, explicitly outside the 5–8 minute participant ceiling per
Global Constraints — but Task F2 must move it into provisioning, or Lab 1 silently
absorbs 28 seconds. `_create_lab_workload` already uses
`DROP SCHEMA IF EXISTS workbench_lab CASCADE` (Gate 4 proved this rebuild is clean
from arbitrary dirty state), so re-running is safe and no migration path is
needed. The `generate_series` inserts use doubled `%%` because the SQL is passed
through Python `%`-formatting — preserve that or the insert fails with a
parameter-binding error at 3M scale, wasting a full bootstrap cycle.
`ANALYZE` at the end of bootstrap is **required**: without it the Task B5 query
regression measures a cold-statistics artifact instead of the real missing-index
finding.

**Do not change `_create_lab_workload`'s ownership model here.** Task D3 step 3a
changes how the schema and tables are owned (`CREATE SCHEMA ... AUTHORIZATION
workbench_lab_owner`, tables created under that role) so the participant can run
Lab 4's `CREATE INDEX`, which requires table ownership rather than any grantable
privilege. That change is D3's because D3 owns the role it depends on; this task
changes only `LAB_ROWS` and the column shape. If you are executing B1 after D3,
keep D3's ownership block intact — re-flattening it back to a bare `CREATE SCHEMA`
silently breaks Lab 4.

- [ ] **Step 1: Write the failing test.** In `backend/tests/test_incident_lab.py`,
  replace the `LAB_ROWS` assertion:

```python
    def test_lab_workload_is_three_million_orders(self) -> None:
        self.assertEqual(LAB_ROWS, 3_000_000)
        self.assertEqual(LAB_CUSTOMERS, 5_000)
        source = (REPO_ROOT / "labs" / "incident" / "run_live_workshop.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("DROP SCHEMA IF EXISTS workbench_lab CASCADE", source)
        self.assertNotIn("priority_tier", source.split("def _create_lab_workload")[1].split("def ")[0])
```

- [ ] **Step 2: Run it and confirm it fails.**

```bash
.venv/bin/python -m pytest backend/tests/test_incident_lab.py::IncidentLabTests::test_lab_workload_is_three_million_orders -v
```

Expected: FAIL — `25000 != 3000000`.

- [ ] **Step 3: Change the constant and confirm the DDL shape.** Set
  `LAB_ROWS = 3_000_000` in `labs/incident/run_live_workshop.py`. In
  `_create_lab_workload`, confirm `workbench_lab.orders` is created **without**
  `priority_tier` (the migration adds it) and that the function ends with
  `ANALYZE workbench_lab.orders`. Keep the doubled `%%` in the `generate_series`
  inserts exactly as-is.

- [ ] **Step 4: Run the test again.**

```bash
.venv/bin/python -m pytest backend/tests/test_incident_lab.py -v
```

Expected: PASS on the new test. The old-mechanism tests at
`backend/tests/test_incident_lab.py:27-37` (file-set assertion) and `:39-43`
(`OBSERVATION_COUNT`/`WRITER_COUNT`/`READER_COUNT`) and `:86-131` (lock-vocabulary
string literals) will fail — they describe the mechanism being replaced. Task B6
rewrites them; note the failures and move on rather than deleting assertions to
get green.

- [ ] **Step 5: Live-Aurora acceptance criteria.** Bootstrap against the
  disposable database and confirm both row counts, the absence of
  `priority_tier`, and that bootstrap completes in under 60 seconds (measured
  27.6s; 60s is the acceptance bound, not the target):

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python -c "
import time, psycopg
from backend.app.config import get_settings
dsn = get_settings().database_url
with psycopg.connect(dsn, autocommit=True) as conn:
    name = conn.execute('SELECT current_database()').fetchone()[0]
    assert name.endswith('_test'), f'SAFETY ABORT: {name}'
    print('database:', name)
"
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python -m labs.incident.run_live_workshop --bootstrap-only
psql -X -v ON_ERROR_STOP=1 \
  "postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" <<'SQL'
SELECT (SELECT count(*) FROM workbench_lab.orders) AS orders,
       (SELECT count(*) FROM workbench_lab.customers) AS customers,
       to_regclass('workbench_lab.orders') IS NOT NULL AS table_present,
       (SELECT count(*) FROM information_schema.columns
        WHERE table_schema='workbench_lab' AND table_name='orders'
          AND column_name='priority_tier') AS priority_tier_cols;
SQL
```

Expected: `orders = 3000000`, `customers = 5000`, `table_present = t`,
`priority_tier_cols = 0`.

- [ ] **Step 6: Cleanup and failure recovery.** A failed or interrupted bootstrap
  leaves a partial `workbench_lab`; the next run's `DROP SCHEMA ... CASCADE`
  clears it (Gate 4's `probe_rerun_against_dirty_state` proved this against a
  deliberately non-canonical prior state). If a SIGKILLed bootstrap left an open
  server-side transaction, terminate it by tag — never by killing all backends:

```bash
psql -X -v ON_ERROR_STOP=1 \
  "postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" <<'SQL'
DO $guard$ BEGIN
  IF current_database() <> 'dat410_review_remediation_test' THEN
    RAISE EXCEPTION 'SAFETY ABORT: connected to %', current_database();
  END IF;
END $guard$;
SELECT pg_terminate_backend(pid), application_name
FROM pg_stat_activity
WHERE application_name LIKE 'workbench-live-%'
  AND datname = current_database()   -- pg_stat_activity is CLUSTER-wide
  AND pid <> pg_backend_pid();
SQL
```

  **`datname = current_database()` is required, not defensive.** `pg_stat_activity`
  shows every session on the whole cluster, and `dat410_live` shares this cluster
  and uses the same `workbench-live-%` tag. Without that predicate this statement
  terminates a live workshop participant's sessions from a test-database
  connection, and the `DO $guard$` block above cannot prevent it — the guard
  checks which database you are connected to, not which sessions you reach.

  `_assert_no_live_lab_sessions` (`run_live_workshop.py:131-145`) already refuses
  to start when tagged sessions exist, so a leaked session fails the next run
  loudly instead of corrupting it. To reclaim disk after a rehearsal, drop the
  schema **explicitly** — Task C2 step 3a inverts the cleanup flag, so a plain run
  now retains the table (Labs 2–4 need it) and reclaiming requires
  `--drop-lab-schema`. 3,000,000 rows is real storage, not a rounding error.

- [ ] **Step 7: Participant-facing changes.** The table the participant queries in
  every lab is now 3,000,000 rows instead of 25,000. Any participant-facing text
  stating the row count must change, including the sibling repo's
  `FinalValidation`/`InitializeSchema` assertions of 5000/25000 — those are
  user-owned CloudFormation, so produce the exact diff here and hand it to Task F2's
  sibling-repo handoff rather than editing the sibling repo from this worktree.

- [ ] **Step 8: Commit.**

```bash
git add labs/incident/run_live_workshop.py backend/tests/test_incident_lab.py
git commit -m "Bootstrap the lab workload at three million orders"
```

**Dependencies:** none (Phase A is database-contract work; this is workload work).

### Task B1a: Implement the migration driver and retire the old hold mechanism

**Owning schema/module:** `labs/incident/`; new `labs/incident/migration.py`.

**Files:**
- Create: `labs/incident/migration.py`
- Modify: `labs/incident/run_live_workshop.py:414-435` (`_hold_unsafe_index`),
  `:437-455` (`_blocked_writer`), `:457-` (`_active_reader`) — delete all three,
  plus the thread wiring at `:637`
- Test: `backend/tests/test_incident_lab.py`

**Interfaces:**
- Consumes: Task B1's `workbench_lab.orders` at 3,000,000 rows with **no**
  `priority_tier` column.
- Produces:
  - `add_priority_tier_column(conn) -> None` — commits
    `ALTER TABLE workbench_lab.orders ADD COLUMN priority_tier int` as its own
    statement.
  - `open_backfill(database_url) -> BackfillHandle`, where `BackfillHandle` carries
    `pid: int`, `duration_seconds: float`, `rows_updated: int`, and
    `commit()` / `abort()` methods. The transaction is **left open** on return.
  - Task B3 consumes `handle.pid` as its `backfill_pid`; Task B4 calls
    `handle.commit()` before verifying; Task B5 needs the column this task adds.

**Migration and compatibility implications:** this is the task that actually causes
the incident, and three separate correctness requirements live here.

**First, the `ADD COLUMN` must commit separately from the backfill.** If one
explicit transaction spans both, it retains the `AccessExclusiveLock` from the
`ALTER TABLE` for the backfill's full ~22 seconds, and every hot writer then blocks
on a *relation* lock rather than a *row* lock. That produces
`wait_event = 'Lock:relation'`, not `'Lock:transactionid'` — a different incident
with a different diagnosis, and one the Task B3 hold controller's proving condition
would reject. The separation is the mechanism, not a style choice.

**Second, the backfill's transaction must stay open across a function return.**
`with _connect(...)` closes on exit, which would commit or roll back and release
every row lock. `BackfillHandle` therefore owns the connection for its lifetime and
the caller is responsible for `commit()` or `abort()` — the one place in this
codebase where a connection deliberately outlives its opening scope. Give the
connection `SET idle_in_transaction_session_timeout` a real ceiling (the existing
`_hold_unsafe_index` used `'3min'`) so a crashed orchestrator cannot hold 3,000,000
row locks indefinitely. Gate 4 proved `pg_terminate_backend()` recovers an
abandoned transaction cleanly, but a server-side timeout means recovery is automatic
rather than manual.

**Third, the old mechanism must be deleted, not left beside the new one.**
`_hold_unsafe_index` (a `CREATE INDEX` holding a `ShareLock`), `_blocked_writer`,
and `_active_reader` (a `pg_sleep`-based reader whose duration is derived from
`OBSERVATION_COUNT * OBSERVATION_INTERVAL_SECONDS`) implement the mechanism this
redesign replaces. Leaving them creates two incident mechanisms in one file, and
`_active_reader`'s dependence on `OBSERVATION_COUNT` couples it to the fixed-sample
contract Task A2 removes. Replace, do not deprecate.

The measured backfill cost is 22.3s for 3,000,000 rows (design spec's New 3M-Row
baseline), consistent with ~7.1s per million on this instance class. Hot writers
target the lowest 10 `order_id`s: Gate 1 confirmed empirically that an unbatched
`UPDATE` scans in ascending physical order on a freshly bulk-loaded table, so the
lowest IDs are locked first and stay locked. That makes the
`SELECT ... FOR UPDATE NOWAIT` polling fallback the design originally proposed
unnecessary — do not implement it.

- [ ] **Step 1: Write the failing test.** Add to
  `backend/tests/test_incident_lab.py`:

```python
    def test_old_hold_mechanism_is_gone(self) -> None:
        source = (REPO_ROOT / "labs" / "incident" / "run_live_workshop.py").read_text(
            encoding="utf-8"
        )
        for retired in ("_hold_unsafe_index", "_blocked_writer", "_active_reader"):
            self.assertNotIn(
                retired, source,
                f"{retired} implements the replaced mechanism and must be deleted",
            )

    def test_add_column_commits_before_the_backfill_opens(self) -> None:
        """One transaction spanning both would hold AccessExclusiveLock for the
        backfill's full duration, producing Lock:relation instead of
        Lock:transactionid -- a different incident than the labs teach."""
        source = (REPO_ROOT / "labs" / "incident" / "migration.py").read_text(
            encoding="utf-8"
        )
        add_column = source.split("def add_priority_tier_column")[1].split("\ndef ")[0]
        self.assertIn("ADD COLUMN priority_tier", add_column)
        self.assertNotIn("UPDATE", add_column, "the backfill must not share this transaction")

    def test_backfill_handle_bounds_its_idle_transaction(self) -> None:
        source = (REPO_ROOT / "labs" / "incident" / "migration.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("idle_in_transaction_session_timeout", source)
```

- [ ] **Step 2: Run them and confirm they fail.**

```bash
.venv/bin/python -m pytest backend/tests/test_incident_lab.py -k "old_hold or add_column or backfill_handle" -v
```

Expected: FAIL — `ModuleNotFoundError: ... migration`, plus the retired names still
present in `run_live_workshop.py`.

- [ ] **Step 3: Implement the driver.** Create `labs/incident/migration.py`:

```python
"""Phase 1 of the incident: an unbatched backfill held open in one transaction.

The ADD COLUMN commits separately on purpose. A single transaction spanning both
retains AccessExclusiveLock for the backfill's duration, so hot writers would block
on Lock:relation rather than Lock:transactionid -- a different incident than the one
Labs 1-4 diagnose.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import psycopg


def add_priority_tier_column(conn: psycopg.Connection) -> None:
    conn.execute("ALTER TABLE workbench_lab.orders ADD COLUMN priority_tier int")


@dataclass
class BackfillHandle:
    pid: int
    duration_seconds: float
    rows_updated: int
    _conn: psycopg.Connection

    def commit(self) -> None:
        self._conn.commit()
        self._conn.close()

    def abort(self) -> None:
        self._conn.rollback()
        self._conn.close()


def open_backfill(database_url: str) -> BackfillHandle:
    """Run the unbatched backfill and return with its transaction still open.

    The caller owns the returned handle and MUST call commit() or abort(); the
    connection deliberately outlives this function so the row locks survive.
    """
    conn = psycopg.connect(
        database_url,
        autocommit=False,
        application_name="workbench-lab-backfill",
    )
    conn.execute("SET idle_in_transaction_session_timeout = '3min'")
    conn.execute("SET statement_timeout = '3min'")
    pid = conn.execute("SELECT pg_backend_pid()").fetchone()[0]
    started = time.monotonic()
    cursor = conn.execute(
        "UPDATE workbench_lab.orders "
        "SET priority_tier = (order_id %% 5) + 1"
    )
    return BackfillHandle(
        pid=pid,
        duration_seconds=time.monotonic() - started,
        rows_updated=cursor.rowcount,
        _conn=conn,
    )
```

  Note the doubled `%%`: the same `%`-formatting hazard Task B1 flags applies to any
  modulo in SQL passed through Python string handling. Then delete
  `_hold_unsafe_index`, `_blocked_writer`, `_active_reader`, and their thread wiring
  from `run_live_workshop.py`, and call this module in their place.

- [ ] **Step 4: Run the tests.**

```bash
.venv/bin/python -m pytest backend/tests/test_incident_lab.py -v
```

Expected: PASS. Tests naming the retired functions or the old
`ShareLock`/`RowExclusiveLock` vocabulary will fail — Task B6 owns rewriting those,
so if they fail here, note them and let B6 fix them rather than editing them twice.

- [ ] **Step 5: Live-Aurora acceptance criteria.** Five criteria:
  1. `add_priority_tier_column` completes in well under a second and holds no lock
     afterward — verify `pg_locks` shows no `AccessExclusiveLock` on
     `workbench_lab.orders` once it returns.
  2. `open_backfill` returns with `rows_updated == 3_000_000` and
     `duration_seconds` within 50% of the measured 22.3s.
  3. `pg_stat_activity` shows the backfill PID as `idle in transaction` after the
     call returns, proving the transaction survived the function boundary.
  4. A concurrent writer against `order_id = 1` shows
     `wait_event_type = 'Lock'` and `wait_event = 'transactionid'` — **not**
     `'relation'`. If it shows `relation`, the `ADD COLUMN` did not commit
     separately; fix that before proceeding to Task B2, because every downstream
     proving condition depends on it.
  5. `handle.commit()` releases all locks and the blocked writer completes.
  6. The blocked writer's total wait fits inside the 40-second
     `LAB_HOT_WRITE_STATEMENT_TIMEOUT` budget. The budget must cover the
     backfill's remaining runtime after saturation plus the 10–15s observation
     hold; at a measured 22.3s backfill and a 12s hold, the worst realistic wait
     is roughly 25–30s. If `duration_seconds` ever exceeds ~25s on the target
     instance class, raise the statement timeout to 45s rather than shortening the
     hold — the hold is what the evidence describes, and the timeout is the value
     with slack in it.

- [ ] **Step 6: Cleanup and failure recovery.** If the orchestrator dies between
  `open_backfill` and `commit()`, the server-side
  `idle_in_transaction_session_timeout = '3min'` terminates the backend and rolls
  the backfill back automatically. To recover sooner, terminate by application name:

```sql
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
WHERE application_name = 'workbench-lab-backfill';
```

  Re-running is safe: Task B1's `DROP SCHEMA ... CASCADE` rebuild removes the column
  along with the table, so `ADD COLUMN` never hits a duplicate-column error on a
  clean bootstrap. If the driver is re-run *without* a rebuild, `ADD COLUMN` fails
  with `42701` — that is the correct, informative failure, so do not add
  `IF NOT EXISTS` to paper over a skipped bootstrap.

- [ ] **Step 7: Participant-facing changes.** This is the incident participants
  diagnose. The participant-facing description must say what actually happened: a
  schema migration backfilled 3,000,000 rows in one unbatched statement and held the
  transaction open. Do not describe it as "a long-running query" — the open
  transaction, not the duration, is what blocked the writers, and conflating the two
  teaches the wrong lesson.

- [ ] **Step 8: Commit.**

```bash
git add labs/incident/migration.py labs/incident/run_live_workshop.py \
  backend/tests/test_incident_lab.py
git commit -m "Add the migration driver and retire the old hold mechanism"
```

**Dependencies:** Task B1 (the table must exist at 3M rows without
`priority_tier`).

### Task B2: Add the lab-only hot-write endpoint — HC-1 and HC-2 binding

**Owning schema/module:** `backend/app/`; new `backend/app/lab_routes.py`.

**Files:**
- Create: `backend/app/lab_routes.py`
- Modify: `backend/app/main.py` — register the two lab routes
- Modify: `backend/app/config.py` — add `LAB_ENDPOINTS_ENABLED` (default off),
  `LAB_HOT_WRITE_CHECKOUT_TIMEOUT_SECONDS` (default `3.0`),
  `LAB_HOT_WRITE_STATEMENT_TIMEOUT` (default `'40s'`),
  `LAB_HOT_WRITE_REQUEST_COUNT` (default `12`)
- Test: `backend/tests/test_lab_routes.py` (new)

**Interfaces:**
- Consumes: Task B1's `workbench_lab.orders` shape.
- Produces:
  - `POST /v1/lab/hot-write` with body `{"order_id": int}`, returning
    `{"order_id": int, "outcome": "committed" | "statement_timeout" |
    "pool_timeout", "waited_seconds": float}` — **200 in every case**, because a
    timeout here is a measured observation, not an API error.
  - `GET /v1/lab/pool-status` returning
    `{"pool_size": int, "pool_available": int, "requests_waiting": int,
    "requests_queued": int, "usage_ms": float}`.
  Task B3's hold controller calls both; Task C2's evidence builder consumes the
  `outcome` values.

**The timeout defaults are the corrected policy, not Gate 1's.** Gate 1 set both
timeouts to `3s`; the shipped statement timeout is `'40s'` per HC-1's second
paragraph and the Global Constraints timeout policy. A reviewer seeing `'3s'` in
`config.py` should treat it as a defect, not as fidelity to the gate script.

**Migration and compatibility implications:** `backend/app/main.py` today has 30
routes registered directly on `app` with no `APIRouter` and **no existing
lab-only or config-gated route** — these two are first-of-kind, so the pattern
this task establishes is the precedent. Put them in their own module and gate them
on `LAB_ENDPOINTS_ENABLED` so a deployed workshop app does not expose a write
endpoint by default. CORS is `allow_methods=["GET","POST"]` only, which already
covers both. There are no global exception handlers; conventions are
`_unavailable(area, error)` → 503, `ValueError` → 404,
`_require_retrieval_ready()` → 409. The hot-write endpoint deliberately does
**not** use those: a `PoolTimeout` is a 200 with
`outcome = "pool_timeout"`, because the design spec's Error Handling section
requires `psycopg_pool.PoolTimeout` to be "caught at the call site and recorded as
evidence, not allowed to propagate as an unhandled driver error." Do **not** use
`get_conn()` — it opens its own transaction and issues `SET LOCAL ROLE` for
personas; this is the owner-less pooled lab path and must check out from
`get_pool()` directly. `get_owner_conn()` is **not pooled** (direct
`psycopg.connect`), so using it would make pool stats never move and silently
defeat the whole mechanism.

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_lab_routes.py`:

```python
"""Lab-only route tests. Requires a disposable _test database."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
ALLOW_RESET = os.environ.get("ALLOW_TEST_DATABASE_RESET") == "1"


class LabRouteContractTests(unittest.TestCase):
    def test_hot_write_holds_set_local_and_update_in_one_transaction(self) -> None:
        source = (REPO_ROOT / "backend" / "app" / "lab_routes.py").read_text(
            encoding="utf-8"
        )
        body = source.split("def _hot_write")[1].split("\ndef ")[0]
        self.assertIn("with conn.transaction():", body)
        self.assertIn("SET LOCAL statement_timeout", body)
        self.assertIn("SET LOCAL application_name", body)
        transaction_at = body.index("with conn.transaction():")
        for statement in ("SET LOCAL statement_timeout", "SET LOCAL application_name", "UPDATE workbench_lab.orders"):
            self.assertGreater(
                body.index(statement),
                transaction_at,
                f"HC-2 violated: {statement} runs outside the explicit transaction",
            )

    def test_hot_write_sets_both_timeouts(self) -> None:
        source = (REPO_ROOT / "backend" / "app" / "lab_routes.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("connection(timeout=", source)
        self.assertIn("SET LOCAL statement_timeout", source)

    def test_pool_status_performs_no_checkout(self) -> None:
        source = (REPO_ROOT / "backend" / "app" / "lab_routes.py").read_text(
            encoding="utf-8"
        )
        body = source.split("def _pool_status")[1].split("\ndef ")[0]
        self.assertIn("get_stats()", body)
        self.assertNotIn(".connection(", body)
        self.assertNotIn("get_conn", body)
```

- [ ] **Step 2: Run it and confirm it fails.**

```bash
.venv/bin/python -m pytest backend/tests/test_lab_routes.py -v
```

Expected: FAIL — `FileNotFoundError: .../backend/app/lab_routes.py`.

- [ ] **Step 3: Implement both endpoints.** Create `backend/app/lab_routes.py`.
  The hot-write body is the Gate-1-proven shape, unchanged in structure:

```python
"""Lab-only routes for the induced incident. Config-gated, never on by default.

Two hard contracts from Gate 1 govern _hot_write and must not be refactored
apart:

HC-1  Checkout timeout and statement timeout are separate bounds.
      pool.connection(timeout=...) bounds only the wait for a free pool slot.
      A writer that gets a connection before the pool saturates has no bound
      on its row-lock wait, and will hang indefinitely. Both timeouts are
      required.

HC-2  SET LOCAL and the UPDATE must run inside ONE explicit transaction on the
      SAME pooled connection. Pooled connections are autocommit=True, so a bare
      conn.execute("SET LOCAL ...") ends its own implicit transaction and
      silently resets the setting before the UPDATE runs.
"""
from __future__ import annotations

import time

import psycopg_pool
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app import db as app_db
from backend.app.config import get_settings

router = APIRouter()


class HotWriteRequest(BaseModel):
    order_id: int


class HotWriteResult(BaseModel):
    order_id: int
    outcome: str
    waited_seconds: float


def _require_lab_endpoints() -> None:
    if not get_settings().lab_endpoints_enabled:
        raise HTTPException(
            status_code=404,
            detail="lab endpoints are disabled; set LAB_ENDPOINTS_ENABLED=1",
        )


@router.post("/v1/lab/hot-write", response_model=HotWriteResult)
def _hot_write(request: HotWriteRequest) -> HotWriteResult:
    _require_lab_endpoints()
    settings = get_settings()
    started = time.monotonic()
    try:
        with app_db.get_pool().connection(
            timeout=settings.lab_hot_write_checkout_timeout_seconds
        ) as conn:
            # HC-2: one explicit transaction, same connection, both SET LOCALs
            # and the UPDATE inside it.
            with conn.transaction():
                conn.execute(
                    "SET LOCAL application_name = 'workbench-lab-api-hot-write'"
                )
                # HC-1: the checkout timeout above does not bound this wait.
                conn.execute(
                    "SET LOCAL statement_timeout = %s",
                    (settings.lab_hot_write_statement_timeout,),
                )
                conn.execute(
                    "UPDATE workbench_lab.orders SET status = 'touched' "
                    "WHERE order_id = %s",
                    (request.order_id,),
                )
    except psycopg_pool.PoolTimeout:
        return HotWriteResult(
            order_id=request.order_id,
            outcome="pool_timeout",
            waited_seconds=time.monotonic() - started,
        )
    except psycopg.errors.QueryCanceled:
        return HotWriteResult(
            order_id=request.order_id,
            outcome="statement_timeout",
            waited_seconds=time.monotonic() - started,
        )
    return HotWriteResult(
        order_id=request.order_id,
        outcome="committed",
        waited_seconds=time.monotonic() - started,
    )


@router.get("/v1/lab/pool-status")
def _pool_status() -> dict[str, float | int]:
    _require_lab_endpoints()
    # No checkout of its own: get_stats() reads the pool's own counters. A
    # checkout here would consume one of the ten slots the mechanism depends on
    # and would itself block once the pool saturates, making the endpoint
    # unresponsive exactly when it is needed.
    stats = app_db.get_pool().get_stats()
    return {
        "pool_size": stats.get("pool_size", 0),
        "pool_available": stats.get("pool_available", 0),
        "requests_waiting": stats.get("requests_waiting", 0),
        "requests_queued": stats.get("requests_queued", 0),
        "usage_ms": stats.get("usage_ms", 0),
    }
```

  Add `import psycopg` at the top (needed for `psycopg.errors.QueryCanceled`).
  In `backend/app/main.py`, register with `app.include_router(router)` next to the
  existing route definitions. In `backend/app/config.py`, add the three settings
  using the existing `default_factory=lambda: os.environ.get(...)` pattern —
  never a bare `os.environ.get()` default, which resolves at import time and is
  the root cause of the documented DSN trap.

- [ ] **Step 4: Run the tests.**

```bash
.venv/bin/python -m pytest backend/tests/test_lab_routes.py -v
```

Expected: PASS, all three.

- [ ] **Step 5: Live-Aurora acceptance criteria.** This is the verification Gate 1
  left owed, stated precisely: **Gate 1 did exercise the real
  `psycopg_pool.ConnectionPool`** via `backend/app/db.py`'s `open_pool()` /
  `get_pool()` — that much is closed. What Gate 1 did **not** exercise is the real
  **HTTP endpoint** path: FastAPI request handling, Pydantic
  request/response models, per-request threading through the ASGI worker, and the
  `outcome`-as-200 error contract. What this step owes is therefore
  **endpoint-level proof**, not first-time pool proof. It also owes the first proof
  of the corrected 12-request topology, which Gate 1's 10-request script could not
  produce by construction.

  Start the API against the disposable database, hold a backfill open, and fire
  **12** concurrent hot-writes against **12 distinct** `order_id`s:

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
LAB_ENDPOINTS_ENABLED=1 DB_POOL_MAX_SIZE=10 \
  .venv/bin/uvicorn backend.app.main:app --port 8099 &
sleep 3
curl -s localhost:8099/v1/lab/pool-status
```

  Then, with a backfill transaction held open, issue **12** concurrent
  `POST /v1/lab/hot-write` calls against `order_id` 1–12. Acceptance criteria, all
  six required:
  1. All 12 responses are HTTP 200 — none is a 500 or a dropped connection. A
     `PoolTimeout` surfacing as a 500 means the `outcome`-as-200 contract was not
     wired, which is exactly what this endpoint-level step exists to catch and
     what Gate 1 could not have caught.
  2. **Exactly 2** responses have `outcome = "pool_timeout"`, each with
     `waited_seconds` between 3.0 and 3.5 — they never obtained a connection and
     hit the 3-second checkout bound. This is the pool-exhaustion signal.
  3. **Exactly 10** responses have `outcome = "committed"` — they obtained a
     connection, blocked on `Lock:transactionid` for the remainder of the
     backfill, and committed once it released. This is the row-lock-blocking
     signal, and it drains rather than erroring because the statement timeout is
     `'40s'`, not `'3s'`.
  4. Every `committed` response's `waited_seconds` **exceeds** the queued
     requests' — a blocked writer necessarily waited longer than a writer that
     gave up after 3 seconds. If a `committed` response returns in under 1 second,
     it never blocked at all and the backfill was not holding its locks when the
     request arrived.
  5. **Zero** responses have `outcome = "statement_timeout"`. Gate 1's nine
     `statement_timeout`s were an artifact of its own 3-second setting; seeing any
     here means `LAB_HOT_WRITE_STATEMENT_TIMEOUT` is still too short for the
     backfill's remaining runtime.
  6. `GET /v1/lab/pool-status` returns in under 100ms **during** full saturation,
     showing `pool_available = 0` and `requests_waiting >= 2`. Gate 1 measured max
     status-check latency at 0.0001s; 100ms is the acceptance bound.

  Failure interpretation, all three drawn from real Gate 1 failures:
  - Any `outcome = "committed"` with `waited_seconds` under 1 second, or a
    `pool_timeout` count of zero: the writers did not collide with the backfill.
    Verify the backfill transaction is genuinely still open and that the
    `order_id`s targeted fall inside the range it has already updated.
  - A call that hangs past 60 seconds: **HC-2 violated** — the `SET LOCAL
    statement_timeout` was reset by an implicit transaction boundary, so no
    statement bound is in force. This is Gate 1 attempt 2's exact failure.
  - More than 2 `pool_timeout`s: fewer than 10 requests are reaching PostgreSQL.
    Check `DB_POOL_MAX_SIZE` is actually 10 in this environment — a smaller pool
    silently converts blocked writers into queued ones and quietly changes which
    incident is being measured.

- [ ] **Step 6: Cleanup and failure recovery.** Kill the uvicorn process, then
  clear any tagged sessions the aborted run left behind:

```bash
kill %1
psql -X -v ON_ERROR_STOP=1 \
  "postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" <<'SQL'
DO $guard$ BEGIN
  IF current_database() <> 'dat410_review_remediation_test' THEN
    RAISE EXCEPTION 'SAFETY ABORT: connected to %', current_database();
  END IF;
END $guard$;
SELECT pg_terminate_backend(pid), application_name, state
FROM pg_stat_activity
WHERE application_name IN ('workbench-lab-api-hot-write', 'workbench-lab-backfill')
  AND datname = current_database()   -- pg_stat_activity is CLUSTER-wide
  AND pid <> pg_backend_pid();
SQL
```

  `datname = current_database()` is required for the same reason as in Task B1:
  `pg_stat_activity` spans the whole cluster, and `dat410_live` uses these same
  two application-name tags. Measured on 2026-08-04: five sessions belonging to
  other databases were visible from a single test-database connection.

  Gate 4 proved a SIGKILLed client's orphaned server-side backend is cleanly
  removable by `pg_terminate_backend()` filtered by `application_name`, and that
  the pool itself recovers to `pool_available == pool_size` with no restart. Both
  recoveries were independently observed twice. Filter by `application_name` —
  never terminate by broad predicate on a shared cluster.

- [ ] **Step 7: Participant-facing changes.** The participant never calls these
  endpoints directly; the orchestrator does. But `LAB_ENDPOINTS_ENABLED` must be
  set in the workshop environment or Lab 1 fails with a 404 whose message names
  the missing variable — Task F1 owns that wiring.

- [ ] **Step 8: Commit.**

```bash
git add backend/app/lab_routes.py backend/app/main.py backend/app/config.py \
  backend/tests/test_lab_routes.py
git commit -m "Add lab-only hot-write and pool-status endpoints"
```

**Dependencies:** Tasks B1 and B1a (`workbench_lab.orders` must exist at 3M rows,
and the backfill must be holding its transaction open, for the live acceptance run
to produce real lock contention).

### Task B3: Implement the condition-based hold controller

**Owning schema/module:** `labs/incident/`; new
`labs/incident/hold_controller.py`.

**Files:**
- Create: `labs/incident/hold_controller.py`
- Modify: `labs/incident/run_live_workshop.py` — call the controller between the
  backfill and the commit
- Test: `backend/tests/test_incident_lab.py`

**Interfaces:**
- Consumes: Task B2's `GET /v1/lab/pool-status` and
  `POST /v1/lab/hot-write`; Task B1's table.
- Produces: `prove_hold(conn, *, backfill_pid, pool_status,
  expected_blocked_sessions=10, poll_interval=0.25, required_samples=3,
  hold_seconds=12.0, max_attempt_seconds=90.0) -> HoldProof`, where `HoldProof` carries
  `samples: list[PollSample]` (every raw poll, for `casework.*_samples`) and
  `state_changes: list[StateChange]` (the transitions Task C2 turns into
  documents). Task C2's evidence builder consumes exactly this.

**Migration and compatibility implications:** this replaces the old mechanism's
fixed 60-second induced stall (measured 69.1s wall-clock, the single largest
fixed cost in the old pipeline) with a condition-based hold that ends as soon as
the state is proven. That is both faster and honest: the old sleep asserted
nothing. Per Global Constraints the hold begins only after **3 consecutive
samples** simultaneously prove all four conditions: `pool_size = pool_max = 10`,
`pool_available = 0`, `requests_waiting >= 2`, and exactly
`expected_blocked_sessions` (10) tagged sessions show `wait_event_type = 'Lock'`
with the backfill PID in `pg_blocking_pids()`.

**`expected_blocked_sessions` is `DB_POOL_MAX_SIZE`, not the launched request
count, and the parameter is named that way on purpose.** The driver launches
12–14 requests; only 10 can hold a connection, so only 10 can appear in
`pg_stat_activity` at all. The remaining 2–4 are the source of
`requests_waiting >= 2` — they are counted by the pool, never by PostgreSQL.
Naming this parameter `writer_count` invites an implementer to pass the request
count and produce a condition that can never be satisfied: a hold that waits for
12 blocked sessions against a 10-slot pool times out every single run. Do **not**
rename it back, and do **not** derive it from `LAB_HOT_WRITE_REQUEST_COUNT`.

Per the
design spec's Error Handling section, `max_attempt_seconds` is the **one place a
numeric ceiling still matters** — it prevents an unbounded retry loop if the
mechanism is broken — and on expiry it raises `LiveWorkshopError` naming *which
specific condition never held*, not an opaque timeout. Per Global Constraints the
250ms poll is control, not document generation: persist every raw sample, emit a
document only on a state change.

- [ ] **Step 1: Write the failing test.** Add to
  `backend/tests/test_incident_lab.py`:

```python
    def test_hold_requires_three_consecutive_proving_samples(self) -> None:
        from labs.incident.hold_controller import PollSample, evaluate_samples

        proving = PollSample(
            pool_size=10, pool_max=10, pool_available=0, requests_waiting=2,
            blocked_session_count=10,
        )
        not_proving = PollSample(
            pool_size=10, pool_max=10, pool_available=1, requests_waiting=2,
            blocked_session_count=10,
        )
        self.assertFalse(
            evaluate_samples([proving, proving], expected_blocked_sessions=10)
        )
        self.assertTrue(
            evaluate_samples([proving, proving, proving], expected_blocked_sessions=10)
        )
        self.assertFalse(
            evaluate_samples([proving, not_proving, proving], expected_blocked_sessions=10),
            "a non-proving sample must reset the streak, not be skipped",
        )

    def test_hold_failure_names_the_condition_that_never_held(self) -> None:
        from labs.incident.hold_controller import PollSample, describe_failure

        samples = [
            PollSample(
                pool_size=10, pool_max=10, pool_available=0, requests_waiting=2,
                blocked_session_count=7,
            )
        ] * 4
        message = describe_failure(samples, expected_blocked_sessions=10)
        self.assertIn("only 7 of 10", message)
        self.assertNotIn("timeout", message.lower())

    def test_hold_expects_pool_max_blocked_sessions_not_request_count(self) -> None:
        """Only DB_POOL_MAX_SIZE requests can hold a connection, so only that many
        can ever appear blocked in pg_stat_activity. A hold that expects the
        launched request count (12) can never be satisfied against a 10-slot pool.
        """
        from labs.incident.hold_controller import PollSample, evaluate_samples

        fully_saturated = PollSample(
            pool_size=10, pool_max=10, pool_available=0, requests_waiting=2,
            blocked_session_count=10,
        )
        samples = [fully_saturated] * 3
        self.assertTrue(evaluate_samples(samples, expected_blocked_sessions=10))
        self.assertFalse(
            evaluate_samples(samples, expected_blocked_sessions=12),
            "expected_blocked_sessions must be DB_POOL_MAX_SIZE, not "
            "LAB_HOT_WRITE_REQUEST_COUNT -- 12 is unsatisfiable by construction",
        )
```

- [ ] **Step 2: Run it and confirm it fails.**

```bash
.venv/bin/python -m pytest backend/tests/test_incident_lab.py -k hold -v
```

Expected: FAIL — `ModuleNotFoundError: No module named
'labs.incident.hold_controller'`.

- [ ] **Step 3: Implement the controller.** Create
  `labs/incident/hold_controller.py`:

```python
"""Condition-based hold controller for the induced incident.

The hold is never a fixed sleep. It begins only after three consecutive polls
simultaneously prove the pool is genuinely exhausted and every tagged writer is
genuinely blocked by the backfill. A fixed sleep asserts nothing; this asserts
the exact state the evidence will later claim.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PollSample:
    pool_size: int
    pool_max: int
    pool_available: int
    requests_waiting: int
    blocked_session_count: int
    observed_at: str = ""


@dataclass(frozen=True)
class StateChange:
    label: str
    detail: str
    observed_at: str


@dataclass
class HoldProof:
    samples: list[PollSample] = field(default_factory=list)
    state_changes: list[StateChange] = field(default_factory=list)
    proven_at: str = ""
    hold_seconds: float = 0.0


def _proves(sample: PollSample, *, expected_blocked_sessions: int) -> bool:
    """Both signals must hold in the SAME sample.

    pool_available == 0 and blocked_session_count == expected_blocked_sessions
    describe the connections that are held; requests_waiting >= 2 describes the
    requests that could not get one. They are disjoint populations, which is why
    the driver launches more requests than the pool has slots.
    """
    return (
        sample.pool_size == sample.pool_max
        and sample.pool_available == 0
        and sample.requests_waiting >= 2
        and sample.blocked_session_count == expected_blocked_sessions
    )


def evaluate_samples(
    samples: list[PollSample],
    *,
    expected_blocked_sessions: int,
    required_samples: int = 3,
) -> bool:
    """Return True when the last ``required_samples`` polls all prove the hold.

    A non-proving sample resets the streak. Three proving samples separated by
    a non-proving one are not a proven hold -- they are a flapping pool.

    ``expected_blocked_sessions`` is DB_POOL_MAX_SIZE, never the launched request
    count: a request waiting for a slot holds no connection and so cannot appear
    blocked in pg_stat_activity.
    """
    if len(samples) < required_samples:
        return False
    tail = samples[-required_samples:]
    return all(
        _proves(sample, expected_blocked_sessions=expected_blocked_sessions)
        for sample in tail
    )


def describe_failure(
    samples: list[PollSample], *, expected_blocked_sessions: int
) -> str:
    """Name the specific condition that never held, never a bare timeout."""
    if not samples:
        return "no poll samples were collected at all"
    if not any(s.pool_size == s.pool_max for s in samples):
        worst = max(s.pool_size for s in samples)
        return f"pool never reached its maximum size: peaked at {worst} of {samples[0].pool_max}"
    if not any(s.pool_available == 0 for s in samples):
        best = min(s.pool_available for s in samples)
        return f"pool_available stayed non-zero: lowest observed was {best}"
    if not any(s.requests_waiting >= 2 for s in samples):
        best = max(s.requests_waiting for s in samples)
        return f"requests_waiting never reached 2: peaked at {best}"
    best = max(s.blocked_session_count for s in samples)
    return (
        f"only {best} of {expected_blocked_sessions} tagged sessions were ever "
        f"blocked on the backfill; the hold requires all "
        f"{expected_blocked_sessions}"
    )
```

  Add `prove_hold(...)` driving the 250ms loop: sample
  `GET /v1/lab/pool-status` and the blocked-session count via
  `pg_blocking_pids(pid) @> ARRAY[backfill_pid]`, append every sample to
  `HoldProof.samples`, append a `StateChange` only when a field crosses a
  boundary, and on `evaluate_samples(...) is True` hold for `hold_seconds` then
  return. On `max_attempt_seconds` expiry, raise
  `LiveWorkshopError(describe_failure(samples, expected_blocked_sessions=expected_blocked_sessions))`.

  `prove_hold` must default `expected_blocked_sessions` from
  `get_settings().db_pool_max_size`, **not** from
  `lab_hot_write_request_count`. The caller in `run_live_workshop.py` launches
  `LAB_HOT_WRITE_REQUEST_COUNT` (12) requests and passes
  `DB_POOL_MAX_SIZE` (10) here; those two numbers are deliberately different and
  must not be unified.

- [ ] **Step 4: Run the tests.**

```bash
.venv/bin/python -m pytest backend/tests/test_incident_lab.py -k hold -v
```

Expected: PASS on both.

- [ ] **Step 5: Live-Aurora acceptance criteria.** Run the real controller against
  the real pool and the real 3M-row backfill (the mechanism, not a mock — the unit
  tests above cover the predicate, not the integration). Acceptance criteria:
  1. `prove_hold` returns with `proven_at` set, in **under 45 seconds** total from
     backfill start (measured backfill duration 21.1–22.3s, plus saturation time).
  2. `HoldProof.samples` contains every raw poll at ~250ms spacing — a sample count
     consistent with the elapsed time, not a suspiciously round number.
  3. `HoldProof.state_changes` is **strictly fewer** than
     `len(HoldProof.samples)` — this is the mechanical check that the 250ms poll
     is control and not document generation. If they are equal, a document is
     being emitted per tick and Global Constraints are violated.
  4. Deliberately break the mechanism (set `LAB_HOT_WRITE_REQUEST_COUNT=7`, so
     only 7 requests exist and at most 7 sessions can block) and confirm the
     raised message reads `only 7 of 10 tagged sessions were ever blocked`, not a
     timeout. A controller whose failure path has never been exercised is not
     verified.
  5. During the proven hold, `pool_status.requests_waiting` is **at least 2** in
     the same samples where `blocked_session_count == 10`. This is the mechanical
     proof that the 12-request topology delivered both signals simultaneously —
     the exact condition a 10-request run cannot satisfy. If
     `requests_waiting` is 0 whenever `blocked_session_count` is 10, the driver is
     launching only `DB_POOL_MAX_SIZE` requests and the Global Constraints
     concurrency contract has been violated somewhere upstream.

- [ ] **Step 6: Cleanup and failure recovery.** On `LiveWorkshopError` the caller
  in `run_live_workshop.py` must still commit or roll back the backfill
  transaction and terminate tagged sessions — an abandoned hold must not leave 3M
  rows locked. Use the same `application_name`-filtered termination as Task B2
  step 6. Confirm recovery before declaring the failure path handled:

```bash
psql -X -v ON_ERROR_STOP=1 \
  "postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" <<'SQL'
SELECT count(*) AS blocked_sessions
FROM pg_stat_activity
WHERE wait_event_type = 'Lock'
  AND application_name LIKE 'workbench-lab-%'
  AND datname = current_database();   -- pg_stat_activity is CLUSTER-wide
SQL
```

Expected: `blocked_sessions = 0`.

- [ ] **Step 7: Participant-facing changes.** The participant's Lab 1 wait becomes
  variable (as short as the state takes to prove) rather than a fixed 60 seconds.
  Facilitator guidance must say the hold is condition-based and its duration
  varies — participants comparing timings will otherwise think something is wrong.

- [ ] **Step 8: Commit.**

```bash
git add labs/incident/hold_controller.py labs/incident/run_live_workshop.py \
  backend/tests/test_incident_lab.py
git commit -m "Add the condition-based hold controller"
```

**Dependencies:** Task B2 (the controller polls `/v1/lab/pool-status` and drives
`/v1/lab/hot-write`; neither exists before B2) and Task B1a (`backfill_pid` comes
from `BackfillHandle.pid`, and the proving condition requires that PID to be
holding row locks).

### Task B4: Implement the recovery verifier with seven independent assertions

**Owning schema/module:** `labs/incident/`; new
`labs/incident/recovery_verifier.py`.

**Files:**
- Create: `labs/incident/recovery_verifier.py`
- Modify: `labs/incident/run_live_workshop.py` — call it immediately after commit
- Test: `backend/tests/test_incident_lab.py`

**Interfaces:**
- Consumes: Task B2's pool-status endpoint, Task B3's `HoldProof`.
- Produces: `verify_recovery(conn, *, backfill_pid, pool_status,
  write_outcomes: list[HotWriteResult]) -> RecoveryProof`, carrying one named
  boolean per assertion. Task C2 turns these into the recovery-phase documents.
  `write_outcomes` is the list of `HotWriteResult` values (Task B2's response
  model, fields `order_id` / `outcome` / `waited_seconds`) that the hot-write
  driver already collects from its **12** concurrent calls — the same list Task C1
  turns into `request` documents. Do not add an `outcome` field to Task B3's
  `StateChange` for this: `StateChange` describes pool transitions, and a
  per-writer request outcome is a different thing that already has a home.

**Migration and compatibility implications:** the old mechanism had no recovery
verification at all — it slept, repaired with `CREATE INDEX CONCURRENTLY`, and
moved on. Per the design spec's Error Handling section, the seven assertions must
**fail independently and identifiably, not as one bundled check**, so that a
partial-recovery bug is diagnosable from the error message alone. The seven:
(1) the backfill PID no longer appears in any `pg_blocking_pids()` result;
(2) `pool_available == pool_size`; (3) `requests_waiting == 0`; (4) zero sessions
remain in `wait_event_type = 'Lock'` under a `workbench-lab-%` application name;
(5) **at least one `PoolTimeout` was recorded during the hold** — read from the
hot-write results, which is why `verify_recovery` takes them as a parameter;
(6) **the blocked writers drained**: exactly `DB_POOL_MAX_SIZE` (10)
`write_outcomes` have `outcome = "committed"`, and **zero** have
`outcome = "statement_timeout"`; (7) a fresh
`POST /v1/lab/hot-write` returns `outcome = "committed"`.

Assertion 7 is the load-bearing one for recovery — assertions 1–4 are
observational and could all pass while writes still fail. Assertions 5 and 6 are
different in kind from the rest, and both are **retrospective**: they check that
the incident actually happened and ended correctly, rather than that recovery
succeeded.

Assertion 5 is the design spec's guard against the most dangerous false green in
the whole mechanism — a run where the pool never actually saturated would satisfy
every other assertion trivially (nothing was blocked, so nothing needs to have
recovered) and emit a corpus describing an incident that did not occur. `>= 1` is
the honest threshold at a 12-request/10-slot topology, which is designed to
produce 2; do not raise it to a count the mechanism does not reliably produce, and
do not lower it to 0.

Assertion 6 is new and exists because the corrected timeout policy makes the
drain observable for the first time. Under Gate 1's 3-second statement timeout,
nine writers cancelled themselves and nothing drained; under the shipped `'40s'`
timeout, all ten blocked writers must commit once the backfill releases. A
`statement_timeout` outcome here is therefore not a measurement — it is a Phase B
regression indicating the statement bound is too short for the backfill's runtime
plus the hold, and it must fail loudly rather than be written into the corpus as
though it were the incident's real shape.

- [ ] **Step 1: Write the failing test.**

```python
    def test_recovery_assertions_fail_independently(self) -> None:
        from labs.incident.recovery_verifier import RecoveryProof, failed_assertions

        proof = RecoveryProof(
            backfill_no_longer_blocking=True,
            pool_fully_available=False,
            no_requests_waiting=True,
            no_sessions_blocked=True,
            pool_timeout_observed=True,
            blocked_writers_drained=True,
            fresh_write_committed=False,
        )
        failures = failed_assertions(proof)
        self.assertEqual(
            failures, ["pool_fully_available", "fresh_write_committed"]
        )
        self.assertEqual(failed_assertions(RecoveryProof()), [], "default must be all-passing or explicit")

    def test_recovery_rejects_a_hold_that_never_saturated_the_pool(self) -> None:
        """A run with no PoolTimeout did not prove pool exhaustion, so every
        other assertion passes vacuously. This must still fail."""
        from labs.incident.recovery_verifier import RecoveryProof, failed_assertions

        proof = RecoveryProof(pool_timeout_observed=False)
        self.assertEqual(failed_assertions(proof), ["pool_timeout_observed"])

    def test_drain_requires_pool_max_commits_and_no_statement_timeouts(self) -> None:
        """The corrected timeout policy makes the drain observable: all 10 blocked
        writers must commit once the backfill releases. A statement_timeout here
        means the statement bound is shorter than the backfill plus the hold --
        a Phase B regression, not a measurement.
        """
        from labs.incident.recovery_verifier import evaluate_drain

        def outcomes(committed: int, pool_timeout: int, statement_timeout: int = 0):
            return (
                [SimpleNamespace(outcome="committed")] * committed
                + [SimpleNamespace(outcome="pool_timeout")] * pool_timeout
                + [SimpleNamespace(outcome="statement_timeout")] * statement_timeout
            )

        self.assertTrue(evaluate_drain(outcomes(10, 2), pool_max_size=10))
        self.assertFalse(
            evaluate_drain(outcomes(9, 2, 1), pool_max_size=10),
            "a statement_timeout means the statement bound was too short",
        )
        self.assertFalse(
            evaluate_drain(outcomes(9, 3), pool_max_size=10),
            "only 9 commits means a blocked writer never drained",
        )
        self.assertFalse(
            evaluate_drain(outcomes(12, 0), pool_max_size=10),
            "12 commits and zero pool_timeouts means the pool never saturated",
        )
```

  Add `from types import SimpleNamespace` to the test module's imports.

- [ ] **Step 2: Run it and confirm it fails.**

```bash
.venv/bin/python -m pytest backend/tests/test_incident_lab.py -k recovery -v
```

Expected: FAIL — `ModuleNotFoundError: ... recovery_verifier`.

- [ ] **Step 3: Implement the verifier.** Create
  `labs/incident/recovery_verifier.py` with a frozen `RecoveryProof` dataclass
  carrying the seven named booleans (all defaulting `True`), `failed_assertions()`
  returning the field names that are `False` in declaration order, and
  `verify_recovery()` evaluating each of the seven separately and raising
  `LiveWorkshopError` naming **every** failed assertion:

```python
def evaluate_drain(write_outcomes, *, pool_max_size: int) -> bool:
    """Every writer that held a connection must have committed.

    Exactly pool_max_size requests can hold a connection, so exactly that many
    must commit. A statement_timeout means the statement bound was shorter than
    the backfill's remaining runtime plus the hold -- a regression in the timeout
    policy, never a property of the incident. Zero pool_timeouts means the pool
    never saturated, so the drain proves nothing.
    """
    committed = sum(1 for item in write_outcomes if item.outcome == "committed")
    statement_timeouts = sum(
        1 for item in write_outcomes if item.outcome == "statement_timeout"
    )
    pool_timeouts = sum(
        1 for item in write_outcomes if item.outcome == "pool_timeout"
    )
    return (
        committed == pool_max_size
        and statement_timeouts == 0
        and pool_timeouts >= 1
    )


def verify_recovery(conn, *, backfill_pid: int, pool_status, write_outcomes) -> RecoveryProof:
    pool_max_size = get_settings().db_pool_max_size
    proof = RecoveryProof(
        backfill_no_longer_blocking=_no_longer_blocking(conn, backfill_pid),
        pool_fully_available=_pool_fully_available(pool_status),
        no_requests_waiting=_no_requests_waiting(pool_status),
        no_sessions_blocked=_no_sessions_blocked(conn),
        pool_timeout_observed=any(
            item.outcome == "pool_timeout" for item in write_outcomes
        ),
        blocked_writers_drained=evaluate_drain(
            write_outcomes, pool_max_size=pool_max_size
        ),
        fresh_write_committed=_fresh_write_commits(),
    )
    failures = failed_assertions(proof)
    if failures:
        raise LiveWorkshopError(
            "recovery verification failed on: " + ", ".join(failures)
        )
    return proof
```

- [ ] **Step 4: Run the tests.**

```bash
.venv/bin/python -m pytest backend/tests/test_incident_lab.py -k recovery -v
```

Expected: PASS.

- [ ] **Step 5: Live-Aurora acceptance criteria.** After a real hold and commit,
  all seven assertions pass and `verify_recovery` returns within 5 seconds of
  commit. Then prove three failure paths separately: (a) commit the backfill but hold
  one hot-write session open, and confirm the raised message names
  `no_sessions_blocked` specifically — not a bundled "recovery failed"; (b) run the
  whole mechanism with `DB_POOL_MAX_SIZE` raised to **14**, above the 12 launched
  requests, so no request ever queues and the pool never saturates, and confirm it
  fails on `pool_timeout_observed` even though every other assertion passes;
  (c) run with `LAB_HOT_WRITE_STATEMENT_TIMEOUT='3s'` — Gate 1's value — and
  confirm it fails on `blocked_writers_drained`, because the writers cancel
  themselves instead of draining. Path (b) proves the vacuous-green guard works;
  path (c) proves the corrected timeout policy is actually enforced rather than
  merely documented, and it reproduces the precise defect this correction pass
  fixed. Without running both, assertions 5 and 6 are untested by construction.
  Gate 4 already measured the real
  pool recovering 1→9 connections with `requests_queued = 14` and returning to
  `pool_available == pool_size` unaided, so assertion 2 is expected to pass
  naturally; if it does not, the pool is being held by something outside the lab
  path.

- [ ] **Step 6: Cleanup and failure recovery.** A failed recovery verification
  means state is still held; the caller must terminate tagged sessions before
  raising further, or the next run's `_assert_no_live_lab_sessions` refuses to
  start. That refusal is correct behavior — do not weaken it to let a dirty run
  proceed.

- [ ] **Step 7: Participant-facing changes.** The participant sees an explicit
  "recovery verified" step in Lab 1's output, naming what was checked. This is
  what makes the incident a closed loop rather than an induced failure the
  workshop walks away from.

- [ ] **Step 8: Commit.**

```bash
git add labs/incident/recovery_verifier.py labs/incident/run_live_workshop.py \
  backend/tests/test_incident_lab.py
git commit -m "Add the recovery verifier with seven independent assertions"
```

**Dependencies:** Tasks B2 and B3.

### Task B5: Implement the query-regression driver with three plan checkpoints

**Owning schema/module:** `labs/incident/`; new
`labs/incident/query_regression.py`.

**Files:**
- Create: `labs/incident/query_regression.py`
- Modify: `labs/incident/run_live_workshop.py`
- Test: `backend/tests/test_incident_lab.py`

**Interfaces:**
- Consumes: Task B1's table plus the `priority_tier` column added by the
  migration.
- Produces: `capture_plan_checkpoints(conn, *, tier: int) ->
  list[PlanCheckpoint]` where each checkpoint carries
  `label` (`'before_analyze'`, `'after_analyze'`, `'after_index'`), `plan_type`,
  `execution_ms`, `rows_returned`, `rows_removed_by_filter`, `buffers`, and the
  raw `EXPLAIN (ANALYZE, BUFFERS)` text. Wave A captures the first two;
  **Wave B captures the third, after the participant creates the index.**

**Migration and compatibility implications:** the reference query is
`SELECT order_id, customer_id, created_at FROM workbench_lab.orders
WHERE priority_tier = :n ORDER BY created_at DESC LIMIT 20`. Measured numbers
across two independent runs: 471.75ms → 245.65ms after `ANALYZE` → 2.24ms with the
index (first run 225ms → 219ms → 1.5ms). These are **reference observations, not
acceptance thresholds** — run-to-run variance is real and the acceptance criterion
is the *plan shape* (seq scan → seq scan → index scan), never a millisecond
number. The `after_index` checkpoint must **not** be captured in Wave A: per
Global Constraints the agent cannot see or reference a post-index result because
none exists yet in `retrieval.*` — that is source truth, not a filter. Capturing
it early and hiding it would be exactly the dishonesty the two-wave model exists
to avoid.

- [ ] **Step 1: Write the failing test.**

```python
    def test_wave_a_captures_only_the_pre_index_checkpoints(self) -> None:
        from labs.incident.query_regression import WAVE_A_CHECKPOINTS, WAVE_B_CHECKPOINTS

        self.assertEqual(WAVE_A_CHECKPOINTS, ("before_analyze", "after_analyze"))
        self.assertEqual(WAVE_B_CHECKPOINTS, ("after_index",))
        self.assertNotIn("after_index", WAVE_A_CHECKPOINTS)

    def test_plan_checkpoints_assert_shape_not_timing(self) -> None:
        source = (REPO_ROOT / "labs" / "incident" / "query_regression.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("Seq Scan", source)
        self.assertIn("Index Scan", source)
        for forbidden in ("471.75", "245.65", "2.24", "225", "219", "1.5"):
            self.assertNotIn(
                f"execution_ms == {forbidden}", source,
                "timings are reference observations, never assertions",
            )
```

- [ ] **Step 2: Run it and confirm it fails.**

```bash
.venv/bin/python -m pytest backend/tests/test_incident_lab.py -k plan -v
```

Expected: FAIL — `ModuleNotFoundError: ... query_regression`.

- [ ] **Step 3: Implement the driver.** Create
  `labs/incident/query_regression.py` with the reference query as a module
  constant, `WAVE_A_CHECKPOINTS = ("before_analyze", "after_analyze")`,
  `WAVE_B_CHECKPOINTS = ("after_index",)`, and a `capture_plan_checkpoints`
  that runs `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` and parses the node type,
  actual rows, rows-removed-by-filter, and buffer counts out of the JSON plan
  rather than regexing the text form. Assert plan **shape**:
  `before_analyze` and `after_analyze` must both contain `Seq Scan`;
  `after_index` must contain `Index Scan`. Raise `LiveWorkshopError` if
  `after_analyze` shows an index scan — that would mean the missing-index finding
  is not reproducible on this instance and the lab's central conclusion is false.

- [ ] **Step 4: Run the tests.**

```bash
.venv/bin/python -m pytest backend/tests/test_incident_lab.py -k plan -v
```

Expected: PASS on both.

- [ ] **Step 5: Live-Aurora acceptance criteria.** Against the real 3M-row table:
  1. `before_analyze` and `after_analyze` both report `Seq Scan`, with
     `rows_removed_by_filter` in the millions (measured 2,400,000 of 3,000,000).
  2. `ANALYZE` measurably changes the estimate but **not** the plan shape — this
     is the finding Lab 2 establishes from evidence, so it must be genuinely true,
     not asserted.
  3. After the index exists, `after_index` reports `Index Scan` with
     `rows_removed_by_filter = 0` and a buffer count two orders of magnitude
     smaller (measured 53,038 → 23 buffers). Buffers are the honest signal here;
     timings vary, buffer counts barely do.
  4. Record the actual measured numbers from this run in the gate-results
     document as fresh reference observations. Do not reuse the earlier numbers as
     if they were this run's.

- [ ] **Step 6: Cleanup and failure recovery.** `EXPLAIN ANALYZE` genuinely runs
  the query, so each checkpoint costs real I/O; three checkpoints on a 3M-row seq
  scan is roughly 1.5 seconds total, immaterial. If a checkpoint fails mid-capture,
  re-running is safe (read-only). The `priority_tier` index created for Wave B is
  the participant's own object — the orchestrator must not drop it, or Lab 4's
  proof disappears.

- [ ] **Step 7: Participant-facing changes.** This is the substance of Lab 2's
  central finding and Lab 4's proof. Participant-facing copy must present the
  4-step reasoning sequence from the design spec (observe the slow query, read the
  plan, try `ANALYZE`, discover the missing access path) and must state the
  timings as observations from their own run, never as expected values to match.

- [ ] **Step 8: Commit.**

```bash
git add labs/incident/query_regression.py labs/incident/run_live_workshop.py \
  backend/tests/test_incident_lab.py
git commit -m "Add the query regression driver with plan checkpoints"
```

**Dependencies:** Tasks B1 and B1a (the reference query filters on
`priority_tier`, which Task B1a's `add_priority_tier_column` creates). Independent
of B2–B4 (no pool involvement), so it can be implemented in parallel with them, but
it must land before Phase C's evidence builder consumes its checkpoints.

### Task B6: Delete the Performance Insights collection path and rewrite the stale mechanism tests

**Owning schema/module:** `labs/incident/`.

**Files:**
- Modify: `labs/incident/capture_observability.py` — delete
  `MAX_PI_SQL_DOCUMENTS` (line 28), `_pi_rows` (95–117), `_points_in_window`
  (120–132), `_wait_for_database_insights` (135–237), `_validate_target`'s
  `PerformanceInsightsEnabled` assertion (63–66), the `preflight_aws_observability`
  PI probe (304, 322–329), and the `collect_aws_observability` PI wiring (355,
  364–370, 398, 405). **Keep** `_cloudwatch_samples` (240–290), `METRICS`, and
  `PERIOD_SECONDS = 60` as best-effort.
- Modify: `labs/incident/run_live_workshop.py` — delete `_sample_postgresql`'s
  9/9/6-row assertions (514–624) and replace with the new phase-derived shape;
  delete the `--pi-wait-seconds` CLI flag. **Delete
  `_measured_visibility` (`:887-908`) and `_PI_UNRESOLVED_STATEMENT` (`:884`) only
  after Task C1's replacement classifier exists.** That function is the sole
  producer of `visibility='restricted'` in the repository. Deleting it first
  produces a uniformly unrestricted corpus, and — until Task A2 makes the ACL
  explicit — silently: `admit_evidence` defaults an unlabelled record to `workshop`
  (`sql/10_admission.sql:418`). The optional-security consequence is that G-27
  exits 1 rather than BLOCKED on zero restricted rows (measured), so the optional
  RLS lab loses its release evidence; the core sweep is unaffected, because G-27 is
  a `SECURITY_GATES` entry that the default `gates/checks.sh` run does not execute.
  Task C1's Files block carries the replacement classifier, its three provenance
  fields, and the two `gates/rls_enforcement.py` remediation strings that go stale
  with it; read it before deleting this
- Modify: `backend/tests/test_incident_lab.py:27-37` (file-set assertion),
  `:39-43` (`OBSERVATION_COUNT`/`WRITER_COUNT`/`READER_COUNT`), `:86-131`
  (old lock-vocabulary string assertions)
- Modify: `backend/scripts/smoke_test.py:45-51` (`_live_keys()`'s fixed 5-key
  shape)
- Modify: `sql/01_schema.sql` — replace the retired relation-lock constraint and
  "ran the index build" renderer text with the measured transaction-ID wait
- Modify: `sql/04_diagnostics.sql` — replace the 30-sample,
  `Lock:relation`, fixed CloudWatch-count, and latest-single-capture readiness
  contract with four-phase, two-wave behavioral readiness
- Modify: `sql/10_admission.sql` — replace A2's temporary relation-lock
  validation with the final `Lock:transactionid` backfill contract
- Modify: `backend/tests/test_admission.py` and
  `backend/tests/test_release_capture.py` — replace old-mechanism fixtures and
  assertions with the final lock/readiness contract
- Test: `backend/tests/test_incident_lab.py`

**Interfaces:**
- Consumes: Tasks B1a and B2–B5's modules (the file-set assertion must list all
  five: `migration.py`, `lab_routes.py`, `hold_controller.py`,
  `recovery_verifier.py`, `query_regression.py`).
- Produces: a `capture_observability` module with CloudWatch only, and
  `run_live_workshop.py` with no PI dependency anywhere. Phase C builds on this.

**Migration and compatibility implications:** this is the change the entire
redesign exists for — PI Active Session History does not sample `idle in
transaction` backends, so the old mechanism's central wait could never appear in
PI, and no query could fix it. `_validate_target`'s `PerformanceInsightsEnabled`
assertion currently makes PI a **hard precondition**: leaving it in place means the
new mechanism still refuses to start on a cluster without PI, for no reason.
CloudWatch stays but is demoted to best-effort per Global Constraints: failures
record `"cloudwatch_status": "unavailable"` in receipt metadata and never raise.
`backend/scripts/smoke_test.py:45-51`'s `_live_keys()` assumes exactly 1 incident,
2 changes, 1 lock, and 1 fuzzy probe; the new mechanism's change cardinality
differs, so smoke will fail on a correct run until this is updated. The stale
tests at `:86-131` assert on the *old* SQL's exact lock vocabulary (`ShareLock`,
`pg_blocking_pids`); the new mechanism's vocabulary is `Lock:Transactionid` and
row locks, so these must be rewritten to the new mechanism's real vocabulary —
**not deleted**, or the tests stop guarding anything.

- [ ] **Step 1: Write the failing test.**

```python
    def test_no_performance_insights_dependency_remains(self) -> None:
        for name in ("capture_observability.py", "run_live_workshop.py"):
            source = (REPO_ROOT / "labs" / "incident" / name).read_text(encoding="utf-8")
            for forbidden in (
                "PerformanceInsightsEnabled",
                "MAX_PI_SQL_DOCUMENTS",
                "_wait_for_database_insights",
                "pi-wait-seconds",
                "performance_insights",
            ):
                self.assertNotIn(forbidden, source, f"{name} still references {forbidden}")

    def test_cloudwatch_is_best_effort(self) -> None:
        source = (REPO_ROOT / "labs" / "incident" / "capture_observability.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("_cloudwatch_samples", source)
        self.assertIn("cloudwatch_status", source)
        self.assertIn("unavailable", source)

    def test_incident_module_file_set(self) -> None:
        present = {
            path.name
            for path in (REPO_ROOT / "labs" / "incident").glob("*.py")
            if not path.name.startswith("_gate")
        }
        self.assertEqual(
            present,
            {
                "__init__.py",
                "capture_observability.py",
                "hold_controller.py",
                "migration.py",
                "query_regression.py",
                "recovery_verifier.py",
                "run_live_workshop.py",
            },
        )
```

- [ ] **Step 2: Run it and confirm it fails.**

```bash
.venv/bin/python -m pytest backend/tests/test_incident_lab.py -k "performance_insights or cloudwatch or file_set" -v
```

Expected: FAIL on all three — PI references present, and the file set still
missing the new modules.

- [ ] **Step 3: Delete the PI path and rewrite the stale tests.** Make the
  deletions listed in Files above. Rewrite `_sample_postgresql`'s assertions to
  the new mechanism's shape: at least one `pg_stat_activity` row per tagged
  session, at least one `pg_locks` row naming the backfill's relation, and at
  least one `pg_blocking_pids` row containing the backfill PID — presence-based,
  since the exact counts now vary with the condition-based hold's duration.
  Replace the `:86-131` lock-vocabulary assertions with the new vocabulary
  (`Lock`, `Transactionid`, `pg_blocking_pids`) and drop the `ShareLock` /
  `RowExclusiveLock`-granted pair, which belonged to the old `CREATE INDEX`
  mechanism. Update `_live_keys()` in `backend/scripts/smoke_test.py` to derive
  its key set from the admitted corpus rather than hardcoding five keys.

- [ ] **Step 4: Run the full test suite.**

```bash
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
ALLOW_TEST_DATABASE_RESET=1 make test
```

Expected: all tests pass. If any assertion was deleted rather than rewritten,
call it out in the commit message — a silently weakened test is worse than a
failing one.

- [ ] **Step 5: Live-Aurora acceptance criteria.** Run the full orchestrator
  end-to-end against the disposable database on a cluster with PI *disabled*, and
  confirm it completes. That is the definitive proof the dependency is gone:

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
LAB_ENDPOINTS_ENABLED=1 \
  .venv/bin/python -m labs.incident.run_live_workshop \
  --output-dir data/generated/incident-lab
```

  Acceptance criteria: exit 0; a receipt written to `data/generated/incident-lab`;
  `cloudwatch_status` present in receipt metadata; **zero** occurrences of
  `performance` or `insights` in the receipt JSON. Also run once with CloudWatch
  deliberately unreachable (revoke the metric permission or point at a bogus
  region) and confirm the run still exits 0 with
  `"cloudwatch_status": "unavailable"` — best-effort means best-effort.

- [ ] **Step 6: Cleanup and failure recovery.** Delete the six `_gate*.py`
  throwaway prototypes from `labs/incident/` once their findings are recorded in
  the gate-results document — the file-set test above will fail while they remain
  unless excluded, and they were explicitly throwaway. Use `trash`, not `rm -rf`.
  Remove `data/generated/incident-lab` after verification; it is gitignored
  generated output and must never be committed.

- [ ] **Step 7: Participant-facing changes.** Performance Insights and Database
  Insights disappear from the participant path entirely. `CLAUDE.md`'s statement
  that the evidence store "may index only PostgreSQL, CloudWatch, and Database
  Insights observations" must be updated to drop Database Insights — that line is
  a project rule, and leaving it stale makes the rule describe a capability that
  no longer exists.

- [ ] **Step 8: Commit.**

```bash
git add labs/incident/ backend/tests/test_incident_lab.py \
  backend/scripts/smoke_test.py CLAUDE.md
git commit -m "Delete the Performance Insights collection path"
```

**Dependencies:** Tasks B1a, B2, B3, B4, B5 — the file-set assertion names all five
new modules, so this task cannot pass until they exist. **Also Task C1**, out of
phase order: this task deletes `_measured_visibility` and C1 owns its replacement,
so deleting it first leaves the corpus with no restricted cohort, which costs the
optional RLS lab its release evidence (G-27 red when run by ID) while leaving the
core sweep green — a silent gap, which is the reason this dependency is written
down. Either implement C1 before this task, or leave those two functions in place
here and let C1 delete them — state in the report which you chose.

## Phase C — Retrieval Corpus

Owning modules: `labs/incident/` (evidence builder) and `backend/app/search_index.py`
(index rebuild). This phase turns Phase B's raw observations into searchable
documents and gets both waves indexed. Gate 5's finding governs everything here:
**numeric variation inside a fixed sentence template is not diversity.** The
sentence structure itself must vary per event.

### Task C1: Build the six-signal-type evidence builder

**Owning schema/module:** `labs/incident/`; new
`labs/incident/evidence_builder.py`.

**Files:**
- Create: `labs/incident/evidence_builder.py`
- Modify: `labs/incident/run_live_workshop.py` — call it after the recovery
  verifier
- Modify: `sql/12_masking.sql` — re-anchor the worked masking narrative on the
  captured `pg_stat_*` statement text and remove retired PI/index-repair examples
- Modify: `sql/11_roles_rls.sql` and `gates/masking_determinism.py` — replace
  retired Performance Insights and relation-lock examples without weakening the
  optional security assertions
- Modify: `gates/rls_enforcement.py` — point facilitator remediation to the new
  statement-text classifier
- Modify: `gates/persona_equivalence.py`, `backend/tests/test_db_persona.py`, and
  `backend/tests/test_rls_personas.py` — replace the old 110-row measured examples
  with final-run counts or count-free contract language
- Test: `backend/tests/test_evidence_builder.py` (new)

**Interfaces:**
- Consumes: Task B3's `HoldProof` (`samples` + `state_changes`), Task B4's
  `RecoveryProof`, Task B5's `list[PlanCheckpoint]`, and the hot-write outcome
  list from Task B2.
- Produces: `build_wave_a_documents(...) -> list[EvidenceDocument]` and
  `build_wave_b_documents(...) -> list[EvidenceDocument]`, where
  `EvidenceDocument` carries `key`, `signal_type` (one of `lock`, `pool`,
  `request`, `wal`, `meta`, `plan`), `phase`, `title`, `body`, `occurred_at`,
  `visibility` (`'workshop'` or `'restricted'`), and the three provenance fields
  `classifier_version: str`, `classification_reason: str`, and
  `classification_sources: list[str]`. Task C2 admits all four; Task C3 indexes
  the documents.

**The `visibility` field is load-bearing and must not be dropped as unused.**
Task B6 deletes `labs/incident/run_live_workshop.py:_measured_visibility`, which
is today the **only** producer of `visibility='restricted'` anywhere in the
repository — verified by grep. Everything downstream of it fails silently if
nothing replaces it:

- `casework.admit_evidence` defaults a record with no `acl` key to
  `'{"visibility":"workshop"}'` (`sql/10_admission.sql:418`). A builder that omits
  the field therefore produces a corpus with **zero** restricted rows, and no
  error anywhere. **Task A2 removes that silent default**, so after A2 an omitted
  ACL is a loud admission rejection rather than a silent relabel — but this task
  still owes the classification, because a rejection is not a corpus.
- G-27 (`gates/rls_enforcement.py`) treats zero restricted rows as an
  **assertion failure and exits 1**, not BLOCKED. Measured against
  `dat410_review_remediation_test` after Task A1: `restricted rows measured on the
  engine: 0`, then `assertion failed: retrieval_admin is named by every policy and
  holds can_see_restricted, so it is reading unfiltered: the capture holds no
  restricted evidence`.
- **Scope, exactly: G-27 is an optional-security gate, not a core release
  dependency.** It is registered in `SECURITY_GATES` (`gates/checks.sh:47`), not
  `CORE_GATES`, and the no-argument sweep both omits it and forces
  `WORKBENCH_SECURITY_ENABLED=0` (`:58`) — measured: a
  `WORKBENCH_SECURITY_ENABLED=1 FAIL_ON_BLOCKED=1 gates/checks.sh` run executed
  seven gates and G-27 was not among them. So an all-`workshop` corpus does **not**
  block Task G3's core freeze sweep; it blocks the optional RLS lab's release
  criteria in Global Constraints, and it does so silently unless someone runs the
  security gates by ID. That silence is the reason this classification is written
  here rather than left to whoever eventually runs G-27.
- The persona switcher and the ACL row-filtering assertions measure a cohort that
  would no longer exist. Lab 3's core path does **not** depend on it — see the
  Lab-3-stays-retrieval-first rule in Global Constraints — so this classification
  serves the optional module and the audit trail, not the one-hour path.

**Replacement classification, and why it is honest.** Classify on resolved
statement text from the two columns `sql/12_masking.sql` still masks:
`casework.pg_stat_activity_samples.query` and
`casework.pg_stat_statements_samples.queries`. A document whose structured payload
carries non-empty captured statement text gets `visibility='restricted'`;
everything else gets `'workshop'`. This is the same rule
`_measured_visibility` implemented, re-anchored from a Performance Insights
dimension onto a `pg_stat_*` column — the participant's own live query text,
captured in their own run, which is exactly what a real operator restricts and
exactly what the masking policies already protect. It invents no cohort and
labels no row by hand, so it holds under the live-data-only rule. Do **not**
substitute a hardcoded list of keys to mark restricted: that is authored data
wearing a classification's clothes.

**The classifier is deterministic and its decision is replayable, which means three
fields travel with every label.** Per the Global Constraints replayability rule, the
classifier is a single pure function and every document it labels carries:

- `classifier_version` — the literal `"statement-text/1"`. Bump the suffix if the
  rule itself ever changes, so an old corpus's labels stay interpretable. Define it
  as one module-level constant, not a string repeated per call site.
- `classification_reason` — a closed vocabulary of exactly three machine-readable
  values, never free prose: `"statement_text_present"` (restricted),
  `"no_statement_text"` (workshop), `"statement_text_empty"` (workshop; the field
  existed but held only whitespace, which is a genuinely different observation from
  its absence and is what the old `_PI_UNRESOLVED_STATEMENT` sentinel was papering
  over). A reader must be able to distinguish "this document had no statement" from
  "this document had a statement we could not resolve" without re-reading the
  corpus.
- `classification_sources` — the sample identifiers the decision was read from, as
  `"pg_stat_activity_samples:<sample_id>"` and
  `"pg_stat_statements_samples:<sample_id>"` strings. This is what makes the label
  replayable: a reviewer can go back to the exact rows and re-run the rule. It must
  be **non-empty whenever the reason is `statement_text_present`** — a restricted
  label with no source row is unprovable, and the test in Step 1 asserts it.

Determinism is a property to test, not to assert: the same input payload must
produce byte-identical `(visibility, classifier_version, classification_reason,
classification_sources)` on two separate calls, with `classification_sources` in a
stable sorted order. An unsorted list makes an otherwise-identical replay diff.

The rule is not vacuous on the new corpus, verified against the schema: every
`lock` document derives from a `pg_stat_activity` sample row that carries the
blocked writer's `UPDATE` and the backfill transaction's statement, and `plan`
documents carry the reference query. `pool` and `request` documents describe
connection outcomes with no statement text and stay `workshop`, which gives the
corpus a genuine mix rather than a uniform label. That mix is what the optional
lab's release criterion (2) in Global Constraints requires, and this task is the
only place it can come from.

**Also fix the two stale remediation strings this replacement invalidates**, in
`gates/rls_enforcement.py:663-667` and `:686-691`. Both currently end
`Re-run make live-workshop against a cluster with Database Insights advanced mode
enabled` and one cites
`labs/incident/run_live_workshop.py:_measured_visibility` by name. After Task A1
that advice is impossible to follow and after Task B6 the cited function does not
exist, so a facilitator hitting a genuinely empty capture is sent to a deleted
feature. Rewrite both to name the new classifier and the `pg_stat_activity`
statement-text condition. Task A1 deliberately left this file alone (its capture
table list is catalog-discovered, so it needed no edit there); these two strings
are this task's to correct because this task creates the mechanism they describe.

**Migration and compatibility implications:** the old builder emitted exactly 30
each of `activity_window` / `lock_topology` / `blocking_chain` — time-sliced
snapshots of the same signal, which is precisely the pattern Gate 5 proved
produces 100% within-category near-duplicates. The new builder emits **one
document per genuinely distinct event**, with per-event structural variation.
Concretely, from Gate 5's passing 51-document sample: `lock` documents describe a
specific writer entering *or* leaving a wait (2 per blocked writer, ~20 total);
`pool` documents describe state *transitions* (empty → filling → saturated →
draining → recovered, ~10 total); `request` documents are one per distinct
*outcome class* actually observed (~3); `wal` documents are progress *milestones*
in different structural terms (~5); `meta` documents are lifecycle events (~10);
`plan` documents are exactly the checkpoints (2 in Wave A, 1 in Wave B). That
totals ~50–51, matching the DECIDED 50–80 expectation. `TEL-LOCK` will still show
an elevated within-category near-duplicate rate (measured 42.6%) because 10
blocked writers produce inherently similar descriptions — that is accepted, the
10 blocked writers is a contract from `DB_POOL_MAX_SIZE` and is not changing, and
the aggregate stays well under 15%.

**Gate 5's retired sample bodies encoded the wrong outcome distribution and must
not be reconstructed or copied verbatim.** The prototype preserved in historical
commit `c9ca891` was written
against Gate 1's measurements: nine writers cancelled by a 3-second
`statement_timeout` and one `pool_timeout`. Under the corrected contract the real
run produces **ten writers that block and then commit** plus **two requests that
never obtained a connection**. The builder's per-signal *structure* is what Gate 5
validated and what carries forward; its *numbers and outcome vocabulary* are stale.
Specifically:
- `lock` documents pair "entered a `Lock:transactionid` wait against the open
  backfill transaction" with "acquired its lock and committed after the backfill
  released," **not** with "was canceled by its own 3-second statement_timeout."
- The queued requests get their **own** differently-shaped `request` document —
  they never appear in `pg_stat_activity`, never entered a lock wait, and so must
  never be described as blocked. This distinction is the pool-exhaustion signal
  and the single most important thing the corpus has to teach.
- `request` outcome classes for a healthy run are `committed` (10) and
  `pool_timeout` (2). A `statement_timeout` class appearing in a real run is a
  Phase B regression that Task B4's assertion 6 rejects before the builder ever
  sees it; the builder needs no branch for it.
- The document describing the incident's end is "the ten blocked writers drained
  successfully," not Gate 5's "no hot-write request completed successfully during
  the proven hold." The drain **is** the recovery, and it is the honest ending.

- [ ] **Step 1: Write the failing test.** Create
  `backend/tests/test_evidence_builder.py`:

```python
"""Evidence builder tests. Pure functions -- no database required."""
from __future__ import annotations

import unittest

from labs.incident.evidence_builder import (
    CLASSIFIER_VERSION,
    CLASSIFICATION_REASONS,
    SIGNAL_TYPES,
    build_wave_a_documents,
    build_wave_b_documents,
    classify_visibility,
)


class VisibilityClassifierTests(unittest.TestCase):
    """The classifier is the only producer of visibility='restricted' after the
    Performance Insights path is deleted. Its decision must be deterministic and
    replayable from the recorded reason and source sample IDs alone.
    """

    def test_version_is_a_single_constant(self) -> None:
        self.assertEqual(CLASSIFIER_VERSION, "statement-text/1")

    def test_reason_vocabulary_is_closed(self) -> None:
        self.assertEqual(
            CLASSIFICATION_REASONS,
            ("statement_text_present", "no_statement_text", "statement_text_empty"),
        )

    def test_resolved_statement_text_is_restricted_with_its_sources(self) -> None:
        decision = classify_visibility(
            {
                "statement": "UPDATE workbench_lab.orders SET priority_tier = 2",
                "activity_sample_ids": [41, 7],
                "statements_sample_ids": [3],
            }
        )
        self.assertEqual(decision.visibility, "restricted")
        self.assertEqual(decision.reason, "statement_text_present")
        self.assertEqual(decision.classifier_version, CLASSIFIER_VERSION)
        self.assertEqual(
            decision.sources,
            (
                "pg_stat_activity_samples:7",
                "pg_stat_activity_samples:41",
                "pg_stat_statements_samples:3",
            ),
            "sources must be sorted so two replays diff identically",
        )

    def test_absent_and_empty_statement_text_are_different_reasons(self) -> None:
        absent = classify_visibility({"pool_available": 0})
        self.assertEqual(absent.visibility, "workshop")
        self.assertEqual(absent.reason, "no_statement_text")
        empty = classify_visibility(
            {"statement": "   ", "activity_sample_ids": [9]}
        )
        self.assertEqual(empty.visibility, "workshop")
        self.assertEqual(empty.reason, "statement_text_empty")

    def test_restricted_without_a_source_row_is_rejected(self) -> None:
        """An unprovable restricted label is worse than no label: nothing can
        replay it, so nothing can distinguish it from a hand-written one.
        """
        with self.assertRaises(ValueError):
            classify_visibility({"statement": "SELECT 1"})

    def test_classification_is_byte_identical_on_replay(self) -> None:
        payload = {
            "statement": "UPDATE workbench_lab.orders SET priority_tier = 2",
            "activity_sample_ids": [41, 7],
        }
        first = classify_visibility(payload)
        second = classify_visibility(payload)
        self.assertEqual(first, second)


class EvidenceBuilderTests(unittest.TestCase):
    def test_every_document_carries_replayable_classification(self) -> None:
        for document in build_wave_a_documents(**self._fixture_free_inputs()):
            with self.subTest(key=document.key):
                self.assertIn(document.visibility, ("workshop", "restricted"))
                self.assertEqual(document.classifier_version, CLASSIFIER_VERSION)
                self.assertIn(document.classification_reason, CLASSIFICATION_REASONS)
                if document.visibility == "restricted":
                    self.assertTrue(
                        document.classification_sources,
                        "a restricted label with no source sample is unprovable",
                    )

    def test_wave_a_corpus_is_genuinely_mixed(self) -> None:
        """A uniform corpus proves nothing about row filtering, which is the
        optional RLS lab's entire subject. This is measured here on the pure
        builder so a uniform run fails before it ever reaches admission.
        """
        visibilities = {
            document.visibility
            for document in build_wave_a_documents(**self._fixture_free_inputs())
        }
        self.assertEqual(visibilities, {"workshop", "restricted"})

    def test_signal_types_are_the_six_from_the_design(self) -> None:
        self.assertEqual(
            SIGNAL_TYPES, ("lock", "pool", "request", "wal", "meta", "plan")
        )

    def test_wave_a_covers_every_signal_type_except_none(self) -> None:
        documents = build_wave_a_documents(**self._fixture_free_inputs())
        covered = {doc.signal_type for doc in documents}
        self.assertEqual(covered, set(SIGNAL_TYPES))

    def test_wave_a_emits_no_post_index_plan_checkpoint(self) -> None:
        documents = build_wave_a_documents(**self._fixture_free_inputs())
        plans = [doc for doc in documents if doc.signal_type == "plan"]
        self.assertEqual(len(plans), 2)
        self.assertNotIn("after_index", " ".join(doc.key for doc in plans))

    def test_documents_are_fewer_than_raw_poll_samples(self) -> None:
        inputs = self._fixture_free_inputs()
        documents = build_wave_a_documents(**inputs)
        self.assertLess(
            len(documents),
            len(inputs["hold_proof"].samples),
            "one document per poll tick violates the control-not-generation rule",
        )

    def test_wave_b_adds_new_facts_not_restatements(self) -> None:
        inputs = self._fixture_free_inputs()
        wave_a = build_wave_a_documents(**inputs)
        wave_b = build_wave_b_documents(**self._wave_b_inputs())
        self.assertTrue(wave_b)
        overlap = {doc.key for doc in wave_a} & {doc.key for doc in wave_b}
        self.assertEqual(overlap, set(), "Wave B must not reuse Wave A keys")

    def test_queued_requests_are_never_described_as_blocked(self) -> None:
        """A request that never obtained a connection never entered a lock wait
        and never appeared in pg_stat_activity. Describing it as blocked collapses
        the two signals the corpus exists to distinguish.
        """
        documents = build_wave_a_documents(**self._fixture_free_inputs())
        queued = [doc for doc in documents if "pool_timeout" in doc.body]
        self.assertTrue(queued, "the queued requests must produce their own document")
        for doc in queued:
            self.assertNotIn("Lock:transactionid", doc.body)
            self.assertNotIn("entered a", doc.body)

    def test_no_document_claims_a_statement_timeout(self) -> None:
        """Gate 1's nine statement_timeouts were an artifact of its own 3-second
        setting. Under the shipped '40s' policy the blocked writers drain, and a
        statement_timeout is a regression Task B4 rejects before this builder runs.
        """
        documents = build_wave_a_documents(**self._fixture_free_inputs())
        for doc in documents:
            self.assertNotIn("statement_timeout", doc.body)
            self.assertNotIn("statement timeout", doc.body)

    def test_drain_is_recorded_as_the_recovery(self) -> None:
        documents = build_wave_a_documents(**self._fixture_free_inputs())
        bodies = " ".join(doc.body for doc in documents)
        self.assertIn("committed", bodies)
        self.assertNotIn(
            "No hot-write request completed successfully", bodies,
            "the ten blocked writers drain on commit; that is the recovery",
        )
```

  `_fixture_free_inputs()` constructs `HoldProof` / `RecoveryProof` /
  `PlanCheckpoint` objects **in the test** from plausible values. This is not a
  fixture in the live-data-only sense — it is a unit test of a pure function, and
  the values never enter any database or participant path. The live-data-only rule
  governs the participant path, not unit tests of pure formatting logic.

- [ ] **Step 2: Run it and confirm it fails.**

```bash
.venv/bin/python -m pytest backend/tests/test_evidence_builder.py -v
```

Expected: FAIL — `ModuleNotFoundError: ... evidence_builder`.

- [ ] **Step 3: Implement the builder.** Create
  `labs/incident/evidence_builder.py`. Per signal type, generate from real
  measurements with **structural** variation, following Gate 5's passing pattern.
  For `lock`, two differently-shaped sentences per **blocked** writer (entering the
  wait vs. acquiring the lock and committing when the backfill released). The
  queued requests produce no `lock` documents at all — they never reached a lock
  wait — and are described only in `request` and `pool` documents, in different
  language. For
  `pool`, one document per `HoldProof.state_changes` entry, each describing a
  different *kind* of transition. For `request`, one per distinct outcome class
  present in the hot-write results. For `wal`, milestones in different structural
  terms. For `meta`, lifecycle events as `title: body`. For `plan`, one per
  checkpoint with the real plan node type, buffers, and rows-removed.

  Do **not** loop a fixed count over one sentence template. The module docstring
  must say why, citing Gate 5's 20.65% failure, so the next person to touch it
  does not reintroduce the bug.

  The classifier is the other half of this module. Write it as one pure function
  with one version constant and one closed reason vocabulary, and have every
  document construction path call it — never inline the rule at a call site:

```python
CLASSIFIER_VERSION = "statement-text/1"
CLASSIFICATION_REASONS = (
    "statement_text_present",
    "no_statement_text",
    "statement_text_empty",
)


@dataclass(frozen=True)
class VisibilityDecision:
    """One replayable classification: the label plus everything needed to redo it."""

    visibility: str
    reason: str
    classifier_version: str
    sources: tuple[str, ...]


def _sources(structured: Mapping[str, Any]) -> tuple[str, ...]:
    collected: list[str] = []
    for key, table in (
        ("activity_sample_ids", "pg_stat_activity_samples"),
        ("statements_sample_ids", "pg_stat_statements_samples"),
    ):
        for sample_id in structured.get(key) or ():
            collected.append(f"{table}:{int(sample_id)}")
    return tuple(sorted(collected))


def classify_visibility(structured: Mapping[str, Any]) -> VisibilityDecision:
    """Classify one measured observation by whether it carries statement text.

    Statement text is the one thing in this capture a real operator restricts,
    and it is what `sql/12_masking.sql` already protects on
    `casework.pg_stat_activity_samples.query` and
    `casework.pg_stat_statements_samples.queries`. Reading the captured payload
    is what keeps the label measured rather than authored.

    Args:
        structured: The measured payload for one evidence document.

    Returns:
        The label, the machine-readable reason, the classifier version, and the
        sorted sample identifiers the decision was read from.

    Raises:
        ValueError: A restricted label carries no source sample, which would make
            it unprovable on replay.
    """
    sources = _sources(structured)
    statement = structured.get("statement")
    if not isinstance(statement, str):
        return VisibilityDecision("workshop", "no_statement_text", CLASSIFIER_VERSION, sources)
    if not statement.strip():
        return VisibilityDecision(
            "workshop", "statement_text_empty", CLASSIFIER_VERSION, sources
        )
    if not sources:
        raise ValueError(
            "restricted classification requires at least one source sample id; "
            f"got statement text with no activity_sample_ids or statements_sample_ids: "
            f"{sorted(structured)}"
        )
    return VisibilityDecision(
        "restricted", "statement_text_present", CLASSIFIER_VERSION, sources
    )
```

  Note what the old `_PI_UNRESOLVED_STATEMENT = "unknown"` sentinel becomes: it is
  **deleted, not ported**. It existed because Performance Insights substituted the
  literal string `"unknown"` for query text it could not resolve; `pg_stat_activity`
  has no such convention, and a real captured statement could legitimately be the
  word `unknown`. `statement_text_empty` covers the honest case — the field was
  present but held nothing — without a magic string that could match real data.

- [ ] **Step 4: Run the tests.**

```bash
.venv/bin/python -m pytest backend/tests/test_evidence_builder.py -v
```

Expected: PASS — the six `VisibilityClassifierTests` plus the ten
`EvidenceBuilderTests`, with no skips. A skip here means the module did not import.

- [ ] **Step 5: Live-Aurora acceptance criteria.** Run the real orchestrator, then
  measure the real generated corpus with the same server-side `pg_trgm` self-join
  Gate 5 proved (that recorded logic becomes a permanent gate in Task C4):
  1. Document count lands in **50–80**. Outside that range is not an automatic
     failure — it is a signal to check whether events were padded or dropped, and
     the actual number gets recorded either way.
  2. Overall near-duplicate rate (trigram similarity > 0.6) is **under 15%**.
  3. Every one of the six signal types has at least one document.
  4. Every one of the four phases has at least one document.
  5. `plan` documents in Wave A number exactly 2, and none mentions the index.
  6. The corpus is genuinely **mixed**: both `workshop` and `restricted` documents
     are present, and the counts are recorded. This is optional-security release
     criterion (2) from Global Constraints, and this run is the only place it can
     be measured — G-27 can confirm the mix exists but cannot create it. Record the
     two counts and the classifier version verbatim; a uniform corpus here means
     the classifier did not fire and must be diagnosed now, not at freeze time.

- [ ] **Step 6: Cleanup and failure recovery.** The builder is pure — a failure
  produces no database state. If the diversity check fails, redesign the offending
  category's *structure* (as Gate 5's second attempt did), never widen the
  similarity threshold and never pad with extra documents to dilute the rate.
  Both of those are the failure mode this task exists to prevent.

- [ ] **Step 7: Participant-facing changes.** Every document the participant
  retrieves in Labs 2–4 comes from here. The bodies are participant-facing prose
  and must obey the Global Constraints terminology rules exactly: "online schema
  and data migration," never "upgrade"; "evidence-backed finding," never "incident
  diagnosis."

- [ ] **Step 8: Commit.**

```bash
git add labs/incident/evidence_builder.py labs/incident/run_live_workshop.py \
  backend/tests/test_evidence_builder.py
git commit -m "Add the six-signal-type evidence builder"
```

**Dependencies:** Tasks B3, B4, B5 (it consumes all three of their outputs).

### Task C2: Wire the two-wave admission calls

**Owning schema/module:** `labs/incident/`; `casework` via
`casework.admit_evidence`.

**Files:**
- Modify: `labs/incident/run_live_workshop.py` — `_admit_payload` (1461–1471) and
  `_verify_live_run` (1518–1659); add a Wave B entry point; make `main()`'s
  prepare and cleanup calls wave-aware (step 3a — without it Wave B cannot run at
  all, and Lab 4's table is destroyed at the end of Lab 1)
- Modify: `backend/scripts/doctor.py` — resolve one incident with Wave A and Wave
  B instead of requiring exactly one capture or deriving Wave A keys from the
  latest capture suffix
- Modify: `backend/app/insights.py` — make `_latest_live_run` return the
  two-wave incident without requiring a retired `remediated` edge
- Modify: `backend/tests/test_retrieval_integration.py` — derive Wave A and Wave B
  identities separately and assert the additive corpus
- Test: `backend/tests/test_incident_lab.py`

**Interfaces:**
- Consumes: Task A3's wave-aware `casework.admit_evidence(jsonb)`, Task C1's
  documents — **including each document's `visibility` field and its three
  provenance fields**, emitted into every record as:

```json
"acl": {
  "visibility": "restricted",
  "classifier_version": "statement-text/1",
  "classification_reason": "statement_text_present",
  "classification_sources": ["pg_stat_activity_samples:41"]
}
```

  All four keys are required per record. `visibility` is what the retrieval
  predicates read; the other three are what make the label auditable and replayable
  per the Global Constraints replayability rule, and Task A2's admission contract
  rejects a record missing any of them. Emitting `visibility` alone leaves a corpus
  whose labels cannot be re-derived, which is indistinguishable on inspection from
  hand-labelled data. Dropping the `acl` object entirely is a loud admission
  rejection after Task A2 — before A2 it was a silent relabel to `workshop`
  (`sql/10_admission.sql:418`'s `coalesce`), which is the defect A2 removes. C1's
  Files block explains the classification and the closed reason vocabulary.
- Produces: `admit_wave_a(conn, documents, ...) -> AdmissionReceipt` and
  `admit_wave_b(conn, documents, *, incident_key, ...) -> AdmissionReceipt`, plus
  a `--wave {A,B}` CLI flag on `run_live_workshop.py`. Lab 4 (Phase D) invokes the
  Wave B path.

**Migration and compatibility implications:** `_admit_payload` currently calls
`SELECT casework.admit_evidence(%s::jsonb)` with a single payload and no wave
concept. Wave B needs its **own** capture ID, run suffix, observation window, and
receipt — only `incident_key` is shared (Task A3). The Wave B call must therefore
run a genuine, bounded, *second* observation window around the participant's
`CREATE INDEX`, not reuse Wave A's window; reusing it would mean claiming the
post-index plan was observed during the incident, which is false.
`_verify_live_run` calls `casework.assert_live_capture_ready()` at line 1605 —
that function is `SECURITY DEFINER` (changed when a masked predicate broke
`make doctor`) and its checks must accept a two-wave corpus, or Wave B admission
succeeds and verification then fails.

**Two lifecycle guards in `main()` make Wave B impossible today.** Adding the
`--wave` flag without fixing both produces a flag that cannot be used; step 3a
covers them and is not optional:

1. `main()` calls `_prepare_lab` unconditionally (`run_live_workshop.py:1812`), and
   `_prepare_lab` (`:308-340`) calls `_assert_empty_evidence_store` (`:148-160`),
   which raises `LiveWorkshopError` when **any** non-deleted
   `casework.evidence_items` row exists. Wave A's whole purpose is to write those
   rows. So `--wave B` aborts on the corpus Wave A just created — before it reaches
   any admission code. The careless fix (skip `_prepare_lab` entirely for Wave B)
   is also wrong: it skips `_assert_no_live_lab_sessions`, the only guard against
   two participants colliding on one database.
2. `main()` calls `_cleanup_lab` at `:1932-1934` unless `--keep-lab-schema` is
   passed, and that flag (`:1779-1783`) is `action="store_true"`, defaulting to
   **False**. `_cleanup_lab` runs `DROP SCHEMA IF EXISTS workbench_lab CASCADE`
   (`:1740`). So a successful Lab 1 run ends by destroying the 3,000,000-row table
   that Labs 2, 3, and 4 all query, and the participant's Lab 4 index with it.
   `--keep-lab-schema` appears nowhere in this plan or the design spec, so nothing
   currently tells the participant or the facilitator to pass it. Fixing the
   default is better than documenting the flag: a workshop that depends on every
   participant remembering a CLI flag will lose participants.

- [ ] **Step 1: Write the failing test.**

```python
    def test_orchestrator_exposes_both_wave_entry_points(self) -> None:
        source = (REPO_ROOT / "labs" / "incident" / "run_live_workshop.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def admit_wave_a", source)
        self.assertIn("def admit_wave_b", source)
        self.assertIn('"--wave"', source)
        wave_b = source.split("def admit_wave_b")[1].split("\ndef ")[0]
        self.assertIn("incident_key", wave_b)
        self.assertIn('"wave": "B"', wave_b)
```

  And the two lifecycle guards, which are behavioural rather than textual —
  `_assert_empty_evidence_store` must stop being reachable on Wave B, and cleanup
  must stop being the default:

```python
    def test_wave_b_does_not_require_an_empty_evidence_store(self) -> None:
        """Wave A writes the corpus Wave B is told to be empty of.

        _prepare_lab -> _assert_empty_evidence_store raises whenever any
        non-deleted casework.evidence_items row exists, so before this fix
        `--wave B` aborted on Wave A's own output. Calling the wave-B preparer
        against a NON-empty store is the whole assertion.
        """
        with self._owner_conn() as conn:
            conn.execute(
                "SELECT casework.admit_evidence(%s::jsonb)", (self._minimal_wave_a(),)
            )
            existing = conn.execute(
                "SELECT count(*) FROM casework.evidence_items WHERE NOT is_deleted"
            ).fetchone()[0]
        self.assertGreater(existing, 0, "fixture must leave a non-empty store")
        _prepare_lab_for_wave(OWNER_DSN, uuid.uuid4(), wave="B")  # must not raise

    def test_wave_b_preparation_still_refuses_colliding_sessions(self) -> None:
        """The careless fix -- skipping _prepare_lab for Wave B -- also skips the
        only guard against two participants sharing one database. Wave B must drop
        the emptiness check and KEEP the session check."""
        with psycopg.connect(OWNER_DSN) as squatter:
            squatter.execute("SET application_name = 'workbench-live-squatter'")
            squatter.execute("SELECT 1")
            with self.assertRaises(LiveWorkshopError):
                _prepare_lab_for_wave(OWNER_DSN, uuid.uuid4(), wave="B")

    def test_the_lab_schema_survives_a_successful_run_by_default(self) -> None:
        """Labs 2-4 all query workbench_lab.orders, and Lab 4's index lives there.

        --keep-lab-schema was action="store_true", so the DEFAULT was to
        DROP SCHEMA workbench_lab CASCADE at the end of a successful Lab 1 run --
        destroying the 3,000,000-row table the rest of the workshop depends on. The
        flag is not documented anywhere in the plan or the spec, so no participant
        would have passed it.
        """
        parsed = _parser().parse_args(_MINIMAL_ARGV)
        self.assertTrue(
            parsed.keep_lab_schema,
            "the lab schema must survive by default; Labs 2-4 need the table",
        )
        source = (REPO_ROOT / "labs" / "incident" / "run_live_workshop.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("--drop-lab-schema", source)
```

- [ ] **Step 2: Run it and confirm it fails.**

```bash
.venv/bin/python -m pytest backend/tests/test_incident_lab.py -k wave -v
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
ALLOW_TEST_DATABASE_RESET=1 \
  .venv/bin/python -m pytest backend/tests/test_incident_lab.py -k "wave_b or lab_schema_survives" -v
```

Expected: the entry-point test FAILs with `'def admit_wave_a' not found`; the
Wave B preparation test FAILs with `LiveWorkshopError: the participant corpus is
not empty`; the survival test FAILs with `keep_lab_schema` being `False`. Those are
three distinct failures and all three must appear — a single collapsed failure
means the fixture, not the code, is what broke.

- [ ] **Step 3: Implement both admission paths.** Split `_admit_payload` into
  `admit_wave_a` and `admit_wave_b`. Wave B builds its payload with
  `"wave": "B"`, its own fresh capture ID / run suffix / observation window
  bracketing the index creation, and the `incident_key` read from the Wave A
  corpus. Add the `--wave {A,B}` CLI flag defaulting to `A`. Add a `validates`
  relationship row linking Wave B's plan checkpoint to Wave A's finding (this is
  why Task A3 widened the CHECK).

- [ ] **Step 3a: Make preparation wave-aware and stop dropping the schema.** Both
  edits are in `labs/incident/run_live_workshop.py`.

  First, split the emptiness check out of the shared preparation path. Keep the
  session check on **both** waves — it is the collision guard, not a wave concern:

```python
def _prepare_lab_for_wave(
    database_url: str,
    capture_id: uuid.UUID,
    *,
    wave: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prepare for one wave's capture.

    Wave A requires an empty evidence store: it is the first capture of a fresh
    workshop database and a non-empty store means this run would mix with someone
    else's. Wave B requires the OPPOSITE -- it validates the finding Wave A
    admitted, so an empty store means Wave A never ran and the participant has
    skipped to Lab 4. Both waves keep the session check.
    """
    with _connect(database_url, f"workbench-live-setup-{wave.lower()}",
                  autocommit=True) as connection:
        _assert_no_live_lab_sessions(connection)
        if wave == "A":
            _assert_empty_evidence_store(connection)
        else:
            _assert_wave_a_corpus_present(connection)
        ...  # identity + before-state reads, unchanged from _prepare_lab
```

  `_assert_wave_a_corpus_present` is the mirror image, and it is a real check
  rather than a comment: it must raise `LiveWorkshopError` naming Lab 1 when the
  store holds no Wave A evidence, so a participant who runs `--wave B` first gets
  told what to do instead of a confusing downstream failure.

  Replace `_prepare_lab`'s two call sites with `_prepare_lab_for_wave(...,
  wave=args.wave)`. Do not leave `_prepare_lab` in place as a wrapper — per the
  coding standards, replace rather than deprecate.

  Second, invert the cleanup flag. Replace `--keep-lab-schema` with
  `--drop-lab-schema` (`action="store_true"`, default False) and change
  `main()`'s guard at `:1932-1934` to `if args.drop_lab_schema:`. Keep
  `_cleanup_lab` itself unchanged — its live-session refusal is correct and Gate 4
  proved the rebuild path. The rename is the point: an inverted flag whose absence
  destroys data is a footgun, and no participant passes a flag nobody told them
  about.

  **Rehearsal-time consequence, not a side note:** every existing invocation that
  relied on the old default now leaves 3,000,000 rows behind. Task G1 step 6's
  between-rehearsal reset must pass `--drop-lab-schema` explicitly, or repeated
  rehearsals accumulate storage.

- [ ] **Step 4: Run the tests.**

```bash
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
ALLOW_TEST_DATABASE_RESET=1 make test
```

Expected: PASS.

- [ ] **Step 5: Live-Aurora acceptance criteria.** Run Wave A, create the index by
  hand (standing in for the participant), then run Wave B:

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
LAB_ENDPOINTS_ENABLED=1 \
  .venv/bin/python -m labs.incident.run_live_workshop --wave A \
  --output-dir data/generated/incident-lab

psql -X -v ON_ERROR_STOP=1 \
  "postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" <<'SQL'
DO $guard$ BEGIN
  IF current_database() <> 'dat410_review_remediation_test' THEN
    RAISE EXCEPTION 'SAFETY ABORT: connected to %', current_database();
  END IF;
END $guard$;
CREATE INDEX idx_orders_priority_created
  ON workbench_lab.orders (priority_tier, created_at DESC);
SQL

DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
LAB_ENDPOINTS_ENABLED=1 \
  .venv/bin/python -m labs.incident.run_live_workshop --wave B \
  --output-dir data/generated/incident-lab
```

  Acceptance criteria: both exit 0; two receipts written; `casework` shows exactly
  one incident, two capture runs, two distinct `ingest_receipts` rows, at least one
  `validates` relationship; and re-running the Wave B command returns
  `idempotent_replay: true` while adding zero rows. Then run
  `gates/wave_additivity.py` (G-32) and confirm it goes from BLOCKED to **PASS** —
  that transition is the acceptance signal.

  **The `CREATE INDEX` between the two runs is the acceptance test for step 3a**,
  not incidental scaffolding. Note that neither command passes a schema flag: with
  the old default, the Wave A run would have dropped `workbench_lab` on its way out
  and this `CREATE INDEX` would fail with `relation "workbench_lab.orders" does not
  exist`. If you see that error, step 3a's flag inversion was not applied. Confirm
  the table and index both survive:

```bash
psql -X -v ON_ERROR_STOP=1 \
  "postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" <<'SQL'
DO $guard$ BEGIN
  IF current_database() <> 'dat410_review_remediation_test' THEN
    RAISE EXCEPTION 'SAFETY ABORT: connected to %', current_database();
  END IF;
END $guard$;
SELECT to_regclass('workbench_lab.orders') IS NOT NULL AS table_survived,
       (SELECT count(*) FROM workbench_lab.orders) AS rows_survived,
       to_regclass('workbench_lab.idx_orders_priority_created') IS NOT NULL
         AS index_survived;
SQL
```

Expected: `table_survived = t`, `rows_survived = 3000000`, `index_survived = t`.

- [ ] **Step 6: Cleanup and failure recovery.** A failed Wave B leaves Wave A
  intact by construction (Task A3 step 6 verified this). If Wave B fails after the
  index exists, re-running is safe: the index is idempotent-by-existence and the
  admission is idempotent-by-content-hash. Do **not** drop the participant's index
  as part of cleanup — it is their proof artifact.

  Cleanup is now **explicit**, per step 3a: a run that should reclaim the
  3,000,000-row table must pass `--drop-lab-schema`. Reclaim between rehearsals,
  never during a session — dropping the schema mid-workshop takes Labs 2 through 4
  with it.

- [ ] **Step 7: Participant-facing changes.** The participant now gets two
  receipts: a diagnostic receipt closing Lab 1 and a validation receipt closing
  Lab 4. Both must be presented as separate, permanent records — never as a
  before/after where the earlier one is superseded.

- [ ] **Step 8: Commit.**

```bash
git add labs/incident/run_live_workshop.py backend/tests/test_incident_lab.py
git commit -m "Wire the two-wave admission calls"
```

**Dependencies:** Task A3 (the wave-aware admission function) and Task C1 (the
documents to admit).

### Task C3: Make the index rebuild additive across waves, and resolve run_graph pinning

**Owning schema/module:** `backend/app/search_index.py`, `backend/app/insights.py`.

**Files:**
- Modify: `labs/incident/run_live_workshop.py:1474-1516` (`_build_search_index`)
- Modify: `backend/app/insights.py:581-616` (`run_graph`) and its call from
  `run_timeline` (line 706)
- Test: `backend/tests/test_search_index.py`

**Interfaces:**
- Consumes: Task C2's two-wave corpus.
- Produces: an index rebuild that is additive across waves, and a `run_graph`
  whose traversal is scoped to the run's own admission window.

**Migration and compatibility implications:** Gate 3 proved
`rebuild_search_index()` does not spuriously demote unrelated evidence — all 8
`is_current = false` sites are provably scoped (2 join-scoped via
`previous.evidence_id`, 2 parameter-bound, 2 `ON CONFLICT (document_version_id)`,
2 `NOT EXISTS` chunk-scoped), and 103/103 evidence items retained `is_current`
across a real full rebuild with unchanged content hashes. The deterministic
`document_version_id` = uuid5(`evidence_id:version:search_document_hash`) makes
the rebuild idempotent and additive. So Wave B needs **no change** to the demotion
logic — only a scoped invocation. `_build_search_index` already passes
`source_systems=[SOURCE_SYSTEM]` and `batch_size=48`, and writes a run-scoped
`embeddings-{run_suffix}.jsonl`; Wave B has its own run suffix so the collision
check still holds.

**The unresolved `run_graph` pinning question, now resolved:**
`backend/app/insights.py:581-616` reads
`SELECT DISTINCT evidence_id FROM proof.retrieval_candidates WHERE run_id = %s`
(line 588) — correctly pinned, since `proof.retrieval_candidates` is immutable per
run (Gate 2 proved a later write against `casework.evidence_items` leaves replayed
candidates unchanged at 15/15). But it then **live-calls**
`SELECT * FROM retrieval.traverse_evidence(%s::uuid[], 2)` (lines 599–603), which
walks the graph *as it exists now*. After Wave B, a replayed Lab 3 graph would
surface Wave B edges the agent never saw. **Resolution: scope the traversal to
edges whose evidence was admitted at or before the run's own admission window.**
This preserves the honest claim — the replayed graph shows what was traversable
then — without building the `as_of_admission_id` machinery the design spec
explicitly said not to build. `run_timeline` (line 706) calls the same function
and inherits the fix.

- [ ] **Step 1: Write the failing test.**

```python
    def test_run_graph_traversal_is_scoped_to_the_run_window(self) -> None:
        source = (REPO_ROOT / "backend" / "app" / "insights.py").read_text(encoding="utf-8")
        body = source.split("def run_graph")[1].split("\ndef ")[0]
        self.assertIn("traverse_evidence", body)
        self.assertIn("observation_window_end", body)
        self.assertNotIn(
            "traverse_evidence(%s::uuid[], 2)\n", body,
            "unscoped live traversal would leak Wave B edges into a replayed Wave A graph",
        )
```

- [ ] **Step 2: Run it and confirm it fails.**

```bash
.venv/bin/python -m pytest backend/tests/test_search_index.py -k run_graph -v
```

Expected: FAIL — `'observation_window_end' not found`.

- [ ] **Step 3: Scope the traversal.** In `backend/app/insights.py`'s `run_graph`,
  resolve the run's admission window from `proof.retrieval_runs` joined to
  `casework.incident_capture_runs`, then filter the traversal result to edges whose
  endpoint evidence was admitted at or before that window's end. Add a comment
  naming Gate 2 and this hazard so the scoping is not "simplified" away later. In
  `_build_search_index`, pass the wave's own `source_systems` and run suffix
  unchanged — no new parameters needed.

- [ ] **Step 4: Run the tests.**

```bash
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
ALLOW_TEST_DATABASE_RESET=1 make test
```

Expected: PASS.

- [ ] **Step 5: Live-Aurora acceptance criteria.** With a two-wave corpus present:
  1. `retrieval.documents` shows **every** Wave A document still
     `is_current = true` (G-32 asserts this; run it).
  2. A Wave A `run_id` replayed through `GET /v1/runs/{run_id}/graph` returns the
     **same** node and edge set as it did before Wave B was admitted. Capture the
     response before Wave B, capture it after, diff them — byte-identical is the
     criterion.
  3. Content hashes of Wave A documents are unchanged after the Wave B rebuild
     (no spurious version bump) — the same check Gate 3 made.
  4. `retrieval.search_index_builds` shows two build rows with a growing
     `document_count`, confirming the rebuild was additive rather than
     replacing.

- [ ] **Step 6: Cleanup and failure recovery.** A failed rebuild leaves the index
  in a partially-updated state, but the deterministic `document_version_id` makes
  re-running fully idempotent — re-run rather than hand-repairing. Never regenerate
  the shipped real-embeddings dump as part of recovery; that artifact is
  separately managed and regenerating it costs real Bedrock calls for no benefit.

- [ ] **Step 7: Participant-facing changes.** A participant who replays their Lab 3
  investigation after Lab 4 sees exactly what the agent saw — Wave A only. That
  property is the whole point of the two-wave model, and it is now enforced in
  code rather than assumed.

- [ ] **Step 8: Commit.**

```bash
git add backend/app/insights.py labs/incident/run_live_workshop.py \
  backend/tests/test_search_index.py
git commit -m "Scope run graph traversal to the run's admission window"
```

**Dependencies:** Task C2 (a two-wave corpus must exist to verify against).

### Task C4: Promote the corpus diversity check to a permanent gate (G-33)

**Owning schema/module:** `gates/`.

**Files:**
- Create: `gates/corpus_diversity.py` (G-33)
- Modify: `gates/checks.sh` — add `G-33` to `CORE_GATES`
- Modify: `backend/scripts/doctor.py` — set the recalibrated document bounds
- Confirm: no `_gate*.py` prototype exists in `labs/incident/`; the repository
  audit retired them early because they were tracked throwaways and already made
  `test_only_the_guided_live_path_is_shipped` fail.

**Interfaces:**
- Consumes: Task C1's real generated corpus.
- Produces: `G-33` in `CORE_GATES`.

**Migration and compatibility implications:** Gate 5's historical diversity
prototype loaded documents from `/tmp` and created a temp table. The permanent
gate must be **read-only** per `gates/_common.py`'s contract
(`SELECT` / `SET LOCAL` only), so it computes similarity directly against
`retrieval.documents` with a self-join rather than `COPY`ing into a temp table.
`pg_trgm` is already installed (`sql/00_extensions.sql`). Per the
`gate-self-reference-fail-open` hazard, the six signal types and 15% threshold are
hardcoded literals in the gate, never derived from the corpus being judged — a
corpus that lost a whole signal type must turn the gate red, not redefine what
"complete" means. `backend/scripts/doctor.py`'s bounds get their real numbers here,
measured from an actual run, not guessed: this is the task that closes the
"recompute the bounds and re-verify against a real run" requirement the design
spec's Testing section raised.

- [ ] **Step 1: Write G-33.** Create `gates/corpus_diversity.py` following
  `gates/_common.py`'s contract exactly (the `sys.path.insert` +
  `from _common import (...)` boilerplate verbatim, `print_header`/`finish`,
  `read_env_value("DATABASE_URL")` + `redact_dsn()`, `require()` not raw
  `assert`, `main_guard(run)`):

```python
GATE_ID = "G-33"
TITLE = "corpus diversity and signal coverage"

SIGNAL_TYPES = ("lock", "pool", "request", "wal", "meta", "plan")
PHASES = ("backfill", "pool_exhaustion", "recovery", "plan_regression")
SIMILARITY_THRESHOLD = 0.6
MAX_NEAR_DUPLICATE_RATE = 0.15
```

  The core query is a read-only self-join over the current corpus:

```sql
WITH docs AS (
  SELECT d.document_version_id, d.search_document AS body
  FROM retrieval.documents d
  WHERE d.is_current
),
pairs AS (
  SELECT count(*) AS total,
         count(*) FILTER (
           WHERE similarity(a.body, b.body) > %(threshold)s
         ) AS near_dupes
  FROM docs a JOIN docs b ON a.document_version_id < b.document_version_id
)
SELECT total, near_dupes FROM pairs
```

  Then `require()` the rate under `MAX_NEAR_DUPLICATE_RATE`, and require at least
  one current document per hardcoded signal type and per hardcoded phase. Return
  BLOCKED (not FAIL) when the corpus is empty — an unindexed database is an honest
  unbuilt state, matching G-13/G-14 precedent.

- [ ] **Step 2: Run it and confirm it BLOCKS on an empty corpus, then PASSES on the
  real one.**

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python gates/corpus_diversity.py; echo "exit=$?"
```

Expected: `exit=2` (BLOCKED) before a run; `exit=0` with the measured rate printed
after Task C1's corpus is indexed.

- [ ] **Step 3: Recalibrate doctor's bounds from the real run.** Read the actual
  document count and per-type distribution from the real corpus, then set
  `backend/scripts/doctor.py`'s bounds to a range that brackets it with honest
  margin, replacing the `104 <= total <= 124` / `100 <= telemetry <= 120` numbers
  from the old mechanism. Write the measured numbers into the gate-results
  document. Do not set the bounds first and hope the run lands inside them.

- [ ] **Step 4: Register and run the gates.**

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  gates/checks.sh
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python backend/scripts/doctor.py
```

Expected: all core gates PASS (G-32 and G-33 included); `doctor.py` reports OK.

- [ ] **Step 5: Live-Aurora acceptance criteria.** Prove G-33 can go red: create a
  deliberate near-duplicate flood in the `_test` database (insert 20 copies of one
  document body with distinct keys), re-run, confirm FAIL with the measured rate
  named, then reset. A gate never seen red is not evidence — this is the
  `gate-self-reference-fail-open` lesson applied.

- [ ] **Step 6: Cleanup and failure recovery.** Confirm every `_gate*.py`
  prototype remains absent from `labs/incident/`; their findings are recorded in
  `docs/superpowers/specs/2026-08-04-dat410-gate-results.md`. Reset the `_test`
  database with `make schema` after the step 5 flood.

- [ ] **Step 7: Participant-facing changes.** None — gates are facilitator and CI
  tooling.

- [ ] **Step 8: Commit.**

```bash
git add gates/corpus_diversity.py gates/checks.sh backend/scripts/doctor.py
git commit -m "Add G-33 corpus diversity gate and retire the prototypes"
```

**Dependencies:** Tasks C1, C2, C3 (the gate measures the real indexed corpus, and
the doctor bounds must be calibrated against a completed two-wave run).

## Phase D — Labs

Owning modules: `labs/exercises/`, `agent/`, and the sibling Workshop Studio
repo's lab content. Per the design spec's Out of Scope section, **no change to
Labs 2–4's retrieval/ranking/agent/citation mechanics** — only the evidence
underneath them changes, plus Lab 4's new participant-executed `CREATE INDEX`
step. This phase is mostly verification that the unchanged mechanics still work
against the new corpus, plus the genuinely new Lab 4 step.

**Every task in this phase touching participant-facing copy is bound by the session
thesis in Global Constraints.** The theme-to-lab mapping this phase owns: Lab 2 is where
signal-to-noise becomes hybrid retrieval and reranking; Labs 3 and 4 are where the
expertise gap becomes a cited, replayable recommendation; Lab 4 is where
human-in-the-loop becomes "recommend, don't execute." Verification tasks (D1, D2) do not
need new copy, but they must not introduce copy that frames the outcome as a fixed index.

**Lab 3 is retrieval-first, and no task in this phase may make the optional security
module a prerequisite for it.** This is stated here because the coupling would be easy
to add by accident while Phase C is fresh in mind: Phase C carries a visibility
classifier, and a plausible-looking next step is "have Lab 3 demonstrate it." That step
is out of scope. Concretely, and each verified absent across this phase today:

- **No persona switching.** No lab step, exercise prompt, test, or piece of copy may
  require `SET LOCAL ROLE`, a persona DSN, `WORKBENCH_SECURITY_ENABLED=1`, or the
  frontend's persona route to reach Lab 3's answer.
- **No restricted citation.** The canonical Lab 3 cited set must resolve entirely from
  `workshop`-visibility evidence. A participant on a database that has never run
  `make security-schema` — which is every participant on the default path — must get the
  same answer and the same citations as one who has.
- **No `acl_visible` / `acl_scalars_visible` behaviour as a lab objective.** Those
  predicates are load-bearing inside `sql/03_search_functions.sql` and stay there
  untouched; they are not something Lab 3 teaches or asserts.

Phase D contains none of these requirements as written, so this is a rule against
introducing one, not a removal. If a future task believes it needs one, that is a scope
change to raise, not an implementation detail to add — the optional module has its own
release criteria in Global Constraints precisely so it can be exercised without
entering the one-hour path.

### Task D1: Re-confirm the four retrieval arms differentiate on the new corpus

**Owning schema/module:** `sql/03_search_functions.sql` (unchanged — verification
only); `backend/scripts/smoke_test.py`.

**Files:**
- Modify: `backend/scripts/smoke_test.py` — the semantic assertion and
  `_live_keys()` (already touched in Task B6; this task adds the arm-differentiation
  assertion)
- Test: `backend/scripts/smoke_test.py` is itself the test (`make smoke`)

**Interfaces:**
- Consumes: Task C3's indexed two-wave corpus.
- Produces: a smoke run that asserts the four arms return meaningfully different
  top candidates, and writes `READINESS.md` with the run ID.

**Migration and compatibility implications:** the design spec's Corpus Adequacy
criteria require re-confirming arm differentiation against the *new* corpus rather
than assuming it carries over — it was measured real at 103 old-mechanism documents
(exact ranked the `INC-` key first; FTS ranked `LOCK-...-01` first; vector ranked
`CHG-...-01` first; fuzzy resolved a transposed ID), but the new corpus is smaller
and differently shaped. `make smoke` cannot override `EMBED_PROVIDER` inline (a
known local trap), so run it with the environment already set. `READINESS.md` is
gitignored and carries the single-line `smoke run_id:` that G-13 scrapes; the
two-wave model now produces **two** run IDs per incident, so if Lab 4 verification
needs to replay the Wave B run specifically, `READINESS.md`'s single-line format
and `verify_sql_golden.py`'s `_SMOKE_RUN_ID_PATTERN` need a second resolution path.
Resolve it the cheap, honest way: G-13 continues to replay the *Wave A* smoke run
(the canonical answer run), and Wave B verification uses its own receipt rather
than `READINESS.md`. Do not extend the format speculatively.

- [ ] **Step 1: Add the failing assertion.** In `backend/scripts/smoke_test.py`,
  add an arm-differentiation check that fails loudly when two arms return the same
  top candidate:

```python
def _assert_arms_differentiate(receipts: dict[str, object]) -> None:
    """The four arms must return meaningfully different top candidates.

    Not a style preference: if exact/FTS/vector/fuzzy all rank the same document
    first, Labs 2-4 have nothing to teach and the corpus is too homogeneous.
    Re-checked per corpus because it is a property of the evidence, not the SQL.
    """
    tops = {
        arm: receipts.get(f"{arm}_top_key")
        for arm in ("exact", "fulltext", "semantic", "fuzzy")
    }
    distinct = {key for key in tops.values() if key}
    if len(distinct) < 3:
        raise SystemExit(
            f"smoke failed: only {len(distinct)} distinct top candidates across "
            f"four arms: {tops}"
        )
```

- [ ] **Step 2: Run smoke and confirm the assertion is exercised.**

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
EMBED_PROVIDER=bedrock \
  make smoke
```

Expected: the new assertion runs. If it fails on the real corpus, that is a real
finding about corpus homogeneity — return to Task C1 and add genuinely distinct
signal content, do not lower the threshold from 3.

- [ ] **Step 3: Record the measured arm results.** Capture the actual top candidate
  per arm and write them into the gate-results document as this corpus's measured
  differentiation. The old corpus's results are not this corpus's results.

- [ ] **Step 4: Confirm rerank still reorders for defensible reasons.** Run the
  same fusion query with `rerank=false` and `rerank=true` and compare. On the old
  103-document corpus, Cohere Rerank 3.5 promoted `TEL-...-R01` from outside the
  RRF top-8 to #2 and pulled `LOCK-...-01` and `CHG-...-02` into the top 4, with
  rerank scores 0.52–0.69 for promoted vs. ~0.42 for demoted — a real, separated
  signal. Acceptance criterion: the reranked ordering differs from the RRF ordering
  in at least one top-5 position, and `rrf_score` / `final_score` columns are
  **unchanged** between the two responses (this repo's score-separation invariant).

- [ ] **Step 5: Live-Aurora acceptance criteria.** `make smoke` exits 0;
  `READINESS.md` is written with a run ID; at least 3 distinct top candidates across
  the four arms; rerank reorders at least one top-5 position; `G-13` passes using
  the freshly written run ID.

- [ ] **Step 6: Cleanup and failure recovery.** `READINESS.md` is gitignored — never
  commit it. A failed smoke leaves a `proof.retrieval_runs` row, which is correct
  and should stay (it is a real run). No cleanup needed beyond not committing
  generated files.

- [ ] **Step 7: Participant-facing changes.** None to the mechanics. But the
  measured arm results become the concrete examples in Lab 2's content, replacing
  the old corpus's `INC-`/`LOCK-`/`CHG-` examples.

- [ ] **Step 8: Commit.**

```bash
git add backend/scripts/smoke_test.py
git commit -m "Assert retrieval arms differentiate on the new corpus"
```

**Dependencies:** Task C3.

### Task D2: Reconcile and verify the Wave-A-only hybrid retrieval agent

**Owning schema/module:** `agent/`; descriptions and prompts change, while the
seven read-only tool capabilities remain unchanged.

**Files:**
- Modify: `agent/registry.py`, `backend/app/agent.py`, and
  `backend/app/agent_tools.py` — replace repair/reads-continue decomposition with
  the three-clause backfill, pool, and plan-regression finding
- Regenerate: `lambda_mcp/generated_dispatch.py` and
  `mcp-server/src/server.generated.ts`
- Modify: `scripts/invoke_agentcore_gateway.py` — consume the Wave A receipt and
  ask the new canonical question
- Modify: `labs/exercises/` — reconcile Lab 2/3 requests and `checkpoint.py`,
  including `change_validates` and separate Wave A/Wave B keys
- Modify: `backend/tests/test_agent_and_synthesis.py`,
  `backend/tests/test_agent_tools.py`, `backend/tests/test_participant_exercises.py`,
  `backend/tests/test_strands_agent.py`, and `backend/tests/test_mcp_contract.py`
  — assert the new participant-facing contract
- Test: a new live assertion in `backend/tests/test_agent_contract.py` (new)

**Interfaces:**
- Consumes: Task C3's indexed corpus and Task C2's Wave A / Wave B separation.
- Produces: a test asserting the agent's cited set contains **zero** Wave B
  evidence when answering the diagnostic question.

**Migration and compatibility implications:** Global Constraints forbid adding a
write-capable tool; all 7 tools in `agent/registry.py` are read/synthesis-only
today and **no task in this plan may change that**. The agent's inability to see
post-index evidence is *source truth* — before Lab 4 runs, no Wave B evidence
exists in `retrieval.*` at all, so there is nothing to filter. The test must
therefore assert the honest property: when a two-wave corpus exists (i.e., after
Lab 4), an agent answering the *diagnostic* question still cites only Wave A. That
is the harder and more meaningful assertion, and it is the one a replaying
participant depends on. Full agent synthesis costs a real ~25s Bedrock Claude call
(measured 24.85s), so this test is gated behind the live-test environment
variables, not run on every `make test`.

- [ ] **Step 1: Write the failing test.** Create
  `backend/tests/test_agent_contract.py`:

```python
"""Agent contract tests. The live synthesis test costs a real ~25s Bedrock call
and is gated behind TEST_DATABASE_URL, matching the existing convention."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
ALLOW_RESET = os.environ.get("ALLOW_TEST_DATABASE_RESET") == "1"


class AgentToolSurfaceTests(unittest.TestCase):
    def test_no_tool_can_write_or_run_ddl(self) -> None:
        source = (REPO_ROOT / "agent" / "registry.py").read_text(encoding="utf-8")
        for forbidden in ("CREATE INDEX", "CREATE ", "UPDATE ", "DELETE ", "ALTER ", "DROP "):
            self.assertNotIn(
                forbidden, source,
                f"registry.py must stay read-only; found {forbidden!r}",
            )


@unittest.skipUnless(
    TEST_DATABASE_URL and ALLOW_RESET,
    "requires TEST_DATABASE_URL and ALLOW_TEST_DATABASE_RESET=1",
)
class AgentCitationScopeTests(unittest.TestCase):
    def test_diagnostic_answer_cites_no_wave_b_evidence(self) -> None:
        run_id, citations = self._answer_the_diagnostic_question()
        self.assertTrue(citations, "the agent must cite something")
        waves = self._waves_for(citations)
        self.assertEqual(
            waves, {"A"},
            f"diagnostic answer leaked Wave B evidence: {waves}",
        )
```

- [ ] **Step 2: Run it and confirm the tool-surface test passes and the citation
  test fails or skips.**

```bash
.venv/bin/python -m pytest backend/tests/test_agent_contract.py -v
```

Expected: `test_no_tool_can_write_or_run_ddl` PASS immediately (it is already
true — this is a regression guard, not a change); the citation test SKIP without
the env vars.

- [ ] **Step 3: Implement the helpers.** `_answer_the_diagnostic_question()` calls
  the real answer endpoint with the canonical diagnostic question and returns the
  run ID plus cited evidence IDs. `_waves_for()` resolves each cited evidence ID to
  its wave via `casework.incident_capture_runs`.

- [ ] **Step 4: Run the live test against a two-wave corpus.**

```bash
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
ALLOW_TEST_DATABASE_RESET=1 \
  .venv/bin/python -m pytest backend/tests/test_agent_contract.py -v
```

Expected: PASS. A failure means either the traversal scoping from Task C3 is not
holding, or the diagnostic question is phrased in a way that legitimately pulls
validation evidence — investigate which before changing anything.

- [ ] **Step 5: Live-Aurora acceptance criteria.** The agent produces a cited
  evidence-backed finding from Wave A alone that (a) names the unbatched backfill
  as the cause of the write stall, (b) names the missing composite index as the
  cause of the query regression, (c) states that `ANALYZE` did not resolve it, and
  (d) recommends both the index and batched-backfill-as-future-practice. All four
  must come from cited documents, not from the model's general knowledge — check
  each claim has a citation. If the agent reaches a correct conclusion with no
  supporting citation, the corpus is missing the document that should support it.

- [ ] **Step 6: Cleanup and failure recovery.** Each live run costs a real ~25s
  Bedrock call and writes a `proof.retrieval_runs` row. Those rows are real runs
  and stay. Do not loop this test.

- [ ] **Step 7: Participant-facing changes.** The ~25s synthesis wait is a real
  wait a participant sits through mid-Lab-3. Facilitator guidance must call it out
  as expected, not a hang — this was flagged in the measured baseline and is easy
  to mistake for a failure in a room full of people.

- [ ] **Step 8: Commit.**

```bash
git add backend/tests/test_agent_contract.py labs/exercises/
git commit -m "Assert the agent cites Wave A evidence only"
```

**Dependencies:** Tasks C2 and C3.

### Task D2a: Write the agent's structured action proposal in the Lab 3 answer path

**Owning schema/module:** `backend/app/`; new `backend/app/action_proposal.py`.
**No change to `agent/registry.py`.**

**Files:**
- Create: `backend/app/action_proposal.py`
- Modify: `backend/app/agent.py:682-955` — `_persist_answer()` gains one emission
  block after citation validation succeeds; `synthesize_cited_answer_impl()` is
  unchanged
- Test: `backend/tests/test_action_proposal.py` (new)

**Interfaces:**
- Consumes: Task A5's `proof.action_proposals`, `proof.action_proposal_citations`,
  `proof.canonical_index_key(text,text,text,text)`,
  `proof.index_action_fingerprint(text,text,text,text,boolean,text[],text[],text)`;
  the existing `proof.validate_answer_citations(uuid)`.
- Produces, all in `backend/app/action_proposal.py`:
  - `ACTION_PROPOSAL_TOOL_NAME: str = "record_action_proposal"`
  - `ACTION_PROPOSAL_TOOL_SPEC: dict` — the Bedrock `toolSpec` payload
  - `STATEMENT_TIMEOUT: str = "5min"` and `LOCK_TIMEOUT: str = "5s"`
  - `@dataclass(frozen=True) class IndexKey: column: str; direction: str`
  - `@dataclass(frozen=True) class ProposalFields` with fields `action_type: str`,
    `target_schema: str`, `target_table: str`, `index_method: str`,
    `is_unique: bool`, `key_columns: tuple[IndexKey, ...]`,
    `included_columns: tuple[str, ...]`, `predicate: str | None`,
    `expected_effect: str`, `supporting_citations: tuple[dict[str, Any], ...]`
  - `parse_proposal_fields(payload: dict) -> ProposalFields` — validates every
    identifier and raises `ValueError` otherwise
  - `index_name_for(fields: ProposalFields) -> str`
  - `render_create_index(fields: ProposalFields) -> tuple[str, str]` returning
    `(index_name, ddl)`
  - `render_rollback(fields: ProposalFields, index_name: str) -> str`
  - `propose_action_live(question, answer, evidence) -> ProposalFields`
  - `measure_preconditions(cursor, fields) -> list[dict[str, Any]]`
  - `persist_action_proposal(cursor, *, agent_run_id, run_id, fields,
    valid_citation_numbers) -> str` returning the `proposal_id`
- Task D3 consumes the stored proposal row: it reads `proposed_sql` to hand the
  participant, and `proposed_fingerprint` to compare against the catalog.

**This is an audit trail, not a capability, and the distinction is the whole
point.** The design spec is explicit: "a tool the agent can call is a capability;
a record written about the agent's output is an audit trail." The proposal is
written by the answer path from the answer the agent already produced — the same
way `proof.answer_citations` is written today — so `agent/registry.py` stays at
seven read/synthesis-only tools and Task D2's
`test_agent_registry_exposes_exactly_the_seven_readonly_tools` (A5 step 13) and
`test_no_tool_can_write_or_run_ddl` both keep passing unchanged. If this task's
implementer finds themselves adding an entry to the registry, they have
misread the task.

**Four implementation decisions, each with the reason it went that way. A
reviewer must check the reason, not just the code.**

1. **The model supplies the structured fields; the code renders the SQL.** The
   proposal's `action_type`, target, index method, uniqueness, ordered key
   columns, included columns, predicate, expected effect, and supporting citation
   numbers come from a Bedrock `toolConfig` call constrained to
   `ACTION_PROPOSAL_TOOL_SPEC` — so the recommendation is genuinely the agent's,
   not the harness's. The `CREATE INDEX` text the participant pastes into a psql
   prompt is then **rendered from those validated fields**, never taken as free
   text from the model. Two reasons, both concrete: a model-authored SQL string
   could disagree with the model's own structured fields, which would surface in
   Lab 4 as a fingerprint mismatch on a perfectly-executed action and blame the
   participant for the model's inconsistency; and a free-text DDL string handed to
   a human to run is an injection sink with a human as the executor. Every
   identifier is checked against `^[a-z_][a-z0-9_]*$` and rejected otherwise.
2. **A second model call, not prose parsing.** `synthesize_live()` is bound by
   `SYSTEM_PROMPT` to "exactly 5 to 7 concise sentences with no headings, bullets,
   or preamble," and `decompose_question_impl()` is pure deterministic Python with
   no model in it. There is no existing structured-output call anywhere in this
   repository, so this task establishes the pattern. The alternative — regexing a
   `CREATE INDEX` out of five sentences of prose — is a parser whose failure mode
   is a silently absent proposal, and Lab 4 cannot start without one. Cost is one
   extra Converse call on top of Lab 3's measured 24.85s synthesis; measure it in
   step 5 and record the number.
3. **The code measures the preconditions; the model does not assert them.** A
   model claiming `"satisfied": true` is a claim, and
   `proof.autonomy_readiness()`'s requirement 3 exists to test a fact. All four
   preconditions are evaluated against the live catalog inside the same
   transaction that writes the proposal. Timeouts and rollback SQL are likewise
   module constants and a rendered `DROP INDEX`, not model output. **This does not
   make the verdict vacuous:** a non-allowlisted `action_type`, an unapproved
   target, an already-existing equivalent index, a nonexistent key column, and
   citations that fail `proof.validate_answer_citations` are all reachable
   failures on this path, and each produces its own named reason.
4. **`/v1/agent/answer` is the canonical Lab 3 proposal path, and the Strands path
   deliberately emits nothing.** `proof.action_proposals.agent_run_id` is
   `NOT NULL REFERENCES proof.agent_runs`, and **only** `answer_question()`
   (`agent.py:1839`) creates a `proof.agent_runs` row — via `_start_agent_run`
   (`agent.py:1296`) — and threads `agent_run_id` into
   `synthesize_cited_answer_impl` (`agent.py:2076-2080`). Every other caller
   passes nothing: `synthesize_cited_answer_from_run_impl` (`agent.py:1022`) and
   `synthesize_cited_answer_from_runs_impl` (`agent.py:1039`) both omit it, the
   latter is what `agent/registry.py:396`, `backend/app/agent_tools.py:534`, and
   `backend/app/main.py:320` call, and `agent_tools.start_run()`
   (`agent_tools.py:79-99`) builds a **purely in-memory** dict in a ContextVar
   without ever inserting a `proof.agent_runs` row. So the emission block must be
   guarded on `agent_run_id` being truthy, exactly mirroring the existing
   `if run_id` guard — an unguarded `INSERT` fails the FK and turns
   `/v1/agent/strands/answer` and `/v1/tools/synthesize` into 500s. Giving the
   Strands path a real `proof.agent_runs` row is **out of scope for this plan**
   and is named here as a known limitation rather than left as a surprise.
   **Lab 3's proposal-producing step calls `POST /v1/agent/answer`.** Task D3's
   sibling-content work must confirm the Lab 3 page names that endpoint; if it
   names the Strands endpoint, changing the page is D3's job, not a reason to
   widen this task.

**Two more properties that are easy to get wrong.**

- **The proposal is written inside `_persist_answer()`'s existing transaction,
  after validation succeeds.** `proof.action_proposal_citations` carries
  `FOREIGN KEY (run_id, citation_number) REFERENCES
  proof.answer_citations(run_id, citation_number)`, so the rows it references do
  not exist until that function's `executemany` has run; and a proposal supported
  by citations that then failed validation is a proposal built on evidence the
  answer layer rejected. Placing the block after the `validation_status = 'valid'`
  update satisfies both. A failure here rolls the whole answer back and raises —
  a Lab 3 run with no proposal is a Lab 4 that cannot start, so silent absence is
  the worse outcome.
- **No proposal from an extractive fallback.** `synthesize_cited_answer_impl`
  catches any synthesis error and substitutes `_extractive_answer()` with
  `synthesis["mode"] = "extractive_fallback"`. A concatenation of evidence
  sentences recommends nothing, so emitting a proposal from it would attribute a
  recommendation to an agent that never made one. Guard on
  `synthesis["mode"] == "bedrock"`.

- [ ] **Step 1: Write the failing tests.** Create
  `backend/tests/test_action_proposal.py`. The rendering and validation tests are
  pure Python and run on every `make test`; the live emission test is gated.

```python
"""Action-proposal tests. The rendering and identifier-validation tests are pure
Python. The live emission test costs a real Bedrock synthesis plus a real
structured-output call and is gated behind TEST_DATABASE_URL."""
from __future__ import annotations

import os
import unittest

from backend.app.action_proposal import (
    ACTION_PROPOSAL_TOOL_NAME,
    ACTION_PROPOSAL_TOOL_SPEC,
    IndexKey,
    ProposalFields,
    index_name_for,
    parse_proposal_fields,
    render_create_index,
    render_rollback,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

VALID_PAYLOAD = {
    "action_type": "create_index",
    "target_schema": "workbench_lab",
    "target_table": "orders",
    "index_method": "btree",
    "is_unique": False,
    "key_columns": [
        {"column": "priority_tier", "direction": "asc"},
        {"column": "created_at", "direction": "desc"},
    ],
    "included_columns": [],
    "predicate": None,
    "expected_effect": "an index scan replaces the sequential scan",
    "supporting_citations": [
        {"citation_number": 1, "claim": "the plan is a sequential scan"}
    ],
}


class ProposalParsingTests(unittest.TestCase):
    def test_tool_spec_names_the_tool_it_is_registered_under(self) -> None:
        self.assertEqual(
            ACTION_PROPOSAL_TOOL_SPEC["toolSpec"]["name"], ACTION_PROPOSAL_TOOL_NAME
        )

    def test_valid_payload_parses(self) -> None:
        fields = parse_proposal_fields(VALID_PAYLOAD)
        self.assertEqual(fields.action_type, "create_index")
        self.assertEqual(
            fields.key_columns,
            (IndexKey("priority_tier", "asc"), IndexKey("created_at", "desc")),
        )

    def test_key_column_order_is_preserved_not_sorted(self) -> None:
        """Key order is semantically load-bearing and the fingerprint treats it
        as ordered. Sorting here would silently turn one action into another."""
        reversed_payload = dict(VALID_PAYLOAD)
        reversed_payload["key_columns"] = list(
            reversed(VALID_PAYLOAD["key_columns"])
        )
        fields = parse_proposal_fields(reversed_payload)
        self.assertEqual(
            [key.column for key in fields.key_columns],
            ["created_at", "priority_tier"],
        )

    def test_an_injected_identifier_is_refused(self) -> None:
        """This string is rendered into DDL that a human pastes into psql."""
        for bad in (
            "orders; DROP TABLE workbench_lab.orders",
            'orders" ; --',
            "pg_catalog.pg_class",
            "",
        ):
            with self.subTest(identifier=bad):
                payload = dict(VALID_PAYLOAD, target_table=bad)
                with self.assertRaises(ValueError):
                    parse_proposal_fields(payload)

    def test_no_key_columns_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            parse_proposal_fields(dict(VALID_PAYLOAD, key_columns=[]))

    def test_an_unknown_direction_is_refused(self) -> None:
        payload = dict(VALID_PAYLOAD)
        payload["key_columns"] = [{"column": "created_at", "direction": "sideways"}]
        with self.assertRaises(ValueError):
            parse_proposal_fields(payload)


class ProposalRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fields = parse_proposal_fields(VALID_PAYLOAD)

    def test_rendered_ddl_is_deterministic_and_qualified(self) -> None:
        name, ddl = render_create_index(self.fields)
        self.assertEqual(name, index_name_for(self.fields))
        self.assertEqual(
            ddl,
            "CREATE INDEX idx_orders_priority_tier_created_at\n"
            "  ON workbench_lab.orders USING btree "
            "(priority_tier ASC, created_at DESC);",
        )

    def test_rendered_ddl_emits_no_nulls_or_opclass_clause(self) -> None:
        """The proposal side passes NULL for p_nulls and p_opclass, so
        proof.canonical_index_key materializes PostgreSQL's own defaults. An
        explicit NULLS or opclass clause in the DDL would create a real index the
        canonical key does not describe."""
        _name, ddl = render_create_index(self.fields)
        self.assertNotIn("NULLS", ddl)
        self.assertNotIn("opclass", ddl.lower())
        self.assertNotIn("text_pattern_ops", ddl)

    def test_rollback_drops_exactly_the_proposed_index(self) -> None:
        name, _ddl = render_create_index(self.fields)
        self.assertEqual(
            render_rollback(self.fields, name),
            "DROP INDEX IF EXISTS workbench_lab.idx_orders_priority_tier_created_at;",
        )

    def test_index_name_stays_within_the_identifier_limit(self) -> None:
        long_fields = ProposalFields(
            action_type="create_index",
            target_schema="workbench_lab",
            target_table="orders",
            index_method="btree",
            is_unique=False,
            key_columns=tuple(
                IndexKey(f"a_very_long_column_name_number_{n}", "asc")
                for n in range(6)
            ),
            included_columns=(),
            predicate=None,
            expected_effect="x",
            supporting_citations=(),
        )
        self.assertLessEqual(len(index_name_for(long_fields).encode("utf-8")), 63)


@unittest.skipUnless(TEST_DATABASE_URL, "requires TEST_DATABASE_URL")
class ProposalEmissionTests(unittest.TestCase):
    def test_the_answer_path_writes_exactly_one_proposal(self) -> None:
        agent_run_id, proposal = self._answer_and_read_proposal()
        self.assertEqual(proposal["agent_run_id"], agent_run_id)
        self.assertEqual(proposal["action_type"], "create_index")
        self.assertEqual(proposal["target_schema"], "workbench_lab")
        self.assertEqual(proposal["target_table"], "orders")
        self.assertTrue(proposal["proposed_sql"].startswith("CREATE INDEX "))
        self.assertEqual(len(proposal["proposed_sql_sha256"]), 64)
        self.assertEqual(len(proposal["proposed_fingerprint"]), 64)
        self.assertEqual(proposal["statement_timeout"], "5min")
        self.assertEqual(proposal["lock_timeout"], "5s")

    def test_the_proposal_cites_only_validated_citations(self) -> None:
        _agent_run_id, proposal = self._answer_and_read_proposal()
        cited, invalid = self._citation_counts(proposal["proposal_id"])
        self.assertGreater(cited, 0, "a proposal with no citations is ineligible")
        self.assertEqual(invalid, 0)

    def test_the_fresh_proposal_is_pre_execution_eligible(self) -> None:
        _agent_run_id, proposal = self._answer_and_read_proposal()
        verdict = self._verdict(proposal["proposal_id"])
        self.assertTrue(
            verdict["pre_execution_eligible"],
            f"ineligible: {verdict['pre_execution_reasons']}",
        )
        self.assertFalse(verdict["post_execution_validated"])
        self.assertEqual(
            verdict["post_execution_reasons"], ["no execution has been recorded yet"]
        )

    def test_the_strands_path_writes_no_proposal_and_does_not_error(self) -> None:
        """proof.action_proposals.agent_run_id is NOT NULL and only
        answer_question() creates a proof.agent_runs row. An unguarded INSERT
        turns this endpoint into a 500."""
        before = self._proposal_count()
        run_id = self._answer_via_strands()
        self.assertTrue(run_id)
        self.assertEqual(self._proposal_count(), before)
```

  The four `_`-prefixed helpers are owed by step 4, not by this step:
  `_answer_and_read_proposal()` posts the Lab 3 diagnostic question through
  `answer_question()` and returns `(agent_run_id, proposal_row)`;
  `_citation_counts(proposal_id)` returns `(cited, invalid)` by joining
  `proof.action_proposal_citations` to `proof.validate_answer_citations(run_id)`;
  `_verdict(proposal_id)` selects the single row from
  `proof.autonomy_readiness(proposal_id)`; `_proposal_count()` returns
  `SELECT count(*) FROM proof.action_proposals`; `_answer_via_strands()` calls
  `backend.app.agent_tools`' run-based synthesis path and returns its `run_id`.

- [ ] **Step 2: Run the tests and confirm they fail for the right reason.**

```bash
.venv/bin/python -m pytest backend/tests/test_action_proposal.py -v
```

Expected: every test in `ProposalParsingTests` and `ProposalRenderingTests` errors
at import with `ModuleNotFoundError: No module named 'backend.app.action_proposal'`,
and `ProposalEmissionTests` skips without `TEST_DATABASE_URL`. An import error is
the correct first failure — a test that fails on an assertion instead means the
module already exists and this task is not starting from zero.

- [ ] **Step 3: Write `backend/app/action_proposal.py` — the tool spec, the
  validators, and the renderers.** This is the half the parsing and rendering
  tests cover, and it is pure Python with no database and no Bedrock.

```python
"""The agent's structured action proposal.

This module holds no write path to the database's schema objects. It turns the
agent's structured recommendation into (a) a canonical fingerprint the catalog can
be compared against and (b) the exact DDL text a human is asked to run. The
participant executes it; the agent never does.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

# Bounded on purpose, and not model-supplied: an unbounded CREATE INDEX on a
# 3,000,000-row table is exactly the operational mistake this lab teaches against.
STATEMENT_TIMEOUT = "5min"
LOCK_TIMEOUT = "5s"

# PostgreSQL truncates identifiers at 63 bytes. A silently truncated index name
# still creates an index, under a name the rollback SQL would then not match.
MAX_IDENTIFIER_BYTES = 63

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
DIRECTIONS = ("asc", "desc")
ACTION_TYPES = ("create_index",)
INDEX_METHODS = ("btree",)

ACTION_PROPOSAL_TOOL_NAME = "record_action_proposal"

ACTION_PROPOSAL_TOOL_SPEC: dict[str, Any] = {
    "toolSpec": {
        "name": ACTION_PROPOSAL_TOOL_NAME,
        "description": (
            "Record the single database change your cited answer recommends. "
            "You are not executing anything: a human reviews this proposal and "
            "runs it themselves. Recommend exactly one index."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "action_type": {"type": "string", "enum": list(ACTION_TYPES)},
                    "target_schema": {"type": "string"},
                    "target_table": {"type": "string"},
                    "index_method": {"type": "string", "enum": list(INDEX_METHODS)},
                    "is_unique": {"type": "boolean"},
                    "key_columns": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "direction": {
                                    "type": "string",
                                    "enum": list(DIRECTIONS),
                                },
                            },
                            "required": ["column", "direction"],
                        },
                        "description": (
                            "Key columns in index order. Order is semantically "
                            "load-bearing; list them in the order the index "
                            "should use."
                        ),
                    },
                    "included_columns": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    # No "predicate" property. A partial index cannot be
                    # fingerprinted against its catalog read-back, so the field is
                    # rejected by parse_proposal_fields() rather than advertised
                    # here. Do not re-add it to "make the schema complete."
                    "expected_effect": {
                        "type": "string",
                        "description": (
                            "What the plan should do differently afterwards, in "
                            "one sentence."
                        ),
                    },
                    "supporting_citations": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "citation_number": {"type": "integer"},
                                "claim": {"type": "string"},
                            },
                            "required": ["citation_number", "claim"],
                        },
                        "description": (
                            "The bracketed citation numbers from your answer that "
                            "support this recommendation, each with the claim it "
                            "supports."
                        ),
                    },
                },
                "required": [
                    "action_type",
                    "target_schema",
                    "target_table",
                    "key_columns",
                    "expected_effect",
                    "supporting_citations",
                ],
            }
        },
    }
}


@dataclass(frozen=True)
class IndexKey:
    column: str
    direction: str


@dataclass(frozen=True)
class ProposalFields:
    action_type: str
    target_schema: str
    target_table: str
    index_method: str
    is_unique: bool
    key_columns: tuple[IndexKey, ...]
    included_columns: tuple[str, ...]
    predicate: str | None
    expected_effect: str
    supporting_citations: tuple[dict[str, Any], ...]


def _identifier(value: Any, field: str) -> str:
    """Return ``value`` as a validated lower-case SQL identifier.

    Every string this returns is interpolated into DDL a human is asked to run,
    so an allowlist is the only acceptable check. Quoting is not enough: the
    fingerprint treats a quoted identifier as case-sensitive, so accepting one
    here would let two different actions share one canonical form.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string, got {type(value).__name__}")
    folded = value.strip().lower()
    if not IDENTIFIER.match(folded):
        raise ValueError(f"{field} is not a plain SQL identifier: {value!r}")
    if len(folded.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise ValueError(f"{field} exceeds {MAX_IDENTIFIER_BYTES} bytes: {value!r}")
    return folded


def parse_proposal_fields(payload: dict[str, Any]) -> ProposalFields:
    """Validate a model-supplied proposal payload into ``ProposalFields``."""
    action_type = str(payload.get("action_type") or "").strip().lower()
    if action_type not in ACTION_TYPES:
        raise ValueError(f"unsupported action_type: {action_type!r}")
    method = str(payload.get("index_method") or "btree").strip().lower()
    if method not in INDEX_METHODS:
        raise ValueError(f"unsupported index_method: {method!r}")

    raw_keys = payload.get("key_columns") or []
    if not isinstance(raw_keys, list) or not raw_keys:
        raise ValueError("key_columns must be a non-empty list")
    keys: list[IndexKey] = []
    for position, entry in enumerate(raw_keys, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"key_columns[{position}] must be an object")
        direction = str(entry.get("direction") or "asc").strip().lower()
        if direction not in DIRECTIONS:
            raise ValueError(
                f"key_columns[{position}].direction must be asc or desc, "
                f"got {direction!r}"
            )
        keys.append(
            IndexKey(
                _identifier(entry.get("column"), f"key_columns[{position}].column"),
                direction,
            )
        )
    seen = [key.column for key in keys]
    if len(set(seen)) != len(seen):
        raise ValueError(f"key_columns repeats a column: {seen}")

    included = tuple(
        _identifier(value, f"included_columns[{position}]")
        for position, value in enumerate(payload.get("included_columns") or [], 1)
    )
    # A predicate is REJECTED, not sanitized. Two independent reasons, both
    # measured:
    #
    # 1. It cannot be fingerprinted. The catalog rewrites it through
    #    pg_get_expr(), so the proposal-side and observation-side fingerprints
    #    disagree for an identical index and a correct participant is told they
    #    executed the wrong action. proof.action_proposals carries a matching
    #    CHECK (predicate IS NULL); this raise is the same rule stated where the
    #    error message can name the field.
    # 2. It is the ONLY field that reaches rendered DDL without passing
    #    _identifier(). Every other interpolated value is checked against
    #    ^[a-z_][a-z0-9_]*$; a free-text predicate spliced into a CREATE INDEX a
    #    human pastes into psql is exactly the injection sink the structured-field
    #    design exists to eliminate -- `status = 'open'; DROP TABLE orders; --`
    #    renders as a valid statement the participant is instructed to run.
    #
    # Removing "predicate" from the tool schema alone is not sufficient: the model
    # supplies this payload, and a field absent from a schema can still appear in
    # a payload. Validate, do not trust.
    predicate = payload.get("predicate")
    if predicate is not None and str(predicate).strip():
        raise ValueError(
            "predicate is not supported: a partial-index predicate cannot be "
            "fingerprinted consistently (the catalog rewrites it via "
            "pg_get_expr) and is the only proposal field that would reach "
            "rendered DDL unvalidated; propose a plain index instead"
        )
    predicate = None

    citations = tuple(
        {
            "citation_number": int(entry["citation_number"]),
            "claim": str(entry["claim"]).strip(),
        }
        for entry in (payload.get("supporting_citations") or [])
        if isinstance(entry, dict)
        and entry.get("citation_number") is not None
        and str(entry.get("claim") or "").strip()
    )

    effect = str(payload.get("expected_effect") or "").strip()
    if not effect:
        raise ValueError("expected_effect must not be blank")

    return ProposalFields(
        action_type=action_type,
        target_schema=_identifier(payload.get("target_schema"), "target_schema"),
        target_table=_identifier(payload.get("target_table"), "target_table"),
        index_method=method,
        is_unique=bool(payload.get("is_unique")),
        key_columns=tuple(keys),
        included_columns=included,
        predicate=str(predicate).strip() if predicate is not None else None,
        expected_effect=effect,
        supporting_citations=citations,
    )


def index_name_for(fields: ProposalFields) -> str:
    """Deterministic index name, truncated to PostgreSQL's identifier limit.

    Truncation is by whole trailing column, then hard-sliced, so the name stays
    readable rather than ending mid-word. Determinism matters because
    ``render_rollback`` has to name the same index.
    """
    columns = [key.column for key in fields.key_columns]
    while columns:
        name = "_".join(["idx", fields.target_table, *columns])
        if len(name.encode("utf-8")) <= MAX_IDENTIFIER_BYTES:
            return name
        columns.pop()
    return f"idx_{fields.target_table}"[:MAX_IDENTIFIER_BYTES]


def render_create_index(fields: ProposalFields) -> tuple[str, str]:
    """Render ``(index_name, ddl)`` from validated fields.

    No NULLS clause and no opclass are emitted. proof.canonical_index_key
    materializes PostgreSQL's own defaults on both sides, so an explicit clause
    here would build a real index the canonical form does not describe.
    """
    name = index_name_for(fields)
    keys = ", ".join(
        f"{key.column} {key.direction.upper()}" for key in fields.key_columns
    )
    include = (
        f" INCLUDE ({', '.join(fields.included_columns)})"
        if fields.included_columns
        else ""
    )
    # No WHERE clause is ever emitted. parse_proposal_fields() raises on a
    # non-empty predicate and proof.action_proposals CHECKs it NULL, so rendering
    # one would be unreachable code that also happens to be the design's only
    # injection sink. Asserted rather than branched on: a silent `if predicate`
    # here would quietly start emitting model text into a statement a human runs
    # the moment someone relaxes the parser.
    if fields.predicate:
        raise ValueError("render_create_index received a predicate; see parse_proposal_fields")
    unique = "UNIQUE " if fields.is_unique else ""
    return name, (
        f"CREATE {unique}INDEX {name}\n"
        f"  ON {fields.target_schema}.{fields.target_table} "
        f"USING {fields.index_method} ({keys}){include};"
    )


def render_rollback(fields: ProposalFields, index_name: str) -> str:
    """Render the rollback for a rendered CREATE INDEX."""
    return f"DROP INDEX IF EXISTS {fields.target_schema}.{index_name};"


def sql_sha256(statement: str) -> str:
    """Raw-SQL hash, stored for audit only.

    The authoritative equality test is the canonical fingerprint. Whitespace,
    quoting, and equivalent PostgreSQL syntax make a raw hash comparison
    brittle, so this value is recorded and never compared.
    """
    return hashlib.sha256(statement.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run the pure tests and confirm they pass.**

```bash
.venv/bin/python -m pytest backend/tests/test_action_proposal.py -v \
  -k "ProposalParsingTests or ProposalRenderingTests"
```

Expected: all PASS. If `test_rendered_ddl_is_deterministic_and_qualified` fails on
whitespace, fix the renderer to match the test — the test's exact string is the
contract Lab 4 pastes into psql, and Task D3's participant copy quotes it.

- [ ] **Step 5: Add the structured-output call.** Append to
  `backend/app/action_proposal.py`. This is the repository's first `toolConfig`
  Converse call; `backend/app/synthesis.py:86-113` is the model for the client,
  the model-ID guard, and the transport check, and this function deliberately
  reuses `evidence_block()` so the model sees the identical numbered evidence it
  just cited.

```python
def propose_action_live(
    question: str,
    answer: str,
    evidence: list[dict[str, Any]],
) -> ProposalFields:
    """Ask the model for the structured form of the recommendation it just made.

    The model chooses the action; this module renders the SQL. A model-authored
    DDL string could contradict the model's own structured fields, which would
    surface in Lab 4 as a fingerprint mismatch on a correctly executed action.

    Raises:
        ValueError: if the transport is unsupported, the model declines to call
            the tool, or the returned fields fail validation.
    """
    from .bedrock import get_bedrock_client
    from .config import get_settings
    from .synthesis import evidence_block

    settings = get_settings()
    if settings.bedrock_model_transport != "converse_global_cris":
        raise ValueError(
            "unsupported BEDROCK_MODEL_TRANSPORT; use converse_global_cris"
        )

    response = get_bedrock_client(
        "bedrock-runtime",
        region=settings.aws_region,
    ).converse(
        modelId=settings.bedrock_synthesis_model,
        system=[
            {
                "text": (
                    "You recommend database changes; you never execute them. A "
                    "human reviews your proposal and runs it themselves. Record "
                    "exactly one index using the record_action_proposal tool. "
                    "Cite only the bracketed evidence numbers that appear in the "
                    "answer you are given. Do not write SQL: give the structured "
                    "fields and the caller renders the statement."
                )
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            f"Question: {question}\n\n"
                            f"Your cited answer:\n{answer}\n\n"
                            f"Evidence:\n{evidence_block(evidence)}\n\n"
                            "Record the single index this answer recommends."
                        )
                    }
                ],
            }
        ],
        toolConfig={
            "tools": [ACTION_PROPOSAL_TOOL_SPEC],
            # Forced, not offered. An optional tool lets the model reply with
            # prose instead, and a Lab 3 run with no proposal is a Lab 4 that
            # cannot start.
            "toolChoice": {"tool": {"name": ACTION_PROPOSAL_TOOL_NAME}},
        },
        inferenceConfig={"maxTokens": settings.bedrock_synthesis_max_tokens},
    )
    if response.get("stopReason") == "max_tokens":
        raise ValueError("action proposal reached the configured token limit")
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    for block in blocks:
        use = block.get("toolUse") if isinstance(block, dict) else None
        if use and use.get("name") == ACTION_PROPOSAL_TOOL_NAME:
            return parse_proposal_fields(use.get("input") or {})
    raise ValueError(
        f"model did not call {ACTION_PROPOSAL_TOOL_NAME}; "
        f"stopReason={response.get('stopReason')!r}"
    )
```

- [ ] **Step 6: Add the precondition measurement.** Append to
  `backend/app/action_proposal.py`. Every entry's `satisfied` value is measured
  against the live catalog inside the caller's transaction. A model asserting
  `"satisfied": true` would make `proof.autonomy_readiness()`'s requirement 3 a
  restatement of the model's confidence rather than a test of a fact.

```python
def measure_preconditions(
    cursor: Any,
    fields: ProposalFields,
) -> list[dict[str, Any]]:
    """Evaluate the proposal's preconditions against the live catalog.

    Args:
        cursor: an open cursor on the same transaction that will write the
            proposal, so the measurement and the record cannot disagree.
        fields: the validated proposal fields.

    Returns:
        One entry per check, each with ``check``, ``satisfied``, and ``detail``.
        Unsatisfied entries are returned, not raised: an incomplete proposal must
        be storable so proof.autonomy_readiness() can report why it is ineligible.
    """
    qualified = f"{fields.target_schema}.{fields.target_table}"
    cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (qualified,))
    table_exists = bool(cursor.fetchone()[0])

    cursor.execute(
        """
        SELECT count(*) = %(expected)s
        FROM pg_attribute a
        WHERE a.attrelid = to_regclass(%(qualified)s)
          AND NOT a.attisdropped
          AND a.attnum > 0
          AND a.attname = ANY(%(columns)s)
        """,
        {
            "qualified": qualified,
            "columns": [key.column for key in fields.key_columns]
            + list(fields.included_columns),
            "expected": len(fields.key_columns) + len(fields.included_columns),
        },
    )
    columns_exist = bool(cursor.fetchone()[0])

    index_name, ddl = render_create_index(fields)
    canonical_keys = [
        # NULL for p_nulls and p_opclass on purpose: canonical_index_key
        # materializes PostgreSQL's defaults, and the rendered DDL emits neither
        # clause. Measured identical to the catalog side at 82d2c73c30ae4f86.
        (key.column, key.direction)
        for key in fields.key_columns
    ]
    cursor.execute(
        """
        SELECT proof.index_action_fingerprint(
                 %(action_type)s, %(schema)s, %(table)s, %(method)s, %(unique)s,
                 (SELECT array_agg(
                            proof.canonical_index_key(k.expr, k.dir, NULL, NULL)
                            ORDER BY k.ordinality)
                    FROM unnest(%(exprs)s::text[], %(dirs)s::text[])
                         WITH ORDINALITY AS k(expr, dir, ordinality)),
                 %(include)s::text[], %(predicate)s)
        """,
        {
            "action_type": fields.action_type,
            "schema": fields.target_schema,
            "table": fields.target_table,
            "method": fields.index_method,
            "unique": fields.is_unique,
            "exprs": [column for column, _ in canonical_keys],
            "dirs": [direction for _, direction in canonical_keys],
            "include": list(fields.included_columns),
            "predicate": fields.predicate,
        },
    )
    fingerprint = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT count(*)
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        CROSS JOIN proof.observed_index_fingerprint(i.indexrelid) f
        WHERE i.indrelid = to_regclass(%(qualified)s)
          AND f.fingerprint = %(fingerprint)s
        """,
        {"qualified": qualified, "fingerprint": fingerprint},
    )
    equivalent_indexes = int(cursor.fetchone()[0])

    return [
        {
            "check": "target_table_exists",
            "satisfied": table_exists,
            "detail": qualified,
        },
        {
            "check": "key_columns_exist",
            "satisfied": columns_exist,
            "detail": ", ".join(key.column for key in fields.key_columns),
        },
        {
            "check": "no_equivalent_index_exists",
            "satisfied": equivalent_indexes == 0,
            "detail": (
                f"{equivalent_indexes} index(es) already match this fingerprint"
                if equivalent_indexes
                else "no existing index matches this fingerprint"
            ),
        },
        {
            "check": "statement_is_rendered_not_model_authored",
            "satisfied": True,
            "detail": f"{index_name}: {ddl.splitlines()[0]}",
        },
    ]
```

  The `no_equivalent_index_exists` check compares **fingerprints**, not index
  names. A participant who created the same index under a different name has
  satisfied the recommendation, and a differently-shaped index sharing the
  expected name has not.

- [ ] **Step 7: Add the persistence function.** Append to
  `backend/app/action_proposal.py`. It writes with two `INSERT`s and no `UPDATE`
  and no `DELETE`, matching the INSERT-only grant Task A5 step 11 established.

```python
def persist_action_proposal(
    cursor: Any,
    *,
    agent_run_id: str,
    run_id: str,
    fields: ProposalFields,
    valid_citation_numbers: list[int],
) -> str:
    """Write the proposal and its supporting citation links.

    Args:
        cursor: an open cursor inside _persist_answer's transaction, after the
            proof.answer_citations rows exist and have validated.
        agent_run_id: the proof.agent_runs row this answer belongs to.
        run_id: the proof.retrieval_runs row the citations belong to.
        fields: the validated proposal fields.
        valid_citation_numbers: the citation numbers actually written for this
            run. A model-supplied number outside this set is dropped rather than
            written, because the composite FK to proof.answer_citations would
            reject it and abort the whole answer.

    Returns:
        The new proposal_id.
    """
    index_name, ddl = render_create_index(fields)
    preconditions = measure_preconditions(cursor, fields)
    cursor.execute(
        """
        INSERT INTO proof.action_proposals(
          agent_run_id, run_id, action_type, target_schema, target_table,
          index_method, is_unique, key_columns, included_columns, predicate,
          proposed_fingerprint, proposed_sql, proposed_sql_sha256,
          preconditions, expected_effect, rollback_sql, rollback_guidance,
          statement_timeout, lock_timeout
        )
        VALUES (
          %(agent_run_id)s, %(run_id)s, %(action_type)s, %(schema)s, %(table)s,
          %(method)s, %(unique)s,
          (SELECT array_agg(proof.canonical_index_key(k.expr, k.dir, NULL, NULL)
                            ORDER BY k.ordinality)
             FROM unnest(%(exprs)s::text[], %(dirs)s::text[])
                  WITH ORDINALITY AS k(expr, dir, ordinality)),
          %(include)s::text[], %(predicate)s,
          proof.index_action_fingerprint(
            %(action_type)s, %(schema)s, %(table)s, %(method)s, %(unique)s,
            (SELECT array_agg(proof.canonical_index_key(k.expr, k.dir, NULL, NULL)
                              ORDER BY k.ordinality)
               FROM unnest(%(exprs)s::text[], %(dirs)s::text[])
                    WITH ORDINALITY AS k(expr, dir, ordinality)),
            %(include)s::text[], %(predicate)s),
          %(ddl)s, %(ddl_sha)s, %(preconditions)s::jsonb, %(effect)s,
          %(rollback_sql)s, %(rollback_guidance)s,
          %(statement_timeout)s, %(lock_timeout)s
        )
        RETURNING proposal_id
        """,
        {
            "agent_run_id": agent_run_id,
            "run_id": run_id,
            "action_type": fields.action_type,
            "schema": fields.target_schema,
            "table": fields.target_table,
            "method": fields.index_method,
            "unique": fields.is_unique,
            "exprs": [key.column for key in fields.key_columns],
            "dirs": [key.direction for key in fields.key_columns],
            "include": list(fields.included_columns),
            "predicate": fields.predicate,
            "ddl": ddl,
            "ddl_sha": sql_sha256(ddl),
            "preconditions": json.dumps(preconditions),
            "effect": fields.expected_effect,
            "rollback_sql": render_rollback(fields, index_name),
            "rollback_guidance": (
                f"Dropping {index_name} restores the pre-change plan. The index "
                "is additive: it changes no row and no column, so the rollback "
                "loses no data."
            ),
            "statement_timeout": STATEMENT_TIMEOUT,
            "lock_timeout": LOCK_TIMEOUT,
        },
    )
    row = cursor.fetchone()
    proposal_id = str(row[0] if isinstance(row, tuple) else row["proposal_id"])

    allowed = set(valid_citation_numbers)
    # The SAME run_id that went into the proposal above, and Task A5 step 3's
    # composite FK to proof.action_proposals(proposal_id, run_id) now enforces
    # that rather than trusting it: a link naming a different run is refused with
    # foreign_key_violation, which aborts the answer transaction instead of
    # storing a proposal whose citations and verdict disagree about which run
    # they describe.
    links = [
        (proposal_id, run_id, entry["citation_number"], entry["claim"])
        for entry in fields.supporting_citations
        if entry["citation_number"] in allowed
    ]
    if links:
        cursor.executemany(
            """
            INSERT INTO proof.action_proposal_citations(
              proposal_id, run_id, citation_number, claim
            )
            VALUES (%s, %s, %s, %s)
            """,
            links,
        )
    return proposal_id
```

  `import json` belongs at the top of the module with the other imports; it is
  listed here only where it is first used. **A proposal with zero surviving links
  is still written**, and `proof.autonomy_readiness()` reports it as
  `the proposal cites no evidence` — which is the honest outcome, and strictly
  better than a Lab 4 that cannot start because the answer path raised.

- [ ] **Step 8: Wire the emission into `_persist_answer()`.** In
  `backend/app/agent.py`, the function currently ends by marking the answer valid
  and returning the citation list (`agent.py:860-867`). Insert the emission block
  between the `validation_status = 'valid'` update and the `return`, still inside
  the `with connection.transaction():` block:

```python
                cursor.execute(
                    """
                    UPDATE proof.agent_answers
                    SET validation_status = 'valid'
                    WHERE run_id = %s
                    """,
                    (run_id,),
                )
                # Recorded ABOUT the agent's answer, not BY a tool the agent can
                # call: agent/registry.py stays at seven read/synthesis-only
                # tools. Guarded on agent_run_id because
                # proof.action_proposals.agent_run_id is NOT NULL REFERENCES
                # proof.agent_runs and only answer_question() creates that row --
                # the Strands and /v1/tools/synthesize paths pass None, and an
                # unguarded INSERT would turn those endpoints into 500s.
                # Guarded on 'bedrock' because an extractive fallback
                # concatenates evidence sentences and recommends nothing;
                # emitting a proposal from it would attribute a recommendation to
                # an agent that never made one.
                if agent_run_id and synthesis["mode"] == "bedrock":
                    from .action_proposal import (
                        persist_action_proposal,
                        propose_action_live,
                    )

                    persist_action_proposal(
                        cursor,
                        agent_run_id=agent_run_id,
                        run_id=run_id,
                        fields=propose_action_live(question, answer, evidence),
                        valid_citation_numbers=citation_numbers,
                    )
    return citations
```

  **Do not wrap this in `try/except`.** A failure here aborts the transaction and
  raises, which discards the answer too — and that is correct: a Lab 3 answer with
  no recorded proposal is a Lab 4 that has nothing to approve, and a silently
  missing proposal is discovered by a participant mid-lab rather than by this
  task's tests. The import is function-local to match the existing
  `from .synthesis import synthesize_live` pattern in
  `synthesize_cited_answer_impl` and to keep `backend/app/agent.py`'s import
  graph unchanged for the modules that never emit a proposal.

- [ ] **Step 9: Run the pure test suite plus the existing agent tests.**

```bash
.venv/bin/python -m pytest backend/tests/test_action_proposal.py \
  backend/tests/test_agent_and_synthesis.py backend/tests/test_agent_tools.py \
  backend/tests/test_strands_agent.py backend/tests/test_mcp_contract.py -v
```

Expected: all PASS. The last three matter more than the first: they exercise the
paths that pass `agent_run_id=None`, and a regression there is the failure mode
this task's step-4 guard exists to prevent.

- [ ] **Step 10: Run the live emission tests against Aurora.**

```bash
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python -m pytest backend/tests/test_action_proposal.py -v \
  -k ProposalEmissionTests
```

Expected: PASS. Each of the first three tests costs one full agent answer — the
measured ~25s synthesis plus this task's added structured-output call. **Record the
measured wall-clock of the added call in the gate-results document**, because it
lands directly on the Lab 3 wait a participant sits through and Task D2 step 7
already commits the facilitator guidance to a number.

  Two failures have specific meanings, and the difference matters:
  - `model did not call record_action_proposal` — the forced `toolChoice` was
    dropped or the model ID is not a tool-capable profile. Check
    `BEDROCK_SYNTHESIS_MODEL` resolves to a Claude profile; do not "fix" this by
    making the tool optional and parsing prose.
  - `pre_execution_eligible` false with reason
    `no_equivalent_index_exists` unsatisfied — the index from Task A5 step 15's
    fingerprint measurement was left on the table. Drop it (A5 step 16) and rerun.
    This is the precondition doing its job, not a defect.

- [ ] **Step 11: Live-Aurora acceptance criteria.**
  1. One `proof.action_proposals` row per `/v1/agent/answer` call, with
     `action_type = 'create_index'`, `target_schema = 'workbench_lab'`,
     `target_table = 'orders'`, and `key_columns` containing `priority_tier`
     before `created_at`. **The column order is the agent's finding, not a
     constant this task supplies** — if the model proposes a different order, the
     corpus is not carrying the plan evidence Task C1 owes, and that is a Phase C
     defect to fix there rather than a value to hardcode here.
  2. `proposed_fingerprint` equals the fingerprint
     `proof.observed_index_fingerprint()` returns for the index the rendered
     `proposed_sql` actually creates. Verify by executing the stored
     `proposed_sql` as owner in a scratch transaction and rolling back:

```bash
psql -X -v ON_ERROR_STOP=1 "<uri>" <<'SQL'
DO $guard$
BEGIN
  IF current_database() <> 'dat410_review_remediation_test' THEN
    RAISE EXCEPTION 'refusing to run against %', current_database();
  END IF;
END
$guard$;
BEGIN;
  DO $probe$
  DECLARE
    v_proposal proof.action_proposals;
    v_observed text;
  BEGIN
    SELECT * INTO v_proposal FROM proof.action_proposals
     ORDER BY created_at DESC LIMIT 1;
    EXECUTE v_proposal.proposed_sql;
    SELECT f.fingerprint INTO v_observed
      FROM pg_class c
      CROSS JOIN proof.observed_index_fingerprint(c.oid) f
     WHERE c.relnamespace = 'workbench_lab'::regnamespace
       AND c.relkind = 'i'
       AND f.fingerprint = v_proposal.proposed_fingerprint;
    RAISE NOTICE 'proposed=% observed=% match=%',
      left(v_proposal.proposed_fingerprint, 16), left(coalesce(v_observed, 'none'), 16),
      v_observed IS NOT NULL;
  END
  $probe$;
ROLLBACK;
SQL
```

  Expected: `match=t`. This is the single most important acceptance check in the
  task — it proves the rendered SQL and the recorded fingerprint describe the same
  index, which is what makes Lab 4's comparison evidence rather than assertion. The
  `ROLLBACK` is why this probe is safe to run before the participant's own
  `CREATE INDEX`.
  3. `proof.autonomy_readiness(proposal_id)` returns
     `pre_execution_eligible = true` with an empty reasons array, and
     `post_execution_validated = false` with exactly
     `{"no execution has been recorded yet"}`.
  4. `gates/checks.sh` passes, including G-34 — which now runs against a database
     that actually holds a proposal, satisfying A6 step 5's fourth criterion
     ("proposals but no executions still PASSES") with real data rather than an
     empty table.
  5. `/v1/agent/strands/answer` and `/v1/tools/synthesize` still return 200 and
     write no proposal row.

- [ ] **Step 12: Cleanup and failure recovery.** Every live run writes a real
  `proof.agent_runs`, `proof.retrieval_runs`, `proof.agent_answers`, and
  `proof.action_proposals` row. Those are real runs and they stay — the
  `UNIQUE (agent_run_id)` constraint is per-run, so repeated runs accumulate
  independent proposals rather than conflicting. Do not delete them to "clean up";
  `proof.action_proposals` carries `ON DELETE RESTRICT` to `proof.agent_runs`
  precisely so a proposal cannot be orphaned by a tidy-up. If step 10's probe
  index survives a failed `ROLLBACK`, drop it explicitly:

```bash
psql -X -v ON_ERROR_STOP=1 "<uri>" -c \
  "DROP INDEX IF EXISTS workbench_lab.idx_orders_priority_tier_created_at;"
```

- [ ] **Step 13: Participant-facing changes.** None in this task, with one
  handoff. The proposal is written but nothing renders it yet — Task E4 owns the
  Lab 4 verdict panel and Task D3 owns the participant instruction that hands them
  the stored `proposed_sql`. What this task does change is the Lab 3 wait: the
  added Converse call extends it, and the number measured in step 10 must reach
  the facilitator guidance Task D2 step 7 writes. Two sequential model calls that
  look like a hang in a room of 200 people is a delivery problem, not a
  footnote.

- [ ] **Step 14: Commit.**

```bash
git add backend/app/action_proposal.py backend/app/agent.py \
  backend/tests/test_action_proposal.py
git commit -m "Record the agent's structured action proposal in the answer path"
```

**Dependencies:** Task A5 (the schema, the fingerprint functions, and the
INSERT-only grant), Task C3 (an indexed corpus the agent can answer from), and
Task D2 (which establishes that the diagnostic answer is Wave-A-only — the answer
this task derives the proposal from).

**Known limitation, stated rather than hidden:** the Strands and
`/v1/tools/synthesize` paths produce no proposal because they create no
`proof.agent_runs` row. Giving them one is out of scope for this plan. If a later
change makes Strands the canonical Lab 3 path, that change owns adding the
`proof.agent_runs` row, and this task's step-8 guard will keep it honest in the
meantime by writing nothing rather than writing a proposal with a fabricated
parent.

### Task D3: Add Lab 4's participant-executed index step and validation replay

**Owning schema/module:** `labs/exercises/`; sibling Workshop Studio repo's Lab 4
content; the execution recorder in `labs/incident/run_live_workshop.py`.

**Files:**
- Modify: `labs/exercises/` — Lab 4's exercise definition
- Modify: `sql/11_roles_rls.sql` — the `workbench_lab_owner` role and its two
  memberships (`workshop_participant` and `current_user`, step 3). **Not a
  schema-level `GRANT`**: measured, no grantable privilege permits `CREATE INDEX`.
  **Not `workshop_app` either** — the pool gets DML in step 3a instead, because
  owner membership would give the pool identity passive DDL
- Modify: `labs/incident/run_live_workshop.py` — four separate edits: the
  supervised-execution recorder in the Wave B capture path (steps 7–8), plus
  `_create_lab_workload` + the new `_create_lab_tables` and `_grant_lab_writes`
  helpers (schema and table ownership, step 3a), `main()`'s
  wave routing (step 3b), and `main()`'s cleanup guard (step 3c). The last three
  are not incidental: without them Lab 4's table does not exist when Lab 4 runs
- Modify (sibling repo): Lab 4's content page
- Test: `backend/tests/test_incident_lab.py`

**Interfaces:**
- Consumes: Task C2's `--wave B` entry point, Task B5's `after_index` checkpoint,
  Task D2a's stored `proof.action_proposals` row (`proposed_sql` is what the
  participant runs; `proposed_fingerprint` is what the catalog is compared
  against), Task A5's `proof.observed_index_fingerprint(oid)` and
  `proof.autonomy_readiness(uuid)`.
- Produces: `record_action_execution(conn, *, proposal_id, approved_by,
  observed_index_oid, outcome, outcome_detail, started_at, completed_at,
  plan_before_checkpoint, plan_after_checkpoint, wave_b_capture_id,
  wave_b_ingest_id) -> str` in `labs/incident/run_live_workshop.py`, returning the new
  `execution_id`; and the participant-facing Lab 4 sequence: review the agent's
  proposal → approve it explicitly → execute the proposal's own DDL in Code
  Editor → run `--wave B`, which records the execution and admits the validation
  evidence → replay the Lab 3 investigation unchanged alongside the new proof.

**Migration and compatibility implications:** the participant runs the DDL
themselves — the agent never gets DDL privilege or an execution path, per Global
Constraints — so `workshop_participant` must actually be able to create an index on
`workbench_lab.orders`. Three separate things block that today, all measured on
PostgreSQL 17.10; read all three before writing step 3, because the obvious fix
(`GRANT CREATE ON SCHEMA`) fails all three.

1. **`CREATE INDEX` has no grantable privilege. It requires table ownership.**
   Measured: a role holding `CREATE, USAGE ON SCHEMA` *plus*
   `SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN` on the
   table still gets `ERROR: must be owner of table orders`. `MAINTAIN` (new in
   PG 17) covers `REINDEX`, not `CREATE INDEX`. There is no grant that fixes this;
   the participant must *own* the table, directly or through a role it is a member
   of.
2. **Object grants do not survive `_create_lab_workload`.**
   `labs/incident/run_live_workshop.py:163-165` runs
   `DROP SCHEMA IF EXISTS workbench_lab CASCADE` then `CREATE SCHEMA workbench_lab`
   on every prepare. Measured: a schema grant issued before that sequence reads
   back `f` after it, and nothing in the codebase reissues it. Role *membership*
   does survive, because it lives on the role rather than on the dropped object —
   which is why the fix in step 3 is a role, not a grant.
3. **A `GRANT … ON SCHEMA workbench_lab` statement cannot even execute in
   `sql/11_roles_rls.sql`.** That file runs under `make security-schema` against a
   database where `workbench_lab` does not exist yet — the schema is created by
   `make live-workshop`, later. Measured: `ERROR: schema "workbench_lab" does not
   exist`, and `backend/scripts/run_sql.py` re-raises, so the statement breaks
   `make security-schema` on a fresh database outright.

4. **The API pool must not get there by the same route.** The obvious fix to defect
   2 — make `workshop_app` a member of the owner role too — is wrong, and it is
   wrong in the direction that matters. `sql/11_roles_rls.sql:20-27` documents
   `workshop_app` as holding **no direct table grants** and failing closed without a
   `SET ROLE`; owner membership would hand the pool identity `CREATE INDEX`, `DROP
   TABLE`, and `TRUNCATE` on the lab table passively, on every request. But the pool
   does need writes: Gate 1 proved the hot-write path as
   `UPDATE workbench_lab.orders …` through the pool with no `SET ROLE`, and Task
   B2 owns the supported endpoint.
   Measured on PostgreSQL 17.10, the narrow grant is exactly sufficient and exactly
   bounded — with `USAGE ON SCHEMA` plus `SELECT, INSERT, UPDATE, DELETE ON ALL
   TABLES` and no ownership, `UPDATE` succeeds while `CREATE INDEX` and `DROP TABLE`
   fail with `must be owner of table orders`, `TRUNCATE` fails with `permission
   denied for table orders`, and `CREATE TABLE` in the schema fails with `permission
   denied for schema workbench_lab`.

The fix, measured end to end in step 3: a `workbench_lab_owner` role created in
`sql/11_roles_rls.sql` (which touches no `workbench_lab` object, so it is safe to
run before bootstrap), granted to `workshop_participant` **only**, and
`CREATE SCHEMA workbench_lab AUTHORIZATION workbench_lab_owner` with the tables
created as that role in `_create_lab_workload`. The API pool gets DML instead of
membership, granted inside the rebuild by `_grant_lab_writes` (step 3a) so it
survives every `DROP SCHEMA CASCADE`. Measured result: the participant's
`CREATE INDEX` succeeds with **zero** schema-level or table-level `GRANT`
statements, and still succeeds after a second full
`DROP SCHEMA CASCADE` / `CREATE SCHEMA … AUTHORIZATION` cycle with no re-grant;
the pool's `UPDATE` succeeds across the same cycle and its `CREATE INDEX` does not.

Check the result against `gates/participant_ceremony.py`'s privilege model: it
asserts `workshop_participant` is denied on `casework.evidence_items` /
`retrieval.documents` / `retrieval.chunks` and has no
`rolsuper`/`rolbypassrls`/`rolcreaterole`/`rolcreatedb`, and grants monitoring
views. A `workbench_lab_owner` membership violates none of those: the role is
`NOLOGIN`, owns nothing outside `workbench_lab`, and confers no role attributes.
`workbench_lab` is deliberately not in `DENIED_TABLES` — it is the one schema the
participant is *supposed* to be able to change.

A plain `CREATE INDEX` (not `CONCURRENTLY`) is correct here because the table is
not under concurrent write load at that point, and `CONCURRENTLY` would add
complexity for no teaching benefit. Its wall-clock duration on 3,000,000 rows is
an **unmeasured number** — see Task G1's measurement list — and Lab 4's content
must not state a figure until G1 measures one.

- [ ] **Step 1: Write the failing test.** It must *attempt the actual DDL* as the
  participant and roll it back. Do not probe `has_schema_privilege` — measured, it
  returns `t` in exactly the state where `CREATE INDEX` raises
  `must be owner of table orders`, so the privilege-probing form of this test is
  green-on-broken and would certify the defect it exists to catch.

```python
@unittest.skipUnless(
    PARTICIPANT_DSN and SECURITY_ENABLED,
    "set WORKSHOP_PARTICIPANT_DATABASE_URL and WORKBENCH_SECURITY_ENABLED=1",
)
class ParticipantIndexPrivilegeTests(unittest.TestCase):
    """Lab 4's central step, executed rather than inferred.

    CREATE INDEX has no grantable privilege in PostgreSQL: it requires table
    ownership. Measured on PG 17.10, a role holding CREATE, USAGE ON SCHEMA plus
    SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN on the
    table still raises `must be owner of table orders`. So this test does the only
    thing that proves the claim: it runs the statement, then rolls it back.
    """

    def test_the_participant_can_create_an_index_on_the_lab_table(self) -> None:
        with psycopg.connect(PARTICIPANT_DSN) as conn, conn.cursor() as cur:
            cur.execute("SELECT current_user")
            self.assertEqual(cur.fetchone()[0], "workshop_participant")
            cur.execute("BEGIN")
            try:
                cur.execute(
                    "CREATE INDEX probe_participant_can_index "
                    "ON workbench_lab.orders (customer_id, created_at DESC)"
                )
            except psycopg.errors.InsufficientPrivilege as exc:
                self.fail(
                    "Lab 4's central step is the participant creating an index on "
                    "workbench_lab.orders, and the participant cannot: "
                    f"{exc}. CREATE INDEX requires table OWNERSHIP -- no GRANT "
                    "fixes this. See step 3's workbench_lab_owner role."
                )
            finally:
                cur.execute("ROLLBACK")

    def test_the_index_privilege_survives_a_workload_rebuild(self) -> None:
        """The regression the obvious fix does not survive.

        `_create_lab_workload` runs DROP SCHEMA ... CASCADE then CREATE SCHEMA on
        every prepare. Measured: a schema-level GRANT reads back `f` afterwards and
        nothing reissues it, so a grant-based fix works exactly once -- during the
        rehearsal, and never again in a real session. Role MEMBERSHIP survives,
        because it lives on the role rather than on the dropped object.
        """
        prepare_lab_workload(OWNER_DSN)
        self.test_the_participant_can_create_an_index_on_the_lab_table()


@unittest.skipUnless(
    APP_DSN and SECURITY_ENABLED,
    "set WORKSHOP_APP_DATABASE_URL and WORKBENCH_SECURITY_ENABLED=1",
)
class ApiPoolLabPrivilegeTests(unittest.TestCase):
    """The other half of the boundary: the pool writes, the pool does not alter.

    The hot-write path runs `UPDATE workbench_lab.orders` through the pool with no
    SET ROLE (Task B2), so workshop_app needs DML.
    It must NOT get that by joining workbench_lab_owner, which would hand the pool
    identity CREATE INDEX, DROP TABLE and TRUNCATE passively on every request. Both
    halves are executed here, because a privilege boundary that is asserted and
    never exercised is the same green-on-broken shape as the has_schema_privilege
    probe above.
    """

    def test_the_pool_can_write_to_the_lab_table(self) -> None:
        with psycopg.connect(APP_DSN) as conn, conn.cursor() as cur:
            cur.execute("SELECT current_user")
            self.assertEqual(cur.fetchone()[0], "workshop_app")
            cur.execute("BEGIN")
            try:
                cur.execute(
                    "UPDATE workbench_lab.orders SET status = 'touched' "
                    "WHERE order_id = (SELECT min(order_id) FROM workbench_lab.orders)"
                )
            except psycopg.errors.InsufficientPrivilege as exc:
                self.fail(
                    "the hot-write path drives UPDATE workbench_lab.orders through "
                    f"the pool and the pool cannot write: {exc}. See step 3a's "
                    "_grant_lab_writes -- the grant must be issued INSIDE the "
                    "rebuild, because DROP SCHEMA CASCADE destroys it."
                )
            finally:
                cur.execute("ROLLBACK")

    def test_the_pool_cannot_alter_the_lab_table(self) -> None:
        forbidden = (
            ("CREATE INDEX probe_pool_must_not_index "
             "ON workbench_lab.orders (customer_id)"),
            "DROP TABLE workbench_lab.orders",
            "TRUNCATE workbench_lab.orders",
            "CREATE TABLE workbench_lab.probe_pool_must_not_create (i int)",
        )
        with psycopg.connect(APP_DSN) as conn, conn.cursor() as cur:
            for statement in forbidden:
                with self.subTest(statement=statement):
                    cur.execute("BEGIN")
                    try:
                        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                            cur.execute(statement)
                    finally:
                        cur.execute("ROLLBACK")

    def test_the_pool_is_not_a_member_of_the_lab_owner_role(self) -> None:
        """State the intent directly, so the reason survives a refactor.

        The two behavioural tests above would also pass if someone granted the pool
        every table privilege individually. This one says why they pass.
        """
        with psycopg.connect(OWNER_DSN) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT pg_has_role('workshop_app', 'workbench_lab_owner', 'USAGE')"
            )
            self.assertFalse(
                cur.fetchone()[0],
                "workshop_app is a member of workbench_lab_owner; the pool "
                "identity now holds passive DDL on the lab table",
            )
```

  `APP_DSN` reads `WORKSHOP_APP_DATABASE_URL`, alongside the existing
  `PARTICIPANT_DSN`/`OWNER_DSN`/`SECURITY_ENABLED` module constants. Follow
  `backend/tests/test_rls_personas.py:20-135` for the `load_dotenv(override=False)`
  handling — the same hazard comment there applies.

  `test_the_pool_cannot_alter_the_lab_table` asserts the *failure*, which is the
  inversion that makes it meaningful: three of those four statements are refused for
  ownership reasons and one for schema `USAGE`, and all four must stay refused. Note
  that `psycopg.errors.InsufficientPrivilege` is SQLSTATE 42501 and covers both
  `must be owner of table orders` and `permission denied for …` — measured, so a
  narrower exception class would miss half the cases.

- [ ] **Step 2: Run it and confirm it fails.**

```bash
WORKBENCH_SECURITY_ENABLED=1 \
WORKSHOP_PARTICIPANT_DATABASE_URL="postgresql://workshop_participant@<host>:5432/dat410_review_remediation_test?sslmode=require" \
WORKSHOP_APP_DATABASE_URL="postgresql://workshop_app@<host>:5432/dat410_review_remediation_test?sslmode=require" \
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
ALLOW_TEST_DATABASE_RESET=1 \
  .venv/bin/python -m pytest backend/tests/test_incident_lab.py \
    -k "ParticipantIndexPrivilege or ApiPoolLabPrivilege" -v
```

Expected, and the mix matters — read each line, do not just count failures:

- both `ParticipantIndexPrivilegeTests` FAIL with `must be owner of table orders`
  (SQLSTATE 42501), not with a missing-grant message. That exact error text is the
  point: it is what tells you a `GRANT` will not fix this.
- `test_the_pool_can_write_to_the_lab_table` FAILS — today the pool has no grant on
  `workbench_lab` at all.
- `test_the_pool_cannot_alter_the_lab_table` and
  `test_the_pool_is_not_a_member_of_the_lab_owner_role` **PASS already**, because
  today nothing grants the pool anything. They are regression guards on the fix, not
  demonstrations of a current defect. A test that passes before the change is only
  worth keeping if it can fail after one — so before moving on, verify these two can:
  temporarily run `GRANT workbench_lab_owner TO workshop_app` as owner, re-run, and
  confirm BOTH flip to FAIL. Then `REVOKE workbench_lab_owner FROM workshop_app`.
  If either still passes with that grant in place, the test is wrong.

- [ ] **Step 3: Add the owner role to `sql/11_roles_rls.sql`.** Place it beside the
  existing login-role block (`sql/11_roles_rls.sql:285-294`), **not** near any
  `workbench_lab` object reference. This file runs under `make security-schema`
  against a database where `workbench_lab` does not exist yet — measured, a
  `GRANT ... ON SCHEMA workbench_lab` there raises
  `ERROR: schema "workbench_lab" does not exist`, and `backend/scripts/run_sql.py`
  re-raises, breaking `make security-schema` on a fresh database. A `CREATE ROLE`
  plus role grants touch no `workbench_lab` object, so they are safe to run first.

```sql
-- ---------------------------------------------------------------------------
-- The lab-workload owner.
--
-- Lab 4's central step is the participant running CREATE INDEX on
-- workbench_lab.orders themselves, because the agent holds no DDL privilege by
-- design. CREATE INDEX has NO grantable privilege in PostgreSQL -- it requires
-- table ownership. Measured on PG 17.10: a role holding CREATE, USAGE ON SCHEMA
-- plus SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN on
-- the table still gets `ERROR: must be owner of table orders`. MAINTAIN (new in
-- PG 17) covers REINDEX, not CREATE INDEX. So the participant must OWN the table.
--
-- Shared ownership through a role, not direct ownership, and not a GRANT, for two
-- measured reasons:
--
--   * A GRANT would not survive. run_live_workshop.py's _create_lab_workload runs
--     DROP SCHEMA IF EXISTS workbench_lab CASCADE then CREATE SCHEMA on every
--     prepare. Measured: has_schema_privilege goes t -> f across that sequence and
--     nothing reissues the grant. Role MEMBERSHIP survives, because it lives on
--     the role rather than on the dropped object. Measured across two full
--     DROP/CREATE cycles: the participant still indexed, with zero re-grants.
--   * Direct ownership by workshop_participant would put the orchestrator's own
--     DDL (which runs as the bootstrap owner) on the wrong side of the boundary.
--     A shared owner role that BOTH are members of keeps every path working.
--
-- NOLOGIN: this role is an ownership handle, never an identity anyone connects as.
-- It owns nothing outside workbench_lab and confers no role attributes, so
-- gates/participant_ceremony.py (G-30) stays green -- its FORBIDDEN_ATTRIBUTES
-- check reads pg_roles attributes, and membership in a NOLOGIN owner role sets
-- none of them.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'workbench_lab_owner') THEN
    CREATE ROLE workbench_lab_owner NOLOGIN;
  END IF;
END
$$;

-- INHERIT TRUE here, deliberately breaking with the INHERIT FALSE convention two
-- sections above, and the difference is not cosmetic. The persona grants are
-- INHERIT FALSE so a forgotten SET LOCAL ROLE fails CLOSED on the read path. This
-- grant has the opposite requirement: the participant types CREATE INDEX into a
-- plain psql session in Code Editor with no SET ROLE ceremony. Measured under
-- INHERIT FALSE: the passive CREATE INDEX raises `permission denied for schema
-- workbench_lab` and only succeeds after an explicit SET ROLE -- which would put
-- a ceremony step in front of the one action Lab 4 is about. There is no read-path
-- exposure to fail open on: workbench_lab holds no evidence, no ACL column and no
-- RLS policy. It is the disposable operational substrate.
--
-- workshop_participant ONLY. workshop_app is deliberately NOT a member -- see the
-- Migration paragraph's defect 4 and step 3a's DML grant.
GRANT workbench_lab_owner TO workshop_participant;

-- The bootstrap owner too: _create_lab_workload's DROP SCHEMA CASCADE must be able
-- to drop a schema it no longer owns. Measured: a non-superuser CREATEROLE role
-- that is a MEMBER of workbench_lab_owner drops the schema successfully, so this
-- needs no superuser on Aurora. current_user rather than a literal, for the same
-- reason section 2 gives: the owner is retrieval_admin locally and workshop_admin
-- on a provisioned cluster.
DO $$
BEGIN
  EXECUTE format('GRANT workbench_lab_owner TO %I', current_user);
END
$$;
```

  Then add `workbench_lab_owner` to the ADMIN OPTION preflight list at
  `sql/11_roles_rls.sql:145` (`unnest(ARRAY['can_see_restricted', ...])`). Without
  it, the three grants above fail with 42501 on a cluster where the roles outlived
  the owner that created them, and the preflight's whole purpose is to catch that
  before any grant runs.

- [ ] **Step 3a: Make `_create_lab_workload` create the schema and tables as that
  role.** In `labs/incident/run_live_workshop.py:163-165`, replace the bare
  `CREATE SCHEMA workbench_lab`. **The role must be optional**: the security module
  is off by default (`.env.example`: `WORKBENCH_SECURITY_ENABLED=0`), `sql/11` is
  applied only by `make security-schema`, and it is the only file that creates any
  role. Measured: `CREATE SCHEMA wblab AUTHORIZATION <absent role>` raises
  `ERROR: role "..." does not exist` — so an unconditional change breaks
  `make live-workshop` for every default install.

```python
LAB_SCHEMA_OWNER = "workbench_lab_owner"
LAB_WRITER_ROLE = "workshop_app"


def _create_lab_workload(connection: psycopg.Connection) -> None:
    connection.execute("DROP SCHEMA IF EXISTS workbench_lab CASCADE")
    # Ownership, not a GRANT: CREATE INDEX requires it, and Lab 4's central step is
    # the participant running CREATE INDEX. Conditional because the owner role
    # exists only when the optional security module (sql/11_roles_rls.sql) has been
    # applied; CREATE SCHEMA ... AUTHORIZATION raises outright on an absent role.
    owned = connection.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s) AS present",
        (LAB_SCHEMA_OWNER,),
    ).fetchone()["present"]
    if owned:
        connection.execute(
            sql.SQL("CREATE SCHEMA workbench_lab AUTHORIZATION {}").format(
                sql.Identifier(LAB_SCHEMA_OWNER)
            )
        )
        connection.execute(
            sql.SQL("SET ROLE {}").format(sql.Identifier(LAB_SCHEMA_OWNER))
        )
    else:
        connection.execute("CREATE SCHEMA workbench_lab")
    try:
        _create_lab_tables(connection)
        if owned:
            _grant_lab_writes(connection)
    finally:
        if owned:
            connection.execute("RESET ROLE")


def _grant_lab_writes(connection: psycopg.Connection) -> None:
    """Give the API pool DML on the lab tables, and nothing more.

    Issued HERE rather than in sql/11 for a measured reason: DROP SCHEMA CASCADE
    destroys every grant on the schema, so a grant written in sql/11 is gone after
    the first rebuild and nothing reissues it. Inside the rebuild, it survives every
    cycle. Runs as LAB_SCHEMA_OWNER (the caller has already SET ROLE), which is the
    only role that can grant on tables it owns.

    DML only, deliberately. workshop_app is NOT a member of workbench_lab_owner:
    the pool needs UPDATE for the hot-write path and must not gain DDL. Measured on
    PostgreSQL 17.10 with exactly these grants -- UPDATE succeeds; CREATE INDEX and
    DROP TABLE fail with `must be owner of table orders`; TRUNCATE fails with
    `permission denied for table orders`; CREATE TABLE in the schema fails with
    `permission denied for schema workbench_lab`.
    """
    writer = sql.Identifier(LAB_WRITER_ROLE)
    connection.execute(
        sql.SQL("GRANT USAGE ON SCHEMA workbench_lab TO {}").format(writer)
    )
    connection.execute(
        sql.SQL(
            "GRANT SELECT, INSERT, UPDATE, DELETE "
            "ON ALL TABLES IN SCHEMA workbench_lab TO {}"
        ).format(writer)
    )
    connection.execute(
        sql.SQL(
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA workbench_lab TO {}"
        ).format(writer)
    )
```

  `SET ROLE` rather than `SET LOCAL ROLE`: this connection is opened with
  `autocommit=True` (`prepare_lab_workload`, `run_live_workshop.py:297-301`), so
  there is no enclosing transaction for `LOCAL` to scope to and it would silently
  do nothing. The `finally: RESET ROLE` is what keeps that safe. Move the existing
  table and insert statements (`:166-222`) verbatim into `_create_lab_tables`;
  splitting is required, because `_create_lab_workload` now has two exit paths and
  the tables must be created under the role in both.

  `_grant_lab_writes` runs inside the `try`, before the `RESET ROLE`, and only on
  the `owned` branch. On the security-off branch there is no `workshop_app` role to
  grant to — the same reason the ownership change is conditional — and the bootstrap
  owner already owns everything, so nothing is needed.

  **`ON ALL TABLES IN SCHEMA` is evaluated at grant time, not as a standing rule.**
  It covers the tables `_create_lab_tables` just created, which is why the call sits
  after it. A table added to `workbench_lab` later in the same run would get no
  grant. If Task B1's larger build ever creates a table after this point, the grant
  moves after that too — do not paper over it with `ALTER DEFAULT PRIVILEGES`, which
  would apply to every future object created by that role and is broader than this
  needs.

  Import `sql` from `psycopg` for the identifier quoting. Do not build these
  statements with f-strings: `CREATE SCHEMA ... AUTHORIZATION` and `GRANT ... TO
  <role>` both take identifiers, not parameters, so `%s` binding is not available
  and `sql.Identifier` is the only safe form.

- [ ] **Step 3b: Write the Lab 4 exercise copy.** The participant runs the exact
  DDL the agent recommended, verbatim from the agent's output rather than copied
  from the lab text — that is what makes it *their* validation of *the agent's*
  recommendation rather than a scripted step. State no duration for the index
  build: that number is unmeasured until Task G1 measures it.

- [ ] **Step 4: Run the tests.**

```bash
WORKBENCH_SECURITY_ENABLED=1 \
WORKSHOP_PARTICIPANT_DATABASE_URL="postgresql://workshop_participant@<host>:5432/dat410_review_remediation_test?sslmode=require" \
WORKSHOP_APP_DATABASE_URL="postgresql://workshop_app@<host>:5432/dat410_review_remediation_test?sslmode=require" \
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
ALLOW_TEST_DATABASE_RESET=1 \
  .venv/bin/python -m pytest backend/tests/test_incident_lab.py \
    -k "ParticipantIndexPrivilege or ApiPoolLabPrivilege" -v
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  gates/checks.sh
WORKBENCH_SECURITY_ENABLED=1 FAIL_ON_BLOCKED=1 \
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  gates/checks.sh G-27 G-29 G-30 G-31
```

Expected: all five tests PASS, and the security gates stay green — the new
membership must not widen participant privilege anywhere G-30 checks, and the pool's
DML grant must not appear as a leak anywhere G-27/G-31 check. Run `gates/checks.sh`
whole here rather than a subset: the pool identity is the same connection the
retrieval gates exercise, and a grant that widened it would show up there first.

- [ ] **Step 4a: Prove the default, security-off path still works.** This is the
  path every participant who never runs `make security-schema` takes, and step 3a's
  conditional is the only thing protecting it. Run against a database with **no**
  `workbench_lab_owner` role:

```bash
psql -X -v ON_ERROR_STOP=1 \
  "postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" <<'SQL'
DO $guard$ BEGIN
  IF current_database() <> 'dat410_review_remediation_test' THEN
    RAISE EXCEPTION 'SAFETY ABORT: connected to %', current_database();
  END IF;
END $guard$;
SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='workbench_lab_owner') AS owner_role_present;
SQL
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  .venv/bin/python -m labs.incident.run_live_workshop --bootstrap-only
```

Expected: `owner_role_present = f`, and bootstrap completes with the schema owned
by the connecting role — byte-identical behaviour to today. If this errors with
`role "workbench_lab_owner" does not exist`, step 3a's conditional is wrong and
every default install is broken.

- [ ] **Step 5: Write the failing execution-recorder test.** Add to
  `backend/tests/test_incident_lab.py`. This is the half of the Supervised
  Execution Model that proves what the participant *actually ran*, and the
  fingerprint comparison is the whole point of it.

```python
    def test_execution_records_the_observed_index_not_the_proposed_one(self) -> None:
        """The observed definition is read back from pg_index, never trusted from
        the input. Reading it back is what makes the comparison evidence."""
        proposal_id, expected_fingerprint = self._latest_proposal()
        index_oid = self._create_the_proposed_index(proposal_id)
        execution_id = record_action_execution(
            self._owner_conn(),
            proposal_id=proposal_id,
            approved_by="workshop_participant",
            observed_index_oid=index_oid,
            outcome="succeeded",
            outcome_detail=None,
            started_at=self._started_at,
            completed_at=self._completed_at,
            plan_before_checkpoint="before_analyze",
            plan_after_checkpoint="after_index",
            wave_b_capture_id=self._capture_id,
            wave_b_ingest_id=self._ingest_id,
        )
        row = self._execution(execution_id)
        self.assertEqual(row["observed_fingerprint"], expected_fingerprint)
        self.assertTrue(row["fingerprint_matches"])
        self.assertIn("CREATE INDEX", row["observed_index_definition"])

    def test_a_differently_shaped_index_is_recorded_as_a_mismatch(self) -> None:
        """A participant who indexes (created_at, priority_tier) instead has run a
        DIFFERENT action. The record must say so rather than pass."""
        proposal_id, expected_fingerprint = self._latest_proposal()
        index_oid = self._create_index(
            "idx_orders_reversed",
            "workbench_lab.orders (created_at DESC, priority_tier)",
        )
        execution_id = record_action_execution(
            self._owner_conn(),
            proposal_id=proposal_id,
            approved_by="workshop_participant",
            observed_index_oid=index_oid,
            outcome="succeeded",
            outcome_detail=None,
            started_at=self._started_at,
            completed_at=self._completed_at,
            plan_before_checkpoint="before_analyze",
            plan_after_checkpoint="after_index",
            wave_b_capture_id=self._capture_id,
            wave_b_ingest_id=self._ingest_id,
        )
        row = self._execution(execution_id)
        self.assertNotEqual(row["observed_fingerprint"], expected_fingerprint)
        self.assertFalse(row["fingerprint_matches"])

    def test_a_mismatched_execution_is_not_post_execution_validated(self) -> None:
        """The verdict must report the mismatch, not absorb it. Post-execution
        success never travels backwards into pre-execution eligibility."""
        proposal_id, _fingerprint = self._latest_proposal()
        index_oid = self._create_index(
            "idx_orders_reversed",
            "workbench_lab.orders (created_at DESC, priority_tier)",
        )
        record_action_execution(
            self._owner_conn(),
            proposal_id=proposal_id,
            approved_by="workshop_participant",
            observed_index_oid=index_oid,
            outcome="succeeded",
            outcome_detail=None,
            started_at=self._started_at,
            completed_at=self._completed_at,
            plan_before_checkpoint="before_analyze",
            plan_after_checkpoint="after_index",
            wave_b_capture_id=self._capture_id,
            wave_b_ingest_id=self._ingest_id,
        )
        verdict = self._verdict(proposal_id)
        self.assertFalse(verdict["post_execution_validated"])
        self.assertIn(
            "the executed action does not match the proposed action",
            verdict["post_execution_reasons"],
        )
        self.assertTrue(
            verdict["pre_execution_eligible"],
            "a mismatched execution must not retroactively invalidate the "
            "pre-execution assessment either -- the two verdicts are separate",
        )

    def test_the_recorder_takes_no_definition_argument(self) -> None:
        """A caller-supplied definition string would make the record an
        assertion. The signature must not offer that option."""
        import inspect

        parameters = inspect.signature(record_action_execution).parameters
        for forbidden in (
            "observed_index_definition",
            "observed_fingerprint",
            "fingerprint_matches",
        ):
            self.assertNotIn(
                forbidden, parameters,
                f"{forbidden} must be derived from the catalog, not passed in",
            )
```

- [ ] **Step 6: Run them and confirm they fail.**

```bash
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
ALLOW_TEST_DATABASE_RESET=1 \
  .venv/bin/python -m pytest backend/tests/test_incident_lab.py -v \
  -k "execution or fingerprint or post_execution"
```

Expected: ImportError on `record_action_execution`. The signature test failing
last is fine; it exists to stop a later "convenience" parameter from being added.

- [ ] **Step 7: Implement the recorder.** Add to `labs/incident/run_live_workshop.py`.
  **One `INSERT`, no `UPDATE`, and the observed values come from
  `proof.observed_index_fingerprint()` inside that same statement** — Task A5 step
  11 grants `INSERT` only, precisely so a failed outcome cannot later be rewritten
  as a success.

```python
def record_action_execution(
    conn: Connection,
    *,
    proposal_id: str,
    approved_by: str,
    observed_index_oid: int | None,
    outcome: str,
    outcome_detail: str | None,
    started_at: datetime | None,
    completed_at: datetime | None,
    plan_before_checkpoint: str | None,
    plan_after_checkpoint: str | None,
    wave_b_capture_id: str | None,
    wave_b_ingest_id: str | None,
) -> str:
    """Record what the participant actually executed, once.

    The observed index definition, its fingerprint, and whether it matches the
    proposal are all derived from the catalog inside this statement. There is
    deliberately no parameter for any of them: a caller-supplied definition would
    make this record an assertion about what was run instead of evidence of it.

    Args:
        conn: an owner connection. The participant's own role cannot read
            proof.action_proposals under RLS, and the execution row is the
            workshop's record rather than theirs to write.
        proposal_id: the proposal the participant approved.
        approved_by: the role or persona that gave the explicit approval.
        observed_index_oid: the oid of the index the participant created, or None
            when the outcome is 'failed'.
        outcome: 'succeeded' or 'failed'. There is no third value: a proposal
            never executed is the absence of a row here, not an 'abandoned' one.
        started_at, completed_at: when the participant ran the DDL.
        plan_before_checkpoint, plan_after_checkpoint: Task B5 checkpoint labels
            bracketing the change ('before_analyze' and 'after_index').
        wave_b_capture_id, wave_b_ingest_id: the Wave B capture and admission this
            validation belongs to. A NULL ingest id is why
            proof.autonomy_readiness reports 'the result was not validated by an
            admitted Wave B capture'.

    Returns:
        The new execution_id.

    Raises:
        LiveWorkshopError: if outcome is 'succeeded' without an index oid, which
            the table's own CHECK would reject anyway -- caught here to give the
            participant a legible message instead of a constraint violation.
    """
    if outcome == "succeeded" and observed_index_oid is None:
        raise LiveWorkshopError(
            "a succeeded execution must name the index that was created; "
            "record outcome='failed' when no index exists"
        )
    with conn.transaction(), conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO proof.action_executions(
              proposal_id, run_id, approved_by, executed_sql, executed_sql_sha256,
              observed_index_definition, observed_fingerprint, fingerprint_matches,
              outcome, outcome_detail, started_at, completed_at,
              plan_before_checkpoint, plan_after_checkpoint,
              wave_b_capture_id, wave_b_ingest_id
            )
            SELECT
              p.proposal_id,
              p.run_id,
              %(approved_by)s,
              observed.index_definition,
              CASE
                WHEN observed.index_definition IS NULL THEN NULL
                ELSE encode(sha256(convert_to(observed.index_definition, 'UTF8')),
                            'hex')
              END,
              observed.index_definition,
              observed.fingerprint,
              CASE
                WHEN observed.fingerprint IS NULL THEN NULL
                ELSE observed.fingerprint = p.proposed_fingerprint
              END,
              %(outcome)s, %(outcome_detail)s, %(started_at)s, %(completed_at)s,
              %(plan_before)s, %(plan_after)s, %(capture_id)s, %(ingest_id)s
            FROM proof.action_proposals p
            LEFT JOIN LATERAL (
              SELECT f.index_definition, f.fingerprint
              FROM proof.observed_index_fingerprint(%(index_oid)s::oid) f
              WHERE %(index_oid)s IS NOT NULL
            ) observed ON true
            WHERE p.proposal_id = %(proposal_id)s
            RETURNING execution_id
            """,
            {
                "proposal_id": proposal_id,
                "approved_by": approved_by,
                "index_oid": observed_index_oid,
                "outcome": outcome,
                "outcome_detail": outcome_detail,
                "started_at": started_at,
                "completed_at": completed_at,
                "plan_before": plan_before_checkpoint,
                "plan_after": plan_after_checkpoint,
                "capture_id": wave_b_capture_id,
                "ingest_id": wave_b_ingest_id,
            },
        )
        row = cursor.fetchone()
        if row is None:
            raise LiveWorkshopError(
                f"no proposal {proposal_id} exists to record an execution against"
            )
        return str(row[0])
```

  `executed_sql` records the definition PostgreSQL reports for the index that now
  exists, and `executed_sql_sha256` hashes that same text. Both are audit fields:
  the raw hash is stored and never compared, because whitespace, quoting, and
  equivalent syntax make raw-SQL equality brittle. `fingerprint_matches` is the
  authoritative answer to "did the participant execute the proposed action."

  **`run_id` is copied from the proposal by the `SELECT`, never passed in.** The
  composite FK `(proposal_id, run_id)` would reject a mismatch, but taking it from
  the proposal means the denormalized column cannot name a run belonging to a
  different persona in the first place — which is what the RLS policy on this
  table chains through.

- [ ] **Step 8: Call it from the Wave B capture path — recording FIRST, admission
  second, and the Wave B identifiers attached afterwards.** The obvious ordering
  is wrong and was corrected here after review. Recording only *after*
  `admit_wave_b()` returns means that a participant whose `CREATE INDEX` succeeded
  but whose admission then failed — Bedrock throttled, the pool exhausted, the
  network dropped — leaves **zero** `proof.action_executions` rows. The verdict
  then reports `no execution has been recorded yet`, which is a false statement
  about a real event: the index exists in the catalog. Worse, it is the same
  verdict a participant who never attempted Lab 4 gets, so the two are
  indistinguishable in the one place that is supposed to tell them apart.

  The sequence is therefore:

  1. Capture the `after_index` checkpoint.
  2. Resolve `observed_index_oid` by fingerprint (below) and call
     `record_action_execution(...)` with `wave_b_capture_id` and
     `wave_b_ingest_id` left NULL. This row is the durable fact that an execution
     happened, and it survives every downstream failure.
  3. Call Task C2's `admit_wave_b()`.
  4. Attach the receipt to the row just written.

  Step 4 is an `UPDATE`, which raises the question of who is permitted to run it.
  **This task grants no new privilege to answer that question, and the reason was
  measured rather than reasoned.** The recorder in step 7 takes an *owner*
  connection — its docstring says so, because the participant's own role cannot
  read `proof.action_proposals` under RLS — and the owner already holds `UPDATE`
  on its own table. An earlier draft of this step wrapped the attachment in a
  `SECURITY DEFINER` function granted to `workshop_participant`. Measured on
  PostgreSQL 17.10 on 2026-08-04, a plain `SECURITY INVOKER` function called on
  the owner connection attaches the receipt on the first call and raises
  `execution ... does not exist or already carries a Wave B receipt` on the
  second — identical behaviour. The `SECURITY DEFINER` marking and the
  `workshop_participant` grant bought nothing, and what they cost is real: every
  participant would gain the ability to attach an arbitrary capture and ingest id
  to *any* execution row in the table, including another participant's, through a
  function no code path calls on their behalf. It is removed. `INVOKER` rights,
  no grant.

  That leaves the actual hole this step must close, which the `SECURITY DEFINER`
  wrapper never closed either: the owner connection holds unrestricted `UPDATE`,
  so nothing above stops the recorder — or a later maintainer editing it — from
  rewriting `fingerprint_matches` from `false` to `true`. Global Constraints
  forbid *granting* `UPDATE` to non-owners; they do not constrain the owner. The
  enforcement therefore has to live in the table, not in the grant:

```sql
-- The receipt attachment. SECURITY INVOKER (the default) -- deliberately NOT
-- SECURITY DEFINER, and deliberately granted to nobody. Its only caller is the
-- Wave B recorder, which already runs as the owner. See the plan text above:
-- the DEFINER variant was measured to add no capability and to hand every
-- participant an arbitrary-row write.
--
-- The REVOKE below is necessary but NOT sufficient. This file is in
-- CORE_SQL_FILES and applies BEFORE sql/11_roles_rls.sql, whose persona loop runs
-- `GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA proof` -- evaluated over the
-- functions that exist, which by then includes this one. Measured: persona
-- EXECUTE goes f -> t across those two files. Task A5 step 11a adds the matching
-- targeted REVOKE inside that loop, and step 11b asserts no persona holds
-- EXECUTE. If you make this function SECURITY DEFINER, that stale grant becomes
-- an arbitrary-row write on every execution row -- which is why it is INVOKER.
CREATE OR REPLACE FUNCTION proof.attach_wave_b_receipt(
  p_execution_id uuid,
  p_capture_id uuid,
  p_ingest_id uuid
) RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog, proof, casework AS $$
BEGIN
  UPDATE proof.action_executions
     SET wave_b_capture_id = p_capture_id,
         wave_b_ingest_id = p_ingest_id
   WHERE execution_id = p_execution_id
     AND wave_b_capture_id IS NULL
     AND wave_b_ingest_id IS NULL;
  IF NOT FOUND THEN
    RAISE EXCEPTION
      'execution % does not exist or already carries a Wave B receipt',
      p_execution_id;
  END IF;
END
$$;

REVOKE ALL ON FUNCTION proof.attach_wave_b_receipt(uuid, uuid, uuid) FROM PUBLIC;

COMMENT ON FUNCTION proof.attach_wave_b_receipt(uuid, uuid, uuid) IS
  'Attaches a Wave B receipt to an already-recorded execution, once. Exists so '
  'the execution can be recorded BEFORE admission -- a successful CREATE INDEX '
  'followed by a failed admission must not vanish. Owner-only by design: the '
  'recorder that calls it already runs as the owner, so no GRANT is needed. Two '
  'REVOKEs keep it that way -- the one below, and the targeted one in '
  'sql/11_roles_rls.sql''s persona loop that undoes that file''s blanket GRANT '
  'EXECUTE ON ALL FUNCTIONS IN SCHEMA proof.';

-- The append-only rule, enforced where privilege cannot reach: the OWNER can
-- UPDATE this table, and the whole comparison collapses if a mismatch can be
-- edited into a match. Only the two Wave B receipt columns may ever change, and
-- only from NULL.
--
-- MEASURED on PostgreSQL 17.10, 2026-08-04, and TWO drafts of this trigger were
-- measured wrong before this one:
--
-- 1. The first draft silently reverted protected columns
--    (`NEW.outcome := OLD.outcome`) instead of raising. An `UPDATE` that set
--    `fingerprint_matches = true` and a receipt in ONE statement then succeeded,
--    wrote the receipt, kept the honest verdict -- and reported no error at all.
--    The caller believed it had rewritten the verdict; the log showed a
--    successful UPDATE. Silent correction is the wrong failure mode for an
--    integrity rule: it leaves the operator with a false belief and leaves
--    nothing behind. This version raises.
--
-- 2. The second draft refused ANY update to a row that already carried a
--    receipt. That also refuses the `ON DELETE SET NULL` on both receipt foreign
--    keys, because a referential action IS an UPDATE and fires BEFORE UPDATE
--    triggers. Measured: `DELETE FROM casework.incident_capture_runs` on a
--    referenced capture failed with `execution ... already carries a Wave B
--    receipt`, the delete rolled back, and the capture became undeletable for as
--    long as the execution row existed. So the rule is stated on the TRANSITION,
--    not on the row: NULL -> value is an attach, value -> NULL is the engine
--    clearing a dangling reference, value -> different value is the overwrite
--    that must never happen.
CREATE OR REPLACE FUNCTION proof.action_executions_append_only()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, proof AS $$
BEGIN
  IF NEW.execution_id      IS DISTINCT FROM OLD.execution_id
     OR NEW.proposal_id    IS DISTINCT FROM OLD.proposal_id
     OR NEW.run_id         IS DISTINCT FROM OLD.run_id
     OR NEW.approved_by    IS DISTINCT FROM OLD.approved_by
     OR NEW.approved_at    IS DISTINCT FROM OLD.approved_at
     OR NEW.outcome        IS DISTINCT FROM OLD.outcome
     OR NEW.fingerprint_matches IS DISTINCT FROM OLD.fingerprint_matches
     OR NEW.observed_fingerprint IS DISTINCT FROM OLD.observed_fingerprint
     OR NEW.observed_index_definition
          IS DISTINCT FROM OLD.observed_index_definition
     OR NEW.executed_sql   IS DISTINCT FROM OLD.executed_sql
     OR NEW.executed_sql_sha256 IS DISTINCT FROM OLD.executed_sql_sha256 THEN
    RAISE EXCEPTION
      'proof.action_executions is append-only except for its Wave B receipt; '
      'execution % attempted to change a verdict or provenance column',
      OLD.execution_id;
  END IF;
  IF (OLD.wave_b_capture_id IS NOT NULL
      AND NEW.wave_b_capture_id IS NOT NULL
      AND NEW.wave_b_capture_id <> OLD.wave_b_capture_id)
     OR (OLD.wave_b_ingest_id IS NOT NULL
         AND NEW.wave_b_ingest_id IS NOT NULL
         AND NEW.wave_b_ingest_id <> OLD.wave_b_ingest_id) THEN
    RAISE EXCEPTION
      'execution % already carries a different Wave B receipt',
      OLD.execution_id;
  END IF;
  RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS action_executions_append_only
  ON proof.action_executions;
CREATE TRIGGER action_executions_append_only
  BEFORE UPDATE ON proof.action_executions
  FOR EACH ROW EXECUTE FUNCTION proof.action_executions_append_only();
```

  **Measured 2026-08-04 on PostgreSQL 17.10, against a probe schema carrying this
  table's full column set, both receipt foreign keys with `ON DELETE SET NULL`,
  the composite FK, and the identity column** — six cases, all as stated:

  | case | result |
  | --- | --- |
  | first `attach_wave_b_receipt()` | succeeded; `outcome`/`fingerprint_matches` unchanged |
  | second attach on the same row | refused, `already carries a Wave B receipt` |
  | owner `UPDATE fingerprint_matches = true` | refused, append-only message |
  | owner `UPDATE outcome = 'failed'` | refused, append-only message |
  | `DELETE` the referenced capture run | succeeded; `wave_b_capture_id` cleared, verdict intact |
  | `DELETE` the referenced ingest receipt | succeeded; `wave_b_ingest_id` cleared, verdict intact |

  The last two are the cases the second draft broke, and they are why the rule is
  written on the transition rather than the row. The verdict columns came back
  `succeeded` / `false` after every one of the six.

  One gap remains open and is stated rather than hidden: `DELETE` on this table
  still succeeds for the owner, measured. Closing it would break Task A5 step
  16's cleanup path, which drops the test rows, so the trigger covers `UPDATE`
  only. A `DELETE` removes a record visibly; the defect this rule exists to stop
  is a record that *looks* honest while saying something else.

  **This DDL belongs to Task A5, not here.** Both objects go in
  `sql/13_supervised_execution.sql` at the end of A5's step 3, immediately after
  the `proof.action_executions` table they constrain — a trigger cannot be created
  before its table, and `sql/13` is A5's file. The text lives in this step because
  this is the step whose ordering requires them; A5's step 3 carries a pointer
  back to here.

  **The transient state is honest, not a bug.** Between steps 2 and 3 the row has
  `wave_b_ingest_id` NULL, so `proof.autonomy_readiness()` reports
  `the result was not validated by an admitted Wave B capture`. That is a true
  statement at that moment: the index exists, and its effect has not yet been
  admitted as evidence. `pre_execution_eligible` is unaffected, because it never
  reads this table at all. Compare the two failure modes directly: a participant
  whose admission failed sees "executed, not yet validated" — accurate, and it
  points at the actual next step — instead of "no execution has been recorded",
  which is false and points nowhere.

  A rerun after a fixed admission failure appends a second execution row rather
  than attaching to the first, and `ORDER BY approved_at DESC, recorded_seq DESC`
  makes the later one the reported attempt. That is the same append-only rerun
  path step 11 describes, and it is why `attach_wave_b_receipt()` refuses to
  overwrite: the second attempt gets its own row and its own receipt.

  Resolve `observed_index_oid` by fingerprint, not by name:

```python
    cursor.execute(
        """
        SELECT i.indexrelid
        FROM pg_index i
        CROSS JOIN proof.observed_index_fingerprint(i.indexrelid) f
        WHERE i.indrelid = 'workbench_lab.orders'::regclass
          AND f.fingerprint = %s
        """,
        (proposal["proposed_fingerprint"],),
    )
    matched = cursor.fetchone()
```

  When `matched` is None the participant created *something else*, or nothing.
  Resolve the oid by name as a fallback and record the execution anyway with
  `fingerprint_matches` false — **an execution that did not match must be
  recorded, not skipped.** Skipping it would make a mismatch indistinguishable
  from a lab the participant never ran, and the verdict's two reasons
  (`the executed action does not match the proposed action` versus
  `no execution has been recorded yet`) exist to tell those apart.

- [ ] **Step 9: Run the recorder tests.**

```bash
TEST_DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
ALLOW_TEST_DATABASE_RESET=1 \
  .venv/bin/python -m pytest backend/tests/test_incident_lab.py -v
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  gates/checks.sh
```

Expected: PASS, and G-34 stays PASS — the contradiction scan now runs against a
database holding both a proposal and an execution, which is the state A6 could not
reach on its own.

- [ ] **Step 10: Live-Aurora acceptance criteria.** As `workshop_participant`
  (not the owner), execute the full Lab 4 sequence end to end:
  1. The participant reads the stored proposal — action type, target, ordered key
     columns, `proposed_sql`, preconditions with their measured `satisfied`
     values, `expected_effect`, and rollback — and
     `proof.autonomy_readiness(proposal_id)` reports `pre_execution_eligible` with
     an empty reasons array **before** anything is executed.
  2. Running the proposal's own `proposed_sql` verbatim succeeds. The **predicted**
     shape is `CREATE INDEX idx_orders_priority_tier_created_at ON
     workbench_lab.orders USING btree (priority_tier ASC, created_at DESC);` — a
     prediction of what Task D2a step 3's `index_name_for()` renderer produces, not
     a measurement, and Task G3 reconciles it against the real rendered text. The
     participant runs what the proposal stored, never what this plan quotes; if the
     two differ, the plan's quote is what is wrong.
  3. The `after_index` plan checkpoint shows `Index Scan` with a buffer count two
     orders of magnitude below the seq-scan checkpoints.
  4. `--wave B` admits successfully, G-32 passes, and exactly one
     `proof.action_executions` row exists with `outcome = 'succeeded'`,
     `fingerprint_matches = true`, a non-null `observed_index_definition`, both
     Wave B identifiers populated, and both plan checkpoint labels set.
  5. `proof.autonomy_readiness(proposal_id)` now reports
     `post_execution_validated = true` with an empty reasons array, while
     `pre_execution_eligible` and its reasons are **byte-identical to what they
     were in criterion 1**. Capture both verdicts and diff them. A pre-execution
     verdict that changed after a successful execution is the exact defect G-34
     exists to prevent, and observing it here means the gate has a hole.
  6. Replaying the Lab 3 run returns a byte-identical graph and citation set to
     before Wave B (Task C3's criterion, re-verified from the participant's seat).
  7. The participant can see both receipts.

- [ ] **Step 11: Cleanup and failure recovery.** If the participant's index creation
  fails (typo, permission, wrong column order), the lab must be re-runnable.
  Dropping and recreating the index is safe; re-running `--wave B` after a
  corrected index is safe by content-hash idempotency. Never auto-create the index
  on the participant's behalf as a "recovery" — that destroys the exercise.

  **Two distinct failure points, and step 8's ordering makes them distinguishable
  in the record.** A `CREATE INDEX` that errored produces an execution row with
  `outcome = 'failed'` and no index oid. An admission that failed *after* a
  successful `CREATE INDEX` produces a row with `outcome = 'succeeded'`,
  `fingerprint_matches = true`, and NULL Wave B identifiers. Both are real states
  with distinct verdicts, and neither is silence. The earlier draft recorded only
  after admission and so produced zero rows in the second case, which the verdict
  reported as `no execution has been recorded yet` — false, and identical to what
  a participant who skipped Lab 4 entirely would see.

  **The execution record is append-only and a corrected rerun adds a second row.**
  `proof.autonomy_readiness()` reads `ORDER BY approved_at DESC, recorded_seq
  DESC LIMIT 1`, so the latest attempt is the one the verdict reports, and the
  earlier mismatch stays visible as history. Do not delete the first row to "clean up" — `INSERT` is the
  only grant the personas hold, the mismatch is a real thing that happened, and a
  participant who fixed their own typo has produced a better audit trail than one
  who got it right first time. If a rehearsal needs a genuinely clean slate, drop
  and recreate the whole test database rather than surgically deleting receipts.

- [ ] **Step 12: Participant-facing changes.** This is the largest participant-facing
  change in the plan. Lab 4 goes from "read a remediation delta" to "review the
  agent's proposal, approve it, execute it yourself, then prove it worked, then
  replay the original investigation and see it unchanged." All four lab titles are
  fixed by Global Constraints; Lab 4 is "Validate, prove, and replay."

  **This step is where the session thesis's human-in-the-loop theme lands, and the copy
  must say so.** Use the phrase **"recommend, don't execute"** to name why the agent
  hands the participant DDL instead of running it: the agent holds no DDL privilege and
  no execution path, by design, and the participant's judgment is the control point.

  **The approval is an explicit act with a name attached, not an implied one.** The
  copy asks the participant to read the proposal's fields — what the agent wants
  changed, on what, why, what it expects to happen, how to undo it, and which cited
  claims support it — and then to approve it before running anything. `approved_by`
  records who approved; the proposal row records what was approved; the execution
  row records what was actually run. Three separate facts, in that order.

  **Name the autonomy verdict for what it is: an assessment, not a licence.** The
  copy must say that a proposal passing every pre-execution check was still
  executed by a human, and that a successful outcome afterwards does not mean the
  action was safe to take unattended. Do not write copy that reads as "the agent
  earned the right to run this" or "next time it can do this itself." The two
  verdicts are separate on purpose, and the participant should leave understanding
  why: `post_execution_validated` is what happened, `pre_execution_eligible` is
  what was knowable beforehand, and one never rewrites the other.

  **If the participant's execution did not match, say so plainly.** A false
  `fingerprint_matches` is a legitimate lab outcome with a real lesson in it — the
  index they built is not the index the evidence supported. The copy must present
  the mismatch as information, not as failure, and point at the two fingerprints
  and the two index definitions rather than a generic error.

  Lab 4's closing copy carries the session's closing message — *you built the trusted
  context layer required by a fleet-scale database agent* — and it must be conditional on
  this participant's own Wave B admission having succeeded. **A static Markdown page
  cannot be conditional, so the message is emitted from `labs/incident/run_live_workshop.py`'s
  `--wave B` path, after `admit_wave_b()` returns a receipt, and not from the sibling
  repo's content page at all.** The content page may set up the claim ("if your Wave B
  admission succeeds, the run will tell you what you built") but must not state it
  outright, because the page renders identically for a participant whose admission
  failed. This is the live-data-only rule applied to the summary text: the closing
  sentence is a claim about the participant's own run, so only the run can print it.
  Fleet expansion is a "Take it home" architecture discussion in the closing text
  only; adding a second cluster or a cross-fleet step to this lab is forbidden by Global
  Constraints.

  Do **not** let Lab 4's summary read as "we fixed the missing index." The index is the
  mechanism the participant validates; the outcome is the validated, cited, replayable
  evidence layer they built to decide on it.

- [ ] **Step 13: Commit.**

```bash
git add sql/11_roles_rls.sql labs/exercises/ labs/incident/run_live_workshop.py \
  backend/tests/test_incident_lab.py
git commit -m "Add Lab 4's participant-executed index and validation replay"
```

**Dependencies:** Tasks C2, C3, D2, and D2a (the participant executes and approves
*the agent's stored proposal*, so the proposal must exist before this task's
central step has anything to point at).

## Phase E — UI

Owning module: `frontend/src/`. There is **no frontend test framework** in this
repo; `npm run build` is `tsc && vite build` with `"noEmit": true`, so `tsc` is a
pure typecheck gate and is the only automated check available. Every UI task's
acceptance is therefore `tsc` clean plus a named visual verification against the
live app. `frontend/src/main.tsx` is a pure live renderer with no content constants
and no fallbacks — that property must survive this phase.

### Task E1: Reconcile the UI narrative and remove the Database Insights surface

**Owning schema/module:** `frontend/src/`; `backend/app/main.py`'s
`observability_refs` attachment.

**Files:**
- Modify: `backend/app/` — the `observability_refs` HTTP-layer attachment and its
  config gate, plus the latest-live-run wire shape consumed by Overview
- Modify: `frontend/src/` — the deep-link button component and its wire type;
  replace the ordinary-index/concurrent-repair timeline, presets, labels, and
  compound question with the four-phase online-migration narrative and Hybrid
  Retrieval Agent terminology
- Modify: `frontend/src/workbench.css` — the button's styles, if unshared
- Test: `npm run build` (`tsc`) plus a live visual check

**Interfaces:**
- Consumes: Task A1's deletion of `casework.database_insights_samples`.
- Produces: a UI that offers only the observation window and the CloudWatch/lock
  deep links that still resolve to something real.

**Migration and compatibility implications:** PR-6 added `proof.observability_refs`
with config-gated Database Insights and lock deep-link buttons, defaulting to empty
(window shown, no button). Task A1 deletes the Database Insights admission surface,
so a DBI deep link now points at a console page whose underlying data this workshop
no longer collects — a link to nothing, which is worse than no link. The lock deep
link and the observation window stay: both are still backed by real captured data.
Because the buttons are config-gated and default off, a stale deployment that still
sets the DBI config key must not crash — remove the key's handling so an unknown key
is simply ignored, and delete the key from `.env.example` and the docs.

- [ ] **Step 1: Locate every reference.**

```bash
rg -n --hidden -g '!node_modules' -i \
  'database.?insights|observability_refs|performance.?insights' \
  frontend/src backend/app
```

Read every hit before editing. Do not delete by pattern.

- [ ] **Step 2: Remove the DBI branch, keep the lock and window branches.** In the
  wire type, drop the DBI variant from the `observability_refs` union rather than
  making it optional — an optional-but-never-populated field is a phantom feature.

- [ ] **Step 3: Typecheck.**

```bash
cd frontend && npm run build
```

Expected: clean. A `tsc` error naming a removed variant is the compiler finding a
call site the grep missed — fix it, don't cast around it.

- [ ] **Step 4: Run the noun and verify gates.**

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  gates/checks.sh G-11 G-13 G-14 G-23
```

Expected: PASS. G-14 is the verify-affordance gate; removing a panel must not remove
a `_verify_sql` disclosure from a panel that still renders data.

- [ ] **Step 5: Live-Aurora acceptance criteria.** Load the app against a live
  two-wave run and confirm: the observation window still renders with real
  timestamps; the lock deep link still renders when configured; no Database Insights
  button appears under any configuration; no console error; the Proof surface's
  panels all still carry their verify affordance.

- [ ] **Step 6: Cleanup and failure recovery.** Delete the DBI config key from
  `.env.example` and from the deployment docs in the same commit. If a running
  deployment still sets it, the app must start and ignore it — verify by setting the
  removed key and starting the backend.

- [ ] **Step 7: Participant-facing changes.** Participants lose a button that would
  have led to an empty console page. The observation window — the honest artifact —
  stays. Facilitator notes that previously said "open Database Insights here" must be
  rewritten, not just have the sentence deleted, so the beat still has a purpose.

- [ ] **Step 8: Commit.**

```bash
git add frontend/src backend/app .env.example docs/
git commit -m "Remove the Database Insights surface from the UI"
```

**Dependencies:** Task A1.

### Task E2: Label Wave A and Wave B evidence on the Corpus surface

**Owning schema/module:** `frontend/src/`; the diagnostics endpoint that feeds the
Corpus surface.

**Files:**
- Modify: `sql/04_diagnostics.sql:472-484` — `retrieval.v_corpus_distribution`
- Modify: `frontend/src/` — the `SearchIndexDiagnostics` wire interface and the
  Corpus surface's distribution panel
- Modify: `frontend/src/workbench.css` — one new modifier class for the wave grouping
- Test: `npm run build` plus a live visual check

**Interfaces:**
- Consumes: Task A3's `wave` column on `casework.incident_capture_runs`, Task C2's
  two-wave admission.
- Produces: `retrieval.v_corpus_distribution` rows carrying a nullable `wave` column,
  and a Corpus panel that groups by wave within evidence kind.

**Migration and compatibility implications:** this is genuinely new wire surface.
`distribution[]` today groups only by `evidence_kind`; no Wave A/B, admission-wave,
batch, or as-of marker exists anywhere in the TypeScript interfaces. The change lands
in the **view**, not in `backend/app/insights.py` — line 248 is
`SELECT * FROM retrieval.v_corpus_distribution`, so widening the view widens the wire
payload with no Python change and keeps `main.tsx` a pure live renderer.

**`wave` is derived from provenance, not guessed from evidence kind.**
`casework.admit_evidence` requires every record's `source_uri` to begin with that
capture's `source_bundle_uri`, and each wave has a distinct bundle URI. That
contract covers incident, change, lock, and telemetry records even though only
the last two carry a `capture_id` foreign key. Join the indexed document's
`source_uri` to the longest matching bundle URI and take that run's `wave`.

The wire type remains `wave: "A" | "B" | null` because the view is reusable for
future non-capture evidence. In the live-only participant path, however, a null
wave is a provenance defect: do not fold it into Wave A and do not label all
changes "not wave-scoped." In particular, the Wave B validation change is one of
the clearest records the panel should attribute correctly.

The panel must render whatever waves the database reports — including a single-wave
corpus before Lab 4 runs — without a hardcoded group count (the `repeat(0)` CSS trap
from the timeline lens applies here: a grid template computed from an empty array
produces invalid CSS).

- [ ] **Step 1: Widen the view.** Replace `sql/04_diagnostics.sql:472-484` with a
  version that resolves `wave` through the only two links that exist, and leaves it
  null when neither applies:

```sql
CREATE OR REPLACE VIEW retrieval.v_corpus_distribution AS
WITH document_wave AS (
  SELECT
    document.document_version_id,
    document.evidence_kind,
    document.occurred_at,
    capture.wave
  FROM retrieval.documents document
  LEFT JOIN LATERAL (
    SELECT run.wave
    FROM casework.incident_capture_runs run
    WHERE document.source_uri LIKE run.source_bundle_uri || '/%'
    ORDER BY length(run.source_bundle_uri) DESC
    LIMIT 1
  ) capture ON true
  WHERE document.is_current
    AND document.index_state = 'ready'
)
SELECT
  document.evidence_kind,
  document.wave,
  count(DISTINCT document.document_version_id) AS documents,
  count(chunk.chunk_version_id) AS chunks,
  min(document.occurred_at) AS oldest_evidence,
  max(document.occurred_at) AS newest_evidence
FROM document_wave document
JOIN retrieval.chunks chunk
  ON chunk.document_version_id = document.document_version_id
GROUP BY document.evidence_kind, document.wave
ORDER BY document.evidence_kind, document.wave NULLS FIRST;
```

  Note the aggregate change: the original counted `DISTINCT document.evidence_id`;
  this counts `DISTINCT document.document_version_id`. With `is_current` filtering to
  one version per evidence item the two are equal, but the version ID is the honest
  grain for a view that now groups by a document-level attribute. Verify the totals
  match the old view before and after (Step 3).

- [ ] **Step 2: Widen the wire type and render.** Add `wave: "A" | "B" | null` to the
  distribution element interface. Group the panel by wave, and label the groups with
  participant-facing text, not the letters alone:

```
Wave A — captured before the recommendation
Wave B — captured after the participant validated the recommendation
Not wave-scoped — provenance does not map this record to a capture
```

- [ ] **Step 3: Typecheck, and confirm the row totals are unchanged.**

```bash
cd frontend && npm run build
/opt/homebrew/opt/libpq/bin/psql -X -v ON_ERROR_STOP=1 \
  "postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  -c "SELECT sum(documents), sum(chunks) FROM retrieval.v_corpus_distribution"
```

Expected: `tsc` errors at every place constructing a distribution element without
`wave` — that is the required-field choice paying for itself; fix each from real data.
The sums must equal the pre-change sums; a changed total means the added LEFT JOINs
are fanning out (an evidence item matching more than one capture run), which is a real
defect, not a rounding difference.

- [ ] **Step 4: Add the verify affordance.** The new grouped panel needs its own
  `_verify_sql`. `VerifyAffordance` silently renders nothing when `_verify_sql` is
  absent, so a missing key produces a panel that looks fine and quietly drops the
  verify guarantee. Add the key server-side and confirm the disclosure renders.

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  gates/checks.sh G-13 G-14
```

Expected: PASS, including the new panel's SQL round-tripping through G-13.

- [ ] **Step 5: Live-Aurora acceptance criteria.** Three checks, in this order:
  1. Against a Wave-A-only corpus, the panel renders one group labeled "Wave A" with
     real counts and no empty Wave B group, no CSS artifact, no console error.
  2. After Wave B admission, the panel renders both groups, and the Wave A counts are
     **identical** to check 1 — the visible proof of additivity, and the reason this
     panel is worth building at all.
  3. The verify affordance expands and its SQL, pasted into `psql`, returns the
     numbers shown.

- [ ] **Step 6: Cleanup and failure recovery.** No migration to undo; the field is
  derived. If the live-only participant corpus produces a null `wave`, that is a
  real provenance defect from Phase A/C — fix it there, never paper over it with a
  default in the renderer.

- [ ] **Step 7: Participant-facing changes.** The Corpus surface becomes the place a
  participant sees, as a number, that fixing the problem did not rewrite the record
  of the problem. That is the two-wave model's whole point, and until now it existed
  only in SQL.

- [ ] **Step 8: Commit.**

```bash
git add sql/04_diagnostics.sql frontend/src
git commit -m "Label Wave A and Wave B evidence on the Corpus surface"
```

**Dependencies:** Tasks A3, C2, C4.

### Task E3: State plainly in the plan lens that sequential scans are correct here

**Owning schema/module:** `frontend/src/` — the retrieve surface's plan lens.

**Files:**
- Modify: `frontend/src/` — the plan panel component
- Test: `npm run build` plus a live visual check

**Interfaces:**
- Consumes: the existing diagnostics plan endpoints and Task B5's checkpoints.
- Produces: an inline note on the plan lens distinguishing the two different
  sequential scans a participant sees.

**Migration and compatibility implications:** a participant on the plan lens sees
`Seq Scan` in two completely different places and must not conflate them:
1. On `retrieval.chunks` — **correct**, because at 50–80 documents the planner is
   right that a sequential scan beats an HNSW index scan. Nothing to fix.
2. On `workbench_lab.orders` — **the incident**, 2.4M rows discarded by filter, fixed
   by the index the participant creates in Lab 4.

Without the distinction, the lab teaches that seq scans are bad, then shows one that
is fine, and the sharper participants correctly conclude the lab is confused. Global
Constraints require stating this plainly rather than finessing it. The note is static
explanatory copy keyed to which relation the plan touched — not a data fallback, and
not a claim about numbers. Verified: this guidance does **not** already exist in
`docs/builder-session-flow.md`, so there is nothing to link to and the copy is new.
Production-scale ANN behavior goes in the appendix note only.

- [ ] **Step 1: Add the note, keyed to the relation.** Render it from the plan's own
  relation name — never from a hardcoded assumption about which lens is showing:

```tsx
{planRelation.startsWith("retrieval.") && (
  <p className="plan-note">
    A sequential scan here is the planner making the right call. At this corpus
    size, scanning every chunk costs less than descending an index. Index scans
    start winning at production scale, not at 80 documents.
  </p>
)}
{planRelation === "workbench_lab.orders" && (
  <p className="plan-note plan-note--incident">
    This sequential scan is the incident: the filter discards most of the rows it
    reads. ANALYZE will not fix it, because the statistics were never wrong — the
    access path is missing.
  </p>
)}
```

- [ ] **Step 2: Typecheck.**

```bash
cd frontend && npm run build
```

Expected: clean.

- [ ] **Step 3: Confirm the copy passes the noun gate.**

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  gates/checks.sh G-11 G-14
```

Expected: PASS. G-11 checks concrete-ID leakage and retired strings; new prose is
where a stray hardcoded ID most easily slips in. Note that **no existing gate lints
participant-facing prose terminology** — G-11 and G-30 do not — so the terminology
substitutions in Global Constraints are enforced by review here, not by CI. Do not
claim gate coverage this repo does not have.

- [ ] **Step 4: Live-Aurora acceptance criteria.** On the live app: the
  `retrieval.chunks` plan shows the "right call" note and no incident styling; the
  `workbench_lab.orders` plan shows the incident note; neither note appears on an
  index-scan plan; after the Lab 4 index exists, the `orders` plan shows an index
  scan and the incident note is gone.

- [ ] **Step 5: Cleanup and failure recovery.** If the relation name arrives in an
  unexpected form (schema-qualified vs. bare), neither note renders — a missing note
  is a fixable cosmetic gap, whereas a note attached to the wrong plan is a false
  statement. Prefer the silent failure and fix the matching.

- [ ] **Step 6: Participant-facing changes.** The most likely participant
  misconception in the whole workshop gets addressed at the exact point of confusion
  rather than in a facilitator aside nobody hears.

- [ ] **Step 7: Commit.**

```bash
git add frontend/src
git commit -m "Distinguish the correct seq scan from the incident seq scan"
```

**Dependencies:** Task B5 (the checkpoints the lens renders).

### Task E4: Add the supervision lens to the Proof surface

**Owning schema/module:** `frontend/src/` — a fourth lens on the `proof` surface;
`backend/app/insights.py` and `backend/app/verify_sql.py` for the read path.

**Files:**
- Modify: `backend/app/verify_sql.py` — add the supervision statements to the
  registry
- Modify: `backend/app/insights.py` — add the supervision reader
- Modify: `backend/app/main.py` — add `GET /v1/runs/{run_id}/supervision`
- Modify: `frontend/src/route.ts:41` — `proof` gains a `supervision` lens
- Modify: `frontend/src/WorkbenchApp.tsx` — eight separate sites, enumerated in
  step 5: the `ProveTab` union (line 71-77), `PRIMARY_NAV`'s `proof` lenses
  (line 126-135), the `SupervisionReceipt` interface (beside `RunTimeline`,
  line 531-535), the `supervision` state and its reset in
  `clearLoadedProofState()` (line 3997-4007), the `loadRun()` fetch
  (line 4258-4262), `goTo()`'s `proof` case (line 4069-4078), `activeSurface`'s
  `proveTab` test (line 4105-4108), the heading kicker/title/deck triple
  (line 6060-6104), and the panel block itself (after the timeline block ending
  line 7306)
- Modify: `frontend/src/workbench.css` — the lens's styles
- Modify: `gates/route_contract.py:64-78` — the new lens's contract route
- Modify: `gates/verify_sql_golden.py:185-300` — a fourth replay path for the
  supervision endpoint (step 6a). Without it G-13 replays **none** of step 1's
  statements: `run()` hardcodes `/v1/runs/<id>`, `/graph`, and `/timeline`, so a
  broken supervision descriptor would ship green
- Test: `npm run build` (`tsc`), `gates/checks.sh G-13 G-14 G-23`, plus a live
  visual check

**Interfaces:**
- Consumes: Task A5's `proof.action_proposals`, `proof.action_proposal_citations`,
  `proof.action_executions`, and `proof.autonomy_readiness(uuid)`; Task D2a's
  written proposal; Task D3's written execution row.
- Produces: `supervision_receipt(run_id, role="app_engineer") -> dict` in
  `backend/app/insights.py`; `supervision_verify_sql(run_id, persona) -> dict`
  in `backend/app/verify_sql.py`; `GET /v1/runs/{run_id}/supervision`; the
  `proof` surface's fourth lens.

**Migration and compatibility implications:** the lens is the only place the
participant sees the Supervised Execution Model, and its single hardest
requirement is that it **renders the computed verdict rather than narrating one**.
`proof.autonomy_readiness()` already returns four values — two booleans and two
reason arrays — and the frontend's job is to display them, not to re-derive
eligibility from the proposal fields it also renders. A frontend that recomputes
"looks eligible to me" is the fail-open hazard this whole model was built to avoid,
one layer up. **No conditional in this lens may read the execution row to decide
what to say about pre-execution eligibility.**

The lens is additive: `frontend/src/main.tsx` stays a pure live renderer with no
content constants and no fallbacks. An absent proposal is a rendered empty state
("no proposal recorded for this run"), never invented content.

- [ ] **Step 1: Add the registry statements.** Append to
  `backend/app/verify_sql.py`, after `OBSERVABILITY_REF_SQL`. Three panel-grain
  statements, each a single `run_id`-bound SELECT, matching the module's stated
  panel grain:

```python
# --- Panel grain: supervised execution (SPEC's Supervised Execution Model) ----
# Three run_id-bound SELECTs. The verdict is a function call, not a recomputation:
# the panel shows what proof.autonomy_readiness() returned, and this statement
# replays that same call rather than re-deriving eligibility client-side.

ACTION_PROPOSAL_SQL = (
    "SELECT proposal_id, agent_run_id, run_id, action_type, target_schema,\n"
    "       target_table, index_method, is_unique, key_columns,\n"
    "       included_columns, predicate, proposed_fingerprint, proposed_sql,\n"
    "       proposed_sql_sha256, preconditions, expected_effect, rollback_sql,\n"
    "       rollback_guidance, statement_timeout, lock_timeout, created_at\n"
    "FROM proof.action_proposals\n"
    "WHERE run_id = %(run_id)s\n"
    "ORDER BY created_at DESC"
)

ACTION_EXECUTION_SQL = (
    "SELECT execution_id, proposal_id, run_id, approved_by, approved_at,\n"
    "       observed_index_definition, observed_fingerprint,\n"
    "       fingerprint_matches, outcome, outcome_detail, started_at,\n"
    "       completed_at, plan_before_checkpoint, plan_after_checkpoint,\n"
    "       wave_b_capture_id, wave_b_ingest_id\n"
    "FROM proof.action_executions\n"
    "WHERE run_id = %(run_id)s\n"
    # recorded_seq, byte-for-byte the same ORDER BY as
    # proof.autonomy_readiness(). Two attempts recorded in one transaction share
    # an approved_at, so ordering on it alone let the panel and the verdict pick
    # DIFFERENT rows -- the panel would show a failed attempt beside a verdict
    # computed from the successful one. Measured non-deterministic on PostgreSQL
    # 17.10; see the recorded_seq column comment in Task A5 step 3.
    "ORDER BY approved_at DESC, recorded_seq DESC"
)

AUTONOMY_VERDICT_SQL = (
    "SELECT p.proposal_id,\n"
    "       v.pre_execution_eligible,\n"
    "       v.pre_execution_reasons,\n"
    "       v.post_execution_validated,\n"
    "       v.post_execution_reasons\n"
    "FROM proof.action_proposals p\n"
    "CROSS JOIN proof.autonomy_readiness(p.proposal_id) v\n"
    "WHERE p.run_id = %(run_id)s\n"
    "ORDER BY p.created_at DESC"
)
```

  And the accessor, beside `receipt_verify_sql`:

```python
def supervision_verify_sql(run_id: str, persona: str) -> dict[str, dict[str, Any]]:
    """Return the three panel-grain descriptors for the supervision lens.

    Args:
        run_id: The run whose proposal and execution are being rendered.
        persona: The persona whose rows this lens showed. Required, never
            defaulted, for the same reason receipt_verify_sql requires it.

    Returns:
        A ``panel -> descriptor`` map for the proposal, execution, and verdict
        panels, each replayable with ``{"run_id": run_id}``.
    """
    binds = {"run_id": run_id}
    return {
        "proposal": _descriptor(ACTION_PROPOSAL_SQL, binds, persona),
        "execution": _descriptor(ACTION_EXECUTION_SQL, binds, persona),
        "verdict": _descriptor(AUTONOMY_VERDICT_SQL, binds, persona),
    }
```

  **The verdict panel's `_verify_sql` calls `proof.autonomy_readiness()` — it does
  not restate the function's logic as SQL.** A pasteable statement that reproduced
  the verdict independently would be a second implementation to drift against the
  first, which is exactly the twin G-13 exists to prevent.

- [ ] **Step 2: Add the reader.** Append to `backend/app/insights.py`, beside
  `observability_ref`. It follows that function's shape exactly: resolve the run's
  stored role with `_run_role`, read under `get_dict_conn(stored_role)`, and attach
  the registry descriptors.

```python
def supervision_receipt(
    run_id: str,
    role: str = "app_engineer",
) -> dict[str, Any]:
    """Return the supervised-execution record for a run.

    Three reads, in the order the participant meets them: what the agent proposed,
    what the human executed, and what the computed autonomy verdict says about
    both. The verdict comes from proof.autonomy_readiness() -- this function does
    not evaluate eligibility, and neither does its caller.

    Args:
        run_id: The retrieval run whose proposal and execution are being read.
        role: The requesting persona; the run's stored role wins, as elsewhere.

    Returns:
        ``{"run_id", "proposal", "citations", "execution", "verdict", "_verify_sql"}``.
        ``proposal``, ``execution``, and ``verdict`` are None when no row exists --
        an unexecuted proposal and an unproposed run are different states and the
        lens renders them differently.
    """
    stored_role = _run_role(run_id, role)
    with get_dict_conn(stored_role) as connection:
        with connection.cursor() as cursor:
            cursor.execute(ACTION_PROPOSAL_SQL, {"run_id": run_id})
            proposals = cursor.fetchall()
            cursor.execute(ACTION_EXECUTION_SQL, {"run_id": run_id})
            executions = cursor.fetchall()
            cursor.execute(AUTONOMY_VERDICT_SQL, {"run_id": run_id})
            verdicts = cursor.fetchall()
            citations: list[dict[str, Any]] = []
            if proposals:
                cursor.execute(
                    PROPOSAL_CITATION_SQL,
                    {"proposal_id": proposals[0]["proposal_id"]},
                )
                citations = cursor.fetchall()
    return {
        "run_id": run_id,
        # The latest of each. proof.autonomy_readiness() reads the latest
        # execution too, with the IDENTICAL `ORDER BY approved_at DESC,
        # recorded_seq DESC`, so the panel and the verdict describe the same
        # attempt rather than two different ones. If either ordering is ever
        # changed, change both -- a panel describing one attempt beside a verdict
        # computed from another is worse than showing nothing.
        "proposal": proposals[0] if proposals else None,
        "citations": citations,
        "execution": executions[0] if executions else None,
        "verdict": verdicts[0] if verdicts else None,
        "_verify_sql": supervision_verify_sql(run_id, stored_role),
    }
```

  `PROPOSAL_CITATION_SQL` is the fourth registry statement, element-grain by
  `proposal_id`, and belongs in `backend/app/verify_sql.py` with the other three.
  It joins the link table to the validation function so the panel can show each
  supporting claim beside whether that citation still validates:

```python
# LEFT JOINs, for the same reason proof.autonomy_readiness() counts VALIDATED
# citations rather than invalid ones. Both joined sides are RLS-filtered
# (proof.answer_citations carries the evidence-reachability clause,
# sql/11_roles_rls.sql:963-979; proof.validate_answer_citations INNER JOINs two
# FORCE-RLS tables, sql/06_receipts.sql:67), and this statement runs under the
# requesting persona. With inner joins, a link whose citation the persona cannot
# read DISAPPEARS from the panel -- the participant sees three supporting claims
# where the proposal recorded four, with nothing indicating one was withheld.
# A NULL is_valid renders as "cannot be validated from this persona's view",
# which is the honest cell; a missing row is a lie by omission.
PROPOSAL_CITATION_SQL = (
    "SELECT link.citation_number, link.claim, citation.source_uri,\n"
    "       citation.source_revision, citation.quote_text, validation.is_valid,\n"
    "       validation.issue\n"
    "FROM proof.action_proposal_citations link\n"
    "JOIN proof.action_proposals proposal\n"
    "  ON proposal.proposal_id = link.proposal_id\n"
    " AND proposal.run_id = link.run_id\n"
    "LEFT JOIN proof.answer_citations citation\n"
    "  ON citation.run_id = link.run_id\n"
    " AND citation.citation_number = link.citation_number\n"
    "LEFT JOIN proof.validate_answer_citations(proposal.run_id) validation\n"
    "  ON validation.citation_number = link.citation_number\n"
    "WHERE link.proposal_id = %(proposal_id)s\n"
    "ORDER BY link.citation_number"
)
```

  Add it to `supervision_verify_sql`'s returned map under `"citations"`, bound with
  `{"proposal_id": ...}` rather than `{"run_id": ...}` — a mixed-bind map is
  correct here and `_descriptor` takes its binds per statement.

- [ ] **Step 3: Add the endpoint.** In `backend/app/main.py`, beside
  `/v1/runs/{run_id}/timeline` (line 508), following that handler's exact error
  contract — `ValueError` becomes a 404, anything else becomes `_unavailable`:

```python
@app.get("/v1/runs/{run_id}/supervision")
def supervision(run_id: str, role: Persona = DEFAULT_ROLE):
    try:
        return supervision_receipt(run_id, role=role)
    except ValueError as error:
        raise HTTPException(404, str(error))
    except Exception as error:
        raise _unavailable("supervision receipt", error)
```

  Import `supervision_receipt` in the existing `from .insights import (...)` block
  at line 37, where `observability_ref` already lives.

- [ ] **Step 4: Register the lens.** In `frontend/src/route.ts`, extend the `proof`
  entry in `SURFACE_LENSES` (line 41). **Append, never prepend** — the first entry
  is the default emitted with no `?lens=` param, so putting `supervision` first
  would silently change what `#/proof/<run>` renders and break
  `gates/route_contract.py`'s bare-route assertion at line 74:

```ts
  proof: ['receipt', 'replay', 'timeline', 'supervision'],
```

  Then add the contract route to `CORE_CONTRACT_ROUTES` in
  `gates/route_contract.py`, matching the existing timeline entry's shape at
  lines 76-79:

```python
    (
        "#/proof/rr_9b41d7?lens=supervision",
        {"surface": "proof", "runId": "rr_9b41d7", "lens": "supervision"},
    ),
```

- [ ] **Step 5: Wire the lens into `WorkbenchApp.tsx`.** A new lens is not one
  edit in this file. It is eight, and skipping any one of them leaves the lens
  unreachable, un-highlighted in the nav, or holding a previous run's data. Do all
  eight. `tsc` catches 5a, 5c, and 5e; it is silent on the other five, and the two
  it is most dangerously silent on are 5d's reset line and 5g's `activeSurface`
  branch — both compile fine while being wrong at runtime.

  **5a. The `ProveTab` union** (line 71-77) — `supervision` becomes a legal tab:

```tsx
type ProveTab =
  | 'answer'
  | 'graph'
  | 'receipt'
  | 'replay'
  | 'timeline'
  | 'supervision'
  | 'evaluation';
```

  **5b. `PRIMARY_NAV`'s proof lenses** (line 126-135) — append after `timeline`,
  matching `SURFACE_LENSES` order from step 4. Import `UserCheck` from
  `lucide-react` alongside the other icons:

```tsx
      { key: 'timeline', label: 'Timeline', Icon: GitMerge },
      { key: 'supervision', label: 'Supervision', Icon: UserCheck },
```

  **5c. The payload interface**, beside `RunTimeline` (line 531-535). Field names
  and nullability mirror `supervision_receipt()`'s return exactly — `proposal`,
  `execution`, and `verdict` are independently nullable:

```tsx
interface ActionProposal {
  proposal_id: string;
  agent_run_id: string;
  run_id: string;
  action_type: string;
  target_schema: string;
  target_table: string;
  index_method: string;
  is_unique: boolean;
  key_columns: string[];
  included_columns: string[];
  predicate: string | null;
  proposed_fingerprint: string;
  proposed_sql: string;
  proposed_sql_sha256: string;
  preconditions: Array<{
    check: string;
    satisfied: boolean;
    detail?: string;
  }>;
  expected_effect: string;
  rollback_sql: string | null;
  rollback_guidance: string | null;
  statement_timeout: string | null;
  lock_timeout: string | null;
  created_at: string;
}

interface ActionExecution {
  execution_id: string;
  proposal_id: string;
  run_id: string;
  approved_by: string;
  approved_at: string;
  observed_index_definition: string | null;
  observed_fingerprint: string | null;
  fingerprint_matches: boolean | null;
  outcome: string;
  outcome_detail: string | null;
  started_at: string | null;
  completed_at: string | null;
  plan_before_checkpoint: string | null;
  plan_after_checkpoint: string | null;
  wave_b_capture_id: string | null;
  wave_b_ingest_id: string | null;
}

interface AutonomyVerdict {
  proposal_id: string;
  pre_execution_eligible: boolean;
  pre_execution_reasons: string[];
  post_execution_validated: boolean;
  post_execution_reasons: string[];
}

interface SupervisionReceipt {
  run_id: string;
  proposal: ActionProposal | null;
  citations: Array<{
    citation_number: number;
    claim: string;
    source_uri: string | null;
    source_revision: string | null;
    quote_text: string | null;
    is_valid: boolean;
    issue: string | null;
  }>;
  execution: ActionExecution | null;
  verdict: AutonomyVerdict | null;
  _verify_sql?: Record<string, VerifySql>;
}
```

  `preconditions` types `check`/`satisfied`/`detail` because those are the exact
  keys `measure_preconditions()` writes in Task D2a step 6. A mismatch here is a
  silent `undefined` at render time, not a `tsc` error, because the payload arrives
  as JSON.

  **5d. State and reset** — declare beside `timeline` (line 3745) and clear it in
  `clearLoadedProofState()` (line 3997-4007), in the same place `setTimeline(null)`
  lives:

```tsx
  const [supervision, setSupervision] = useState<SupervisionReceipt | null>(null);
```

  **Adding the `setSupervision(null)` line to `clearLoadedProofState()` is not
  optional bookkeeping.** That function is what stops a previous run's data from
  surviving a run switch, and this lens is the one place in the app where stale
  data would show one run's proposal beside another run's verdict. `tsc` will not
  catch its absence.

  **5e. The fetch** — two edits in `loadRun()`, and **both** are required. Add a
  fourth entry to the `Promise.all` (`frontend/src/WorkbenchApp.tsx:4259-4263`):

```tsx
      const [runReceipt, runGraph, runTimeline, runSupervision] =
        await Promise.all([
          api<RunReceipt>(`/v1/runs/${runKey}?${roleQuery}`),
          api<RunGraph>(`/v1/runs/${runKey}/graph?${roleQuery}`),
          api<RunTimeline>(`/v1/runs/${runKey}/timeline?${roleQuery}`),
          api<SupervisionReceipt>(`/v1/runs/${runKey}/supervision?${roleQuery}`),
        ]);
```

  Then **set it**, on the line after `setTimeline(runTimeline)` (`:4271`), which is
  after the stale-transition guard at `:4268`:

```tsx
      setTimeline(runTimeline);
      setSupervision(runSupervision);
```

  Fetching without setting is the failure mode to watch for here: `tsc` accepts an
  unused destructured binding, so the lens would render permanently empty from
  `supervision === null` while the network tab shows a successful 200. Both lines,
  or the whole lens is dead.

  The `setSupervision` call must sit **after** the
  `if (transitionVersion !== roleTransitionVersion.current) return false;` guard,
  with the other three setters — not next to the fetch. Placing it before the guard
  would write a superseded run's supervision data during a persona switch, which is
  the exact race the guard exists to close.

  `Promise.all` rejects on any member, so a 500 from the supervision endpoint would
  break loading a run entirely — which is why step 3's endpoint returns a populated
  body with null members for a run that has no proposal, rather than a 404. A run
  with no proposal is a normal state, not an error, and Task G2 step 1a case 4
  injects exactly this. Note that `run_receipt`, `run_timeline`, and `run_graph` in
  `backend/app/main.py` (`:495`, `:515`, `:525`) already raise `_unavailable`
  (`:96`) on their own failures, so this endpoint is not introducing a new class of
  fragility — it is joining an existing one, deliberately, rather than adding a
  second loading path.

  **5f. `goTo()`'s proof case** (line 4069-4078) — the nested ternary gains a
  branch. `receipt` stays the final fallback so a bare `#/proof/<run>` is unchanged:

```tsx
      case 'proof':
        setModule('prove');
        setProveTab(
          lens === 'replay'
            ? 'replay'
            : lens === 'timeline'
              ? 'timeline'
              : lens === 'supervision'
                ? 'supervision'
                : 'receipt',
        );
        break;
```

  **5g. `activeSurface`** (line 4105-4108) — without this the nav highlight falls
  through to `'agent'` and the URL emits the wrong surface, failing G-23:

```tsx
                : proveTab === 'receipt' ||
                    proveTab === 'replay' ||
                    proveTab === 'timeline' ||
                    proveTab === 'supervision'
                  ? 'proof'
                  : 'agent';
```

  **5h. The heading triple** (line 6060-6104) — kicker, title, and deck each gain a
  `proveTab === 'supervision'` branch before the `'Evaluation'` fallback, in the
  same nested-ternary style the file already uses:

```tsx
                          : proveTab === 'timeline'
                            ? 'Proof · Timeline'
                            : proveTab === 'supervision'
                              ? 'Proof · Supervision'
                              : 'Evaluation'}
```

```tsx
                  ) : proveTab === 'supervision' ? (
                    <>A human approved it. <em>The database recorded both.</em></>
                  ) : (
```

```tsx
                            : proveTab === 'supervision'
                              ? 'Compare what the agent proposed against what a human executed, and read the separately computed autonomy verdict.'
                              : 'Measure retrieval modes and graph traversal with different metrics.'}
```

- [ ] **Step 5i: Render the panels.** Add the block after the timeline lens's
  closing `) : null}` (line 7306), following that block's shape. Four sections in
  the order the participant reads them, and the verdict section renders `verdict`
  fields only:

```tsx
            {proveTab === 'supervision' ? (
              <section className="supervision-theater">
                <header>
                  <div>
                    <span className="section-label">
                      Proposed, approved, executed, assessed
                    </span>
                    <h2>{receipt?.run.query_text || controls.query}</h2>
                  </div>
                  <div className="supervision-theater-meta">
                    <span className="status-pill">
                      {supervision?.proposal ? '1 proposal' : 'no proposal'}
                    </span>
                    <span className="status-pill">
                      {supervision?.execution
                        ? `executed · ${supervision.execution.outcome}`
                        : 'not executed'}
                    </span>
                    <span className="status-pill">
                      {supervision?.citations.length || 0} supporting citations
                    </span>
                  </div>
                </header>

                {!supervision?.proposal ? (
                  <Empty
                    icon={<UserCheck size={20} />}
                    title="No proposal recorded for this run"
                    detail="A proposal is written when the agent answers through the answer path. A run answered another way, or answered before supervised execution shipped, has none."
                  />
                ) : (
                  <>
                    <article className="supervision-panel">
                      <h3>What the agent proposed</h3>
                      <dl>
                        <dt>Action</dt>
                        <dd>{supervision.proposal.action_type}</dd>
                        <dt>Target</dt>
                        <dd>
                          {supervision.proposal.target_schema}.
                          {supervision.proposal.target_table}
                        </dd>
                        <dt>Keys, in index order</dt>
                        <dd>{supervision.proposal.key_columns.join(', ')}</dd>
                        <dt>Expected effect</dt>
                        <dd>{supervision.proposal.expected_effect}</dd>
                        <dt>Rollback</dt>
                        <dd>
                          <code>
                            {supervision.proposal.rollback_sql ||
                              supervision.proposal.rollback_guidance ||
                              '—'}
                          </code>
                        </dd>
                        <dt>Bounds</dt>
                        <dd>
                          statement_timeout{' '}
                          {supervision.proposal.statement_timeout || '—'},
                          lock_timeout{' '}
                          {supervision.proposal.lock_timeout || '—'}
                        </dd>
                      </dl>
                      <pre className="supervision-sql">
                        {supervision.proposal.proposed_sql}
                      </pre>
                      <p className="supervision-note">
                        The agent holds no DDL privilege and no execution path.
                        This statement is a recommendation a human runs.
                      </p>
                      <VerifyAffordance
                        descriptor={supervision._verify_sql?.proposal}
                      />
                    </article>

                    <article className="supervision-panel">
                      <h3>Preconditions, as measured</h3>
                      <ul className="supervision-checks">
                        {supervision.proposal.preconditions.map((check) => (
                          <li
                            key={check.check}
                            className={
                              check.satisfied ? 'is-satisfied' : 'is-unsatisfied'
                            }
                          >
                            <strong>{check.check}</strong>
                            <span>
                              {check.satisfied ? 'satisfied' : 'not satisfied'}
                            </span>
                            {check.detail ? <em>{check.detail}</em> : null}
                          </li>
                        ))}
                      </ul>
                    </article>

                    <article className="supervision-panel">
                      <h3>What was executed</h3>
                      {!supervision.execution ? (
                        <Empty
                          icon={<UserCheck size={20} />}
                          title="No execution recorded"
                          detail="The proposal is waiting on a human. Nothing has been run."
                        />
                      ) : (
                        <>
                          <dl>
                            <dt>Approved by</dt>
                            <dd>{supervision.execution.approved_by}</dd>
                            <dt>Outcome</dt>
                            <dd>{supervision.execution.outcome}</dd>
                            <dt>Observed index</dt>
                            <dd>
                              <code>
                                {supervision.execution
                                  .observed_index_definition || '—'}
                              </code>
                            </dd>
                            <dt>Matches the proposal</dt>
                            <dd>
                              {supervision.execution.fingerprint_matches
                                ? 'yes'
                                : 'no'}
                            </dd>
                            <dt>Plan evidence</dt>
                            <dd>
                              {supervision.execution.plan_before_checkpoint ||
                                '—'}{' '}
                              →{' '}
                              {supervision.execution.plan_after_checkpoint ||
                                '—'}
                            </dd>
                          </dl>
                          <VerifyAffordance
                            descriptor={supervision._verify_sql?.execution}
                          />
                        </>
                      )}
                    </article>

                    <article className="supervision-panel supervision-verdict">
                      <h3>Autonomy readiness</h3>
                      <p
                        className={
                          supervision.verdict?.pre_execution_eligible
                            ? 'is-eligible'
                            : 'is-blocked'
                        }
                      >
                        Before execution:{' '}
                        {supervision.verdict?.pre_execution_eligible
                          ? 'every pre-execution requirement was met'
                          : 'not eligible'}
                      </p>
                      <ul className="supervision-reasons">
                        {(
                          supervision.verdict?.pre_execution_reasons ?? []
                        ).map((reason) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                      <p
                        className={
                          supervision.verdict?.post_execution_validated
                            ? 'is-validated'
                            : 'is-unvalidated'
                        }
                      >
                        After execution:{' '}
                        {supervision.verdict?.post_execution_validated
                          ? 'the executed action matched the proposal and an admitted Wave B capture validated the result'
                          : 'not validated'}
                      </p>
                      <ul className="supervision-reasons">
                        {(
                          supervision.verdict?.post_execution_reasons ?? []
                        ).map((reason) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                      <p className="supervision-note">
                        This is an autonomy-readiness assessment, not autonomous
                        execution. A human approved and executed this action. A
                        validated result afterwards does not mean the action was
                        safe to take unattended — the two verdicts are computed
                        separately and neither rewrites the other.
                      </p>
                      <VerifyAffordance
                        descriptor={supervision._verify_sql?.verdict}
                      />
                    </article>
                  </>
                )}
              </section>
            ) : null}
```

  Four properties of this block are load-bearing:

  **The closing note is required copy, not decoration.** It is the participant-facing
  half of the invariant G-34 enforces in the database, and it is the sentence that
  keeps the lens from reading as a permission slip. Do not shorten it to "human in
  the loop."

  **Both verdict lines read `supervision.verdict` alone.** Do not add a conditional
  that reads `supervision.execution` to decide what the pre-execution line says —
  that is the retroactive-safety defect reimplemented in TypeScript, where no gate
  can see it.

  **Absent renders as negative, never as pass.** Every verdict field is read through
  `supervision.verdict?.`, so a null verdict shows `not eligible` / `not validated`.
  If `verdict` is null while `proposal` is not, the function call failed rather than
  returning no rows — a real defect the lens must not paper over with an optimistic
  default.

  **Every panel publishes its `_verify_sql` through the existing `VerifyAffordance`
  component**, the same inline-disclosure affordance the other Proof lenses use.
  G-13 replays each published statement and diffs it against the API JSON, so a
  descriptor that does not reproduce its own panel fails. Do not render the SQL as
  static text — reuse the component. Its prop is `descriptor`, not `verify`, and it
  already returns `null` on an absent descriptor, so no caller-side conditional is
  needed. Verified against `WorkbenchApp.tsx`'s definition: `function
  VerifyAffordance({ descriptor, label = 'verify in psql' })`, with
  `if (!descriptor) return null;` as its first statement. `Empty` takes
  `{icon, title, detail?}` and `UserCheck` is exported by the pinned `lucide-react`
  — all three checked against the files, not assumed.

  **No literal from a measured run may appear in this JSX.** G-14 scans the built
  bundle (`frontend/dist`) for canned participant evidence against a numeral
  denylist, and it does not care that a number arrived by copy-paste from a real
  run rather than from a fixture. Every value in this lens comes from
  `supervision`; the only hardcoded strings are labels, the empty states, and the
  closing note. This is the same rule the rest of the app already follows, restated
  because a proposal's `proposed_sql` is exactly the kind of thing an implementer
  is tempted to paste in as a placeholder while styling.

- [ ] **Step 5j: Add the styles.** Append to `frontend/src/workbench.css`. The
  theater shell copies `.tgrid-theater`'s shape verbatim so the fourth lens sits at
  the same visual weight as the third; only the panel internals are new. Use the
  existing tokens — no new colors:

```css
/* --- Proof · Supervision -------------------------------------------------- */
.supervision-theater {
  min-width: 0;
  margin-top: 12px;
  padding: 22px 24px;
  background: #fff;
  border: 1px solid var(--edge);
  border-radius: 16px;
  box-shadow: var(--shadow);
}

.supervision-theater > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.supervision-theater h2 {
  max-width: 900px;
  margin: 7px 0 0;
  font: 600 17px/1.4 var(--serif);
}

.supervision-theater-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.supervision-panel {
  margin-top: 20px;
  padding-top: 18px;
  border-top: 1px solid var(--hair-soft);
}

.supervision-panel h3 {
  margin: 0 0 12px;
  font: 600 14px/1.4 var(--sans);
  color: var(--ink);
}

.supervision-panel dl {
  display: grid;
  grid-template-columns: minmax(140px, max-content) 1fr;
  gap: 6px 18px;
  margin: 0;
  font: 400 14px/1.5 var(--workbench-data);
}

.supervision-panel dt {
  color: var(--muted);
}

.supervision-panel dd {
  margin: 0;
  color: var(--ink);
}

.supervision-sql {
  margin: 14px 0 0;
  padding: 12px 14px;
  overflow-x: auto;
  font: 400 13px/1.6 var(--mono);
  color: var(--ink);
  background: var(--sql-body);
  border-radius: 10px;
}

.supervision-note {
  margin: 12px 0 0;
  max-width: 68ch;
  font: 400 13px/1.6 var(--sans);
  color: var(--ink-soft);
}

.supervision-checks,
.supervision-reasons {
  margin: 0;
  padding: 0;
  list-style: none;
}

.supervision-checks li {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 10px;
  padding: 7px 0;
  font: 400 13px/1.5 var(--workbench-data);
  border-bottom: 1px solid var(--hair-soft);
}

.supervision-checks li:last-child {
  border-bottom: 0;
}

.supervision-checks strong {
  font-weight: 600;
  color: var(--ink);
}

.supervision-checks em {
  flex-basis: 100%;
  font-style: normal;
  color: var(--muted);
}

.supervision-checks .is-satisfied span {
  color: var(--green);
}

.supervision-checks .is-unsatisfied span {
  color: var(--red);
}

.supervision-verdict .is-eligible,
.supervision-verdict .is-validated {
  margin: 0;
  padding: 10px 14px;
  font: 600 14px/1.5 var(--sans);
  color: var(--green);
  background: var(--green-wash);
  border-radius: 10px;
}

.supervision-verdict .is-blocked,
.supervision-verdict .is-unvalidated {
  margin: 0;
  padding: 10px 14px;
  font: 600 14px/1.5 var(--sans);
  color: var(--red-deep);
  background: var(--wash);
  border-radius: 10px;
}

.supervision-verdict .is-validated,
.supervision-verdict .is-unvalidated {
  margin-top: 16px;
}

.supervision-reasons li {
  margin-top: 8px;
  padding-left: 14px;
  font: 400 13px/1.6 var(--sans);
  color: var(--ink-soft);
  border-left: 2px solid var(--hair-strong);
}
```

  Two notes. `--green`/`--green-wash` and `--red-deep`/`--wash` are the tokens the
  rest of the app already uses for pass and fail, so an eligible verdict reads the
  same as any other green state in the app rather than inventing a private palette.
  And color is never the only signal: each verdict line states its outcome in words,
  because a projector's color rendition is not something this workshop controls.

- [ ] **Step 6: Typecheck and run the gates.**

```bash
cd frontend && npm run build
cd .. && DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  gates/checks.sh G-11 G-13 G-14 G-23 G-34
```

Expected: `tsc` clean and all five PASS. What each one is doing here, since three of
them are easy to run without knowing what they check:

- **G-13** (`verify_sql_golden.py`) replays published `_verify_sql` descriptors and
  diffs the replayed rows against the API JSON. A descriptor whose statement does not
  reproduce its own panel fails. **Read `gates/verify_sql_golden.py:185-300` before
  relying on it here.** Its `run()` calls `_check_receipt` for `/v1/runs/<id>` and
  `_check_elements` for `/graph` + `edges` and `/timeline` + `events` — three
  hardcoded paths. It has no supervision awareness, so as written it would replay
  **none** of step 1's four statements and still report PASS. Step 6a adds the
  fourth path; until it does, running G-13 here proves nothing about this lens.
- **G-14** (`empty_db_ui_test.py`) scans `frontend/dist` for canned participant
  evidence. It requires a **built** bundle, so run `npm run build` first — G-14 on a
  stale `dist/` is judging the previous commit's code.
- **G-23** (`route_contract.py`) covers the new lens route from step 4 and the
  `activeSurface` change from step 5g. It is the gate that catches a lens that
  renders but does not round-trip through the URL.
- **G-11** (`noun_lint.py`) checks Law-1 nouns, which the new nav label and heading
  copy are subject to.
- **G-34** (`retroactive_safety.py`, Task A6) is included deliberately even though
  this task changes no SQL: it is the invariant this lens exists to display, and
  running it here confirms the thing being rendered is still true.

- [ ] **Step 6a: Teach G-13 the supervision endpoint.** Without this, step 6's G-13
  run is theatre: `gates/verify_sql_golden.py`'s `run()` visits three hardcoded
  paths and none of them is `/supervision`, so all four of step 1's statements go
  unreplayed and a descriptor that returns different rows than the panel ships
  green. Add a fourth call beside the existing two `_check_elements` calls
  (`gates/verify_sql_golden.py:277-297`):

```python
def _check_supervision(cur, api_base: str, run_id: str, ok_lines: list[str]) -> None:
    """Diff the supervision panels for the smoke run.

    Panel grain like _check_receipt, with two differences that matter. First, the
    panel may legitimately be null: a smoke run has no action proposal, so
    `proposal`, `execution`, and `verdict` are all None and there is nothing to
    replay. That is a SKIP, reported as such -- not a silent pass, and not a
    failure. Second, three of the four members are single-row while their
    statements return sets, so those are collapsed exactly the way
    backend/app/insights.py collapses them, or replay != API on shape alone.
    """
    panel = _get_json(api_base, f"/v1/runs/{run_id}/supervision")
    verify = panel.get("_verify_sql")
    if not verify:
        raise Mismatch(
            f"/v1/runs/{run_id}/supervision carries no _verify_sql "
            "(registry not attached)"
        )
    if panel.get("proposal") is None:
        ok_lines.append(
            "  supervision: no proposal on the smoke run; 0 descriptor(s) replayed"
        )
        return
    single_row = {"proposal", "execution", "verdict"}
    for member, descriptor in verify.items():
        published = panel[member]
        replayed = _replay(cur, descriptor, f"supervision.{member}")
        if member in single_row:
            replayed = replayed[0] if replayed else None
        ok_lines.append(_require_equal(f"supervision.{member}", replayed, published))
```

  Call it from `run()` after the timeline check, inside the same read-only
  transaction. The `single_row` collapse must mirror
  `supervision_receipt`'s `proposals[0] if proposals else None` exactly — the same
  `ORDER BY approved_at DESC, recorded_seq DESC` the reader and
  `proof.autonomy_readiness()` share. If the orderings ever diverge, this gate is
  where it surfaces, which is a second reason to add it.

  **The early return is a real branch, not defensive padding.** G-13 replays the
  *smoke* run (`_smoke_run_id()`), and the smoke run answers the canonical retrieval
  question — it never proposes an action. So on a normal database this function
  reports a skip. That means step 6's G-13 PASS does **not** prove the supervision
  descriptors work; only step 7's live check on a run that has a proposal does.
  Say so in the gate's own output rather than letting a skip read like a pass.

- [ ] **Step 6b: Prove the new G-13 path can fail.** A gate that has never gone red
  proves nothing. Break one descriptor deliberately and confirm the gate catches it,
  against a run that **has** a proposal (Task D3's run, not the smoke run):

```bash
WORKBENCH_SMOKE_RUN_ID="<a run_id that has an action proposal>" \
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  gates/checks.sh G-13
```

  Expected: PASS. Then change `ACTION_PROPOSAL_SQL`'s `ORDER BY created_at DESC` to
  `ASC`, re-run the same command, and confirm it goes **FAIL** with
  `supervision.proposal: replay != API`. Revert the change. If flipping the order
  still passes, the collapse in `_check_supervision` is wrong — most likely it is
  comparing lists to lists and never reaching the single-row path.

- [ ] **Step 7: Live-Aurora acceptance criteria.** With a run that has a proposal
  and no execution yet: the proposal, preconditions, and both verdict blocks
  render; the execution block shows its empty state; the post-execution line reads
  `not validated` with exactly `no execution has been recorded yet`. After Lab 4's
  execution and Wave B admission, on the **same run**: the execution block fills in,
  `fingerprint_matches` shows `yes`, the post-execution line flips to validated with
  an empty reason list, **and the pre-execution line and its reasons are unchanged
  from the first screenshot**. Take both screenshots and compare them; that
  comparison is this task's real acceptance test and it is the only place the
  retroactive-safety property is visible to a human.

  Then paste each of the four `_verify_sql` `rendered` envelopes into psql and
  confirm each reproduces its panel — including the verdict, which returns the
  same two booleans and two arrays the screen shows.

- [ ] **Step 8: Cleanup and failure recovery.** Three states are normal and each
  must render without placeholder content: a run with no proposal shows the lens's
  own empty state; a proposal with no execution renders three of four panels with
  the execution panel showing its empty state; and a proposal whose execution did
  not match renders fully with "Matches the proposal: no." None of the three is an
  error.

  Two are defects and must not be papered over. A null `verdict` beside a non-null
  `proposal` means `proof.autonomy_readiness()` failed rather than returned no rows;
  the lens renders `not eligible` / `not validated` because absent must read as
  negative, never as pass. And a 500 from `/v1/runs/{run_id}/supervision` breaks
  `loadRun()` entirely through `Promise.all` — if that happens, the endpoint is
  raising where it should return null members, which is a step 3 defect and not
  something to catch in the frontend.

  Nothing in this task writes to the database, so there is no state to reset between
  attempts beyond rebuilding `frontend/dist`.

- [ ] **Step 9: Participant-facing changes.** This lens is where the workshop's
  human-in-the-loop claim becomes a thing on screen with SQL behind it rather than
  a sentence in a slide. It sits on the Proof surface as a fourth lens beside
  receipt, replay, and timeline, which is the right home: it is a receipt about a
  decision. The `?lens=supervision` deep link is presenter-usable, matching the
  existing `?lens=timeline` convention.

- [ ] **Step 10: Commit.**

```bash
git add backend/app/verify_sql.py backend/app/insights.py backend/app/main.py \
  frontend/src/route.ts frontend/src/WorkbenchApp.tsx frontend/src/workbench.css \
  gates/route_contract.py
git commit -m "Add the supervision lens to the Proof surface"
```

The file list is explicit rather than `git add frontend/src` because step 5 touches
three files in that directory and an explicit list makes a forgotten one visible in
the commit. `frontend/dist` is gitignored (`.gitignore:24`), so step 6's build cannot
be staged by accident.

**Dependencies:** Task A5 (the schema and the verdict function), Task D2a (a
proposal to render), Task D3 (an execution to render). The lens can be built and
typechecked before D3 lands, but step 7's acceptance comparison needs D3's
execution row.

## Phase F — Infrastructure

Owning modules: this repo's `Makefile`, `.env.example`, and `backend/scripts/`;
plus the **sibling Workshop Studio repo's** CloudFormation, which is user-owned and
outside this worktree. Tasks below state explicitly which side owns each file. Per
the design spec, pgbench, JMeter, ECS, and Lambda load generators are rejected — none
connects through the app's own pool, which is the entire mechanism.

### Task F1: Drop the Performance Insights dependency from infrastructure

**Owning schema/module:** this repo's preflight and docs; sibling repo's CFN and IAM.

**Files:**
- Modify: `labs/incident/capture_observability.py` — already stripped in Task B6;
  this task removes the remaining infra-side coupling
- Modify: `.env.example`, `README.md`, `HANDOFF.md`, `DAT410-BUILD-BRIEF.md`,
  `WORKSHOP-BUILD-SUMMARY.md`, `docs/`, and `labs/incident/README.md` — reconcile
  all source-of-record and participant-facing documentation to the final narrative,
  scale, lab titles, two-wave model, and PI-free telemetry boundary
- Modify: `scripts/build_live_source_archive.sh` and
  `backend/tests/test_release_artifact_scripts.py` — require every new incident,
  exercise, gate, and supervised-execution runtime asset in the participant archive
- Modify: `.env.example` and `docs/` — the PI prerequisite, **and** the two
  schema-inventory rows that Task A1 left describing a table it dropped:
  `docs/data-model.md:22` (`| `database_insights_samples` | Incident-window
  Performance Insights wait and SQL observations |`) and
  `docs/implementation-spec.md:122` (`| `database_insights_samples` | PI top wait
  and SQL observations |`). Delete both rows. A1 deliberately did not touch them —
  its Files block is SQL, gates, and tests — so between A1 and this task the data
  model documentation names a relation that does not exist. These are inventory
  rows, not historical records, so Step 1's grep will hit them; that hit is this
  task's work, not evidence that B6 is incomplete
- Modify (sibling repo, user-owned): the Aurora cluster's
  `PerformanceInsightsEnabled` property, `PerformanceInsightsRetentionPeriod`, and
  the task role's `pi:GetResourceMetrics` / `pi:DescribeDimensionKeys` policy
  statements
- Test: `backend/scripts/doctor.py`

**Interfaces:**
- Consumes: Task B6's removal of all PI collection code.
- Produces: a workshop whose documented prerequisites no longer include Performance
  Insights, and a `make doctor` that does not check for it.

**Migration and compatibility implications:** PI being enabled is harmless — the
point is that nothing depends on it. Do not remove `PerformanceInsightsEnabled` from
CFN as a "cleanup": leaving it enabled costs nothing at 7-day free retention and
gives a facilitator a real console to open if they want one. What must go is the
**dependency**: the preflight assertion, the documented prerequisite, and the IAM
grant. Removing the IAM grant is the load-bearing change, because it is the only one
that makes the "does not depend on PI" claim testable rather than asserted. Sibling
CFN edits are user-owned; this task produces the exact diff and the reason, and the
user applies it.

- [ ] **Step 1: Prove the dependency is gone before touching IAM.**

```bash
rg -n -i 'performance.?insights|pi:|PerformanceInsights' \
  backend/ labs/ gates/ sql/ Makefile .env.example docs/
```

Expected after Tasks A1/B6: hits only in historical documents (the gate-results and
design-spec files, which correctly record why PI was removed). Any hit in executable
code means B6 is incomplete — finish it before proceeding.

- [ ] **Step 2: Remove the doctor check and the documented prerequisite.** Confirm
  `backend/scripts/doctor.py` no longer names the deleted
  `casework.database_insights_samples` in `REQUIRED_TABLES` (Task A1) and carries no
  PI-specific probe.

- [ ] **Step 3: Run doctor and the full gate sweep.**

```bash
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  make doctor
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  gates/checks.sh
```

Expected: doctor PASS, all gates PASS or BLOCKED-with-reason. Note the known trap:
`assert_live_capture_ready` is `SECURITY DEFINER` precisely because a masked
predicate broke `make doctor` — do not change its security context here.

- [ ] **Step 4: Write the sibling-repo diff into the handoff.** Produce the exact
  IAM statement to delete and the exact prerequisite paragraph to remove, with the
  one-line reason ("no code path reads PI; ASH does not sample
  `idle in transaction`, which is the state this incident holds"). Do not edit the
  sibling repo from this worktree.

- [ ] **Step 5: Live-Aurora acceptance criteria.** The definitive test, which Task B6
  also depends on: a complete `make live-workshop` run against a cluster with
  **Performance Insights disabled** exits 0 and admits a full corpus. Run it. If PI
  cannot be disabled on the shared cluster, run it with the PI IAM permissions
  revoked from the calling principal instead — that proves the same thing and is
  reversible.

- [ ] **Step 6: Cleanup and failure recovery.** If the run fails with an AWS
  authorization error naming `pi:`, a code path still reads PI and Step 1's grep
  missed it — find it rather than restoring the permission. Restoring the permission
  makes the failure invisible again, which is how this dependency survived the first
  redesign.

- [ ] **Step 7: Participant-facing changes.** The prerequisite list gets shorter, and
  the workshop stops depending on a feature whose sampling model silently excluded
  the exact wait state the lab is about. Say that plainly in the appendix — it is a
  genuinely instructive observability lesson, and burying it wastes the best teaching
  moment the redesign produced.

- [ ] **Step 8: Commit.**

```bash
git add backend/scripts/doctor.py .env.example docs/
git commit -m "Drop the Performance Insights dependency from prerequisites"
```

**Dependencies:** Tasks A1 and B6.

### Task F2: Re-validate the cold-account build budget against the 3M-row table

**Owning schema/module:** this repo's `Makefile` and bootstrap timing; sibling repo's
`WaitCondition` timeout and custom resources.

**Files:**
- Modify: `docs/` — the timing budget
- Modify (sibling repo, user-owned): the `WaitCondition` timeout
- Test: a timed `make live-workshop` run

**Interfaces:**
- Consumes: Task B1's 3,000,000-row bootstrap.
- Produces: a measured end-to-end build time and a `WaitCondition` timeout that
  exceeds it with real margin.

**Migration and compatibility implications:** the sibling infra audit already
recorded, unfixed, that the `WaitCondition` timeout is shorter than a cold-account
build takes, and that Bedrock first-use in a fresh account plus `FinalValidation`
needs a retry. Task B1 adds a measured 27.6s of bootstrap on top of that. 27.6s is
small in isolation and irrelevant to the audit's conclusion — the timeout was already
too short before this plan touched anything. Do not treat "we only added 27.6s" as
license to leave it. Also relevant: the audit found a **Create-only** custom resource
that skips on stack UPDATE, so a facilitator who updates rather than recreates a stack
can get a cluster whose lab table was never built. Measure the real number, then hand
the user a timeout with margin for the slowest observed case, not the median.

- [ ] **Step 1: Time a full cold run.** On a clean database, with an empty evidence
  store:

```bash
time ( DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  make live-workshop )
```

Record the wall-clock total and each phase. Reference points to beat: the old pipeline
measured 83.6s total with a 69.1s stall and 24.85s of synthesis; the new mechanism
measured 27.6s bootstrap and 22.3s backfill in isolation. The whole-run number is what
matters here, and it has not yet been measured end to end — that is this task.

- [ ] **Step 2: Run it three times and take the slowest.** Bedrock first-use latency
  in a cold account is the documented worst case, and a median hides it.

- [ ] **Step 3: Write the measured budget into the docs.** Actual numbers only. If the
  60-minute lab budget no longer holds, say so and cut a beat rather than reporting a
  number that assumes everything is warm.

- [ ] **Step 4: Live-Aurora acceptance criteria.** Three criteria:
  1. The slowest of three full runs completes inside the documented budget.
  2. The `WaitCondition` timeout the user is asked to set exceeds that slowest run by
     at least 2×.
  3. A stack UPDATE path is either proven to rebuild the lab table or documented as
     recreate-only — the Create-only custom resource finding must be closed one way
     or the other, not carried forward a third time.

- [ ] **Step 5: Cleanup and failure recovery.** Each timing run leaves a full corpus.
  Between runs, reset with the documented reset path (requires a `_test`-suffixed
  database name plus `ALLOW_TEST_DATABASE_RESET=1`) — never against the live
  retrieval database. Verify `current_database()` before every destructive command;
  `run_sql.py` and `get_conn` read `DATABASE_URL`, not `TEST_DATABASE_URL`, and that
  trap has already dropped a live database once in this project.

- [ ] **Step 6: Participant-facing changes.** The documented setup time becomes a
  measured worst case instead of an optimistic estimate. Participants in a cold
  account are the ones who suffer from the optimistic version.

- [ ] **Step 7: Commit.**

```bash
git add docs/
git commit -m "Record the measured cold-run build budget"
```

**Dependencies:** Tasks B1 through B6, including B1a (a full run must exist to
time), F1 (the run
must be timed on the PI-independent path).

## Phase G — Rehearsal

Owning module: none — this phase writes no product code. It runs the finished system
the way a participant and a facilitator will, in the room's conditions, and freezes
what it measures. Everything below is gated on all of Phases A–F.

### Task G1: Full-run rehearsal from a participant's seat

**Files:**
- Modify: `docs/superpowers/specs/2026-08-04-dat410-gate-results.md` — append the
  rehearsal record
- Modify: `docs/` — facilitator notes, with the measured waits

**Interfaces:**
- Consumes: every prior phase.
- Produces: a rehearsal record with real timings and the list of every point a
  participant could reasonably get stuck.

**Migration and compatibility implications:** none — read-only rehearsal, except for
the evidence a real run legitimately writes.

- [ ] **Step 1: Run all four labs as `workshop_participant`, not as the owner.** Owner
  privileges hide exactly the failures a participant hits. Use the participant role
  end to end, including the Lab 4 `CREATE INDEX`.

- [ ] **Step 1a: Rehearse the supervised-execution path end to end, as the
  participant.** This is the one path in the workshop where a human's own action is
  the load-bearing step, and it is the path most likely to be quietly broken by a
  privilege that was granted to the wrong role. Run it in order and record each
  observation:

  1. Lab 3's agent answer completes and a proposal row exists for that
     `agent_run_id`. Confirm from the participant's seat, on the Proof surface's
     supervision lens — not by querying `proof.action_proposals` as owner.
  2. The pre-execution verdict renders **before** anything is executed. Copy the
     rendered `pre_execution_eligible` value and the full `pre_execution_reasons`
     list into the rehearsal record verbatim. This is the "before" half of Task E4
     step 7's comparison and it cannot be reconstructed later.
  3. The participant approves explicitly, by name, per Task D3's participant copy.
  4. The participant executes the stored `proposed_sql` themselves in Code Editor,
     as `workshop_participant`. **Confirm the participant role can execute it and
     the agent's role cannot.** Attempt the same statement as the agent's database
     role and record the exact permission error. A workshop that claims the agent
     holds no DDL privilege must be able to show the refusal.
  5. Wave B admission runs and the execution row records `fingerprint_matches = t`.
  6. The post-execution verdict flips to validated, and the pre-execution verdict
     and its reasons are **unchanged** from the values recorded in sub-step 2.

  Sub-step 6 is not a formality. It is the only place in the entire rehearsal where
  the retroactive-safety property is checked against a real participant's real
  actions rather than against a test fixture, and a difference here is a defect in
  Task A5's function, not a rehearsal note.

- [ ] **Step 2: Time every wait a participant sits through.** Specifically the ~25s
  agent synthesis, the second Converse call that produces the proposal (Task D2a
  adds it to the same request, so Lab 3's total wait is the sum and the facilitator
  line must quote the sum, not the synthesis figure alone), the backfill hold, and
  the index build. Anything over 10 seconds needs a facilitator line telling the room
  it is expected.

- [ ] **Step 2a: Measure the numbers no earlier task measured, and record them as
  measurements.** Each of these is currently unmeasured. Every one is quoted to a
  participant or a facilitator somewhere, so each must come out of this rehearsal
  with a real figure beside it. Record the value, the instance class, and the row
  count for each — a figure without its substrate is not reusable.

  | Measurement | Where the figure gets quoted | Status before G1 |
  | --- | --- | --- |
  | Non-concurrent `CREATE INDEX ON workbench_lab.orders (customer_id, created_at DESC)` on 3,000,000 rows, as `workshop_participant` | Lab 4 participant copy and the facilitator line for step 2's >10s rule | **Unmeasured.** No figure exists in this plan or the design spec. Task D3's Migration paragraph forward-references this row. |
  | Lab 3 total wait: synthesis + the Task D2a proposal Converse call | Lab 3 facilitator line, quoted as the sum | Only the ~25s synthesis half is measured |
  | Wave B admission wall-clock, including the fingerprint resolve | Facilitator line for the Lab 4 → Proof transition | Unmeasured |
  | `prepare_lab_workload()` on 3,000,000 rows (Task B1's build) | Setup expectations and the reset path in step 6 | Unmeasured at 3M; only the 25K figure exists |

  **Measure the index build with `\timing on` and quote it non-concurrently**, because
  that is what the participant types. Do not substitute a `CONCURRENTLY` figure: it is
  a different operation with a different duration, and Task D3's copy does not use it.

  Until this step produces the first row's number, **no participant-facing or
  facilitator-facing file may state an index-build duration** — not as an
  approximation, not as a range, not as "about a minute." An invented figure here is
  the same defect class as an authored evidence record: it reads as measured and is
  not. If G1 runs on an instance class other than the deploy target
  (`db.r8g.xlarge`, I/O-Optimized, non-NVMe), record the class alongside the figure
  and mark the number as not-yet-calibrated rather than quoting it as the workshop's.

- [ ] **Step 3: Record every stumble verbatim.** Ambiguous instruction, unexpected
  error text, a panel that looked empty, a number that did not match. Do not fix them
  during the rehearsal — a rehearsal that stops to fix things measures nothing.

- [ ] **Step 4: Live-Aurora acceptance criteria.** The participant path completes all
  four labs; the agent's finding names both root causes with citations; Lab 4's index
  changes the plan; the replayed Lab 3 investigation is byte-identical; a proposal and
  a matching execution are both recorded for the rehearsal's own run, with the
  pre-execution verdict identical before and after execution; the agent's role is
  measurably unable to run the DDL the participant ran; **all four of step 2a's
  measurements have real figures with their instance class and row count recorded**;
  no step requires facilitator intervention that is not already written into the
  notes.

- [ ] **Step 5: Triage the stumble list.** Each item becomes either a content fix, a
  code fix, or a documented facilitator line. Nothing gets dropped as "they'll figure
  it out."

- [ ] **Step 6: Cleanup and failure recovery.** Reset the database between rehearsals
  via the documented reset path with the `_test` guard. Keep the rehearsal's evidence
  corpus from the final run as the reference for G3's numbers.

  **Pass `--drop-lab-schema` explicitly.** After Task C2 step 3a, the lab schema
  survives a successful run by default — that is deliberate, because Wave B and the
  Lab 4 index both need the Wave A table to still exist. It also means a rehearsal
  reset that omits the flag leaves 3,000,000 rows and their index in place, and the
  next rehearsal measures a warm substrate rather than a cold one. Between rehearsals,
  drop it; after the final rehearsal, keep it if G3 still needs to query it.

- [ ] **Step 7: Participant-facing changes.** All of them, indirectly — this is where
  the participant-facing copy stops being a guess.

- [ ] **Step 8: Commit.**

```bash
git add docs/
git commit -m "Record the participant-seat rehearsal"
```

**Dependencies:** all of Phases A–F.

### Task G2: Failure-injection rehearsal

**Files:**
- Modify: `docs/` — the facilitator recovery runbook
- Modify: `docs/superpowers/specs/2026-08-04-dat410-gate-results.md`

**Interfaces:**
- Consumes: Gate 4's three proven recovery paths and Task B3's `describe_failure()`.
- Produces: a runbook entry per injected failure, each with the exact recovery command
  and the exact symptom a facilitator will see.

**Migration and compatibility implications:** none, by construction — every injected
failure must be recoverable without a fresh database, which is what Gate 4 proved for
three of them.

- [ ] **Step 1: Inject each failure and record the symptom and recovery.** At
  minimum: SIGKILL the orchestrator mid-hold; make CloudWatch unreachable; let the
  hold fail to prove (fewer than 10 sessions blocked); have the participant create the
  index with the columns reversed; run `--wave B` twice; run `--wave B` without a
  Wave A. Each one has a designed behavior somewhere in Phases A–C — this step checks
  the designed behavior is what actually happens.

- [ ] **Step 1a: Inject the four supervised-execution failures.** Each has a
  designed behavior in Task A5, D2a, or D3, and each is a plausible participant
  mistake rather than a contrived one:

  1. **The participant runs a differently-shaped index.** Reverse the key columns —
     this is the same injection as step 1's reversed-column case, now checked on the
     supervision path. Designed behavior: Wave B resolves no index by fingerprint,
     records the execution anyway with `fingerprint_matches = false`, and the
     supervision lens shows "Matches the proposal: no" while the post-execution
     verdict reads `the executed action does not match the proposed action`.
     **The run must not fail and the lab must remain re-runnable.** Record what the
     participant sees; Task D3's copy requires this read as information, not as a
     scolding.
  2. **The participant never executes.** Admit Wave B with no `CREATE INDEX` run.
     Designed behavior: no execution row, the execution panel shows its empty state,
     and the post-execution verdict reads exactly `no execution has been recorded
     yet` while the pre-execution verdict still renders normally.
  3. **The participant executes twice.** Run the stored `proposed_sql` a second time
     after Wave B. Designed behavior: PostgreSQL rejects the duplicate index name,
     and if a second execution row is recorded the table accepts it — it is
     append-only by design (Task D3 step 11) — with the verdict reading the latest.
     Confirm no row was updated in place: `proof.action_executions` has no `UPDATE`
     grant, so an attempt to rewrite the first row must fail on privileges.
  4. **The proposal is absent.** Answer through the Strands path
     (`/v1/agent/strands/answer`), which Task D2a deliberately does not instrument.
     Designed behavior: the request succeeds, no proposal is written, and the
     supervision lens renders its "no proposal recorded for this run" empty state.
     **A 500 here is the NOT NULL foreign-key defect Task D2a's guard exists to
     prevent**, and it is a Phase D fix, not a runbook entry.

  Also attempt, as the agent's own database role: `INSERT` into
  `proof.action_executions` (must succeed — the agent's role has `INSERT`, and this
  is honest: the agent records, it does not execute) and `CREATE INDEX` on
  `workbench_lab.orders` (must fail on privileges). Record both. The distinction
  between "can write an audit row" and "can change the database" is the whole
  supervised-execution claim, and a rehearsal that never tests it is asserting it.

  And once more as the **API pool** identity (`WORKSHOP_APP_DATABASE_URL`, no
  `SET ROLE`), which is a different role from the agent's and a different role from
  the participant's: `UPDATE workbench_lab.orders` must succeed, and `CREATE INDEX`,
  `DROP TABLE`, and `TRUNCATE` on that table must each fail with SQLSTATE 42501.
  Task D3 step 1's `ApiPoolLabPrivilegeTests` covers this against the test database;
  this is the same check against the real provisioned cluster, where the roles were
  created by the deployed `sql/11` rather than by a test fixture. Three identities,
  three different privilege sets, all on one table — if any two of them turn out to
  be the same role on the live cluster, the provisioning is wrong and nothing
  downstream of it means what it says.

- [ ] **Step 2: Confirm every failure message names its condition.** Task B3 requires
  `describe_failure()` to say which condition went unmet, never "timed out." A message
  that says "timed out" is a Phase B regression, not a rehearsal finding to write
  around.

- [ ] **Step 3: Confirm the CloudWatch case is silent and non-fatal.** With CloudWatch
  unreachable the run must exit 0 and record `"cloudwatch_status": "unavailable"`.
  CloudWatch is best-effort; a failure there must never raise.

- [ ] **Step 4: Live-Aurora acceptance criteria.** Every injected failure recovers
  without recreating the database; every failure message names its condition; the
  reversed-column index leaves the lab re-runnable; double `--wave B` is idempotent;
  Wave B without Wave A is rejected by the Task A3 admission contract with the
  message that contract specifies; all four supervised-execution injections behave as
  designed, with the mismatch case recorded rather than skipped and the Strands case
  returning 200 with no proposal.

- [ ] **Step 5: Cleanup and failure recovery.** This task *is* the cleanup test. If any
  injected failure requires a fresh database to recover from, that is a Phase A–C
  defect — fix it there and re-run this task.

- [ ] **Step 6: Participant-facing changes.** The runbook is facilitator-facing. It is
  what stands between one participant's mistake and a stalled room.

- [ ] **Step 7: Commit.**

```bash
git add docs/
git commit -m "Add the failure-injection runbook"
```

**Dependencies:** Task G1.

### Task G3: Final gate sweep, measured-number reconciliation, and freeze

**Files:**
- Modify: `docs/superpowers/specs/2026-08-04-dat410-incident-scenario-redesign-design.md`
  — replace every reference observation with the rehearsal's measured value
- Modify: `docs/superpowers/specs/2026-08-04-dat410-gate-results.md` — Gate 6
- Modify: `CLAUDE.md`, `AGENTS.md` — the permitted-observations list

**Interfaces:**
- Consumes: Tasks G1 and G2.
- Produces: a branch where every documented number was measured by the final run, and
  every gate is green with a recorded exit code.

**Migration and compatibility implications:** the numbers currently in the design spec
are Gate 1–5 reference observations from throwaway prototypes, explicitly labeled as
such. This task replaces them with the real system's numbers. Any number that cannot
be reproduced by the final run gets deleted, not softened.

- [ ] **Step 1: Core gate sweep with `FAIL_ON_BLOCKED=1`. This is the core freeze
  gate, and it does not include the security gates.**

```bash
FAIL_ON_BLOCKED=1 \
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  gates/checks.sh
```

Expected: exit 0, with every registered `CORE_GATES` entry, including G-32, G-33,
and G-34, PASS. Do not copy a fixed count here: the registry is the source of
truth, and this plan deliberately adds three gates after the original seven.
`FAIL_ON_BLOCKED=1` is for release verification, and this is the release
verification. A BLOCKED gate here means a gate has nothing to judge, which at
freeze time is indistinguishable from a gate that cannot fail.

**Do not add `WORKBENCH_SECURITY_ENABLED=1` to this command.** It would not do what
it appears to do: the no-argument path of `gates/checks.sh` forces
`export WORKBENCH_SECURITY_ENABLED=0` at `:58` and builds `WANT` from `CORE_GATES`
only, so the variable is overwritten and the security gates never run — measured, a
`WORKBENCH_SECURITY_ENABLED=1 FAIL_ON_BLOCKED=1 gates/checks.sh` run executed
exactly seven gates. Setting it here reads as an effective control while doing
nothing, which is worse than omitting it: a future reader concludes the freeze sweep
covered the security module when it did not. The security gates are Step 1a's, run by
explicit ID.

G-34 deserves a named check here rather than being counted among the rest. It reports
BLOCKED when `proof.autonomy_readiness()` does not exist, and its behavioral half
scans rows — so a sweep run against a database with the schema applied but zero
proposals gives G-34 nothing to contradict. Confirm the sweep ran against the
rehearsal's own database, the one G1 left holding a real proposal and a real
execution, and record G-34's PASS line verbatim including its assignment count and
helper list. That line is the freeze-time evidence that the pre-execution path is
absent rather than merely unused.

- [ ] **Step 1a: Optional-security release gates, run separately and by explicit
  ID.** These judge the optional RLS/masking lab, not core participant readiness.
  Their result never blocks the core freeze in Step 1, and Step 1 never runs them.
  Run this step only against a database that has had `make security-schema`
  applied — on a core-only database all four report BLOCKED, which is honest and is
  not a release verdict for the optional lab in either direction:

```bash
WORKBENCH_SECURITY_ENABLED=1 FAIL_ON_BLOCKED=1 \
DATABASE_URL="postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" \
WORKSHOP_APP_DATABASE_URL="postgresql://workshop_app@<host>:5432/dat410_review_remediation_test?sslmode=require" \
  gates/checks.sh G-27 G-29 G-30 G-31
```

Expected: exit 0, four PASS. `WORKSHOP_APP_DATABASE_URL` is load-bearing for G-29
only: it needs the app-pool DSN to `SET LOCAL ROLE`, and without it G-29 reports
BLOCKED — observed during Task A1, where it was not an A1 defect but did leave the
masking half of the sweep unexercised. Do not record a sweep as green while G-29 is
BLOCKED for want of an environment variable.

G-27 deserves a named treatment here, for the opposite reason to G-34: it fails
loudly on a corpus with **zero** restricted rows (measured on the migrated test
database after Task A1: `restricted rows measured on the engine: 0`, then
`assertion failed: retrieval_admin ... the capture holds no restricted evidence`,
exit 1). That is the correct behaviour, and it is the tripwire for Task C1's
visibility classifier silently not running. If G-27 fails here, do **not** treat it
as a gate defect, an empty-database artifact, or a core-workshop blocker: check that
C1's classifier produced a mixed corpus and that C2 threaded the full four-key `acl`
object into the admission payload.

Record the numbers, not the verdicts, and check them against optional-security
release criteria (2) and (3) in Global Constraints — the restricted row count, the
workshop row count, and the `classifier_version` that produced them:

```bash
psql -X -v ON_ERROR_STOP=1 \
  "postgresql://<user>@<host>:5432/dat410_review_remediation_test?sslmode=require" <<'SQL'
SELECT acl ->> 'visibility' AS visibility,
       acl ->> 'classifier_version' AS classifier_version,
       count(*) AS rows
FROM casework.evidence_items
WHERE NOT is_deleted
GROUP BY 1, 2
ORDER BY 1, 2;
SQL
```

  This one needs no `DO $guard$` block: it is a read with no write to guard.
  Expected: **both** `workshop` and `restricted` present with nonzero counts, and one
  `classifier_version` value across all rows. A single-visibility result means the
  optional lab is not releasable even if all four gates said PASS — the gates would
  have judged an unmixed corpus, which proves nothing about row filtering. A mixture
  of `classifier_version` values means two classifier generations are in one corpus;
  re-run the capture rather than reasoning about which rows are which.

- [ ] **Step 2: Full test suite and typecheck.**

```bash
.venv/bin/python -m pytest backend/tests -q
cd frontend && npm run build
```

Expected: all pass, `tsc` clean.

- [ ] **Step 3: Reconcile every number.** Walk the design spec's four Measured Baseline
  sections and every participant-facing number. Each one is either reproduced by the
  final run and kept, or deleted.

  Two limitations must each be explicitly closed or explicitly restated as open — never
  left implicitly closed:
  1. **Real-pool proof.** Gate 1 closed this: it drove the real
     `psycopg_pool.ConnectionPool` through `backend/app/db.py`'s `open_pool()`/`get_pool()`.
     Cite Gate 1 for the pool claim.
  2. **Endpoint-level proof.** Gate 1 did **not** exercise FastAPI request handling,
     Pydantic models, per-request ASGI threading, or the `outcome`-as-200 contract. Cite
     Task B2's live acceptance result for this, or state that it remains open.

  Also confirm that Gate 1's stale numbers (nine `statement_timeout`, one `pool_timeout`,
  a `'3s'` statement timeout) appear nowhere as acceptance values. The shipped mechanism's
  numbers are ten `committed` plus two `pool_timeout` under a 40-second statement timeout.

  A third item joins the two limitations above, and it is a claim rather than a number:

  3. **Supervised execution is an autonomy-*readiness* assessment, not autonomous
     execution.** Every surface that mentions the autonomy verdict must say so. Check
     that no participant-facing text, slide, or spec section has drifted into
     describing the workshop as demonstrating autonomous remediation, an agent that
     "fixed" the database, or a system cleared to act unattended. The verdict answers
     "would this action have been safe to take unattended, judged on what was known
     before it was taken" and nothing more.

  ```bash
  rg -ni "autonomous(ly)? (remediat|fix|execut|appl)|the agent (fixed|created the index|applied)" \
    docs/ content/ frontend/src/ labs/
  ```

  Expected: no hit. A hit that explicitly *contrasts* with what the workshop does
  ("this is not autonomous remediation") is correct and stays; read each hit rather
  than deleting on the match.

  Then reconcile the supervision numbers from G1's rehearsal record: the index name
  the proposal actually generated, the fingerprint the proposal stored, the three plan
  checkpoint labels the execution row references, and Lab 3's total wait including the
  proposal call. Any of these quoted from this plan rather than measured by the final
  run gets replaced or deleted — this plan's `idx_orders_priority_tier_created_at` is
  a prediction of what `index_name_for()` produces, not a measurement.

- [ ] **Step 4: Update the permitted-observations list.** `CLAUDE.md` currently permits
  "PostgreSQL, CloudWatch, and Database Insights observations." Drop Database
  Insights. The live-data-only rule itself is unchanged and non-negotiable.

- [ ] **Step 5: Confirm no prototype survives.**

```bash
rg -n --files -g '_gate*.py' .
git status --porcelain
```

Expected: no `_gate*.py` files, clean tree. Task C4 removes them with `trash` plus
`git rm`; this is the check that it happened.

- [ ] **Step 6: Write Gate 6.** Consolidated report: every gate's result, the
  rehearsal timings, the runbook, the reconciled numbers, and an explicit list of
  anything still owed. An empty owed-list must be earned, not assumed.

- [ ] **Step 6a: Verify the session thesis reached every participant-facing surface.**

Walk each surface a participant sees — the four Workshop Studio lab pages, the guide, the
Overview surface, and the closing — and confirm each one expresses the thesis rather than
the mechanism. A page is wrong if its summary line ends at "we fixed the query," even when
every fact on it is accurate.

```bash
rg -n "fixed the (missing )?index|fixed the query|added the index" \
  docs/ frontend/src/ labs/ backend/app/ README.md
```

Expected (measured 2026-08-04): four hits, all in `docs/superpowers/` — one in the design
spec, and three in this plan, of which one is this step's own `rg` line matching its own
pattern. All four are the prohibition, not a violation of it. Any hit outside
`docs/superpowers/` is a real defect. Hits describing the mechanical step inside Lab 4 are
correct and stay.

**Do not add `content/` to that path list.** It does not exist in this repository — the
Workshop Studio pages live in the sibling repo, and `rg` exits 2 on a missing directory,
which turns this check into a script failure rather than a finding. Run the same pattern
separately in the sibling checkout as part of Task F1's handoff, and record both results in
Gate 6.

Then confirm four things by reading, not grepping:
1. The verbatim closing message is emitted by `labs/incident/run_live_workshop.py`'s `--wave B`
   path, conditional on this participant's own Wave B admission having succeeded, and
   is **not** printed unconditionally on the sibling repo's static Lab 4 page — a
   Markdown page renders the same sentence for a participant whose admission failed,
   which is the live-data-only rule broken in the summary text. Verify the conditional
   by reading the emitting code, then verify the absence by grepping the sibling
   checkout for the closing sentence.
2. "Recommend, don't execute" appears as the participant-facing phrasing of the agent's
   read-only constraint.
3. Fleet expansion appears only in the closing architecture discussion, with no lab step,
   second cluster, or cross-fleet aggregation added anywhere.
4. The supervised-execution model appears as a shipped, inspectable thing rather than a
   stated intention: a participant can point at the proposal, the approval, the
   execution record, the fingerprint match, and the two separately-computed verdicts.
   The claim "human in the loop" must be traceable to rows, not to a bullet.

- [ ] **Step 7: Live-Aurora acceptance criteria.** All gates exit 0 under
  `FAIL_ON_BLOCKED=1`, with G-34 PASS rather than BLOCKED and its output recorded; the
  full test suite passes; `tsc` clean; every documented number traces to the final run;
  no `_gate*.py` remains; Gate 6 is written with its owed-list stated; and Step 6a's
  four thesis checks all hold.

- [ ] **Step 8: Cleanup and failure recovery.** Remove the disposable
  `dat410_review_remediation_test` database only after Gate 6 is written — it holds the
  corpus every number cites. `dat410_live` is deliberately **not** migrated by this
  plan; that decision stands and must be restated in Gate 6 so it is not mistaken for
  an oversight.

- [ ] **Step 9: Participant-facing changes.** Every participant-facing number in the
  workshop is now one that a participant's own run will reproduce. That is the whole
  point of the live-data-only rule, and this is the task that verifies it rather than
  asserting it.

- [ ] **Step 10: Commit.**

```bash
git add docs/ CLAUDE.md AGENTS.md
git commit -m "Reconcile measured numbers and record Gate 6"
```

**Dependencies:** Tasks G1 and G2.
