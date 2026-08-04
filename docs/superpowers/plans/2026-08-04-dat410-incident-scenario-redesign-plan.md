# DAT410 Incident Scenario Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Lab 1's broken, Performance-Insights-dependent single-incident mechanism with a real, measured, production-representative four-phase incident (unbatched migration backfill → connection-pool exhaustion → query-plan regression, diagnosed before remediation), producing a 180–250 document two-wave evidence corpus that gives Labs 2–4's retrieval/agent/citation mechanics genuine material to work with.

**Architecture:** A new orchestration driver in `labs/incident/` runs four phases against a real 3,000,000-row `workbench_lab.orders` table: (1) an unbatched backfill left open in an explicit transaction, (2) ten tagged hot-write requests through the existing FastAPI connection pool proving genuine pool exhaustion via condition-based polling (not fixed sleeps), (3) commit and recovery verification, (4) — deferred to Lab 4 — the participant's own `CREATE INDEX` fixing a query-plan regression that `ANALYZE` alone does not fix. Evidence is admitted in two waves: Wave A (diagnostic, end of Lab 1) and Wave B (remediation, end of Lab 4, additive not replacing). The full design rationale, real measurements, and every rejected alternative are in `docs/superpowers/specs/2026-08-04-dat410-incident-scenario-redesign-design.md` — read it before starting any task below; this plan does not repeat that reasoning.

**Tech Stack:** Python 3.13 (`labs/incident/`, `backend/app/`), PL/pgSQL (`sql/`), FastAPI/`psycopg_pool`, Cohere Embed v4 via Bedrock, existing 7-tool agent registry (`agent/registry.py`), React/TypeScript frontend (`frontend/src/`), Workshop Studio content (sibling repo).

## Global Constraints

- **Terminology, exact and non-negotiable in all participant-facing content and code comments:**
  - "migration" always means an application-level **online schema and data migration** (`ADD COLUMN` + backfill) — never Aurora engine-version migration. Say "online schema and data migration" or "the migration," never bare "upgrade."
  - This is a **real, measured, production-representative incident** — not "a production incident." It did not occur in an actual production system; it is a widely-recognized failure pattern reproduced live on a real Aurora cluster. Never write "production incident."
  - Participant-facing terminology: "incident diagnosis" → "evidence-backed finding"; "remediation delta" → "validation evidence"; "incident agent" → "hybrid retrieval agent"; "remediate" → "apply and validate the recommendation." Internal package/schema/ID names (`labs/incident/`, `casework.*`, `INC-<run-suffix>`, etc.) do NOT change.
  - Participant-facing agent name: **Hybrid Retrieval Agent**, described as a **read-only database-evidence agent** — distinct from the app's own name "Hybrid Retrieval Workbench" (`backend/app/config.py`'s `APP_DISPLAY_NAME`, unchanged).
  - Lab titles: Lab 1 "Capture and admit live evidence"; Lab 2 "Build hybrid retrieval in SQL"; Lab 3 "Build the hybrid retrieval agent"; Lab 4 "Validate, prove, and replay."
