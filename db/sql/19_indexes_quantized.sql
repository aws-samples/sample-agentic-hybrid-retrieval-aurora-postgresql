\set ON_ERROR_STOP on

-- Quantized HNSW representations of the same 500,000 vectors.
--
-- Expression indexes, not new columns: `halfvec` and `bit` are derived from the fp32
-- `embedding` by cast, so no re-embedding and no extra heap storage is involved. A query
-- must repeat the same expression to use the index.
--
-- Run after embeddings exist, alongside 08_indexes_concurrent.sql. These statements must
-- not run inside a transaction block.
--
-- Compare representations against an exact scan over the same vectors and filters.
-- Index size includes graph and page overhead, so payload size alone does not
-- predict the on-disk reduction. Inspect current plans, recall and timings in
-- the HNSW Playground; do not carry a measurement across catalog revisions.
--
-- Half precision trades some distance precision for a smaller vector payload.
-- Binary quantization changes the first-pass distance to Hamming distance and
-- needs full-precision rescoring. Measure its overfetch requirement before using
-- it for a workload; a smaller index does not guarantee a faster complete query.

CREATE INDEX CONCURRENTLY IF NOT EXISTS product_document_embedding_hnsw_halfvec_idx
    ON mosaic_search.product_document
    USING hnsw ((embedding::halfvec(1024)) halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 200)
    WHERE embedding IS NOT NULL;

-- bit_hamming_ops has no cosine operator. The first pass ranks by bit differences with
-- `<~>`, which is why a second pass over the fp32 vectors is required to recover order.
CREATE INDEX CONCURRENTLY IF NOT EXISTS product_document_embedding_hnsw_binary_idx
    ON mosaic_search.product_document
    USING hnsw ((binary_quantize(embedding)::bit(1024)) bit_hamming_ops)
    WITH (m = 16, ef_construction = 200)
    WHERE embedding IS NOT NULL;

ANALYZE mosaic_search.product_document;
