# DAT410 Production Workshop Build Brief

**Session:** DAT410, AWS re:Invent 2026  
**Title:** Build agentic hybrid retrieval with Amazon Aurora PostgreSQL  
**Format:** Builders' session, strict 60 minutes  
**Level:** 400  
**Application:** Hybrid Retrieval Workbench<br>
**Scenario:** Synthetic application incident running on Aurora PostgreSQL  
**Last evidence audit:** August 1, 2026

This is the governing implementation and release brief for the current
incident-evidence workshop. It replaces the earlier Orion and `ops.*` workshop
story. Read `AGENTS.md` first. For search index, retrieval, ranking, citation,
traversal, diagnostics, or evaluation changes, apply
`.claude/skills/extend-hybrid-retrieval/SKILL.md`.

## 1. Executive Objective

Participants investigate one controlled database incident and build an
inspectable retrieval path that:

1. combines exact, full-text, semantic, and fuzzy retrieval;
2. applies metadata filters and the fixed workshop visibility predicate before
   fusion;
3. combines independent ranks with weighted Reciprocal Rank Fusion (RRF);
4. optionally reranks the fused pool with Cohere Rerank;
5. traverses authoritative PostgreSQL relationships;
6. synthesizes an answer only from retrieved evidence;
7. persists candidates, signals, stages, citations, and evaluation results in
   Aurora PostgreSQL; and
8. can optionally invoke the same contract through a managed MCP boundary
   without duplicating ranking logic.

The workshop is not a generic chatbot lab. The durable product is the search
and proof contract. Hybrid Retrieval Workbench is its inspection UI.

## 2. Evidence Labels

Every implementation or presentation claim must use one of these labels:

| Label | Meaning |
|---|---|
| **Implemented** | The behavior exists in the current source. |
| **Live validated** | The behavior was exercised against the current Aurora or Bedrock environment. |
| **Synthetic fixture** | The record is deterministic workshop data, not a real incident or customer record. |
| **Workshop infrastructure** | The behavior belongs to the sibling Workshop Studio repository. |
| **Release gate** | The behavior must be proved in a fresh target account before publication. |
| **Production adaptation** | The control is required for a real deployment but is not part of the 60-minute build. |

Do not collapse these labels. In particular, implemented validation code is not
evidence that a release capture exists.

## 3. Session Contract

- **Speakers:** Shayon Sanyal, Grant McAlister, Sudhir Amin, Veerendra Nayak,
  Rinisha Marar.
- **Audience:** advanced builders who can read SQL, query plans, JSON receipts,
  and Python service code.
- **Participant outcome:** a working, cited incident answer plus the SQL and
  proof patterns needed to adapt the design.
- **Hard duration:** 60 minutes. Provisioning, bulk embedding generation,
  connector construction, Gateway deployment, and release capture generation
  are pre-session or appendix work.
- **Quality bar:** each participant action must create inspectable proof. No
  step exists only to tour a feature.
- **Framing:** call this "an application incident running on Aurora
  PostgreSQL." Never call it an Aurora service incident.

### Governing scope

The required release path is incident hybrid retrieval through cited synthesis,
diagnostics, and replay. It uses `make schema` (`sql/00` through `sql/10`) with
`WORKBENCH_SECURITY_ENABLED=0`, and it must not require persona roles, RLS, or
`pg_columnmask`.

RLS and column masking are an implemented optional appendix. That path uses
`make security-schema`, enables `WORKBENCH_SECURITY_ENABLED=1`, connects the API
with `WORKSHOP_APP_DATABASE_URL`, and runs `make security-checks`. Its gates do
not belong to the default release gate set. A `BLOCKED` appendix gate is not
evidence of a pass.

## 4. Current Validated State

This snapshot must be refreshed before the release artifact is frozen.

