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
| Products | 500,000 | `database.product_count` |
| Product embeddings | 500,000 | `database.embedded_product_count` |
| Embedding shape | Cohere Embed v4, 1,024 dimensions | `database.embedding_dimensions`, `database.embedding_model_ids` |

The schema also installs `pg_trgm`, `unaccent`, and `pgcrypto`
(`db/sql/00_extensions.sql`).

## What the pipeline uses

**Three retrieval arms in one database.** `mosaic_search.search_fts` reads a
generated `tsvector` column through a GIN index.
`mosaic_search.search_trigram` reads `pg_trgm` normalized text through a GIN
`gin_trgm_ops` index. `mosaic_search.search_vector` reads an HNSW index built
with `vector_cosine_ops`, `m = 16`, and `ef_construction = 200`. Each arm
applies the same eligibility predicates before its own limit, and
`mosaic_search.search_hybrid_rrf` fuses their positions. The definitions are in
`db/sql/09_search_functions.sql`, the indexes in `db/sql/07_indexes.sql` and
`db/sql/08_indexes_concurrent.sql`.

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
planner can inline, so its HNSW index does appear. The per-arm index names on
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
premium cohort and evidence coverage counts, any missing or invalid retrieval
index among the three named above, any missing retrieval function, and whether
the exact-neighbour ground truth used by the Vector index at scale lens has
been seeded. The endpoint reports `ready` only when the database, the model
space, and Bedrock credentials all pass; otherwise it reports `blocked` with
the failing field visible.

## What is not claimed

No version-to-version performance claim is made here, and none may be added
until it is measured. Nobody has run this corpus on an earlier PostgreSQL major
version with the same instance class, the same indexes, and the same retrieval
profile, so there is no basis for saying this pipeline is faster on 18 than on
17, and this page will not imply it. The measured claims the workshop does
stand behind are the retrieval scorecard and the Vector index at scale
artifact, each served with its own provenance.

Release-note features of PostgreSQL 18 that this pipeline does not exercise are
out of scope for this page on purpose. If you want to demonstrate one, measure
it on this corpus first, then write down what you measured.
