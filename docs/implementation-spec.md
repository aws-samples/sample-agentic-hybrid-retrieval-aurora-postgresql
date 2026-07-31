# DAT410 Implementation Specification

## Document Status

This document specifies Hybrid Retrieval Workbench as currently implemented in
this repository for DAT410 at AWS re:Invent 2026.

- **Session:** DAT410, Build agentic hybrid retrieval with Amazon Aurora PostgreSQL
- **Level:** 400
- **Format:** Builders' session
- **Duration:** 60 minutes
- **Application status:** Implemented and locally validated
- **Release status:** Not final until the Aurora, Bedrock, release-artifact, and
  Workshop Studio gates in this document pass

The source code, SQL, tests, and API responses are authoritative when this
document and an implementation disagree. The corpus is synthetic. No incident,
support case, customer, or telemetry record in this repository is an actual AWS
or customer record.

## 1. Product Contract

Hybrid Retrieval Workbench is an incident-evidence system, not a generic
chatbot.

Amazon Aurora PostgreSQL owns:

- the derived search index;
- exact, lexical, semantic, and fuzzy retrieval;
- metadata and ACL filtering;
- weighted reciprocal rank fusion;
- canonical relationship traversal;
- candidate and stage diagnostics;
- answer and citation receipts;
- controlled retrieval and traversal evaluation.

Authoritative operational systems own:

- workflow and mutable business state;
- current permissions;
- actions and mutations;
- connector cursors and source transport receipts.

The production decision for each evidence source must be explicit:

| Path | Use when |
|---|---|
| Materialize | Approved evidence must be ranked, joined, cited, evaluated, and replayed with predictable latency. |
| Federate | A source already has a suitable index or its content should remain outside Aurora. |
| Revalidate live | State is volatile, permission-sensitive, or will drive an action. |

The workshop implements the materialized path over a controlled synthetic
fixture. It does not simulate an unimplemented connector or source mutation.

## 2. Participant Outcome

The participant investigates one question:

> Why did CHG-1842 block checkout writes during INC-2047, which visible
> customer was affected, and what was the safe fix?

The evidence-backed result is:

- `CHG-1842` ran ordinary `CREATE INDEX` on the production writer.
- PostgreSQL allowed ordinary reads while writes accumulated
  `Lock:relation` waits.
- `LOCK-2047-001` and `LOCK-2047-002` identify the blocking index backend.
- visible support case `CASE-7419` identifies Acme Retail as affected;
  restricted `CASE-7421` remains hidden from the analyst persona;
  `CASE-7424` is explicitly unrelated.
- the response cancelled the blocking build and recovered queued writers.
- `RB-017` recommends `CREATE INDEX CONCURRENTLY` outside a transaction,
  with progress monitoring and invalid-index cleanup after failure.

The participant leaves with a persisted `run_id` that replays the query,
filters, persona, retrieval controls, candidates, stages, answer, citations,
relationship graph, and evidence timeline.

## 3. System Architecture

```text
Synthetic normalized operational records
                 |
                 | stable ID, revision, URI, ACL, typed foreign keys
                 v
          casework.* relational truth
                 |
                 | deterministic render + search document hash + outbox
                 v
        retrieval.* versioned search index
  documents -> chunks -> B-tree / GIN / HNSW indexes
                 |
                 | filters and ACLs before each retrieval arm
                 v
       canonical retrieval.* SQL functions
 exact + FTS + vector + trigram -> weighted RRF -> rerank
                 |
          +------+------+
          |             |
          v             v
  proof.* receipts   inspectable agent tools
          |             |
          +------+------+
                 v
       cited answer through HTTP or MCP
```

### Ownership layers

| Schema | Ownership |
|---|---|
| `casework` | Authoritative normalized workshop fixture and foreign-key relationships |
| `retrieval` | One-way derived, rebuildable, versioned search index and relationship view |
| `proof` | Historical retrieval, stage, answer, citation, and evaluation receipts |

The derived search tables uses base tables rather than a materialized view because
externally generated embeddings, incremental versions, tombstones, current
version promotion, and historical citation references are not a materialized
view refresh problem. A blocking refresh would also reintroduce an avoidable
availability tradeoff.

