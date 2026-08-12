\set ON_ERROR_STOP on

-- Lab 1: lexical precision and typo tolerance, against the tree the API reads.
--
-- Every query here runs on `mosaic_search`, the schema `service/retrieval.py`
-- queries. The `catalog.*` tree this lab used to target is not read by the
-- application, so a participant tuning it was tuning nothing.
--
-- Run with:
--     psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/sql/lab_01_typo_tolerance.sql

\echo ''
\echo '== Lab 1: find what the user typed, even when they typed it badly =='

\set typo_query 'noice canceling hedphones'

-- Step 1. The lexical arm on a misspelled query.
--
-- `search_fts` OR-combines the lexemes and keeps the strict
-- `websearch_to_tsquery` match as a scoring bonus, so a misspelled token no
-- longer makes the whole conjunction unsatisfiable. Compare the two directly:
-- the strict query is what an AND-only builder would have used, and on this
-- input it matches nothing.
\echo ''
\echo '-- 1a. strict AND-only tsquery: what the arm used to build'
SELECT count(*) AS strict_matches
FROM mosaic_search.product_document
WHERE search_document @@ websearch_to_tsquery('english', :'typo_query');

\echo ''
\echo '-- 1b. the shipped lexical arm on the same query'
SELECT result.product_id,
       document.title,
       result.fts_score,
       result.fts_rank
FROM mosaic_search.search_fts(:'typo_query', '{}'::jsonb, 10) AS result
JOIN mosaic_search.product_document AS document USING (product_id)
ORDER BY result.fts_rank;

-- Step 2. Trigram recovery.
--
-- `search_trigram` combines whole-identity similarity for model and SKU queries
-- with indexed token-level word similarity for prose. The live default minimum
-- score is 0.20; pass it explicitly so the lab reflects shipped behavior rather
-- than a number chosen for the lab.
\echo ''
\echo '-- 2. trigram recovery of the misspelled tokens'
SELECT result.product_id,
       document.title,
       document.brand_name,
       document.model_name,
       result.trigram_score,
       result.trigram_rank
FROM mosaic_search.search_trigram(:'typo_query', '{}'::jsonb, 20, 0.20) AS result
JOIN mosaic_search.product_document AS document USING (product_id)
ORDER BY result.trigram_rank;

-- Step 3. Prove the recovery path is indexed.
--
-- `<%` is word similarity and is served by `product_document_trigram_gin_idx`.
-- Look for a bitmap index scan on that index in the plan below: if this were a
-- sequential scan, the arm would not survive the full catalog.
\echo ''
\echo '-- 3. EXPLAIN the indexed word-similarity access path'
EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
SELECT product_id, title
FROM mosaic_search.product_document
WHERE 'hedphones' <% trigram_text
ORDER BY word_similarity('hedphones', trigram_text) DESC
LIMIT 20;

-- Step 4. Threshold sweep.
--
-- Precision generally rises as the accepted score increases. Two things to keep
-- straight, or the wrong conclusion follows:
--
--   * This sweep measures the SCORING function `word_similarity()`. It does not
--     move the index gate.
--   * The gate is `pg_trgm.word_similarity_threshold`, which
--     `make db-configure-retrieval` pins at database scope from
--     `db/config/retrieval.yaml`. That setting is unchanged by everything
--     below; `<%` here still admits candidates before the score filter runs.
\echo ''
\echo '-- 4. threshold sweep over the scoring function, not the index gate'
SELECT threshold,
       (SELECT count(*)
        FROM mosaic_search.product_document d
        WHERE 'hedphones' <% d.trigram_text
          AND word_similarity('hedphones', d.trigram_text) >= threshold) AS matches
FROM unnest(ARRAY[0.60, 0.65, 0.70, 0.80, 0.90, 1.00]::real[]) AS threshold
ORDER BY threshold;

\echo ''
\echo 'Lab 1 complete. The lexical arm recovers a pool, trigram recovers the'
\echo 'misspelled identity, and the access path is index-backed.'
