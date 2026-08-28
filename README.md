# Build agentic hybrid retrieval with Amazon Aurora PostgreSQL

[![Project CI](https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql/actions/workflows/ci.yml)
[![CodeQL](https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql/actions/workflows/github-code-scanning/codeql)
[![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Node.js 22](https://img.shields.io/badge/Node.js-22-5FA04E?logo=nodedotjs&logoColor=white)](https://nodejs.org/)
[![PostgreSQL 18](https://img.shields.io/badge/PostgreSQL-18-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=20232A)](https://react.dev/)
[![License: MIT-0](https://img.shields.io/badge/License-MIT--0-2EA44F.svg)](LICENSE)

Mosaic is a production-shaped product discovery application and hands-on
builder session for agentic hybrid retrieval on Amazon Aurora PostgreSQL. It
combines PostgreSQL full-text search, `pg_trgm`, pgvector HNSW, hard relational
filters, reciprocal-rank fusion, managed reranking, source-addressable evidence,
and bounded agent tools in one inspectable retrieval system.

The session thesis is simple: **retrieval correctness is a pipeline property,
not a top-1 result**. Each required lab breaks composition while the underlying
components remain healthy: candidate recall in Retrieve, contribution arithmetic
in Rank, and evidence authorization in Reason.

The reference application includes a responsive React storefront, a typed
FastAPI service, a Strands agent with citation-bounded synthesis, an optional
MCP 2.0 adapter, a 500,000-product synthetic catalog, and deterministic release
gates. The complete session framing is in
[the session abstract](docs/session-abstract.md).

![Mosaic Discover page with product discovery and natural-language search](docs/images/mosaic-discover.webp)

> [!IMPORTANT]
> **Aurora only.** This project has no local database path. Every database
> command must receive a `DATABASE_URL` for the intended Aurora PostgreSQL
> cluster. See [ARTIFACTS.md](ARTIFACTS.md) before running any `db-*`, lab,
> evaluation, or API target.

**Jump to:** [Quick start](#quick-start) | [Architecture](#architecture) |
[Workshop path](#workshop-path) | [Validation](#validation) |
[Repository map](#repository-map)

## Quick start

Prerequisites:

- Python `3.13` and [`uv`](https://docs.astral.sh/uv/);
- Node.js `22` and npm, matching the workshop host, which installs the
  versioned `nodejs22 nodejs22-npm` pair and asserts `v22`
  (`deploy/mosaic-bootstrap.sh:98`, `:109`);
- PostgreSQL client tools;
- AWS credentials for Amazon Bedrock in `us-east-1`;
- an Aurora PostgreSQL `DATABASE_URL` for the Mosaic catalog.

Install the locked dependencies and create the runtime environment:

```bash
make setup
make ui-install
cp config/.env.example .env
```

Edit `.env`, then start the API:

```bash
set -a
source .env
set +a
make api-serve
```

Start the React application in a second terminal:

```bash
make ui-dev
```

Open `http://127.0.0.1:5173`. The API defaults to
`http://127.0.0.1:8000`. Override `UI_PORT`, `API_PORT`, or
`CATALOG_API_PROXY` when those ports are occupied.

Useful runtime probes:

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/readiness
```

`/api/readiness` validates the live schema, product and embedding counts,
premium cohort, evidence coverage, required retrieval indexes and functions,
model-space compatibility, and AWS credential availability.

If `DATABASE_URL` contains `&`, keep it single-quoted when sourcing the file.
Corporate-network TLS and security-group diagnostics are documented in
[ARTIFACTS.md](ARTIFACTS.md).

## What Mosaic demonstrates

| Capability | Implementation | Inspectable proof |
|---|---|---|
| Exact and lexical retrieval | PostgreSQL weighted FTS with strict-query preservation | FTS rank, source URI, and persisted retrieval event |
| Typo recovery | `pg_trgm` candidate generation | Trigram similarity and rank contribution |
| Semantic retrieval | Cohere Embed v4 with pgvector HNSW | Vector distance, HNSW settings, and model identity |
| Product eligibility | SQL columns and JSONB predicates applied before fusion | Applied filters and production `matches_filters` checks |
| Candidate fusion | Unweighted reciprocal-rank fusion | Per-arm ranks, contributions, and pre-rerank order |
| Final ordering | Cohere Rerank 3.5 through Amazon Bedrock | Rerank score, final rank, and exact-identity preservation |
| Grounded recommendations | Strands tools over product and evidence records | Tool trace, retrieval IDs, evidence IDs, and numbered citations |
| Production diagnosis | Persisted events and on-demand `EXPLAIN (ANALYZE, BUFFERS, SETTINGS)` | Query plan, indexes, runtime settings, and Aurora identity |

The visible application surfaces are:

- **Discover** - editorial product discovery and direct search;
- **Shop** - hybrid search, filters, sorting, product detail, and Ask Mosaic;
- **Retrieval Observatory** - read-only inspection of retrieval, ranking, and
  evidence, with HNSW-at-scale and Studio alongside it.

Search and agent results always come from the API. The UI does not recreate
retrieval scores or silently substitute fixture products when Aurora, Bedrock,
reranking, evidence, or synthesis is unavailable.

## Architecture

```mermaid
flowchart LR
    U[Buyer or builder] --> UI[React: Discover, Shop, Retrieval Observatory]
    UI --> API[FastAPI retrieval and agent API]
    H[MCP-compatible host] --> MCP[MCP 2.0 adapter]
    MCP --> API

    API --> Q[Query and filter contract]
    Q --> FTS[PostgreSQL FTS]
    Q --> TRI[pg_trgm]
    Q --> EMB[Cohere Embed v4]
    EMB --> HNSW[pgvector HNSW]
    Q --> FIL[SQL and JSONB filters]

    FTS --> RRF[Reciprocal-rank fusion]
    TRI --> RRF
    HNSW --> RRF
    FIL --> RRF
    RRF --> RR[Cohere Rerank 3.5]
    RR --> EV[Product evidence]
    EV --> AG[Strands agent tools]
    AG --> SYN[Citation-bounded synthesis]
    SYN --> UI

    RRF --> AUDIT[(Aurora retrieval events)]
    RR --> AUDIT
    AG --> AUDIT
```

Aurora is both the search engine and the context system: canonical product
metadata, FTS documents, trigram-normalized text, structured attributes,
embeddings, HNSW indexes, evidence, retrieval events, judgments, and benchmark
records remain in one transactionally consistent data plane.

See [the architecture reference](docs/architecture.md) and
[the API contract](docs/api-contract.md) for the complete runtime boundaries.

## Workshop path

The 60-minute session follows one system through three required labs:

```text
RETRIEVE -> RANK -> REASON
```

| Lab | Time | Participant outcome |
|---|---:|---|
| **1. Build hybrid retrieval** | 10 min | Prove the right eligible candidates entered the pool, then reconnect one missing candidate arm |
| **2. Fuse, rerank, and inspect** | 10 min | Repair `1 / (k + rank)` and prove why a correct final answer can hide incorrect fusion |
| **3. Build the retrieval agent** | 15 min | Attach evidence identity to application-owned synthesis state and prove every citation resolves |

The checked-in source is the solved reference implementation. Deliberate
starter states are injected by `scripts/lab_state.py`; a failure already present
in the repository is a defect, not an exercise. The single source for lab
timings, queries, targets, assertions, and checkpoints is
[`data/evals/mosaic_labs_missions.json`](data/evals/mosaic_labs_missions.json).

Read [the curriculum](docs/retrieval-curriculum.md) and
[the intentional-gap contract](docs/intentional-gaps.md) before changing a lab
seam.

The companion Workshop Studio project owns participant instructions,
provisioning-time gap injection, deployment automation, and the clean-account
rehearsal. Repository checks prove the source contract; they do not replace
fresh-stack deployment and projector rehearsal.

## Release baseline

The Aurora release contract verifies:

| Property | Baseline |
|---|---:|
| Aurora PostgreSQL | 18.x |
| pgvector | 0.8+ |
| Products | 500,000 |
| Product embeddings | 500,000 |
| Embedding model | `us.cohere.embed-v4:0` |
| Embedding dimensions | 1,024 |
| Rerank model | `cohere.rerank-v3-5:0` |
| Agent and synthesis model | `global.anthropic.claude-sonnet-4-6` |
| Premium visual cohort | 120 products |
| Photographed Shop edit | 200 products |
| Product specification coverage | 500,000 products |
| Generated review evidence | 15,000 records |
| Filter-contract cases | 720 |
| Canonical scorecard | 20 product retrieval cases plus 1 agent contract case |

The catalog is synthetic and represents no real products, reviews, or customer
testimony. It spans three domains:

| Domain | Products | Retrieval emphasis |
|---|---:|---|
| Consumer electronics | 210,000 | model and SKU precision, compatibility, specifications, lexical ambiguity |
| Running and fitness | 160,000 | semantic intent, nuanced attributes, hard negatives |
| Home office and workspace | 130,000 | ergonomic intent, dimensions, compatibility, selective filters |

The three compressed catalog shards are checked into `data/full/`; their load
order, size limits, and SHA-256 digests are enforced by the dataset contract.
Real Cohere embeddings are not stored in Git. Workshop Studio restores them
from a pinned, content-addressed cache into a fresh encrypted Aurora cluster.
Hash embeddings require explicit development opt-in and cannot support workshop
relevance claims.

## Validation

### Offline contracts

These checks do not make Aurora or Bedrock readiness claims:

```bash
make setup
make lint
make validate
make validate-db
make validate-config
uv run python scripts/mission_contract.py --shape-only
PYTHONPATH=. uv run pytest -q

make mcp-install
make mcp-test

make ui-install
make ui-test
make ui-build
make ui-audit
```

### Aurora-backed release gates

With `DATABASE_URL` pointing at the intended Aurora cluster:

The full Python gate includes 9 read-only integration tests against Aurora.

```bash
MISSION_GATE_REQUIRE_DB=1 make validate-missions
make validate-evals
FUNCTION_CENSUS_REQUIRE_DB=1 make validate-functions
make db-verify-bootstrap
make test
make score-evals
```

`make validate-evals` proves the 720 target/filter contracts through the
production `mosaic_search.matches_filters` function. `make score-evals` runs
the served retrieval path over the canonical scorecard and verifies source,
dataset, retrieval-profile, model, Aurora, ranked-result, and metric provenance.
It is a release gate, not a general benchmark command.

These assets answer different questions:

- golden lab anchors ask whether critical behavior regressed;
- the 20 product-retrieval cases measure retrieval quality;
- the 720 generated fixtures test whether filters violated their contract.

Only `scripts/benchmark_hnsw.py` records measured Aurora performance.
`scripts/simulate_scale.py` produces a labeled projection and must not be
presented as benchmark evidence.

See [READINESS.md](READINESS.md) and
[the evaluation plan](docs/evaluation-plan.md) before accepting or publishing a
new scorecard.

## Continuous integration and security

[`Project CI`](.github/workflows/ci.yml) runs the offline Python, configuration,
schema-package, MCP, UI, build, and dependency-audit gates on pull requests and
pushes to `main`.

The manually dispatched **Aurora release contracts** job runs only on a
networked self-hosted runner labeled `mosaic-aurora`. It requires:

- `MOSAIC_AURORA_DATABASE_URL`;
- `MOSAIC_AURORA_CI_ROLE_ARN`;
- OIDC access to the configured AWS role in `us-east-1`.

That job runs the live mission, evaluation, function-census, bootstrap,
integration-test, and canonical-scorecard gates against Aurora. A missing
database or AWS role fails closed.

GitHub CodeQL default setup scans Python and JavaScript/TypeScript. Actions are
pinned to full commit SHAs, workflow permissions are minimal, and dependency
auditing is part of the UI gate.

## Aurora bootstrap and recovery

The portable Workshop Studio path imports the checked-in catalog and a verified
embedding cache:

```bash
make db-fetch-embeddings \
  EMBEDDING_CACHE_URI=s3://example-workshop-assets/mosaic/embedding-cache/

make db-bootstrap-cached \
  DATABASE_URL="$DATABASE_URL" \
  EMBEDDING_CACHE_MANIFEST=build/embedding-cache/manifest.json
```

The cache contains resumable float32 NPZ shards and a SHA-256 manifest.
Changed, missing, or model-incompatible products fail import instead of silently
receiving stale vectors. A cluster snapshot remains the fast same-account
operator recovery path; the cache is the portable cross-account path.

The supplied infrastructure is intentionally workshop-shaped. A production
deployment must choose its own high-availability, backup, deletion-protection,
authentication, connection-pooling, monitoring, and retention policies.

The complete restore policy and the non-recoverable predecessor history are in
[ARTIFACTS.md](ARTIFACTS.md).

## Optional MCP contract

MCP interoperability is supported reference material rather than a fourth
required lab. The isolated MCP 2.0 environment exposes typed, read-only product
search, product evidence, and retrieval-run inspection tools over the same API:

```bash
make mcp-install
make mcp-test
make mcp-serve
```

Connect a compatible host to `http://127.0.0.1:8001/mcp`. The agent and MCP
surfaces are projections of
[`db/config/agent_tool_contracts.json`](db/config/agent_tool_contracts.json);
they do not maintain independent retrieval schemas.

See [the MCP interoperability guide](docs/mcp-interoperability.md).

## Sources of truth

Do not duplicate these contracts:

| Contract | Source |
|---|---|
| Candidate limits, fusion `k`, weights, trigram threshold | [`db/config/retrieval.yaml`](db/config/retrieval.yaml) |
| Lab queries, checkpoints, timings, targets, assertions | [`data/evals/mosaic_labs_missions.json`](data/evals/mosaic_labs_missions.json) |
| Assertion vocabulary and falsifiers | [`service/assertions.py`](service/assertions.py) |
| Agent and MCP tool schemas | [`db/config/agent_tool_contracts.json`](db/config/agent_tool_contracts.json) |
| Dataset load order and domain counts | [`data/full/manifest.json`](data/full/manifest.json) |
| Product-bound media contract | [`data/media/asset_labels_200.json`](data/media/asset_labels_200.json) |

Repository gates reject duplicate retrieval constants, configuration drift,
missing falsifiers, malformed mission contracts, stale SQL defaults, and
multiple live signatures for retrieval functions.

## Repository map

```text
config/       Runtime configuration and environment example
data/         Catalog shards, dictionaries, evaluations, and media manifests
db/           Aurora schemas, loaders, indexes, retrieval functions, and labs
deploy/       Source-owned Code Editor bootstrap and delivery contract
docs/         Architecture, curriculum, evaluation, operations, and UI contracts
mcp-server/   Isolated MCP 2.0 adapter
scripts/      Data, embedding, validation, scorecard, and benchmark tooling
service/      FastAPI, retrieval orchestration, Strands tools, and model clients
tests/        Dataset, SQL, API, provenance, and release-contract tests
ui/           React storefront, Ask Mosaic, and the Retrieval Observatory
```

Start with:

- [Documentation map](docs/index.md)
- [Architecture](docs/architecture.md)
- [API contract](docs/api-contract.md)
- [Retrieval curriculum](docs/retrieval-curriculum.md)
- [Evaluation plan](docs/evaluation-plan.md)
- [House standards](docs/house-standards.md)
- [Production-readiness checklist](docs/production-readiness.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Amazon Open Source Code of Conduct](CODE_OF_CONDUCT.md). Report security issues
through the process described in the contributing guide, not through a public
issue.

## License

This project is licensed under the [MIT No Attribution License](LICENSE).
