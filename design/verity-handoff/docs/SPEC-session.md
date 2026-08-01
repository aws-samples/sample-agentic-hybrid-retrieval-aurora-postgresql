# SPEC - DAT410 builders session

## Build agentic hybrid retrieval with Amazon Aurora PostgreSQL

**Version:** draft-24, August 1, 2026
**Level:** 400
**Duration:** 60 minutes

**Abstract:** As applications evolve from RAG to agentic workflows, retrieval
must support more than top-k semantic matches. In this session, use Aurora
PostgreSQL as the core search and context engine for agentic hybrid retrieval.
Implement PostgreSQL full-text search for lexical retrieval, pgvector semantic
similarity, SQL and metadata filters, fuzzy matching, reciprocal rank fusion,
model-based reranking, source attribution, and retrieval diagnostics. Then wire
these capabilities into agent tools that decompose complex questions, gather
targeted evidence, compare sources, explain ranking signals, and synthesize
cited answers. Leave with working code, schema patterns, ranking templates, and
techniques for trustworthy retrieval-heavy AI applications.

This document is the session contract. The application implementation remains
authoritative for schemas, APIs, SQL functions, and exact response shapes. The
sibling Workshop Studio repository is authoritative for participant-facing page
order and infrastructure.

---

## 0. Session spine and laws

The workshop is an incident-evidence system, not a generic chatbot:

```text
Observe and reproduce
        |
        v
Retrieve and fuse
        |
        v
Investigate with tools
        |
        v
Prove and replay
```

The canonical question is:

> Why did CHG-1842 block checkout writes during INC-2047, which visible
> customer was affected, and what was the safe fix?

The participant first creates the PostgreSQL lock relationship behind the
synthetic incident. They then investigate the preloaded historical record of
that incident through exact, lexical, semantic, fuzzy, and filtered retrieval;
weighted reciprocal rank fusion (RRF); optional model reranking; relationship
traversal; cited synthesis; and replayable proof.

**Law 1 - Same incident nouns everywhere.** The live lab uses
`workbench_lab.orders` and `idx_orders_customer_created`. The historical
evidence uses `CHG-1842`, `INC-2047`, `CGH-1842`, and
`checkout-prod-cluster-01`. The guide must state clearly that the lab schema is
a disposable reproduction of the mechanism, not the authoritative casework
record.

**Law 2 - PostgreSQL owns retrieval and proof.** Canonical retrieval, filters,
fusion, traversal, citations, diagnostics, and replay stay in
`casework`, `retrieval`, and `proof`. The frontend and agent consume those
contracts; they do not reimplement ranking.

**Law 3 - Scores remain typed.** Full-text rank, cosine similarity, trigram
similarity, weighted RRF, and model rerank scores have different meanings.
They remain separate and none is presented as a probability.

**Law 4 - Answers require evidence.** The agent may synthesize only from
numbered evidence. A citation is valid only when its source URI, revision,
chunk, and quoted span resolve. Attribution validation is not a claim-truth
score.

**Law 5 - Replay is a product requirement.** Candidate signals and stages are
persisted before synthesis. A saved `run_id` replays candidates, answer,
citations, graph, and timeline without another model call.

**Law 6 - The synthetic boundary is explicit.** The corpus is deterministic
synthetic workshop data. Live PIDs, locks, wait events, relation OIDs, and
catalog rows in Lab 1 come from the connected PostgreSQL engine. Neither is
presented as real customer incident data.

---

## 1. Binding decisions