| Area | Current evidence | Status |
|---|---|---|
| Database connection | Aurora PostgreSQL endpoint, database `retrieval`, application user `retrieval_admin` | Live validated |
| PostgreSQL | `18.3` | Live validated |
| Extensions | `vector 0.8.1`, `pg_trgm 1.6`, `pg_stat_statements 1.12` | Live validated |
| Search corpus | 15,017 source rows, current documents, chunks, and ready embeddings | Live validated |
| Search index drift | The current development cluster has known drift and must not be used as release evidence until repaired | Open release gate |
| Embedding space | `us.cohere.embed-v4:0`, 1,024 dimensions | Live validated |
| Latest complete build | 15,017 documents, 15,017 chunks, 15,017 cache hits, 0 new embeddings | Live validated |
| Synthesis | `global.anthropic.claude-sonnet-5` through Bedrock Converse and Global CRIS | Live validated in the current Isengard account |
| Rerank | `cohere.rerank-v3-5:0` through Bedrock Agent Runtime | Live validated in the current Isengard account |
| Optional security appendix | Persona RLS and Auditor masking exist in `sql/11-12`; `pg_columnmask` requires Aurora validation | Implemented; not a core release gate |
| Lock fixture | 25,000 transient rows; real `ShareLock` and `RowExclusiveLock` wait chain; safe concurrent retry | Validated locally on PostgreSQL 18.4; target rehearsal required |
| Workshop guides | Required incident, retrieval, agent, proof, and replay pages are rewritten; RLS and AgentCore are optional tracks | Implemented |
| Release archive | The checked-in zip is retired v1 content and `SourceRevision=UNRELEASED` blocks it | Open release blocker |
| Proof screenshots | Run record, Replay, and mobile references still show the local hash model and 222-document corpus | Target recapture required |

### Current environment distinctions

Three different instance descriptions currently exist and must not be merged:

1. The current Isengard validation cluster uses `db.serverless`.
2. The synthetic scenario record describes `checkout-prod-cluster-01` as
   `db.r8g.xlarge`.
3. The Workshop Studio CloudFormation template defaults to the representative
   rehearsal class `db.r8g.2xlarge`.

The 25,000-row lab and 317 MB measured retrieval database do not require 64 GiB
of memory. `db.r8g.2xlarge` is the fixed event rehearsal target, not a
dataset-size minimum. A fresh Workshop Studio deployment must establish the
actual release class and behavior.

## 5. Incident Ground Truth

### Canonical identifiers

| Concept | Value |
|---|---|
| Production cluster | `checkout-prod-cluster-01` |
| Table under migration | `workbench_lab.orders` |
| Primary incident | `INC-2047` |
| Causal change | `CHG-1842` |
| Safe follow-up change | `CHG-1907` |
| Index | `idx_orders_customer_created` |
| Lock observations | `LOCK-2047-001`, `LOCK-2047-002` |
| Visible support case | `CASE-7419`, Acme Retail (fictional) |
| Restricted support case | `CASE-7421`, Northstar Foods (fictional) |
| Unaffected support case | `CASE-7424`, Zenith Corp (fictional) |
| Current runbook | `RB-017` |
| Superseded runbook | `RB-092` |
| Commitment | `COMMIT-4471` |
| Postmortem | `PM-2047` |
| Fuzzy input | `CGH-1842` |

### Canonical question

> Why did `CHG-1842` block checkout writes during `INC-2047`, which visible
> customer was affected, and what was the safe fix?

### Root-cause statement

A plain `CREATE INDEX` takes `ShareLock` on the target table. Ordinary reads use
`AccessShareLock`, which does not conflict with `ShareLock`, so reads can
continue. `INSERT`, `UPDATE`, and `DELETE` use `RowExclusiveLock`, which
conflicts with `ShareLock`, so writers wait.

`CREATE INDEX CONCURRENTLY` uses `ShareUpdateExclusiveLock`, which does not
conflict with `RowExclusiveLock`. It allows ordinary reads and writes to
continue, but it performs two table scans, waits for relevant transactions,
usually takes longer, cannot run inside a transaction block, and can leave an
`INVALID` index after failure.

### Reproduction realism boundary

The ordinary index build is real, but 25,000 rows build too quickly for a
reliable room-wide observation. `labs/incident/10_unsafe_index.sql` therefore
keeps the explicit transaction open after `CREATE INDEX` completes. PostgreSQL
retains the genuine `ShareLock`, and the participant's writer genuinely waits
for `RowExclusiveLock` while reads continue.

