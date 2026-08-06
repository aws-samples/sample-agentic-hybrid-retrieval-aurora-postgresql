# DAT410 Implementation Specification

## Status

Hybrid Retrieval Workbench is the DAT410 source application for AWS re:Invent
2026. The active scenario is a four-phase Aurora PostgreSQL online-migration
failure with two additive evidence admissions.

- Session: Build agentic hybrid retrieval with Amazon Aurora PostgreSQL
- Level: 400
- Format: 60-minute builders' session
- Participant corpus: live-only and capture-derived
- Packaging: committed application source only, with no database state

The governing rule is that no fictional, offline, demo, authored, or previously
captured record may enter the participant retrieval, agent, citation,
evaluation, or proof path. The Overview graphic is the sole illustrative
exception and is never persisted or queried.

## 1. Participant Outcome

Participants begin with a pre-provisioned operational workload and an empty
evidence store. They run:

```bash
make live-workshop
```

Investigation Evidence captures the diagnosis of one migration:

```text
nullable priority_tier column
  -> unbatched 3,000,000-row backfill
  -> lock collision with ten pooled API writers
  -> two additional requests queue and timeout at the pool boundary
  -> commit and measured recovery
  -> sequential query plans before and after ANALYZE
  -> normalized evidence, runtime embeddings, and an Investigation Evidence receipt
```

The participant investigates:

> Why did order writes time out during the priority-tier migration, why did the
> application recover after commit, and why did the priority query remain slow?

The Hybrid Retrieval Agent answers from Investigation Evidence only and persists a structured,
cited index proposal. A human reviews the proposal and runs its rendered DDL.
Validation Evidence then captures only the observed post-index validation result:

```bash
make live-workshop ARGS="--wave B --proposal-id <uuid> --approved-by <name-or-role>"
```

Validation Evidence remains additive. It never replaces the diagnostic evidence that
grounded the proposal.

## 2. Ownership

| Schema or surface | Owns |
|---|---|
| `workbench_lab` | Disposable customers and orders used to induce the migration |
| `evidence` | Live evidence identity, raw telemetry, typed facts, and canonical relationships |
| `retrieval` | Rebuildable document versions, chunks, embeddings, indexes, ranking, and traversal |
| `proof` | Retrieval runs, candidate signals, citations, action proposals, executions, verdicts, and replay |
| Backend | API orchestration, model adapters, lab routes, tools, synthesis, and readiness |
| Frontend | Inspection UI over API responses and persisted proof |

Operational systems remain authoritative for mutable workflow, current
authorization, and actions. Aurora PostgreSQL owns only the measured evidence
and its retrieval/proof model.

## 3. Operational Substrate and Live Incident

Workshop Studio bootstrap runs `make prepare-workload` after `make schema`.
That step creates exactly 5,000 `workbench_lab.customers` rows and 3,000,000
related `workbench_lab.orders` rows. It requires zero evidence and creates no
`evidence`, `retrieval`, or `proof` records.

`labs/incident/run_live_workshop.py` is the only participant incident
producer. Investigation Evidence requires:

- a requested Aurora PostgreSQL 18.3 writer in `us-east-1`;
- current core schema and empty evidence store;
- the canonical preloaded workload with no `priority_tier` column or target
  composite index;
- the real API with `LAB_ENDPOINTS_ENABLED=1` and
  `DB_POOL_MIN_SIZE=DB_POOL_MAX_SIZE=10`;
- Cohere Embed through Bedrock; and
- a Bedrock embedding provider.

CloudWatch is best-effort supplemental evidence. A failed metric request is
recorded as `cloudwatch_status=unavailable`; it does not invalidate the
PostgreSQL and application-pool proof.

### 3.1 Investigation Evidence

1. `ALTER TABLE ... ADD COLUMN priority_tier int` commits by itself, releasing
   the DDL lock before the migration workload starts.
2. One explicit transaction updates all orders and remains open after the
   update. The backfill PID is retained.
3. Twelve writes use `POST /v1/lab/hot-write` through the production
   application pool. Each successful checkout keeps its tag, statement timeout,
   and `UPDATE` in one explicit transaction.
4. The controller polls every 250ms and requires three consecutive samples
   showing a ten-slot exhausted pool, zero available connections, at least two
   waiting callers, and ten tagged sessions waiting on transaction-ID locks
   blocked by the backfill PID.
5. The controller retains that proven state for a bounded observation hold,
   commits the backfill, and verifies recovery: no blocker, available pool, no
   waiters, no tagged lock waits, at least one recorded pool timeout, ten
   drained writers, and a fresh committed write.
