# Mosaic data models for Aurora PostgreSQL

Version: **1.0.0**
Prepared for: **Mosaic — agentic product discovery with Aurora PostgreSQL**

This is the standalone schema and contract package for the Mosaic re:Invent builders' session. The real products and saved vectors ship separately in the hash-pinned catalog bundle.

## What this package models

Mosaic uses two complementary shapes:

1. **Normalized catalog source of truth** — products, brands, taxonomy, commerce state, media, merchandising, and evidence.
2. **Denormalized retrieval projection** — one row per product containing weighted full-text fields, a trigram document, semantic text, rerank text, common filter columns, and one product embedding.

This gives the workshop a clean teaching story without forcing every retrieval query through a large join graph:

```text
Catalog source of truth
        ↓ refresh/upsert
Product retrieval projection
        ├── PostgreSQL FTS
        ├── pg_trgm typo recovery
        ├── pgvector HNSW semantic retrieval
        └── SQL/JSONB metadata filters
                ↓
             RRF fusion
                ↓
          external reranker
                ↓
    exact catalog-SKU preservation
                ↓
       agent compare/evidence tools
```

Product recommendations use **one product-level embedding**. Every active
product has an authoritative specification row in `mosaic.product_evidence`;
review evidence is available where sourced. Evidence retrieval ranks those rows
against the question with FTS and uses the product vector only for the
authoritative product-spec row, so the agent can separately answer:

- Which products match the shopper's intent?
- What evidence supports the recommendation?

## Package structure

```text
mosaic-data-models-aurora-v1/
├── sql/                         Aurora PostgreSQL DDL, indexes, functions, labs
├── models/                      Pydantic, JSON Schema, and DBML contracts
├── scripts/                     Render, validate, split/import, and export tools
├── config/                      Retrieval and model configuration
├── docs/                        Architecture, ERD, retrieval, media, agent, HNSW
├── tests/                       Offline contract/package tests
├── Makefile
└── SHA256SUMS
```

## Installation order

File numbers follow install order. `sql/install.sql` runs:

| Files | What they create |
|---|---|
| `00`–`07` | Extensions, schemas and types, reference data, catalog, media, evidence, the retrieval projection and its indexes |
| `08_search_channels.sql` | Shared filters, HNSW settings, and full-text, close-spelling and vector search |
| `../../labs/lab2_rank/rrf_contribution.sql` | Lab 2's exercise: each channel's reciprocal rank fusion contribution |
| `../../labs/lab1_retrieve/hybrid_search.sql` | Lab 1's exercise: hybrid search over the three channels |
| `09_weighted_fusion.sql`, `10_evidence_search.sql` | Weighted fusion for comparison, and evidence search for citations |
| `11`–`14` | Query coverage, agent audit, telemetry and the tool contract registry |

Later steps run separately, in number order: `15` and `16` build the HNSW
indexes once embeddings exist, and `install_measurement.sql`
adds the evaluation and benchmark tables in `20`–`22`. `98` and `99` are the
bootstrap acceptance and smoke checks.

The checked-in schema uses `vector(1024)` for the pinned Cohere Embed v4
catalog. To use another embedding model and dimension, render a separate SQL
tree and regenerate the embeddings; never relabel vectors from another space.

```bash
uv run python scripts/render_dimension.py --dimension 1536 --output build/render
psql "$DATABASE_URL" -f build/render/db/sql/install.sql
```

The output keeps the repository layout, `db/sql/` and `labs/`, because
`install.sql` includes the two lab SQL files from `labs/`.

For the included 1024-dimensional version:

```bash
psql "$DATABASE_URL" -f sql/install.sql
```

After products are loaded and embeddings are populated, build the HNSW indexes separately:

```bash
psql "$DATABASE_URL" -f sql/15_indexes_concurrent.sql
```

`CREATE INDEX CONCURRENTLY` is intentionally outside `install.sql` because it cannot run inside a transaction block.

## Real-catalog restore

Run `make db-bootstrap-schema` from the source root against a fresh Aurora
cluster, then restore using `scripts/catalog/real_catalog_cache.py` and select
`MOSAIC_CATALOG_DATASET`. The archive includes saved embeddings; no synthetic
products or generated reviews are loaded. Run `make db-verify-bootstrap` to
verify the real-only population. See [ARTIFACTS.md](../ARTIFACTS.md).

## Core tables

| Table | Purpose |
|---|---|
| `mosaic.product` | Stable product identity and descriptive content |
| `mosaic.product_offer` | Current price, availability, rating, inventory, and business signals |
| `mosaic.media_asset` | Physical image object metadata and crop/mark zones |
| `mosaic.product_media` | Product-to-image roles such as catalog/detail/lifestyle |
| `mosaic.merchandising_assignment` | Premium tier, Shop pagination, flagship, and retrieval-anchor flags |
| `mosaic.product_evidence` | Specs, reviews, Q&A, expert summaries, and evidence embeddings |
| `mosaic_search.product_document` | Denormalized FTS/trigram/vector/filter projection |
| `mosaic.search_event` | End-to-end query telemetry |
| `mosaic.agent_tool_event` | Agent tool-call audit/provenance |
| `mosaic_eval.*` | Queries, judgments, runs, results, and metrics |
| `mosaic_bench.*` | HNSW profiles, benchmark runs, and measurements |

## Retrieval representations

Do not overload one field for every retrieval stage.

| Representation | Job |
|---|---|
| `search_document` | Weighted FTS for exact product language, model names, and features |
| `trigram_text` | Typo tolerance for brands, models, aliases, and product terms |
| `embedding_text` | Stable semantic product document; excludes volatile price/inventory |
| `embedding` | HNSW candidate retrieval |
| `rerank_text` | Rich candidate document, including decisive filters and commerce context |
| typed columns / JSONB | Hard eligibility constraints and facets |

## Validate the package

```bash
python scripts/validate_package.py
python -m unittest discover -s tests -v
```

The validator checks JSON contracts, SQL ordering and unresolved placeholders.

## Scope boundary

The shared schema contracts support the real catalog and the workshop labs.
Synthetic catalog fixtures and their loading tools have been retired.
