\set ON_ERROR_STOP on

DO $$
DECLARE
    product_count bigint;
    document_count bigint;
    embedded_count bigint;
    premium_count bigint;
    evidence_count bigint;
    specification_count bigint;
    review_count bigint;
    vector_dimensions integer[];
    model_ids text[];
    missing_indexes text[];
BEGIN
    SELECT count(*) INTO product_count FROM mosaic.product;
    SELECT count(*) INTO document_count FROM mosaic_search.product_document;
    SELECT count(*) FILTER (WHERE embedding IS NOT NULL),
           array_agg(DISTINCT vector_dims(embedding))
               FILTER (WHERE embedding IS NOT NULL),
           array_agg(DISTINCT embedding_model_key ORDER BY embedding_model_key)
               FILTER (WHERE embedding_model_key IS NOT NULL)
    INTO embedded_count, vector_dimensions, model_ids
    FROM mosaic_search.product_document;
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
    WHERE source_name IN (
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
    IF embedded_count <> 500000 THEN
        RAISE EXCEPTION
            'DAT410 bootstrap requires 500000 embeddings; found %. Re-run the verified cache import.',
            embedded_count;
    END IF;
    IF vector_dimensions IS DISTINCT FROM ARRAY[1024] THEN
        RAISE EXCEPTION
            'DAT410 bootstrap requires only 1024-dimensional vectors; found %. Load the Cohere Embed v4 cache.',
            vector_dimensions;
    END IF;
    IF model_ids IS DISTINCT FROM ARRAY['us.cohere.embed-v4:0'] THEN
        RAISE EXCEPTION
            'DAT410 bootstrap requires only us.cohere.embed-v4:0; found %. Load the pinned cache release.',
            model_ids;
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
    (SELECT count(*) FROM mosaic_search.product_document
      WHERE embedding IS NOT NULL) AS embeddings,
    (SELECT count(*) FROM mosaic.merchandising_assignment
      WHERE media_tier IN ('flagship', 'premium')) AS premium_products,
    (SELECT count(*) FROM mosaic.product_evidence) AS evidence_records,
    'us.cohere.embed-v4:0'::text AS embedding_model,
    1024 AS embedding_dimensions;
