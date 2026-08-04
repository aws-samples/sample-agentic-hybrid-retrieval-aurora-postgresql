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

**Result: pending**

## Gate 3: Confirm pre-remediation evidence remains additive rather than incorrectly superseded

**Result: pending**

## Gate 4: Add fail-safe cleanup for timeouts, abandoned transactions, load generators, pool recovery, and reruns

**Result: pending** (see Gate 1's incidental abandoned-transaction recovery above — a real, unplanned positive data point for this gate, to be cross-referenced not re-derived)

## Gate 5: Validate corpus diversity and deduplication before freezing document-count expectations

**Result: pending**

## Gate 6: Consolidated report and user go-ahead

**Result: pending — blocked on Gates 2–5**