## 4. Controlled Corpus

### Canonical evidence

| Key | Kind | Purpose |
|---|---|---|
| `INC-2047` | Incident | Impact, read/write split, and resolution |
| `CHG-1842` | Change | Confirmed ordinary `CREATE INDEX` cause |
| `CHG-1838` | Change | Explicit ruled-out application worker change |
| `LOCK-2047-001` | Lock evidence | Blocked writer and blocking index statement |
| `LOCK-2047-002` | Lock evidence | Second blocked writer and `pg_blocking_pids` confirmation |
| `CASE-7419` | Support case | Visible affected customer and commitment |
| `CASE-7421` | Support case | Relevant restricted evidence for ACL proof |
| `CASE-7424` | Support case | Explicit unaffected comparison case |
| `RB-017` | Runbook | Concurrent index build guidance and caveats |

### Corpus scale

- Canonical thread: 11 source records.
- Offline local default: canonical thread plus 200 deterministic background
  records, for 211 documents.
- Release target: canonical thread plus deterministic background records to
  reach approximately 15,000 documents.
- Each generated source URI uses the `workshop://` scheme and remains synthetic.

### ACL fixture

The default evidence ACL is:

```json
{"visibility":"workshop","principals":[]}
```

`principals` is retained as an empty list only because
`retrieval.documents.acl_principals` and its GIN indexes are still projected; no
code reads it. `visibility` is the classification.

Seven objects are `{"visibility":"restricted"}`: `CASE-7421` (the canonical ACL
proof), `CASE-8102`, `CASE-8137`, `INC-3162`, `INC-4117`, `CHG-6213`, and
`CHG-3309`. They are visible only to a persona holding `can_see_restricted`
(`admin`, `auditor`), never to `analyst`. RLS enforces this at the three read
tables; `retrieval.acl_visible` applies the same expression inside every arm and
at every traversal hop.

## 5. Authoritative Data Model

### `casework` tables

| Table | Contract |
|---|---|
| `database_clusters` | Engine, Region, environment, service, and cluster identity |
| `evidence_items` | Stable evidence ID, kind, external key, source URI/revision/time, ACL, tombstone |
| `incidents` | Severity, interval, impact, resolution, and cluster |
| `changes` | Type, SQL, timing, owner, description, and rollback |
| `support_cases` | Account, tier, severity, SLA, description, and commitment |
| `runbooks` | Versioned procedure, applicability, owner, and caveats |
| `lock_evidence` | Controlled blocked/blocking PID snapshot tied to an incident |
| `incident_changes` | Suspected, confirmed, or ruled-out relationship |
| `incident_support_cases` | Affected, potentially affected, or unaffected relationship |
| `incident_runbooks` | Used, recommended, or rejected relationship |

`casework.evidence_items.evidence_id` is stable internal identity. Typed tables
own domain facts. Join tables and foreign keys own canonical relationships.

`casework.v_evidence_documents` is a deterministic renderer that emits source
identity, title, body, ACL, typed filters, metadata, and SHA-256
`search_document_hash`. It is an input contract, not the indexed search surface.

## 6. search index Contract

### `retrieval` relations

| Relation | Contract |
|---|---|
| `search_index_queue` | Source revision queued for search index |
| `search_index_builds` | Build version, model space, counts, status, timing, and error |
| `documents` | Versioned document metadata and current/superseded state |
| `chunks` | Versioned text, FTS vector, hash, embedding, model, and state |
| `inferred_edges` | Non-authoritative edges with method, confidence, and revision |
| `evidence_edges` | Read-only union of FK-derived canonical and governed inferred edges |

### Identity and versioning

```text
document version =
  evidence_id + renderer version + chunker version
  + embedding model ID + search document hash

chunk version =
  document_version_id + chunk ordinal + chunk hash

embedding cache key =
  embedding model ID + chunk hash
```

Only one ready document can be current for an evidence item. Historical
documents and chunks remain addressable by persisted candidates and citations.

### Build lifecycle

