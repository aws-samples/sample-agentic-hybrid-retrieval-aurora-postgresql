# Architecture

## System Boundary

Hybrid Retrieval Workbench is an evidence system, not a general chatbot and not
a replacement for an incident-management, change-management, support, or
observability system.

```text
Operational systems or normalized domain tables
                  |
                  | stable ID, source URI, revision, ACL
                  v
       casework.* authoritative records
                  |
                  | deterministic render + content hash
                  v
       retrieval.* physical search index
 documents -> chunks -> FTS / HNSW / trigram indexes
                  |
                  | filtered candidates and rank positions
                  v
       retrieval.* canonical SQL ranking
                  |
          +-------+-------+
          |               |
          v               v
 proof.* receipts     inspectable agent tools
          |               |
          +-------+-------+
                  v
      cited answer through HTTP or MCP
```

Inside the workshop, `casework.*` is a controlled synthetic source-of-record
fixture. In production, the equivalent input can be approved domain tables,
views, exports, events, or connector output. The original systems still own
workflow, current permissions, mutable state, and actions.

## Controlled Incident Substrate

`workbench_lab.*` is a disposable operational workload used only to reproduce
the PostgreSQL locking mechanism before retrieval begins. It is deliberately
outside all three application ownership schemas:

```text
Three participant psql sessions
  ordinary CREATE INDEX | reader and writer | catalog observer
                         |
                         v
        workbench_lab.orders + PostgreSQL lock catalogs
                         |
               measured JSON snapshot
                         |
                         v
          optional casework.admit_evidence
```

The ordinary phase holds the real `CREATE INDEX` transaction open after the
build so its granted `ShareLock` remains observable. The observer proves that
`AccessShareLock` reads continue, a writer's `RowExclusiveLock` request waits,
and `pg_blocking_pids()` names the index backend.

The safe phase starts `CREATE INDEX CONCURRENTLY` behind an already-open writer.
The build holds `ShareUpdateExclusiveLock` and may wait on the older virtual
transaction, while another `UPDATE` completes. The final check requires the
index to be ready, valid, and live.

The measured snapshot can enter `casework` through the admission contract, but
admission only queues retrieval projection. It does not synchronously generate
an embedding or make the new row searchable. The preloaded `INC-2047` corpus
remains the deterministic retrieval and evaluation fixture.

## Core and Optional Security Modes

The core workshop path is incident hybrid retrieval through cited synthesis,
diagnostics, and replay. `make schema` applies `sql/00` through `sql/10`;
`WORKBENCH_SECURITY_ENABLED` defaults off; and the API uses `DATABASE_URL`
without assuming a PostgreSQL persona role. Core release validation therefore
does not require RLS or `pg_columnmask`.

The optional security appendix applies `sql/11_roles_rls.sql` and
`sql/12_masking.sql`, enables `WORKBENCH_SECURITY_ENABLED=1`, and requires a
non-owner `WORKSHOP_APP_DATABASE_URL`. It adds transaction-scoped persona roles,
forced RLS, and Auditor masking without changing the owning retrieval or proof
contracts. These controls are appendix validation, not default release gates.

## Three Ownership Layers

### 1. `casework`: relational truth

`casework.evidence_items` supplies stable evidence identity, source provenance,
ACL metadata, and tombstone state. Typed tables hold the domain facts:

- incidents and Aurora PostgreSQL clusters
- changes and executed SQL
- support cases and customer commitments
- runbooks and version applicability
- controlled lock evidence

Join tables express incident-to-change, incident-to-case, and
incident-to-runbook relationships with foreign keys. Lock evidence references
its incident directly. These relations are authoritative in the workshop
model.

### 2. `retrieval`: derived search state

`casework.v_evidence_documents` deterministically renders relational rows into
searchable documents. `backend/app/search_index.py` versions those documents,
chunks them, resolves embeddings by model and content hash, and promotes only
ready versions to the current search surface.

This layer uses physical base tables instead of a materialized view because:

- embeddings are computed outside PostgreSQL and cached by content hash;
- document and chunk versions must remain addressable by historical proof;
- individual changes need idempotent replacement and tombstone handling;
- HNSW, GIN, and B-tree indexes operate over a stable physical search surface.

A regular materialized-view refresh would also introduce a blocking refresh
operation. A concurrent refresh changes that locking tradeoff but does not
solve external embedding generation, revision history, or freshness control.

The search index is not a second source of truth. It is one-way derived,
rebuildable, and checked through `retrieval.v_search_index_drift` and
`retrieval.assert_search_index_ready()`.

### 3. `proof`: answer evidence

Each request creates `proof.retrieval_runs` before retrieval. Candidate-level
positions and scores are stored in `proof.retrieval_candidates`; stage timings
are stored separately. Synthesis persists the answer and exact citations.

The proof layer answers:

- Which query, filters, workshop context, model space, and ANN controls were
  used, including persona when the optional appendix is enabled?
