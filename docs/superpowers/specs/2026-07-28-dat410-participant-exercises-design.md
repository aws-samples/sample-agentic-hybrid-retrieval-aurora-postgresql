# DAT410 participant exercises — design

Date: 2026-07-28
Status: approved and bound into `SPEC-session.md` draft-20 (holes H1–H3, D24,
G-27, G-28). This doc is the long-form rationale; the SPEC is authoritative.
Companion: `SPEC-session.md` draft-20 — all three copies (`~/Downloads`,
`design/SPEC-session.md`, `design/verity-handoff/docs/SPEC-session.md`) synced
byte-identical (sha256 `621ff17e…a7e749`).

## Purpose

Turn the four-lab session skeleton (D12: Incident & observability / Hybrid
retrieval / Agentic retrieval / Proof & replay) into concrete hands-on
participant exercises. This is a builder's session: participants must spend
their minutes writing code, not watching Hybrid Retrieval Workbench. The design answers two
questions the SPEC implies but does not enumerate:

1. What does a participant build with their hands in each lab?
2. How do the four labs connect into one seamless thread?

## Organizing principle (governs every lab)

**Participants build the agent's *decisions* in SQL. The machinery ships
prebuilt.**

Building the loop teaches the framework; building the decisions teaches the
thesis — Aurora as the retrieval engine of record. The rule that sorts every
candidate exercise:

- **Never a hole (machinery):** the Strands loop, the six-tool registry
  (T4 — generated; hand-writing it violates G-17), the plan executor
  (T2 planned mode), tool wrappers, rerank (a Bedrock API call, T3),
  the AgentCore Gateway forwarder (D15/M5).
- **The holes (decisions, all SQL):** the fusion combination (Lab 2), the
  entitlement predicate at the hop (Lab 3), the coverage rule that gates
  synthesis (Lab 3).

Because the prebuilt tools call the SQL functions, fixing a function body
changes what the agent does — automatically. This is verified in the code,
not asserted: `search_evidence_impl` (`backend/app/agent.py:248`) →
`run_hybrid_search` → the weighted-RRF sum at
`sql/03_search_functions.sql:917-920`, whose comment already documents the
E1 integer-division trap.

## The connective thread (Lab 1 → 4)

One canonical question, one `run_id` lineage, surfaced at each lab boundary.

**Wiring model: checkpointed-but-literal.** A participant whose Lab 2 verify
checkpoint prints `OK` carries *their own* fusion SQL forward into Lab 3, where
the agent's `search_evidence` tool executes it live. A participant who is
behind runs `reset.sh lab3` (or `make lab3-start`), which restores
reference-good SQL, so Lab 3 always works for everyone. Seamless if you
succeed; safe if you don't. This satisfies the D23 never-answer-critical law
and the F1 floor-recovery posture, and it respects the D9 cut-ladder.

**The reveal that makes the thread literal, not narrated:** in Lab 3, open the
`search_evidence` tool receipt inside the agent thread → "Verify in psql" → it
is the *same fusion SQL edited in Lab 2*, producing the *same `rrf_score`* the
participant computed by hand at the Lab 2 checkpoint. "That number in the
agent's trace? You wrote the SQL that produced it."

| Lab | Participant builds / does | What threads forward |
|---|---|---|
| 1 | Runs the incident; admits `LOCK-LIVE-001` via `admit.sh` (M5, zero model calls) | Their evidence row + `run_id` lineage begins |
| 2 | Writes the fusion SQL (**H1**); verifies `rrf_score` against the golden in psql | That exact function is what the agent will call |
| 3 | Writes `acl_visible` at the hop (**H2**) + the coverage rule (**H3**) | Same `rrf_score`, now inside the agent's tool receipt |
| 4 | Replays the Lab 3 `run_id` (zero model calls); installs the skill | The whole lineage proven reproducible |

## Lab-by-lab exercises

### Lab 1 — Incident & observability (run + observe; not a SQL hole)

Participant-run, no code hole. Runs `incident.sh` (M1: first blocked writer in
their own terminal), watches it terminal-native (`watch.sql`,
`pg_blocking_pids`, `pg_locks`), resolves, fixes with `CREATE INDEX
CONCURRENTLY` (before/after EXPLAIN). Then the **admission beat** (`admit.sh`,
M5, core, **zero model calls**): their own lock observation enters the record
via `casework.admit_evidence` (D21), ingest receipt printed,
`LOCK-LIVE-001` retrievable by the exact arm immediately. This is the Law-4
two-beat (evaporation → admission) and the concrete answer to "how does data
get into Postgres." Thread start.

### Lab 2 — Hybrid retrieval (H1: the fusion decision)

**Hole (H1):** a 400-level TODO in the fusion function body — write the
**weighted-RRF sum** across the three ranked arms. Concept hints, never
copy-paste SQL.

- **E1 (the payoff failure):** the naive `2/(60+r)` is integer division and
  silently evaluates to `0.00000` for every candidate; casting one operand
  `::numeric` produces real scores. "This failure exists only because we fuse
  in-database — and so does the receipt that catches it."
