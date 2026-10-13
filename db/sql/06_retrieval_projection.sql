\set ON_ERROR_STOP on

-- The searchable listings. The restore fills this table once from the verified
-- source records (scripts/catalog/prepare_staged_catalog_search.py) and then
-- builds its indexes; nothing in a lab writes to it. Missing commerce facts
-- stay null: a historical listing price cannot become a current price, and an
-- unreported condition cannot mean new.
CREATE TABLE IF NOT EXISTS mosaic_search.product_listing (
    product_id              bigint PRIMARY KEY,
    dataset_id              text,
    parent_asin             text UNIQUE,
    source_record_sha256    text,
    embedding_text_sha256   text,
    domain                  mosaic.product_domain,
    category_key            text,
    category_path           text,
    brand_name              text,
    title                   text,
    price_cents             bigint,
    availability            mosaic.availability_status,
    rating                  numeric,
    attributes              jsonb,
    is_refurbished          boolean,
    is_sponsored            boolean,
    catalog_asset_key       text,
    canonical_group_id      text,
    challenge_cohorts       text[],
    is_retrieval_anchor     boolean,
    title_text              text,
    identity_text           text,
    feature_text            text,
    body_text               text,
    trigram_text            text,
    embedding_text          text,
    rerank_text             text,
    embedding               vector(1024) NOT NULL,
    embedding_model_key     text,
    search_document         tsvector
);

COMMENT ON TABLE mosaic_search.product_listing IS
'The source listings and their search indexes. Searches read product_listing_view.';

COMMENT ON COLUMN mosaic_search.product_listing.search_document IS
'Title and listing identity weighted A, features B, description C (to_tsvector english).';

COMMENT ON COLUMN mosaic_search.product_listing.trigram_text IS
'Lower-cased title and listing identity, matched by pg_trgm.';

COMMENT ON COLUMN mosaic_search.product_listing.embedding IS
'Cohere Embed v4 vector of embedding_text, compared by cosine distance.';

-- Reading each raw source record for its price made a budgeted headphones count
-- take 831 ms; this keyed copy answers it in 143 ms and costs nothing without a
-- budget. Only exact numeric prices qualify: "from 19.99" is not one price.
CREATE TABLE IF NOT EXISTS mosaic_search.source_price (
    product_id   bigint PRIMARY KEY,
    price_cents  bigint NOT NULL CHECK (price_cents >= 0)
);

-- What Shop, the API and your agent search. The offset gives each listing a
-- product ID distinct from every other catalog's, and the view adds the shop's
-- fields; PostgreSQL still uses product_listing's indexes through it.
CREATE OR REPLACE VIEW mosaic_search.product_listing_view AS
SELECT d.product_id + 1000000 AS product_id,
       d.dataset_id, d.parent_asin, d.source_record_sha256, d.embedding_text_sha256,
       d.parent_asin AS sku, d.domain, d.category_key, d.category_path,
       coalesce(d.brand_name, '') AS brand_name, d.parent_asin AS model_name,
       d.title, coalesce(nullif(d.body_text, ''), d.feature_text) AS short_description,
       d.price_cents, NULL::bigint AS list_price_cents, 'USD'::text AS currency,
       d.availability, NULL::integer AS inventory_count, d.rating,
       NULL::integer AS review_count, d.attributes, ARRAY[]::text[] AS tags,
       d.is_refurbished, d.is_sponsored, d.catalog_asset_key, d.canonical_group_id,
       d.challenge_cohorts, d.is_retrieval_anchor, false AS is_flagship,
       NULL::text AS media_tier, NULL::real AS freshness_score,
       NULL::real AS popularity_score, NULL::timestamptz AS updated_at,
       d.title_text, d.identity_text, d.feature_text, d.body_text, d.trigram_text,
       d.embedding_text,
       'Catalog identity: parent ASIN ' || d.parent_asin || E'.\n' || d.embedding_text AS rerank_text,
       d.embedding, d.embedding_model_key, d.search_document,
       -- The listing price the source recorded when it was collected. It is
       -- not a current offer, so it never becomes price_cents; a budget filter
       -- matches it instead (see 08_search_channels.sql).
       p.price_cents AS historical_price_cents
FROM mosaic_search.product_listing d
LEFT JOIN mosaic_search.source_price p ON p.product_id = d.product_id + 1000000;

COMMENT ON VIEW mosaic_search.product_listing_view IS
'The listings Shop, the API and the agent search, with shop product IDs and recorded source prices.';
