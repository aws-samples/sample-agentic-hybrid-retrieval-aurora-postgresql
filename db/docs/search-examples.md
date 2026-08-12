# Search examples

## Typo-tolerant hybrid retrieval

```sql
BEGIN;
SELECT mosaic_search.configure_hnsw(100, 'relaxed_order', 20000, 1);

SELECT *
FROM mosaic_search.search_hybrid_rrf(
    'wirless noice canceling hedphones under 200 with long batery life',
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
    ARRAY['verified_review','expert_summary']::mosaic.evidence_type[],
    8
);
```

## Compare exact and HNSW

```sql
-- Exact baseline for recall calculation
SET LOCAL enable_indexscan = off;
SELECT product_id
FROM mosaic_search.product_document
WHERE embedding IS NOT NULL
ORDER BY embedding <=> :'query_embedding'::vector(1024)
LIMIT 10;

-- Approximate profile
SELECT mosaic_search.configure_hnsw(100, 'relaxed_order', 20000, 1);
SELECT product_id
FROM mosaic_search.product_document
WHERE embedding IS NOT NULL
ORDER BY embedding <=> :'query_embedding'::vector(1024)
LIMIT 10;
```