- **Scale, exact numbers, do not round or approximate:** `workbench_lab.orders` = 3,000,000 rows (`LAB_ROWS` constant, currently 25,000). `workbench_lab.customers` stays 5,000. Corpus target = 180–250 searchable documents, a range not an exact number, from genuinely distinct signal types — never from denser time-sampling of the same signal. CloudWatch documents do not count toward this range.
- **Live-data-only, unchanged from the existing project rule:** zero fixtures/mocks/dummy/offline/canned records anywhere in the participant path, ever. Every document in both Wave A and Wave B must derive from genuinely measured observations of that participant's own run.
- **The hold is condition-based, never a fixed sleep.** The hold controller polls `get_pool().get_stats()` plus `pg_stat_activity`/`pg_locks` every 250ms and only begins the 10–15s observation hold after 3 consecutive samples simultaneously prove: `pool_size = pool_max = 10`, `pool_available = 0`, `requests_waiting >= 2`, and all 10 tagged sessions show `wait_event_type = 'Lock'` with the backfill PID in `pg_blocking_pids()`.
- **The 250ms poll is control, not document generation.** Persist every raw poll sample (matching the existing `casework.*_samples` pattern). Create a searchable document only on a state change or a meaningful interval boundary — never one document per poll tick.
- **The agent never gets DDL privilege or an execution path.** This is already true today (all 7 tools in `agent/registry.py` are read/synthesis-only) — no task in this plan may add a write-capable tool. The participant executes `CREATE INDEX` themselves in Code Editor after reviewing the agent's recommendation.
- **Wave B is additive, never a replacement.** Before-`ANALYZE`, after-`ANALYZE`, and post-index plan checkpoints all remain separate, permanently retrievable documents. Never tombstone or supersede Wave A evidence because Wave B exists. Version (`is_current`) only genuinely mutable facts (e.g., incident status `investigating`→`resolved`), never the observations themselves.
- **No new fragile external dependency.** Reuse the existing FastAPI pool (`backend/app/db.py`, `DB_POOL_MAX_SIZE=10`) for pool exhaustion. Do not add RDS Proxy, PgBouncer, pgbench, JMeter, or ECS/Lambda-driven load generation. CloudWatch stays best-effort, non-gating, never blocking the pipeline.
- **Participant-facing incident time (Lab 1's induce/capture) stays under the 5–8 minute ceiling.** Bootstrap (3M-row table creation) is pre-session Workshop Studio provisioning time, not counted against this ceiling.
- **Preserve the optional RLS/masking lab and AgentCore lab** unless a task below finds a specific, concrete incompatibility (none anticipated — neither touches `workbench_lab` or the incident-generation code path today).
- **Aurora PostgreSQL owns ranking.** This redesign changes evidence generation shape; it never moves fusion/rerank logic out of `sql/03_search_functions.sql` or into the agent/frontend.
- **New gate IDs start at G-32** (G-31 is the highest existing gate anywhere in the codebase, confirmed via `gates/*.py` and `gates/checks.sh`).
- **Test convention, matching existing files exactly:** `TEST_DATABASE_URL` + `ALLOW_TEST_DATABASE_RESET=1`, database name must end in `_test`, `_apply_schema(connection, reset=True)` pattern from `backend/tests/test_admission.py`/`test_incident_lab.py`. Never run destructive tests against `DATABASE_URL` alone — always verify `current_database()` first.
- **Every task that runs SQL/Python against a real database must inline-set `DATABASE_URL` to the disposable test database and assert `current_database()` before any write** — this project has a documented prior incident (`run-sql-dsn-trap-live-drop` memory) where a script defaulted to the wrong DSN and dropped a live database.

---

## Gate Tasks (Risk-Reduction, Must Pass Before Proceeding to Implementation)

These six gates exist because further design discussion cannot reduce the remaining risk — only working prototypes can. Each gate task produces a small, throwaway or semi-throwaway script proving one specific claim against the real Aurora cluster, before any schema/orchestration/UI work begins. If a gate fails, STOP and return to design — do not patch around a failed gate to keep moving.

### Gate 1: Prove all 10 API sessions block directly on the backfill while the pool-status endpoint remains responsive

**Files:**
- Create: `labs/incident/_gate1_pool_block.py` (throwaway prototype script, not shipped — delete or move to `labs/incident/` proper only if Task "Hot-write driver" below reuses its logic verbatim)

**Interfaces:**
- Consumes: `backend/app/db.py`'s real `get_pool()`/`get_conn()` (the actual FastAPI pool, imported directly, not reimplemented)
- Produces: a pass/fail report (printed, not a test-framework assertion) proving the exact behavioral claim below

This gate closes the one unverified claim from the design spec's "Measured Baseline — New 3M-Row Mechanism" section: the earlier live test used direct short-lived `psycopg` connections with a `statement_timeout`, not the real `psycopg_pool.ConnectionPool`. This gate must use the real pool.

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

Expected: `GATE 1 PASSED` — all 10 writers show `pool_timeout`, the pool-status endpoint's max latency stays well under 0.5s even while the pool is fully saturated, and at least 3 samples show the pool genuinely exhausted (`pool_available=0`, `requests_waiting>=2`).

- [ ] **Step 4: If the gate fails, diagnose before retrying**

If not all 10 writers show `pool_timeout`: check `DB_POOL_MAX_SIZE` is actually 10 in the test environment's config (`backend/app/config.py`), and that `hot_write`'s row selection (IDs 1–10) matches the backfill's actual scan order — re-verify with a smaller writer count first if this fails, don't assume the earlier session's "lowest IDs collide first" finding transfers unchanged to the real pool path.

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
- Produces: a report of near-duplicate document pairs (via `pg_trgm` similarity or embedding cosine distance) at the 180–250 target scale, informing whether that range is actually achievable without the near-duplicate problem the design spec explicitly wants to avoid

This gate exists because the 180–250 target and its six signal-type categories are a design intent, not yet validated against real generated text. The risk: even "distinct signal types" could still produce near-duplicate document bodies if the text-generation templates are too similar across state-change events (e.g., many pool-saturation snapshots that differ only in a timestamp).

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

- [ ] **Step 4: If the gate fails**, identify which signal-type category is producing the near-duplicates and redesign that category's document-body template (e.g., include more of the actual varying measurement in the body text, not just the timestamp) before locking the 180–250 target — do not silently widen the similarity threshold to force a pass.

- [ ] **Step 5: Record the result, including the actual measured dupe rate, in `docs/superpowers/specs/2026-08-04-dat410-gate-results.md`** — this number directly informs whether the Evidence builder tasks later in this plan need a design adjustment before implementation.

---

### Gate 6: Run one complete Aurora rehearsal before broad Workshop Studio and participant-copy updates

**Files:** none created — this gate is a checkpoint, not a script.

**Interfaces:** consumes the combined output of Gates 1–5.

- [ ] **Step 1: Confirm Gates 1–5 all show PASSED in `docs/superpowers/specs/2026-08-04-dat410-gate-results.md`** before proceeding. If any gate is still FAILED, stop — do not begin the Orchestration/Corpus/Labs/UI/Infrastructure phases below with an unresolved gate.

- [ ] **Step 2: Report the consolidated gate results to the user** and get explicit go-ahead before starting the "Schema and Admission" phase. This is a deliberate human checkpoint, not an automatic pass-through — the six gates de-risk the mechanism, but committing to the full schema/orchestration/UI/infrastructure build is a bigger investment the user should explicitly approve seeing the real gate evidence first.

- [ ] **Step 3 (after all remaining implementation phases land, referenced here for sequencing only — do not execute yet):** the final "Rehearsal" phase at the end of this plan is Gate 6's real completion — one full, timed, end-to-end run of the finished mechanism against the real Aurora cluster, before any broad Workshop Studio content or participant-copy changes ship. This early Gate 6 step is the checkpoint; the full rehearsal task is defined in this plan's final phase.

---

*(Schema and Admission, Orchestration, Retrieval Corpus, Labs, UI, Infrastructure, and Rehearsal phases continue in the next section of this plan, added after the Gate tasks above are reviewed.)*
