# search index Build Contract

The workshop does not expose a generic ingestion HTTP API. The old
source-object endpoint was removed because it duplicated the domain model and
promised connector behavior that the one-hour session did not exercise.

The implemented write boundary is:

```text
typed casework transaction
  -> casework.evidence_items source revision
  -> casework.queue_evidence(evidence_id)
  -> retrieval.search_index_queue
  -> backend/app/search_index.py
  -> versioned retrieval.documents and retrieval.chunks
```

## Source Input

Every searchable casework row must resolve to one
`casework.evidence_items` record with:

- stable `evidence_id`;
- evidence kind and external key;
- source system and source URI;
- monotonic or otherwise comparable source revision;
- source update timestamp;
- ACL metadata;
- tombstone state.

Typed domain tables own facts and relationships. Search text is rendered from
those rows by `casework.v_evidence_documents`; applications do not hand-edit
`retrieval.documents`.

## search index Version

The search index version combines:

- renderer version;
- chunker version;
- embedding model ID.

The render output adds a search document hash. Together these values determine
whether the current version can be reused or a new document and chunk set is
required.

Embedding cache keys include both model ID and chunk hash. An unchanged chunk
in the same model space is reused. A changed chunk or model ID requires a new
embedding.

## Build Commands

Offline deterministic fixture:

```bash
make schema
make seed-local
```

search index from already loaded casework and a complete embedding cache:

```bash
make seed-project
```

Release-author-only generation of missing Cohere vectors:

```bash
.venv/bin/python backend/scripts/build_search_index.py \
  --load-casework \
  --background-documents 15000 \
  --provider bedrock \
  --embed-missing
```

`--embed-missing` is explicit because it makes billable Bedrock calls. Workshop
accounts restore precomputed state; participants do not embed 15,000 documents
during the session.

## Idempotency

For each rendered document, the search index builder:

1. checks for the deterministic ready document version;
2. marks its matching outbox row complete and skips work when unchanged;
3. inserts or resumes the non-current document version when changed;
4. writes deterministic chunk versions and ready embeddings;
5. supersedes the prior current document;
6. promotes the new ready document;
7. completes the matching source-revision outbox row.

Each document is processed in its own transaction. A failed build can therefore
leave a mix of old and new ready versions, but never two current ready versions
for one evidence item. The build receipt records failure and the readiness
assertion detects missing or stale search index state before the API is declared
ready.

After at least 1,000 indexed documents, the bulk builder runs `ANALYZE` on
the document and chunk tables so planner statistics reflect the new corpus.

## Tombstones

A source deletion is an authoritative casework update:

```sql
UPDATE casework.evidence_items
SET is_deleted = true,
    deleted_at = now(),
    source_revision = :new_revision
WHERE evidence_id = :evidence_id;

SELECT casework.queue_evidence(:evidence_id);
```

The next build supersedes the current search document and completes the outbox
event. Historical proof keeps its foreign-key references to the old document
and chunk versions.

## Production Adaptation

A production connector or event consumer should write the typed domain tables
and queue the affected evidence ID in the same transaction. It should retain
its own source cursor and transport receipt outside the generic search
search index.

Use:

- **delta/upsert processing** for webhooks or incremental polls;
- **periodic full reconciliation** to detect source deletions;
- **bounded batches** for casework writes and search index work;
- **content-hash reuse** for embeddings;
- **live revalidation** for volatile permissions or action-driving state.

Do not call Bedrock from a materialized-view refresh or database trigger. Model
latency, retries, and cost belong in an observable worker boundary.

## Read APIs

The implemented public surface is retrieval and proof:

```text
POST /v1/search
POST /v1/agent/answer
POST /v1/tools/decompose
POST /v1/tools/traverse
POST /v1/tools/compare
POST /v1/tools/synthesize
GET  /v1/runs/{run_id}
GET  /v1/evidence/{evidence_id}
POST /v1/evaluation
```

These APIs consume the ready search index. They do not mutate authoritative
casework.
