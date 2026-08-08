# Build agentic hybrid retrieval with Amazon Aurora PostgreSQL

This repository is being rebuilt as a hands-on agentic hybrid-retrieval
workshop for Amazon Aurora PostgreSQL. Participants build lexical,
typo-tolerant, semantic, filtered, fused, reranked, and inspectable product
retrieval using PostgreSQL full-text search, `pg_trgm`, pgvector/HNSW, and
reciprocal-rank fusion. They then expose that retrieval through typed agent
tools for decomposition, evidence gathering, comparison, ranking explanation,
and cited synthesis.

The complete session abstract is in
[`docs/session-abstract.md`](docs/session-abstract.md).

The current baseline contains the corrected catalog, evaluation assets, SQL
retrieval layer, typed API, Cohere Embed v4 and Cohere Rerank integrations, the
Strands agent harness, an isolated MCP 2.0 adapter, and a responsive React
application. Deployment automation and a measured Aurora performance baseline
remain active build phases.

## Canonical Dataset

The catalog contains 500,000 synthetic products:

| Domain | Products | Retrieval value |
|---|---:|---|
| Consumer electronics | 210,000 | model/SKU precision, compatibility, specifications, and lexical ambiguity |
| Running and fitness | 160,000 | semantic intent, nuanced attributes, and hard negatives |
| Home office and workspace | 130,000 | ergonomic intent, dimensions, compatibility, and selective filters |

The full catalog is checked in as three domain shards:

```text
data/full/products_consumer_electronics.csv.gz
data/full/products_running_fitness.csv.gz
data/full/products_home_office.csv.gz
```

Every shard is below GitHub's 100 MB per-file limit. The manifest preserves
their load order and the quality report preserves each shard's SHA-256 digest.

## Baseline Validation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r config/requirements.txt

make validate
make test
make ui-install
make ui-build
make ui-test
make ui-audit
```

Regenerate the canonical dataset and its quality report with:

```bash
make generate
```

The validation contract rejects:

- an update timestamp earlier than its product launch date;
- a malformed or duplicate SKU;
- an unsupported evaluation filter;
- an evaluation target that does not satisfy its own filters;
- a catalog shard at or above GitHub's 100 MB file limit;
- a shard whose digest differs from the recorded quality report.

## Database Baseline

```bash
export DATABASE_URL='postgresql://postgres:postgres@localhost:5432/catalog_workshop'
make db-init
make db-load
make db-index
```

`make db-load` loads both the three catalog shards and the governed 500K
product-media mapping. The six Mosaic showcase products retain their approved
Mosaic identities and assets; the rest of the catalog uses curated or
category-appropriate local media.

The SQL baseline owns full-text search, trigram matching, metadata filters,
pgvector retrieval, and RRF. The workshop indexing, query, and evaluation paths
all use Cohere Embed v4 (`us.cohere.embed-v4:0`) through Amazon Bedrock with
1,024-dimensional vectors. Hash embeddings require explicit development opt-in;
they are not workshop results and must not be used for semantic-quality claims.

## Local Application

Start the API and React application in separate terminals:

```bash
export DATABASE_URL='postgresql://postgres:postgres@localhost:5432/catalog_workshop'
make api-serve
```

```bash
make ui-dev
```

Open `http://127.0.0.1:5173`. Set `API_PORT`, `UI_PORT`, or
`CATALOG_API_PROXY` when those defaults are already occupied.

Catalog Studio provides six connected routes: Discover, Catalog, Search &
Agent, Product Detail, Retrieval Lab, and HNSW Performance Tuning. Search and
agent results come from the real API; the UI does not calculate retrieval
scores or substitute static products.

## MCP Interoperability

Lab 3 includes a short MCP checkpoint over the canonical API. The adapter uses
MCP Python SDK `2.0.0` and protocol revision `2026-07-28`, while the Strands
runtime remains in its compatible environment:

```bash
make mcp-install
make mcp-test
make mcp-serve
```

Connect an MCP-compatible host to `http://127.0.0.1:8001/mcp`. The adapter
exposes typed, read-only product search, product evidence, and retrieval-run
inspection tools. See
[`docs/mcp-interoperability.md`](docs/mcp-interoperability.md).

## Repository Map

```text
config/     Workshop and runtime configuration
data/       Full catalog shards, samples, dictionaries, and evaluation assets
docs/       Architecture, curriculum, data, evaluation, and deployment notes
infra/      Local PostgreSQL/pgvector development support
scripts/    Generation, loading, embedding, benchmark, and evaluation tools
mcp-server/ Isolated MCP 2.0 adapter over the canonical API
service/    FastAPI, Strands tools, retrieval orchestration, and model clients
sql/        Schema, load, index, retrieval, and lab SQL
tests/      Dataset and contract validation
ui/         React catalog, agent, evidence, retrieval, and performance surfaces
```

## Benchmarking Rule

The generated catalog is real source data. Output from
`scripts/benchmark_hnsw.py` is measured. Output from
`scripts/simulate_scale.py` is a labeled projection and must not be presented
as Aurora performance evidence.

## Technical References

- [pgvector](https://github.com/pgvector/pgvector)
- [PostgreSQL `pg_trgm`](https://www.postgresql.org/docs/current/pgtrgm.html)
- [Aurora PostgreSQL vector storage](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraPostgreSQL.VectorDB.html)
