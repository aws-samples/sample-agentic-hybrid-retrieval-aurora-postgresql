\set ON_ERROR_STOP on

-- Run only after embeddings are populated. These statements must not run inside a transaction block.
CREATE INDEX CONCURRENTLY IF NOT EXISTS product_document_embedding_hnsw_cosine_idx
    ON mosaic_search.product_document
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200)
    WHERE embedding IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS product_evidence_embedding_hnsw_cosine_idx
    ON mosaic.product_evidence
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 160)
    WHERE embedding IS NOT NULL;

ANALYZE mosaic_search.product_document;
ANALYZE mosaic.product_evidence;
