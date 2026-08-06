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

1. **Concurrency contract.** The participant driver launches 12 requests (`LAB_HOT_WRITE_REQUEST_COUNT=12`) against `DB_POOL_MAX_SIZE = 10`. Exactly 10 obtain connections and block on distinct rows; the remaining two never obtain a connection and return `PoolTimeout`. Two signals, two disjoint populations, never conflated.
2. **Timeout policy, three separate bounds.** Checkout 3s (`LAB_HOT_WRITE_CHECKOUT_TIMEOUT_SECONDS`), blocked-statement 30–45s (`LAB_HOT_WRITE_STATEMENT_TIMEOUT`, default `'40s'`), controller proving loop 90s (`max_attempt_seconds`). Gate 1's `'3s'` statement timeout is a property of the gate script and is a defect if it appears in shipped config.
3. **Drain is the honest ending.** The 10 blocked writers commit after the backfill releases its locks. Task B4 gained a seventh recovery assertion, `blocked_writers_drained`, requiring exactly `DB_POOL_MAX_SIZE` commits and zero `statement_timeout`; the separate `pool_timeout_observed` assertion proves saturation.
4. **Task B3's hold parameter renamed** `writer_count` → `expected_blocked_sessions`, with a test asserting 12 is unsatisfiable by construction. The old name invited passing the request count into a condition only the pool size can satisfy.
5. **Task A2's admission payload split** `writer_count` into `request_count` and `blocked_writer_count`, with a CHECK asserting `request_count > blocked_writer_count`. A single field cannot express that some requests never reached the database, which is the entire pool-exhaustion signal.
6. **Task C1's corpus bodies detached from Gate 5's sample.** Gate 5's retired prototype encoded nine self-cancelled writers and "no hot-write request completed successfully" — an incident the corrected mechanism does not produce. Its per-signal structure carries forward; its numbers and outcome vocabulary do not. The prototype remains available in historical commit `c9ca891`, not in the participant lab directory.
7. **Task B1's `priority_tier` ownership** corrected from Task B2 to Task B1a.
8. **Gate 1's own step text** corrected: its Step 3 predicted ten `pool_timeout` outcomes, which was never what it measured, and its Step 2 code block is now labeled as the pre-fix draft carrying both HC defects.

**Still owed, carried into implementation rather than blocking it:**

