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
  3,000,000 rows, up from 25,000) never enters `casework`/`retrieval`/`proof`. The 3M-row
  table carries the volume story on its own; the searchable corpus is the smaller set of
  meaningful observations one incident actually produces. **Expected range: 50–80
  documents** (empirically confirmed via Gate 5 — see Testing section — NOT the 180–250
  originally targeted; inflating the count to hit a number would mean manufacturing
  evidence, which the live-data-only rule forbids). This is an expected range, not a hard
  acceptance gate — see the behavioral coverage criteria in the Testing section. Built from
  genuinely distinct signal types — lock/blocking-state transitions, pool saturation/recovery,
  request latency/timeout aggregates, WAL/statement deltas, backfill/recovery/index metadata,
  and the
  three query-plan checkpoints — never from denser time-sampling of the same signal.
  CloudWatch metrics do not count toward this range (best-effort supplemental only).
- No new fragile external dependency may replace the one being removed. Reuse the existing
  FastAPI connection pool (`backend/app/db.py`, `DB_POOL_MAX_SIZE=10`) for pool exhaustion —
  do not add RDS Proxy, PgBouncer, or any new pooling infrastructure. Do not gate readiness on
  CloudWatch or any AWS console-side telemetry.
- Preserve the existing optional RLS/masking module unless this implementation directly
  requires a compatible update to it. **Do not describe either optional module as a lab in
  participant-facing content**: the RLS/masking module exists only on the
  `rls-personas-column-masking` branch (deleted from `main` in f4e6399, live database
  deliberately not migrated), and the AgentCore lab was removed in d272014, leaving only a
  transport plus an orphaned sibling-repo page. See the Participant-Facing Framing section's
  "Two things this arc must not claim."

  **This redesign does require one compatible update, and it is not optional.** Removing
  Performance Insights removes the only producer of `acl.visibility = 'restricted'`:
  `labs/incident/run_live_workshop.py:_measured_visibility` classified an evidence record
  restricted when the PI capture resolved query text for it. Nothing else in the repository
  emits that value, `casework.admit_evidence` silently defaults an unlabelled record to
  `workshop` (`sql/10_admission.sql:418`), and G-27 exits 1 — not BLOCKED — on a corpus with
  zero restricted rows (measured after the schema change on the disposable test database).
  The new evidence builder therefore carries the classification forward, re-anchored onto
  the participant's own captured statement text in
  `casework.pg_stat_activity_samples.query` and
  `casework.pg_stat_statements_samples.queries` — the two columns the masking module already
  protects. Same rule, same live-data-only footing, different source column. A hardcoded
  list of keys to label restricted would be authored data and is not acceptable.

  **Scope of that update: the evidence layer, not the participant path.** Three boundaries
  hold, and the third is what keeps the first two from drifting:
  1. **The classification is replayable.** Every label carries the classifier version, a
     machine-readable reason from a closed vocabulary, and the identifiers of the measured
     samples it was read from. `casework.admit_evidence` requires all four and rejects a
     record that omits any — replacing the silent `workshop` default, which was a
     classification the database invented on a producer's behalf and which failed
     unrestricted.
  2. **G-27 and G-29 stay optional-security release gates.** They are registered in
     `gates/checks.sh`'s `SECURITY_GATES`, not `CORE_GATES`, and the no-argument sweep both
     omits them and forces `WORKBENCH_SECURITY_ENABLED=0` (the original seven-gate
     measurement proved this boundary; later core gates do not change it). A red security gate means
     the optional RLS lab is not releasable; it never means the workshop is not releasable.
     The optional lab is releasable only against a real mixed-visibility capture — both
     `workshop` and `restricted` rows present, counts recorded, classifier version recorded.
  3. **Lab 3 stays retrieval-first.** Persona switching, `SET LOCAL ROLE`, and restricted
     citations are not requirements of any core lab, and the canonical Lab 3 answer resolves
     identically on a database that has never run `make security-schema`. Carrying the
     classification forward is an evidence-layer obligation and an audit-trail obligation.
     It is not permission to put the optional module on the one-hour critical path.
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
  → ~50-80 searchable documents (expected range, gated on coverage not count)
  → casework/retrieval/proof (unchanged admission path)

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

