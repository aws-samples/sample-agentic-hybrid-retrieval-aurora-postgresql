# DAT410 Implementation Specification

## Status

Hybrid Retrieval Workbench is the implemented DAT410 reference application for
AWS re:Invent 2026.

- Session: Build agentic hybrid retrieval with Amazon Aurora PostgreSQL
- Level: 400
- Format: Builders' session
- Duration: 60 minutes
- Participant corpus: live-only
- Packaging: schema-only source archive

Application source, SQL, tests, and API responses are authoritative. The
standing rule is that no fictional, offline, demo, authored, or previously
captured record may enter the participant path. The Overview page's main
graphic is the only illustrative exception and is never persisted or queried.

## 1. Participant Outcome

One command induces and indexes the participant's own incident:

```bash
make live-workshop
```

The resulting indexing receipt supplies:

```text
CAP-<run-suffix>
INC-<run-suffix>
CHG-<run-suffix>-01
CHG-<run-suffix>-02
LOCK-<run-suffix>-01
TEL-<run-suffix>-...
```

The participant investigates:

> What caused `INC-<run-suffix>`, how did `CHG-<run-suffix>-01` block writes,
> how did `CHG-<run-suffix>-02` repair the behavior, and what did
> `LOCK-<run-suffix>-01` prove?

The answer must be grounded in measured PostgreSQL and AWS telemetry from that
capture. No customer, support, company, person, runbook, postmortem, or
distractor record exists in the participant database.

## 2. Ownership

| Schema or surface | Owns |
|---|---|
| `workbench_lab` | Disposable orders table and index used to induce the incident |
| `casework` | Live evidence identity, raw telemetry, typed facts, and canonical relationships |
| `retrieval` | Rebuildable document versions, chunks, embeddings, indexes, ranking, and traversal |
| `proof` | Retrieval runs, candidate signals, stages, answers, citations, evaluation, and replay |
| Backend | API orchestration, model adapters, tools, synthesis, and readiness |
| Frontend | Inspection UI over API and persisted proof |

Operational systems remain authoritative for mutable workflow, current
permissions, and actions. The workshop materializes only its measured incident
evidence into Aurora PostgreSQL.

## 3. Live Incident

Workshop Studio bootstrap runs `make prepare-workload` after `make schema`.
That step generates 5,000 rows in `workbench_lab.customers` and 25,000
foreign-key-related rows in `workbench_lab.orders`, requires an empty evidence
store, and creates no `casework`, `retrieval`, or `proof` records.

`labs/incident/run_live_workshop.py` is the only participant incident producer.
Before inducing the incident, it proves:

- the target is the requested Aurora PostgreSQL writer;
- PostgreSQL and pgvector satisfy the repository minimums;
- the core schema is complete;
- the participant corpus is empty;
- the operational workload contains exactly 5,000 customers and 25,000
  canonical related orders with no target incident index;
- Performance Insights is enabled;
- CloudWatch and Performance Insights are reachable;
- Cohere Embed is available through Bedrock; and
- the embedding provider is `bedrock`.

The orchestrator requires the bootstrapped workload. Source-only local use runs
`make prepare-workload` explicitly before `make live-workshop`.

The unsafe phase:

- uses the 5,000 preloaded customers and 25,000 related orders;
- starts ordinary `CREATE INDEX`;
- keeps its transaction open after index construction;
- starts six real blocked writers and two readers;
- takes 30 samples at two-second intervals; and
- proves granted `ShareLock`, waiting `RowExclusiveLock`,
  `pg_blocking_pids()`, and `Lock:relation`.

The repair phase:

- rolls back the ordinary index transaction;
- applies `CREATE INDEX CONCURRENTLY`;
- proves a fresh `UPDATE` completes;
- captures the safe lock state; and
- requires the final index to be ready, valid, and live.

AWS collection filters every CloudWatch and Performance Insights observation
to the capture window and the validated Aurora writer. The PI evidence must
contain both `Lock:relation` and the ordinary `CREATE INDEX` SQL.

## 4. Authoritative Data

### Capture tables