The observer reads live `pg_stat_activity`, `pg_locks`, and
`pg_blocking_pids()` rows and writes a measured JSON capture. The safe phase
then observes `ShareUpdateExclusiveLock` and proves fresh DML succeeds beside
`CREATE INDEX CONCURRENTLY`.

This technique proves lock compatibility and the wait chain. It does not prove
Aurora index-build duration, production throughput impact, or instance-class
performance. No duration or throughput number from the lab may appear as a
production claim.

## 6. Corpus and Data Design

### Search corpus

The current search corpus has exactly 15,017 current evidence items:

| Evidence kind | Count |
|---|---:|
| Change | 3,755 |
| Incident | 3,753 |
| Support case | 3,753 |
| Runbook | 3,752 |
| Lock evidence | 2 |
| Commitment | 1 |
| Postmortem | 1 |

Seventeen records form the focused incident fixture. The remaining 15,000
records are deterministic background incidents, changes, cases, and runbooks
with fictional tenant names. The corpus makes filtered retrieval and ranking
behavior observable; it is not customer data.

### Separate lock fixture

The incident lab creates 25,000 rows in `workbench_lab.orders`, then
`99_cleanup.sql` drops that schema. It is separate from the persistent
15,017-document search corpus. The row count makes the real lock relationship
quick and deterministic; it does not define retrieval scale or production
index-build duration.

### Ownership

| Schema | Responsibility |
|---|---|
| `casework` | Normalized source identity, typed domain records, ACLs, tombstones, and authoritative foreign-key relationships |
| `retrieval` | Versioned documents, chunks, embeddings, indexes, search functions, uniform edge reads, and search index health |
| `proof` | Retrieval runs, candidate signals, stages, agent records, answers, citations, judgments, and evaluation results |

`casework.*` is authoritative inside the synthetic fixture. `retrieval.*` is
one-way derived and rebuildable. `proof.*` preserves what a request actually
used.

### Search index lifecycle

```text
typed casework transaction
  -> source revision and ACL
  -> casework.queue_evidence(evidence_id)
  -> retrieval.search_index_queue
  -> deterministic render and hash
  -> versioned document and chunks
  -> cached or generated embeddings
  -> promote ready version
  -> complete build and outbox receipts
```

Production connectors must write typed domain records and queue the affected
evidence ID in the same transaction. Applications must not hand-edit indexed
documents.

## 7. Retrieval Contract

### Retrieval arms

| Arm | PostgreSQL implementation | What it proves |
|---|---|---|
| Exact identifier | B-tree and boundary-aware ID matching | Precise IDs such as `CHG-1842` |
| Full text | Document and chunk `tsvector` streams with GIN | Exact operational language |
| Semantic | pgvector cosine distance over 1,024-dimensional vectors | Meaning when words differ |
| Fuzzy | `pg_trgm` GIN over IDs and titles | Typo recovery such as `CGH-1842` |

### Filters and authorization

Supported filters include evidence kind, cluster, incident, account, severity,
environment, service, engine version, Region, and time range.

An ACL predicate runs inside every retrieval arm before fusion and at the seed
and every hop of relationship traversal:
`retrieval.acl_visible(acl)` over the JSONB and
`retrieval.acl_scalars_visible(acl_visibility)` over the projected column. In
core mode these predicates expose only `visibility = 'workshop'`; the role-shaped
argument remains API compatibility metadata and does not require a database
persona.

The optional security appendix replaces those predicates with persona-aware
versions and adds forced RLS plus `pg_columnmask`. The application still accepts
the persona from the request because the workshop ships no authentication.
Therefore the appendix demonstrates database enforcement under an assumed
persona, not production caller authorization. A production API must derive that
persona from verified identity and revalidate mutable source permissions.

### Ranking: a deterministic tier above weighted RRF

Final order is a two-key sort, not a single score. Exact identifier resolution
is a tier, and weighted RRF orders candidates within the fused tier:

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

Exact identifier resolution is a fact about the query, not a score. It is a
B-tree equality probe on `lower(external_key)`: either the caller named an
indexed identifier or they did not. Expressing it as a fourth weighted term
would make it outrankable by construction, because any weighted term can be
beaten by a large enough weight on another arm. With `w_text = 0` and
`w_vector = 10` — both inside the ranges the UI exposes — a semantic false
positive measurably outscored `CHG-1842`. Tiering makes the acceptance
criterion in section 14 hold for every weight setting a participant can dial,
which a weighted term cannot do.

