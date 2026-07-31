# Data Model

The schema separates authoritative casework, derived search state, and
historical proof. That separation is the central design invariant.

## `casework`: Authoritative Fixture

| Relation | Purpose |
|---|---|
| `database_clusters` | Aurora PostgreSQL cluster, engine version, Region, environment, and service metadata |
| `evidence_items` | Stable evidence ID, type, external key, source URI, source revision, ACL, and tombstone |
| `incidents` | Severity, interval, impact, resolution, and cluster |
| `changes` | Change type, SQL, timing, owner, description, and rollback plan |
| `support_cases` | Account, tier, severity, SLA, description, and commitment |
| `runbooks` | Versioned procedure, applicability range, owner, and caveats |
| `lock_evidence` | Controlled blocked/blocking PID snapshot tied to an incident |
| `incident_changes` | Suspected, confirmed, or ruled-out change relationship |
| `incident_support_cases` | Affected, potentially affected, or unaffected case relationship |
| `incident_runbooks` | Used, recommended, or rejected runbook relationship |

`evidence_items.evidence_id` is the stable internal identity. External keys are
unique within an evidence kind, and the controlled corpus also keeps them
globally unique for unambiguous agent references.

`casework.v_evidence_documents` is a deterministic renderer over the normalized
tables. It emits:

- source identity and revision;
- title and rendered body;
- ACL;
- typed filter columns such as cluster, incident, account, severity,
  environment, and event time;
- metadata JSONB;
- a SHA-256 `search_document_hash`.

The view is an input contract, not the indexed search surface.

## `retrieval`: Rebuildable search index

| Relation | Purpose |
|---|---|
| `search_index_queue` | Evidence revision queued for search index |
| `search_index_builds` | Renderer, chunker, model space, counts, status, and error for each build |
| `documents` | Versioned searchable document metadata and current/superseded state |
| `chunks` | Versioned text chunks, hashes, full-text vectors, and embeddings |
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
| B-tree partial indexes on kind, cluster, incident, account, severity, and time | Candidate filtering |
| GIN on document `search_tsv` | Identifier and title full-text retrieval |
| GIN on chunk `search_tsv` | Body full-text retrieval |
| GIN `gin_trgm_ops` on identifier and title | Fuzzy entity recovery |
| GIN on ACL JSONB | ACL metadata support |
| HNSW `vector_cosine_ops` on ready chunk embeddings | Approximate semantic retrieval |

The HNSW index uses `m=16` and `ef_construction=64`. Query-time `ef_search`
defaults to `40`. pgvector iterative scan defaults to `relaxed_order` so
post-index filters can continue scanning for enough visible candidates. These
settings are inspectable tuning inputs, not guarantees of recall or latency.

## `proof`: Replayable Evidence

| Relation | Purpose |
|---|---|
| `retrieval_runs` | Query, filters, persona, model space, RRF weights, fuzzy threshold, ANN controls, rerank state, status, and latency |
| `retrieval_candidates` | Final rank plus raw arm scores, arm positions, RRF, rerank score, and evidence snapshot |
| `run_stages` | Ordered retrieval and agent stage timings |
| `agent_answers` | Question, answer text, synthesis mode, model transport, and token usage |
| `answer_citations` | Citation number, exact document/chunk versions, URI, revision, quote, and claim |
| `evaluation_queries` | Controlled retrieval or traversal question |
| `relevance_judgments` | Graded relevance label and rationale |
| `traversal_results` | Persisted graph paths for traversal evaluation |

`proof.validate_answer_citations(run_id)` verifies that a citation URI and
revision match the referenced document and that the quote occurs in the exact
referenced chunk. It validates attribution integrity; it does not claim that a
model-generated sentence is universally true.

## ACL Model

Every evidence item carries:

```json
{
  "visibility": "workshop"
}
```

`visibility` is the only classification axis. It is projected to the sargable
column `retrieval.documents.acl_visibility` (and `retrieval.chunks`), which both
the RLS policy and `retrieval.acl_visible` read. Anything other than `'workshop'`
is restricted, and the schema default is `'restricted'` so an unclassified row
fails closed.

Identity is the caller's persona — `analyst`, `admin`, or `auditor` — carried as a
database role, never as a value in the request body. `CASE-7421` and the six
restricted objects seeded alongside it are visible only to a persona holding the
`can_see_restricted` clearance, and they must not enter any retrieval arm,
traversal hop, comparison, or answer for the analyst.

The JSONB policy is intentionally small for teaching. A production design should
map authenticated identity and source-system authorization into a reviewed policy,
and revalidate permissions live when indexed ACL metadata is not sufficient.

## Deletion and History

Deleting source evidence means setting `is_deleted` and `deleted_at`, updating
the source revision, and queuing that evidence ID. search index rebuild then:

1. removes the item from `casework.v_evidence_documents`;
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