1. A typed casework transaction updates `evidence_items.source_revision`.
2. The same transaction calls `casework.queue_evidence(evidence_id)`.
3. The search index builder renders `casework.v_evidence_documents`.
4. An unchanged deterministic version is reused.
5. A changed render creates document and chunk versions.
6. Unchanged model-and-hash embeddings are reused.
7. The new ready document is promoted and the prior current document is
   superseded.
8. The matching outbox row is completed.

Each document is processed in its own transaction. A failed build can leave
some old current versions in place, but cannot promote two current ready
versions for one item.

### Tombstones

An authoritative deletion sets `is_deleted`, `deleted_at`, advances the source
revision, and queues the item. Rebuild supersedes the current search version.
New retrieval excludes it; historical receipts remain valid.

### Readiness and drift

`retrieval.v_search_index_drift` detects:

- missing current documents;
- revision or search-document-hash mismatches;
- current documents that are not ready;
- current documents for deleted evidence;
- missing ready embeddings.

`retrieval.assert_search_index_ready()` fails closed unless every live source row
has one current, ready, fully embedded, drift-free document. API `/ready`,
doctor, smoke, and tests use this database assertion.

## 7. Search and Index Design

### Physical indexes

| Index family | Purpose |
|---|---|
| B-tree | Exact identifiers and selective metadata/time filters |
| GIN `tsvector` | Separate document identity/title and chunk body FTS streams |
| GIN `gin_trgm_ops` | Identifier and title typo recovery |
| GIN JSONB | ACL metadata support |
| HNSW `vector_cosine_ops` | Approximate semantic candidates over ready chunk embeddings |

HNSW build defaults are `m=16` and `ef_construction=64`. Runtime defaults are
`ef_search=40` and `iterative_scan=relaxed_order`.

### Common filters

All arms support:

- evidence kinds;
- cluster ID;
- incident ID;
- account;
- severity;
- environment;
- start and end timestamps;
- caller persona.

Filters and `retrieval.acl_visible` execute inside each arm before fusion.

### Exact and full-text retrieval

- Boundary-aware exact identifier matching protects IDs such as `CHG-1842`.
- Document FTS prioritizes external key and title.
- Chunk FTS retrieves body evidence.
- PostgreSQL ranking values remain diagnostics.
- Results retain one strongest passage per evidence item before the final
  result limit.

### Semantic retrieval

- Cohere Embed 4 uses 1,024-dimensional vectors.
- Stored evidence uses `search_document`.
- Live queries use `search_query`.
- Query and stored vectors must have the same model ID and dimensions.
- Cosine distance produces the semantic ordering.
- HNSW runtime settings are transaction-local through
  `retrieval.configure_ann_runtime`.
- Iterative scan can continue scanning after selective post-index filters.

The deterministic hash provider is an offline mechanical substitute. It proves
embedding-space enforcement and search plumbing, not semantic quality.

### Fuzzy retrieval

`pg_trgm` operates over normalized external identifiers and titles. It is not
an unbounded body similarity scan. The default threshold is `0.3`.

### Weighted reciprocal rank fusion

The default weights are:

```text
text : vector : fuzzy = 2 : 1 : 1
k = 60
```

For candidate `d`:

```text
RRF(d) =
  2 / (60 + exact_identifier_rank(d))
  + 2 / (60 + text_rank(d))
  + 1 / (60 + vector_rank(d))
  + 1 / (60 + fuzzy_rank(d))
```

The exact-identifier term is present only for a boundary-matched identifier and
shares the text weight. Any absent arm contributes zero. Raw FTS, cosine, and
trigram values are not added to the fused score. `final_score` is weighted RRF
before optional model reranking.

### Model reranking

Cohere Rerank v3.5 receives the fused candidate pool after Aurora ranking.
Reranking can reorder that pool, but the receipt preserves:

- original arm positions;
- raw arm diagnostics;
- Aurora RRF score;
- separate model rerank score;
- whether reranking was applied;
- rerank stage timing and model ID.

No score is presented as a probability.

## 8. Agent Pipeline

The implemented tool sequence is:

1. `decompose_question`
2. `search_evidence`
3. `follow_evidence_links`
4. `compare_sources`
5. `explain_ranking`
6. `synthesize_cited_answer`

