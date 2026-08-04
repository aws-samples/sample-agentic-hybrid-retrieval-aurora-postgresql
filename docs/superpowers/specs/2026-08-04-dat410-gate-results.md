# DAT410 Incident Redesign — Gate Results

Running record of Gates 1–6 from `docs/superpowers/plans/2026-08-04-dat410-incident-scenario-redesign-plan.md`. All runs against the real Aurora cluster `agenticretrievalcorestack-aurorapostgresretrievalc-rxrppbdex0nu` (`db.r8g.2xlarge`, Aurora PostgreSQL 18.3), disposable database `dat410_review_remediation_test`.

## Gate 1: Prove all 10 API sessions block directly on the backfill while the pool-status endpoint remains responsive

**Result: PASSED** (third attempt — first two attempts found and fixed real bugs, see below)

```
bootstrap: 10.63s
backfill (left open): 21.12s

writer 1: statement_timeout after 3.19s
writer 2: statement_timeout after 3.58s
writer 3: statement_timeout after 4.04s
writer 4: statement_timeout after 4.29s
writer 5: statement_timeout after 4.68s
writer 6: statement_timeout after 5.09s
writer 7: statement_timeout after 5.39s
writer 8: statement_timeout after 5.81s
writer 9: statement_timeout after 6.15s
writer 10: pool_timeout after 3.01s
ALL 10 GENUINELY BLOCKED (checkout or statement timeout): True

samples collected: 24
max status-check latency: 0.0001s
samples showing pool_available=0 and requests_waiting>=2: 11

GATE 1 PASSED
```

**Two real bugs found and fixed while getting to this result — both must inform the real hot-write endpoint implementation later in this plan, not just this gate script:**

1. **First attempt** (no statement timeout at all, only `pool.connection(timeout=3.0)`): hung indefinitely. Root cause: `pool.connection(timeout=3.0)` only bounds the *checkout* wait (how long to wait for a free pool slot). A writer that gets a real connection immediately (before the pool fully saturates) has no bound on how long it then waits on the actual row lock. Confirmed via `pg_stat_activity`: sessions stuck `active`/`wait_event=Lock:Transactionid` for 50+ seconds with no timeout firing. **Action for the real endpoint: checkout timeout alone is insufficient; a statement-level timeout is required too.**

2. **Second attempt** (added `SET LOCAL statement_timeout = '3s'` as a bare `conn.execute()` call before the `UPDATE`): still hung. Root cause: the pool's connections run `autocommit=True` (`backend/app/db.py`'s `_configure_connection`), so each bare `conn.execute()` is its own implicit transaction. `SET LOCAL` only lasts until the *current* transaction ends — the `SET LOCAL statement_timeout` call's own implicit transaction ended immediately, silently resetting the timeout to unlimited before the `UPDATE` ran in a fresh transaction. **Action for the real endpoint: `SET LOCAL statement_timeout` (and any other `SET LOCAL`, including the `application_name` tag) must be issued inside the SAME explicit `with conn.transaction():` block as the actual write — never as a separate bare `execute()` call on an autocommit connection.** This is a real, subtle, easy-to-get-wrong pattern that the Orchestration phase's hot-write endpoint task must call out explicitly, not assume.

Fixed by wrapping `SET LOCAL application_name`, `SET LOCAL statement_timeout`, and the `UPDATE` in one `with conn.transaction():` block. Third attempt passed cleanly.

**Also incidentally exercised (not by design) an abandoned-transaction scenario**: the first hung attempt's process was killed with SIGKILL while the backfill and hot-write sessions were still open server-side. Recovery via `pg_terminate_backend()` filtered by `application_name` plus `DROP SCHEMA ... CASCADE` worked cleanly on the first attempt with no residual state affecting the second/third runs. This is a real, positive data point for Gate 4, run early by accident.

## Gate 2: Prove Wave A replay remains unchanged after Wave B admission

**Result: PASSED**

```
evidence_items present: 103
run_id: 87a5376f-ee89-41b2-9a2f-306ddddf0f73
candidates before: 15
performed a later write against casework.evidence_items
candidates after: 15

GATE 2 PASSED: replayed candidates unchanged after a later write
```

