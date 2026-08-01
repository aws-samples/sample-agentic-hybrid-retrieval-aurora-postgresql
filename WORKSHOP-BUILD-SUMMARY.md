# What DAT410 Builds

DAT410 builds an incident-evidence retrieval system on Amazon Aurora
PostgreSQL. Participants do not build a chatbot shell or a vector-only demo.
They build and inspect the database, retrieval, agent, and proof contracts that
produce a cited answer.

The full governing contract is in [DAT410-BUILD-BRIEF.md](DAT410-BUILD-BRIEF.md).

## The Question

> Why did `CHG-1842` block checkout writes during `INC-2047`, which visible
> customer was affected, and what was the safe fix?

The scenario is synthetic. PostgreSQL lock behavior and SQL syntax are real;
incident IDs, customer names, support cases, and operational records are
controlled fixtures.

The required path first reproduces the lock mechanism with real PostgreSQL
sessions, then diagnoses the historical incident through hybrid retrieval,
fusion and reranking, agent tools, cited synthesis, and diagnostics and replay.
Persona switching, RLS and masking comparison, and managed Gateway invocation
are optional appendix exercises.

## What Is Prebuilt

Workshop Studio prepares the expensive and slow dependencies before the room
opens:

- Aurora PostgreSQL and supported extensions;
- VPC, private database networking, IAM, KMS, and Secrets Manager;
- Code Editor and the immutable workshop source;
- 15,017 indexed evidence documents and 15,017 Cohere embeddings;
- B-tree, GIN full-text, GIN trigram, and HNSW indexes;
- FastAPI and the Hybrid Retrieval Workbench frontend;
- configured Bedrock embedding, reranking, and synthesis models.

Participants do not provision infrastructure, generate the full embedding
cache, or build a connector during the hour.

Workshop Studio may also prebuild AgentCore Gateway and its stateless Lambda MCP
target for the optional managed-contract appendix.

## What Participants Build and Prove

### 1. Relational evidence

`casework.*` holds normalized synthetic incidents, changes, support cases,
runbooks, lock observations, commitments, postmortems, ACLs, and foreign-key
relationships.

Participants prove that:

- `CHG-1842` is the confirmed causal change;
- `CHG-1838` is ruled out;
- `CASE-7419` is the visible affected case;
- `CASE-7424` is explicitly unaffected;
- `RB-017` is current and `RB-092` is superseded; and
- declared relationships come from relational facts, not text
  co-occurrence.

### 2. A versioned search index

`retrieval.*` turns approved casework into versioned documents and chunks with:

- stable evidence IDs;
- source URI and revision;
- content hashes;
- ACL metadata;
- typed filter columns;
- full-text vectors;
- 1,024-dimensional embeddings;
- tombstone and current-version state; and
- search index build and drift receipts.

The frozen release target must contain exactly 15,017 ready documents and
chunks with zero drift. The search index is derived and rebuildable; it is not
the source of truth.

### 3. Four retrieval signals

Participants run:

- exact identifier lookup for `CHG-1842`;
- PostgreSQL full-text search over document and chunk text;
- pgvector semantic retrieval for `checkout writes froze`; and
- `pg_trgm` fuzzy retrieval for `CGH-1842`.

Metadata filters execute inside every arm before candidates enter fusion. The
implemented ACL checks follow the same placement, and the optional persona
appendix makes that boundary visible.

Three of the four signals are ranked and weighted. The exact identifier lookup
is a deterministic tier instead, for the reason given below.

### 4. A deterministic tier above weighted RRF

Aurora combines rank positions, not incompatible raw score scales. Final order
is a two-key sort:

```text
ORDER BY
    match_tier,                 -- 1 = exact identifier, 2 = fused
    exact_identifier_position,  -- within tier 1 only
    rrf_score DESC              -- within tier 2

rrf_score(d) =
    2 / (60 + full_text_rank)
  + 1 / (60 + semantic_rank)
  + 1 / (60 + fuzzy_rank)
```

Participants prove why the tier exists. Exact identifier resolution is a B-tree
equality probe, so it is a fact about the query rather than a score. They then
use an identifier-free symptom query, change the fused weights from `2:1:1` to
semantic-only `0:4:0`, and independently recompute the stored RRF score. The
experiment changes fused ordering without weakening the exact-ID contract.

