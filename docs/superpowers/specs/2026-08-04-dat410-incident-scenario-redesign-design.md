# DAT410 Incident Scenario Redesign — Design

## Objective

Build one L400 Aurora PostgreSQL incident with four measured phases, presented through an
L300 narrative accessible to every persona. It is one failed **online schema and data
migration**, not four separate incidents.

**Terminology note:** "migration" here always means an application-level online schema and
data migration (an `ADD COLUMN` + backfill, of the kind an app team ships in a release) — not
an Aurora engine-version migration/upgrade. Use "online schema and data migration" or "the
migration" (never bare "upgrade") throughout participant-facing content to avoid confusion
with Aurora's own version-upgrade feature.

## Background

The current Lab 1 (`labs/incident/run_live_workshop.py`, `capture_observability.py`) induces
a single lock-contention incident (non-concurrent `CREATE INDEX` on a 25,000-row table,
blocking six synthetic Python-thread writers) and depends on AWS Performance Insights to
identify the blocking statement. Live testing against the real Aurora cluster
(`agenticretrievalcorestack-aurorapostgresretrievalc-rxrppbdex0nu`, `db.r8g.2xlarge`, Aurora
PostgreSQL 18.3) proved this dependency structurally broken: PI's Active Session History
never samples `idle in transaction` backends, and the current scenario's blocker sits idle
after its (sub-second) `CREATE INDEX` completes. No PI query variant — different dimensions,
different wait budgets — can surface it. Full root-cause chain: project memory
`database-insights-removal-decided.md`.

Fixing that dependency in isolation would have left the rest of the scenario unchanged: a
25,000-row table, a single evidence "kind," and a corpus small enough that full-text,
semantic, fuzzy, RRF, and rerank arms have little room to visibly disagree. The project owner
asked for a holistic re-evaluation instead — real, larger-scale data; a scenario grounded in
common production database operations (not generic document content); deterministic behavior
for ~100 concurrent participants; and a compelling narrative that still fits inside a hard
60-minute, single-session time budget.

This document is the resulting design, reconciling three rounds of iteration (this session's
own analysis, an independent review from a second agent (Codex), and the project owner's
corrections to both) into one final, user-approved contract. The authoritative requirements
text is preserved verbatim in project memory `dat410-revised-incident-scenario-contract.md`;
this document adds the architecture, component boundaries, data flow, error handling, and
testing sections around that contract.

## Global Constraints

- Live-data-only: zero fixtures, mocks, dummy, offline, or canned records anywhere in the
  participant path, ever (`AGENTS.md`, `CLAUDE.md`). Every searchable document must be built
  from genuinely measured observations of this run.
- Participant-facing incident time (induce → collect → admit) must stay under a 5–8 minute
  ceiling. This is the redesign's hardest constraint — the current session is a 60-minute
  single sitting, and retrieval (Labs 2–4) is the actual point of the workshop.
- Acceptance is behavioral, not duration-based: specific proven states
  (`pg_blocking_pids()` identifies the backfill; all 10 pool connections blocked; requests
  queue/timeout; full recovery; correct post-index plan; retrieval/citations/replay use only
  current-run evidence), not "took N seconds."
- The operational workload table is not the retrieval corpus. `workbench_lab.orders` (now
  3,000,000 rows, up from 25,000) never enters `casework`/`retrieval`/`proof`. The searchable
  corpus targets a 180–250 document range (not an exact number), built from genuinely
  distinct signal types — lock/blocking-state transitions, pool saturation/recovery, request
  latency/timeout aggregates, WAL/statement deltas, backfill/recovery/index metadata, and the
  three query-plan checkpoints — never from denser time-sampling of the same signal.
  CloudWatch metrics do not count toward this range (best-effort supplemental only).
- No new fragile external dependency may replace the one being removed. Reuse the existing
  FastAPI connection pool (`backend/app/db.py`, `DB_POOL_MAX_SIZE=10`) for pool exhaustion —
  do not add RDS Proxy, PgBouncer, or any new pooling infrastructure. Do not gate readiness on
  CloudWatch or any AWS console-side telemetry.
- Preserve the existing optional RLS/masking lab and AgentCore lab unless this implementation
  directly requires a compatible update to either.
- Aurora PostgreSQL owns ranking; this redesign is about evidence generation shape, not about
  moving ranking logic anywhere else.

## Approaches Considered

**A. Narrow fix — swap the PI query for a different PI query or a longer wait.** Rejected:
proven empirically that no PI query (any dimension, any wait budget) can surface an
idle-in-transaction backend. Not fixable without changing what the blocker session does while
holding the lock.

**B. Scale up the existing single incident (bigger `CREATE INDEX`, same story).** Considered
and partially adopted (bigger row counts, still one incident), but abandoned as the *sole*
lever: a single lock-contention event, however large, still produces one evidence "kind." It
does not address corpus diversity for retrieval differentiation, and non-concurrent
`CREATE INDEX` on this instance class needs ~60–100M rows to hold a lock for ~60s purely from
build time — an impractical per-participant bootstrap at real event scale.