| ID | Decision | Consequence |
|---|---|---|
| D1 | The incident is the spine, not a separate database-operations workshop. | Lab 1 gets ten minutes. If terminal orchestration runs long, use the measured capture and protect retrieval, cited synthesis, and replay. |
| D2 | Lab 1 uses the shipped 25,000-row `workbench_lab.orders` substrate. | The ordinary build completes quickly, then its explicit transaction remains open so the genuine `ShareLock` stays observable. This proves lock compatibility and the wait chain, not production build duration or throughput. |
| D3 | The preloaded evidence corpus is the deterministic evaluation target. | Participants do not generate 15,000 embeddings, build HNSW, or depend on admitting their live capture before retrieval. Evidence admission is an optional extension. |
| D4 | Engine-first ordering is fixed. | Hybrid Retrieval precedes Agentic Retrieval, so participants can inspect arm positions, RRF, and reranking before reading an agent trace. |
| D5 | Exact, full-text, semantic, fuzzy, filters, fusion, reranking, citations, diagnostics, and replay are core. | Every item named in the title and abstract has a participant checkpoint. |
| D6 | Aurora PostgreSQL is the engine of record for the workshop. | Relational truth, search projection, ranking, receipts, and citation validation remain inspectable in one database. |
| D7 | The agent is bounded by evidence requirements and tool budgets. | It decomposes, retrieves, traverses, compares, explains, and then synthesizes. Plausible prose without persisted evidence is a failure. |
| D8 | RLS with `pg_columnmask` is optional. | The reference application keeps the implementation, but the App Engineer, Auditor, and DBA comparison is not a prerequisite, title claim, or core release gate. |
| D9 | AgentCore Gateway is optional. | It demonstrates transport parity over the same API and receipts. Gateway deployment cannot block the one-hour core. |
| D10 | Database Insights is an optional facilitator overview. | Participant observability is terminal-native through `pg_stat_activity`, `pg_locks`, and `pg_blocking_pids()`. No participant AWS console access is required. |
| D11 | `db.r8g.2xlarge` is the representative validated workshop class, not a dataset-size minimum. | A fresh-stack rehearsal must use it. The class is not justified by the retired 25-million-row design, and no gate depends on a multi-minute index build. |
| D12 | Workshop Studio provisions one revision-bound archive containing committed source plus the binary seed dump. | Participant stacks do not clone GitHub. The dump supplies fixed Cohere Embed 4 vectors without a model call during provisioning. |

---

## 2. Architecture and environment

### 2.1 Ownership boundary

| Surface | Owns |
|---|---|
| `workbench_lab` | disposable operational workload used only for the lock reproduction |
| `casework` | authoritative synthetic incidents, changes, cases, runbooks, lock evidence, and foreign-key relationships |
| `retrieval` | derived documents, chunks, embeddings, exact/FTS/HNSW/trigram indexes, ranking functions, traversal, and search-index readiness |
| `proof` | retrieval runs, candidate-level signals, stages, answers, citations, evaluation, graph, timeline, and replay |
| Backend | API orchestration, model adapters, agent tools, and extractive degradation |
| Frontend | inspection UI over API responses and persisted proof |
| Operational source systems | mutable workflow state, current permissions, and actions in a production design |

The projection is rebuildable. Stable evidence identity, source URI, revision,
content hash, ACL metadata, model space, and citation coordinates are not
optional metadata.

### 2.2 Representative account

- One Aurora PostgreSQL writer in `us-east-1`, representative class
  `db.r8g.2xlarge`.
- PostgreSQL extensions required by the core: `vector`, `pg_trgm`, and
  `pg_stat_statements`.
- One Code Editor host running the terminal, FastAPI backend, and React
  frontend behind the authenticated workshop route.
- Preloaded deterministic casework and Cohere Embed 4 vectors.
- Bedrock access for query embedding, optional Cohere reranking, and cited
  synthesis.
- No participant console access, load generator, reader instance, RDS Proxy,
  or Gateway requirement in the core.

The representative class provides event headroom and a stable rehearsal target.
It is not a claim that the corpus requires 64 GiB. A measured July 31 snapshot
of the current live retrieval database contained 41 tables and approximately
317 MB total:

| Object | Measured rows or size |
|---|---:|
| `retrieval.chunks` | 15,017 rows, 241 MB total |
| `retrieval.documents` | 15,017 rows, 53 MB total |
| `casework.evidence_items` | 15,017 rows, about 6.3 MB |
| HNSW embedding index | 117 MB |

These figures are release evidence, not hardcoded readiness targets. Provisioned
counts and sizes must be measured again from each frozen artifact.

### 2.3 Provisioning and archive contract

Workshop Studio's `PrepareWorkshopSource` step downloads
`hybrid-retrieval-source.zip`; it does not clone `GitHubRepo`. The archive
contains:

1. source from `git archive` at one committed application revision;
2. `seed/artifacts/hybrid-retrieval-seed-v2.dump`; and
3. the dump's `.revision` sidecar, equal to the source revision; and
4. the dump's `.sha256` sidecar, equal to the packaged bytes.

The dump must contain table data for `casework`, `retrieval`, and `proof`. It
must be produced from an explicitly disposable, seeded database. The archive
build fails when the worktree is dirty, revisions differ, the checksum differs,
a schema is absent, or a participant-required path is missing.

The binary dump is load-bearing because it carries fixed vectors. Source could
theoretically come from a pinned clone, but the event environment would then
depend on GitHub reachability. The single archive is the safer current
deployment contract.