| Relation | Purpose |
|---|---|
| `incident_capture_runs` | One participant-induced run, bounded window, target identity, and manifest |
| `pg_stat_activity_samples` | Activity rows with observation number and raw row |
| `pg_lock_samples` | Relation-lock rows with observation number and raw row |
| `pg_blocking_pids_samples` | Blocking chains and literal SQL output |
| `pg_stat_statements_samples` | Before, during, and after statement measurements |
| `cloudwatch_metric_samples` | Five incident-window RDS metric observations |
| `database_insights_samples` | PI top wait and SQL observations |

### Searchable evidence

| Kind | Purpose |
|---|---|
| `incident` | Measured write stall and resolution interval |
| `change` | Unsafe ordinary index build and measured concurrent repair |
| `lock_evidence` | Primary observed lock chain |
| `telemetry` | Searchable evidence built deterministically from measured telemetry |

The searchable evidence build creates 30 activity-window, 30 lock-topology, and 30
blocking-chain documents plus measured statement, metric, PI, and remediation
documents. A successful run contains about 110 searchable documents and
100-250 chunks while retaining about 735 raw telemetry rows.

`casework.v_evidence_documents` renders normalized facts deterministically. It
emits stable evidence identity, source URI, source revision, ACL, typed filters,
metadata, content, and a SHA-256 search-document hash.

## 5. Admission

`casework.admit_evidence(jsonb)` is the atomic write boundary. It requires:

- source system `pg_incident_capture`;
- Aurora PostgreSQL database identity;
- one UUID capture ID and matching eight-character run suffix;
- exact run-derived key forms;
- 30 observations, six writers, and two readers;
- at least 270 activity, 270 lock, and 180 blocking rows;
- all three statement phases;
- all five CloudWatch metric records;
- Performance Insights `Lock:relation`;
- 100-120 searchable telemetry documents;
- source URIs under the run bundle URI; and
- one capture origin, `participant_induced`.

Admission writes evidence, typed rows, telemetry, relationships, and search
queue entries in one transaction. Any validation failure rolls back the entire
run. An identical payload is idempotent; a mixed or changed payload is rejected.

## 6. Search Index

The search index version combines:

- renderer version;
- chunker version;
- embedding model ID; and
- search-document hash.

`backend/app/search_index.py`:

1. reads only queued authoritative rows;
2. renders and chunks them;
3. batches Cohere Embed calls through Bedrock with `search_document`;
4. writes ready chunks and vectors;
5. promotes one current ready document version;
6. supersedes the prior version when content changes; and
7. records a build receipt.

Query embeddings use `search_query`. Stored and query vectors must share the
same model ID and 1,024 dimensions. Participant indexing does not permit hash
embeddings or a prebuilt cache.

`retrieval.assert_search_index_ready()` returns `awaiting_incident` for an empty,
drift-free schema. After admission it requires:

- source document count equals current document count;
- every current chunk has a ready embedding;
- one embedding space;
- zero queue or document drift; and
- a live capture receipt.

Search and agent endpoints return HTTP 409 until these checks pass.

## 7. Retrieval

Canonical ranking stays in `sql/03_search_functions.sql`.

1. Boundary-aware exact identifiers form a deterministic first tier.
2. PostgreSQL full-text search ranks document and chunk text.
3. pgvector cosine search ranks semantic evidence.
4. `pg_trgm` ranks identifier and title near matches.
5. Weighted reciprocal rank fusion combines active arm positions.
6. Cohere Rerank may reorder the fused candidate pool.

Default RRF controls are text `2`, semantic `1`, fuzzy `1`, and `k=60`.
PostgreSQL RRF is plain PostgreSQL SQL, not an Aurora-specific algorithm.
Raw arm scores, arm positions, RRF, and model rerank scores remain distinct and
none is a confidence probability.

Every participant request applies `source_systems=["pg_incident_capture"]`
inside each arm. Exercises also verify that every candidate key matches the
current indexing receipt.

## 8. Relationships

Canonical relationships are rendered from foreign keys:

```text
INC-<run-suffix> -> CHG-<run-suffix>-01  change_confirmed
INC-<run-suffix> -> CHG-<run-suffix>-02  change_remediated
LOCK-<run-suffix>-01 -> CHG-<run-suffix>-01  blocked_by_change
LOCK-<run-suffix>-01 -> INC-<run-suffix>  observed_during
TEL-<run-suffix>-... -> INC-<run-suffix>  observed_during
```

`retrieval.evidence_edges` is the uniform read view. Traversal checks visibility
at the seed and every hop. The frontend and agent never infer canonical
relationships from prose.

