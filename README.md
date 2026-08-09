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

## Local Runtime

Mosaic standardizes on Python 3.13; the checked-in `.python-version` is
`3.13.14`. `make` uses the repository virtual environment when it exists and
rejects other Python minor versions for application and MCP work.

## Baseline Validation

```bash
make setup
source .venv/bin/activate
make doctor

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

Mosaic provides connected Discover, Shop, Collections, Product Detail, Mosaic
Labs, and HNSW Performance surfaces. The source app owns the mission contract
in [`data/evals/mosaic_labs_missions.json`](data/evals/mosaic_labs_missions.json):
golden queries, ground-truth product IDs, hard filters, and evaluation
assertions. The separate Workshop Studio repository owns participant guides,
deliberate starter gaps, and code-editor exercises. Search and agent results
come from the real API; the UI does not calculate retrieval scores or
substitute static products.

## MCP Portable Tool Contract

Lab 3 includes an instructor-led MCP checkpoint over the canonical API. The
adapter uses MCP Python SDK `2.0.0` and protocol revision `2026-07-28` to make
the same three typed, read-only retrieval tools portable to another compatible
agent host. The Strands runtime remains in its compatible environment:

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
  media/    Premium-cohort asset labels and the outstanding shot list
docs/       Architecture, curriculum, data, evaluation, and deployment notes
infra/      Local PostgreSQL/pgvector development support
scripts/    Generation, loading, embedding, benchmark, and evaluation tools
mcp-server/ Isolated MCP 2.0 adapter over the canonical API
service/    FastAPI, Strands tools, retrieval orchestration, and model clients
sql/        Schema, load, index, retrieval, and lab SQL
tests/      Dataset and contract validation
ui/         React catalog, agent, evidence, retrieval, and performance surfaces
  public/assets/images/mosaic/   Runtime product photography, one file per
                                 cohort asset key (see data/media/)
```

Product photography is named by cohort asset key, not by ad-hoc slug:

```text
<domain>-<subcategory>-<discriminator>-<role>.webp

ce-over-ear-headphones-auraluxe-h9-catalog-3x2.webp
rf-road-running-shoes-01-catalog-3x2.webp
ho-ultrawide-monitors-atelier-32-detail-1x1.webp
```

`make media-labels` regenerates `data/media/asset_labels_120.json` from the
schema package's cohort file, and `make media-shot-list` reports which images
are still missing. See `docs/media-shot-list.md`.

## Benchmarking Rule

The generated catalog is real source data. Output from
`scripts/benchmark_hnsw.py` is measured. Output from
`scripts/simulate_scale.py` is a labeled projection and must not be presented
as Aurora performance evidence.

## Technical References

- [pgvector](https://github.com/pgvector/pgvector)
- [PostgreSQL `pg_trgm`](https://www.postgresql.org/docs/current/pgtrgm.html)
- [Aurora PostgreSQL vector storage](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraPostgreSQL.VectorDB.html)