Core schema setup applies `sql/00_extensions.sql` through
`sql/10_admission.sql`. Optional security setup applies
`sql/11_roles_rls.sql` and `sql/12_masking.sql` separately.

---

## 3. Lab 1 - Reproduce and observe the write stall

Lab 1 uses three PostgreSQL sessions and these exact files:

| Order | File | Proof |
|---:|---|---|
| 1 | `labs/incident/00_setup.sql` | creates 25,000 rows in disposable `workbench_lab` |
| 2 | `labs/incident/10_unsafe_index.sql` | ordinary `CREATE INDEX` owns granted `ShareLock` in an open transaction |
| 3 | `labs/incident/20_blocked_writer.sql` | read completes; `UPDATE` waits for `RowExclusiveLock` |
| 4 | `labs/incident/30_observe_unsafe.sql` | catalogs and `pg_blocking_pids()` prove the wait chain and write measured JSON |
| 5 | `labs/incident/40_safe_writer.sql` | one normal writer transaction remains open |
| 6 | `labs/incident/50_concurrent_index.sql` | `CREATE INDEX CONCURRENTLY` owns `ShareUpdateExclusiveLock` |
| 7 | `labs/incident/60_observe_safe.sql` | a fresh `UPDATE` completes beside the concurrent build |
| 8 | `labs/incident/70_verify.sql` | index is ready, valid, live, and no relation waiter remains |
| 9 | `labs/incident/99_cleanup.sql` | removes only `workbench_lab`; retains the measured capture |

### 3.1 Unsafe phase

The ordinary index build is real. Its explicit transaction is deliberately held
open after the small index finishes so PostgreSQL retains the real relation
lock:

```text
ordinary CREATE INDEX       granted ShareLock
checkout UPDATE             waiting RowExclusiveLock
order-history SELECT        compatible AccessShareLock
```

The observer must show `Lock:relation`, identify the blocking backend, and
complete a 25,000-row read. Returning to terminal A rolls back the transaction,
removes the ordinary index, and drains the writer.

### 3.2 Safe phase

The safe phase reverses the relationship:

```text
existing writer             granted RowExclusiveLock
CREATE INDEX CONCURRENTLY   granted ShareUpdateExclusiveLock
fresh UPDATE                completes
```

The concurrent build may wait on an older transaction's virtual transaction.
That is expected. The learning objective is directional: ordinary DML is not
queued behind the concurrent build's relation lock.

### 3.3 Realism boundary

Every statement, lock mode, wait event, PID, relation OID, and catalog row is
measured from the connected engine. The held transaction is a deterministic
observation technique. The workshop makes no claim about production index-build
duration, write throughput, or the performance of an Aurora instance class.

The generated lock capture may be admitted through `admission/admit.sh` after
the core workshop. Admission queues search projection; it does not synchronously
embed the item or gate the canonical answer.

---

## 4. Lab 2 - Build hybrid retrieval

Lab 2 teaches one query shape per retrieval mechanism:

| Query shape | Mechanism | Required checkpoint |
|---|---|---|
| named change or incident | boundary-aware exact identifier | `CHG-1842` is rank 1 in tier 1 |
| SQL and lock vocabulary without an ID | PostgreSQL full-text search | dedicated FTS ranks `CHG-1842` first |
| semantic symptoms | pgvector cosine distance over the matching model space | the UI explains why the top evidence matches the question |
| controlled typo | indexed `pg_trgm` `%` search | `CGH-1842` resolves uniquely to `CHG-1842` |
| cluster, incident, kind, or time scope | typed SQL and metadata filters | the participant edit removes the staging distractor before fusion |
| mixed query | weighted RRF over arm rank positions | the participant changes weights, completes the RRF SQL expression, and every score recomputes |
| post-fusion ordering | Cohere Rerank v3.5 when available | rerank score is separate and `rerank_applied=false` preserves Aurora order on failure |

The default RRF weights are text `2`, vector `1`, and fuzzy `1`, with `k=60`.
An absent arm contributes zero. Exact boundary matches remain deterministic and
cannot be demoted by changing fusion weights.

One plan inspection reports the index PostgreSQL actually selected for the
semantic arm. The fuzzy plan reports abstention when no unresolved identifier
exists. Filtered-HNSW iterative-scan comparison and deeper trigram plan
contrasts remain in the diagnostics appendix.

---

## 5. Lab 3 - Build the incident agent

The participant first decomposes the canonical question, fills the incident
seed in a traversal request, discovers the competing change, and fills the
three-source comparison request. The agent then receives the same question and
must:

1. decompose it into change cause, incident mechanism, visible customer impact,
   safe remediation, and citation requirements;