An absent arm contributes zero. Weights are `numeric`, because integer
`2 / (60 + 1)` truncates to `0`. Raw text scores, vector distance, trigram
similarity, RRF, and Cohere rerank scores remain separate. None is a
probability.

### 5. Filtering and semantic diagnostics

The corpus includes a staging rehearsal whose language is deliberately more
similar to one query than the production incident. Participants first observe
that distractor, then add `cluster_id=checkout-prod-cluster-01` and prove every
returned row is in scope before fusion.

Participants also inspect:

- cosine distance;
- the HNSW index;
- `ef_search`;
- the actual PostgreSQL query plan.

The lesson is planner-aware: the UI reports the plan PostgreSQL selected. It
does not claim HNSW when PostgreSQL chose a different path.

The deeper `off`, `strict_order`, and `relaxed_order` iterative-scan comparison
is an appendix exercise.

### 6. Post-fusion model reranking

Cohere Rerank v3.5 can reorder the Aurora candidate pool after SQL fusion.
Aurora's RRF score remains intact. If reranking fails, the run records the
failure and keeps SQL order. The participant still completes the checkpoint by
observing `rerank_applied=false`.

### 7. Evidence-bound agent tools

The agent contract answers in this order:

1. `decompose_question`
2. `search_evidence`, once per subquestion plus bounded retries
3. `follow_evidence_links`
4. `compare_sources`
5. `synthesize_cited_answer`

The tools decompose the question, retrieve targeted evidence, traverse
authoritative links, reject distractors, and synthesize from numbered evidence.

Two further tools are registered outside that sequence. `explain_ranking` reads
a persisted receipt and calls no model, so it explains ranking after the fact
rather than during answering. `answer_with_citations` runs the whole loop in one
call for the managed transports.

### 8. Replayable proof

`proof.*` persists:

- the query, filters, persona, model space, and retrieval controls;
- candidate arm positions and raw diagnostics;
- RRF and optional rerank scores;
- ordered stage timing;
- agent subquestions and retrievals;
- answer text and synthesis metadata;
- exact source, document, and chunk versions; and
- citation quote and source context, with a claim only when one is persisted.

The returned `run_id` replays the answer without another model call.

### 9. Retrieval and traversal evaluation after the core path

The controlled set contains four questions and 17 graded judgments:

- `exact-change`;
- `fuzzy-change-id`;
- `semantic-symptom`; and
- `customer-impact`.

Retrieval uses recall, precision, MRR, and nDCG. Relationship traversal uses
separate recall and precision.

### 10. Portable invocation

The same contract is available through:

- FastAPI HTTP;
- a Lambda target behind AgentCore Gateway; and
- a local stdio MCP server.

Adapters do not reimplement ranking. A managed call still creates an Aurora
retrieval receipt.

## Participant Exercises

| Exercise | Participant action | Required proof |
|---|---|---|
| Incident reproduction | Run the ordinary and concurrent index phases in three terminals | Reads continue; ordinary index blocks a writer; concurrent index permits fresh DML |
| Readiness | Run `make doctor` | Aurora, extensions, model space, 15,017 documents/chunks, zero drift |
| Exact and full text | Run an exact-ID question, then a dedicated FTS query with SQL and lock vocabulary but no ID | Exact tier remains deterministic; FTS ranks `CHG-1842` first |
| Fuzzy ID | Search `CGH-1842` | `CHG-1842` recovered; `CHG-1838` rejected |
| Semantic retrieval | Search the reads-succeed/writes-time-out paraphrase | Relevant evidence without exact wording |
| Filter | Edit the unscoped starter request to add `cluster_id` | Staging evidence appears before the edit and is absent afterward |
| Fusion | Edit the starter from `2:1:1` to semantic-only `0:4:0`, then complete the weighted-RRF SQL expression | Every stored RRF score recomputes from arm positions |
| Query plan | Read one live `EXPLAIN` observation | Name the index PostgreSQL selected or explain why the arm abstained |
| Rerank | Set `rerank=true` and compare Aurora and Cohere orders | Both scores remain separate, or the explicit fallback remains inspectable |
| Agent plan | Fill the traversal and comparison requests from decomposition output | Confirmed and ruled-out changes resolve through authoritative relationships |
| Agent answer | Ask the canonical question after the plan passes | Lock cause, visible customer, safe fix, numbered citations |
| Citation audit | Validate URI, revision, chunk, quote, and source context | Database attribution validation passes |
| Replay | Reload the answer by `run_id` | Candidates, stages, answer, and citations return without a model call |

