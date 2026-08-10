\set ON_ERROR_STOP on

-- DEPRECATED: the `catalog.*` tree. The application does not read this schema;
-- `service/retrieval.py` queries `mosaic` and `mosaic_search` (see db/sql/).
-- Deleted by Phase 2 Unit E. See docs/rewrite-losses.md for what the rewrite
-- dropped and docs/superpowers/specs/ for the Phase 2 design.
-- Do not add features here. Do not point a lab at it.

-- Assumes product.embedding is populated and product_embedding_hnsw_cosine_idx exists.
-- Use scripts/benchmark_hnsw.py for repeatable p50/p95 and recall@k measurements.

-- Inspect index size and table size.
SELECT
    pg_size_pretty(pg_relation_size('catalog.product_embedding_hnsw_cosine_idx')) AS hnsw_index_size,
    pg_size_pretty(pg_total_relation_size('catalog.product')) AS product_total_size;

-- Runtime accuracy/latency control.
SET hnsw.ef_search = 64;
SET hnsw.iterative_scan = strict_order;

-- Replace with a real query vector.
\set query_vector '''[0,0,0]'''
-- The example above is intentionally not executable against vector(1024); use the benchmark harness.

-- Filter-selectivity lab setup.
SELECT domain, category, subcategory, count(*) AS rows,
       round(100.0 * count(*) / sum(count(*)) OVER (), 3) AS pct_of_catalog
FROM catalog.product
GROUP BY domain, category, subcategory
ORDER BY rows DESC;

-- Compare strict and relaxed iterative scans for filtered ANN retrieval.
-- SET LOCAL hnsw.iterative_scan = off;
-- SET hnsw.iterative_scan = strict_order;
-- SET LOCAL hnsw.iterative_scan = relaxed_order;

-- Candidate partial index pattern for a highly reused domain predicate.
-- CREATE INDEX CONCURRENTLY product_ce_embedding_hnsw_idx
-- ON catalog.product USING hnsw (embedding vector_cosine_ops)
-- WITH (m=16, ef_construction=200)
-- WHERE domain = 'consumer_electronics' AND embedding IS NOT NULL;

-- Partitioning is an alternate experiment when tenant/domain isolation is structural.
