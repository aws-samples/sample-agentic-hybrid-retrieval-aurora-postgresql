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

**Result: PASSED, but surfaced a real gap between the 180-250 target and the natural event count — read the finding below, this is the most consequential gate result so far**

First attempt (148 documents, mechanically cycling ~3-10 fixed values through a repeated sentence template per category): **FAILED at 20.65% overall**, with `TEL-LOCK`/`TEL-POOL`/`TEL-REQ`/`TEL-WAL` all at 100% within-category near-duplicate rate. Root cause, confirmed by direct inspection: numeric variation alone inside a fixed sentence template does not produce enough lexical difference for `pg_trgm` similarity to distinguish documents — the fixed scaffolding text dominates the trigram set. This is a sharper, more specific version of the design spec's "distinct signal types, not denser sampling" principle than originally stated: **even genuinely-different numbers plugged into one template are not sufficient; the sentence structure itself must vary per event.**

Second attempt (51 documents, one per genuinely distinct real event on the incident's timeline, each described in different structural language — a state-change list for pool transitions, one document per actually-distinct outcome class for requests, milestone descriptions for WAL, not time-sliced snapshots): **PASSED at 6.43% overall.**

```
documents loaded: 51
total pairs checked: 1275
near-duplicate pairs (trigram similarity > 0.6): 82

per-category near-dupe rate (within-category pairs only):
  TEL-LOCK: 81/190 (42.6%)
  TEL-META: 0/45 (0.0%)
  TEL-PLAN: 1/3 (33.3%)
  TEL-POOL: 0/45 (0.0%)
  TEL-REQ: 0/3 (0.0%)
  TEL-WAL: 0/10 (0.0%)

overall near-dupe rate: 6.43%
GATE 5 PASSED (threshold: <15%)
```

**The consequential finding, separate from pass/fail**: this honestly-constructed sample — one document per genuinely distinct event across all six signal-type categories for ONE incident run — totals **51 documents**, not 180-250. `TEL-LOCK` still shows 42.6% even after the fix, because there are only 10 hot writers and their "entered wait" / "timed out" descriptions still share too much scaffolding language across writers — this category may have an inherent ceiling on how many genuinely-distinct documents it can produce for exactly 10 writers, no matter how the sentences are varied.

**This means the 180-250 target, as currently scoped to "one run's four phases," may not be reachable without reintroducing the near-duplicate problem this gate exists to prevent.** Options for the Evidence builder implementation phase to resolve, not yet decided:
1. Accept a smaller corpus (e.g., 50-80 documents) as the honest number for one run, revising the 180-250 target.
2. Find additional genuinely distinct signal categories not yet in the six listed (e.g., per-writer individual timeline documents combining multiple signal types per writer, not one category-siloed document per writer).
3. Increase the hot-write driver's writer count beyond 10 (changes the Two-Wave Evidence Model's specified mechanism, needs explicit re-approval, not a unilateral change).
4. Accept a higher near-duplicate rate for `TEL-LOCK` specifically (still well under the 15% gate threshold in aggregate) since 10 writers is a deliberate, specified constant from the contract, not an accident.

**DECIDED (2026-08-04):** 50-80 documents is the expected range for one incident run, not the 180-250 originally targeted. The 3,000,000-row operational workload carries the "volume" story on its own; the retrieval corpus represents the smaller set of meaningful observations one incident actually produces — inflating it would mean manufacturing evidence, which the live-data-only rule forbids regardless of how it's dressed up. The 10-writer contract stays exactly as specified (matches `DB_POOL_MAX_SIZE`); no finer sampling, no additional signal categories invented solely to hit a number.