Three ranked arms therefore contribute three weighted terms. An absent arm
contributes zero. Every published `rrf_score` reproduces exactly from the
formula above, including for tier 1 rows: a tier 1 row can legitimately carry a
lower `rrf_score` than the row beneath it, and the UI shows both values rather
than reconciling them silently.

Weights are `numeric`. Integer `2 / (60 + 1)` truncates to `0` and flattens
every score.

Raw `ts_rank`, cosine distance, trigram similarity, RRF, and model rerank
scores stay separate. None is a probability. Cohere reranking reorders within a
tier and never across tiers: it scores relevance, not identity, so it has no
basis for demoting an identifier the caller named.

### HNSW controls

- index operator class: `vector_cosine_ops`;
- index build settings: `m=16`, `ef_construction=64`;
- query `ef_search`: default `40`, allowed `1..1000`;
- iterative scan: `off`, `strict_order`, or `relaxed_order`;
- request default in the current API: `strict_order`.

The planner chooses the plan. The UI and guide must display the actual
`EXPLAIN` output and must not claim HNSW was used when PostgreSQL chose a bitmap
or exact path.

### Model reranking

Cohere Rerank v3.5 runs after Aurora selects and persists the fused pool. It can
change presentation order but cannot overwrite the Aurora RRF score. On model
failure:

- persist the failed or skipped stage;
- set `rerank_applied = false`;
- retain SQL order; and
- do not fabricate a rerank score.

## 8. Relationship and Agent Contract

### Relationship reads

`retrieval.evidence_edges` is the uniform read view over:

- canonical foreign-key relationships with confidence `1`; and
- separately labeled inferred edges with method, confidence, and source
  revision.

The workshop uses foreign keys to establish support case, incident, change,
runbook, commitment, and postmortem relationships. Full-text co-occurrence is
not a declared relationship.

### Agent tools

The implemented answer sequence is:

1. `decompose_question`
2. `search_evidence`, once per subquestion plus bounded retries
3. `follow_evidence_links`
4. `compare_sources`
5. `synthesize_cited_answer`

Two more tools are registered but sit outside that sequence. `explain_ranking`
re-reads a persisted receipt without calling a model, so neither answer path
sequences it; it backs the Proof surface and `GET /v1/runs/{run_id}`.
`answer_with_citations` runs the whole loop in one call and is exposed only on
the managed transports.

Strands provides the Python tool surface. FastAPI, the Lambda adapter, and the
stdio MCP server call the same owning implementations. No adapter contains
ranking SQL.

### Citation integrity

Every citation records:

- evidence ID;
- document and chunk version IDs;
- source URI;
- source revision;
- exact quote; and
- supported claim.

`proof.validate_answer_citations(run_id)` verifies URI, revision, and quote
against the exact persisted chunk. This proves attribution integrity. It does
not prove that every statement in a source is objectively true.

## 9. Application and Managed Boundaries

### FastAPI

The public read and proof surface includes:

- search by hybrid, semantic, lexical, or fuzzy mode;
- complete and streaming cited answers;
- decomposition, traversal, comparison, ranking explanation, and synthesis;
- evidence details;
- retrieval receipts, candidates, graph, and timeline;
- search index, corpus, fusion SQL, plan, index, and slow-query diagnostics;
- retrieval and traversal evaluation.

There is no generic source-object write API.

### Hybrid Retrieval Workbench UI

The UI uses a persistent incident-oriented navigation:

1. **Diagnose hybrid retrieval**
   - Retrieval lab
   - Fusion anatomy
   - Query plan
   - Scale and builds
2. **Audit cited provenance**
   - Answer and plan
   - Evidence graph
   - Replay receipt
   - Evaluation
3. **Invoke managed contract**

The UI consumes live API and proof data. It does not hardcode answers,
candidate scores, relationships, or citations.

### Managed tool contract

Workshop Studio provisions an `AWS_IAM`-authorized Amazon Bedrock AgentCore
Gateway and a stateless Lambda MCP target. The target calls Hybrid Retrieval
Workbench's private API and records transport metadata. Aurora still owns
retrieval and proof.