2. retrieve targeted evidence with typed filters;
3. traverse declared, foreign-key-derived relationships;
4. compare confirmed evidence with ruled-out and superseded evidence;
5. explain the ranking signals without converting them into probabilities; and
6. synthesize only from numbered evidence.

The relationship question, "which visible customer was affected?", is not
solved by vector similarity. It requires traversal over canonical casework
relationships after retrieval has found the incident thread.

The complete answer must identify `CHG-1842`, the `ShareLock` versus
`RowExclusiveLock` mechanism during `INC-2047`, the visible customer supported
by case evidence, and the `CREATE INDEX CONCURRENTLY` remediation supported by
the current runbook revision.

When synthesis is unavailable, the extractive fallback must use the same
persisted evidence rows and say that the model step was not applied.

---

## 6. Lab 4 - Prove and replay

Required participant proof is:

- source URI, revision, chunk, and quote for each citation;
- citation validation status and its attribution-only meaning; and
- replay by `run_id` with zero model calls.

Candidate details, relationship graph, incident timeline, and compact evaluation
remain available after the required path. Evaluation reports retrieval metrics
separately from relationship-traversal metrics. A high retrieval score does not
prove that the agent found the customer relationship, and citation validity does
not prove a claim is semantically true.

The application navigation mirrors the teaching path:

```text
Overview -> Hybrid Retrieval -> Agentic Retrieval -> Proof
```

Corpus, Evaluation, and Health are supporting inspection surfaces rather than
separate workshop narratives.

---

## 7. Sixty-minute run of show

| Clock | Required activity | Participant proof | Cut line |
|---|---|---|---|
| 00:00-00:05 | Observe the write stall | connect successful reads, waiting writes, blocker relationship, and schema ownership | no product tour |
| 00:05-00:10 | Verify the environment | ready search index, matching model space, pending `0`, drift `0` | move blocked participants to a prevalidated terminal |
| 00:10-00:20 | Lab 1 | real unsafe wait chain and safe concurrent retry | use facilitator capture if orchestration runs long |
| 00:20-00:40 | Lab 2 | exact and FTS shapes, semantic, typo, filter edit, fusion edit and SQL, rerank, one plan | use a saved plan observation; `rerank_applied=false` is valid |
| 00:40-00:50 | Lab 3 | participant tool plan, traversal, comparison, bounded recovery, cited answer | use complete-answer endpoint if individual tool calls run long |
| 00:50-00:55 | Lab 4 | citation attribution and model-free replay | skip visual Proof exploration, preserve citation SQL and receipt GET |
| 00:55-01:00 | Close | completed exercise chain and one production boundary | run compact evaluation after the session |

Never cut dedicated FTS, the filter and fusion checkpoints, the cited answer,
or persisted replay.

Workshop Studio top-level pages must remain:

1. Observe the write stall.
2. Verify the environment.
3. Lab 1: Reproduce and observe the write stall.
4. Lab 2: Build hybrid retrieval.
5. Lab 3: Build the incident agent.
6. Lab 4: Prove and replay.
7. Summary.

Optional RLS/masking, AgentCore Gateway, troubleshooting, index operations,
deeper HNSW work, compact evaluation, and additional retrieval diagnostics
follow the core path.

---

## 8. Release gates

### 8.1 Core application gates

The default `gates/checks.sh` contract remains:

| Gate | Contract |
|---|---|
| G-11 | canonical noun lint |
| G-13 | visible API values match server-generated verify SQL |
| G-14 | schema-only database renders empty states and no fixture numerals are bundled |
| G-17 | tool registry and generated adapters have no drift |
| G-21 | `CGH-1842` fixture arithmetic remains unique on the target engine |
| G-23 | required guide deep links resolve to the intended application surface |
| G-25 | evidence admission is deterministic, even though it is not a core participant step |

The exact multi-session incident files must pass
`backend/tests/test_incident_lab.py` on disposable PostgreSQL and on the target
Aurora engine with the participant role.

### 8.2 Core end-to-end gates

- `make doctor` reports the search index ready, model space aligned, pending
  queue `0`, and drift `0`.
- Exact, fuzzy, semantic, filtered, hybrid, rerank fallback, answer, citation,
  graph, timeline, evaluation, and replay checks pass.
- The canonical answer has real source revisions and passes
  `proof.validate_answer_citations`.
- A frozen archive provisions a fresh Workshop Studio account without GitHub or
  an embedding call.
- The archive comment, dump revision, dump checksum, and approved application
  revision match.
