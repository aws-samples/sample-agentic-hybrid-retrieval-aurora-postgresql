# Guided Live Incident

This lab has one participant entrypoint:

```bash
make live-workshop
```

It creates no prewritten records and reads no capture fixture. The command
refuses to start unless it can prove that:

- `DATABASE_URL` reaches the requested Aurora PostgreSQL writer;
- the database contains the current application schema and no evidence rows;
- the preloaded workload contains 5,000 customers, 3,000,000 canonical related
  orders, and no target incident index;
- Performance Insights is enabled;
- CloudWatch, Performance Insights, and Bedrock are reachable; and
- `EMBED_PROVIDER=bedrock` uses the configured Cohere embedding model.

Workshop bootstrap runs `make prepare-workload` before the participant arrives.
That command creates only the disposable operational tables and preserves the
empty evidence store. Source-only local use runs the same command explicitly.

## Visible Checkpoints

The orchestrator prints eight checkpoints:

1. preflight AWS, Aurora, schema, and Cohere access;
2. induce a roughly 60-second stall with one ordinary `CREATE INDEX`, six
   blocked writers, and two active readers;
3. apply `CREATE INDEX CONCURRENTLY`, run fresh DML, and verify `pg_index`;
4. collect incident-window CloudWatch metrics and Performance Insights wait and
   SQL observations;
5. build run-scoped searchable evidence from measured data;
6. admit the complete run atomically into `casework`;
7. batch-generate Cohere embeddings through Bedrock; and
8. verify and publish the indexing receipt that enables participant retrieval.

The participant command verifies and reuses 5,000 preloaded customers and
3,000,000 related orders as workload substrate. The unsafe phase then captures 30
observations at two-second intervals. Each observation preserves nine
`pg_stat_activity` rows, nine relation-lock rows, and six
`pg_blocking_pids` rows. With statement, CloudWatch, and Performance Insights
observations, a successful run retains about 735 raw telemetry rows.

The deterministic evidence build creates about 105 telemetry documents plus one
incident, two changes, and one primary lock observation. The search index
therefore contains about 110 participant-generated documents and 100-250
chunks.
This is useful workshop scale for exact, full-text, semantic, fuzzy, fusion,
reranking, citations, and replay. It is not presented as an HNSW performance
benchmark.

The 5,000 customer rows and 3,000,000 order rows never enter the evidence corpus
and are removed with `workbench_lab`. Their measured effects survive as
normalized telemetry, searchable evidence, and proof.

## Run-Derived Identity

Each execution creates one UUID capture ID. Its final eight hexadecimal
characters become the run suffix:

```text
INC-<suffix>
CHG-<suffix>-01
CHG-<suffix>-02
LOCK-<suffix>-01
TEL-<suffix>-...
```

The receipt, evidence source URIs, raw telemetry foreign keys, searchable
documents, chunks, and embeddings all trace to that capture. A fresh database
is required so evidence from different runs cannot mix.

## Outputs

Generated files are written under `data/generated/incident-lab/` and are
gitignored:

- `live-run-<suffix>.json`: complete measured admission payload;
- `embeddings-<suffix>.jsonl`: runtime embedding cache for that run;
- `indexing-receipt-<suffix>.json`: provenance and readiness receipt; and
- `exercises/`: requests rendered with this run's identifiers.

Retrieval should not begin until the command prints `RETRIEVAL READY` with the
receipt path. The disposable `workbench_lab` schema is removed after successful
verification unless `--keep-lab-schema` is passed directly to the orchestrator.

## Failure Rule

No failure path substitutes local, fixture, demo, or previously captured data.
If PostgreSQL telemetry, AWS observations, admission, embeddings, or readiness
validation fails, no retrieval-ready receipt is published.
