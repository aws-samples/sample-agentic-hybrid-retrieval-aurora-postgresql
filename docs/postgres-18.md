# What this pipeline runs on

Version facts for the database behind the workshop, and the limits of what
those facts prove. This page answers "what does PostgreSQL 18 give you here"
with things that are visible in a run, and refuses the version comparison
nobody has measured.

## The cluster

| Fact | Value | Where it is reported |
|---|---|---|
| Engine | Aurora PostgreSQL 18.3 | `GET /api/readiness`, `database.server_version` |
| Vector extension | pgvector 0.8.1 | `GET /api/readiness`, `database.vector_version` |
| Products | 553,911 | `database.product_count` |
| Product embeddings | 553,911 | `database.embedded_product_count` |
| Embedding shape | Cohere Embed v4, 1,024 dimensions | `database.embedding_dimensions`, `database.embedding_model_ids` |

The schema also installs `pg_trgm`, `unaccent`, and `pgcrypto`
(`db/sql/00_extensions.sql`).

## What the pipeline uses

**Three retrieval arms in one database.** `mosaic_live_search.search_fts` reads a
generated `tsvector` column through a GIN index.
`mosaic_live_search.search_trigram` reads `pg_trgm` normalized text through a GIN
`gin_trgm_ops` index. `mosaic_live_search.search_vector` reads an HNSW index built
with `vector_cosine_ops`, `m = 16`, and `ef_construction = 200`. Each arm
applies the same eligibility predicates before its own limit, and
`mosaic_live_search.search_hybrid_rrf` fuses their positions. The live functions
are rendered by
`scripts/prepare_live_catalog.py` from `db/sql/09_search_functions.sql`; the
real search table and its indexes are installed by
`scripts/prepare_staged_catalog_search.py`. Historical `mosaic_search` functions
remain separate from this serving projection.

**Iterative index scans.** pgvector 0.8 added them, and filtered vector
retrieval here depends on them. `mosaic_search.configure_hnsw` sets
`hnsw.iterative_scan`, `hnsw.ef_search`, `hnsw.max_scan_tuples`, and
`hnsw.scan_mem_multiplier` for the transaction from the served retrieval
profile; the shipped values are `relaxed_order`, 100, 20,000, and 2, all owned
by `db/config/retrieval.yaml`. That file records why the memory multiplier is 2
and not 1: on a filter anti-correlated with the query neighbourhood, the vector
arm returned between 42 and 150 of the 150 candidates it asked for across eight
anchors, and fusion then combined the short pool as though it were complete.
`db/sql/00_extensions.sql` raises a warning at install time if the extension
predates 0.8.0.

**Plan receipts, on demand.** The route
`POST /api/retrieval/events/{search_event_id}/plan` replays that persisted
event's exact fusion call after applying `mosaic_search.configure_hnsw`, then
stores `EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON)` in the event's
`plan_json` column with the capture time in its diagnostics. It is explicit and on demand
because `ANALYZE` executes the query, so a plan exists for the events somebody
asked about, not for every search. Read that plan carefully: the full-text and
trigram arms are `plpgsql` functions, so they appear as opaque function scans
with no index named inside them, while the vector arm is a `sql` function the
planner can inline, so its HNSW index does appear, provided the outer
`search_hybrid_rrf` stays inlinable too (SQL-language, one `SELECT`, not
`STRICT`, not `VOLATILE`, no `SET` clause); otherwise the whole call collapses
to one opaque function scan. The per-arm index names on
the Playground's channel list and their validity in readiness are the
authority, not the plan text.

**Generated columns and JSONB filters.** The full-text and evidence documents
are stored generated columns, and eligibility filters run against indexed
`jsonb` attributes and ordinary btree columns in the same statement as vector
distance. This is the point the workshop keeps making: relational filters and
approximate vector search sit in one transactionally consistent data plane.

## What readiness reports

`GET /api/readiness` reads the connected cluster and returns the database name,
the server version string, the pgvector extension version, product and embedded
product counts, embedding dimensions and stored embedding model ids, the
real-catalog receipt and evidence coverage, any missing or invalid retrieval
index among the three named above, any missing retrieval function, and optional
exact-neighbour ground truth. Historical benchmark state does not establish
readiness of the real-catalog performance instrument. The endpoint reports
`ready` only when the database, the model
space, and Bedrock credentials all pass; otherwise it reports `blocked` with
the failing field visible.

## What is not claimed

No version-to-version performance claim is made here, and none may be added
until it is measured. Nobody has run this corpus on an earlier PostgreSQL major
version with the same instance class, the same indexes, and the same retrieval
profile, so there is no basis for saying this pipeline is faster on 18 than on
17, and this page will not imply it. Stored scorecards and HNSW
measurements retain their original catalog and source provenance; historical
results do not certify the current real catalog. The
[fresh-account record](evidence/fresh-account-2026-09-26.md) reports deployment
measurements with their own scope and limitations.

Release-note features of PostgreSQL 18 that this pipeline does not exercise are
out of scope for this page on purpose. If you want to demonstrate one, measure
it on this corpus first, then write down what you measured.