- The full participant path completes in 60 minutes on `db.r8g.2xlarge`.

### 8.3 Optional gates

G-27, G-29, G-30, and G-31 validate the RLS and masking appendix. They do not
block the core release. If that appendix is published, every gate must report
`PASS`; `BLOCKED` is not evidence.

AgentCore Gateway publication requires an opt-in stack, successful tool
invocation, and receipt parity with the direct API for the same request.

### 8.4 Retired design gates

The following draft gates are deleted, not pending:

- **Former G-6:** 240-420 second ordinary index build on 25 million rows.
- **Former G-9:** nonzero pgbench read TPS throughout the incident.

No release criterion may depend on those unbuilt assets or timing windows.

---

## 9. Failure handling

| Failure | Continue with |
|---|---|
| Three-terminal orchestration runs long | facilitator's measured lock capture, then continue to retrieval |
| Bedrock query embedding is slow | packaged query-vector checkpoint |
| Cohere rerank is unavailable | Aurora RRF order with `rerank_applied=false` |
| Synthesis model is unavailable | extractive answer from the same persisted evidence |
| Frontend is unavailable | HTTP endpoints and SQL receipt views |
| One participant loses Aurora access | pair with a validated environment; do not switch the room to a different architecture |
| Gateway or optional security setup fails | omit the optional module; core remains complete |

Do not reseed a participant database during the room.

---

## 10. Optional modules

### 10.1 PostgreSQL RLS and masking

Repeat one restricted-evidence query:

1. App Engineer cannot retrieve or traverse the restricted case.
2. Auditor can retrieve it with customer identities masked.
3. DBA can retrieve it unmasked.

This appendix demonstrates database enforcement using the same retrieval
contract. Caller-selected persona remains a teaching fixture, not production
authentication. Production identity mapping and authorization revalidation are
explicitly separate concerns.

### 10.2 AgentCore Gateway

Publish the existing retrieval tools through the optional Gateway stack, invoke
the same incident request, and compare the persisted candidates and citations
with the direct API receipt. Gateway is a transport over the engine; it does not
own ranking or proof.

### 10.3 Evidence admission and operations

Participants may admit their generated lock capture, inspect projection queue
state, rebuild search projection, or explore HNSW operations after the core.
These are real engineering extensions, not required completion steps.

---

## 11. Deferred production-scale extension

The former design specified `shop.orders` at 25 million rows, companion customer
and product tables, three continuously running pgbench workloads, and a
single-worker ordinary index build calibrated to 240-420 seconds. None of those
assets ships in either repository.

They are intentionally deferred. The current lab already proves the learning
objective with real locks and wait chains while avoiding roughly 3 GB of extra
seed data, event-time calibration, background services, and an instance-class
dependent timing gate.

A future production-scale extension may add that substrate only when it has:

- checked-in DDL, deterministic seed, load scripts, service definitions, and
  cleanup;
- calibration on every supported instance class and engine version;
- measured acceptance ranges for build duration and workload rates;
- fresh-account bootstrap and teardown coverage; and
- a participant outcome that earns the additional time and cost.

Until then, 25-million-row, pgbench TPS, 3 GB working-set, and 240-420 second
claims must not appear as deployed facts.

Other out-of-scope items include connector implementation, production identity
architecture, live embedding generation, Gateway deployment in the core,
multi-region or failover testing, and extensive index tuning.

---

## 12. Freeze checklist

1. Freeze and test the application revision.
2. Produce the v2 dump from an explicitly disposable seeded database.
3. Build `hybrid-retrieval-source.zip` from the same revision.
4. Verify all nine Lab 1 SQL files, `admission/`, `gates/`, generated adapters,
   and the v2 dump are present.
5. Provision a fresh Workshop Studio account in `us-east-1`.
6. Rehearse the participant role on `db.r8g.2xlarge`.
7. Run the complete canonical question through Retrieval, Agent, and Proof.
8. Validate screenshots, routes, model IDs, quotas, IAM, cost, and cleanup.
9. Publish optional RLS/masking or Gateway modules only when their own gates
   pass.

Workshop Studio commits, pushes, and publication remain event-owner managed.

---

## 13. Open release items

1. Generate the real v2 dump from a seeded disposable database at the frozen
   application revision.
2. Build and upload the matching source archive.
3. Resolve the current live search-index drift before using that cluster as
   release evidence.
4. Complete the fresh-account target Aurora rehearsal.
5. Recheck Bedrock model identifiers, lifecycle, CRIS routing, quotas, and IAM
   immediately before content freeze.
