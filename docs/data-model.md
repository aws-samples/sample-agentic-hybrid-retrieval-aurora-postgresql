# Data Model

The schema separates **Authoritative Evidence** (`evidence`), **Search &
Ranking** (`retrieval`), and **Runs, Citations & Audit** (`proof`). That
separation is the central design invariant. The participant-facing names
describe each boundary; the schema names are the stable SQL contract.

## `evidence`: Authoritative Evidence

| Relation | Purpose |
|---|---|
| `database_clusters` | Aurora PostgreSQL cluster, engine version, Region, environment, and service metadata |
| `evidence_items` | Stable evidence ID, type, external key, source URI, source revision, ACL, and tombstone |
| `ingest_receipts` | Idempotent evidence-admission receipt with source, payload hash, write counts, and queue result |
| `incidents` | Severity, interval, impact, resolution, and cluster |
| `changes` | Change type, SQL, timing, owner, description, and rollback plan |
| `incident_capture_runs` | Participant-induced capture identity, bounded window, relation, target, and manifest |
| `lock_evidence` | Measured blocked/blocking PID snapshot tied to an incident and capture |
| `telemetry_evidence` | Searchable evidence built deterministically from measured telemetry |
| `pg_stat_activity_samples` | Raw activity rows for each observation |
| `pg_lock_samples` | Raw relation-lock rows for each observation |
| `pg_blocking_pids_samples` | Raw blocking chains for each observation |
| `pg_stat_statements_samples` | Before, during, and after statement measurements |
| `cloudwatch_metric_samples` | Incident-window RDS metric observations |
| `incident_changes` | Suspected, confirmed, or ruled-out change relationship |

`evidence_items.evidence_id` is the stable internal identity. External keys are
unique within an evidence kind and are globally unique for unambiguous agent
references.

The participant core admits two additive measured bundles under source system
`pg_incident_capture`. Investigation Evidence contains the migration diagnosis; Validation Evidence attaches
post-index validation to the same incident without replacing Investigation Evidence. Every key
is derived from its capture UUID: `INC-<run-suffix>`,
`CHG-<run-suffix>-...`, `LOCK-<run-suffix>-01`, and
`TEL-<run-suffix>-...`. The database starts empty, and participant retrieval
filters on source system and receipt identity before ranking.

`evidence.v_evidence_documents` is a deterministic renderer over the normalized
tables. It emits:

- source identity and revision;
- title and rendered body;
- ACL;
- typed filter columns such as cluster, incident, account, severity,
  environment, and event time;
- metadata JSONB;
- a SHA-256 `search_document_hash`.

Timestamp metadata is rendered in a fixed UTC form before hashing, so the
document identity does not depend on the database session's `TimeZone`.

The view is an input contract, not the indexed search surface.

## `retrieval`: Search & Ranking

| Relation | Purpose |
|---|---|
| `search_index_queue` | Evidence revision queued for search index |
| `search_index_builds` | Renderer, chunker, model space, counts, status, and error for each build |
| `documents` | Versioned searchable document metadata and current/superseded state |
| `chunks` | Versioned text chunks, source system, hashes, full-text vectors, and embeddings |
| `inferred_edges` | Non-authoritative relationships with method, confidence, and revision |
| `evidence_edges` | Read-only union of canonical foreign-key edges and inferred edges |

A document version is deterministic for:

```text
evidence_id + renderer/chunker/model version + search_document_hash
```

A chunk version is deterministic for:

```text
document_version_id + chunk ordinal + chunk hash
```

Only one ready document can be current for an evidence item. Rebuilding an
unchanged search index skips document and embedding work. A changed render creates
a new version and supersedes the old one. Historical candidates and citations
continue to reference the old versions.

The search index model records `search_document` for stored embeddings. Query
embeddings use `search_query`; both must use the same model ID and 1,024
dimensions.

## Search Indexes

| Index | Role |
|---|---|
| B-tree on `lower(external_key)` | Exact identifier lookup |
| B-tree partial indexes on source system, kind, cluster, incident, account, severity, and time | Candidate filtering |
| GIN on document `search_tsv` | Identifier and title full-text retrieval |
| GIN on chunk `search_tsv` | Body full-text retrieval |
| GIN `gin_trgm_ops` on identifier and title | Fuzzy entity recovery |
| GIN on ACL JSONB | ACL metadata support |
| HNSW `vector_cosine_ops` on ready chunk embeddings | Approximate semantic retrieval |

