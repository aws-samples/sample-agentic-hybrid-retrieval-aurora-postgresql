# Builder-session curriculum

## Session promise

Attendees will leave with a working hybrid product search pipeline in Aurora PostgreSQL, a measurable evaluation loop, and an engineering understanding of where FTS, `pg_trgm`, vector search, filters, fusion, reranking, and HNSW tuning each fit.

## Suggested 60-minute flow

| Time | Activity | Artifact |
|---:|---|---|
| 0–8 min | Cinematic product-discovery setup and architecture | Mosaic Discover screen |
| 8–18 min | Lab 1: lexical precision + typo tolerance | `05_typo_tolerance_lab.sql` |
| 18–31 min | Lab 2: semantic candidates + metadata filters | vector query + filtered HNSW |
| 31–43 min | Lab 3: RRF + rerank + evidence inspection + MCP checkpoint | `search_hybrid_rrf` + Retrieval Lab + typed tools |
| 43–56 min | Lab 4: HNSW recall/latency/filter selectivity | measured benchmark harness |
| 56–60 min | Production guardrails and takeaways | eval scorecard + next steps |

A 45-minute hands-on format can merge Labs 2 and 3 and use instructor-provided embeddings/indexes.

## Lab 1 — Find what the user typed, even when they typed it badly

Start query:

```text
noice canceling hedphones under 200 for long fligts
```

Progression:

1. FTS-only query exposes token mismatch.
2. `pg_trgm` recovers fuzzy title/brand/model/category candidates.
3. Threshold changes reveal recall-versus-noise behavior.
4. Exact model/SKU query demonstrates why fuzzy matching must not replace lexical precision.
5. Candidate provenance is retained for fusion and explainability.

## Lab 2 — Understand the purchase intent

Start query:

```text
headphones that make a long flight quieter without dying halfway through
```

Progression:

1. Exact vector baseline establishes ground truth for a small query set.
2. HNSW accelerates interactive retrieval.
3. SQL filters enforce price, stock, domain, and decisive JSON attributes.
4. Hard negatives reveal why similarity is not product eligibility.
5. Filter selectivity introduces iterative HNSW scans.

## Lab 3 — Fuse, rerank, and explain

Use three independent candidate lists:

- PostgreSQL FTS
- `pg_trgm`
- semantic HNSW

Apply RRF with `k=60`, then enrich with business signals without allowing popularity or sponsorship to override required constraints. Send the top candidate pool to a reranker, retain component scores, and render evidence for the final answer.

Close the lab with a four-to-five-minute MCP interoperability checkpoint:

1. connect a compatible host to the stateless MCP `2026-07-28` endpoint;
2. inspect the typed, read-only product tools;
3. run the same filtered product query through `search_products`;
4. inspect its persisted rank signals through `inspect_retrieval_run`.

This is not a separate protocol lab. It proves that Strands, the React UI, and
an MCP-compatible host can consume one canonical Aurora retrieval system.

Teaching comparison:

| Stage | Expected behavior |
|---|---|
| Lexical only | exact terms/models win; paraphrases and typos suffer |
| Semantic only | intent improves; exact model and hard constraints can drift |
| Lexical + semantic | stronger recall, but score scales are incomparable |
| RRF | robust rank fusion without score calibration |
| RRF + filters | product eligibility becomes explicit |
| RRF + rerank | nuanced relevance and hard negatives improve |
| Full pipeline | relevance, constraints, evidence, and diagnostics are visible |

## Lab 4 — HNSW is a workload, not a checkbox

Measure—not merely display—the effects of:

- dataset scale
- vector dimension
- `m`
- `ef_construction`
- `ef_search`
- result count (`k`)
- filter selectivity
- strict vs relaxed iterative scans
- warm vs cold cache
- concurrency
- index and table size

The 500K catalog is the hands-on baseline. The 1M/5M/10M/100M UI presets are either measured environments or explicitly labeled projections calibrated from the measured baseline.

## Final production lesson

The winning architecture is not “vector search.” It is a governed retrieval system:

```text
query understanding
  → lexical / typo / semantic candidate generation
  → relational eligibility filters
  → rank fusion
  → reranking
  → evidence + explanation
  → evaluation + telemetry
```
