# Intentional gaps

Authoritative manifest of what ships **deliberately broken** for participants to
repair.

## Status: the checked-in state ships NOTHING broken

Every defect found in the committed tree is a real defect. There is no
protected failure. If a lab check fails here, fix it.

The gaps themselves are defined and implemented **in this repository**:
`scripts/lab_state.py` holds each broken body next to its solved body, the
marker seams live in `db/sql/09_search_functions.sql` and
`service/agent_tools.py`, and `make reset-lab-N` performs the injection. The
Workshop Studio repository narrates the repairs and triggers `make reset-lab-1`
at provision time; it ships no starter template of its own. This document is
the authoritative manifest: a gap listed here is a gap `lab_state.py` must
implement, and a gap not listed here must not exist.

## Why the committed tree holds no broken code

`data/evals/mosaic_labs_missions.json` splits ownership:

| Repository | Owns |
|---|---|
| This one | lab contract, application surfaces, evaluation assertions, **gap seams and broken bodies** |
| Workshop Studio | participant instructions, provisioning-time gap injection, code-editor exercises |

The source application is the reference implementation: the state a participant
reaches when every repair succeeds. Disabling code here would make the reference
unable to demonstrate its own contract, and would make a genuine regression
indistinguishable from a planted exercise.

Re-verified 2026-08-11 for the three-lab `Retrieve -> Rank -> Reason` path. All
three repair capabilities are fully wired here.

| Lab anchor | Capability | Evidence it is live |
|---|---|---|
| `typo-recovery` | pg_trgm candidate arm | `db/sql/09_search_functions.sql:423-429` fuses `typo AS (SELECT * FROM mosaic_search.search_trigram(...))` between the `LAB1_TRIGRAM_CTE` markers |
| `rank-with-evidence` | reciprocal-rank contribution | `mosaic_search.reciprocal_rank_contribution` computes `1 / (k + rank)` |
| `agentic-research` | evidence-to-synthesis state | `service/agent_tools.get_product_evidence` records evidence IDs by product |

## Gap contract

Three lab anchors carry `checkpoint: "repair"`. Their narrative promises the
participant something to fix, so `make reset-lab-N` (backed by
`scripts/lab_state.py`) must remove exactly these capabilities and nothing
else. Workshop Studio invokes `make reset-lab-1` at provision time and narrates
the later resets.

### GAP-1 — typo-recovery arm

- **Lab 1 anchor** `typo-recovery` (`checkpoint: repair`, stage `retrieve`)
- **Query** `noice cancelng hedfones`
- **Target** product 2, Sonora WH-C720 Wireless Noise-Cancelling Headphones
- **What to disable** the `typo` CTE in `mosaic_search.search_hybrid_rrf`, so the
  fusion receives only the FTS and vector arms. Leave
  `mosaic_search.search_trigram` itself installed and callable: the lesson is
  that a working arm is not contributing, not that a function is missing.
- **Restoring it looks like** adding the `typo` CTE back to the `channels` union
  with its `mosaic_search.reciprocal_rank_contribution(trigram_rank, rrf_k)`
  contribution — the exact seam text in `scripts/lab_state.py`, which the
  validator compares literally.
- **Assertion that turns green** `trigram_signal_present`
- **Board state before repair** `REPAIR PENDING`, never `FAIL`

### GAP-2 — reciprocal-rank contribution

- **Lab 2 anchor** `rank-with-evidence` (`checkpoint: repair`, stage `rank`)
- **Query** `ergonomic mesh chair for long workdays with adjustable lumbar support`
- **Target** product 370002, PostureWorks Pro Mesh Ergonomic Chair
- **What to disable** replace the marked `1 / (rrf_k + source_rank)` body with
  `1 / (rrf_k + 1)`. Candidate generation remains intact, but every candidate
  from an arm contributes as if it held rank 1, so within-arm order disappears.
- **Restoring it looks like** restoring the inspectable reciprocal-rank formula.
- **Measured movement** broken fusion orders 370001 then 370002 even though
  370002 wins all three arms; repaired fusion orders 370002 then 370001. Cohere
  Rerank returns 370002 then 370001 in both states, deliberately demonstrating
  why every ranking layer needs its own validation.
- **Assertions that turn green** `rank_provenance_present`,
  `rerank_score_present`, plus the production validator's arithmetic and
  repeatability checks.
- **Board state before repair** `REPAIR PENDING`

### GAP-3 — evidence-to-synthesis state

- **Lab 3 anchor** `agentic-research` (`checkpoint: repair`, stage `reason`)
- **Query** the canonical compound home-office request in the mission manifest
- **Targets** products 370001 and 429001
- **What to disable** remove the marked state update that records retrieved
  evidence IDs under their product. All tools remain registered and read-only.
- **Restoring it looks like** attaching each returned evidence record to
  `state["evidence"]` and `state["evidence_by_product"]`.
- **Assertions that turn green** evidence tool, grounding, and resolvable
  citation assertions declared by the mission.
- **Board state before repair** `REPAIR PENDING`

## Rules

1. A gap must expose one legible mechanism, never an arbitrary failure. The
   marked CTE, RRF equation, and evidence-state block are the only seams.
2. A gap must map to at least one assertion, so repair is machine-checkable.
3. Only `checkpoint: "repair"` lab anchors may carry gaps. `baseline`,
   `comparison`, and `advanced` checks must pass on a correct deployment.
4. The lab board renders a listed, unrepaired gap as `REPAIR PENDING`. Any
   failure not listed here renders `FAIL` and is a real regression.
5. Adding a gap requires listing it here and implementing its seam markers and
   broken body in `scripts/lab_state.py` first. The sibling only narrates and
   triggers gaps; it never defines one.

## Non-gaps

Defects found and fixed in the Phase 1 pass. None was ever intentional; they are
recorded so nobody reclassifies a fixed bug as an exercise.

| Defect | Why not a gap | Fix |
|---|---|---|
| `BUSINESS_WEIGHT=0.15` exceeding the 0.05 bound | crashed every search with an unhandled 500; no assertion covers it and no repair narrative mentions it | `service.config.ConfigurationError` refuses out-of-range values at startup; `tests/test_service_config.py` |
| `search_fts` AND-only query construction | broke the missions that then declared `fts`, and no `fts_signal_present` assertion existed to detect it | `search_fts` keeps the strict `websearch_to_tsquery` match, then backs off to an AND query (`&`-joined) over at most four salient lexemes when the strict match returns nothing: longest lexemes first, numeric-only lexemes dropped, filtered through an intent stoplist, and kept only when the corpus contains them. There is no OR-combine and no negation guard; `fts_signal_present` added to `service/assertions.py` |
| MCP `/retrieval/runs/` path | route never existed; nothing to restore | tool requests `/retrieval/events/{id}`; `tests/test_mcp_route_contract.py` resolves it against the real route table |
| `sql/05_typo_tolerance_lab.sql` targeting `catalog.*` | taught against a schema the API does not read | ported to `db/sql/lab_01_typo_tolerance.sql` against `mosaic_search` |

All four were measured on the live 500,000-product Aurora cluster before and
after the fix. The shipped `search_fts` left four of the six missions with an
empty lexical arm; the fix runs the strict `websearch_to_tsquery` match first,
and only when that returns zero rows backs off to a conjunctive query over at
most four corpus-present salient terms, so every mission's lexical arm gets a
pool instead of an empty result. `catalog.*` does not exist on that cluster,
which is why a lab targeting it could never teach anything.
