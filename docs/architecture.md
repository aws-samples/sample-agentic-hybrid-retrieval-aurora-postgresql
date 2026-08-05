# Architecture

## System Boundary

Hybrid Retrieval Workbench is an evidence system, not a general chatbot and not
a replacement for an incident-management, change-management, support, or
observability system.

```text
Participant-induced Aurora write stall
PostgreSQL catalogs + CloudWatch + Performance Insights
                  |
                  | one capture ID + bounded run window
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

Inside the workshop, `casework.*` contains only measurements from the
participant's current run. Provisioning starts with zero evidence. No fixture,
dump, authored record, or earlier capture enters the participant path. In
production, equivalent inputs can come from approved domain tables, views,
events, or connectors; the original systems still own workflow, current
permissions, mutable state, and actions.

## Controlled Incident Substrate

`workbench_lab.*` is a disposable operational workload used only to reproduce
the PostgreSQL locking mechanism before retrieval begins. Workshop bootstrap
generates 5,000 customers and 3,000,000 related orders while the evidence store
remains empty. It is deliberately outside all three application ownership
schemas:

```text
Bootstrap: 5,000 customers + 3,000,000 orders, zero evidence
                         |
                         v
One guided participant orchestrator
  ordinary CREATE INDEX | six writers | two readers | 30 samples
                         |
                         v
 workbench_lab customers/orders + PostgreSQL lock catalogs
                         |
          PostgreSQL and AWS measurements
                         |
                         v
       atomic casework.admit_evidence bundle
                         |
                         v
      deterministic searchable evidence build
                         |
                         v
       runtime Cohere embedding build
```

The ordinary phase holds the real `CREATE INDEX` transaction open after the
build so its granted `ShareLock` remains observable. The observer proves that
`AccessShareLock` reads continue, a writer's `RowExclusiveLock` request waits,
and `pg_blocking_pids()` names the index backend.

The safe phase starts `CREATE INDEX CONCURRENTLY` behind an already-open writer.
The build holds `ShareUpdateExclusiveLock` and may wait on the older virtual
transaction, while another `UPDATE` completes. The final check requires the
index to be ready, valid, and live.

The orchestrator verifies and reuses the preloaded rows. The unsafe samples,
repair, statement deltas, CloudWatch metrics, and Performance Insights
observations are all required. Admission atomically
writes `INC-<run-suffix>`, measured changes `CHG-<run-suffix>-01/02`, primary
lock evidence `LOCK-<run-suffix>-01`, and `TEL-<run-suffix>-...` telemetry
documents. The orchestrator indexes only source system
`pg_incident_capture`, generates runtime Cohere embeddings, and publishes a
receipt only when 100-120 documents are current and ready.

The participant frontend and agent requests always carry
`source_systems=["pg_incident_capture"]` and derive identifiers from that
receipt. The Overview main graphic is illustrative and never enters retrieval.

## Participant Mode

The workshop path is live incident retrieval through cited synthesis,
diagnostics, and replay. `make schema` applies the core schema and the API uses
the participant database directly. The corpus contains no authored restricted
records: every restricted row a persona can compare against is produced by
that participant's own `make live-workshop` capture, never a fictional one.

An event owner may additionally run `make security-schema` to enable the
optional RLS and column-masking lab (`sql/11_roles_rls.sql`,
`sql/12_masking.sql`) against that same live capture. It adds real
role-based visibility comparison on top of the required path; it does not
replace the fixed workshop visibility predicate the required path always
uses. See `docs/builder-session-flow.md` for when it is offered.

## Three Ownership Layers

### 1. `casework`: relational truth

`casework.evidence_items` supplies stable evidence identity, source provenance,
ACL metadata, and tombstone state. Typed tables hold the domain facts:

- participant-induced capture runs and Aurora PostgreSQL identity
- measured incidents, changes, and executed SQL
- raw PostgreSQL, CloudWatch, and Performance Insights rows
- controlled lock evidence and searchable telemetry documents

Foreign keys express incident-to-change, lock-to-change, lock-to-incident, and
telemetry-to-incident relationships. These relations are authoritative in the
workshop model.

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
  used?
- Which candidates entered the final result and from which retrieval arms?
- What were the lexical, vector, fuzzy, RRF, and optional rerank signals?
- Which source revision and chunk supports each cited claim?
- Can the citation quote still be validated against that exact chunk version?

## Retrieval Path

All retrieval arms apply source-system and metadata filters plus an ACL
predicate before candidates enter fusion:
`retrieval.acl_visible(document.acl)` where the arm reads the JSONB,
`retrieval.acl_scalars_visible(acl_visibility)` where it reads the derived
column. Both expose the fixed workshop-visible scope and do not require
database roles.

1. **Exact and full text:** boundary-aware identifier matching plus separate
   document and chunk `tsvector` streams.
2. **Semantic:** cosine distance over 1,024-dimensional Cohere embeddings with
   HNSW runtime controls.
3. **Fuzzy:** `pg_trgm` similarity over external identifiers and titles.
4. **Fusion:** weighted RRF over independent arm positions. A boundary-matched
   exact identifier receives a separate lexical vote using the text weight. Raw
   arm scores are retained for diagnostics and are not added to the fused score.
5. **Rerank:** Cohere Rerank v3.5 can reorder the fused candidate pool. The
   PostgreSQL RRF score and model rerank score remain separate.

The default RRF weights are lexical `2`, semantic `1`, fuzzy `1`, with
`k=60`. These are workshop defaults and evaluation inputs, not universal
constants.

## Relationship Path

`retrieval.evidence_edges` renders canonical foreign-key relationships as a
uniform read surface and unions separately governed inferred edges. Canonical
edges have confidence `1` and retain their relational rationale. Inferred edges
retain method, confidence, and source revision.

Recursive traversal enforces the fixed workshop-visible scope at the seed and
at every hop. It never turns an inferred relation into a foreign-key fact.

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
did. Its tool calls write the same retrieval and answer receipts, but the
model-loop trace itself remains runtime state rather than a first-class
replayable agent-run record.

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