### Decomposition

The deterministic planner extracts keys such as `INC-*`, `CHG-*`, `CASE-*`,
`RB-*`, and `LOCK-*`, plus a database cluster identifier when present. It
produces inspectable filters and steps rather than an opaque plan.

### Targeted retrieval

The search tool calls the canonical SQL implementation and persists the run and
candidate receipts before synthesis.

### Relationship traversal

`retrieval.traverse_evidence` recursively walks canonical and inferred edges,
applies ACL checks to seeds and every hop, records path provenance, and limits
depth. FK-derived edges have confidence `1`; inferred edges retain their method
and confidence and never become FK facts.

### Source comparison

The compare stage loads source revisions, times, filters, and explicit edges for
the selected evidence. Each relevant edge is attached to synthesis evidence
with:

- relation;
- direction;
- counterpart key;
- canonical or inferred origin;
- confidence;
- rationale when available.

This makes source comparison an input to the answer, not a decorative stage.

### Cited synthesis

The model receives at most eight numbered evidence blocks. Each block includes
source metadata, relationship context, title, and exact evidence text. The
system prompt requires citations for factual sentences and forbids presenting
retrieval scores as probabilities.

If model synthesis is unavailable, a deterministic extractive fallback:

- prefers the named incident and change;
- selects diverse incident, change, lock, affected-case, and runbook evidence;
- excludes ruled-out changes and explicitly unaffected cases unless named;
- includes the visible account and safe-fix guidance;
- persists and validates citations exactly like model synthesis.

The fallback remains evidence-backed, but it is not a replacement for final
model-quality validation.

## 9. Proof, Attribution, and Replay

### `proof` tables

| Table | Persisted contract |
|---|---|
| `retrieval_runs` | Query, mode, filters, persona, models, controls, status, latency |
| `retrieval_candidates` | Final rank, arm values/positions, RRF, rerank, evidence snapshot |
| `run_stages` | Ordered stage name, duration, and details |
| `agent_answers` | Question, answer, synthesis mode, model transport, token usage |
| `answer_citations` | Citation number, source IDs, exact versions, URI, revision, quote, claim |
| `evaluation_queries` | Controlled retrieval or traversal question |
| `relevance_judgments` | Graded relevance and rationale |
| `traversal_results` | Persisted graph paths used for traversal metrics |

### Citation integrity

`proof.validate_answer_citations(run_id)` verifies:

- the evidence, document, and chunk versions resolve;
- source URI and revision match the exact document version;
- the quote occurs in the exact referenced chunk.

This proves attribution integrity. It does not independently establish that a
source statement or model claim is universally true.

### Replay surfaces

A `run_id` resolves to:

- run configuration and status;
- persisted candidates and ranking signals;
- stage timeline;
- persisted answer and citations;
- canonical relationship graph;
- chronological evidence timeline.

## 10. Evaluation

The controlled evaluation set contains:

- `exact-change`;
- `fuzzy-change-id`;
- `semantic-symptom`;
- `customer-impact`.

Retrieval metrics:

- recall at k;
- precision at k;
- mean reciprocal rank;
- nDCG at k.

Traversal metrics:

- relationship recall;
- relationship precision.

Retrieval and traversal metrics are reported separately. A graph traversal is
not scored as if it were a top-k retrieval list.

## 11. HTTP API

### Health and search

| Method and path | Purpose |
|---|---|
| `GET /health` | Process liveness |
| `GET /ready` | Database search index readiness |
| `POST /v1/search` | Configurable canonical retrieval |
| `POST /v1/search/vector` | Semantic mode |
| `POST /v1/search/fts` | Lexical mode |
| `POST /v1/search/fuzzy` | Fuzzy mode |

### Agent tools

| Method and path | Purpose |
|---|---|
| `POST /v1/agent/answer` | Complete inspectable agent path |
| `POST /v1/agent/answer/stream` | Event-stream form of the same result |
| `POST /v1/tools/decompose` | Deterministic decomposition |
| `POST /v1/tools/traverse` | ACL-safe relationship traversal |
| `POST /v1/tools/compare` | Source and relationship comparison |
| `POST /v1/tools/synthesize` | Synthesize from a persisted run |