**C. One migration, four causally-chained, measured phases (chosen).** A single failed
online schema and data migration (unbatched backfill) that cascades through lock contention → connection-pool
exhaustion → query-plan regression. One coherent root cause, four genuinely different
evidence signatures (lock/transaction state, pool/request telemetry, WAL/row-churn
signals, query-plan output), each mapped to a distinct persona entry point (app engineer,
DBA, data engineer, data scientist). Chosen because it satisfies corpus diversity without
scaling any single mechanism to an impractical size, and because "one bad migration causes a
cascading incident" is both a widely-recognized, production-representative failure pattern —
measured and reproduced live in this lab, not an incident that occurred in an actual
production system — and a natural fit for the existing agent
traversal/decompose/compare/synthesize story.

## Architecture

```
Pre-session (Workshop Studio provisioning, not participant time)
  └─ Bootstrap: 5,000 customers + 3,000,000 orders → workbench_lab schema

Participant-facing Lab 1 (target: 5–8 min ceiling)
  ┌─ Phase 1: Migration
  │    ADD COLUMN priority_tier (committed separately, no held lock)
  │    → unbatched UPDATE backfill, explicit transaction, left open (measured: 21.7s)
  │
  ├─ Phase 2: Collision + Proven Hold
  │    10 tagged API writes (existing FastAPI pool) hit hot rows the backfill touched
  │    Orchestrator polls pool stats + pg_stat_activity/pg_locks every 250ms
  │    On 3 consecutive samples proving exhaustion → hold 10–15s, sampling continuously
  │    → commit
  │
  ├─ Phase 3: Recovery
  │    Verify: zero waiters, zero blocked sessions, connections returned,
  │            ≥1 recorded PoolTimeout, one fresh write succeeds
  │
  └─ Phase 4: Query Regression
       Named query, EXPLAIN (ANALYZE, BUFFERS) at 3 checkpoints:
       before ANALYZE → after ANALYZE → after missing index

Evidence build (from measured phases 1–4 only, state-change/interval-boundary documents,
                 not one document per 250ms poll)
  → 180–250 searchable documents → casework/retrieval/proof (unchanged admission path)

Labs 2–4 (unchanged): hybrid retrieval, agent tools, citations, replay
```

## Components

**Bootstrap (`labs/incident/prepare_workload.py`, `run_live_workshop.py::_create_lab_workload`)**
— Modify: row count constant `LAB_ROWS` 25,000 → 3,000,000. No structural change; this is
already a full `DROP SCHEMA ... CASCADE` + recreate, already idempotent. Reclassified as
pre-session provisioning in all timing/documentation language — it does not count against
the participant-facing 5–8 minute ceiling.

**Migration driver (new, in `run_live_workshop.py` or a new `labs/incident/migration.py`)** —
Owns Phase 1: commits `ADD COLUMN priority_tier int` as its own statement (no explicit
transaction spanning both the `ADD COLUMN` and the backfill — this is what avoids retaining
the `AccessExclusiveLock` during the long backfill), then opens one explicit transaction
running the single unbatched `UPDATE ... SET priority_tier = ...` over all 3M rows, and holds
that transaction open (does not commit) until Phase 3 explicitly commits it. Records the
backfill session's PID for later correlation.

**Hot-write driver (new: a lab-only FastAPI endpoint + a driver script/thread pool)** — Owns
Phase 2's collision mechanism. The endpoint performs a real write through
`backend/app/db.py`'s existing pool (`get_conn`/`get_dict_conn` pattern, unchanged) against a
specific, predetermined "hot" `order_id`. **Confirmed empirically** (see Testing section's
"Measured Baseline — New 3M-Row Mechanism"): an unbatched `UPDATE` does scan in ascending
physical/heap order on a freshly-bulk-loaded table — 10 concurrent writers against the lowest
10 `order_id`s all genuinely blocked while the backfill held its transaction open. "Lowest
IDs" is a safe, verified hot-row selection rule; the `SELECT ... FOR UPDATE NOWAIT`-polling
fallback originally proposed here is not needed. Every transaction issued through this
endpoint runs `SET LOCAL application_name = 'workbench-lab-api-hot-write'` immediately after
checkout, making it unambiguously identifiable in `pg_stat_activity`. The driver launches 10
concurrent calls against 10 distinct hot IDs, then continuously issues at least 2 more to keep
`requests_waiting` non-zero.

**Two implementation traps found and fixed while running Gate 1** (full detail in
`docs/superpowers/specs/2026-08-04-dat410-gate-results.md`), both mandatory for the real
endpoint, not just the gate script that discovered them:
1. `pool.connection(timeout=3.0)` bounds only the checkout wait. A writer that gets a real
   connection before the pool saturates has no bound on how long it then waits on the actual
   row lock — the real endpoint MUST also set a statement-level timeout, not rely on checkout
   timeout alone.