### Optional Appendix Exercises

| Exercise | Participant action | Required proof |
|---|---|---|
| Persona boundary | Repeat one query as App Engineer, Auditor, and DBA | `CASE-7421` is absent, masked, then unmasked |
| Managed contract | Invoke the Gateway tool | `AWS_IAM` call returns a real Aurora `run_id` |

Neither appendix exercise is required for participant completion or the default
release path.

## Sixty-Minute Path

| Minute | Participant outcome |
|---:|---|
| 0-5 | Scenario and system boundary |
| 5-10 | Readiness against the preloaded evidence corpus |
| 10-20 | Reproduce the lock wait and apply the concurrent-index repair |
| 20-40 | Four query shapes; filter edit; fusion edit; rerank; one plan |
| 40-50 | Participant tool plan, traversal, comparison, and cited synthesis |
| 50-55 | Citation attribution and model-free replay |
| 55-60 | Completed exercise chain, production boundary, and close |

First cut: use a saved plan observation. If reranking is unavailable, keep its
explicit fallback. Deeper HNSW tuning and compact evaluation run after the
core. The filter and fusion checkpoints, cited answer, and replay receipt remain
mandatory.

## What the UI Exposes

### Diagnose hybrid retrieval

- Retrieval lab
- Fusion anatomy
- Query plan
- Scale and search index builds

### Audit cited provenance

- Answer and persisted plan
- Evidence graph
- Replay receipt
- Evaluation

### Optional managed contract

- HTTP contract
- MCP tool catalog
- AgentCore Gateway and Lambda target status
- transport receipt and parity check

## What Participants Take Home

- normalized PostgreSQL evidence schema patterns;
- B-tree, GIN, trigram, and HNSW index patterns;
- canonical SQL for filtered retrieval and weighted RRF;
- a versioned search index builder with hash-based embedding reuse;
- ACL-before-ranking and ACL-at-every-hop examples;
- evidence-bound agent tools;
- persisted retrieval and citation receipts;
- retrieval and traversal evaluation SQL;
- FastAPI, MCP, and AgentCore adapter contracts; and
- a production adaptation checklist.

## Production Boundaries

A real deployment must additionally provide:

- authenticated caller identity and trusted persona mapping;
- least-privilege database roles;
- TLS, private networking, restricted CORS, and API abuse controls;
- source cursors, retries, reconciliation, and dead-letter handling;
- current source authorization revalidation;
- backup, restore, failover, and recovery testing;
- room-scale and production load testing;
- model quotas, lifecycle checks, residency review, and cost controls;
- correlated API, agent, retrieval, model, and database observability; and
- owned retention, deletion, and audit policies.

The Workshop Studio topology is intentionally disposable. Its one writer,
one-day backup retention, deletion protection off, and disabled forced SSL are
not production defaults.

## Current Release Gaps

The application and Workshop Studio narrative are implemented, but publication
still requires release evidence:

1. build the real v2 dump and source archive from one immutable tested revision;
2. replace `SourceRevision=UNRELEASED` with that 40-character revision;
3. provision a fresh Workshop Studio account on `db.r8g.2xlarge`;
4. run all nine incident scripts and every participant step with the
   participant role;
5. repair any search-index drift and prove exact, FTS, fuzzy, semantic, filter,
   fusion, rerank, agent-plan, citation, and replay contracts;
6. verify model access and quotas under the participant role;
7. recapture Run record, Replay, and mobile proof images from the frozen
   Cohere-backed target; and
8. complete the required path inside 60 minutes with the documented cut lines.

## Non-Claims

This workshop does not present synthetic records as real AWS or customer data,
does not treat Aurora as the operational system of record, does not claim that
vector search is sufficient by itself, does not label scores as probabilities,
and does not claim that the deterministic 25,000-row lock lab measures
production index-build duration or throughput.
