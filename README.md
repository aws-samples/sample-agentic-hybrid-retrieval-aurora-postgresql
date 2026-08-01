# Hybrid Retrieval Workbench

**Agentic hybrid retrieval with Amazon Aurora PostgreSQL**

Hybrid Retrieval Workbench is the runnable reference application for DAT410 at
AWS re:Invent 2026.
It investigates one controlled database incident by retrieving normalized
incident, change, lock, support-case, and runbook evidence through Aurora
PostgreSQL. Every ranked candidate, agent stage, answer, and citation is
persisted for inspection.

> This repository contains synthetic workshop data. `INC-2047`, `CHG-1842`,
> the customer names, and the lock snapshots are controlled fixtures, not real
> AWS incidents, Support cases, or customer records.

## The Question

> Why did CHG-1842 block checkout writes during INC-2047, which visible
> customer was affected, and what was the safe fix?

The answer path is real:

1. Decompose identifiers and database filters.
2. Run lexical, semantic, and fuzzy retrieval with ACL and metadata filters.
3. Keep exact identifiers in a deterministic tier, then fuse full-text,
   semantic, and fuzzy rank positions with weighted reciprocal rank fusion
   (RRF).
4. Optionally rerank the fused candidate pool with Cohere Rerank v3.5.
5. Traverse authoritative incident relationships and compare sources.
6. Synthesize only from numbered evidence.
7. Persist source URI, revision, chunk, quote, and source context for each
   citation, then validate attribution against the exact stored chunk.

No frontend result, score, citation, or answer is hardcoded.

## Reproduce the Lock Mechanism

Before searching the historical evidence, participants can reproduce the
database behavior with real concurrent PostgreSQL sessions:

1. run ordinary `CREATE INDEX` and retain its granted `ShareLock`;
2. prove a read succeeds while an `UPDATE` waits for `RowExclusiveLock`;
3. resolve the queue by rolling back the ordinary build;
4. run `CREATE INDEX CONCURRENTLY` beside an open writer transaction; and
5. prove a fresh write succeeds while `ShareUpdateExclusiveLock` and
   `RowExclusiveLock` coexist.

The scripts, three-terminal runbook, measured assertions, capture artifact, and
cleanup are in [labs/incident](labs/incident/README.md). The exercise operates
only on the disposable `workbench_lab` schema. It does not mutate the
preloaded `casework`, `retrieval`, or `proof` data.

The ordinary build is held by an open transaction after it completes so the
lock remains observable on fast workshop hardware. This is a deterministic
proof of lock compatibility and the wait chain, not a production-duration or
throughput benchmark.

## Architecture

```text
Authoritative operational records
Workshop: casework.* synthetic fixture
Production: approved domain tables, exports, events, or connectors
                  |
                  | source revision + ACL + stable evidence ID
                  v
        retrieval.search_index_queue
                  |
                  v
Versioned retrieval.documents + retrieval.chunks
  B-tree exact/filter indexes | GIN FTS | GIN pg_trgm | HNSW pgvector
                  |
                  v
Canonical retrieval.* SQL functions
  exact ID tier + (full text + vector + fuzzy -> weighted RRF) -> model rerank
                  |
          +-------+--------+
          |                |
          v                v
  proof.* receipts     Agent tools / HTTP / MCP
          |                |
          +-------+--------+
                  v
       cited answer + replayable run_id
```

| Schema | Owns |
|---|---|
| `casework` | Normalized source-of-record fixture, relational constraints, and authoritative incident relationships |
| `retrieval` | Rebuildable document versions, chunks, embeddings, indexes, search functions, traversal, and search index health |
| `proof` | Retrieval runs, candidate signals, stages, answers, citations, judgments, and evaluation metrics |

The physical search index is intentional. Externally computed embeddings
do not belong in a materialized-view definition, and a search index needs
versioning, incremental replacement, tombstones, and historical references.
`casework.*` remains authoritative; `retrieval.*` is one-way derived state and
can be rebuilt and checked for drift.

See [architecture.md](docs/architecture.md) and
[data-model.md](docs/data-model.md) for the exact boundaries.
The consolidated [implementation specification](docs/implementation-spec.md)
records the complete application, workshop, validation, and release contract.
The [production workshop brief](DAT410-BUILD-BRIEF.md) governs release claims,
and [What DAT410 Builds](WORKSHOP-BUILD-SUMMARY.md) summarizes the participant
exercises and take-home artifacts.

The required session path is incident diagnosis through hybrid retrieval,
fusion and reranking, evidence-bound agent tools, cited synthesis, and
diagnostics and replay. It runs with the default App Engineer persona and does
not require persona switching. Row-level security and `pg_columnmask` are an
optional appendix comparison: rerun one query as App Engineer, Auditor, and DBA
to compare absent, masked, and unmasked restricted evidence. That appendix is
not a participant prerequisite or a default release gate.