2. The pool's connections run `autocommit=True` (`backend/app/db.py`'s `_configure_connection`).
   `SET LOCAL application_name` and `SET LOCAL statement_timeout` MUST be issued inside the
   same explicit `with conn.transaction():` block as the actual write — issuing either as a
   separate bare `conn.execute()` call silently ends its own implicit transaction first,
   resetting `SET LOCAL`'s effect to nothing before the write runs in a fresh transaction.
   Verified live: this exact mistake hung a real hot-write session on `Lock:Transactionid`
   for 50+ seconds with no timeout ever firing.

**Pool-status endpoint (new, lab-only)** — A `GET` endpoint that calls `get_pool().get_stats()`
and returns the dict directly, performing no database checkout itself (must not itself
consume a pool slot while checking pool exhaustion, which would corrupt the measurement).

**Hold controller (new, in the migration/orchestration driver)** — Polls the pool-status
endpoint and a `pg_stat_activity`/`pg_locks` query (joined via
`pg_blocking_pids(pid) @> ARRAY[backfill_pid]`) every 250ms. Declares the state proven only
after 3 consecutive samples simultaneously satisfying: `pool_size = pool_max = 10`,
`pool_available = 0`, `requests_waiting >= 2`, and all 10 tagged sessions showing
`wait_event_type = 'Lock'` with the backfill PID in their `pg_blocking_pids()`. This is
condition-based waiting (poll-until-proven), not a fixed sleep — the same category of fix
already validated by this redesign's own root-cause investigation into why fixed timeouts
against external systems are fragile. Once proven, holds for 10–15 seconds while continuing
to sample every signal listed in the contract (pool, lock, latency, timeout, WAL, statement).

**Timeout policy** — Lab hot-write requests checkout with `pool.connection(timeout=3.0)`
(confirmed real, supported `psycopg_pool` signature); a `psycopg_pool.PoolTimeout` raised by
a queued request is caught explicitly and recorded as a measured evidence event, not treated
as a driver failure. The backfill transaction and any blocked SQL get a longer safety
timeout (matching the existing `SET statement_timeout` pattern already used in
`_hold_unsafe_index`).

**Recovery verifier (new, in the orchestration driver)** — After commit, asserts: zero pool
waiters, zero backfill-blocked sessions, all previously-checked-out connections returned
(`pool_available` restored to `pool_size`), at least one `PoolTimeout` was recorded during the
hold, and one fresh hot-write request succeeds. Any assertion failing raises
`LiveWorkshopError` (existing exception class), matching the existing fail-closed pattern —
no fixture/fallback substitution.

