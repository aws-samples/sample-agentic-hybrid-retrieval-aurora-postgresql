\set ON_ERROR_STOP on

-- Search projection: relational and metadata filters.
CREATE INDEX IF NOT EXISTS product_document_domain_category_idx
    ON mosaic_search.product_document (domain, category_id);
CREATE INDEX IF NOT EXISTS product_document_brand_idx
    ON mosaic_search.product_document (brand_id, model_name);
CREATE INDEX IF NOT EXISTS product_document_price_idx
    ON mosaic_search.product_document (price_cents);
CREATE INDEX IF NOT EXISTS product_document_availability_price_idx
    ON mosaic_search.product_document (availability, price_cents);
CREATE INDEX IF NOT EXISTS product_document_rating_idx
    ON mosaic_search.product_document (rating DESC, review_count DESC);
CREATE INDEX IF NOT EXISTS product_document_canonical_idx
    ON mosaic_search.product_document (canonical_group_id);
CREATE INDEX IF NOT EXISTS product_document_anchor_idx
    ON mosaic_search.product_document (is_retrieval_anchor, media_tier)
    WHERE is_retrieval_anchor;
CREATE INDEX IF NOT EXISTS product_document_attributes_gin_idx
    ON mosaic_search.product_document USING gin (attributes jsonb_path_ops);
CREATE INDEX IF NOT EXISTS product_document_tags_gin_idx
    ON mosaic_search.product_document USING gin (tags);
CREATE INDEX IF NOT EXISTS product_document_cohorts_gin_idx
    ON mosaic_search.product_document USING gin (challenge_cohorts);

-- Lexical and typo retrieval.
CREATE INDEX IF NOT EXISTS product_document_fts_gin_idx
    ON mosaic_search.product_document USING gin (search_document);
CREATE INDEX IF NOT EXISTS product_document_trigram_gin_idx
    ON mosaic_search.product_document USING gin (trigram_text gin_trgm_ops);

-- Operational freshness and ingestion checks.
CREATE INDEX IF NOT EXISTS product_document_source_updated_idx
    ON mosaic_search.product_document (source_updated_at DESC);

ANALYZE mosaic.product;
ANALYZE mosaic.product_offer;
ANALYZE mosaic_search.product_document;