The HNSW index uses `m=16` and `ef_construction=64`. Query-time `ef_search`
defaults to `40`. pgvector iterative scan defaults to `relaxed_order` so
post-index filters can continue scanning for enough visible candidates. These
settings are inspectable tuning inputs, not guarantees of recall or latency.

## `proof`: Runs, Citations & Audit

| Relation | Purpose |
|---|---|
| `retrieval_runs` | Query, filters, workshop role field, model space, RRF weights, fuzzy threshold, ANN controls, rerank state, status, and latency |
| `retrieval_candidates` | Final rank plus raw arm scores, arm positions, RRF, rerank score, and evidence snapshot |
| `run_stages` | Ordered retrieval and agent stage timings |
| `observability_refs` | Retrieval-window observability reference and verification context |
| `agent_runs` | Bounded agent question, initial controls, tool-call budget, and completion state |
| `agent_subquestions` | Decomposed evidence requirement and coverage state for an agent run |
| `agent_retrievals` | Retrieval attempts made for an agent subquestion |
| `agent_escalations` | Recorded retry or escalation when a subquestion lacks required evidence |
| `agent_answers` | Question, answer text, synthesis mode, model transport, and token usage |
| `answer_citations` | Citation number, exact document/chunk versions, URI, revision, quote, and claim |
| `action_proposals` | Structured, cited, catalog-checked recommendation rendered into participant SQL |
| `action_proposal_citations` | Proposal claim links to validated answer citations |
| `action_executions` | Append-only human approval, observed index fingerprint, and Validation Evidence receipt link |
| `evaluation_queries` | Controlled retrieval or traversal question |
| `relevance_judgments` | Graded relevance label and rationale |
| `traversal_results` | Persisted graph paths for traversal evaluation |
| `transport_invocations` | HTTP, MCP, or AgentCore invocation receipt linked to a retrieval run when available |

`proof.validate_answer_citations(run_id)` verifies that a citation URI and
revision match the referenced document and that the quote occurs in the exact
referenced chunk. It validates attribution integrity; it does not claim that a
model-generated sentence is universally true.

`proof.autonomy_readiness(proposal_id)` separately reports what evidence
supported an action before execution and what the recorded human-approved
outcome later validated. It is an auditable readiness assessment, not
authorization for autonomous DDL.

## ACL Model

Every evidence item carries:

```json
{
  "visibility": "workshop",
  "principals": []
}
```

`visibility` is the only classification axis. `principals` survives as an always
empty list because `retrieval.documents.acl_principals` and its GIN indexes are
still copied into derived columns; no code reads it.

`evidence.evidence_items` keeps the JSONB. The search index copies the same
value into the sargable columns `retrieval.documents.acl_visibility` and
`retrieval.chunks.acl_visibility`. Anything other than `workshop` is restricted,
and the derived columns default to `restricted`, so an unclassified row fails
closed.

In core mode, `retrieval.acl_visible` and
`retrieval.acl_scalars_visible` expose only workshop-visible rows. This fixed
scope is applied before every retrieval arm enters fusion and at every traversal
hop; it requires no persona role or RLS installation.

Production identity and authorization revalidation remain architecture
concerns, not participant demonstrations: the API's workshop context is not
production authentication, and its persona selection is a teaching control
under the API caller's own AWS account, not an access-control boundary
between separate identities. The live workshop corpus contains no authored
restricted customer record. An event owner may enable `sql/11_roles_rls.sql`
and `sql/12_masking.sql` as an optional lab so a participant can compare
real RLS/masking visibility against that same live capture from inside the
persona they select.

The JSONB policy is intentionally small for teaching. A production design should
map authenticated identity and source-system authorization into a reviewed policy,
and revalidate permissions live when indexed ACL metadata is not sufficient.

## Deletion and History

Deleting source evidence means setting `is_deleted` and `deleted_at`, updating
the source revision, and queuing that evidence ID. search index rebuild then:

1. removes the item from `evidence.v_evidence_documents`;
2. supersedes its current search document;
3. completes the tombstone outbox event;
4. excludes it from new search and traversal;
5. preserves historical document, candidate, answer, and citation references.

Foreign keys use `ON DELETE RESTRICT`; history is not silently erased.

## Drift Contract

`retrieval.v_search_index_drift` reports:

- missing current documents;
- search-document-hash or source-revision mismatches;
- current documents that are not ready;
- current documents for deleted evidence;
- missing ready embeddings.

`retrieval.assert_search_index_ready()` fails unless the search index is complete,
drift-free, and fully embedded. `make doctor`, API readiness, tests, and
workshop preflight all use that assertion.