The Gateway is not a second search implementation. Gateway authorization does
not replace the core evidence predicate or, when enabled, optional row-level
security.

## 10. Participant Path

Every required block ends with inspectable PostgreSQL or persisted proof.

### Context and architecture

**Time:** 0-5 minutes

Frame the production symptom, the real lock relationship, and the ownership
boundary: operational systems remain authoritative, while Aurora PostgreSQL
owns retrieval, ranking, relationships, citations, diagnostics, and replay.

### Prove readiness

**Time:** 5-10 minutes

Run `make doctor` and confirm Aurora PostgreSQL, required extensions, the
Cohere embedding space, 15,017 ready documents and chunks, and zero search-index
drift.

**Checkpoint:** the environment is ready before any participant creates the
controlled incident.

### Lab 1: Reproduce and observe

**Time:** 10-20 minutes

Run all nine `labs/incident/*.sql` files across three terminals. Prove reads
continue, ordinary `CREATE INDEX` blocks a writer, the blocking PID is
measured, `CREATE INDEX CONCURRENTLY` permits fresh DML, and the final index is
ready, valid, and live.

**Checkpoint:** PostgreSQL catalogs and `pg_blocking_pids()` reproduce the
failure mechanism, and cleanup leaves no relation waiter.

If terminal orchestration threatens the 10-minute block, use the facilitator's
measured capture and safe-fix verification. Never present a prewritten lock row
as a live observation.

### Lab 2: Build hybrid retrieval

**Time:** 20-40 minutes

Run exact and full-text retrieval for `CHG-1842`, fuzzy retrieval for
`CGH-1842`, semantic retrieval for the write-stall symptoms, metadata filters,
weighted RRF, optional Cohere reranking, and one live arm plan. Keep exact,
text, vector, fuzzy, RRF, and rerank signals separate.

**Checkpoint:** `CHG-1842` ranks first, the typo resolves correctly, semantic
retrieval works without exact wording, filters execute before fusion, and the
receipt explains why each result ranked where it did.

**First cut when behind:** remove the filtered-HNSW comparison, then live
reranking. Preserve exact, fuzzy, semantic, fusion, and the plan inspection.

### Lab 3: Build the incident agent

**Time:** 40-50 minutes

Ask the canonical question. Inspect decomposition, targeted retrieval,
relationship traversal, distractor rejection, ranking explanation, and cited
synthesis.

**Checkpoint:** the answer identifies the lock conflict, Acme Retail
(fictional), and `CREATE INDEX CONCURRENTLY`, with factual claims tied to
numbered evidence.

### Lab 4: Prove and replay

**Time:** 50-55 minutes

Save the `run_id`; load the candidate receipt, graph, and timeline; validate
citation URI, revision, chunk, and quote; reproduce one displayed diagnostic
with verify-SQL; and replay without another model call.

**Checkpoint:** `/v1/runs/{run_id}`, `/graph`, and `/timeline` resolve
persisted proof, and `proof.validate_answer_citations` validates every
citation.

### Summary and production boundary

**Time:** 55-60 minutes

Run or inspect the compact retrieval and traversal evaluation, then identify
which evidence a production system should materialize, federate, or revalidate
live. Retrieval metrics and relationship-traversal metrics remain separate.

Do not start a new demo after minute 55.

### Optional appendix: Invoke the managed contract

This exercise is outside the required 60-minute path.

Participants:

1. verify the AgentCore Gateway and target are `READY`;
2. confirm `AWS_IAM` authorization;
3. invoke `search_evidence` or `answer_with_citations`;
4. capture the returned `run_id`; and
5. compare its receipt with the HTTP path.

**Checkpoint:** the managed call creates real Aurora proof through the same
contract. If the managed resources are not release-validated, this exercise is
replaced by local MCP parity and the managed path moves to the appendix.

### Optional appendix: Enforce personas and masking

This appendix is not timed and is not required for the default release:

1. apply `make security-schema` on Aurora PostgreSQL;
2. configure `WORKSHOP_APP_DATABASE_URL` and
   `WORKBENCH_SECURITY_ENABLED=1`;