**Evidence builder (`run_live_workshop.py::_telemetry_documents`, modified)** — Expected
range: **50–80 searchable documents** for one incident run (empirically confirmed via Gate 5,
`docs/superpowers/specs/2026-08-04-dat410-gate-results.md` — NOT the 180–250 originally
targeted; a first attempt at 148 mechanically-templated documents hit a 20.65% near-duplicate
rate, and even an honestly-varied second attempt topped out at 51 genuinely distinct
documents for the current six-category, 10-writer design). This is an expected range, not a
hard acceptance gate — see the behavioral coverage criteria in the Testing section for what
actually gates readiness. Produced from genuinely distinct signal types, never from denser
time-sampling of the same four phases. CloudWatch metrics do not count toward this range
(they stay best-effort supplemental evidence per the CloudWatch section below, and their
availability is not guaranteed).

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

**Action proposal writer (new, in the agent's Lab 3 answer path)** — After the agent produces
its cited answer, writes exactly one `proof.action_proposals` row referencing that
`agent_run_id`: structured action type and target, proposed SQL, supporting citations
restricted to those already passing `proof.validate_answer_citations()`, preconditions,
expected effect, and rollback guidance. **This is not a new agent tool** — the agent gains no
capability, and `agent/registry.py` stays at seven read/synthesis-only tools. The proposal is
recorded by the answer path from the answer the agent already produced, the same way
`proof.answer_citations` is recorded today. The distinction matters: a tool the agent can call
is a capability; a record written about the agent's output is an audit trail.

**Supervised execution recorder (new, in the Wave B capture path)** — Writes exactly one
`proof.action_executions` row per execution attempt: the participant's explicit approval, the
executed SQL, the **observed** index definition read back from `pg_indexes`/`pg_get_indexdef`
(never the participant's typed text), outcome and timestamps, before/after plan evidence
references, and the canonical-fingerprint comparison; the Wave B receipt identifiers are
attached to that row once admission succeeds. Reading
the definition back from the catalog rather than trusting the input is what makes the comparison
evidence rather than assertion.

**Canonical fingerprint function and autonomy-readiness verdict (new, in `sql/`)** — Both live
in Aurora as SQL, not in Python, for the same reason ranking does: they are the proof layer, and
a participant must be able to run them and read them. The fingerprint normalizes action type,
schema, table, index method, ordered key columns, included columns, and predicate into a
comparable structure; the verdict computes `pre_execution_eligible` and
`post_execution_validated` with explicit reasons. Full contract in the Supervised Execution
Model section below.

## Session Thesis and Closing Message

This section governs every participant-facing surface — Workshop Studio content, the guide,
UI copy, the agent's system prompt framing, and the closing slide. Where a copy decision
elsewhere in this document or in the implementation plan appears to conflict with the thesis
below, the thesis wins.

**The outcome is not "participants fixed a missing index."** That is the mechanism, not the
lesson. Stating it as the outcome reduces an L400 Aurora PostgreSQL session to an
introductory query-tuning exercise, and it wastes the corpus the lab spent its whole first
third building.

**The outcome is this, and this exact wording is the session's thesis:**

> At fleet scale, telemetry is abundant; trustworthy context is scarce. Participants build the
> database-native evidence layer an operational agent needs: live signals become versioned,
> searchable evidence; Aurora PostgreSQL retrieves, combines, ranks, relates, and cites that
> evidence; and a human validates the recommendation before any action is taken.

**Closing message, verbatim:** *you built the trusted context layer required by a fleet-scale
database agent.*

### Why this framing, and what it deliberately avoids

The thesis is chosen to connect to the operational-AI themes the surrounding conference track
raises — signal-to-noise at fleet scale, the operator expertise gap, human-in-the-loop
control, semantic and context layers, fleet expansion — **without duplicating an
autonomous-operations session.** This session's differentiator is that it never grants the
agent an execution path. It builds the context substrate an autonomous system would need and
stops precisely where a human's judgment belongs.

The five theme mappings, which are how the thesis reaches each lab:

| Theme | How this session realizes it | Where it lands |
|---|---|---|
| Signal-to-noise | Hybrid retrieval and reranking over a corpus with genuine near-duplicates and competing signals | Lab 2 |
| The expertise gap | A cited, replayable recommendation a non-expert can audit without trusting the model | Labs 3 and 4 |
| Human-in-the-loop | **Recommend, don't execute** — the participant runs `CREATE INDEX` themselves after reading the agent's evidence | Lab 4 |
| Semantic and context layers | Casework (authoritative) → retrieval (derived) → proof (replayable), as three real schemas | Labs 1 through 4 |
| Fleet expansion | The "Take it home" architecture discussion | Closing, **not** extra lab scope |

**Fleet expansion is a closing architecture discussion and never becomes lab work.** No task
may add a second cluster, a multi-tenant dimension, or a cross-fleet aggregation step to any
lab in service of this theme. The 60-minute budget does not have room, and the theme is
satisfied by explaining how the same evidence layer scales, not by scaling it live.

**The conference-track connection above is internal positioning rationale.** No customer or
company name appears in any participant-facing surface. Participants see the thesis and the
closing message; they never see this subsection's reasoning.

### Consequences for copy that already exists

- The incident is the corpus generator, and the thesis makes that ordering explicit rather
  than merely implied. Any page whose summary line ends at "we fixed the query" is wrong even
  if every fact on it is right.
- "Recommend, don't execute" is the participant-facing phrasing of the agent's read-only
  constraint. Use it in copy; keep the mechanical statement (all tools in
  `agent/registry.py` are read/synthesis-only) in technical text.
- The closing message is a claim about what the participant built, so it must be literally
  true of their own run. A participant whose Wave B admission failed did not build a
  validated evidence layer, and the closing surface must not tell them they did — this is the
  live-data-only rule applied to the summary, not just to the data. A static content page
  cannot satisfy that condition, since it renders the same sentence either way, so the
  closing message is emitted by the Wave B capture path after a successful admission. The
  content page may set the claim up; only the run may state it.

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

### The central question, and why it has three clauses

> Why did order writes time out during the priority-tier migration, why did the application
> recover after commit, and why did the priority query remain slow?

**The three clauses are a design decision, not stylistic padding.** No single retrieval arm
answers all three, and that is the point: the question forces the participant through decompose
(three sub-questions with different evidence needs), traverse (the request → connection →
backend → blocker → migration chain that links clause one to clause two), and compare (the
plan checkpoints that answer clause three and are unrelated to the lock evidence). A
single-clause question would let one lexical search look sufficient and would make Lab 3's
tool registry look like ceremony.

Note also that the three clauses have **different answers with different mechanisms**: clause
one is lock contention plus pool exhaustion, clause two is the commit releasing row locks, and
clause three is a missing access path that has nothing to do with either. A participant who
tries to explain all three with one cause will be contradicted by the evidence, which is the
intended learning moment.

### Session beats, with the honest emphases

These are the beats the participant experiences. Each entry names the beat and the thing about
it that must not be softened or compressed away.

**Establish ground truth.** 5,000 customers and 3,000,000 orders are preloaded operational
data; `casework`, `retrieval`, and `proof` contain zero participant evidence. **The operational
workload is not the retrieval corpus** — this distinction is load-bearing and is why the corpus
is 50–80 documents while the table is 3,000,000 rows.

**The migration ships.** Add nullable `priority_tier`, backfill all three million rows in one
transaction, application writes collide with that uncommitted transaction. Accessible at L300;
the L400 mechanics are inspected progressively rather than asserted up front.

**Lab 1, beat: ten writers block, visibly.** Tagged application sessions enter
`Lock:transactionid`; `pg_blocking_pids()` identifies the backfill PID. This is the signal
participants expect to find, and they find it.

**Lab 1, beat: the queue that leaves no database footprint.** This is its own beat and must
never be reduced to a bullet inside the previous one. The ten blocked writers appear in
`pg_stat_activity` with a wait event and a blocking-PID chain. The additional queued requests
appear **nowhere in the database at all** — they never obtained a connection, never entered a
lock wait, never appeared in `pg_stat_activity`, and exist only in pool statistics and in their
own `PoolTimeout`. A request that failed and left no database footprint is the session thesis in
a single observation: telemetry is abundant, trustworthy context is scarce. The corrected
12-request-against-10-slot contract (see Global Constraints) is what makes this observable at
all — with ten requests against ten slots you can never see a fully-saturated pool and a
non-empty wait queue in the same sample.

**Lab 1, beat: the drain.** After the commit, the ten blocked writers acquire their locks and
**commit successfully** — a measured recovery, not merely "writes recover." This is the proof
the diagnosis was right, and it is why the blocked-statement timeout is 40 seconds rather than
Gate 1's 3 seconds: a 3-second bound cancels every writer before the observation hold begins
and there is no drain to observe. A run in which zero writes commit is a regression, not a
variant.

**Lab 1, beat: `ANALYZE` does not help.** The priority query is captured before and after
`ANALYZE`; both plans are sequential scans. The supporting index is deliberately absent. What
changes is the estimate; what does not change is the access path.

**Lab 2, and the uncomfortable result.** Participants build the four arms, filter before
fusion, adjust weighted-RRF inputs, and compare PostgreSQL fusion against Cohere reranking.
**On at least one judged query in this repository, lexical retrieval beats hybrid** — a real,
measured result (see the `eval-leaderboard-honesty` memory). Publish it. A workshop that shows
an arm losing is credible; one that claims hybrid always wins is not, and the participants best
equipped to notice are the ones whose opinion matters most. Also state plainly that at 50–80
documents a sequential scan may be the planner's correct retrieval plan.

**Lab 3, lead with the structural impossibility.** The strongest honesty claim in the workshop
is this, and it goes first rather than last: at Lab 3 the after-index checkpoint **does not
exist in Aurora**. If the agent asserted an improvement, it would be a fabrication with no
citable document, and `proof.validate_answer_citations()` would fail it. That is structural
honesty enforced by *time and schema*, not by prompt discipline — the agent is not being
trusted to refrain, it is unable. Everything else the agent does in Lab 3 (decompose, search,
traverse the request → connection → backend → blocker → migration chain, compare, explain
ranking, cite) is subordinate to that point. The run ends by writing a structured, cited action
proposal — not prose advice.

**Lab 4, supervised execution.** The participant reviews and explicitly approves the proposal,
executes the DDL themselves, then compares proposed against observed via the canonical
fingerprint, captures and admits Wave B, inspects both receipts, replays the Lab 3 run
unchanged, and computes the autonomy-readiness verdict. "Recommend, don't execute" is the
participant-facing phrasing of why the agent handed them SQL instead of running it.

**Transfer.** A reusable SQL hybrid-retrieval workbook; a read-only agent pattern; two
versioned evidence receipts; persisted rankings, relationships, citations, and replay; the
supervision record; and a production extension model — additional accounts, engines,
connectors, ACLs, and structured outputs for human or IaC workflows. Fleet expansion and the
read-only → human-approved → policy-bounded-autonomous progression are discussed here, as
architecture, and never as lab work.

### Two things this arc must not claim

**No mixed-run timing numbers.** The measured baselines below contain two separate runs: the
brainstorming probe (225 ms → 219 ms → 1.5 ms) and the fresh 3M-row run (471.75 ms →
245.65 ms → 2.24 ms). Splicing them — for example "219 ms to 1.5–2.2 ms" — produces a number no
run ever produced and violates the exact-numbers rule in Global Constraints. Publish one run's
triple, or publish the shape instead: buffers dropping two orders of magnitude and
rows-removed-by-filter going from roughly 2.4 million to zero. **The shape is the better
teaching point anyway**, because execution time alone never shows *why* the index worked. Task
G3 replaces every published number with the final run's measurements regardless.

**No unsupported optional-lab promises.** Do not tell participants the session includes
optional RLS-with-masking and AgentCore-publication labs. Current reality: the RLS and column-
masking module exists only on the `rls-personas-column-masking` branch (`sql/11_roles_rls.sql`,
`sql/12_masking.sql`); commit f4e6399 deleted it from `main`, and the live database is
deliberately not migrated for it. The AgentCore **lab** was removed in d272014 — what survives
is a transport (`lambda_mcp/handler.py`, `scripts/invoke_agentcore_gateway.py`) and an orphaned
page in the sibling Workshop Studio repo. Additionally, the final 3 minutes of a 60-minute
session is a cleanup slot, not room for a substantial module. If these are offered at all, they
are **take-home extensions**, described as such, and only for the pieces that actually exist on
the shipping branch.

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

## Supervised Execution Model

**The agent stays read-only; the workflow becomes supervised read/write.** This section closes
a real audit gap in the design as previously written: the chain ran agent recommendation →
*nothing* → Wave B outcome. The human decision, which is the single most important event in a
human-in-the-loop session, left no trace in Aurora. A participant could not answer "what
exactly was proposed, did I approve it, and did I execute what was proposed?" from the
database, which is precisely the class of question this whole workshop claims Aurora can
answer.

**What does not change, and is not negotiable:** the agent receives no write tool, no DDL
privilege, and no execution path. All tools in `agent/registry.py` stay read/synthesis-only.
The participant executes the DDL themselves in Code Editor. Granting the agent DDL would
import authorization, rollback, idempotency, concurrency, and policy enforcement as new
subjects and dilute the hybrid-retrieval focus this session exists to teach.

### Two new proof tables

**`proof.action_proposals`** — written by the Lab 3 agent run, one row per proposed action.
References the `proof.agent_runs` row that produced it, so a proposal is never free-floating
advice. Carries:

- structured action type and target (not only prose): action type, schema, table, index
  method, ordered key columns, included columns, predicate;
- the proposed SQL text;
- supporting citations, restricted to citations that already pass
  `proof.validate_answer_citations()` — an unvalidated citation cannot support a proposal;
- preconditions the action assumes;
- expected effect;
- rollback guidance.

**`proof.action_executions`** — written during Wave B, one row per execution attempt.
References its proposal. Carries the participant's explicit approval, the executed SQL, the
**observed** index definition read back from the catalog (not the SQL the participant typed —
what PostgreSQL actually created), outcome and timestamps, before/after plan evidence
references, the Wave B admission and receipt IDs, and whether the executed action matched the
proposal.

The row is **append-only, and not merely by privilege**. Non-owner roles hold `INSERT` and
never `UPDATE`, but the recorder that writes the row runs as the owner, and the owner holds
`UPDATE` inherently — so the rule is enforced by a trigger on the table rather than by a
grant. Every column that decides a verdict is written by the `INSERT` that creates the row and
cannot be changed afterwards by anyone: an execution that did not match the proposal cannot be
edited into one that did.

One exception exists and it is not a verdict column. The two Wave B receipt identifiers are
attached *after* the row is written, because the execution is recorded **before** admission is
attempted. A `CREATE INDEX` that succeeded and an admission that then failed must not
disappear from the record; recording after admission would leave zero rows, which reads as "no
execution has been recorded" — false, and indistinguishable from a participant who skipped the
lab. Until the receipt is attached the verdict says the result was not validated by an
admitted Wave B capture, which is exactly true at that moment. The attachment is once-only:
substituting a different receipt is refused.

A rerun after a fixed admission failure appends a **new** row rather than amending the first.
The verdict and the Proof surface both report the latest attempt, ordered identically, so the
panel a participant reads and the verdict computed for them can never describe different
attempts.

### Canonical fingerprint, not raw SQL hash

**Raw SQL hash equality is the wrong authoritative test, and using it would make the workshop
lie to participants.** Whitespace, quoting, casing, optional keywords, schema qualification,
and equivalent PostgreSQL syntax all change the hash without changing the action. A
participant who typed the recommended index with different spacing would be told they executed
something else.

The authoritative equality test is a **canonical structured fingerprint** built from:

```
action type
schema
table
index method
ordered key columns   (order matters: (priority_tier, created_at DESC) != (created_at DESC, priority_tier))
included columns
predicate
```

Key column order is part of the fingerprint because it is semantically load-bearing for this
exact index — a participant who reverses the columns has *not* executed the proposed action,
and the workshop should say so.

Raw SQL hashes are still stored on both tables, for audit and for showing participants that
identical actions can arrive as different text. They are never the equality test.

The fingerprint is computed twice from two independent sources: once from the proposal's
structured fields, and once from the **observed catalog definition** after execution. That
second derivation is what makes the comparison meaningful — it compares what was proposed
against what PostgreSQL actually built, not against what the participant claims to have run.

### Autonomy readiness: computed, never narrated

The verdict is a SQL function over the proposal, its citations, its preconditions, and the
execution record. It emits two independent booleans, each with explicit reasons:

- **`pre_execution_eligible`** — computed from information available *before* execution only.
  Requires: validated supporting citations; an allowlisted action type; an approved target
  (schema and table on the allowlist); satisfied preconditions; bounded timeouts declared;
  and rollback guidance present. Each failed requirement contributes a named reason.
- **`post_execution_validated`** — computed from the execution record: the action succeeded,
  the observed fingerprint matches the proposed fingerprint, and the after-plan evidence
  demonstrates the expected effect.

**Successful post-execution evidence must never be fed back into `pre_execution_eligible`.**
An action that worked was not therefore safe to automate; a proposal missing rollback guidance
stays ineligible even after a flawless execution. This is the single most important property
of the verdict, and the gate for it (G-34, see the implementation plan) exists specifically to
prove the retroactive path is absent rather than merely unused.

This is an **autonomy-readiness assessment, not autonomous execution.** Nothing in this design
executes anything without the participant. The three-stage progression — read-only
recommendation → human-approved execution → policy-bounded autonomous execution — belongs in
the "Take it home" closing discussion, where fleet expansion also lives, and never becomes lab
scope.

### Participant arc

**Lab 3:** the agent creates a cited, structured action proposal. The post-index result does
not yet exist, so the agent cannot claim success — and this is enforced by the database, not
by prompt discipline. See the Participant-Facing Framing section's Lab 3 beat.

**Lab 4:** the participant reviews and approves the proposal, executes the action, captures
Wave B, compares the proposed and observed action via the canonical fingerprint, validates the
result, and computes whether the action could qualify for future policy-bounded automation.

**Cost to the participant is roughly one minute**, since they are already reviewing the
recommendation and running the DDL. No new external dependency: two tables, one fingerprint
function, one verdict function, all in Aurora.

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
   Evidence builder converts every measured signal into Wave A telemetry documents (50-80
   expected range, state-change/interval-boundary, not per-poll). Wave A is admitted, embedded, and its
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
   The run also writes one `proof.action_proposals` row: structured action type and target,
   proposed SQL, validated supporting citations, preconditions, expected effect, and rollback
   guidance, referencing this `agent_run_id`.
5. **Lab 4 — Remediate and prove.** The participant reviews and explicitly approves the
   proposal, then executes the recommended `CREATE INDEX` DDL themselves in Code Editor (the
   agent never gets DDL privilege or an execution path). The orchestrator captures the
   post-index plan, verifies the index, reads the **observed** index definition back from the
   catalog, and writes `proof.action_executions` — approval, executed SQL, observed
   definition, outcome and timestamps, before/after plan references, and the
   canonical-fingerprint comparison of proposed versus observed. That write happens **before**
   admission is attempted, so an execution cannot be lost to a later failure; the Wave B
   receipt identifiers are attached to the row afterwards. It then admits Wave B — a new
   follow-up admission contract, additive to Wave A, with its own
   admission ID, observation window, and receipt — embeds the small delta, publishes the
   remediation receipt, and the participant replays the original Lab 3 investigation
   (unchanged, still showing Wave A only) alongside the new remediation proof and the computed
   autonomy-readiness verdict.

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
- **Supervised execution needs adversarial tests, not happy-path tests**, because every
  interesting property is a negative one:
  - The canonical fingerprint must match across formatting variance: different whitespace,
    casing, quoting, and schema qualification of the same index must produce one fingerprint.
    The raw SQL hashes must *differ* across those same variants — that contrast is the reason
    the fingerprint exists and should be asserted directly.
  - The fingerprint must **not** match on reversed key column order. `(priority_tier,
    created_at DESC)` and `(created_at DESC, priority_tier)` are different actions.
  - `pre_execution_eligible` must be false, with a named reason, for each requirement removed
    in isolation: unvalidated citation, non-allowlisted action, unapproved target, unsatisfied
    precondition, unbounded timeout, missing rollback guidance. Six independent negative cases,
    not one bundled check.
  - **A successful execution must not flip `pre_execution_eligible` to true.** Construct a
    proposal that is ineligible (say, no rollback guidance), execute it successfully, and assert
    the pre-execution verdict is still false with its reason intact. This is the retroactive-
    safety test, and it is the one test in this group that must never be skipped.
  - The agent must hold no DDL privilege on `workbench_lab`. Assert it against the catalog
    rather than trusting the tool registry, since privilege can be granted without touching
    Python.

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
per batch (two mild outliers up to 2.6s, not a systematic slowdown). At the 50-80 document
expected range (assuming ~1 chunk/document, matching the current corpus's exact 1:1 ratio),
embedding time is a rounding error against the 5–8 minute ceiling — well under the
103-document baseline's already-small 4.0s, and this measurement's headroom is even larger
now that the range is smaller, not larger, than originally assumed. Embedding throughput was
never the binding constraint on corpus size in
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

### Honest Framing: Sequential Scans Are Correct at This Scale, Not a Limitation

At 50–80 documents, PostgreSQL's planner may correctly choose a sequential scan over an HNSW
index scan for some retrieval arms — this is the RIGHT choice at this corpus size, not a
limitation or a failed demonstration. **Correction to an earlier draft of this section**: an
initial version of this note claimed this framing already existed verbatim in
`docs/builder-session-flow.md` — checked directly against that file and no such sentence
exists there. This is new guidance this redesign introduces, not a restatement of prior
documentation. State it plainly in participant-facing content going forward; do not apologize
for the sequential scan or engineer around it. Production-scale ANN index behavior belongs in
an appendix note ("at production scale, this changes because...") — never folded into the
core lab's numbers or presented as something the redesign failed to achieve.

### Corpus Adequacy: Behavioral Coverage Criteria, Not a Document Count

**DECIDED (2026-08-04, after Gate 5):** 50–80 documents is the expected range for one
incident run — not the 180–250 originally targeted in this document's earlier drafts. Full
reasoning and the empirical measurements that produced this number are in
`docs/superpowers/specs/2026-08-04-dat410-gate-results.md`'s Gate 5 section. This is an
**expected range, not a hard acceptance gate.** The `workbench_lab.orders` 3,000,000-row
table carries the "volume" story on its own; the retrieval corpus is deliberately the smaller
set of meaningful observations one incident actually produces. Inflating the document count
to hit a number would mean manufacturing evidence, which the live-data-only rule forbids
regardless of how the padding is dressed up (this is exactly what Gate 5's first attempt
did by accident, and it was rejected once discovered, not shipped).

Corpus adequacy is gated on coverage instead, matching the behavioral-acceptance pattern
already used everywhere else in this design:
- Every incident phase and every evidence category (the six signal types in the Evidence
  builder component above) is represented in the admitted corpus.
- Exact, full-text, semantic, and fuzzy retrieval produce meaningfully different top
  candidates for the same query — already demonstrated real at 103 old-mechanism documents
  (see the Measured Retrieval-Quality Baseline above); the implementation phase must
  re-confirm this against the new corpus, not assume it carries over unchanged.
- Fusion and reranking alter ordering for defensible, explainable reasons — already
  demonstrated real (Cohere Rerank 3.5 promoting causally-relevant documents RRF buried
  behind near-duplicates); re-confirm against the new corpus.
- Wave B adds distinct, genuinely new validation evidence, not a restatement of Wave A
  evidence in different words.
- Near-duplicate rate stays bounded (Gate 5's 15% threshold, or a number the Evidence builder
  implementation task recalibrates against real generated text — not assumed from the gate
  script's throwaway samples).
- Citations and replay resolve to exact document versions (Gate 2 already proved the
  underlying replay mechanism; re-confirm end-to-end once the real admission contract exists).

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
- **Granting the agent a write tool, DDL privilege, or any execution path.** Considered and
  explicitly rejected: it would import authorization, rollback, idempotency, concurrency, and
  policy enforcement as major new subjects and weaken the hybrid-retrieval focus. The
  Supervised Execution Model section is the accepted alternative — a supervised read/write
  *workflow* around a read-only agent.
- **Live autonomous execution of any kind.** The autonomy-readiness verdict is a computed
  assessment over recorded evidence, not an execution mode. Enabling autonomous DDL on a
  workshop database would be less credible, not more.
- **Restoring the optional modules as participant-facing labs**, or presenting them as fitting
  inside the 60-minute budget. If offered, they are take-home extensions limited to what exists
  on the shipping branch.
