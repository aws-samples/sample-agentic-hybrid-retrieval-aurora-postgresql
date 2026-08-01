# DAT410 Builder Session Flow

**Level:** 400
**Hard duration:** 60 minutes
**Participant outcome:** diagnose one database incident with a working hybrid
retrieval and cited-agent path, then leave with the SQL and proof contract.

The opening guide establishes the incident and system boundary. The labs then
make each retrieval method earn its place, let participants change retrieval
and agent decisions, and prove what the final answer used.

## Minimal End-to-End Path

Every participant must complete this path:

1. Reproduce the incident with real PostgreSQL sessions: reads continue,
   writes wait, and the ordinary index backend owns the blocking `ShareLock`.
2. Apply `CREATE INDEX CONCURRENTLY` and prove a fresh write still completes.
3. Pass preflight against the preloaded Aurora PostgreSQL evidence corpus.
4. Recover `CHG-1842` through exact retrieval, then run a dedicated PostgreSQL
   full-text query without an identifier.
5. Recover mistyped `CGH-1842` through indexed trigram search and retrieve a
   semantic symptom paraphrase through pgvector.
6. Remove the seeded staging distractor with a cluster filter before fusion.
7. Change the weighted-RRF controls, complete the SQL expression in a temporary
   checkpoint table, and independently recompute the persisted score from arm
   positions.
8. Apply Cohere reranking without overwriting the Aurora score, or inspect the
   explicit `rerank_applied=false` fallback.
9. Build an evidence plan from decomposition, relationship traversal, and
   source comparison before running the complete agent.
10. Validate citation rows and replay the retrieval receipt by `run_id`.

Participants do not provision Aurora, generate 15,000 embeddings, build a
connector, or deploy AgentCore Gateway during the hour.

## Minute-by-Minute Run of Show

| Minute | Activity | Participant proof | Time risk and cut line |
|---:|---|---|---|
| 0-5 | Scenario and system boundary | Connect the production write-stall question to `casework`, `retrieval`, and `proof` | No product tour |
| 5-10 | Readiness | `make doctor` shows search index ready, model space aligned, and zero drift | Move blocked participants to the prevalidated terminal |
| 10-20 | Reproduce and repair | Read succeeds; writer waits on `Lock:relation`; `ShareLock` and `RowExclusiveLock` are visible; concurrent retry permits fresh DML | Use the facilitator's measured capture if terminal orchestration runs long |
| 20-40 | Hybrid retrieval | Dedicated FTS, semantic, and fuzzy queries pass; a filter removes the staging distractor; participant-edited weights pass the RRF checkpoint; rerank and one live plan remain inspectable | Use a saved plan observation if the drawer is slow; `rerank_applied=false` is a valid fallback |
| 40-50 | Agent tools | Build the evidence plan, traverse FK-derived edges, compare confirmed and ruled-out changes, then synthesize the cited answer | Use the complete answer endpoint if individual calls run long |
| 50-55 | Citations and replay | Validate source URI/revision/quote and replay by `run_id` without a model call | Skip visual Proof exploration, preserve citation SQL and receipt GET |
| 55-60 | Close | Connect the participant exercises to the production evidence boundary | Run compact evaluation after the session |

## Core Versus Appendix

### Core

- controlled PostgreSQL lock reproduction and concurrent-index repair;
- exact identifier and PostgreSQL full-text retrieval;
- pgvector cosine search;
- SQL and metadata filters;
- `pg_trgm` typo recovery;
- weighted RRF;
- Cohere model reranking;
- source attribution and citation validation;
- persisted diagnostics and replay;
- decomposition, targeted retrieval, relationship traversal, comparison,
  ranking explanation, and cited synthesis.

### Extend After the Session

- connector transports, cursors, and full reconciliation;
- release-scale embedding generation;
- HNSW index creation and replacement-index operations;
- filtered-HNSW iterative-scan comparisons;
- additional corpora, chunkers, model spaces, and relevance judgments;
- compact retrieval and traversal evaluation;
- inferred-edge generation;
- AgentCore Gateway deployment;
- row-level security and `pg_columnmask` comparison by rerunning one query as
  App Engineer, Auditor, and DBA;