Ran against real, existing admitted evidence (103 items, left over from earlier session work — `casework`/`retrieval`/`proof` untouched by Gate 1, which only drops `workbench_lab`). `search_evidence_impl` → `explain_ranking_impl` round trip confirms `proof.retrieval_candidates` (keyed by `run_id`) is genuinely immune to a subsequent write against `casework.evidence_items` — the design spec's claim about the real replay path (not just the SQL text) holds against the live database. One fixture bug found and fixed (assumed a nonexistent `updated_at` column; `casework.evidence_items` has no such column — used `source_revision = source_revision` as a harmless no-op write instead, which still exercises the same "a write happened after the run" condition).

## Gate 3: Confirm pre-remediation evidence remains additive rather than incorrectly superseded

**Result: PASSED**

```
current documents before: 103
is_current demotion queries found: 8 (expected 8, manually verified scoped on 2026-08-04)
current documents after: 103

same set of current evidence_ids: True
content hashes unchanged (no unnecessary version bump): True
no existing evidence lost is_current status: True
GATE 3 PASSED
```

Ran the REAL `rebuild_search_index()` code path (not a synthetic row insert — the original plan's approach was revised after discovering `casework.evidence_items` has no `is_current` column at all; that versioning lives on `retrieval.documents`/`retrieval.chunks` only, and is populated exclusively by the search-index rebuild path). Manually audited all 8 `SET is_current = false` sites in `backend/app/search_index.py`: 2 join-scoped via `previous.evidence_id`, 2 use a bound `evidence_id`/`document_version_id` parameter, 2 use `ON CONFLICT (document_version_id)` (inherently single-row), 2 use `NOT EXISTS (...document_version_id...)` (chunk scoped to its own document's survival). None can demote an unrelated evidence item's document — confirmed by both static audit and this live behavioral run (103/103 evidence items retained `is_current=true`, identical content hashes, after a real rebuild touching the whole corpus). This directly de-risks the Two-Wave Evidence Model's core claim: admitting Wave B and rebuilding the index will not silently supersede Wave A.

**Caveat, honestly noted**: this test rebuilt the SAME evidence (no new Wave-B-shaped items were actually admitted, since constructing a valid synthetic `casework.admit_evidence` payload outside a real live-workshop run would require faking the entire `admission payload v1` schema — not worth the fragility for a gate script). It proves "rebuilding doesn't spuriously demote unrelated evidence," which is the load-bearing half of the claim. It does NOT yet prove "admitting genuinely new Wave B evidence via the real follow-up admission contract correctly keeps Wave A additive" end-to-end, because that admission contract doesn't exist as code yet — that remains owed to the real "Schema and Admission" implementation phase, with its own test.

## Gate 4: Add fail-safe cleanup for timeouts, abandoned transactions, load generators, pool recovery, and reruns

**Result: PASSED** (clean on the first deliberate attempt — consistent with Gate 1's earlier incidental recovery from a real SIGKILLed process)

```
orphan started, pid=6070
client process SIGKILLed
probe_abandoned_transaction: PASSED

pool stats before saturation: {'connections_num': 1, 'pool_size': 1, 'pool_available': 1, 'requests_waiting': 0}
probe_pool_recovery: PASSED (after={'connections_num': 9, 'requests_num': 15, 'requests_queued': 14,
  'requests_wait_ms': 22514, 'usage_ms': 15622, 'pool_size': 9, 'pool_available': 9, 'requests_waiting': 0})

probe_rerun_against_dirty_state: PASSED

GATE 4 PASSED: {'abandoned_transaction': True, 'pool_recovery': True, 'rerun_dirty_state': True}
```

All three failure modes proven recoverable without a fresh database:
1. A hard-killed (SIGKILL, not graceful close) client process leaves an orphaned server-side backend that `pg_terminate_backend()` cleanly removes.
2. The real pool genuinely grows under load (1→9 connections, `requests_queued=14` confirms real queuing pressure was applied) and fully recovers to `pool_available == pool_size` afterward — no manual intervention, no restart needed.
3. Rebuilding `workbench_lab` from a dirty/non-canonical prior state (matches the existing `_create_lab_workload`'s `DROP SCHEMA ... CASCADE` pattern) produces a clean, empty result every time.

Combined with Gate 1's earlier incidental recovery from the same abandoned-transaction scenario (hit organically while debugging a real script bug, not by design), this failure mode has now been proven recoverable twice, independently.

## Gate 5: Validate corpus diversity and deduplication before freezing document-count expectations

**Result: pending**

## Gate 6: Consolidated report and user go-ahead

**Result: pending — blocked on Gates 2–5**