**Query regression driver (new, split across Lab 1 and Lab 4 per the Two-Wave Evidence Model
below — NOT a single inline step)** — Runs one exact, named query (finalized in the
implementation plan; the design's reference measurement used `SELECT order_id, customer_id,
created_at FROM workbench_lab.orders WHERE priority_tier = :n ORDER BY created_at DESC
LIMIT 20`) through `EXPLAIN (ANALYZE, BUFFERS)`. **Lab 1** captures only the first two
checkpoints — before `ANALYZE` and after `ANALYZE` (still no index) — as part of Wave A; the
supporting index is deliberately NOT created during Lab 1. **Lab 4** is where the participant
executes the recommended `CREATE INDEX` DDL themselves (reviewed from the Lab 3 agent's
recommendation, not auto-applied), and the driver then captures the third checkpoint
(after the index) as part of Wave B. Every checkpoint captures plan node type, estimated vs.
actual rows, rows removed by filter, buffers, planning time, and execution time. If
application traffic is still active during Lab 4's remediation step in the final
implementation, use and measure `CREATE INDEX CONCURRENTLY` and note the measurement;
otherwise the plain `CREATE INDEX` used in this lab is documented as a controlled-lab repair,
not an online-safe production recommendation.

The three captured checkpoints (two from Lab 1, one from Lab 4) exist to support a specific
participant reasoning sequence spanning both labs, not just to display three timings. The
evidence documents and any Lab-3/Lab-4-facing exercise built from this driver's output must
let a participant:
1. Compare estimated vs. actual row counts before and after `ANALYZE` (the estimate is what
   changes; the actual row count captured in each plan is the ground truth against it).
2. Recognize that corrected statistics do not create a missing access path — `ANALYZE`
   changing the estimate does not, by itself, change the plan's scan type in this case
   (measured: seq scan before and after, 225ms → 219ms).
3. Select the appropriate composite or partial index from the query's actual predicate
   (`WHERE priority_tier = :n`) and `ORDER BY` clause (`created_at DESC`) — not simply apply a
   pre-supplied index definition. The reference index
   (`priority_tier, created_at DESC`) is the answer key, not something participants are handed
   upfront.
4. Prove the improvement using plan nodes, buffers, rows removed, and execution time together
   (seq scan → index scan; buffers read dropping; rows removed by filter going from millions
   to zero; 219ms → 1.5ms) — not execution time alone, since time alone doesn't demonstrate
   *why* the index fixed it.

**CloudWatch collector (`labs/incident/capture_observability.py::_cloudwatch_samples`,
existing, minimally modified)** — Kept, but demoted to best-effort: wrapped so a collection
failure or a not-yet-published datapoint records an "unavailable" status in receipt metadata
rather than raising and blocking the pipeline. Collected in parallel with (not blocking) the
admission/embedding steps. Performance Insights / Database Insights (`_wait_for_database_
insights` and all PI-specific code in `capture_observability.py`) is removed entirely — no
role in the new design.

**Evidence builder (`run_live_workshop.py::_telemetry_documents`, modified)** — Target:
**180–250 searchable documents**, a range rather than an exact number, produced from
genuinely distinct signal types rather than denser time-sampling of the same four phases.
CloudWatch metrics do not count toward this minimum (they stay best-effort supplemental
evidence per the CloudWatch section below, and their availability is not guaranteed).

The critical design rule, driving every series below: **the hold controller's 250ms poll
loop is a control mechanism, not a document-generation trigger.** Polling every 250ms for up
to 15 seconds would be ~60 samples — turning every one into a searchable document would
recreate exactly the near-duplicate-snapshot problem the current 103-document corpus already
shows early signs of (six near-identical `TEL-...-A0xx` activity documents burying the causal
chain in RRF, before rerank correctly fixes it — see the measured retrieval-quality baseline
in Testing). Raw telemetry from every poll is still persisted (matching the existing
`casework.*_samples` pattern — nothing is lost), but a searchable document is created only on
a **state change** (e.g., `pool_available` transitions 1→0, a new tagged session enters
`wait_event_type='Lock'`, a `PoolTimeout` fires) or a **meaningful interval boundary** (e.g.,
one document per second of the proven hold, not one per 250ms poll), never on every poll
tick.

Series, replacing the current `A`/`L`/`B`/`S`/`C`/`P`/`R` letters with signal-type-organized
documents (exact external-key letters finalized in the implementation plan, alongside the
existing `TEL-<run-suffix>-*` scheme):
- **Lock and blocking-state transitions** — retargets the existing `A`/`L`/`B` sourcing
  pattern (`pg_stat_activity`/`pg_locks`/`pg_blocking_pids`) at the new backfill/hot-write
  collision, but emits a document per *transition* (e.g., a hot-write session entering or
  leaving a lock wait), not per poll.
- **Pool saturation and recovery snapshots** — new series, sourced from `get_pool().get_stats()`
  plus the correlated `pg_stat_activity` state; documents at the proven-exhaustion transition,
  at fixed points through the hold, and at the recovery transition — not at every 250ms sample.
- **Request latency and timeout aggregates** — new series; one document per distinct outcome
  class (e.g., "N requests completed in Xms," "M requests raised `PoolTimeout`"), not one per
  request.
- **WAL and statement deltas** — retargets the existing `S` (`pg_stat_statements`) sourcing
  pattern at the backfill's actual measured WAL volume and row-version churn (only labeled
  "WAL pressure" if a measured latency/throughput degradation accompanies it, per the
  terminology note above).
- **Backfill, recovery, and index metadata** — retargets the existing `R` (repair
  verification) sourcing pattern at the new commit/recovery/index-creation events.
- **The three query-plan checkpoints** — one document per `EXPLAIN (ANALYZE, BUFFERS)`
  checkpoint (before `ANALYZE`, after `ANALYZE`, after the index): exactly 3, fixed.

The `P` (Performance Insights) series is deleted outright — no role in the new design.

This is a change from the current codebase's pattern (`OBSERVATION_COUNT = 30` fixed samples,
one document per sample, per `_telemetry_documents`) to a state-change/interval-boundary
pattern — a real implementation difference the plan must design deliberately, not inherit
mechanically from the existing loop structure.

## Participant-Facing Framing

The lab titles and terminology below correct a real framing problem: the mechanically
accurate names from earlier in this document ("Cause, fix, and admit the incident", "Prove
and replay", "incident agent") make the session read as an incident-response lab with
retrieval bolted on afterward. The actual subject of this L400 session is how Aurora
PostgreSQL retrieves, combines, ranks, relates, cites, versions, and replays evolving
evidence — the incident is real, but it exists to generate a complex, evolving corpus, not
as the thing being taught. Participant-facing titles and copy must reflect that ordering.

**Lab titles** (replacing today's Workshop Studio titles —
`content/20-reproduce-write-stall/index.en.md`, `30-build-hybrid-retrieval/index.en.md`,
`40-build-incident-agent/index.en.md`, `50-prove-and-replay/index.en.md` — directory slugs
are internal and do not need to change unless a participant sees them):

1. **Lab 1: Capture and admit live evidence** — run the controlled Aurora scenario, capture
   its signals, and create the first searchable evidence corpus (Wave A).
2. **Lab 2: Build hybrid retrieval in SQL** — implement exact, full-text, semantic, and fuzzy
   retrieval, then combine them with filtering, RRF, and reranking.
3. **Lab 3: Build the hybrid retrieval agent** — ground a read-only agent in retrieval,
   relationship traversal, source comparison, and citations.
4. **Lab 4: Validate, prove, and replay** — apply the agent's recommendation, admit the new
   evidence (Wave B), compare before-and-after results, and replay the persisted runs.

Participant arc: **generate evidence → build retrieval → ground an agent → validate with new
evidence.**

**Agent naming**: the participant-facing name is **Hybrid Retrieval Agent** (distinct from
and complementary to the application's own name, "Hybrid Retrieval Workbench" —
`backend/app/config.py`'s `APP_DISPLAY_NAME` default, unchanged). Describe it as a
**read-only database-evidence agent**, not a generic chatbot — this description is accurate
today (all 7 registered tools in `agent/registry.py` are read/synthesis only, none write, per
the Two-Wave Evidence Model section above) and should stay accurate as new tools are ever
added to the registry.

**Terminology replacements** in participant-facing copy (content pages, guide text, UI
strings if any exist — this session found none in the current frontend, so this is primarily
a `docs/`- and Workshop Studio `content/`-scoped change, not a code change):
| Old | New |
|---|---|
| "incident diagnosis" | "evidence-backed finding" |
| "remediation delta" | "validation evidence" |
| "incident agent" | "hybrid retrieval agent" |
| "remediate" | "apply and validate the recommendation" |

Internal package, schema, and identifier names (`labs/incident/`, `casework.*`,
`INC-<run-suffix>`, `CHG-<run-suffix>-*`, etc.) do NOT need mechanical renaming under this
change — the rule is participant-facing language only, matching this project's existing
practice of keeping ticket-style internal IDs stable (see `live-data-and-naming-assessment`
memory: real-looking names break Law 6's naming discipline; ticket-style IDs are intentional).

## Two-Wave Evidence Model

**Diagnose before remediation, without holding the incident's blocking transaction open
across labs.** An earlier draft of this design considered stretching the backfill's hold
across Labs 1–3 so participants would only see pre-remediation evidence. Rejected: that would
make the retrieval and agent APIs themselves unavailable (they share the same connection pool
the backfill is saturating) and leaves a 3-million-row transaction open for however long Labs
1–3 actually take a room of participants — unbounded, not the 10–15s the hold controller
proves and releases.

**The correct mechanism: commit immediately (as already designed), then stage what gets
*admitted*, not the transaction's lifetime.** Wave A is admitted at the end of Lab 1 and
contains only diagnostic evidence — the lock/pool/timeout/WAL signals from Phase 1–3, plus
the before-`ANALYZE` and after-`ANALYZE` (still no index) plan checkpoints from Phase 4. The
missing index is not created during Lab 1 at all (a change from the Components section's
earlier framing of the query regression driver creating the index inline) — creating it is
Lab 4's participant action, not something the orchestrator does automatically. Because
`casework.admit_evidence`/`retrieval.*` only ever contain what has been explicitly admitted,
the Lab 3 agent genuinely cannot see the post-index plan or any remediation evidence — this
is source truth, not an artificial filter layered on top of a tool call. No agent tool queries
`workbench_lab` or live catalogs directly (confirmed: all 7 registered tools in
`agent/registry.py` — `decompose_question`, `search_evidence`, `follow_evidence_links`,
`compare_sources`, `explain_ranking`, `synthesize_cited_answer`, `answer_with_citations` — go
through the canonical `retrieval.*`/`casework.*` SQL functions only, none write, none bypass
admission), so this constraint holds without new access-control code.

**Wave B is genuinely additive, not a replacement.** In Lab 4, the participant reviews the
Lab 3 agent's cited recommendation, then executes the recommended `CREATE INDEX` DDL
themselves in Code Editor (the agent recommends; it has no DDL privilege and no execution
path — already true today, not a new constraint to build). The orchestrator captures the
post-index plan, verifies the index, and admits Wave B through a **new follow-up admission
contract** — a second, later call against the same incident/run identity, with its own
admission ID, its own bounded observation window, and its own receipt. Wave B does not
replace or tombstone Wave A:
- Before-`ANALYZE`, after-`ANALYZE`, and post-index plans remain three separate, permanently
  retrievable observations so later agent runs can compare all three, not just see the latest.
- Wave B adds new evidence kinds — a remediation change record, an index-verification record,
  the post-index plan, and a `validates`-style relationship connecting Wave B's remediation
  back to Wave A's diagnosis — it does not mark any Wave A record obsolete.
- Versioning (`is_current`/`document_version_id`, already in `sql/01_schema.sql`) is reserved
  for genuinely mutable facts, such as the incident's own status moving from `investigating`
  to `resolved` — not applied to the plan/telemetry observations themselves, which are each a
  permanent, distinct historical fact.

**Replay implications, verified against the actual code, not assumed:**
- The core citation/receipt replay path (`explain_ranking_impl` in `backend/app/agent.py`,
  backing `/v1/tools/explain-ranking` and `/v1/runs/{run_id}`) reads `proof.retrieval_candidates`
  filtered by the stored `run_id` — a persisted snapshot written at run time. A Lab 3 run's
  replay is already pinned to Wave A's candidates by construction; Wave B's later admission
  cannot retroactively change what an already-completed run's receipt shows. No new pinning
  code needed for this path.
- **Open question for the implementation plan, not yet resolved**: `run_graph`
  (`backend/app/insights.py`, backing `/v1/runs/{run_id}/graph`) reads a persisted seed set
  from `proof.retrieval_candidates` but then re-runs `retrieval.traverse_evidence()` live for
  the relationship expansion. If a participant reopens a Lab 3 run's graph view after Wave B
  is admitted, this path could surface Wave B nodes/edges that did not exist when the run
  happened. Decide explicitly whether this is desired ("show how the case evolved") or must
  be pinned to Wave A only for genuine replay fidelity — do not let this default silently
  either way.
- An explicit `as_of_admission_id` search parameter (letting any tool pin results to a named
  admission wave) is a reasonable production extension but is explicitly NOT needed for the
  core workshop and would add avoidable complexity — do not build it as part of this redesign.

## Data Flow

1. Workshop Studio provisioning bootstraps `workbench_lab.customers` (5,000) and
   `workbench_lab.orders` (3,000,000). Zero rows in `casework`/`retrieval`/`proof`.
2. **Lab 1 — Induce and capture.** Participant runs the orchestrator. Migration driver
   commits `ADD COLUMN`, opens the backfill transaction, runs the unbatched `UPDATE`, leaves
   it open. Hot-write driver launches 10+ tagged API writes through the real pool against
   predetermined hot rows. Hold controller polls pool stats + PostgreSQL state every 250ms;
   on 3 consecutive proven samples, holds 10–15s sampling every signal; then triggers commit.
   Recovery verifier asserts the 5 post-commit conditions. Query regression driver captures
   the before-`ANALYZE` and after-`ANALYZE` plan checkpoints only — the supporting index is
   NOT created here. CloudWatch collection runs in parallel (best-effort, non-blocking).
   Evidence builder converts every measured signal into Wave A telemetry documents (180–250
   range, state-change/interval-boundary, not per-poll). Wave A is admitted, embedded, and its
   receipt published. The evidence store now contains only pre-remediation, diagnostic
   evidence — the index does not exist in the database, and no post-index plan exists in
   `casework`/`retrieval`.
3. **Lab 2 — Investigate with SQL retrieval.** Participant searches the captured lock, pool,
   timeout, WAL, and plan evidence directly via SQL in Code Editor, using the existing
   exact/FTS/vector/fuzzy/RRF/rerank mechanics unchanged. Establishes from the evidence itself
   that `ANALYZE` did not resolve the regression (the after-`ANALYZE` plan is still a seq
   scan) — no code change from today's retrieval mechanics, only the underlying evidence
   changes.
4. **Lab 3 — Build the incident agent.** The agent (via the existing 7-tool registry,
   unchanged) produces a cited diagnosis from Wave A evidence only, and recommends the
   missing index plus batched-backfill as future practice. It cannot see or reference a
   post-index result, because none exists yet in `retrieval.*` — source truth, not a filter.
5. **Lab 4 — Remediate and prove.** The participant reviews the agent's recommendation, then
   executes the recommended `CREATE INDEX` DDL themselves in Code Editor (the agent never
   gets DDL privilege or an execution path). The orchestrator captures the post-index plan,
   verifies the index, and admits Wave B — a new follow-up admission contract, additive to
   Wave A, with its own admission ID, observation window, and receipt — embeds the small
   delta, publishes the remediation receipt, and the participant replays the original Lab 3
   investigation (unchanged, still showing Wave A only) alongside the new remediation proof.

## Error Handling

- Every new failure mode follows the existing `LiveWorkshopError` pattern (raise, print
  `LIVE WORKSHOP FAILED: ...`, no receipt published, no silent fallback). No new exception
  hierarchy needed.
- `psycopg_pool.PoolTimeout` on a lab hot-write request is an **expected, measured** event
  during the hold — it must be caught at the call site and recorded as evidence, not allowed
  to propagate as an unhandled driver error.
- If the hold controller's 3-consecutive-sample condition never proves within a bounded
  overall attempt window (exact bound set in the implementation plan — this is the one place
  a numeric ceiling still matters, to prevent an unbounded retry loop if the mechanism is
  broken), it raises `LiveWorkshopError` with a message identifying which specific condition
  never held (e.g., "pool_available stayed non-zero" vs. "only 7 of 10 tagged sessions
  blocked") — diagnosable, not opaque.
- CloudWatch collection failures or missing datapoints are caught and recorded as
  `"cloudwatch_status": "unavailable"` in receipt metadata; they never raise
  `LiveWorkshopError` and never block the pipeline.
- The recovery verifier's five assertions each fail independently and identifiably (not one
  bundled check) so a partial-recovery bug is diagnosable from the error message alone.

## Testing

- `backend/tests/test_incident_lab.py` (existing) gets new test classes mirroring the
  existing pattern (`_apply_schema`, `TEST_DATABASE_URL`, `ALLOW_TEST_DATABASE_RESET=1`):
  hold-controller condition detection (unit-testable against a mocked/small pool + synthetic
  `pg_stat_activity` rows, not requiring a real 3M-row table for every test run), recovery
  verifier's five assertions (each independently triggerable/failable), and the query
  regression driver's three-checkpoint capture (testable at small scale — the *mechanism*
  doesn't require 3M rows, only the reference timing numbers do).
- One live, real-scale integration test (gated behind `TEST_DATABASE_URL` +
  `ALLOW_TEST_DATABASE_RESET=1`, matching existing convention) that runs the actual 3M-row
  bootstrap + full phase sequence against a disposable test database, asserting the
  behavioral acceptance criteria from the contract (not the reference timings, which are
  documented as non-binding observations).
- `gates/admission_determinism.py` and the existing telemetry-document-count assertions in
  `backend/scripts/doctor.py` need their bounds recomputed for the new phase mix and
  explicitly re-verified against a real run before this ships — not inherited from the old
  100–120 number.
- Manual/facilitator verification: at least one full dry run against the real Aurora cluster,
  timed end-to-end, confirming the 5–8 minute ceiling holds with real margin.

### Measured Baseline — Current (Unmodified) Pipeline, Real Aurora Cluster

Ran the current, unmodified `run_live_workshop.py` end to end against
`agenticretrievalcorestack-aurorapostgresretrievalc-rxrppbdex0nu` (`db.r8g.2xlarge`, Aurora
PostgreSQL 18.3), with the Performance Insights wait temporarily and locally bypassed (never
committed — PI cannot pass on this scenario at all, per the root-cause chain in
`database-insights-removal-decided` memory; the bypass exists only to let the rest of the
pipeline run for this timing baseline). Per-stage wall-clock, current 25,000-row scale:

| Stage | Time |
|---|---|
| Preflight + Bedrock preflight embed | 4.9s |
| Induced 60s write stall | 69.1s |
| `CREATE INDEX CONCURRENTLY` repair | 2.1s |
| Collect AWS observations (CloudWatch only) | 2.2s |
| Build searchable evidence | 0.03s |
| Admit atomically into Aurora | 0.9s |
| Generate 103 real Cohere Embed v4 embeddings | 4.0s |
| Publish receipt + cleanup | 0.6s |
| **Total** | **83.6s (1.4 min)** |

Real Labs 2–4 API calls against the resulting 103-document corpus (all through the live
FastAPI app, real Bedrock calls where applicable, no mocks):

| Call | Time |
|---|---|
| Exact/hybrid search | 3.25s |
| Full-text search | 1.28s |
| Vector/semantic search | 1.56s |
| Fuzzy search (typo'd ID) | 1.52s |
| Fusion (real generated exercise request) | 1.93s |
| Filter (real generated exercise request) | 1.81s |
| Decompose | 0.13s |
| Traverse | 0.62s |
| Compare | 0.41s |
| **Full agent synthesis (real Claude call, 8 citations)** | **24.85s** |
| Replay (run + candidates, no model call) | 0.82s + 0.75s |
| Explain-ranking | 0.62s |

**Headline**: ~2 minutes of pure backend/API latency across the whole pipeline, dominated by
two fixed costs — the deliberate 60s induced stall and one 24.85s full-synthesis Bedrock
Claude call. This rules out backend latency as a real risk to the 45–60 minute session; it
does not by itself validate the published per-lab minute budgets, since those are about human
reading/typing/discussion time, not server response time. The 24.85s synthesis call is a real,
unavoidable wait a participant sits through mid-Lab-3 and should be called out in facilitator
guidance as expected, not a hang.

### Measured Baseline — New 3M-Row Mechanism, Real Aurora Cluster

Ran the redesigned mechanism's PostgreSQL-side steps end to end (ad hoc script, not yet the
shipped implementation) against the same real cluster:

| Stage | Time |
|---|---|
| Bootstrap (5,000 customers + 3,000,000 orders) | 27.6s |
| `ADD COLUMN priority_tier` (committed separately, no held lock) | 0.04s |
| Backfill `UPDATE` (3M rows, transaction left open) | 22.3s |
| 10 concurrent hot-row writes, all genuinely blocked | all timed out at ~3.1s |
| Commit | 0.03s |
| Query regression: before `ANALYZE` | 471.75ms (seq scan) |
| Query regression: after `ANALYZE`, still no index | 245.65ms (seq scan) |
| Query regression: after index | 2.24ms (index scan) |

**Confirms two things empirically that the design previously flagged as assumptions:**
1. The "lowest `order_id`s collide earliest with the backfill's scan" hypothesis (flagged
   as unverified in the Components section above) is now confirmed — all 10 writers against
   IDs 1–10 genuinely blocked while the backfill held its transaction open.
2. The `ANALYZE`-doesn't-help/index-does finding replicates at a starker ratio on a fresh
   run (471ms→245ms→2.24ms) than the original brainstorming probe (225ms→219ms→1.5ms) —
   consistent story, real run-to-run variance in the exact numbers, timings remain reference
   observations only.

**Explicit limitation, not yet closed**: this test used direct short-lived `psycopg`
connections with a `statement_timeout`, not the actual `psycopg_pool.ConnectionPool` /
`pool.connection(timeout=3.0)` / `PoolTimeout` / `get_pool().get_stats()` mechanism the
contract specifies. It verifies the PostgreSQL-side lock-contention half of Phase 2 for real;
it does NOT yet verify genuine FastAPI-pool exhaustion, since the lab-only hot-write endpoint
and pool-status endpoint don't exist in code yet. That verification is still owed once those
components are built — do not treat this measurement as closing the pool-exhaustion
acceptance criterion.

### Measured Baseline — Embedding Throughput at Corpus-Target Scale

Directly tested Cohere Embed v4's real Bedrock `InvokeModel` batch limit (never assumed):
**96 texts per call is the hard cap** — 128 fails with `ValidationException: Invalid
parameter combination`. Ran 2,000 chunks sequentially in batches of 96 against the real
Bedrock endpoint: **27.6 seconds total, zero throttling, zero errors**, consistent ~1.1–1.4s
per batch (two mild outliers up to 2.6s, not a systematic slowdown). At the 180–250 document
target (assuming ~1 chunk/document, matching the current corpus's exact 1:1 ratio), embedding
time is a rounding error against the 5–8 minute ceiling — well under the 103-document
baseline's already-small 4.0s. Embedding throughput is not a constraint on corpus size in
this range; document-generation diversity (see the Evidence builder component above) is the
real bound, not embedding speed.

### Measured Retrieval-Quality Baseline — Current 103-Document Corpus

Direct inspection of real API responses (not assumed) confirms the corpus already produces
genuinely different top results per arm even at the CURRENT, pre-redesign scale — a positive
signal for the larger redesigned corpus:
- Exact search on an `INC-` key correctly ranks the incident record first.
- Full-text search surfaces `LOCK-...-01` first via lock-vocabulary match — different top
  result from exact.
- Vector/semantic search surfaces `CHG-...-01` first via paraphrase similarity — different
  top result from both exact and full-text.
- Fuzzy search correctly resolves a deliberately transposed ID (`CGH-...-01`) to the real
  `CHG-...-01`.

**Reranking produced a real, substantial, measured difference** — not a marginal reordering.
Comparing `rerank=false` (RRF only) vs. `rerank=true` (Cohere Rerank 3.5) on the identical
fusion query: RRF-only's top 8 results were dominated by six near-duplicate `TEL-...-A0xx`
activity-window snapshots (clustered `rrf_score` 0.041–0.044) — it correctly found the causal
`CHG-...-01` at #1 but buried the rest of the causal chain. Reranked, `TEL-...-R01` (repair
verification, `rrf_score`=0.032, well outside the RRF top-8) jumped to #2, and
`LOCK-...-01`/`CHG-...-02` (repair change) both entered the top 4 from `rrf_score`s the
RRF-only ordering had ranked below several near-duplicate activity documents. Rerank scores
for the promoted documents (0.52–0.69) were clearly separated from the demoted ones (~0.42),
confirming the reranker's signal is real, not noise. Raw `rrf_score` and `final_score`
columns were unchanged by reranking in both responses, confirming this repo's
raw/RRF/rerank-score-separation invariant holds. This is evidence the redesign's larger,
more evidence-diverse corpus should make this effect even clearer, not weaker — the
qualitative story already works at 103 documents; more genuinely-distinct evidence kinds
should sharpen it further.

## Explicitly Out of Scope

- Migrating `main`'s currently-deployed Lab 1 mechanism gradually — this is a full
  replacement of the incident-generation code path, not an incremental patch.
- Any change to Labs 2–4's retrieval/ranking/agent/citation mechanics.
- Any change to the optional RLS/masking or AgentCore labs, unless a specific compatibility
  break is discovered during implementation (not anticipated, since neither touches
  `workbench_lab` or the incident-generation code path today).
- pgbench, JMeter, ECS, or Lambda-driven load generation — considered and explicitly rejected
  for the pool-exhaustion mechanism specifically, because none of those connect through the
  application's own connection pool (pgbench connects directly to Postgres; JMeter/ECS/Lambda
  would need new infrastructure). The hot-write driver going through the real FastAPI pool is
  the only mechanism that can produce genuine `psycopg_pool` exhaustion.