- **Genuinely-new Wave B admission remains unproven** (Gate 3's own caveat). Gate 3 proved rebuilding does not spuriously demote unrelated evidence; it did not prove that admitting new Wave B evidence through the real follow-up contract keeps Wave A additive, because that contract does not exist as code yet. This is a stop/go gate before Labs, UI, infrastructure, and Workshop Studio work.
- **Real HTTP pool topology remains unproven at the endpoint level.** Gate 1 exercised the real `psycopg_pool.ConnectionPool` via `open_pool()`/`get_pool()`; it did not exercise FastAPI request handling, Pydantic models, per-request ASGI threading, or the `outcome`-as-200 error contract. Task B2 owes endpoint-level proof, and it is the second stop/go gate.

**Both owed items are Task A3 and Task B2 dependencies, and both are the designated stop/go points before any downstream phase begins.**

## B5 Implementation Acceptance: Query Regression Checkpoints

**Result: PASSED** (August 5, 2026, final implementation against Aurora PostgreSQL 18.3)

The full condition-based collision ran with the shipped B5 driver. The
23.108-second backfill reached the B3 proving condition, all seven B4 recovery
assertions passed, and the driver captured only the two Wave A checkpoints while
the supporting index was absent:

| Checkpoint | Scan | Execution time | Rows removed by filter | Buffers |
|---|---|---:|---:|---:|
| before `ANALYZE` | `Seq Scan` | 473.911ms | 2,400,000 | 47,062 |
| after `ANALYZE` | `Seq Scan` | 229.169ms | 2,400,000 | 47,059 |
| after participant-equivalent index | `Index Scan` | 2.581ms | 0 | 26 |

The post-index checkpoint was captured only after a separate,
participant-equivalent `CREATE INDEX ... (priority_tier, created_at DESC)`.
It did not exist during the Wave A run. The scan shapes, filter removals, and
buffer reduction are the acceptance signals; the timing values are this run's
reference observations, not thresholds.

## C4 Implementation Acceptance: Permanent corpus diversity gate (G-33)

**Result: PASSED on Aurora PostgreSQL 18.3, including a deliberate red-path
proof**

G-33 now measures the current, derived corpus without writing to the database.
It reconstructs each document body from current `retrieval.chunks`, requires
the six hardcoded signal types (`lock`, `pool`, `request`, `wal`, `meta`,
`plan`) and four hardcoded phases (`backfill`, `pool_exhaustion`, `recovery`,
`plan_regression`), then uses a server-side `pg_trgm` self-join to reject a
near-duplicate rate at or above 15%. An empty corpus returns `BLOCKED`, which
is the honest unbuilt state rather than a false pass.

A clean two-wave rehearsal on the dedicated Aurora PostgreSQL 18.3 `_test`
database produced:

| Measure | Result |
|---|---:|
| Current documents | 57 |
| Wave A / Wave B documents | 54 / 3 |
| Near-duplicate pairs | 99 / 1,596 |
| Near-duplicate rate | 6.20% |
| Required signal types | 6 / 6 |
| Required phases | 4 / 4 |

G-33 passed and G-32 separately confirmed the same Wave A / Wave B
additivity. Doctor reports the approved 50-80 document range as advisory
volume guidance only. Behavioral coverage and G-33's explicit diversity check,
not a target document count, are the acceptance contract.

The gate was also observed red. The disposable `_test` database received 20
copies of the most-similar document with distinct keys. G-33 failed at
489 near-duplicate pairs out of 2,926 (16.71%), naming the measured rate and
the 15% threshold. The database was fully reset, the schema and 3,000,000-row
workload were rebuilt, and a fresh Wave A / Wave B rehearsal completed after
the proof. No duplicate data or generated capture was retained.

## D1 Implementation Acceptance: Retrieval-arm differentiation on the new corpus

**Result: PASSED on Aurora PostgreSQL 18.3 with Bedrock embeddings, reranking,
and synthesis**

The permanent smoke path now makes the corpus-adequacy claim executable. It
uses four probes over the same capture-derived corpus:

| Retrieval signal | Probe result |
|---|---|
| Exact ID | `CHG-37AF2D23-01` |
| Full text | `LOCK-37AF2D23-01` |
| Semantic | `TEL-37AF2D23-R01` |
| Fuzzy ID | `CHG-37AF2D23-01` |

Exact and fuzzy intentionally agree on the named change. The full-text and
semantic probes rank different, relevant evidence, giving three distinct top
candidates across the four arms. The smoke assertion fails if a future corpus
loses that differentiation; it does not assume hybrid retrieval is always the
best result.

For the causal hybrid question, PostgreSQL RRF ranked:

```text
TEL-37AF2D23-R01, TEL-37AF2D23-M08, TEL-37AF2D23-M15,
TEL-37AF2D23-M01, TEL-37AF2D23-M04
```

With Cohere Rerank 3.5, the top five became:

```text
TEL-37AF2D23-M15, TEL-37AF2D23-M08, CHG-37AF2D23-02,
TEL-37AF2D23-P01, TEL-37AF2D23-M03
```

The order changed, while every candidate shared by the two responses retained
its PostgreSQL `rrf_score` and `final_score`; the separate `rerank_score`
remains only a post-fusion ordering signal.

`make smoke` completed with Bedrock synthesis and wrote ignored
`READINESS.md` for answer run `c37e283a-b874-4546-a8fa-985932384df6`. G-13
then compared the API's receipt panels, 63 graph edges, and 34 timeline events
with their `_verify_sql` replays and found zero mismatches.

## D2a Implementation Acceptance: Structured supervised action proposal

**Result: PASSED on Aurora PostgreSQL 18.3 with Bedrock Converse tool use**

The canonical `POST /v1/agent/answer` path now writes one append-only
`proof.action_proposals` record only after Aurora validates the answer's
citations. The model supplies structured index fields through the forced
`record_action_proposal` Converse tool call; application code validates every
identifier and renders the participant-reviewed DDL. The agent registry remains
at seven read/synthesis-only tools, and the agent has no DDL execution path.

The latest live proposal carried the measured key order:

```text
priority_tier asc nulls_last default
created_at desc nulls_first default
```

The added Bedrock proposal call plus proposal persistence measured **5.741s**.
This is an additional Lab 3 wait, not a final participant-path timing: the
rehearsal task must measure and publish the combined synthesis-plus-proposal
wait before facilitator copy quotes a total.

The stored `proposed_sql` was executed only inside a scratch transaction on the
dedicated `_test` database. Aurora's
`proof.observed_index_fingerprint()` returned exactly the stored
`proposed_fingerprint`, and the transaction rolled back, leaving the
participant's pre-remediation index absent.

The same live suite also exercised the non-canonical direct/Strands synthesis
path over fresh retrieval runs. It returned a cited answer without creating an
action proposal, preserving the boundary that only the canonical Lab 3 agent
run has a persisted `proof.agent_runs` parent and can write a supervised action
record.

Validation:

- Focused Python and agent contracts: 48 passed, 4 expected live skips, and 25
  subtests passed without a live test target.
- Live proposal suite: 4 passed in 47.51s, including canonical proposal
  emission, validated citations, pre-execution eligibility, and no proposal
  from direct/Strands synthesis.
- G-17 registry-drift gate: passed.
- G-34 retroactive-safety gate: passed against the live proposal with no
  execution row.

## F2 Implementation Acceptance: Source Build Budget and Bootstrap Lifecycle

**Result: PASSED for the measured source path; full cold Workshop Studio
rehearsal remains required**

Three clean cycles ran on the dedicated Aurora PostgreSQL 18.3
`db.r8g.2xlarge` test database. Each cycle rebuilt the operational workload
and then completed a fresh Wave A capture:

| Cycle | 3M workload rebuild | Wave A | Combined |
|---|---:|---:|---:|
| 1 | 33.86s | 87.52s | 121.38s |
| 2 | 34.17s | 81.55s | 115.72s |
| 3 | 33.49s | 81.70s | 115.19s |

The slowest observed source path was **121.38 seconds**. It is a real
Aurora-backed measurement, not a claim about a fully cold Workshop Studio
account: Code Editor package installation, CloudFormation resource startup,
and first-account Bedrock behavior were outside these runs and remain a
Workshop Studio rehearsal requirement.

The sibling Workshop Studio template currently sets
`BootstrapWaitCondition.Timeout` to **2,400 seconds**. That is **19.77 times**
the slowest measured source path, exceeding the Task F2 two-times requirement;
no timeout increase is justified by the measurement.

The bootstrap custom resource is **Create-only**. Its handler immediately
acknowledges any CloudFormation Update request and does not rerun
`make schema` or `make prepare-workload`. An update is therefore not a valid
way to rebuild a participant substrate: use a new stack or the documented
reset/recreate procedure. This is a lifecycle constraint to be verified again
in the final Workshop Studio rehearsal, not a timeout defect.

## G1 Rehearsal: Participant Path on the Final Two-Wave Contract

**Result: PASSED for the runtime participant path; frontend visual freeze
remains a G3 release check**

On August 5, 2026, a fresh rehearsal ran against
`dat410_review_remediation_test` on Aurora PostgreSQL 18.3
`db.r8g.2xlarge`. Wave A admitted `CAP-889D1D34`
(`96f63d96-bdea-48fb-a402-5de1889d1d34`) and Wave B admitted
`CAP-33E2F05A` (`b121e4fd-c156-457b-afc2-4c7333e2f05a`) under the same
incident.

| Action | Measured observation |
|---|---|
| Wave A | 78.980s wall-clock, including 33.840s local workload preparation; 54 documents from 297 activity rows, 1,728 lock rows, and 270 blocker-chain rows |
| Lab 3 | `POST /v1/agent/answer` completed in 25.832s wall-clock and recorded 25.338s answer latency; retrieval run `e7c23afc-5183-4c23-8446-d660155d6dbb` produced proposal `51d671b2-31e4-476d-9f40-d4cfbca6393a` with eight citations |
| Participant index action | The agent/app identity correctly failed with `must be owner of table orders`; a direct `workshop_participant` connection created the stored index in 1.503s |
| Wave B | 21.228s wall-clock; additive corpus shape was 54 Wave A + 3 Wave B = 57 documents |

The participant-visible plan change was real: Wave A recorded sequential scans
at 477.382ms / 47,062 buffers before `ANALYZE` and 252.115ms / 47,059
buffers after it. Wave B recorded an `Index Scan` at 2.794ms, 26 buffers, and
zero rows removed by filter.

Supervision proof passed without retroactive mutation:

```text
pre_execution_eligible: true
pre_execution_reasons: []
post_execution_validated: true
post_execution_reasons: []
```

The pre-execution values were byte-identical before and after Wave B. The
original Wave A replay remained isolated after Wave B: 31 graph nodes, 58
edges, 31 timeline events, eight citations, and zero Wave B records. `make
doctor` passed against the final two-wave corpus.

One participant-exercise mismatch surfaced during the rehearsal. Traversal
returns a deduplicated spanning tree, so it cannot expose both the direct
incident-to-change edge and the alternate lock-to-change edge for one change.
The checkpoint now requires the three relations available from traversal and
uses source comparison to verify the full relationship set, including
`blocked_by_change`. The corrected Lab 2, Lab 3, and Wave B checkpoints pass.

The frontend was intentionally not running during this source-path rehearsal.
No claim is made here about a rendered screen; the G3 release freeze must
perform the frontend build and visual/API verification against the final
Workshop Studio path.

## G2 Rehearsal: Failure Injection And Facilitator Recovery

**Result: PASSED on Aurora PostgreSQL 18.3.** The observed symptoms and
bounded recoveries are published in
[`docs/facilitator-recovery-runbook.md`](../../facilitator-recovery-runbook.md).

The injected controller failures retained no stale tagged sessions or
unadmitted evidence:

| Injection | Observed behavior | Recovery result |
|---|---|---|
| Orchestrator `SIGKILL` during the proven hold | Client exited `137` after ten tagged blocked writers and two pool waiters | `make prepare-workload` restored the 3M-row substrate; the pool returned to 10/10 available |
| Seven hot-write requests | Bounded prove loop stopped with `only 7 of 10 tagged sessions were ever blocked on the backfill` | No evidence or tagged session residue; default 12-request configuration remained rerunnable |
| CloudWatch unavailable | Wave A `CAP-00C916C9` completed with `cloudwatch_status: unavailable`, 54 documents, and zero CloudWatch rows | No recovery required; PostgreSQL and pool evidence remained ready |
| Wave B without Wave A | Exited `1` with `Wave B requires Lab 1's admitted Wave A evidence; run Lab 1 first` | Left zero evidence and execution rows in the empty target |

The supervised-action cases were also exercised against Wave A
`CAP-00C916C9`:

| Injection | Observed behavior |
|---|---|
| Reversed index keys | Execution `bc81cd25-1262-4683-99a9-968313682dac` was persisted with `fingerprint_matches = false`; no Wave B capture was admitted |
| Missing index | A failed append-only execution was recorded, then the runner named the missing participant-created index and instructed the participant to correct the DDL |
| Correct index and Wave B | `workshop_participant` created the rendered composite index; Wave B `CAP-66AB0602` admitted three new documents and produced 57 current documents with zero drift |
| Repeated Wave B | The saved payload replayed with `idempotent_replay: true`; 57 documents and embeddings were retained, with zero documents indexed and all 57 embeddings reused |
| Repeated participant DDL | PostgreSQL returned `relation "idx_orders_priority_tier_created_at" already exists`; the matching ready index was retained |
| Strands answer | `POST /v1/agent/strands/answer` returned `200` and cited answer run `eb2b049f-d84c-4659-9d3b-b2d15ca6948e`; its supervision receipt and `proof.action_proposals` count were both empty |

The three database identities remained distinct on the real provisioned
database:

- `workshop_app` successfully ran an order `UPDATE`, but `CREATE INDEX`,
  `DROP TABLE`, and `TRUNCATE` were denied (`42501`). It also had no `proof`
  schema access, so it could not insert an action execution.
- `workshop_participant` created the lab index but could not update a persisted
  execution receipt.
- The Hybrid Retrieval Agent has no database login or write-capable tool. The
  owner-side canonical answer and Wave B boundaries record proposal and
  execution facts without granting the agent or app identity direct proof
  mutation.

The G2 rehearsal leaves a real Wave A, a matching Wave B, the expected failed
and successful append-only execution rows, and a no-proposal Strands answer in
the disposable test database for G3 replay. F1's PI-disabled or
`pi:GetResourceMetrics`-revoked end-to-end proof and G3's final source/UI
freeze remain owed.
