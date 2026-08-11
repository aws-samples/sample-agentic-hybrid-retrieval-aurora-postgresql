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
application. All 120 premium-cohort product photographs are installed.
Workshop Studio owns deployment automation; a fresh-stack rehearsal remains the
final environment gate. The measured Aurora performance baseline remains an
active build phase.

This repository ships nothing deliberately broken. Deliberate starter gaps live
in the separate Workshop Studio repository;
[`docs/intentional-gaps.md`](docs/intentional-gaps.md) records that boundary and
the defects fixed against it, so a fixed bug is not later reclassified as an
exercise.

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

## Runtime

Mosaic standardizes on Python 3.13; the checked-in `.python-version` is
`3.13.14`. `make` uses the repository virtual environment when it exists and
rejects other Python minor versions for application and MCP work.

## Baseline Validation

```bash
make setup
source .venv/bin/activate
make doctor

make validate
make ui-install
make ui-build
make ui-test
make ui-audit
```

The full Python gate includes five read-only integration tests against Aurora:

```bash
export DATABASE_URL='postgresql://USER:PASSWORD@YOUR-CLUSTER.cluster-xxxx.us-east-1.rds.amazonaws.com:5432/mosaic_catalog?sslmode=require'
make validate-missions
make validate-evals
make test
```

An unset `DATABASE_URL` is a release-gate failure, not a skipped integration
suite.

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

Runtime settings are range-checked when they are read, so a value the engine
cannot serve fails at startup with the parameter, the offending value, and the
violated bound named, rather than surfacing as an HTTP 500 on every query. Copy
`config/.env.example` to get values that validate.

## Database Baseline

**Aurora only.** There is no local database and no `make` target creates one; the
cluster snapshot is the only restore path. `ARTIFACTS.md` covers what is and is not
restorable, and how to connect from a corporate network — if `psql` hangs while the
port looks open, start with `sslmode=disable` to tell a TLS problem from a
firewall one.

```bash
export DATABASE_URL='postgresql://USER:PASSWORD@YOUR-CLUSTER.cluster-xxxx.us-east-1.rds.amazonaws.com:5432/mosaic_catalog?sslmode=require'
make db-install
make db-prepare-mosaic
make db-load-mosaic
make db-embed
make db-index-concurrent
make db-load-cohort
make db-smoke
```

`make db-prepare-mosaic` transforms the three checked-in domain shards into the
normalized catalog shape and renders the governed 120-product merchandising
cohort. The six Mosaic showcase products retain their approved identities and
assets; the rest of the catalog uses curated or category-appropriate local
media.

The SQL baseline owns full-text search, trigram matching, metadata filters,
pgvector retrieval, and RRF. The workshop indexing, query, and evaluation paths
all use Cohere Embed v4 (`us.cohere.embed-v4:0`) through Amazon Bedrock with
1,024-dimensional vectors. Hash embeddings require explicit development opt-in;
they are not workshop results and must not be used for semantic-quality claims.

The lexical arm OR-combines the query's lexemes and keeps the strict
`websearch_to_tsquery` match as a scoring bonus. An AND-only builder makes any
misspelled token unsatisfiable, which empties the arm on exactly the
conversational queries the workshop uses; the strict bonus is what keeps an
exact model-name query decisively first. Because `tsvector_to_array` discards
`NOT`, a negation in the query requires the strict match as well, so `-wireless`
is honored rather than inverted.

Lab 1 runs read-only against that tree:

```bash
make lab-01 DATABASE_URL="$DATABASE_URL"
```

### Reuse the real embedding load

After all 500,000 Cohere Embed v4 vectors are ready, export a reusable,
content-addressed cache:

```bash
make db-export-embeddings DATABASE_URL="$DATABASE_URL"
```

The ignored `build/embedding-cache/` directory contains resumable
10,000-product float32 NPZ shards and a SHA-256 manifest. Store that directory
under a private S3 prefix available to the Workshop Studio bootstrap role,
rather than Git. A fresh provision downloads the artifact and runs the complete
Mosaic bootstrap without invoking the embedding model:

```bash
make db-fetch-embeddings \
  EMBEDDING_CACHE_URI=s3://example-workshop-assets/mosaic/embedding-cache/
make db-bootstrap-cached \
  DATABASE_URL="$DATABASE_URL" \
  EMBEDDING_CACHE_MANIFEST=build/embedding-cache/manifest.json
```

Changed or missing products fail the import instead of silently receiving stale
vectors. Run the normal embedding job afterward only when the catalog or model
space intentionally changes. A manual Aurora cluster snapshot is the faster
same-account restore option because it also preserves the HNSW index. The S3
cache is the portable cross-account option for Workshop Studio account pools;
keep the snapshot private unless specific target accounts are approved for
restore access.

## Local Application

Start the API and React application in separate terminals:

```bash
export DATABASE_URL='postgresql://USER:PASSWORD@YOUR-CLUSTER.cluster-xxxx.us-east-1.rds.amazonaws.com:5432/mosaic_catalog?sslmode=require'
make api-serve
```

```bash
make ui-dev
```

Open `http://127.0.0.1:5173`. Set `API_PORT`, `UI_PORT`, or
`CATALOG_API_PROXY` when those defaults are already occupied.

Mosaic provides connected Discover, Catalog, Search, Product Detail, Mosaic
Labs, Retrieval Lab, and Performance surfaces. The source app owns the lab
contract
in [`data/evals/mosaic_labs_missions.json`](data/evals/mosaic_labs_missions.json):
three required labs, supporting retrieval checks, ground-truth product IDs,
hard filters, timings, and evaluation
assertions. The separate Workshop Studio repository owns participant guides,
deliberate starter gaps, and code-editor exercises. Search and agent results
come from the real API; the UI does not calculate retrieval scores or
substitute static products.

## MCP Portable Tool Contract

MCP interoperability is optional reference material rather than a required lab:
it needs a second process and an external MCP-compatible host, and its failure
mode is environmental. The capability ships fully supported without fragmenting
the `Retrieve -> Rank -> Reason` session path.

The adapter uses MCP Python SDK `2.0.0` and protocol revision `2026-07-28` to
make the same three typed, read-only retrieval tools portable to another
compatible agent host. The Strands runtime remains in its compatible
environment:

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
  media/    Cohort asset labels, per-batch import provenance, shot list
db/         Vendored schema package: the mosaic_* tree the application reads
  sql/      Schema, load, index, retrieval functions, and lab SQL
docs/       Architecture, curriculum, data, evaluation, and deployment notes
scripts/    Generation, loading, embedding, benchmark, and evaluation tools
mcp-server/ Isolated MCP 2.0 adapter over the canonical API
service/    FastAPI, Strands tools, retrieval orchestration, and model clients
tests/      Dataset and contract validation
ui/         React catalog, agent, evidence, retrieval, and performance surfaces
  public/assets/images/mosaic/   Runtime product photography, one file per
                                 cohort asset key (see data/media/)
```

The retrieval layer the API queries lives in `db/sql/`, under the `mosaic` and
`mosaic_search` schemas.

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

All 120 catalog images and all 6 flagship detail images are installed, so the
shot list is currently empty. Import a new batch with:

```bash
SOURCE=~/Downloads/batch make media-import
make media-shot-list
```

The importer refuses any filename that is not a cohort asset key, so a typo
fails loudly instead of leaving the folder out of step with its manifest. Every
batch records provenance in `data/media/import_batch_*.csv`, and each row's note
must state what was verified **in the picture**: an early batch recorded only
that the bytes arrived, and thirteen of its images turned out to show the wrong
product. Nine are replaced; `docs/media-regeneration-batches.md` carries the
generation prompt for the four still outstanding.

## Benchmarking Rule

The generated catalog is real source data. Output from
`scripts/benchmark_hnsw.py` is measured. Output from
`scripts/simulate_scale.py` is a labeled projection and must not be presented
as Aurora performance evidence.

## Technical References

- [pgvector](https://github.com/pgvector/pgvector)
- [PostgreSQL `pg_trgm`](https://www.postgresql.org/docs/current/pgtrgm.html)
- [Aurora PostgreSQL vector storage](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraPostgreSQL.VectorDB.html)
