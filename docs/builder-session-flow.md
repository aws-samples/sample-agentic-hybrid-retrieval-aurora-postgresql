# DAT410 Builder Session Flow

**Level:** 400
**Hard duration:** 60 minutes
**Participant outcome:** diagnose one database incident with a working hybrid
retrieval and cited-agent path, then leave with the SQL and proof contract.

The opening guide aligns the room on full-text search, semantic search, and RRF
with one short PostgreSQL example. The session then teaches where retrieval
fails, how PostgreSQL executes the signals, and how to prove what an agent used.

## Minimal End-to-End Path

Every participant must complete this path:

1. Pass preflight against a preloaded Aurora PostgreSQL corpus.
2. Recover `CHG-1842` through exact/full-text retrieval and a cluster filter.
3. Recover mistyped `CGH-1842` through indexed trigram search.
4. Compare filtered HNSW behavior with iterative scan off and relaxed.
5. Run weighted RRF and inspect independent arm positions.
6. Apply Cohere reranking without overwriting the Aurora score.
7. Run the agent tool pipeline and receive a cited answer.
8. validate citation rows and replay the retrieval receipt by `run_id`.

Participants do not provision Aurora, generate 15,000 embeddings, build a
connector, or deploy AgentCore Gateway during the hour.

## Minute-by-Minute Run of Show

| Minute | Activity | Participant proof | Time risk and cut line |
|---:|---|---|---|
| 0-3 | Hybrid-search primer, scenario, and boundary | Explain lexical and semantic retrieval, RRF, `casework` as truth, `retrieval` as derived search state, and `proof` as receipts | One formula and one abbreviated SQL shape; no product tour |
| 3-7 | Readiness | `make doctor` shows search index ready, model space aligned, and zero drift | At minute 7, move anyone blocked to the prevalidated terminal |
| 7-14 | Lexical retrieval and filters | Exact ID rank 1; inspect document/chunk GIN streams; apply `cluster_id` and ACL before ranking | Skip the second `EXPLAIN` if two minutes behind |
| 14-19 | Fuzzy entity recovery | `CGH-1842` resolves to `CHG-1842`; inspect threshold and trigram index plan | Do not tune multiple thresholds live |
| 19-27 | Semantic retrieval under filters | Run HNSW with `ef_search=40`; observe candidate loss with iterative scan off and recovery with relaxed scan | If model latency is high, reuse the preflight run's persisted query vector |
| 27-35 | Weighted RRF | Run lexical, semantic, and fuzzy arms; inspect positions, `2:1:1` weights, `k=60`, and fused rank | Weight experiment is the first core cut |
| 35-40 | Model rerank and diagnostics | Compare Aurora RRF order with Cohere order; keep both scores and stage timing | If rerank is unavailable, show the recorded failure and continue with SQL order |
| 40-50 | Agent tools | Decompose, retrieve, traverse FK-derived edges, compare revisions, and explain ranking | Use the complete answer endpoint at minute 47 if individual tool calls run long |
| 50-55 | Citations and evaluation | Validate source URI/revision/quote against the exact chunk; run the small retrieval/traversal evaluation | Evaluation detail is the second core cut |
| 55-60 | Buffer and close | Save `run_id`; identify one production evidence boundary and one appendix exercise | Do not start a new demo after minute 57 |

## Core Versus Appendix

### Core

- exact identifier and PostgreSQL full-text retrieval;
- pgvector cosine search and filtered HNSW iterative scan;
- SQL and metadata filters;
- `pg_trgm` typo recovery;
- weighted RRF;
- Cohere model reranking;
- source attribution and citation validation;
- persisted diagnostics and evaluation;
- decomposition, targeted retrieval, relationship traversal, comparison,
  ranking explanation, and cited synthesis.

### Extend After the Session

- connector transports, cursors, and full reconciliation;
- release-scale embedding generation;
- HNSW index creation and replacement-index operations;
- additional corpora, chunkers, model spaces, and relevance judgments;
- inferred-edge generation;
- AgentCore Gateway deployment;
- production identity mapping and live authorization revalidation;
- load, failover, and Aurora-specific operational testing.

The appendix is runnable engineering work, not a narrated feature claim. It is
not counted as participant completion.

## Unique L400 Proof

The content that distinguishes this session is not the list of retrievers:

1. **Filtered ANN can return too few rows.** On the controlled scale corpus,
   HNSW with iterative scan off can exhaust its candidate budget before a
   selective filter produces enough matches. Strict and relaxed iterative scan
   recover the requested result count with different ordering and latency
   tradeoffs.
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
| Bedrock embedding is slow | Precomputed document vectors and the packaged query-vector checkpoint |
| Cohere rerank is unavailable | Show `rerank_applied=false` and retain Aurora RRF ordering |
| Synthesis model is unavailable | Use the extractive fallback built from the same persisted evidence rows |
| Frontend fails | Use the HTTP endpoints and SQL receipt views |
| Aurora connection fails for one attendee | Pair with a working environment; do not switch the room to local PostgreSQL |
| Room is more than five minutes behind | Skip RRF weight experimentation and detailed evaluation; preserve the cited-answer path |

## Facilitator Gates

Before opening the room:

- Workshop Studio stack is complete and Aurora is reachable from Code Editor.
- Schema, controlled corpus, embeddings, and indexes are already restored.
- `make doctor` passes all hard gates in `us-east-1`.
- Semantic, lexical, fuzzy, hybrid, rerank, answer, citation, and evaluation
  receipts have known expected outputs.
- A full run has been tested on the target Aurora engine, not only local
  PostgreSQL.
- The packaged source revision is immutable and recorded.
- Model lifecycle, CRIS support, IAM, and quotas have been rechecked.

## Expected Outputs

- Lexical rank 1 for `CHG-1842`.
- Fuzzy rank 1 for `CHG-1842` from `CGH-1842`.
- Default hybrid rank 1 for `CHG-1842` under the inferred
  `checkout-prod-cluster-01` filter.
- Default workshop principal cannot retrieve or traverse `CASE-7421`.
- Cited answer includes real source revisions and passes
  `proof.validate_answer_citations`.
- Evaluation reports retrieval metrics separately from traversal metrics.

These outputs are release gates, not slide claims.
