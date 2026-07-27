# DAT410 co-speaker review brief (draft-13)

One page. Read `docs/SPEC-session.md` Section 0 (laws + labs), Section 1 (decisions
D1–D18), and the run-of-show in Section 8 — about 15 minutes. Everything else is
implementation detail the build will validate against gates G-1..G-24.

## How to give feedback
- Challenge by **decision number** ("D11 is wrong because…"), not by vibe — decisions
  carry their rationale, so attack the rationale.
- Propose changes as **gate changes** where possible ("G-6 window should be 180–300 s").
- The 13 open items (Section 13) are already known: cluster-dependent, not oversights.
- Silence on a decision = consent. This spec freezes after this review round.

## The five decisions most worth attacking
- **D9** — incident gets ≤ 19 of 45 min. Too much on-ramp? Too little?
- **D11** — engine-first: Hybrid retrieval (Lab 2) before Agentic (Lab 3). Anyone who'd
  argue agent-first should argue it now.
- **D13** — single LLM, Sonnet-class, no Opus, no fallback LLM. "Sonnet is enough" is a
  stage claim; challenge it if you wouldn't say it aloud.
- **D15** — AgentCore = Gateway-only optional module (M5); Policy/Identity/Runtime are
  slides. If the track pushes back, this is the line we defend.
- **D18** — final checkpoint: participants install the skill in Claude Code and run its
  first assertion in the last 2 minutes. Feasible at room scale?

## Per-reviewer asks
- **Grant**: the Aurora claims — exclusives E3/E4/E5 (wait-event seam; ReplicaLag as
  page-cache lag; orcache plan tiers), the G-6 build-calibration window (240–420 s,
  single worker, 64 MB maintenance_work_mem on the target class), and the open item 10
  call: add a reader (E4 becomes a measured demo — likely new public material) or not.
  Also: audit the audit — is M2 ("room picks any number") airtight from your seat?
- **Whoever runs ops/infra**: bootstrap S1–S9 realism, DBI Advanced enablement + pricing
  (open item 1), participant IAM (item 4), tab-4 exposure (item 9).
- **Everyone**: run the 45-min run-of-show against your own delivery pace; name what you'd
  cut at 35 minutes (the cut-ladder must be decided before rehearsal, D9); sanity-check
  the four takeaway sentences (D18) — they become the skill's section headers verbatim.
- **Floor roles (D10)**: F1/F2/F3 need names. Volunteer or be assigned.

## What's already verified (don't re-litigate without new evidence)
Fixture arithmetic on a live engine (D14: CGH-1842 unique at 0.500; CHG-1482 is a
six-way tie — the base spec still needs its one-line fix), the integer-division RRF
zero, the trigram index trap, sizing (Section 3.0), and the loadgen rates.
