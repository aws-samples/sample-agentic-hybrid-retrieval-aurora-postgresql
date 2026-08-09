# Schema consolidation: one `mosaic` model

## Decision

**There will be one schema family: `mosaic`.** The existing `catalog.*` schema is
replaced, not kept alongside. Two schemas modelling the same products is the
confusion we are removing, and at L400 the audience will read the DDL — a
half-migrated database teaches the wrong thing.

## Why `catalog` existed, and why it goes

`catalog.*` was built for this repository before the standalone data-model
package existed. It is a single flat `catalog.product` table carrying identity,
copy, commerce state, business signals, and retrieval text in one row.

That shape is fine for a demo and wrong for the workshop's own argument. The
session teaches that retrieval representations are separate concerns — weighted
FTS, a trigram document, a semantic document that deliberately excludes volatile
price, and a rerank document that deliberately includes it. A single table with
one `search_text` column cannot demonstrate that distinction, because the
distinction does not exist in it.

`mosaic` models it directly:

```text
mosaic.product          identity and durable descriptive content
mosaic.product_offer    price, availability, inventory, rating  (volatile)
mosaic.product_evidence specs, reviews, Q&A, each independently embedded
        ↓ refresh
mosaic_search.product_document
        search_document   weighted tsvector          → FTS arm
        trigram_text      aliases and misspellings   → pg_trgm arm
        embedding         vector(1024)               → HNSW arm
        rerank_text       rich candidate document    → reranker
        typed columns     price_cents, availability  → hard filters
```

The teaching point becomes visible in the schema: `embedding_text` excludes
current price, so a price change does not require re-embedding, while
`rerank_text` includes it, so the reranker still sees it. That is a real
engineering decision the audience can inspect.

## Embedding dimension

**1024 everywhere.** The package ships `vector(768)` as its default and renders
other dimensions:

```bash
python scripts/render_dimension.py --dimension 1024 --output build/sql-1024
```

Verified: the renderer rewrites all six `vector(768)` sites correctly. Two things
to correct when vendoring:

- `config/retrieval.yaml` in the package states `dimensions: 768`. It must say
  1024 or it will mislead the next reader.
- The rendered 1024 SQL is what we check in, so nobody installs 768 by accident.

## What breaks in the application

Three differences are load-bearing, not cosmetic:

| Concern | `catalog` (now) | `mosaic` (target) | Blast radius |
|---|---|---|---|
| Price | `price_usd numeric(12,2)` | `price_cents bigint` | Every card, filter, the price slider, sort, agent tools |
| Availability | text `'In Stock'` | `mosaic.availability_status` enum `in_stock` | Filters, badges, `in_stock_only` |
| Commerce state | columns on `product` | separate `product_offer` | Every read path and the projection refresh |
| Retrieval reads | base table | `mosaic_search.product_document` | All four search functions |

Money as an integer count of cents is the correct call and worth stating out
loud: `numeric` is exact but invites float drift the moment it crosses into
JSON and JavaScript. `price_cents` cannot lose a penny in transit. The UI
formats at the edge.

## Sequence

Each stage leaves the repository working. No stage is a flag day.

1. **Vendor the package** into `db/` at 1024, with its contracts and docs, so
   `SCHEMA_PACKAGE` stops pointing at a Desktop folder.
2. **Install path**: one `make db-install` that runs the ordered SQL, then the
   concurrent index build separately (it cannot run in a transaction).
3. **Load path**: transform the 500K catalog into the normalized shape, load,
   refresh the projection, embed products and evidence, build HNSW, then load the
   120-product premium cohort and its media keys.
4. **Service layer** against `mosaic_search.product_document` and the new search
   functions, returning the package's `SearchResponse` contract.
5. **UI**: cents and enums at the boundary; the rest of the surfaces are already
   shaped correctly.
6. **Delete `catalog.*`** — SQL, service queries, and the local showcase seed's
   reason to exist — once the live path is green.

## Scope boundary

No live Aurora cluster has been connected to this work. The package was
statically and contract-tested. HNSW build time, execution plans, latency, QPS,
and Recall@10 are all unmeasured and must be captured on the real workshop
cluster before any of those numbers appear in a slide or a doc.