3. compare the same restricted query as App Engineer, Auditor, and DBA;
4. verify that App Engineer cannot see `CASE-7421`, Auditor sees it masked, and
   DBA sees it unmasked; and
5. require G-27, G-29, G-30, and G-31 to report `PASS`, not `BLOCKED`.

Local PostgreSQL may skip `sql/12_masking.sql` when `pg_columnmask` is
unavailable; that is useful for partial development but is not appendix release
evidence. Do not run `make schema` alone after enabling the appendix because
`sql/03` restores the core predicates; reapply the complete security schema.

## 11. Facilitator Fallbacks

| Failure | Continue with |
|---|---|
| One terminal cannot reach Aurora | Pair with a validated environment; do not switch the room to a different database |
| Multi-session incident lab falls behind | Use the facilitator's measured capture and safe-fix verification; preserve the retrieval path |
| Query embedding is slow | Reuse the persisted prepared query vector |
| Cohere rerank fails | Show `rerank_applied=false` and retain Aurora order |
| Synthesis fails | Use the extractive answer built from the same persisted evidence |
| Frontend fails | Use HTTP endpoints and SQL proof views |
| Gateway fails | Prove HTTP or stdio MCP parity and move the managed boundary to the appendix |
| Room is behind | Cut weight experimentation, then detailed evaluation; preserve cited answer and replay |

Fallbacks may reuse persisted proof. They may not substitute invented output.

## 12. Workshop Infrastructure Profile

The sibling Workshop Studio repository is intended to provision:

- a VPC with public and private subnets;
- Aurora PostgreSQL in private subnets;
- a KMS key and Secrets Manager database secret;
- an Aurora writer instance;
- enhanced monitoring, Performance Insights, and PostgreSQL log export;
- Code Editor with the immutable workshop source archive;
- preloaded schema, casework, embeddings, and indexes;
- FastAPI and Vite;
- optionally, AgentCore Gateway with one Lambda MCP target; and
- participant-visible `WorkshopURL` and `WorkbenchURL`, plus Gateway outputs
  only when that appendix is enabled.

The current template is a workshop profile, not a production reference. It
uses one writer, one-day backup retention, deletion protection off, and
`rds.force_ssl=0`. Those choices support ephemeral lab teardown and must not be
copied into a production deployment.

The current Isengard validation cluster is also not the release template. It
uses `db.serverless`, one-day backup retention, no deletion protection, no
Performance Insights, and storage that is not encrypted. It is a temporary
development proof surface and does not establish Workshop Studio or production
security, instance, durability, or observability settings.

## 13. Production Adaptation Requirements

These controls are not participant exercises, but the workshop must explain
where they belong.

### Identity and authorization

- authenticate every API caller;
- derive the evidence persona from trusted identity, not request JSON;
- map source-system permissions through a reviewed policy;
- apply authorization before retrieval, at every graph hop, and before
  returning citations;
- revalidate volatile permissions in the source system; and
- log authorization decisions without exposing sensitive content.

### Database roles

Separate:

- schema migration owner;
- authoritative casework writer;
- search index worker;
- retrieval and proof writer;
- read-only diagnostics user; and
- facilitator-only release operations.

The workshop administrative role is setup convenience, not a production role
design.

### Network and transport

- keep Aurora private;
- require TLS and certificate verification;
- restrict security groups to owning workloads;
- use private service connectivity where required by the deployment;
- restrict CORS to the deployed application origin;
- place authentication, request limits, and abuse controls before FastAPI; and
- do not expose the unauthenticated local API publicly.

### Secrets and encryption

- store database credentials in Secrets Manager;
- use short-lived workload roles rather than static AWS keys;
- encrypt Aurora, snapshots, logs, and model-related artifacts with approved
  keys;
- rotate keys and secrets under an owned process; and
- keep `.env`, dumps, caches, logs, and live exports out of source control.

### Availability, backup, and recovery

- choose writer and reader topology from measured RTO and RPO;
- add an Aurora replica in another Availability Zone when compute failover
  requirements demand it;
- set backup retention and deletion protection for the environment;
- test restore, failover, connection recovery, and search readiness;
- preserve immutable source and embedding artifacts; and
- document degraded behavior when Bedrock or the search index is unavailable.