- **E6 (fuzzy archetype):** the trigram index trap — `WHERE similarity(k,q) >
  0.30` cannot use the GIN index; the `%` operator with
  `pg_trgm.similarity_threshold` can (two EXPLAINs: Seq Scan vs Bitmap Index
  Scan).
- **Checkpoint (M2, G-28):** recompute `rrf_score` for CHG-1842 in psql and
  assert against the **generator-derived golden — never against the panel's own
  value** (a wrong fusion matches its own panel; only the independent golden
  catches an incorrect-but-self-consistent answer). The auditor's invitation —
  "pick any number on any screen."
- **Lab 2 internal compress order (amendment 4):** if time is short, the E6
  EXPLAIN pair moves to the appendix **first**; the H1 hole and the M2 checkpoint
  **never** compress.

**Rerank — observe-and-judge beat, NOT a hole.** Cohere Rerank
(`cohere.rerank-v3-5:0`, T3) is a Bedrock API call: machinery, non-deterministic,
so participants do not write it. They toggle it on/off (fusion control) and
watch the fused order reorder, reasoning about four tradeoffs:

1. **Latency + cost:** rerank adds a Bedrock round-trip per query; skip-rerank
   is the graceful zero-model degradation path (T3, Section 9).
2. **The Law-2 reproducibility boundary:** RRF is SQL — recomputable from
   scratch in psql (the E1 checkpoint). Rerank is a model call — it *cannot* be
   recomputed in psql. Replay reproduces the reranked order only because
   `rerank_score` is persisted (`Candidate.rerank_score`) and read back with
   zero model calls (M4). Teaching line: "The engine's score you can recompute.
   The model's score you can only replay." (Law 2 + Law 4 in one beat.)
3. **Post-fusion, cannot beat recall:** rerank only reorders the fused pool; it
   cannot rescue a row fusion never surfaced (cousin of E2). Ties to the honest
   ablation (talk FAQ #4) — never claim rerank always wins.
4. **Both scores preserved, never summed:** `rerank_score` and Aurora's
   `rrf_score` both persist and both render; rerank never folds into
   `final_score` as a fourth arm.

### Lab 3 — Agentic retrieval (H2 and H3: the agent's two decisions in SQL)

What makes retrieval *agentic* here is deciding sufficiency and scope — both
placed deliberately in SQL. Building the loop would teach the framework;
building these two decisions teaches the thesis.

**H2 — `acl_visible(role)` at the hop.** A TODO inside
`follow_evidence_links`' recursive SQL where the entitlement predicate must be
applied *at the hop*, not post-filtered. Checkpoint = M3 role flip: switching
the "Viewing as" role changes the hop's result set — CASE-7421 appears for
`support-lead`, vanishes for `workshop`. Performs the Lab 3 takeaway sentence
verbatim: "entitlements live in the database, at every arm and hop." (D22: the
word "principal" is banned from participant surfaces; the concept is *role*.)

**H3 — the coverage rule.** Deterministic SQL over the fused pool:
`covered = ≥1 candidate of every required kind in top N`. *Their* rule is what
withholds synthesis on the safe-fix claim and what authorizes the E2 bounded
recovery. Checkpoint (G-28): the E2 hinge asserts against participant-written
SQL from **both directions** — under their rule, the ef_search-widening
counterfactual stays uncovered, and the drop-filter escalation covers.

**RLS default-deny backstop (D24, bound — direction C adopted as written).** The
explicit `acl_visible` predicate remains the *hole* and the arm/hop mechanism —
self-contained in the SQL, index- and plan-controllable, and producing a
self-contained verify-SQL (critical for M2: a pasted SELECT returns the same rows
without a hidden session-variable prerequisite). RLS is added **once in the
schema** as a default-deny backstop and **demonstrated, not built**, in a
~45-second coda after the M3 arm-level flip. The role GUC is **`SET LOCAL`,
transaction-scoped (the T8 pattern)** — a session-level `SET` leaks the role
across pooled connections, so each demo runs inside its own transaction:

```
BEGIN; SET LOCAL verity.role = 'workshop';      SELECT * FROM casework.<evidence>
                 WHERE external_key = 'CASE-7421';   -- 0 rows
COMMIT;
BEGIN; SET LOCAL verity.role = 'support-lead';  SELECT * FROM casework.<evidence>
                 WHERE external_key = 'CASE-7421';   -- 1 row
COMMIT;
```

Raw SQL, straight at the table, no arm and no app — the database itself refuses
the row. This reinforces M2 (participants in psql running raw SQL) and converts
the "why not RLS?" question from an attack into a scripted strength:

> "We use both — RLS so you *can't* leak even when you forget, and the explicit
> predicate so the planner filters early and the receipt is self-contained.
> Belt and suspenders."

**Teaching line:** "The predicate is how the arm filters. RLS is why you can't
leak even when you forget. Real systems want both."

RLS costs to honor (do not skip — these are how RLS silently does nothing):

- The app role must not own the casework tables, or the schema must
  `ALTER TABLE … FORCE ROW LEVEL SECURITY` (owners bypass RLS by default). The
  bootstrap assertion (G-27, bound) connects as the app role, runs
  `SET LOCAL verity.role='workshop'`, and confirms CASE-7421 returns zero rows at
  the raw table.
- Replay must set the role GUC (`SET LOCAL`, transaction-scoped); the receipt
  already records role (D22), so M4 replay is deterministic.
- ACL stays a real, sargable column (the D21 JSONB-boundary rule already
  requires this; it applies identically to the predicate and to RLS).

### Lab 4 — Proof & replay (prove the thread)

Replay the Lab 3 `run_id` (M4, **zero model calls**) → identical candidates,
including the participant's own fusion output and reranked order (from the
persisted `rerank_score`). The **temporal-gate checkpoint** (G-25, D21): run
the same retrieval as-of `t < available_at` — the admitted rows are excluded;
as-of `≥ available_at` — they are included. The gate *is* the checkpoint, not
narration. Final checkpoint (D18): install `skills/aurora-hybrid-retrieval` in
Claude Code on the host and run its first assertion to green.

