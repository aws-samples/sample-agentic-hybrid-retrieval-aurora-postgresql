# search index Lifecycle

This document separates the lifecycle implemented by the workshop from the
connector responsibilities a production system would add.

## Workshop Lifecycle

The participant lifecycle starts with an empty schema and one guided live run.
It has no checked-in fallback:

```text
live write stall + 30 PostgreSQL samples + AWS observations
    -> deterministic projection of measured telemetry
    -> atomic run-scoped admission
    -> 104-111 pending source revisions
    -> runtime Cohere embedding build
    -> indexing receipt enables retrieval
```

The live orchestrator writes normalized `casework.*` rows, queues every source
revision, and invokes one source-scoped search-index build. The builder scans
`casework.v_evidence_documents`, skips deterministic versions already ready,
and completes matching outbox rows.

```text
casework write
    |
    v
outbox pending
    |
    v
search index build running
    |
    +--> unchanged version -> skip -> outbox complete
    |
    +--> changed version -> chunks/embeddings -> promote -> outbox complete
    |
    +--> error -> build failed; readiness/drift checks fail
```

The current bulk command does not pretend to be a distributed connector
scheduler. `claimed` exists in the outbox state model for a production worker,
but the workshop builder does not need competing-consumer coordination.

## Update

An update must:

1. modify the authoritative typed row and `evidence_items.source_revision`;
2. call `casework.queue_evidence(evidence_id)` in the same transaction;
3. render the source row deterministically;
4. reuse embeddings for unchanged model-and-content hashes;
5. create and promote a new document version only when the search index changes.

The prior version is superseded, not deleted.

## Deletion

Set `is_deleted`, set `deleted_at`, advance the source revision, and queue the
evidence item. The renderer excludes deleted rows; rebuild supersedes their
current document. New search and traversal cannot see the item, while historical
proof remains valid.

## Readiness

A corpus is ready only when:

- each live source row has one current ready document;
- current search document hashes and source revisions match;
- no current document belongs to a deleted source;
- every current chunk has a ready embedding in the expected model space;
- the search index has zero drift issues.

API `/ready` and `make doctor` call the database assertion rather than trusting
a process-local flag.

## Index Maintenance

Ordinary inserts and updates maintain B-tree, GIN, trigram, and HNSW indexes.
Do not run `REINDEX` after each source update.

- For a large initial load, load data, create or validate indexes, and run
  `ANALYZE`.
- To change HNSW build parameters, build and validate a replacement index under
  an operationally reviewed rollout.
- Use concurrent index operations only after checking their PostgreSQL and
  Aurora version constraints, transaction restrictions, disk requirements, and
  failure behavior.
- Treat corruption recovery and exceptional bloat as database operations, not
  connector request work.

## Production Connector Responsibilities

A real source adapter must additionally own:

- source authentication and least-privilege authorization;
- a connector-scoped cursor or high-water mark;
- idempotent retries and dead-letter handling;
- bounded source reads, database writes, and embedding batches;
- periodic full reconciliation;
- transport receipts and source API rate limits;
- live authorization revalidation where indexed ACLs are insufficient.

Those responsibilities are deliberately outside the 60-minute workshop core.
The extension point is the typed `casework` transaction plus outbox event, not a
generic untyped source-object table.

## Failure Handling

| Failure | Current behavior | Recovery |
|---|---|---|
| Runtime embedding call fails | Build fails before retrieval readiness | Restore Bedrock access and retry the current live run build |
| Model or network failure during generation | Build receipt is `failed` | Retry only after checking model access and cache state |
| Per-document database error | Current transaction rolls back; build is marked failed | Correct the row/schema issue and rerun idempotently |
| Process stops after partial progress | Promoted versions remain valid; remaining drift is visible | Rerun the search index builder and readiness assertion |
| Source deletion | Old version is superseded | Preserve history; do not hard-delete referenced evidence |

No failure path fabricates embeddings, source revisions, or citations.
