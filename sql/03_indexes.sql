\set ON_ERROR_STOP on

CREATE INDEX IF NOT EXISTS product_domain_category_idx
    ON catalog.product (domain, category, subcategory);
CREATE INDEX IF NOT EXISTS product_price_idx
    ON catalog.product (price_usd);
CREATE INDEX IF NOT EXISTS product_availability_price_idx
    ON catalog.product (availability, price_usd);
CREATE INDEX IF NOT EXISTS product_brand_model_idx
    ON catalog.product (brand, model);
CREATE INDEX IF NOT EXISTS product_rating_idx
    ON catalog.product (rating DESC, review_count DESC);
CREATE INDEX IF NOT EXISTS product_updated_at_idx
    ON catalog.product (updated_at DESC);
CREATE INDEX IF NOT EXISTS product_attributes_gin_idx
    ON catalog.product USING gin (attributes jsonb_path_ops);
CREATE INDEX IF NOT EXISTS product_tags_gin_idx
    ON catalog.product USING gin (tags jsonb_path_ops);
CREATE INDEX IF NOT EXISTS product_search_document_gin_idx
    ON catalog.product USING gin (search_document);
CREATE INDEX IF NOT EXISTS product_trigram_gin_idx
    ON catalog.product USING gin (trigram_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS product_media_primary_idx
    ON catalog.product_media (product_id)
    WHERE role = 'primary' AND sort_order = 0;
CREATE INDEX IF NOT EXISTS retrieval_run_started_idx
    ON catalog.retrieval_run (started_at DESC);
CREATE INDEX IF NOT EXISTS retrieval_candidate_final_idx
    ON catalog.retrieval_candidate (run_id, final_rank)
    WHERE final_rank IS NOT NULL;
CREATE INDEX IF NOT EXISTS product_review_product_date_idx
    ON catalog.product_review (product_id, review_date DESC);

-- Run only after real model embeddings have been populated. CONCURRENTLY must
-- execute outside a transaction.
CREATE INDEX CONCURRENTLY IF NOT EXISTS product_embedding_hnsw_cosine_idx
    ON catalog.product USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200)
    WHERE embedding IS NOT NULL;

ANALYZE catalog.product;
