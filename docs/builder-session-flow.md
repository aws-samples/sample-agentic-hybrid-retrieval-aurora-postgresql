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

1. Run `make live-workshop` to induce one real write stall with six writers,
   two readers, and 30 PostgreSQL samples.
2. Apply and measure `CREATE INDEX CONCURRENTLY`, then collect CloudWatch and
   Performance Insights observations for that same run.
3. Admit 104-111 run-derived records and generate every current Cohere
   embedding through Bedrock before retrieval is enabled.
4. Recover `CHG-<run-suffix>-01` through exact retrieval, then run a dedicated PostgreSQL
   full-text query without an identifier.
5. Recover mistyped `CGH-<run-suffix>-01` through indexed trigram search and retrieve a
   semantic symptom paraphrase through pgvector.
6. Inspect the `pg_incident_capture` source and run-identity checks applied to
   every participant candidate.
7. Change the weighted-RRF controls, complete the SQL expression in a temporary
   checkpoint table, and independently recompute the persisted score from arm
   positions.
8. Apply Cohere reranking without overwriting the PostgreSQL RRF score, or inspect the
   explicit `rerank_applied=false` fallback.
9. Build an evidence plan from decomposition, relationship traversal, and
   source comparison before running the complete agent.
10. Validate citation rows and replay the retrieval receipt by `run_id`.

Participants do not provision Aurora, restore or generate a fictional corpus,
build a connector, or deploy AgentCore Gateway during the hour.

## Minute-by-Minute Run of Show

| Minute | Activity | Participant proof | Time risk and cut line |
|---:|---|---|---|
| 0-5 | Scenario and system boundary | Connect the production write-stall question to `casework`, `retrieval`, and `proof` | No product tour |
| 5-10 | Readiness | `make doctor` shows database and model access ready | Move blocked participants to a working paired terminal |
| 10-22 | Reproduce and repair | Six writers wait on `Lock:relation`; readers continue; concurrent repair permits fresh DML | Pair with a participant whose live run completes; never substitute checked-in data |
| 22-27 | Project and index | Receipt proves 100-120 documents, runtime embeddings, one capture ID, and zero drift | Retry live dependencies; do not load a fallback corpus |
| 27-42 | Hybrid retrieval | Dedicated FTS, semantic, fuzzy, filter, and participant-edited RRF checkpoints pass | `rerank_applied=false` is a valid model fallback |
| 40-50 | Agent tools | Build the evidence plan, traverse the captured incident, change, and lock relationships, then synthesize the cited answer | Use the complete answer endpoint if individual calls run long |
| 50-55 | Citations and replay | Validate source URI/revision/quote and replay by `run_id` without a model call | Skip visual Proof exploration, preserve citation SQL and receipt GET |
| 55-60 | Close | Connect the participant exercises to the production evidence boundary | Run compact evaluation after the session |

## Core Versus Appendix

### Core

- controlled PostgreSQL lock reproduction and concurrent-index repair;
- exact identifier and PostgreSQL full-text retrieval;
- pgvector cosine search;
- source-system, SQL, and metadata filters;
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
- production identity mapping and live authorization revalidation;
- load, failover, and Aurora-specific operational testing.

These production extensions require additional implementation and are not
counted as participant completion.

## Unique L400 Proof

The content that distinguishes this session is not the list of retrievers:

1. **Provenance is part of ranking.** Every candidate must belong to the
   receipt's capture and `pg_incident_capture` source system.
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
| Live incident falls behind | Pair with a participant whose orchestrator produced a complete current-run receipt |
| Bedrock embedding is slow | Retry runtime indexing for that live run; do not substitute precomputed vectors |
| Cohere rerank is unavailable | Show `rerank_applied=false` and retain PostgreSQL RRF ordering |
| Synthesis model is unavailable | Use the extractive fallback built from the same persisted evidence rows |
| Frontend fails | Use the HTTP endpoints and SQL receipt views |
| Aurora connection fails for one attendee | Pair with a working environment; do not switch the room to local PostgreSQL |
| Room is more than five minutes behind | Use the reference response for the live plan, run the filter and fusion checkpoints, and preserve the cited-answer path |

## Facilitator Gates

Before opening the room:

- Workshop Studio stack is complete and Aurora is reachable from Code Editor.
- The guided incident orchestrator passes on the target Aurora engine using the
  participant database role.
- Schema is current and participant evidence is empty before each run.
- `make doctor` passes all hard gates in `us-east-1`.
- Semantic, lexical, fuzzy, hybrid, rerank, answer, citation, and evaluation
  receipts have known expected outputs.
- The filter, fusion, and agent-plan participant checkpoints print `OK`.
- A full run has been tested on the target Aurora engine, not only local
  PostgreSQL.
- The packaged source revision is immutable and recorded.
- Model lifecycle, CRIS support, IAM, and quotas have been rechecked.

## Expected Outputs

- Dedicated FTS rank 1 for the measured unsafe change without an identifier in
  the query.
- Plain `CREATE INDEX` owns granted `ShareLock`; the writer waits for
  `RowExclusiveLock`; reads continue.
- Concurrent index build owns `ShareUpdateExclusiveLock`; fresh DML completes;
  the resulting index is ready, valid, and live.
- Fuzzy rank 1 for `CHG-<run-suffix>-01` from
  `CGH-<run-suffix>-01`.
- Every participant candidate reports source system `pg_incident_capture`.
- Default and semantic-only weighted-RRF receipts recompute from their
  persisted arm positions.
- Agent synthesis identifies the measured wait, blocking DDL, and concurrent
  repair from current-run evidence.
- Cited answer includes real source revisions and passes
  `proof.validate_answer_citations`.
- The saved `run_id` replays candidates, stages, answer, and citations without
  another model call.

These core outputs are release gates, not slide claims.

## After The Session

Production identity, authorization revalidation, RLS, and masking remain
architecture topics. They are not demonstrated with fictional records in the
participant environment.