### Evidence and proof

| Method and path | Purpose |
|---|---|
| `GET /v1/evidence/{evidence_id}` | Current evidence, chunks, and edges |
| `GET /v1/runs/{run_id}` | Run, candidates, stages, answer, and citations |
| `GET /v1/runs/{run_id}/candidates` | Candidate-only receipt |
| `GET /v1/runs/{run_id}/timeline` | Chronological evidence |
| `GET /v1/runs/{run_id}/graph` | Canonical/inferred relationship graph |

### Diagnostics and evaluation

| Method and path | Purpose |
|---|---|
| `GET /v1/diagnostics/search-index` | Health, embedding spaces, distribution, drift, builds |
| `GET /v1/diagnostics/corpus` | Corpus diagnostics |
| `GET /v1/diagnostics/fusion-sql` | Canonical fusion SQL |
| `POST /v1/diagnostics/plan` | Arm-specific query plan |
| `GET /v1/diagnostics/index-usage` | Index usage |
| `GET /v1/diagnostics/slow-queries` | `pg_stat_statements` retrieval diagnostics |
| `POST /v1/evaluation` | Controlled retrieval/traversal evaluation |

The public API reads the ready search index and proof state. It does not expose a
generic source-object write endpoint.

## 12. Tool Adapters

### Lambda / AgentCore Gateway adapter

`lambda_mcp/handler.py` is a stateless MCP-compatible adapter over the same
Python implementations. Workshop Studio owns deployment, IAM, Gateway, target
configuration, and the source package.

### Local stdio MCP server

`mcp-server/src/server.ts` exposes seven tools over MCP:

- `decompose_question`
- `search_evidence`
- `follow_evidence_links`
- `compare_sources`
- `explain_ranking`
- `synthesize_cited_answer`
- `answer_with_citations`

It calls the FastAPI application and does not reimplement SQL or ranking.

### Parity invariant

HTTP, Lambda/Gateway, and stdio MCP must return the same canonical ranking and
proof contracts because they all call the same retrieval and agent owners.

## 13. Frontend Workbench

The React application is an inspection workbench, not a landing page.

### Investigate

- scenario selector for incident, exact-ID, semantic, and typo paths;
- hybrid, semantic, lexical, and fuzzy mode control;
- evidence kind, cluster, incident, environment, and result filters;
- candidate pool, RRF `k`, arm weights, fuzzy threshold, HNSW
  `ef_search`, and iterative scan controls;
- model-rerank control and the Viewing-as persona selector;
- direct search and complete agent actions;
- cited answer and horizontally scrollable citation chips;
- fixed-column candidate receipt with FTS, vector, fuzzy, RRF, and rerank;
- evidence, signal, and relationship inspector tabs.

### Run proof

- load or copy a `run_id`;
- status, latency, candidate, RRF, HNSW, and fuzzy metrics;
- persisted query, models, answer, and citations;
- stage-duration timeline;
- candidate ranking table;
- interactive relationship graph with edge origin;
- chronological evidence timeline.

### Corpus

- source/document/chunk/embedding counts;
- search index drift and index time;
- evidence-kind distribution;
- model ID, dimensions, and vector timestamps;
- recent search index build receipts.

### Evaluation

- mode selection;
- retrieval/traversal query counts;
- nDCG, recall, and MRR leaderboard;
- expandable per-query judgments;
- explicit note that traversal metrics are separate.

### Frontend constraints

- No hardcoded answer, candidate, score, citation, or proof data.
- No remote fonts, analytics, source-system logos, or automatic external calls.
- Operational, dense layout with restrained evidence-kind colors.
- Inner horizontal scrolling for wide ranking and receipt tables.
- Document-level horizontal overflow must remain zero on desktop and mobile.
- The frontend calls only `VITE_RETRIEVAL_API_URL`.

## 14. Model Configuration

Configured workshop roles:

