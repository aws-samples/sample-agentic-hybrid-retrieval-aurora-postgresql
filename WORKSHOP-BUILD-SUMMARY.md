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

## What Is Prebuilt

Workshop Studio prepares the expensive and slow dependencies before the room
opens:

- Aurora PostgreSQL and supported extensions;
- VPC, private database networking, IAM, KMS, and Secrets Manager;
- Code Editor and the immutable workshop source;
- 15,017 indexed evidence documents and 15,017 Cohere embeddings;
- B-tree, GIN full-text, GIN trigram, and HNSW indexes;
- FastAPI and the Hybrid Retrieval Workbench frontend;
- configured Bedrock embedding, reranking, and synthesis models; and
- AgentCore Gateway with a stateless Lambda MCP target when the managed
  exercise passes its release gate.

Participants do not provision infrastructure, generate the full embedding
cache, or build a connector during the hour.

## What Participants Build and Prove

### 1. Relational evidence

`casework.*` holds normalized synthetic incidents, changes, support cases,
runbooks, lock observations, commitments, postmortems, ACLs, and foreign-key
relationships.

Participants prove that:

- `CHG-1842` is the confirmed causal change;
- `CHG-1838` is ruled out;
- `CASE-7419` is the visible affected case;
- `CASE-7421` is relevant but restricted;
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

The current corpus contains exactly 15,017 documents and chunks with zero
drift. The search index is derived and rebuildable; it is not the source of
truth.

### 3. Four retrieval signals

Participants run:

- exact identifier lookup for `CHG-1842`;
- PostgreSQL full-text search over document and chunk text;
- pgvector semantic retrieval for `checkout writes froze`; and
- `pg_trgm` fuzzy retrieval for `CGH-1842`.

Metadata filters and ACL checks execute inside every arm before candidates
enter fusion.

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
equality probe, so it is a fact about the query rather than a score. Written as a
fourth weighted term it becomes outrankable: set the text weight to `0` and the
vector weight to `10` and a semantic false positive overtakes `CHG-1842`.
Participants run exactly that experiment and watch the named identifier hold
rank 1 while carrying a lower `rrf_score` than the row beneath it.

An absent arm contributes zero. Weights are `numeric`, because integer
`2 / (60 + 1)` truncates to `0`. Raw text scores, vector distance, trigram
similarity, RRF, and Cohere rerank scores remain separate. None is a
probability.

### 5. Filtered semantic retrieval

Participants inspect:

- cosine distance;
- the HNSW index;
- `ef_search`;
- `off`, `strict_order`, and `relaxed_order` iterative scans; and
- the actual PostgreSQL query plan.

The lesson is planner-aware: the UI reports the plan PostgreSQL selected. It
does not claim HNSW when PostgreSQL chose a different path.

### 6. Optional model reranking

Cohere Rerank v3.5 can reorder the Aurora candidate pool after SQL fusion.
Aurora's RRF score remains intact. If reranking fails, the run records the
failure and keeps SQL order.

### 7. Evidence-bound agent tools

The agent contract exposes:

1. `decompose_question`
2. `search_evidence`
3. `follow_evidence_links`
4. `compare_sources`
5. `explain_ranking`
6. `synthesize_cited_answer`
7. `answer_with_citations`

The tools decompose the question, retrieve targeted evidence, traverse
authoritative links, reject distractors, explain ranking, and synthesize from
numbered evidence.

### 8. Replayable proof

`proof.*` persists:

- the query, filters, persona, model space, and retrieval controls;
- candidate arm positions and raw diagnostics;
- RRF and optional rerank scores;
- ordered stage timing;
- agent subquestions and retrievals;
- answer text and synthesis metadata;
- exact source, document, and chunk versions; and
- citation quote and claim.

The returned `run_id` replays the answer without another model call.

### 9. Retrieval and traversal evaluation

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
| Readiness | Run `make doctor` | Aurora, extensions, model space, 15,017 documents/chunks, zero drift |
| Exact and full text | Search `CHG-1842` under `checkout-prod-cluster-01` | Exact and text positions; `CHG-1842` rank 1 |
| Fuzzy ID | Search `CGH-1842` | `CHG-1842` recovered; `CHG-1838` rejected |
| Semantic retrieval | Search `checkout writes froze` | Relevant evidence without exact wording |
| Query plan | Compare ANN controls and read `EXPLAIN` | Name the plan PostgreSQL actually selected |
| Fusion | Inspect one candidate across all arms, then try to demote `CHG-1842` by reweighting | Recalculate its RRF contribution by hand; the exact tier holds rank 1 regardless |
| Rerank | Compare Aurora and Cohere orders | Both scores remain present and separate |
| Agent answer | Ask the canonical question | Lock cause, visible customer, safe fix, numbered citations |
| Evidence graph | Follow incident relationships | Confirmed, ruled-out, affected, unaffected, current, and superseded facts |
| ACL boundary | Compare `analyst` and `admin` personas | `CASE-7421` absent from analyst retrieval and traversal |
| Citation audit | Validate URI, revision, chunk, quote, and claim | Database citation validation passes |
| Replay | Reload the answer by `run_id` | Candidates, stages, answer, and citations return without a model call |
| Evaluation | Run the controlled set | Retrieval and traversal metrics reported separately |
| Managed contract | Invoke the Gateway tool | `AWS_IAM` call returns a real Aurora `run_id` |

## Sixty-Minute Path

| Minute | Participant outcome |
|---:|---|
| 0-6 | Scenario, hybrid-search primer, and readiness |
| 6-17 | Exact/full-text and fuzzy identifier retrieval |
| 17-24 | Semantic retrieval, filters, and actual query plan |
| 24-33 | Weighted RRF and optional rerank |
| 33-43 | Agent decomposition, retrieval, traversal, and cited answer |
| 43-50 | Citation audit and replay |
| 50-54 | Compact retrieval and traversal evaluation |
| 54-58 | Managed MCP contract |
| 58-60 | Production boundary and close |

First cut: weight experimentation. Second cut: live evaluation detail. The
cited answer and replay receipt remain mandatory.

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

### Invoke managed contract

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

The application is implemented and live against the current Aurora and Bedrock
environment, but the workshop is not publication-ready until:

1. Orion and `ops.*` content is removed from every Workshop Studio module,
   screenshot, facilitator note, and expected output;
2. the packaged source archive is rebuilt from an immutable tested revision;
3. every participant step passes in a fresh Workshop Studio account;
4. model access and quotas pass under the participant role;
5. the managed Gateway exercise returns current Hybrid Retrieval Workbench
   evidence;
6. the filtered-ANN exercise has literal prepared plans;
7. a genuine `release_aurora` lock capture and observability evidence is
   produced, or those claims are removed; and
8. the complete required path fits inside 60 minutes.

## Non-Claims

This workshop does not present synthetic records as real AWS or customer data,
does not treat Aurora as the operational system of record, does not claim that
vector search is sufficient by itself, does not label scores as probabilities,
and does not claim that the current offline lock capture is release-grade
Aurora telemetry.
