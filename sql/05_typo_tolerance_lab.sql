\set ON_ERROR_STOP on

-- Module: typo tolerance with pg_trgm.
-- Start with a visibly misspelled query that FTS alone may not recover.
\set typo_query 'noice canceling hedphones'

SELECT product_id, title,
       ts_rank_cd(search_document, websearch_to_tsquery('english', :'typo_query')) AS fts_score
FROM catalog.product
WHERE search_document @@ websearch_to_tsquery('english', :'typo_query')
ORDER BY fts_score DESC
LIMIT 10;

-- Inspect canonical trigram recovery. It combines whole-identity similarity
-- for model/SKU queries with indexed token-level word similarity for prose.
SELECT result.product_id, product.title, product.brand, product.model,
       result.trigram_score, result.trigram_rank
FROM catalog.search_trigram(:'typo_query', '{}'::jsonb, 20, 0.24) AS result
JOIN catalog.product AS product USING (product_id)
ORDER BY result.trigram_rank;

-- Explain the indexed token-recovery access path.
EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
SELECT product_id, title
FROM catalog.product
WHERE 'hedphones' <% trigram_text
ORDER BY word_similarity('hedphones', trigram_text) DESC
LIMIT 20;

-- Score-threshold experiment: precision generally rises as the accepted score
-- increases. The indexed operator first bounds the candidate set.
SELECT threshold,
       (SELECT count(*)
        FROM catalog.product p
        WHERE 'hedphones' <% p.trigram_text
          AND word_similarity('hedphones', p.trigram_text) >= threshold) AS matches
FROM unnest(ARRAY[0.60, 0.65, 0.70, 0.80, 0.90, 1.00]::real[]) AS threshold;