| Role | Model ID | API and routing |
|---|---|---|
| Embedding | `us.cohere.embed-v4:0` | Bedrock Runtime `InvokeModel`, US CRIS |
| Reranking | `cohere.rerank-v3-5:0` | Bedrock Agent Runtime `rerank` |
| Synthesis | `global.anthropic.claude-sonnet-5` | Bedrock Runtime `Converse`, Global CRIS |

Required configuration includes:

- `AWS_REGION=us-east-1`
- `AWS_DEFAULT_REGION=us-east-1`
- `BEDROCK_EMBEDDING_MODEL`
- `COHERE_RERANK_MODEL`
- `BEDROCK_SYNTHESIS_MODEL`
- `BEDROCK_MODEL_TRANSPORT=converse_global_cris`
- `BEDROCK_SYNTHESIS_MAX_TOKENS=1200`

Model IDs and transports are configuration, not application constants. Bedrock
clients use bounded adaptive retries. Synthesis sets `maxTokens` explicitly.

The validated synthesis design uses Converse plus Global CRIS. It does not
claim that Mantle and CRIS are used simultaneously. Model lifecycle, CRIS
support, source/destination Regions, IAM, and quotas must be rechecked before
the event.

## 15. Build and Runtime Modes

### Offline local mode

```bash
make schema
make seed-local
DOCTOR_SKIP_BEDROCK=1 make doctor
make api
make frontend
```

Offline mode uses `EMBED_PROVIDER=hash` and disables model reranking. Stored and
query embeddings must both use `local-hash-embedding-v1`.

### Release-author mode

Release authors may explicitly generate missing Cohere vectors:

```bash
.venv/bin/python backend/scripts/build_search_index.py \
  --load-casework \
  --background-documents 15000 \
  --provider bedrock \
  --embed-missing
```

`--embed-missing` is explicit because it makes billable model calls.
Participants do not generate the release corpus during the session.

### Workshop mode

Workshop Studio must provision and package:

- target Aurora PostgreSQL and network access;
- supported extensions and parameters;
- preloaded casework, vectors, and indexes;
- IAM and Bedrock access;
- Code Editor environment;
- AgentCore Gateway and Lambda target;
- immutable application source revision.

## 16. Sixty-Minute Core

| Minute | Core proof |
|---:|---|
| 0-7 | Scenario, ownership boundary, and readiness |
| 7-14 | Exact/full-text retrieval, filters, and ACL placement |
| 14-19 | Indexed trigram typo recovery |
| 19-27 | Filtered HNSW and iterative scan |
| 27-35 | Weighted RRF and independent arm positions |
| 35-40 | Model reranking without replacing Aurora scores |
| 40-50 | Agent decomposition, retrieval, traversal, comparison, ranking explanation |
| 50-55 | Citation validation and compact evaluation |
| 55-60 | Buffer, replay receipt, and production boundary |

First cut when behind: RRF weight experimentation. Second cut: detailed
evaluation walkthrough. The cited-answer and replay path remain mandatory.

Appendix work includes connector transports, release-scale generation,
replacement-index operations, inferred-edge generation, Gateway deployment,
production identity, and load/failover testing.

## 17. Acceptance Criteria

### Retrieval

- `CHG-1842` is lexical rank 1 under the cluster filter.
- `CGH-1842` resolves to `CHG-1842` through indexed trigram retrieval.
- Hybrid persists independent text, vector, and fuzzy positions.
- Default fusion controls persist as `2:1:1`, `k=60`, threshold `0.3`.
- Result sets contain at most one strongest passage per evidence item.
- Query and stored embedding spaces must match exactly.

### Authorization and relationships

- `CASE-7421` and the six supporting restricted objects never enter analyst
  retrieval or traversal, and return zero rows at the raw table.
- The `admin` persona retrieves the restricted fixtures; the `auditor` persona
  retrieves them with customer and operator identity masked.
- FK-derived edges remain distinguishable from inferred edges.
- `CHG-1842` is `change_confirmed`.
- `CHG-1838` is `change_ruled_out`.
- `CASE-7419` is affected and `CASE-7424` is not affected.

### Proof

