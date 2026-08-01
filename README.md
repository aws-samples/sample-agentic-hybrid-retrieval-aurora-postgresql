# Hybrid Retrieval Workbench

**Agentic hybrid retrieval with Amazon Aurora PostgreSQL**

<p align="center">
  <a href="https://aws.amazon.com/rds/aurora/"><img alt="Amazon Aurora PostgreSQL 18.3+" src="https://img.shields.io/badge/Amazon_Aurora-PostgreSQL_18.3%2B-527FFF?style=flat-square"></a>
  <a href="https://github.com/pgvector/pgvector"><img alt="pgvector 0.8.1+" src="https://img.shields.io/badge/pgvector-0.8.1%2B-336791?style=flat-square&logo=postgresql&logoColor=white"></a>
  <a href="https://www.python.org/"><img alt="Python 3.13+" src="https://img.shields.io/badge/Python-3.13%2B-3776AB?style=flat-square&logo=python&logoColor=white"></a>
  <a href="https://nodejs.org/"><img alt="Node.js 20.19+" src="https://img.shields.io/badge/Node.js-20.19%2B-339933?style=flat-square&logo=nodedotjs&logoColor=white"></a>
  <a href="LICENSE"><img alt="License: MIT-0" src="https://img.shields.io/badge/License-MIT--0-2EA44F?style=flat-square"></a>
</p>

Hybrid Retrieval Workbench is the runnable DAT410 reference application for
AWS re:Invent 2026. It investigates one controlled database incident:

> Why did CHG-1842 block checkout writes during INC-2047, which visible
> customer was affected, and what was the safe fix?

Aurora PostgreSQL performs exact, full-text, semantic, and fuzzy retrieval,
weighted RRF, relationship reads, citation validation, and replayable proof.
Every candidate, agent stage, answer, and citation is persisted; no result or
score is hardcoded in the frontend.

> All incidents, customer names, and lock snapshots are synthetic workshop
> fixtures, not real AWS incidents, Support cases, or customer records.

## Incident Lab

[`labs/incident`](labs/incident/README.md) uses three real PostgreSQL sessions
to show ordinary `CREATE INDEX` blocking writers while reads continue, then
proves `CREATE INDEX CONCURRENTLY` permits fresh DML. It modifies only the
disposable `workbench_lab` schema.

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

`casework.*` remains authoritative; the versioned `retrieval.*` index is
one-way derived, rebuildable state. See [architecture.md](docs/architecture.md),
[data-model.md](docs/data-model.md), and the
[implementation specification](docs/implementation-spec.md) for the full
contract.

The one-hour core path uses the App Engineer persona. RLS and `pg_columnmask`
persona comparisons are optional. [`labs/exercises`](labs/exercises/README.md)
contains the bounded filter, RRF, traversal, and comparison exercises.

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

The current workshop configuration uses:

| Role | Configurable ID | Transport |
|---|---|---|
| Embeddings | `us.cohere.embed-v4:0` | Bedrock Runtime `InvokeModel`, US CRIS |
| Reranking | `cohere.rerank-v3-5:0` | Bedrock Agent Runtime `rerank` |
| Answer synthesis | `global.anthropic.claude-sonnet-5` | Bedrock Runtime `Converse`, Global CRIS |

The validated synthesis path uses Global CRIS through Converse. Stored documents
use Cohere `search_document`, queries use `search_query`, and both must share one
model space. The hash provider is an offline test substitute, not a
semantic-quality claim. Re-run `make doctor` before packaging an event.

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
(cd frontend && npm ci)
cp .env.example .env

# For an offline local corpus, set these in .env:
# EMBED_PROVIDER=hash
# COHERE_RERANK_ENABLED=0

make schema
make seed-local
DOCTOR_SKIP_BEDROCK=1 make doctor
```

Start the services in separate terminals:

```bash
make api
make frontend
```

The default URLs are:

- API: `http://127.0.0.1:8000`
- OpenAPI: `http://127.0.0.1:8000/docs`
- Frontend: `http://127.0.0.1:5173`

For Workshop Studio:

```bash
make aurora-local-env
make aurora-verify
make doctor
```

Run these from Code Editor when the cluster is reachable only inside the
workshop VPC.

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
gates/checks.sh G-11 G-14 G-17 G-23
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

The suite truncates `casework`, `retrieval`, and `proof`, so it requires both
the `_test` suffix and reset guard. Never point it at the workshop corpus.

Optional persona validation uses `make security-schema` and
`make security-checks` on an isolated database. `pg_columnmask`, owner-side RLS,
and final smoke validation must run on disposable target Aurora infrastructure;
local PostgreSQL does not cover those boundaries.

## Package the Workshop Studio Release

Participant stacks consume a frozen Workshop Studio zip rather than cloning the
repository. Build it only from a committed revision:

```bash
# 1. Seed a disposable database and dump it (see seed/README.md).
DATABASE_URL=postgresql://.../workbench_seed_test \
ALLOW_SEED_DUMP=1 \
  make seed-dump

# 2. Package the committed tree plus that dump.
make source-archive
```

The producer rejects dirty trees, revision/checksum drift, missing dump schemas,
and missing participant paths. See [seed/README.md](seed/README.md), then record
the zip revision in the sibling repository's `assets/README.md`.

## Repository Layout

```text
backend/app/     FastAPI, search index, retrieval, rerank, tools, and synthesis
backend/tests/   Unit and disposable-database contract tests
admission/       Evidence-admission CLI over the authoritative database contract
agent/           Managed tool registry and generated adapter source
gates/           Static, retrieval, and optional security release gates
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
