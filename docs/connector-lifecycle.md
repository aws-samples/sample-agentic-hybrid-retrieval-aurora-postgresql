# Connector lifecycle

Systems of record keep the work. A connector maintains an approved, rebuildable
evidence projection in Aurora.

## Synchronization contract

Every connector maps source records into `SourceObject` and identifies itself
with a stable `source_system` plus `source_name`.

| Mode | Use | Behavior |
|---|---|---|
| `upsert` | webhook or incremental poll | inserts new objects and updates records present in the request |
| `full` | initial load or periodic reconciliation | performs the upserts, then tombstones active records missing from the snapshot |

The connector cursor is stored in `ops.source_connectors.sync_cursor`. A cursor
can be a Git revision, API continuation token, high-water timestamp, export
manifest, or compound value appropriate to the source.

## Change handling

The ingestion path:

1. Upserts normalized object metadata and source provenance.
2. Compares the body hash and skips chunk work for unchanged content.
3. Rechunks changed content and sets only changed chunk embeddings to `NULL`.
4. Recreates citations for changed chunks.
5. Tombstones missing objects during a full synchronization.
6. Batches embeddings for the remaining `NULL` chunks.

The source remains `indexing` while embeddings are pending and becomes `ready`
only after its active chunks are embedded. Lexical retrieval can be ready before
semantic retrieval; the ingestion response reports both states separately.

Tombstoned rows remain available to historical foreign keys but are excluded
from new retrieval and corpus diagnostics.

## Index maintenance

Normal `INSERT` and `UPDATE` operations maintain the generated `tsvector`, GIN,
trigram, and HNSW indexes automatically. Do not run `REINDEX` after every
connector sync.

- **Incremental sync:** commit bounded batches and let PostgreSQL maintain the
  indexes.
- **Large initial load:** bulk load records and embeddings, build expensive
  indexes after the load, then run `ANALYZE`. `seed/load.sh` demonstrates this.
- **Changed HNSW build parameters:** build a replacement index and cut over after
  validation.
- **Corruption or exceptional bloat:** use operationally controlled concurrent
  reindexing, not the connector request path.

## Scaling the pattern

- Partition connector work by source and cursor; never use one global cursor.
- Make external IDs stable and repository-qualified so retries are idempotent.
- Batch source reads, database writes, and embedding requests independently.
- Apply backpressure and retry only transient source or model failures.
- Run periodic full reconciliation even when webhooks provide the low-latency
  delta path.
- Persist source revision, content hash, connector run, and retrieval `run_id` so
  freshness and answer provenance can be audited separately.
- Keep source transport explicit. A local working-tree snapshot, an immutable
  GitHub commit, a webhook delta, and an API export are different receipts even
  when they normalize into the same objects.
- Revalidate mutable state and perform writes in the source system.