**50-80 is an expected range, not a hard acceptance gate.** The real acceptance criteria for corpus adequacy are now behavioral, matching every other gate in this plan:
- Every incident phase and evidence category is represented in the admitted corpus.
- Exact, full-text, semantic, and fuzzy retrieval produce meaningfully different top candidates for the same query (already demonstrated at 103 old-mechanism documents earlier this session — real, not assumed).
- Fusion and reranking alter ordering for defensible, explainable reasons (already demonstrated: Cohere Rerank 3.5 promoted causally-relevant documents RRF had buried behind near-duplicates, at 103 documents).
- Wave B adds distinct, genuinely new validation evidence, not a restatement of Wave A.
- Near-duplicate rate stays bounded (this gate's own 15% threshold, or a number the real Evidence builder task recalibrates with real data).
- Citations and replay resolve to exact document versions (already proven by Gate 2).

**Honest framing for participant-facing content, not to be finessed away**: at 50-80 documents, PostgreSQL's planner may correctly choose sequential scans over HNSW index scans for some retrieval arms — this is the RIGHT choice at this corpus size, not a bug or a limitation to apologize for. State this plainly. Production-scale ANN index behavior belongs in the appendix as a documented "at scale, this changes" note, not folded into the core lab's numbers.

## Gate 6: Consolidated report and user go-ahead

**Result: PASSED with corrections — go-ahead granted 2026-08-04, conditional on a correction pass completed the same day**

All five prior gates passed against the real cluster. The consolidated report was delivered and the user granted go-ahead for implementation, but review of the report surfaced a mechanical contradiction in the plan that had to be fixed before any task was dispatched.

**The contradiction:** Gate 1 measured nine `statement_timeout` outcomes and one `pool_timeout`, while the plan's hold contract required ten tagged sessions blocked in PostgreSQL *and* at least two requests waiting outside the pool. Ten requests against a ten-slot pool cannot produce both — a request holding a slot is not waiting for one, so ten requests bound the observable maximum at nine blocked plus one `PoolTimeout`. Separately, Gate 1's three-second `statement_timeout` cannot sustain a ten-to-fifteen-second observation hold: every writer cancels itself before the hold begins.

**Corrections applied to `docs/superpowers/plans/2026-08-04-dat410-incident-scenario-redesign-plan.md` (2026-08-04, before Task A1):**

1. **Concurrency contract.** The driver launches 12–14 requests (`LAB_HOT_WRITE_REQUEST_COUNT`, default 12) against `DB_POOL_MAX_SIZE = 10`. Exactly 10 obtain connections and block on distinct rows; the remaining 2–4 never obtain a connection and return `PoolTimeout`. Two signals, two disjoint populations, never conflated.
2. **Timeout policy, three separate bounds.** Checkout 3s (`LAB_HOT_WRITE_CHECKOUT_TIMEOUT_SECONDS`), blocked-statement 30–45s (`LAB_HOT_WRITE_STATEMENT_TIMEOUT`, default `'40s'`), controller proving loop 90s (`max_attempt_seconds`). Gate 1's `'3s'` statement timeout is a property of the gate script and is a defect if it appears in shipped config.
3. **Drain is the honest ending.** The 10 blocked writers commit after the backfill releases its locks. Task B4 gained a seventh recovery assertion, `blocked_writers_drained`, requiring exactly `DB_POOL_MAX_SIZE` commits, zero `statement_timeout`, and at least one `pool_timeout`.
4. **Task B3's hold parameter renamed** `writer_count` → `expected_blocked_sessions`, with a test asserting 12 is unsatisfiable by construction. The old name invited passing the request count into a condition only the pool size can satisfy.
5. **Task A2's admission payload split** `writer_count` into `request_count` and `blocked_writer_count`, with a CHECK asserting `request_count > blocked_writer_count`. A single field cannot express that some requests never reached the database, which is the entire pool-exhaustion signal.
6. **Task C1's corpus bodies detached from Gate 5's sample.** Gate 5's `_gate5_build_sample_documents.py` encodes nine self-cancelled writers and "no hot-write request completed successfully" — an incident the corrected mechanism does not produce. Its per-signal structure carries forward; its numbers and outcome vocabulary do not.
7. **Task B1's `priority_tier` ownership** corrected from Task B2 to Task B1a.
8. **Gate 1's own step text** corrected: its Step 3 predicted ten `pool_timeout` outcomes, which was never what it measured, and its Step 2 code block is now labeled as the pre-fix draft carrying both HC defects.

**Still owed, carried into implementation rather than blocking it:**

- **Genuinely-new Wave B admission remains unproven** (Gate 3's own caveat). Gate 3 proved rebuilding does not spuriously demote unrelated evidence; it did not prove that admitting new Wave B evidence through the real follow-up contract keeps Wave A additive, because that contract does not exist as code yet. This is a stop/go gate before Labs, UI, infrastructure, and Workshop Studio work.
- **Real HTTP pool topology remains unproven at the endpoint level.** Gate 1 exercised the real `psycopg_pool.ConnectionPool` via `open_pool()`/`get_pool()`; it did not exercise FastAPI request handling, Pydantic models, per-request ASGI threading, or the `outcome`-as-200 error contract. Task B2 owes endpoint-level proof, and it is the second stop/go gate.

**Both owed items are Task A3 and Task B2 dependencies, and both are the designated stop/go points before any downstream phase begins.**
