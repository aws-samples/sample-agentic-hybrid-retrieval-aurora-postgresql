# Controlled PostgreSQL Lock Incident

This lab reproduces the lock mechanism behind `INC-2047` with real PostgreSQL
sessions. It does not insert a prewritten incident or issue `LOCK TABLE`.

The lab has two phases:

1. A plain `CREATE INDEX` runs inside an explicit transaction. PostgreSQL keeps
   its granted `ShareLock` until that transaction ends. Reads continue, while an
   `UPDATE` requesting `RowExclusiveLock` waits.
2. A writer transaction stays open while `CREATE INDEX CONCURRENTLY` starts.
   The index build holds `ShareUpdateExclusiveLock`, a fresh `UPDATE` succeeds,
   and the build waits for the older transaction before finishing.

Three sessions are required because a lock wait is a relationship between
different PostgreSQL backends. All objects live in the disposable
`workbench_lab` schema. The scripts never alter `casework`, `retrieval`, or
`proof`.

## Prerequisites

- Run from the repository root.
- Set `DATABASE_URL` to the workshop database.
- Use a database role that can create a schema and inspect all participating
  sessions through `pg_stat_activity` and `pg_locks`.
- Open three terminal tabs.

The setup script refuses to continue when another tagged lab session is still
connected.

## Phase 1: Reproduce the write stall

Run setup once:

```bash
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  -f labs/incident/00_setup.sql
```

In terminal A, start the ordinary index build. It pauses after the build while
the transaction still owns the lock:

```bash
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  -f labs/incident/10_unsafe_index.sql
```

In terminal B, run the reader and writer. The reader returns immediately and
the writer waits:

```bash
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  -f labs/incident/20_blocked_writer.sql
```

In terminal C, inspect and assert the wait chain:

```bash
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  -f labs/incident/30_observe_unsafe.sql
```

The observer must report:

- `ShareLock`, granted, for `workbench-lab-unsafe-index`;
- `RowExclusiveLock`, not granted, for
  `workbench-lab-blocked-writer`;
- `Lock:relation` for the writer;
- the index backend from `pg_blocking_pids(writer_pid)`; and
- a successful 25,000-row read.

The observer also writes the measured snapshot to
`data/generated/incident-lab/lock_capture.json`.

Return to terminal A and press Enter. Its `ROLLBACK` removes the ordinary index
and releases the writer in terminal B.

## Phase 2: Apply the safe pattern

In terminal A, hold one real writer transaction open:

```bash
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  -f labs/incident/40_safe_writer.sql
```

In terminal B, start the concurrent build:

```bash
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  -f labs/incident/50_concurrent_index.sql
```

In terminal C, prove the compatible lock modes and run a fresh write:

```bash
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  -f labs/incident/60_observe_safe.sql
```

The concurrent build can wait on the older writer's virtual transaction. That
is expected. The important result is directional: the index build waits for
safe points, while ordinary DML is not queued behind its relation lock.

Return to terminal A and press Enter. The writer commits and terminal B
finishes the concurrent build. Verify the valid index and final rows:

```bash
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  -f labs/incident/70_verify.sql
```

## Optional evidence admission

After the core application schema and corpus exist, the measured snapshot can
enter the canonical evidence admission boundary:

```bash
admission/admit.sh \
  --capture-dir data/generated/incident-lab
```

Admission queues the evidence for search-index projection. It does not call an
embedding model or make the new item semantically searchable synchronously.

## Cleanup

Run cleanup after admission or after inspection:

```bash
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  -f labs/incident/99_cleanup.sql
```

The capture JSON is retained so it can still be inspected or admitted.

## Realism boundary

Every DDL statement, DML statement, lock, wait event, PID, relation OID, and
catalog row is produced by the connected PostgreSQL engine. The ordinary build
is intentionally held after completion by its open transaction so the
`ShareLock` remains observable on fast workshop hardware. This proves lock
compatibility and the wait chain; it does not claim a production build
duration, throughput loss, or Aurora instance performance.