6. The plan checkpoint captures `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` for
   the reference priority query before and after `ANALYZE`. Both must be
   sequential scans; the incident runner never creates or drops an index.

### 3.2 Validation Evidence

Validation Evidence requires one valid Investigation Evidence incident and one explicit participant approval
of its stored proposal. It reads the actual index definition from the Aurora
catalog, records an append-only execution receipt, and compares its canonical
fingerprint with the proposal. A mismatch remains visible as proof and does not
silently update the proposal.

For a matching index, Validation Evidence captures the post-index plan, admits only new
metadata and plan evidence, rebuilds the search index, and attaches the
receipt to the recorded execution. The participant DDL is rendered by code from
validated proposal fields:

```sql
CREATE INDEX idx_orders_priority_tier_created_at
ON workbench_lab.orders (priority_tier, created_at DESC);
```

The agent neither runs this statement nor has a write-capable tool.

## 4. Authoritative Data

### Capture tables

| Relation | Purpose |
|---|---|
| `incident_capture_runs` | Bounded participant capture identity, wave, target, and manifest |
| `pg_stat_activity_samples` | Activity observations including tagged waiters and blocker PID |
| `pg_lock_samples` | Lock observations, including transaction-ID locks |
| `pg_blocking_pids_samples` | Blocking chains and literal function output |
| `pg_stat_statements_samples` | Statement work before, during, and after the migration |
| `cloudwatch_metric_samples` | Supplemental incident-window RDS metric observations |

### Searchable evidence

| Kind | Investigation Evidence purpose | Validation Evidence purpose |
|---|---|---|
| `incident` | One measured migration failure | None; references the existing incident |
| `change` | Backfill and `ANALYZE` comparison | Participant-approved index validation |
| `lock_evidence` | Primary transaction-ID blocker chain | None |
| `telemetry` | Distinct `lock`, `pool`, `request`, `wal`, `meta`, and `plan` records | New `meta` and `plan` validation records |

`labs/incident/evidence_builder.py` creates documents from meaningful
transitions, outcome classes, lifecycle facts, and plan checkpoints. It never
turns every raw polling tick into a template document. A run is adequate when
it satisfies the signal- and phase-coverage gate and stays below the
near-duplicate threshold; the expected 50-80 document range is guidance, not
an acceptance gate.

Every authoritative record is source-revisioned and rendered through
`evidence.v_evidence_documents` with stable identity, source URI, ACL,
metadata, content, and SHA-256 search-document hash.

## 5. Admission

`evidence.admit_evidence(jsonb)` is the atomic write boundary for either
capture.
It requires:

- `source.system = pg_incident_capture`;
- Aurora identity and a capture UUID with a matching run suffix;
- source URIs beneath the capture bundle URI;
- declared `cloudwatch_status` of `available` or `unavailable`;
- explicit ACL classification for every record;
- Investigation Evidence's four phases: `backfill`, `pool_exhaustion`, `recovery`, and
  `plan_regression`;
- Investigation Evidence's six signal types: `lock`, `pool`, `request`, `wal`, `meta`, and
  `plan`;
- pool-exhaustion and transaction-ID blocking proof;
- Validation Evidence's one existing incident, `plan_regression` phase, `meta` and `plan`
  signal types, and one validation change; and
- a payload that is identical on replay or rejected when changed.

Admission writes typed evidence, relationships, raw samples, and outbox rows
in one transaction. A Validation Evidence admission is a second capture linked to the
existing incident. It cannot alter or deprecate Investigation Evidence.

## 6. Search Index

The derived search index version combines the renderer version, chunker
version, embedding model ID, and search-document hash.

`backend/app/search_index.py`:

1. reads only queued authoritative source revisions;
2. renders and chunks them;
3. obtains Cohere `search_document` embeddings through Bedrock;
4. writes ready chunk versions and vectors;
5. promotes one current ready document version per evidence item;
6. supersedes prior versions only when the source render changes; and
7. records a build receipt.

Query embeddings use Cohere `search_query` in the same 1,024-dimensional model
space. An empty evidence store is `awaiting_incident`; a participant search
becomes ready only with current, fully embedded, drift-free documents from the
current capture lineage.

## 7. Retrieval and Relationships

Canonical ranking remains in `sql/03_search_functions.sql`:

1. boundary-aware exact identifiers form a deterministic first tier;
2. PostgreSQL full-text search ranks document and chunk text;
3. pgvector cosine search ranks semantic evidence;
4. `pg_trgm` ranks near matches;
5. metadata and ACL filters apply inside every arm before fusion;
6. weighted RRF combines arm positions; and
7. Cohere Rerank may reorder the fused candidate pool.

