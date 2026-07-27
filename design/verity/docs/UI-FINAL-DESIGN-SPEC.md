# Final Verity UI design

## Final information architecture

Use three top-level modules:

1. **Retrieve**
2. **Prove**
3. **Port tools**

This replaces the seven equal-weight Ask/Lab/Fusion/Plan/Eval/Graph/Scale navigation.

## Design sources retained

### From Retrieval Lab

- exact/FTS, semantic, fuzzy, and fused columns;
- preset queries;
- principal and rerank toggles;
- per-row receipt inspection;
- legitimate empty-arm state.

### From Fusion

- interactive `k` and arm weights;
- RRF versus naive score-sum comparison;
- separate Aurora RRF and model rerank;
- no probability language.

### From Ask & Decompose

- deterministic plan;
- cited answer;
- tool-stage thread;
- principal behavior;
- replay receipt.

### From Evidence Graph

- canonical versus inferred edges;
- ACL at every hop;
- source comparison verdicts;
- traversal metrics separate from retrieval.

### From Plan X-Ray

- one Aurora statement;
- B-tree, GIN FTS, HNSW, trigram, and fuse nodes;
- transaction-local `ef_search` and iterative scan;
- SQL/EXPLAIN panel;
- explicit plan type;
- Database Insights handoff.

### From Evaluation

- mode leaderboard;
- per-archetype ablation;
- traversal metrics separate.

### Removed

- Scale from core navigation;
- Optimized Reads interactive toggle;
- external fonts;
- old identifiers;
- old Threadline landing/product copy;
- separate Managed KB or connector lanes.

## Module 1 screen — Retrieve

### Header

- query bar;
- preset selector;
- principal;
- rerank;
- search index ready status.

### Main body

Four columns:

1. exact + full-text;
2. semantic;
3. fuzzy;
4. fused RRF.

### Lower drawer

- RRF formula;
- weights and `k`;
- candidate receipt;
- raw diagnostics;
- selected evidence metadata;
- ACL decision.

## Module 2 screen — Prove

Internal tabs:

- Answer
- Graph
- Plan
- Receipt

### Answer

- canonical question;
- deterministic plan;
- cited answer;
- source chips;
- source comparison.

### Graph

- incident/change/lock/case/runbook nodes;
- canonical solid edges;
- inferred dashed clay edges;
- principal and depth controls.

### Plan

- stage budget;
- Aurora retrieval arms;
- SQL/EXPLAIN;
- plan type label;
- `ef_search`;
- iterative scan;
- Database Insights plan and lock-tree actions.

### Receipt

- `RUN-7000`;
- query, controls, principal;
- candidates;
- stages;
- citations;
- timeline;
- search index health;
- compact evaluation.

## Module 3 screen — Port tools

Three transport cards:

1. HTTP/FastAPI
2. stdio MCP
3. AgentCore Gateway

Center/shared panel:

- contract version;
- OpenAPI operation IDs;
- selected tool;
- sample request;
- normalized response digest.

Bottom parity matrix:

- contract version;
- evidence order;
- arm positions;
- ACL-visible set;
- citations;
- proof reference;
- status.

## Visual tokens

```css
--paper: #FAF4EC;
--ink: #211C16;
--ink-soft: #584F45;
--muted: #94897C;
--hair: #E9DFD2;
--red: #C13A26;
--red-deep: #9E2F1E;
--wash: #FBEDE8;
--green: #2E7D54;
--clay: #DE9C7C;
```

## Typography

Use local/system stacks:

- serif: Georgia/Cambria for assertions;
- sans: system UI for prose;
- mono: system monospace for database-returned values.

No remote fonts.

## Semantic rules

- red = evidence thread;
- green = confirmed finding, including a ruled-out alternative;
- clay = semantic/inferred fill or stroke only;
- dashed/muted = absent;
- ACL-hidden evidence is removed;
- raw scores are diagnostic;
- no confidence rings;
- no score is a probability.

## Accessibility

- visible focus;
- reduced motion;
- color plus text/dash/glyph;
- `--muted` only for supporting information;
- no document-level horizontal overflow;
- internal scroll for wide tables.
