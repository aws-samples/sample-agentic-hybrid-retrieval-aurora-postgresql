# Builder-session curriculum

## Session promise

Attendees will leave with a working hybrid product search pipeline in Aurora PostgreSQL, a measurable evaluation loop, and an engineering understanding of where FTS, `pg_trgm`, vector search, filters, fusion, reranking, and HNSW tuning each fit.

## Session flow

`data/evals/mosaic_labs_missions.json` is the single source for the session
shape and every timing below; `make validate-missions` fails if this table and
that file disagree. Three timed exercises, not six — six averaged 6.7 minutes
each with zero slack for questions or a throttled Bedrock call.

| Time | Activity | Mission | Artifact |
|---:|---|---|---|
| 0–2 min | Orientation | — | Mosaic Discover screen |
| 2–13 min | Recover a misspelled request | `typo-recovery` | `db/sql/lab_01_typo_tolerance.sql` |
| 13–25 min | Make the order defensible | `rank-with-evidence` | `search_hybrid_rrf` + the fusion comparison |
| 25–36 min | Produce a cited recommendation | `agentic-research` | typed agent tools + citations |
| 36–40 min | Guardrails and takeaways | — | eval scorecard + next steps |

**40 nominal, 45 hard ceiling, and the 40-to-45 band is never programmed.** It
absorbs a throttled model call or a room that asks questions; a plan that spends
it has no buffer, only a longer session.

Three further exercises ship **self-paced**, with the same contract and the same
assertions: `exact-identity` (3 min), `semantic-eligibility` (9 min), and
`hnsw-performance` (8 min). They are off the clock, not out of the workshop —
index tuning in particular needs a benchmark run to say anything honest, and
that cannot be done in four minutes.

The lab material below is organised by technique rather than by clock position,
so it exceeds the timed session on purpose. Lab 1 maps to `typo-recovery`, Labs 2
and 3 to `rank-with-evidence`, Lab 4 to the self-paced `hnsw-performance`.

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

### MCP interoperability — self-paced, not timed

The MCP checkpoint is **not** part of the timed room budget. It needs a second
process and an external MCP-compatible host inside a four-to-five-minute slot,
against a 45-minute hard ceiling, and its failure mode is environmental — host
not connected, port occupied — which reads to a room as "the retrieval system is
broken" when it is not.

The capability ships and is fully supported: run `make mcp-serve` and follow
`docs/mcp-interoperability.md` to

1. connect a compatible host to the stateless MCP `2026-07-28` endpoint;
2. inspect the typed, read-only product tools;
3. run the same filtered product query through `search_products`;
4. inspect its persisted rank signals through `inspect_retrieval_run`.

This is not a separate protocol lab. Its purpose is to prove that Strands, the
React UI, and an MCP-compatible host can consume one canonical Aurora retrieval
system — which the appendix proves without consuming timed minutes.

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