### Search index operations

- use source cursors, idempotent retries, bounded batches, and dead-letter
  handling;
- reconcile periodically for missed updates and deletions;
- reuse embeddings only for the same model ID and chunk hash;
- run `ANALYZE` after material scale changes;
- build replacement HNSW indexes under an operational rollout;
- monitor queue age, build failures, drift, stale revisions, and model-space
  mismatches; and
- preserve versions referenced by historical proof.

### Observability

Correlate:

- API request ID;
- transport trace ID;
- agent run ID;
- retrieval run ID;
- search index build ID;
- model request metadata; and
- database query and wait evidence.

Production dashboards should cover API latency and errors, pool saturation,
Aurora connections and waits, slow retrieval SQL, search index freshness,
candidate and stage latency, model throttles, token use, citation failures,
Gateway/Lambda errors, and evaluation regressions.

Do not hardcode CloudWatch or Database Insights metric names from memory.
Validate the release engine and console, capture literal output, and update the
validator before freezing screenshots.

### Capacity, quotas, and cost

- establish p50, p95, and p99 targets from load tests;
- test room-scale and production concurrency separately;
- size the database pool and Aurora capacity from measured demand;
- validate Bedrock request, token, and rerank quotas;
- use bounded adaptive retries and backpressure;
- cache immutable embeddings and batch release generation;
- track storage growth from document, embedding, and proof retention; and
- set budgets and alarms for release generation and model use.

No latency, throughput, recall, or cost target should be presented without a
test method, fixture, sample size, and timestamp.

### Data governance and retention

- classify source content before materializing it;
- minimize text sent to embedding, rerank, and synthesis models;
- define source, indexed-version, receipt, citation, and log retention;
- preserve legal or audit history where required;
- tombstone deleted evidence from new retrieval while retaining authorized
  historical proof; and
- document cross-Region model routing and residency implications.

### Model governance

- pin configurable model IDs for the release;
- verify lifecycle, Region and CRIS support, marketplace access, IAM, and
  quotas in a fresh target account;
- keep document and query vectors in the same model space and input-type
  contract;
- rerun retrieval evaluation after any embedding or rerank model change;
- preserve SQL order when rerank is unavailable; and
- never label a model score as confidence or probability.

The current path uses Bedrock Converse with Global CRIS. It does not claim
Mantle. A geographic profile must replace Global CRIS when residency requires
it.

## 14. Evaluation and Acceptance Criteria

### Retrieval

- `CHG-1842` is exact and lexical rank 1 under the production cluster filter,
  and holds rank 1 at every weight setting the API accepts.
- `CGH-1842` resolves to `CHG-1842` through indexed trigram retrieval.
- the semantic symptom query retrieves relevant evidence without requiring
  exact wording;
- all arms apply filters and ACLs before fusion;
- one strongest passage survives per evidence item;
- independent positions and raw diagnostics remain inspectable; and
- the stored and query embedding spaces match exactly.

### Visibility and relationships

- core retrieval admits only workshop-visible evidence before fusion and at
  every traversal hop;
- `CASE-7421` does not enter the core answer;
- canonical and inferred edges remain distinguishable;
- `CHG-1842` is confirmed and `CHG-1838` is ruled out;
- `CASE-7419` is affected and `CASE-7424` is unaffected; and
- traversal depth and ACLs are enforced at every hop.

### Optional security appendix

- App Engineer cannot retrieve or traverse to `CASE-7421`;
- Auditor retrieves the restricted fixture with sensitive values masked;
- DBA retrieves the same fixture unmasked;
- a missing `SET LOCAL ROLE` fails closed; and
- replay preserves the recorded persona envelope.

### Proof

- each run exists before retrieval;
- candidate signals and stages persist before synthesis;
- citations resolve to exact source and chunk versions;
- citation URI, revision, and quote validation passes;
- replay returns candidates, stages, answer, and citations without a new model
  call; and
- HTTP, Gateway/Lambda, and stdio MCP preserve the same contract.

### Search index

