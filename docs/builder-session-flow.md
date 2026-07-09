# Builder session flow

## 10–12 minute presentation

1. Hook: operational truth is scattered across conversations, tickets, docs, cases, and code.
2. Killer query: “Why is Project Orion delayed, what did the team decide in Slack, and what customer commitments are impacted?”
3. Show UI: landing, results, source trail, agent answer, diagnostics.
4. Explain why vector-only search fails.
5. Explain PostgreSQL as the lab retrieval system of record, with localhost and Aurora PostgreSQL 18.3 using the same schema path.
6. Explain hybrid retrieval: SQL filters, FTS, pgvector, pg_trgm, RRF, rerank, citations.
7. Explain agent tools.

## 45 minute hands-on

| Time | Module | Output |
|---:|---|---|
| 0–5 | Environment check | API and PostgreSQL reachable |
| 5–12 | Ingest source bundle | Objects, chunks, citations, and links in PostgreSQL |
| 12–18 | Inspect schema | Source objects and chunks understood |
| 18–25 | Full-text + SQL filters | Lexical retrieval works |
| 25–31 | pgvector semantic retrieval | Semantic matches found |
| 31–37 | Hybrid RRF ranking | Blended ranked results |
| 37–42 | Agent answer | Cited answer from retrieval tools |
| 42–45 | Diagnostics + UI | Scoring and evidence trail visible |

## Stretch options

- Live GitHub connector.
- Slack federated search.
- AppFlow-to-S3 ingestion.
- Optional MCP wrapper.
- VS Code extension concept.
