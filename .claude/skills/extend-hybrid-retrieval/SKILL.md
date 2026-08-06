---
name: extend-hybrid-retrieval
description: Extend and diagnose Hybrid Retrieval Workbench's Aurora PostgreSQL incident-evidence retrieval. Use for search index builds, full-text or pgvector retrieval, pg_trgm fuzzy matching, filters and ACLs, weighted RRF, Cohere reranking, citations, receipts, traversal, or evaluation.
---

# Extend Hybrid Retrieval

Preserve one canonical retrieval implementation, one derived search index, and
replayable proof while changing evidence, signals, weights, or agent contracts.

## 1. Classify the Evidence Path

| Path | Choose it when |
|---|---|
| **Materialize** | Approved evidence must participate in low-latency ranking, joins, citations, evaluation, or replay. |
| **Federate** | A source already exposes suitable search or its content should remain outside Aurora. |
| **Revalidate live** | State is volatile, permission-sensitive, or will drive an action. |

The workshop implements the materialized path. Do not simulate an unimplemented
connector or mutation.

## 2. Read the Owning Contract

- Source or search index change: `docs/ingestion-api.md`,
  `docs/connector-lifecycle.md`, `evidence.v_evidence_documents` in
  `sql/01_schema.sql`, `sql/10_admission.sql`,
  `labs/incident/run_live_workshop.py`, and `backend/app/search_index.py`.
- Retrieval or scoring change: `sql/03_search_functions.sql`,
  `backend/app/search.py`, and `backend/app/models.py`.
- Citation or answer change: `backend/app/agent.py`,
  `backend/app/synthesis.py`, `sql/04_diagnostics.sql`, and
  `sql/06_receipts.sql`.
- Evaluation change: `backend/app/evaluation.py`, `sql/05_evaluation.sql`, and
  `sql/09_traverse_evidence.sql`.
- Managed tool change: `backend/app/main.py`, `lambda_mcp/`, `mcp-server/`, and
  `scripts/invoke_agentcore_gateway.py`.
- Inspection UI change: the API response owner first, then `frontend/src/`.

Run `make doctor` before relying on Aurora, Bedrock, the search index, or the live
API.

## 3. Preserve the Invariants

- `evidence.*` is authoritative. `retrieval.*` is derived and never hand-edited.
- Stable evidence IDs, source URIs, revisions, ACLs, and typed foreign keys
  survive every indexed version.
- Reuse a chunk embedding only when model ID and chunk hash match.
- Keep stored document and live query vectors in one model space.
- Apply filters and `retrieval.acl_visible` inside every retrieval arm before
  fusion.
- Fuse rank positions once through weighted RRF. Raw arm scores remain
  diagnostics and are not added again to `final_score`.
- Treat Cohere Rerank as a post-fusion ordering stage. Preserve both
  `rerank_score` and PostgreSQL RRF score.
- Persist `proof.retrieval_runs`, candidates, and stages before synthesis.
- Build citations only from retrieved document and chunk versions and validate
  URI, revision, and quote.
- Render canonical edges from foreign keys; store inferred edges separately
  with method, confidence, and source revision.
- Revalidate mutable facts and perform writes through their authoritative
  systems.

## 4. Validate the Failure and Fix

| Concern | Required proof |
|---|---|
| Exact identifier | The receipt-derived unsafe change is tier-one rank 1. |
| Semantic recall | A paraphrase retrieves the relevant incident evidence in the configured model space. |
| Fuzzy matching | `CGH-<run-suffix>-01` resolves to `CHG-<run-suffix>-01` without becoming an unbounded body scan. |
| Filters and ACLs | Out-of-scope and restricted evidence never enters an arm or traversal hop. |
| Fusion | Arm positions, weights, RRF, and optional rerank remain inspectable and separate. |
| Search index | Unchanged rows skip work; changed rows version; tombstones supersede; drift is zero. |
| Citation | Every citation resolves to a source URI, revision, exact chunk, and supporting quote. |
| Replay | The returned `run_id` resolves to persisted candidates, stages, answer, and diagnostics. |
| Evaluation | Retrieval and traversal metrics are reported separately. |

Use repository commands where applicable:

```bash
make doctor
make schema
make live-workshop
make smoke
make test
git diff --check
```

Do not run schema, live-workshop, smoke, or resettable integration tests without
an explicit disposable database. Never substitute a fixture, prior capture,
local embedding, or precomputed vector when the live path fails.

## 5. Report the Receipt

Summarize the evidence-path choice, owning files changed, behavior before and
after, validation performed, resulting `run_id` or search index build ID, and any
check that could not run.
