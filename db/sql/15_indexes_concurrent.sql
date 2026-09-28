\set ON_ERROR_STOP on

-- Run only after embeddings are populated. These statements must not run inside a transaction block.
CREATE INDEX CONCURRENTLY IF NOT EXISTS product_document_embedding_hnsw_cosine_idx
    ON mosaic_search.product_document
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200)
    WHERE embedding IS NOT NULL;

-- Product evidence is selected after product retrieval. The authoritative
-- product specification shares the product projection's vector in
-- search_product_evidence, while source-specific facts use FTS. There is no
-- independently embedded evidence corpus to justify a second HNSW index.
DROP INDEX CONCURRENTLY IF EXISTS mosaic.product_evidence_embedding_hnsw_cosine_idx;

ANALYZE mosaic_search.product_document;
ANALYZE mosaic.product_evidence;
