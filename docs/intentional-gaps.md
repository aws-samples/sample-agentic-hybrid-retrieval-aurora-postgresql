# Intentional gaps

Authoritative manifest of what ships **deliberately broken** for participants to
repair.

## Status: this repository ships NOTHING deliberately broken

Every defect found in this repository is a real defect. There is no protected
failure. If a lab check fails here, fix it.

This document exists as the **forward contract** for the Workshop Studio
repository, which injects the gaps. It is authoritative in one direction: a gap
listed here is a gap the sibling is expected to create in its starter template,
and a gap not listed here must not be created.

## Why the source repository holds none

`data/evals/mosaic_labs_missions.json` splits ownership:

| Repository | Owns |
|---|---|
| This one | lab contract, application surfaces, evaluation assertions |
| Workshop Studio | participant instructions, **deliberate starter gaps**, code-editor exercises |

The source application is the reference implementation: the state a participant
reaches when every repair succeeds. Disabling code here would make the reference
unable to demonstrate its own contract, and would make a genuine regression
indistinguishable from a planted exercise.

Re-verified 2026-08-11 for the three-lab `Retrieve -> Rank -> Reason` path. Both
repair-checkpoint capabilities are fully wired here, and both stable IDs remain
anchors for required labs, so neither gap needed rehoming.

| Lab anchor | Capability | Evidence it is live |
|---|---|---|
| `typo-recovery` | pg_trgm candidate arm | `db/sql/09_search_functions.sql:244` fuses `typo AS (SELECT * FROM mosaic_search.search_trigram(...))` |
| `agentic-research` | typed retrieval tool | `service/agent_tools.py:522` registers all five `@tool` functions |

## Gap contract for Workshop Studio

Two lab anchors carry `checkpoint: "repair"`. Their narrative promises the
participant something to fix, so the sibling's starter template must remove
exactly these capabilities and nothing else.

### GAP-1 — typo-recovery arm

- **Lab 1 anchor** `typo-recovery` (`checkpoint: repair`, stage `retrieve`)
- **Query** `wirless noice canceling hedphones under $200 with long batery life`
- **Target** product 2, Sonora WH-C720 Wireless Noise-Cancelling Headphones
- **What to disable** the `typo` CTE in `mosaic_search.search_hybrid_rrf`, so the
  fusion receives only the FTS and vector arms. Leave
  `mosaic_search.search_trigram` itself installed and callable: the lesson is
  that a working arm is not contributing, not that a function is missing.
- **Restoring it looks like** adding the `typo` CTE back to the `channels` union
  and its `1.0 / (rrf_k + trigram_rank)` contribution.
- **Assertion that turns green** `trigram_signal_present`
- **Board state before repair** `REPAIR PENDING`, never `FAIL`

### GAP-2 — typed agent tool

- **Lab 3 anchor** `agentic-research` (`checkpoint: repair`, stage `reason`)
- **Query** `Build a quiet home office under $800 and explain the trade-offs.`
- **Targets** products 370001 and 429001
- **What to disable** remove `search_products` from
  `service/agent_tools.TOOL_FUNCTIONS`, leaving the decorated function defined.
  The agent then has no way to gather evidence and must report the gap rather
  than answer from model memory.
- **Restoring it looks like** re-registering `search_products` in
  `TOOL_FUNCTIONS`.
- **Assertions that turn green** `retrieval_tool_called`, `citations_present`,
  `citation_source_revision_present`
- **Board state before repair** `REPAIR PENDING`

## Rules

1. A gap must be **removal of a wiring point**, never a planted bug. Deleting a
   CTE or a registration is legible; a wrong constant is a puzzle.
2. A gap must map to at least one assertion, so repair is machine-checkable.
3. Only `checkpoint: "repair"` lab anchors may carry gaps. `baseline`,
   `comparison`, and `advanced` checks must pass on a correct deployment.
4. The lab board renders a listed, unrepaired gap as `REPAIR PENDING`. Any
   failure not listed here renders `FAIL` and is a real regression.
5. Adding a gap to the sibling requires adding it here first.

## Non-gaps

Defects found and fixed in the Phase 1 pass. None was ever intentional; they are
recorded so nobody reclassifies a fixed bug as an exercise.

| Defect | Why not a gap | Fix |
|---|---|---|
| `BUSINESS_WEIGHT=0.15` exceeding the 0.05 bound | crashed every search with an unhandled 500; no assertion covers it and no repair narrative mentions it | `service.config.ConfigurationError` refuses out-of-range values at startup; `tests/test_service_config.py` |
| `search_fts` AND-only query construction | broke two missions that declare `fts`, and no `fts_signal_present` assertion existed to detect it | `search_fts` OR-combines lexemes with a strict-match bonus and a negation guard; `fts_signal_present` added to `service/assertions.py` |
| MCP `/retrieval/runs/` path | route never existed; nothing to restore | tool requests `/retrieval/events/{id}`; `tests/test_mcp_route_contract.py` resolves it against the real route table |
| `sql/05_typo_tolerance_lab.sql` targeting `catalog.*` | taught against a schema the API does not read | ported to `db/sql/lab_01_typo_tolerance.sql` against `mosaic_search` |

All four were measured on the live 500,000-product Aurora cluster before and
after the fix. The shipped `search_fts` left four of the six missions with an
empty lexical arm; the fix gives every mission a pool and holds exact identity at
rank 1 by 2.5x. `catalog.*` does not exist on that cluster, which is why a lab
targeting it could never teach anything.
