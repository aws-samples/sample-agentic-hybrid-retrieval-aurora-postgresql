# Verity — final Codex implementation package

This package is the implementation source of truth for the DAT410 builders' session:

**Build agentic hybrid retrieval with Amazon Aurora PostgreSQL**

It consolidates:

- the current implementation specification;
- the strongest UI concepts from Ask, Retrieval Lab, Fusion, Plan X-Ray, Evaluation, and Evidence Graph;
- the simplified workshop identifier scheme;
- a three-module participant journey;
- a deliberately narrow Amazon Bedrock AgentCore Gateway capstone;
- final OpenAPI/MCP tool contracts and contract-parity acceptance tests.

## Final session shape

1. **Retrieve the evidence**
   - exact/B-tree and PostgreSQL full-text search;
   - filtered `pgvector` HNSW;
   - `pg_trgm` typo recovery;
   - ACL and metadata filters inside every arm.

2. **Fuse, traverse, and prove**
   - weighted reciprocal rank fusion;
   - optional model reranking without overwriting Aurora diagnostics;
   - typed relationship traversal;
   - cited answer and replayable proof receipt;
   - Query Plan X-Ray and CloudWatch Database Insights handoff.

3. **Port the tool contracts**
   - the same canonical Python implementations through:
     - HTTP/FastAPI;
     - local stdio MCP;
     - a pre-provisioned Amazon Bedrock AgentCore Gateway OpenAPI target.
   - participants verify semantic parity; they do not provision Gateway, IAM, or OAuth.

## Start here

1. Read `REPAIR-REPORT.md` — what was wrong with the first pass and what changed.
2. Read `docs/VERITY-COMPLETE-CODEX-SPEC.md`. §9–§13 now carry runnable DDL and SQL.
3. Give Codex `CODEX_PROMPT.md`.
4. Use `ui/verity-workbench.html` as the visual reference. Do **not** use
   `reference/superseded/` — that is the pass whose RRF values did not reproduce.
5. Use `contracts/openapi/verity-tools.openapi.yaml` as the transport-neutral tool contract.
6. Use `fixtures/` for deterministic development and tests.
7. Run `python3 scripts/verify_contract_parity.py` — it should pass today, against the shipped captures.

## Every number is derived

No RRF value, rank or golden is authored anywhere. `fixtures/generate.py` is the single
source of truth; the only hand-written numbers in the package are per-arm **orderings**,
raw diagnostics, and rerank scores. Everything else is computed, and the generator refuses
to emit unless ten assertions hold — including that no two candidates tie on `rrf_score`,
and that the fuzzy arm never fires when every identifier token resolved exactly.

```
fixtures/generate.py  →  canonical-scenario · retrieval-presets · runs/RUN-700*.json
                      →  captures/*.json · tool-parity-golden.json · ui-model.json
                      →  ui/build.py  →  ui/verity-workbench.html
```

Regenerate and rebuild after any change:

```bash
python3 fixtures/generate.py          # emits every fixture, self-asserting
python3 ui/build.py                   # regenerates first, then builds the workbench
python3 scripts/verify_contract_parity.py
```

The workbench recomputes the golden fixture in the browser on load and reports the result
in the footer badge. If a displayed number ever drifts from its own formula again, the
page says so on screen rather than looking plausible.

## Important scope decisions

- Aurora PostgreSQL remains the only retrieval and proof authority.
- AgentCore Gateway is a portability capstone, not a second retrieval engine.
- The Gateway is pre-provisioned for the workshop.
- No live connectors, OAuth setup, infrastructure provisioning, or vector generation belongs in the participant path.
- The former Scale page is reference-only and is not part of the core workbench.
- All timings are illustrative until replaced with target-Aurora release-gate measurements.
