# Three-module participant plan

## Whole-session budget

60 minutes end to end: 3 arrival and environment check, 10 presentation, 40 hands-on,
5 replay and production boundary, 2 reserve.

Module ranges below are the acceptable envelope. The plan is 13 / 19 / 8 = 40 minutes.
Overrun is absorbed by the cut ladder, not by the reserve. See spec §15.

## Presentation — 10 minutes

1. **Question and answer** — 90 seconds
2. **Why hybrid** — 90 seconds
3. **Aurora architecture** — 2.5 minutes
4. **Plans, locks, and receipts** — 2 minutes
5. **Three-module lab** — 1.5 minutes
6. **Portability preview** — 1 minute

## Module 1 — Retrieve the evidence

**Time:** 12–14 minutes

### Participant tasks

- inspect the corpus and principal;
- execute exact/FTS search;
- run semantic symptom search;
- run fuzzy ID recovery;
- inspect ACL filtering;
- view independent arm ranks.

### Required edits

Keep authoring small:

- add cluster/time/ACL predicates to starter FTS SQL;
- configure HNSW runtime settings;
- execute the predefined fuzzy query.

### Checkpoint

```text
CHG-1000 lexical rank 1
INC-2000 and LOCK-3000 appear for semantic symptoms
CGH-1000 resolves to CHG-1000 as the only trigram hit
CASE-4001 is absent
```

## Module 2 — Fuse, traverse, and prove

**Time:** 18–20 minutes

### Participant tasks

- complete weighted RRF;
- compare it to naive score sum;
- run the canonical answer path;
- traverse relationships;
- inspect citations;
- load `RUN-7000`;
- inspect Plan X-Ray;
- open Database Insights links when available.

### Required edit

```sql
  COALESCE(:text_weight   / (:rrf_k + text_position),   0)
+ COALESCE(:vector_weight / (:rrf_k + vector_position), 0)
+ COALESCE(:fuzzy_weight  / (:rrf_k + fuzzy_position),  0)
```

Bound at the defaults `2.0 : 1.0 : 1.0` and `rrf_k = 60`, this is:

```sql
  COALESCE(2.0 / (60 + text_position), 0)
+ COALESCE(1.0 / (60 + vector_position), 0)
+ COALESCE(1.0 / (60 + fuzzy_position), 0)
```

Weights must be numeric. `2 / (60 + 1)` is integer division and evaluates to `0`.

### Checkpoint

```text
CHG-1000 confirmed
CHG-1001 ruled out
CASE-4000 affected
CASE-4002 unaffected
five citations valid
RUN-7000 replays
```

## Module 3 — Port the tool contracts

**Time:** 7–9 minutes

### Participant tasks

- inspect `contracts/openapi/verity-tools.openapi.yaml`;
- identify how `operationId` maps to MCP tool names;
- call `search_evidence` over HTTP;
- call the local stdio MCP adapter or use captured output;
- call the pre-provisioned AgentCore Gateway endpoint or use captured output;
- run parity verification.

### Checkpoint

```text
contract version matches
candidate order matches
arm positions match
visible evidence set matches
citation IDs match
transport traces differ
```

## First cuts

1. RRF slider experimentation
2. detailed evaluation
3. Module 3

Never cut:

- ACL proof
- cited answer
- replay receipt