- Which candidates entered the final result and from which retrieval arms?
- What were the lexical, vector, fuzzy, RRF, and optional rerank signals?
- Which source revision and chunk supports each cited claim?
- Can the citation quote still be validated against that exact chunk version?

## Retrieval Path

All retrieval arms apply metadata filters and an ACL predicate before candidates
enter fusion: `retrieval.acl_visible(document.acl)` where the arm reads the JSONB,
`retrieval.acl_scalars_visible(acl_visibility)` where it reads the projected
column. In core mode both expose the fixed workshop-visible scope and do not
require database roles. The optional security appendix replaces the same
function signatures with persona-aware predicates and adds RLS as a backstop if
an arm omits the predicate.

1. **Exact and full text:** boundary-aware identifier matching plus separate
   document and chunk `tsvector` streams.
2. **Semantic:** cosine distance over 1,024-dimensional Cohere embeddings with
   HNSW runtime controls.
3. **Fuzzy:** `pg_trgm` similarity over external identifiers and titles.
4. **Fusion:** weighted RRF over independent arm positions. A boundary-matched
   exact identifier receives a separate lexical vote using the text weight. Raw
   arm scores are retained for diagnostics and are not added to the fused score.
5. **Rerank:** Cohere Rerank v3.5 can reorder the fused candidate pool. The
   Aurora RRF score and model rerank score remain separate.

The default RRF weights are lexical `2`, semantic `1`, fuzzy `1`, with
`k=60`. These are workshop defaults and evaluation inputs, not universal
constants.

## Relationship Path

`retrieval.evidence_edges` renders canonical foreign-key relationships as a
uniform read surface and unions separately governed inferred edges. Canonical
edges have confidence `1` and retain their relational rationale. Inferred edges
retain method, confidence, and source revision.

Recursive traversal enforces ACLs at the seed and at every hop. It never turns
an inferred relation into a foreign-key fact.

In core mode that means the fixed workshop-visible scope at every hop. In the
optional appendix, the same hop checks run under the assumed PostgreSQL persona.

## Agent Boundary

The agent path answers in this order:

1. `decompose_question`
2. `search_evidence`, once per subquestion plus bounded retries
3. `follow_evidence_links`
4. `compare_sources`
5. `synthesize_cited_answer`

`explain_ranking` is the sixth model-selectable tool and is not part of
answering. It
re-reads a persisted receipt without calling a model, so the deterministic
pipeline never calls it and the Strands system prompt does not sequence it; the
Proof surface reads the same receipt through `GET /v1/runs/{run_id}`.

Two harnesses run that contract. `backend/app/agent.py` fixes the order, because
evaluation and replay both need the same input to produce the same output.
`backend/app/strands_agent.py` gives the model all six tools and lets it choose,
because "the agent decided to traverse relationships here" is only true if it
did. Both write the same `proof.*` receipts.

The boundary is harness-neutral. FastAPI, the Lambda adapter, and the stdio MCP
server call the same Python implementations. None reimplements ranking.

The managed AgentCore Gateway is a stateless transport boundary owned by the
Workshop Studio environment. It does not own retrieval, model orchestration, or
proof persistence.

## Model Boundary

- Cohere Embed 4 creates document and query vectors in one 1,024-dimensional
  space.
- Cohere Rerank v3.5 is an optional post-fusion ordering stage.
- Claude Sonnet synthesizes only from numbered evidence and must cite each
  factual sentence.

The validated synthesis path uses Bedrock Converse with a Global CRIS profile.
Mantle is not claimed on that path. Every model ID is configurable, and preflight
must be rerun before the event because model lifecycle and regional support can
change.

## Evidence Placement

One answer can use three paths:

| Path | Use it when | Required proof |
|---|---|---|
| Materialize | Approved evidence must be ranked, joined, cited, evaluated, and replayed at low latency. | Stable source ID, URI, revision, content hash, ACL, and retrieval receipt |
| Federate | A capable external index already exists or content should not be copied. | External query, result references, response revision or timestamp |
| Revalidate live | State is volatile, authorization is current-user-specific, or an action will follow. | Authoritative lookup or action receipt |

The workshop core implements the materialized path. Federation and mutation are
production boundaries, not simulated workshop features.

## Infrastructure Boundary

This repository contains application source only. The sibling Workshop Studio
repository owns CloudFormation, Aurora PostgreSQL, VPC networking, IAM, Code
Editor, AgentCore Gateway, Lambda deployment, and the packaged source archive.

Local PostgreSQL validation proves PostgreSQL semantics. Final release
validation must also run against the target Aurora PostgreSQL engine and
Workshop Studio network path.

The default release validates the core path. Publishing the optional security
appendix additionally requires Aurora support for `pg_columnmask` and passing
security gates; a skipped mask migration or a `BLOCKED` gate is not a pass.
