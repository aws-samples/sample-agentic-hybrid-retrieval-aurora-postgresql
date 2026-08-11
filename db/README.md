# Mosaic data models for Aurora PostgreSQL

Version: **1.0.0**
Prepared for: **Mosaic — agentic product discovery with Aurora PostgreSQL**

This is the standalone schema and contract package for the Mosaic re:Invent builders' session. It is intentionally separate from the 500K catalog archive and the premium image bundles.

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
       agent compare/evidence tools
```

Product recommendations use **one product-level embedding**. Supporting claims live in `mosaic.product_evidence` and receive their own embeddings, so the agent can separately answer:

- Which products match the shopper's intent?
- What evidence supports the recommendation?

## Premium merchandising cohort

The package includes a concrete mapping for **120 premium products** selected from the physical 500K Mosaic catalog:

| Domain | Premium products |
|---|---:|
| Consumer electronics | 48 |
| Running and fitness | 36 |
| Home office and workspace | 36 |
| **Total** | **120** |

It also marks:

- **6 flagship products** with catalog and square detail assets
- **30 retrieval anchors** used by polished workshop queries and relevance judgments
- **10 Shop pages × 12 products** for a consistent laptop, tablet, and mobile merchandising model

See:

- `data/premium_cohort_120.csv`
- `data/premium_cohort_120.json`
- `data/premium_asset_queue_120.json`
- `docs/media-and-merchandising.md`

## Package structure

```text
mosaic-data-models-aurora-v1/
├── sql/                         Aurora PostgreSQL DDL, indexes, functions, labs
├── models/                      Pydantic, JSON Schema, and DBML contracts
├── data/                        120-product premium cohort and media queue
├── sample/                      Small synthetic data and eval examples
├── scripts/                     Render, validate, split/import, and export tools
├── config/                      Retrieval and model configuration
├── docs/                        Architecture, ERD, retrieval, media, agent, HNSW
├── tests/                       Offline contract/package tests
├── Makefile
└── SHA256SUMS
```

## Installation order

The default schema uses `vector(768)` to match the existing Mosaic catalog package. To use another embedding dimension, run the rendering helper before installation.

```bash
python scripts/render_dimension.py --dimension 1024 --output build/sql
```

For the included 768-dimensional version:

```bash
psql "$DATABASE_URL" -f sql/install.sql
```

After products are loaded and embeddings are populated, build the HNSW indexes separately:

```bash
psql "$DATABASE_URL" -f sql/08_indexes_concurrent.sql
```

`CREATE INDEX CONCURRENTLY` is intentionally outside `install.sql` because it cannot run inside a transaction block.

## Recommended load sequence

```text
1. Install extensions and schema
2. Load brands and taxonomy
3. Load products and current commerce state
4. Refresh mosaic_search.product_document
5. Generate product embeddings
6. Generate evidence embeddings
7. Build HNSW indexes
8. Load premium merchandising assignments/media mappings
9. Load eval queries and judgments
10. Capture the measured 500K benchmark baseline
```

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

The validator checks the 120-product distribution, 6 flagships, 30 retrieval anchors, 10 complete Shop pages, JSON contracts, SQL ordering, and unresolved placeholders.

## Scope boundary

This package contains the **data model and retrieval contracts**, not the 500K physical catalog or the premium image binaries. It is designed to plug into the previously generated Mosaic catalog bundle and the separate image asset folders.