Labs 2 and 3 use the editable requests and deterministic checkpoints in
[`labs/exercises`](labs/exercises/README.md). Participants scope a distractor,
change fusion weights, implement the RRF expression against a temporary
receipt table, build a relationship plan, and verify the resulting receipts
without modifying the reference retrieval engine.

## Implemented Retrieval

| Capability | Implementation |
|---|---|
| Exact identifiers | B-tree lookup plus boundary-aware matching for IDs such as `CHG-1842` |
| Full text | Separate document and chunk `tsvector` streams with GIN indexes |
| Semantic | `vector(1024)`, cosine distance, and a partial HNSW index |
| Fuzzy | `pg_trgm` over identifiers and titles; default threshold `0.3` |
| Filters | Kind, cluster, incident, account, severity, environment, and time range |
| Authorization | `retrieval.acl_visible` inside every retrieval arm and relationship hop |
| Fusion | Deterministic exact-ID tier above weighted RRF with defaults text `2`, vector `1`, fuzzy `1`, `k=60` |
| Reranking | Cohere Rerank v3.5 after SQL fusion; its score is not a probability |
| Attribution | Persisted source URI, revision, document version, chunk version, quote, and claim |
| Diagnostics | Arm scores and positions, HNSW controls, plans, index usage, stages, and latency |
| Evaluation | Recall, precision, MRR, nDCG, and separate traversal recall/precision |

Ranking exists once, in `sql/03_search_functions.sql`. The API, agent tools,
Lambda adapter, MCP server, and frontend consume that implementation.

## Model Configuration

The July 2026 workshop configuration uses:

| Role | Configurable ID | Transport |
|---|---|---|
| Embeddings | `us.cohere.embed-v4:0` | Bedrock Runtime `InvokeModel`, US CRIS |
| Reranking | `cohere.rerank-v3-5:0` | Bedrock Agent Runtime `rerank` |
| Answer synthesis | `global.anthropic.claude-sonnet-5` | Bedrock Runtime `Converse`, Global CRIS |

The synthesis path does not claim Mantle and CRIS simultaneously. The validated
path uses Global CRIS through Converse; model IDs and transport are configuration,
not application constants. Re-run `make doctor` and review model lifecycle and
regional support before packaging the event environment.

Stored documents use Cohere's `search_document` input type and live queries use
`search_query`. Stored and query vectors must use the same model and dimensions.
The deterministic hash provider is only an offline test substitute and is not a
semantic-quality claim.

## Prerequisites

- Python 3.13+
- Node.js 20.19+
- PostgreSQL 18.3+ with `vector` 0.8.1+, `pg_trgm`, and
  `pg_stat_statements`
- For the workshop path, Aurora PostgreSQL and AWS credentials in `us-east-1`
- Bedrock access to the configured embedding, reranking, and synthesis models

This repository owns application source. The sibling Workshop Studio repository
owns Aurora, VPC, IAM, Code Editor, AgentCore Gateway, and source packaging.

## Run Locally

Point `DATABASE_URL` at a disposable compatible PostgreSQL database. The seed
command resets workshop tables, so do not use a production database.

```bash
make install
cp .env.example .env

# For an offline local corpus, set these in .env:
# EMBED_PROVIDER=hash
# COHERE_RERANK_ENABLED=0

make schema
make seed-local
DOCTOR_SKIP_BEDROCK=1 make doctor
```

Start the API:

```bash
make api
```

Start the frontend in another terminal:

```bash
cd frontend
npm install
npm run dev
```

The default URLs are:

- API: `http://127.0.0.1:8000`
- OpenAPI: `http://127.0.0.1:8000/docs`
- Frontend: `http://127.0.0.1:5173`

For the Workshop Studio environment:

```bash
make aurora-local-env
make aurora-verify
make doctor
```

`make aurora-local-env` writes ignored backend and frontend environment files
from CloudFormation outputs and Secrets Manager. If its network check cannot
reach the cluster, run the commands from Code Editor inside the workshop VPC.

## Try the Evidence Path

Hybrid retrieval:

```bash
curl -sS http://127.0.0.1:8000/v1/search \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "Why did CHG-1842 block writes on checkout-prod-cluster-01?",
    "cluster_id": "checkout-prod-cluster-01",
    "rerank": false,
    "limit": 8
  }'
```

Cited agent answer:

```bash
curl -sS http://127.0.0.1:8000/v1/agent/answer \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "Why did CHG-1842 block checkout writes during INC-2047, which visible customer was affected, and what was the safe fix?",
    "limit": 8
  }'
```

