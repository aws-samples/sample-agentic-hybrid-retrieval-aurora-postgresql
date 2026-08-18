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
-- Measured on the live cluster (500,000 vectors, m=16, ef_construction=200,
-- ef_search=100, k=10, 30 retrieval anchors, recall against the exact fp32 answer):
--
--   representation   index size   recall@10   server ms   buffers   build
--   fp32             3905 MB      0.9933      1.86        2336      not measured
--   halfvec          1302 MB      0.9900      3.03        2413      487 s
--   binary x200      207 MB       0.9300      4.54        6291      63 s
--
-- halfvec is the recommendation: 3.0x smaller for 0.33 points of recall.
--
-- The size drop is larger than the payload drop, because of page packing rather than the
-- vector itself. An 8 kB page holds exactly one 4,100-byte fp32 element, so fp32 costs
-- 8,189 bytes per vector; a 2,056-byte halfvec element packs three to a page. Halving the
-- element size cut the index by 3x, not 2x.
--
-- Binary does not follow that pattern: at 136 bytes the vector stops being the cost and
-- the m=16 neighbour lists dominate, so 207 MB is 434 bytes per vector against a 136-byte
-- payload. Binary is kept for what it demonstrates rather than as a recommendation: on
-- this corpus the true top-10 sits inside a 0.032-wide cosine band, which 1 bit per
-- dimension cannot resolve, so recall needs x200 overfetch and by then the two-pass is
-- slower and touches more buffers than fp32.

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
