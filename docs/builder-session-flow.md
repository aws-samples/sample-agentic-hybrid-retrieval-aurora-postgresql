# Builder session flow

**Level: 400 (advanced).** The audience knows what pgvector and FTS are; the
session is about the retrieval *decisions* — fusion weighting, index tradeoffs,
lexical failure modes, and agent-tool boundaries — taught through a fail-then-fix
loop against one canonical query.

## 10–12 minute presentation

1. Hook: operational truth is scattered across conversations, tickets, docs, cases, and code.
2. Killer query: “Why did Orion slip, and which customer commitments are at risk?”
3. Show UI: landing, results, timeline, agent answer, diagnostics.
4. Show the failure first: run vector-only and watch `ORION-1489` (the exact metric-name paging ticket) get missed — motivate hybrid before building it.
5. Establish the evidence boundary: systems of record keep the work; Aurora makes approved evidence comparable for cross-system ranking, joins, citations, evaluation, and reproducible retrieval.
6. Explain Aurora PostgreSQL 18.3 as the lab retrieval index, provisioned by Workshop Studio and seeded before the hands-on path.
7. Frame hybrid retrieval as a set of tradeoffs, not a feature list: SQL filters, FTS (and its AND-semantics trap), pgvector + HNSW recall/latency, pg_trgm, RRF weighting, final scoring, citations.
8. Explain Strands Agent tools and where MCP/connectors fit for live lookups or actions.

## 45 minute hands-on (L400)

The environment is pre-provisioned: the API, PostgreSQL, and the seeded evidence
index are already up when the session starts, so the time goes to retrieval
decisions, not setup. Each module is a **fail-then-fix** beat — reproduce the
failure mode first, then fix it and watch the canonical query improve.

| Time | Module | What you build | Decision / failure explored |
|---:|---|---|---|
| 0–4 | Reproduce the retrieval gap | Vector-only baseline over the seeded corpus | Semantic-only misses `ORION-1489`, the exact metric-name paging ticket — why top-k embeddings alone underserve agentic retrieval |
| 4–12 | Make full-text survive natural language | FTS + SQL/metadata filters | `websearch_to_tsquery` defaults to AND-semantics and scores `text_rank = 0` on a natural-language question; fix with the `ops.to_or_tsquery` OR-combine rewrite, then narrow with SQL/metadata filters |
| 12–19 | Semantic recall and the HNSW tradeoff | pgvector cosine + HNSW index (`m=16, ef_construction=64`) | Index build cost vs recall vs query latency; when semantic wins and when it loses to lexical |
| 19–27 | Fuse the rankers with RRF | Reciprocal rank fusion + SQL final scoring | Why `k=60`; fusion beating any single ranker; the `0.55` cut and why ranker overlap is a good sign |
| 27–35 | Strands tools over a retrieval boundary | Agent-callable retrieval path over `ops.hybrid_search` and persisted evidence rows | Question decomposition + `object_links` traversal through real tool-shaped calls vs one monolithic prompt |
| 35–42 | Diagnostics as the proof surface | Funnel (150 → 92 → 24 → 12 → 6), per-ranker positions, latency breakdown, citation rows | Every number traces to a persisted row; the run is a replayable audit trail |
| 42–45 | Tradeoff clinic: break it | Toggle knobs live | Flip OR→AND, drop a retriever, retune `k`, raise the cut — and watch which citations move |

## Stretch options

- Live GitHub projection: ingest selected issues or PRs, update one source item,
  and rerun ingestion to prove that Aurora rebuilds while GitHub remains
  authoritative.
- Slack federated search.
- AppFlow-to-S3 ingestion.
- Production ingestion topology: batch export, webhook, CDC, or live MCP lookup.
- VS Code extension concept.
