---
name: extend-hybrid-retrieval
description: Extend and diagnose Verity's Aurora PostgreSQL hybrid retrieval system. Use for source connectors, SourceObject ingestion, full-text or pgvector retrieval, pg_trgm fuzzy matching, RRF and SQL scoring, filters and ACLs, Cohere reranking, citations, retrieval receipts, evaluation, or failures where exact identifiers and semantic evidence rank incorrectly.
---

# Extend Hybrid Retrieval

Preserve one canonical retrieval implementation and its evidence receipts while
changing sources, signals, weights, or agent-facing contracts.

## 1. Classify the Evidence Path

Before editing code, classify each requested interaction:

| Path | Choose it when |
|---|---|
| **Materialize** | Approved evidence must participate in low-latency cross-source ranking, joins, citations, evaluation, or replay. |
| **Federate** | A source already exposes a suitable search, API, or MCP service, or its content should remain outside Aurora. |
| **Revalidate live** | State is volatile, permission-sensitive, or will drive a mutation or other action. |

One answer may combine all three. State the choice and its required receipt
before implementing.

## 2. Read the Owning Contract

Read only the references needed for the task:

- Source or synchronization change: `docs/ingestion-api.md`,
  `docs/connector-lifecycle.md`, `backend/app/models.py`,
  `backend/app/ingest.py`, and the relevant file in `connectors/`.
- Retrieval or scoring change: `sql/03_search_functions.sql`,
  `backend/app/search.py`, and `backend/app/models.py`.
- Citation or answer change: `backend/app/agent.py`,
  `backend/app/synthesis.py`, and `sql/04_diagnostics.sql`.
- Evaluation change: `backend/app/evaluation.py`, `sql/05_evaluation.sql`, and
  `sql/09_evaluation_metrics.sql`.
- Managed tool change: `backend/app/main.py`, `lambda_mcp/`, and
  `scripts/invoke_agentcore_gateway.py`.
- Inspection UI change: the API response owner first, then `frontend/src/`.

Run `make doctor` before relying on Aurora, Bedrock, the seed, or the live API.

## 3. Preserve the Retrieval Invariants

- Normalize materialized records into `SourceObject`; retain source system,
  external ID, URL, revision or cursor, content hash, ACL, metadata, and source
  authority.
- Use connector-scoped cursors. Apply `upsert` to deltas and `full` to snapshots.
  Tombstone missing records during full reconciliation.
- Skip unchanged bodies, rechunk changed bodies, and embed only chunks whose
  embedding is null. Keep stored and query embeddings in the same model space.
- Keep full-text, vector, and trigram retrieval in the canonical SQL functions.
  Apply filters and `ops.acl_visible` before candidates enter any arm.
- Fuse rank positions once through weighted RRF. Keep raw arm scores for
  diagnostics; do not add them again to `final_score`.
- Treat Cohere Rerank as a post-fusion ordering stage. Preserve both
  `rerank_score` and Aurora's `final_score`; neither is a probability.
- Persist `ops.retrieval_runs` and `ops.retrieval_candidates` before synthesis.
  Return the same `run_id` through HTTP, Strands tools, Gateway MCP, and UI.
- Build citations from retrieved source rows. Never invent evidence when the
  database or source is unavailable.
- Revalidate mutable facts and perform writes through the authoritative source.
- Use only PostgreSQL extensions supported by the target Aurora engine.

## 4. Validate the Failure and the Fix

Start with a failing query or receipt, then test the smallest relevant matrix:

| Concern | Proof |
|---|---|
| Exact identifier | A lexical query finds an ID or symbol that semantic-only retrieval misses. |
| Semantic recall | A paraphrase finds relevant evidence without exact token overlap. |
| Fuzzy matching | A controlled typo produces the intended candidate without dominating fusion. |
| Filters and ACLs | Restricted or out-of-scope objects never enter any retrieval arm. |
| Fusion | Per-arm ranks, RRF contribution, SQL score, and optional rerank score remain inspectable. |
| Citation | Every cited claim resolves to a real source object, URL, and supporting chunk. |
| Update | One source change invalidates and re-embeds only affected chunks. |
| Reconciliation | A missing object is tombstoned and excluded from new retrieval while history remains valid. |
| Replay | The returned `run_id` resolves to persisted candidates and diagnostics. |

Use repository commands where applicable:

```bash
make doctor
make schema
make smoke
make github-export
make github-sync
git diff --check
```

Do not run `make schema`, `make smoke`, or `make github-sync` without a configured
database. `github-sync` can also invoke the configured embedding provider.

## 5. Report the Receipt

Summarize the evidence-path choice, owning files changed, behavior before and
after, validation run, resulting `run_id` or connector receipt when available,
and any check that could not run.