### Stretch (0 core minutes)

Kept exactly as spec'd: AgentCore Gateway M5 receipt-diff (canonical question
over Gateway MCP vs stdio → identical candidates and citations, diffed in psql;
pre-provisioned by bootstrap, never built live, D15), agent free mode (T12),
and attaching an MCP client to `verity_mcp` (T5). None is a build exercise;
building the forwarder would be machinery, not a decision, and G-17 generates
its schemas anyway. Open item 7 (confirm AgentCore `${target}___${tool}`
naming) is a freeze-time verification, not a design choice.

## Scaffolding conventions (all holes)

- **400-level:** TODOs with concept hints; never copy-paste-ready SQL.
- **Checkpoints are copy-pastable one-liners** that print `OK` or a remedy
  (guide convention, G-12: snippets are byte-identical to repo sources).
- **Reference-reset at every lab boundary** (`reset.sh <lab>` / `make
  labN-start`) restores known-good SQL so no participant is ever stranded.
- **Two artifacts, not one:** the frozen reference implementation (what each
  hole converges to) and the participant starting state (the holes). The Lab 2
  starting state deliberately violates the "fuse rank positions, never raw
  scores" invariant (naive score-addition / integer division) so the E1 failure
  is real; that is why the reference and the participant start cannot be served
  from one frozen revision.

## Deliberate exclusions (on principle)

- **Rerank is not a hole** — external API call, non-deterministic, machinery.
  It is the Lab 2 observe-and-judge beat above.
- **The Strands loop / tool registry is not a hole** — T2/T4 ship prebuilt;
  hand-writing the registry violates G-17.
- **AgentCore Gateway is not a build exercise** — D15/M5 stretch, 0 core
  minutes.
- **Embedding generation is off the hands-on path** — participants index and
  query already-materialized vectors; no live Bedrock embed call in a core
  beat (avoids latency/non-determinism).

## SPEC bindings this design carries (all now in draft-20)

1. **D24 (bound)** — RLS default-deny backstop: the explicit `acl_visible`
   predicate remains the arm/hop mechanism and the Lab 3 hole; RLS is added once
   in the schema and demonstrated in the M3 coda. Does not touch the retrieval
   *implementation* freeze (arms keep the explicit predicate); it adds an
   enforcement layer and one demo beat. The role GUC is `SET LOCAL`,
   transaction-scoped (T8) — session-level `SET` leaks roles across pooled
   connections.
2. **G-27 (bound)** — FORCE-RLS assertion: as the app role with
   `SET LOCAL verity.role='workshop'`, CASE-7421 returns zero rows at the raw
   table (proves RLS is not silently bypassed by table ownership).
3. **G-28 (bound)** — hole integrity, both directions: the frozen reference
   passes every generator-derived golden checkpoint and the participant starting
   state fails them. The Lab 2 checkpoint asserts against the golden, never
   against the panel's own value.
4. **Participant-hole framing (H1–H3)** — the SPEC enumerates E1/E2/E6 and
   M1–M5; this design's H1/H2/H3 mapping (which lab beats are participant-written
   SQL holes vs. observe beats) is now reflected in the draft-20 participant-holes
   subsection, Section 8 (guide acts), and the E-registry slots.

No lab renames, no reordering, no change to the canonical question, M1–M5, or
the D9 cut-ladder.

## Spec sync status

All three copies of `SPEC-session.md` (`~/Downloads`, `design/SPEC-session.md`,
`design/verity-handoff/docs/SPEC-session.md`) are synced to **draft-20**,
byte-identical (sha256 `621ff17e…a7e749`), and contain D19–D24, G-27, and G-28.
The repo copies are staged uncommitted, pending the user's go-ahead.

## Open item carried forward

- D24/RLS is bound (direction C). The rehearsal fallback, if the FORCE-RLS
  assertion or the role-GUC-in-replay proves fragile at room scale, is
  predicate-only with "why not RLS?" answered purely in the talk track. This is a
  contingency, not an open decision.
- **Two-artifact packaging** (frozen reference vs. participant starting state,
  per the Scaffolding section) needs a home before implementation: where the
  starting-state holes live relative to the frozen reference touches the sibling
  Workshop Studio repo's packaging. Flagged for the implementation plan, not
  resolved here.
