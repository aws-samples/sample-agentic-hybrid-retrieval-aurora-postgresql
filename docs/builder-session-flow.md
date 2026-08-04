# DAT410 Builder Session Flow

**Level:** 400
**Hard duration:** 60 minutes
**Participant outcome:** diagnose one database incident with a working hybrid
retrieval and cited-agent path, then leave with the SQL and proof contract.

The opening guide establishes the incident and system boundary. The labs then
make each retrieval method earn its place, let participants change retrieval
and agent decisions, and prove what the final answer used.

## Guide Structure

1. **Getting Started:** access the environment and verify the empty evidence
   store.
2. **Workshop Scenario:** understand the hung migration and where its evidence
   comes from.
3. **Lab 1:** cause, fix, and admit the incident.
4. **Lab 2:** build hybrid retrieval.
5. **Lab 3:** build the incident agent.
6. **Lab 4:** prove and replay.
7. **Take it home:** apply the retrieval skill.
8. **Summary and cleanup.**

Optional labs cover RLS with column masking and AgentCore publication. The
appendix owns troubleshooting, facilitator notes, run-derived identifier
reference, live search-index operations, and retrieval diagnostics.

## Minimal End-to-End Path

Every participant must complete this path:

1. Run `make live-workshop` to induce one real write stall with six writers,
   two readers, and 30 PostgreSQL samples.
2. Apply and measure `CREATE INDEX CONCURRENTLY`, then collect CloudWatch and
   Performance Insights observations for that same run.
3. Admit about 110 run-derived records and generate every current Cohere
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
| 0-5 | Getting Started | Access both work surfaces and prove `awaiting_incident` with zero evidence | Move blocked participants to a working paired terminal |
| 5-10 | Workshop Scenario | Explain the hung migration and trace measured telemetry into the evidence store | No product tour |
| 10-25 | Lab 1: Cause, fix, and admit | 5,000 customers and 25,000 related orders produce roughly 735 measured telemetry rows, 110 evidence documents, current embeddings, one capture, and zero drift | Pair with a participant whose live run completes; never substitute checked-in data |
| 25-40 | Lab 2: Build hybrid retrieval | Exact, FTS, semantic, fuzzy, filter, participant-edited RRF, and rerank checkpoints pass | `rerank_applied=false` is a valid model fallback |
| 40-50 | Lab 3: Build the incident agent | Build the evidence plan, traverse captured relationships, compare sources, and synthesize the cited answer | Use the complete answer endpoint if individual calls run long |
| 50-55 | Lab 4: Prove and replay | Validate source URI, revision, and quote, then replay by `run_id` without a model call | Skip visual Proof exploration; preserve citation SQL and receipt GET |
| 55-58 | Take it home | Inspect the reusable retrieval skill and production ownership boundary | Keep this to transfer, not another exercise |
| 58-60 | Summary and cleanup | Confirm the temporary workload is gone while its measured proof remains | Run compact evaluation after the session |

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
  ranking explanation, and cited synthesis;
- a reusable retrieval skill that carries the evidence and proof contract into
  another system.

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

Production identity and authorization revalidation remain architecture topics
in the required path. An event owner may enable the optional RLS and
column-masking lab only against the participant's live capture; it never loads
fictional records.