Use the returned `run_id` to inspect persisted proof:

```bash
curl -sS http://127.0.0.1:8000/v1/runs/RUN_ID
curl -sS http://127.0.0.1:8000/v1/runs/RUN_ID/candidates
curl -sS http://127.0.0.1:8000/v1/runs/RUN_ID/timeline
curl -sS http://127.0.0.1:8000/v1/runs/RUN_ID/graph
```

## Validate

```bash
make doctor
make smoke
make test
cd frontend && npm run build
git diff --check
```

Database integration tests require a disposable database and an explicit reset
guard:

```bash
TEST_DATABASE_URL='postgresql://localhost:55432/workbench_test?sslmode=disable' \
ALLOW_TEST_DATABASE_RESET=1 \
make test
```

`setUpClass` TRUNCATEs every `casework`, `retrieval`, and `proof` table, so the
suite refuses to start unless the database name ends in `_test` and the
application resolves the same URL the tests were handed. Never point
`TEST_DATABASE_URL` at the workshop corpus.

The optional persona appendix has two additional validation limits.
`pg_columnmask` is Aurora-managed, so `sql/12_masking.sql` is skipped locally and
`ColumnMaskingTests` reports as skipped; the run prints both. Also, `FORCE ROW
LEVEL SECURITY` does not subject a superuser, so a local cluster whose owner is
a superuser exercises the policies only through the persona roles, never
through the owner. When publishing the appendix, run the same suite against a
disposable database on the Aurora cluster to cover both. These checks are not
prerequisites for the core retrieval path.

Local PostgreSQL proves PostgreSQL behavior; it does not prove Aurora network,
parameter-group, extension, or engine-version behavior. To run the same suite on
the real cluster, create a second database beside the workshop one and apply the
schema to it:

```bash
psql "$DATABASE_URL" -c 'CREATE DATABASE workbench_test'
DATABASE_URL="${DATABASE_URL%/*}/workbench_test" make schema
TEST_DATABASE_URL="${DATABASE_URL%/*}/workbench_test" \
ALLOW_TEST_DATABASE_RESET=1 \
make test
```

Run the final smoke test on the Workshop Studio-provisioned Aurora cluster
before release.

## Package the Workshop Studio Release

Participant stacks do not clone this repository. CFN downloads one zip from the
Workshop Studio assets bucket, unpacks it into the participant's home folder,
and seeds Aurora from the dump inside it. Build that zip from a committed
revision:

```bash
# 1. Seed a disposable database and dump it (see seed/README.md).
DATABASE_URL=postgresql://.../workbench_seed_test \
ALLOW_SEED_DUMP=1 \
  make seed-dump

# 2. Package the committed tree plus that dump.
make source-archive
```

`scripts/build_source_archive.sh` refuses a dirty worktree, requires the dump's
`.revision` to match `HEAD`, verifies its `.sha256`, confirms the dump actually
carries `casework`, `retrieval`, and `proof`, and fails if any path the guide
tells participants to run is missing. It stamps the revision into the zip
comment. Upload the result as `hybrid-retrieval-source.zip` and record the
revision in the sibling repository's `assets/README.md`.

## Repository Layout

```text
backend/app/     FastAPI, search index, retrieval, rerank, tools, and synthesis
backend/tests/   Unit and disposable-database contract tests
sql/             Schema, indexes, search, diagnostics, receipts, and evaluation
seed/            Deterministic synthetic database-incident corpus
labs/incident/   Participant-run lock incident, observation, fix, and cleanup
labs/exercises/  Editable retrieval and agent requests plus checkpoints
frontend/        Incident-evidence inspection workbench
lambda_mcp/      Stateless AgentCore Gateway Lambda adapter
mcp-server/      Optional stdio MCP wrapper over the same HTTP API
scripts/         Workshop environment, release packaging, and boundary helpers
docs/            Architecture, data contract, security, and session flow
```

## Production Boundary

Use the search index only for approved evidence that must be ranked,
joined, cited, evaluated, and replayed with predictable latency. Federate to an
existing search service when copying content is unnecessary or disallowed.
Revalidate volatile or permission-sensitive facts in the authoritative system
before taking an action.

Aurora is the search and proof engine in this design. It is not a replacement
for operational workflow, current authorization, or mutation APIs.

## Security

See [SECURITY_REVIEW.md](SECURITY_REVIEW.md). The repository commits no
credentials or customer data, makes no automatic frontend network calls beyond
the configured API, and fails closed when required evidence is unavailable.

## License

This project is licensed under the MIT-0 License. See [LICENSE](LICENSE).