- Every run persists candidates before synthesis.
- Every final citation resolves to an exact document and chunk version.
- Citation URI, revision, and quote validation passes.
- `GET /v1/runs/{run_id}` returns the persisted answer and citations.
- Raw scores, RRF, and rerank remain separate and inspectable.

### search index

- Rebuild is idempotent.
- Unchanged content reuses model-and-hash embeddings.
- Tombstones supersede current documents without erasing history.
- search index drift is zero before readiness.
- Exactly one canonical signature exists for each search function.

### Delivery

- Participant core is completable inside 60 minutes.
- No live provisioning, connector build, or 15,000-vector generation is in the
  participant path.
- Every abstract capability has a runnable code path or is explicitly appendix
  work.

## 18. Validation Receipt

Validated locally on July 24, 2026:

- PostgreSQL 18.4 and pgvector 0.8.2.
- Exact schema stack applied to disposable databases.
- 211-document deterministic local corpus.
- 211 ready 1,024-dimensional hash embeddings.
- Zero search index drift.
- 28 backend tests passed.
- Frontend TypeScript and Vite production build passed.
- MCP TypeScript build passed.
- All tracked Python files compiled.
- All tracked shell scripts passed `bash -n`.
- `git diff --check` passed with this document present.
- Doctor passed all hard database, schema, index, ACL, search index, API, and
  frontend gates; Bedrock probes were intentionally skipped.
- Smoke passed lexical, fuzzy, ACL denial/allow, traversal, fallback answer,
  five citations, and persisted receipt checks.
- HTTP answer returned `change_confirmed` and `change_ruled_out` context and
  cited `INC-2047`, `CHG-1842`, `LOCK-2047-001`, `CASE-7419`, and `RB-017`.
- Lambda adapter passed the same cited-answer contract.
- A real stdio MCP client listed all seven tools, retrieved `CHG-1842` at rank
  1, and returned the same five citations.
- Playwright exercised Investigate, Run proof, Corpus, and Evaluation at
  1440x1000 and 390x844.
- Browser checks found no console errors and zero document-level horizontal
  overflow.

This local receipt proves PostgreSQL behavior and application integration. It
does not substitute for target Aurora or live Bedrock release validation.

## 19. Remaining Release Gates

The repository is not event-release-complete until all of these pass:

1. Run schema, doctor, smoke, query plans, and the complete answer on the target
   Aurora PostgreSQL engine inside the Workshop Studio VPC.
2. Reconfirm extension versions, parameter group behavior,
   `pg_stat_statements`, HNSW iterative scan, and planner behavior on Aurora.
3. Recheck Bedrock model lifecycle and current model availability.
4. Run live Cohere Embed, Cohere Rerank, and Claude synthesis probes in
   `us-east-1` with the workshop IAM role.
5. Generate and review the frozen 15,000-document Cohere embedding cache and
   PostgreSQL restore artifact.
6. Validate filtered-HNSW candidate behavior and timing at release scale.
7. Run room-scale concurrency and throttling tests for API, Aurora, rerank, and
   synthesis.
8. Update the sibling Workshop Studio content and immutable source archive only
   after this application revision is frozen.
9. Verify fresh-account Workshop Studio provisioning and participant commands.
10. Record the final source revision, archive hash, expected run IDs, and
    facilitator fallback checkpoints.

No local result should be described as Aurora validation, and no hash-vector
result should be described as Cohere semantic-quality validation.

## 20. Repository Ownership

| Path | Owner |
|---|---|
| `backend/app/` | FastAPI, search index, retrieval, rerank, tools, synthesis, proof |
| `backend/tests/` | Unit and disposable-database contracts |
| `sql/` | Schema, indexes, search, diagnostics, receipts, evaluation, traversal |
| `seed/` | Deterministic synthetic casework corpus and release inputs |
| `frontend/` | Incident-evidence inspection workbench |
| `lambda_mcp/` | Stateless AgentCore Gateway adapter |
| `mcp-server/` | Optional local stdio MCP wrapper |
| `scripts/` | Environment and managed-boundary helpers |
| `docs/` | Architecture, contracts, session flow, and this specification |

This repository owns application source. The sibling Workshop Studio repository
owns infrastructure, workshop pages, deployment, and the packaged source
archive.