## 9. Agent And Synthesis

The deterministic answer path:

1. decomposes the question;
2. searches each bounded subquestion;
3. traverses declared relationships;
4. compares the measured unsafe and repair records;
5. reloads persisted candidates; and
6. synthesizes a cited answer.

The Strands path exposes the same tool implementations to model-directed
selection. Both paths persist the same retrieval and citation contracts.

The six model-selectable tools are `decompose_question`, `search_evidence`,
`follow_evidence_links`, `compare_sources`, `explain_ranking`, and
`synthesize_cited_answer`. Managed transports call the same Python owners.

Synthesis uses only numbered, persisted evidence. If the synthesis model is
unavailable, the extractive fallback uses the same run evidence and does not
invent a record or citation.

## 10. Proof

`proof.retrieval_runs` is created before retrieval. Candidate rows preserve:

- exact tier and final rank;
- full-text, semantic, and fuzzy raw scores;
- independent arm positions;
- PostgreSQL RRF;
- optional Cohere rerank score;
- document and chunk versions; and
- source URI and revision.

`proof.validate_answer_citations(run_id)` verifies that each citation references
the exact persisted document and chunk, that URI and revision match, and that
the quoted span exists in the chunk.

`GET /v1/runs/{run_id}` returns candidates, stages, answer, citations,
relationship graph, and timeline from persisted proof without another model
call.

## 11. Public API

```text
GET  /ready
GET  /v1/workshop/run
POST /v1/search
POST /v1/agent/answer
POST /v1/agent/strands/answer
POST /v1/tools/decompose
POST /v1/tools/traverse
POST /v1/tools/compare
POST /v1/tools/explain-ranking
POST /v1/tools/synthesize
GET  /v1/runs/{run_id}
GET  /v1/evidence/{evidence_id}
POST /v1/evaluation
```

The read APIs consume the ready search index. They do not mutate authoritative
casework.

## 12. Packaging

`scripts/build_live_source_archive.sh` packages one committed source revision.
It rejects:

- dirty runtime source;
- missing live-workshop files;
- a dump or database file;
- generated capture JSON;
- an embedding cache or manifest;
- generated indexing receipts; and
- legacy seed or admission entrypoints.

The participant stack applies schema, generates the disposable operational
workload, and starts with zero evidence. It never restores casework, retrieval,
proof, telemetry, or vectors.

## 13. Acceptance

### Live provenance

- A fresh Aurora run completes all eight checkpoints.
- Every participant-facing source row belongs to one capture ID.
- Every source URI is under that capture's bundle URI.
- PostgreSQL and AWS rows fall within the bounded incident run.
- The database contains zero foreign participant records.

### Scale and indexing

- 100-120 source documents.
- 100-250 chunks.
- 600-1,000 raw telemetry rows.
- Runtime Cohere embeddings for every current chunk.
- Zero cache hits on the fresh validation run.
- One embedding space and zero drift.

### Retrieval and proof

- Exact, dedicated FTS, semantic, fuzzy, filter, and fusion checks pass.
- `CGH-<run-suffix>-01` retrieves `CHG-<run-suffix>-01`.
- RRF and rerank remain separate.
- Agent answer cites only current-run evidence.
- Citation validation and SQL replay pass.
- Graph and timeline values reproduce from published verification SQL.

### Delivery

- The one-hour path uses one guided incident command.
- The archive contains no participant data.
- The app is usable on desktop and mobile.
- No HNSW performance claim is made from workshop-scale data.
- Workshop Studio content matches the committed source behavior.

## 14. Validated Reference Run

The August 2, 2026 fresh Aurora validation used capture
`6949b1ef-03b7-41e7-8def-3518478fd535`, suffix `478FD535`, on Aurora PostgreSQL
18.3. It produced:

- 110 searchable documents and chunks;
- 110 runtime Cohere embeddings with zero cache hits;
- 270 activity rows;
- 270 lock rows;
- 180 blocking rows;
- 3 statement rows;
- 5 CloudWatch rows;
- 7 Performance Insights rows;
- 8 citations in Bedrock synthesis; and
- 216 graph edges and 110 timeline events reproduced through the replay gate.

This identifier is validation evidence only. It must never be compiled into the
participant application, guide defaults, tests, or source archive.
