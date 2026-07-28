# CLAUDE.md — Hybrid Retrieval Workbench / DAT410 session build

You are building the assets for a re:Invent builders session: a live PostgreSQL locking
incident (Lab 1), inspected in Database Insights, then investigated through Hybrid Retrieval Workbench —
an agentic hybrid-retrieval system where Aurora PostgreSQL is the retrieval engine of
record (Labs 2–4). Four browser tabs, four labs, engine-first.

## Documents and precedence

1. **`docs/SPEC-session.md`** (draft-9) — THE CONTRACT for everything session-shaped:
   bootstrap stages S1–S9, shop schema, incident/loadgen scripts, Database Insights
   enablement, workbench deltas, agent & tooling stack (Section 7, T1–T12), guide,
   run-of-show, gates G-1..G-22, decisions D1–D15.
2. **`docs/verity-implementation-spec.md`** — authoritative for Hybrid Retrieval Workbench core: the
   casework/retrieval/proof schemas, the six tool contracts, the /v1 API, the base
   workbench (its Section 13), models, fixtures, evaluation.
   **KNOWN DEFECT — do not implement as written:** its `fuzzy-change-id` acceptance
   uses `CHG-1482`, which is a measured six-way trigram tie (similarity 0.3846 against
   every `chg-1*` record). Session-spec **D14 overrides**: the typo fixture is
   **`CGH-1842`** (letter transposition; measured 0.5000, runner-up 0.2000).
3. **`docs/verity-ui-design-system.md`** — visual language reference (tokens,
   components, data-display conventions).
4. **`reference/concept-screens/*.html`** — seven talk/deck mockups. **Reference only.
   Never port into the workbench**: they use remote fonts (forbidden in the shipped
   workbench) and illustrative numbers (forbidden everywhere in the lab surface).

Conflict rule: the session spec governs session assets; the implementation spec governs
Hybrid Retrieval Workbench core; explicit D-series decisions (D13, D14, D15) override both.

## Definition of done

**Gates, not vibes.** A task is complete when its gates (SPEC-session Section 10,
G-1..G-22) pass — not when code exists. Build the gate harness early; G-5, G-9, G-13,
G-14, G-17, G-18, G-21 are test-shaped and should exist before the code they test.

## Non-negotiable rules

- **Law 1 — same nouns everywhere.** `shop.orders`, `customer_id`,
  `idx_orders_customer`, `Lock:relation`, `CHG-1842`, `INC-2047`, `CGH-1842`,
  `checkout-prod-cluster-01`, lab names verbatim (D12). G-11 lints for synonyms.
- **Law 2 — psql parity.** Nothing renders in the workbench that cannot be reproduced
  from psql with a `run_id`. Every data panel returns `_verify_sql` generated from the
  same query registry the endpoint executes. The empty-database test (G-14) must pass:
  zero fixture numerals in the built frontend bundle.
- **Never hand-type derived numbers.** RRF scores, similarities, orderings, and sizing
  figures are generated and asserted (the `fixtures/generate.py` pattern; G-21). A
  number that cannot be recomputed is a defect.
- **One tool registry.** `agent/registry.py` is the single source; Strands tool specs,
  the stdio MCP server, and the Gateway Lambda-target tool schemas are all generated
  from it (G-17). Never hand-edit a generated artifact.
- **`[VERIFY ...]` markers are blockers, not invitations to guess.** Do not invent CLI
  flags, console URL formats, IAM action lists, or version numbers — surface the item
  and stop.
- **Flags default off / safe:** `VERITY_LIVE_CAPTURE=0`, `VERITY_GATEWAY=0`,
  `VERITY_AGENT_MODE=planned`. Bootstrap force-disables a flag on any failure.
- **Exactly three model IDs (D13):** `us.cohere.embed-v4:0` (pin
  `output_dimension=1024` on BOTH ingest and query), `cohere.rerank-v3-5:0` via
  bedrock-agent-runtime Rerank, `claude-sonnet-5` via Converse. No others, no fallback
  LLM — the zero-model degradation path is extractive synthesis + replay.
- **Overview-first IA (D16):** primary nav mirrors the labs — Overview / Retrieval /
  Agent / Proof; Corpus, Evaluation, Health are utility nav. Guide routes are contract:
  `/overview`, `/retrieval?preset=…`, `/agent?principal=…`, `/proof/{run_id}` (G-23).
  The base spec's tab shell is superseded; its panel contracts are not.
- **The agent executes plans; it does not choose tools** in the lab path (T2).
  `explain_ranking` and `synthesize_cited_answer` descriptions are guardrails (T7).

## Workflow

- Verify loop: write → run → assert, every task. Stand up a local PostgreSQL with
  `pgvector` and `pg_trgm` for anything arithmetic; outputs captured for the guide are
  captured verbatim (G-20).
- The M5 Gateway Lambda is a **thin forwarder** to `/v1` (~50 lines) — never a second
  tool implementation (T6).
- Open items (SPEC-session Section 13, eleven of them) require a real Aurora cluster.
  Do not simulate their answers.

## Suggested build order

1. `agent/registry.py` + the six tools + canonical SQL + `_verify_sql` registry
2. `gates/` harness (checks.sh, empty-DB UI test, verify-SQL golden, registry drift)
3. `bootstrap/` stages S1–S9 (idempotent, stage-markered)
4. `shop/` DDL + seed, `incident/` script family + loadgen (three pgbench units)
5. Workbench deltas (Section 6): live banner, verify-in-psql, observability_refs
6. `guide/` (snippets extracted from repo sources at build time — G-12)
7. Flagged modules: `capture/`, `mcp/gateway_forwarder.py`
8. LAST, at content freeze: `skills/aurora-hybrid-retrieval/` (D17) — SKILL.md + SQL
   templates + gotcha registry + eval scripts, distilled from the final guide and gates.
   The skill's first instruction to its consumer: run the shipped assertions.
   Its four section headers are the four lab takeaway sentences, verbatim (D18/G-24).

## Target layout

See SPEC-session Section 3 for the repo tree. This file lives at the repo root.
