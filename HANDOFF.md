# Handoff

Current DAT410 release contract as of August 2, 2026.

## Repositories

| Repository | Branch | Publication boundary |
|---|---|---|
| `sample-agentic-hybrid-retrieval-aurora-postgresql` | `main` | source commit and push may use Shayon's configured GitHub credentials |
| `build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql` | `mainline` | stage only; the user commits and publishes Workshop Studio |

Freeze and push source first. Build the schema-only Workshop Studio archive
from that exact source commit, then update its three `SourceRevision` fields.

## Standing Evidence Rule

The participant database starts with schema and zero evidence. The sole
participant ingestion path is:

```text
make live-workshop
  -> induce ordinary CREATE INDEX write stall
  -> sample PostgreSQL telemetry
  -> collect CloudWatch and Database Insights observations
  -> apply and measure CREATE INDEX CONCURRENTLY repair
  -> project measured rows into searchable documents
  -> generate Cohere embeddings through Bedrock
  -> publish a run-specific indexing receipt
```

No fixture, authored record, dump, prior capture, JSON snapshot, offline
embedding, canned answer, customer, support case, runbook, postmortem, or
distractor may enter retrieval, agent tools, citations, evaluation, or proof.
The Overview main graphic is the only illustrative exception and is never data.

Identifiers are capture-derived:

```text
INC-<run-suffix>
CHG-<run-suffix>-01
CHG-<run-suffix>-02
LOCK-<run-suffix>-01
TEL-<run-suffix>-...
```

## Verified Live Run

Aurora capture `6949b1ef-03b7-41e7-8def-3518478fd535`
(`run_suffix=478FD535`) produced:

- 110 documents and chunks;
- 110 ready Cohere Embed 4 embeddings;
- 735 preserved raw telemetry rows;
- exact, full-text, semantic, fuzzy, filter, fusion, traversal, citation, and
  replay proof;
- Bedrock synthesis with supporting run
  `86ef82a0-db1a-4381-a4ef-064723c898af`.

The full smoke path and all live contracts passed on the isolated database
`dat410_live_20260802_205751_test`.

## Database Hazard

The ignored `.env` still targets the old `retrieval` database, which contains
legacy authored evidence. Never apply schema, run tests, or run the orchestrator
there.

For the validated live database, replace `/retrieval?` in the DSN with:

```text
/dat410_live_20260802_205751_test?
```

Always inline-prefix `DATABASE_URL` on database-writing commands and verify
`current_database()` first. Resettable tests require a database name ending in
`_test` plus `ALLOW_TEST_DATABASE_RESET=1`.

## Release Validation

Before publishing:

```bash
make doctor
make smoke
make test
gates/checks.sh
cd frontend && npm run build
git diff --check
```

Also inspect the source archive and fail if it contains `seed/`,
`data/generated/`, a dump, capture JSON, embedding cache, database file, or
proof receipt. Workshop Studio bootstrap must end at `awaiting_incident` with
zero evidence.

Do not commit generated live exports, credentials, local databases, logs,
`node_modules`, `.claude/settings.local.json`, `?/`, or `mockups/`.