- unchanged content and embeddings are reused;
- changed content creates a version and supersedes the prior current version;
- tombstones remove evidence from new retrieval without erasing history;
- exactly one current ready document exists per live source;
- every ready chunk has an embedding in the expected model space; and
- readiness fails on drift or an incomplete build.

### Delivery

- a fresh participant completes the core in 60 minutes;
- no participant provisions Aurora or generates 15,000 embeddings;
- every command uses current `casework`, `retrieval`, and `proof` contracts;
- screenshots match the current Hybrid Retrieval Workbench UI;
- no required step depends on a facilitator's private environment; and
- cut lines preserve the cited-answer and replay outcome.

## 15. Release Gates

### P0: must close before publication

1. Build the v2 seed dump and source archive from the same immutable tested
   application revision, then replace `SourceRevision=UNRELEASED`.
2. Verify the archive revision, SHA-256 sidecar, three dump schemas, and all
   nine incident SQL files.
3. Replace the stale Run record, Replay, and mobile proof images with captures
   from the frozen Cohere-backed target.
4. Run a fresh-account Workshop Studio deployment on `db.r8g.2xlarge`.
5. Run every participant command and all nine incident scripts with the
   participant role.
6. Prove exact, lexical, semantic, fuzzy, fusion, fixed visibility, traversal,
   citation, diagnostics, replay, and evaluation checkpoints.
7. Verify all configured Bedrock models and quotas with the participant role.
8. Repair search-index drift before using the target as release evidence.
9. Record the actual release instance class, corpus counts, index sizes, source
   revision, and archive hash.
10. Test the full 60-minute path with cut lines.

G-27, G-29, G-30, and G-31 are optional-security appendix gates. They must pass
before publishing that appendix, but they are not prerequisites for the core
workshop release.

Managed Gateway parity is likewise an appendix release condition, not a core
publication prerequisite.

### P1: must close before calling the workshop production-informed

1. Run room-scale load and throttling tests.
2. Test API restart, pool recovery, model failure, and Aurora failover behavior.
3. Review IAM, CORS, TLS, Secrets Manager, KMS, logs, and generated artifacts.
4. Confirm no credentials, live exports, logs, or unreviewed 241 MB embedding
   cache are included in source control.
5. Capture literal query plans for prepared filtered-HNSW exercises.
6. Re-run the controlled evaluation and store the baseline.
7. Verify all links, rendered pages, images, code blocks, and escape hatches.

## 16. Explicit Non-Claims

The workshop does not claim:

- a real AWS or customer incident;
- that the core release enables persona RLS or column masking;
- a production-ready authorization system;
- a production connector platform;
- a release-grade Aurora telemetry capture in the current data;
- that HNSW is chosen for every semantic query;
- that any score is a probability or universal confidence value;
- that AgentCore Gateway owns retrieval;
- that local PostgreSQL behavior alone proves Aurora behavior;
- that the Workshop Studio lab topology is a production topology; or
- that a scheduled remediation record proves the remediation executed.

## 17. Repository Ownership

| Repository or path | Owns |
|---|---|
| This repository | Application source, SQL, synthetic corpus, API, UI, adapters, tests, and implementation contracts |
| `backend/app/` | Search index, embeddings, retrieval, rerank, tools, synthesis, and proof APIs |
| `sql/` | Core schema, indexes, search, diagnostics, receipts, traversal, and evaluation (`00-10`), plus optional RLS and masking (`11-12`) |
| `seed/` | Deterministic incident corpus and capture tooling |
| `frontend/` | Hybrid Retrieval Workbench UI |
| `lambda_mcp/` | Stateless AgentCore Gateway target |
| `mcp-server/` | Optional stdio MCP adapter |
| Sibling Workshop Studio repository | CloudFormation, IAM, Code Editor, participant guides, screenshots, Gateway deployment, and packaged source archive |

Workshop Studio pushes and publication remain user-managed unless explicitly
requested.

## 18. Definition of Done

The workshop is done only when:

1. the application revision is immutable;
2. the packaged source matches that revision;
3. the fresh-account stack succeeds;
4. the participant path passes inside 60 minutes;
5. all receipts and screenshots come from that environment;
6. every production claim is labeled and evidenced;
7. all P0 gates are closed; and
8. unresolved P1 work is documented without being presented as implemented.
