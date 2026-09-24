\set ON_ERROR_STOP on

-- Base bootstrap acceptance: the schema, retrieval functions, index relations
-- and tool contracts that the served catalog is restored into. No row count is
-- asserted here. The historical synthetic catalog is no longer part of the
-- workshop path, and the served catalog's records and vectors are verified by
-- scripts/real_catalog_cache.py before and after its restore, then reported by
-- /api/readiness, which the bootstrap checks against the pinned 500000.

DO $$
DECLARE
    missing_indexes text[];
    missing_functions text[];
    tool_count bigint;
BEGIN
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

    SELECT array_agg(required.name ORDER BY required.name)
    INTO missing_functions
    FROM (
        VALUES
            ('search_hybrid_rrf'),
            ('search_product_evidence'),
            ('matches_filters'),
            ('query_term_coverage')
    ) AS required(name)
    WHERE NOT EXISTS (
        SELECT 1
        FROM pg_proc function_relation
        JOIN pg_namespace schema_relation
          ON schema_relation.oid = function_relation.pronamespace
        WHERE schema_relation.nspname = 'mosaic_search'
          AND function_relation.proname = required.name
    );

    SELECT count(*) INTO tool_count
    FROM mosaic.agent_tool_contract
    WHERE enabled;

    IF missing_indexes IS NOT NULL THEN
        RAISE EXCEPTION
            'DAT410 bootstrap has missing or invalid retrieval indexes: %. Run make db-drop-invalid-indexes then make db-index-concurrent.',
            missing_indexes;
    END IF;
    IF missing_functions IS NOT NULL THEN
        RAISE EXCEPTION
            'DAT410 bootstrap is missing retrieval functions: %. Run make db-install.',
            missing_functions;
    END IF;
    IF tool_count <> 5 THEN
        RAISE EXCEPTION
            'DAT410 bootstrap requires 5 enabled agent tool contracts; found %. Run make db-install.',
            tool_count;
    END IF;
END
$$;

SELECT
    (SELECT count(*) FROM mosaic.product) AS products,
    (SELECT count(*) FROM mosaic_search.product_document) AS documents,
    (SELECT count(*) FROM mosaic.agent_tool_contract WHERE enabled) AS tool_contracts;