Default RRF controls are text `2`, semantic `1`, fuzzy `1`, and `k=60`.
Exact/raw lexical, vector, fuzzy, RRF, and model-rerank signals have different
meanings and are persisted separately. No score is a probability.

`retrieval.evidence_edges` renders foreign-key relationships as a uniform read
surface. Traversal applies visibility at both the seed and each hop. A
retrieval run's graph and timeline are constrained to the evidence available
when the run started, so a Lab 3 replay does not gain Validation Evidence records.

## 8. Hybrid Retrieval Agent and Supervised Execution

The agent's seven tools are read/synthesis-only. Its canonical answer path
decomposes the central question, searches bounded subquestions, follows
relationships, compares sources, and synthesizes cited text. It persists
candidate signals, stages, answer citations, and one structured action proposal
after validating the proposal's cited support.

The action proposal contains only validated fields. Application code renders
the DDL, derives its expected catalog fingerprint, measures preconditions, and
stores bounded timeout and rollback guidance. Model-authored free-text SQL is
never handed to a participant.

`proof.action_proposals`, `proof.action_proposal_citations`, and
`proof.action_executions` preserve the supervised decision:

- what the agent proposed and the citations that supported it;
- who explicitly approved the action;
- what PostgreSQL catalog definition was observed;
- whether observed and proposed fingerprints match; and
- which Validation Evidence receipt validated the outcome.

`proof.autonomy_readiness(proposal_id)` returns a pre-execution eligibility
verdict and an independent post-execution validation verdict with named
reasons. It is proof for a future policy discussion, not permission for
autonomous DDL.

## 9. Public API

```text
GET  /ready
GET  /v1/workshop/run
POST /v1/lab/hot-write
GET  /v1/lab/pool-status
POST /v1/search
POST /v1/agent/answer
POST /v1/agent/strands/answer
POST /v1/tools/decompose
POST /v1/tools/traverse
POST /v1/tools/compare
POST /v1/tools/explain-ranking
POST /v1/tools/synthesize
GET  /v1/runs/{run_id}
GET  /v1/runs/{run_id}/supervision
GET  /v1/evidence/{evidence_id}
POST /v1/evaluation
```

The lab routes are disabled outside the workshop controller and are not a
general application write API. All retrieval, proof, and agent APIs consume
the ready derived index; none mutates canonical evidence.

## 10. Observability Boundary

The core path is source-native:

- PostgreSQL catalogs prove connected blockers, lock type, and plan shape.
- `psycopg_pool.get_stats()` and API results prove pool waiters and
  `PoolTimeout` calls that have no PostgreSQL backend.
- `pg_stat_statements` and `EXPLAIN (ANALYZE, BUFFERS)` prove statement work
  and the access-path regression.
- CloudWatch is supplemental and non-gating.

Performance Insights and Database Insights are intentionally not prerequisites.
They can be useful production inputs, along with APM, logs, third-party
monitoring, and runbooks, but their availability and sampling model are outside
the deterministic SQL-forward participant path.

## 11. Packaging and Acceptance

`scripts/build_live_source_archive.sh` exports one committed source revision.
It rejects dirty runtime source, missing live-incident/exercise/gate assets,
generated captures, embedding caches, dumps, database files, and retired
fixture/seed paths. The participant stack receives source and generates the
operational workload; it never restores evidence or vectors.

Release acceptance requires:

- Aurora PostgreSQL 18.3 in `us-east-1` or a loopback PostgreSQL 18.3 database
  for local contract work; final release proof is Aurora;
- zero evidence before Investigation Evidence and no participant evidence from another run;
- a proven Investigation Evidence collision, recovery, and four-phase admission;
- coverage of all six Investigation Evidence signal types with acceptable diversity;
- runtime embeddings, one model space, and zero search-index drift;
- differentiated exact, full-text, semantic, fuzzy, fusion, and rerank
  receipts;
- a cited Investigation Evidence agent answer with a persisted proposal;
- a participant-owned matching index execution, additive Validation Evidence,
  and independent readiness verdicts;
- citation validation and replay without a model call;
- no hidden dependence on a Database Insights API permission; and
- a source archive containing no generated participant evidence.

The August 5 participant-path rehearsal on Aurora PostgreSQL 18.3
`db.r8g.2xlarge` measured 25.832s for the Lab 3 answer-plus-proposal request,
1.503s for the participant's non-concurrent index build, and 21.228s for Wave
B admission. It also admitted 54 Investigation Evidence and three Validation Evidence documents. These are
reference measurements for that substrate, not deployment guarantees; a final
Workshop Studio rehearsal must recalibrate them on its provisioned instance
class before publishing different participant-facing numbers.
