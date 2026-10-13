\set ON_ERROR_STOP on

-- The index behind each search, on mosaic_search.product_listing. The restore
-- (scripts/catalog/prepare_staged_catalog_search.py) runs these statements in
-- order once the listings are loaded: building an HNSW graph over loaded rows
-- is far faster than inserting each row into an empty one. install.sql does not
-- include this file.

-- Full-text search. GIN is an inverted index: it maps each stemmed word to the
-- listings that contain it, so `search_document @@ query` reads only the
-- listings holding every query word instead of scanning the table.
CREATE INDEX IF NOT EXISTS product_search_fts_idx
    ON mosaic_search.product_listing USING gin (search_document);

-- Fuzzy matching. The same inverted index over three-letter pieces (trigrams):
-- a mistyped ID still shares most of its trigrams with the real one, so pg_trgm
-- reads only the listings that share them before scoring word similarity.
CREATE INDEX IF NOT EXISTS product_search_trigram_idx
    ON mosaic_search.product_listing USING gin (trigram_text gin_trgm_ops);

-- Category filters and the shop's product IDs (product_listing_view adds the
-- offset), so a shortlist is fetched by key instead of by scanning.
CREATE INDEX IF NOT EXISTS product_search_kind_idx
    ON mosaic_search.product_listing (category_key, product_id);
CREATE INDEX IF NOT EXISTS product_search_public_id_idx
    ON mosaic_search.product_listing ((product_id + 1000000));

-- Semantic search. An HNSW graph over the embeddings finds near neighbours by
-- cosine distance without comparing the request against every listing. The
-- graph parameters must match db/config/retrieval.yaml (config_tripwire.py).
CREATE INDEX IF NOT EXISTS product_search_vector_idx
    ON mosaic_search.product_listing
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);
