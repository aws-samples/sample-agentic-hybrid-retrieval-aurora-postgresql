# Guided Live Incident

The core lab creates two additive, participant-generated evidence captures.
Neither capture reads a fixture, prior run, authored document, or precomputed
embedding.

```bash
make live-workshop
```

The default command runs Investigation Evidence. The CLI and generated
filenames retain internal identifiers `A` and `B` for compatibility:
Investigation Evidence is `A`, and Validation Evidence is `B`. The command
refuses to start unless the configured Aurora PostgreSQL writer has the current
core schema, an empty evidence store, and the preloaded workload of 5,000
customers and 3,000,000 orders. The real FastAPI service must be running with
the lab endpoints enabled and a ten-connection application pool. Bedrock
embedding access is required.
CloudWatch is collected as best-effort supplemental evidence; it does not gate
the incident capture. Performance Insights and Database Insights are not core
lab dependencies. The core path instead uses PostgreSQL catalogs for connected
blockers, pool statistics and request results for callers that never reached
PostgreSQL, and `EXPLAIN (ANALYZE, BUFFERS)` for the access path. Production
connectors can still admit additional observability sources.

## Investigation Evidence

Investigation Evidence is Lab 1's one live incident:

1. It adds the nullable `priority_tier` column and commits that DDL.
2. It runs one unbatched backfill in a separate open transaction.
3. It sends twelve hot writes through the real application pool. Ten requests
   enter PostgreSQL and wait on `Lock:transactionid`; at least two queue at the
   pool boundary and return `pool_timeout` without a PostgreSQL backend.
4. The controller waits for three consecutive samples proving both the pool and
   PostgreSQL conditions, then retains the measured state for the observation
   hold.
5. It commits the backfill, proves recovery, and captures the before- and
   after-`ANALYZE` sequential-scan checkpoints.
6. It atomically admits the normalized evidence, builds the derived search
   index with runtime Cohere embeddings, and writes an Investigation Evidence
   receipt.

The Investigation Evidence receipt includes the run-derived `INC-*`, unsafe `CHG-*`, ruled-out
`ANALYZE` `CHG-*`, and `LOCK-*` identifiers. It is the evidence available to
the retrieval and read-only agent labs. It does not contain a post-index plan.

## Validation Evidence

After the participant reviews and explicitly approves the Hybrid Retrieval
Agent's stored proposal, they execute that proposal's own DDL in Code Editor.
Then capture the new outcome:

```bash
make live-workshop ARGS="--wave B --proposal-id $PROPOSAL_ID --approved-by $APPROVED_BY"
```

Validation Evidence requires exactly one admitted Investigation Evidence capture and the participant-created
index described by the approved proposal. It reads the index definition from
Aurora's catalog, compares it with the proposal's canonical fingerprint, and
records the approval and observed execution before admission is attempted. It
then observes a fresh, bounded post-index `EXPLAIN (ANALYZE, BUFFERS)`
checkpoint, admits only the new validation change and telemetry, rebuilds the
derived search index, and writes a separate Validation Evidence receipt. The receipt is
attached to the already-recorded execution only after admission succeeds.

Validation Evidence adds a `validates` relationship to the same incident; it
never replaces or revises Investigation Evidence records. The agent recommends
but does not execute: it has no DDL privilege or write tool. A successful
readiness assessment records what the evidence supports; it never authorizes
autonomous DDL.

## Outputs and Cleanup

Generated files under `data/generated/incident-lab/` are gitignored:

- `wave-a-<suffix>.json`: Investigation Evidence admission payload;
- `receipt-a-<suffix>.json`: Investigation Evidence indexing and capture receipt;
- `wave-b-for-<wave-a-capture-id>.json`: Validation Evidence admission payload;
- `receipt-b-<suffix>.json`: Validation Evidence indexing and validation receipt; and
- `embeddings-<suffix>.jsonl`: runtime embedding cache for the matching capture.

`workbench_lab` remains available by default so Labs 2 through 4 can inspect
the same operational substrate. Use `--drop-lab-schema` only to reclaim the
disposable workload after a rehearsal or workshop is complete.

## Failure Rule

If PostgreSQL, application-pool, admission, indexing, or readiness validation
fails, the command does not publish a ready receipt. A failed Validation
Evidence leaves the already-admitted Investigation Evidence records intact. If
the participant's index is missing or does not match the approved proposal,
the execution is still recorded before Validation Evidence stops so the
mismatch can be reviewed and corrected.
