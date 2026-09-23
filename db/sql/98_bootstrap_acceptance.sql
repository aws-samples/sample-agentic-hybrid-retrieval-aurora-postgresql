\set ON_ERROR_STOP on

-- Base bootstrap acceptance. The historical synthetic catalog is loaded without
-- vectors; the served catalog's records and vectors are verified separately by
-- scripts/real_catalog_cache.py before and after its restore.

DO $$
DECLARE
    product_count bigint;
    document_count bigint;
    premium_count bigint;
    evidence_count bigint;
    specification_count bigint;
    review_count bigint;
    missing_indexes text[];
BEGIN
    SELECT count(*) INTO product_count FROM mosaic.product;
    SELECT count(*) INTO document_count FROM mosaic_search.product_document;
    SELECT count(*) INTO premium_count
    FROM mosaic.merchandising_assignment
    WHERE media_tier IN ('flagship', 'premium');
    SELECT count(*),
           count(*) FILTER (WHERE evidence_type = 'product_spec'),
           count(*) FILTER (
               WHERE evidence_type::text IN (
                   'customer_review',
                   'verified_review'
               )
           )
    INTO evidence_count, specification_count, review_count
    FROM mosaic.product_evidence
    WHERE is_current AND source_name IN (
        'Mosaic catalog specification',
        'Mosaic synthetic review corpus',
        'Mosaic verified review corpus'
    );

    SELECT array_agg(required.name ORDER BY required.name)
    INTO missing_indexes
    FROM (
        VALUES
            ('product_document_fts_gin_idx'),
            ('product_document_trigram_gin_idx'),
            ('product_document_embedding_hnsw_cosine_idx')
    ) AS required(name)
    LEFT JOIN pg_class index_relation
      ON index_relation.relname = required.name
     AND index_relation.relkind = 'i'
    LEFT JOIN pg_index index_state
      ON index_state.indexrelid = index_relation.oid
    WHERE index_relation.oid IS NULL
       OR NOT index_state.indisvalid
       OR NOT index_state.indisready;

    IF product_count <> 500000 OR document_count <> 500000 THEN
        RAISE EXCEPTION
            'DAT410 bootstrap requires 500000 products and documents; products=%, documents=%. Reload the pinned catalog.',
            product_count, document_count;
    END IF;
    IF missing_indexes IS NOT NULL THEN
        RAISE EXCEPTION
            'DAT410 bootstrap has missing or invalid retrieval indexes: %. Run make db-drop-invalid-indexes then make db-index-concurrent.',
            missing_indexes;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM mosaic_search.corpus_lexeme)
       OR NOT EXISTS (SELECT 1 FROM mosaic_search.corpus_surface_lexeme) THEN
        RAISE EXCEPTION
            'DAT410 bootstrap has an empty query-coverage vocabulary, so every request would read unavailable. Run make db-seed-corpus-lexeme.';
    END IF;
    IF premium_count <> 120 THEN
        RAISE EXCEPTION
            'DAT410 bootstrap requires 120 premium products; found %. Re-run make db-load-cohort.',
            premium_count;
    END IF;
    IF evidence_count <> 515000
       OR specification_count <> 500000
       OR review_count <> 15000 THEN
        RAISE EXCEPTION
            'DAT410 bootstrap requires 500000 product specifications and 15000 synthetic customer reviews; specifications=%, reviews=%, total=%. Re-run make db-load-evidence.',
            specification_count, review_count, evidence_count;
    END IF;
END
$$;

SELECT
    (SELECT count(*) FROM mosaic.product) AS products,
    (SELECT count(*) FROM mosaic.merchandising_assignment
      WHERE media_tier IN ('flagship', 'premium')) AS premium_products,
    (SELECT count(*) FROM mosaic.product_evidence) AS evidence_records;
