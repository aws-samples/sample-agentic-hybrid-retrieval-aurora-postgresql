# Search examples

## Typo-tolerant hybrid retrieval

```sql
BEGIN;
SELECT mosaic_search.configure_hnsw(100, 'relaxed_order', 20000, 2);

SELECT *
FROM mosaic_search.search_hybrid_rrf(
    'noice cancelng hedfones',
    :'query_embedding'::vector(1024),
    '{"domain":"consumer_electronics","max_price_cents":20000,"in_stock_only":true}'::jsonb,
    result_limit => 30
);
COMMIT;
```

## Evidence retrieval

```sql
SELECT *
FROM mosaic_search.search_product_evidence(
    1,
    'comfortable for a long flight while wearing glasses',
    :'query_embedding'::vector(1024),
    ARRAY['customer_review','expert_summary']::mosaic.evidence_type[],
    8,
    :rrf_k,
    :fts_limit,
    :semantic_limit
);
```

## Compare exact and HNSW

```sql
-- Exact baseline for recall calculation. Session settings, not SET LOCAL,
-- so they can be reset before the approximate run.
SET enable_indexscan = off;
SET enable_bitmapscan = off;
SELECT product_id
FROM mosaic_search.product_listing_view
WHERE embedding IS NOT NULL
ORDER BY embedding <=> :'query_embedding'::vector(1024)
LIMIT 10;
RESET enable_indexscan;
RESET enable_bitmapscan;

-- Approximate profile
SELECT mosaic_search.configure_hnsw(100, 'relaxed_order', 20000, 2);
SELECT product_id
FROM mosaic_search.product_listing_view
WHERE embedding IS NOT NULL
ORDER BY embedding <=> :'query_embedding'::vector(1024)
LIMIT 10;
```