- production identity mapping and live authorization revalidation;
- load, failover, and Aurora-specific operational testing.

The appendix is runnable engineering work, not a narrated feature claim. It is
not counted as participant completion.

## Unique L400 Proof

The content that distinguishes this session is not the list of retrievers:

1. **Scope is part of ranking.** The seeded staging rehearsal is deliberately
   more similar to one query than the production incident. Applying
   `cluster_id` inside every retrieval arm prevents that wrong-environment row
   from earning a fusion vote.
2. **Relational truth and search index are different assets.** Foreign
   keys own incident relationships; the physical search index owns
   externally generated vectors and indexable text. Drift is measured rather
   than hidden.
3. **A score is not proof.** Raw full-text, cosine, trigram, RRF, and rerank
   values have different meanings. The persisted receipt keeps positions and
   stages separate, and citations resolve to exact source revisions and chunks.

## Failure Fallbacks

| Failure | Continue with |
|---|---|
| Participant terminal or editor falls behind | Prevalidated complete checkout and the next numbered command |
| Multi-session incident lab falls behind | Facilitator's measured capture and the safe-fix verification; preserve the retrieval path |
| Bedrock embedding is slow | Precomputed document vectors and the packaged query-vector checkpoint |
| Cohere rerank is unavailable | Show `rerank_applied=false` and retain Aurora RRF ordering |
| Synthesis model is unavailable | Use the extractive fallback built from the same persisted evidence rows |
| Frontend fails | Use the HTTP endpoints and SQL receipt views |
| Aurora connection fails for one attendee | Pair with a working environment; do not switch the room to local PostgreSQL |
| Room is more than five minutes behind | Use the reference response for the live plan, run the filter and fusion checkpoints, and preserve the cited-answer path |

## Facilitator Gates

Before opening the room:

- Workshop Studio stack is complete and Aurora is reachable from Code Editor.
- The exact multi-session incident scripts pass on the target Aurora engine
  using the participant database role.
- Schema, controlled corpus, embeddings, and indexes are already restored.
- `make doctor` passes all hard gates in `us-east-1`.
- Semantic, lexical, fuzzy, hybrid, rerank, answer, citation, and evaluation
  receipts have known expected outputs.
- The filter, fusion, and agent-plan participant checkpoints print `OK`.
- A full run has been tested on the target Aurora engine, not only local
  PostgreSQL.
- The packaged source revision is immutable and recorded.
- Model lifecycle, CRIS support, IAM, and quotas have been rechecked.

## Expected Outputs

- Dedicated FTS rank 1 for `CHG-1842` without an identifier in the query.
- Plain `CREATE INDEX` owns granted `ShareLock`; the writer waits for
  `RowExclusiveLock`; reads continue.
- Concurrent index build owns `ShareUpdateExclusiveLock`; fresh DML completes;
  the resulting index is ready, valid, and live.
- Fuzzy rank 1 for `CHG-1842` from `CGH-1842`.
- The unfiltered fusion request exposes `CHG-1840` or `INC-2044`; the edited
  request returns only `checkout-prod-cluster-01`.
- Default and semantic-only weighted-RRF receipts recompute from their
  persisted arm positions.
- Agent synthesis identifies the blocking change, visible affected customer,
  and safe fix from numbered evidence.
- Cited answer includes real source revisions and passes
  `proof.validate_answer_citations`.
- The saved `run_id` replays candidates, stages, answer, and citations without
  another model call.

These core outputs are release gates, not slide claims.

## Optional Persona Appendix

When the target Aurora environment includes `pg_columnmask`, rerun the same
restricted-evidence query in this order:

1. App Engineer cannot retrieve or traverse `CASE-7421`.
2. Auditor can retrieve the row with customer-sensitive text masked.
3. DBA can retrieve the row unmasked.

This comparison validates the implemented RLS and masking boundary. It is not a
participant completion requirement or a default release gate.
