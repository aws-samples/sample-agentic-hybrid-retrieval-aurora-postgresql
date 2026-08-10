\set ON_ERROR_STOP on

\if :{?brands_path}
\else
  \set brands_path 'build/normalized/brands.csv.gz'
\endif
\if :{?categories_path}
\else
  \set categories_path 'build/normalized/categories.csv.gz'
\endif
\if :{?products_path}
\else
  \set products_path 'build/normalized/products.csv.gz'
\endif
\if :{?offers_path}
\else
  \set offers_path 'build/normalized/offers.csv.gz'
\endif

\setenv MOSAIC_BRANDS_PATH :brands_path
\setenv MOSAIC_CATEGORIES_PATH :categories_path
\setenv MOSAIC_PRODUCTS_PATH :products_path
\setenv MOSAIC_OFFERS_PATH :offers_path

CREATE TEMP TABLE brand_stage (
    brand_id text, brand_key text, display_name text, is_synthetic text, metadata text
);
CREATE TEMP TABLE category_stage (
    category_id text, domain text, parent_category_id text, category_key text,
    display_name text, category_path text, depth text, metadata text
);
CREATE TEMP TABLE product_stage (
    product_id text, product_uid text, sku text, brand_id text, category_id text,
    canonical_group_id text, model_name text, title text, short_description text,
    long_description text, language text, attributes text, tags text, aliases text,
    challenge_cohorts text, launch_date text, source_system text, content_hash text,
    is_active text
);
CREATE TEMP TABLE offer_stage (
    product_id text, price_cents text, list_price_cents text, currency text,
    availability text, inventory_count text, seller_count text, shipping_days text,
    warranty_months text, rating text, review_count text, return_rate text,
    popularity_score text, quality_score text, freshness_score text,
    metadata_completeness text, is_refurbished text, is_sponsored text,
    offer_metadata text, effective_at text
);

\copy brand_stage FROM PROGRAM 'gzip -dc "$MOSAIC_BRANDS_PATH"' WITH (FORMAT csv, HEADER true)
\copy category_stage FROM PROGRAM 'gzip -dc "$MOSAIC_CATEGORIES_PATH"' WITH (FORMAT csv, HEADER true)
\copy product_stage FROM PROGRAM 'gzip -dc "$MOSAIC_PRODUCTS_PATH"' WITH (FORMAT csv, HEADER true)
\copy offer_stage FROM PROGRAM 'gzip -dc "$MOSAIC_OFFERS_PATH"' WITH (FORMAT csv, HEADER true)

INSERT INTO mosaic.brand (brand_id, brand_key, display_name, is_synthetic, metadata)
OVERRIDING SYSTEM VALUE
SELECT brand_id::bigint, brand_key, display_name, is_synthetic::boolean, metadata::jsonb
FROM brand_stage
ON CONFLICT (brand_id) DO UPDATE SET
    brand_key = EXCLUDED.brand_key,
    display_name = EXCLUDED.display_name,
    is_synthetic = EXCLUDED.is_synthetic,
    metadata = EXCLUDED.metadata;

INSERT INTO mosaic.category (
    category_id, domain, parent_category_id, category_key, display_name,
    category_path, depth, metadata
)
OVERRIDING SYSTEM VALUE
SELECT category_id::bigint, domain::mosaic.product_domain,
       nullif(parent_category_id, '')::bigint, category_key, display_name,
       category_path, depth::smallint, metadata::jsonb
FROM category_stage
ON CONFLICT (category_id) DO UPDATE SET
    domain = EXCLUDED.domain,
    parent_category_id = EXCLUDED.parent_category_id,
    category_key = EXCLUDED.category_key,
    display_name = EXCLUDED.display_name,
    category_path = EXCLUDED.category_path,
    depth = EXCLUDED.depth,
    metadata = EXCLUDED.metadata;

INSERT INTO mosaic.product (
    product_id, product_uid, sku, brand_id, category_id, canonical_group_id,
    model_name, title, short_description, long_description, language,
    attributes, tags, aliases, challenge_cohorts, launch_date, source_system,
    content_hash, is_active
)
OVERRIDING SYSTEM VALUE
SELECT product_id::bigint, product_uid::uuid, sku, brand_id::bigint, category_id::bigint,
       canonical_group_id, model_name, title, short_description, long_description,
       language, attributes::jsonb,
       ARRAY(SELECT jsonb_array_elements_text(tags::jsonb)),
       ARRAY(SELECT jsonb_array_elements_text(aliases::jsonb)),
       ARRAY(SELECT jsonb_array_elements_text(challenge_cohorts::jsonb)), nullif(launch_date, '')::date, source_system,
       nullif(content_hash, ''), is_active::boolean
FROM product_stage
ON CONFLICT (product_id) DO UPDATE SET
    product_uid = EXCLUDED.product_uid,
    sku = EXCLUDED.sku,
    brand_id = EXCLUDED.brand_id,
    category_id = EXCLUDED.category_id,
    canonical_group_id = EXCLUDED.canonical_group_id,
    model_name = EXCLUDED.model_name,
    title = EXCLUDED.title,
    short_description = EXCLUDED.short_description,
    long_description = EXCLUDED.long_description,
    language = EXCLUDED.language,
    attributes = EXCLUDED.attributes,
    tags = EXCLUDED.tags,
    aliases = EXCLUDED.aliases,
    challenge_cohorts = EXCLUDED.challenge_cohorts,
    launch_date = EXCLUDED.launch_date,
    source_system = EXCLUDED.source_system,
    content_hash = EXCLUDED.content_hash,
    is_active = EXCLUDED.is_active;

INSERT INTO mosaic.product_offer (
    product_id, price_cents, list_price_cents, currency, availability,
    inventory_count, seller_count, shipping_days, warranty_months, rating,
    review_count, return_rate, popularity_score, quality_score, freshness_score,
    metadata_completeness, is_refurbished, is_sponsored, offer_metadata, effective_at
)
SELECT product_id::bigint, price_cents::bigint, list_price_cents::bigint, currency,
       availability::mosaic.availability_status, inventory_count::integer,
       seller_count::smallint, nullif(shipping_days, '')::smallint,
       nullif(warranty_months, '')::smallint, nullif(rating, '')::numeric,
       review_count::integer, nullif(return_rate, '')::real,
       popularity_score::real, quality_score::real, freshness_score::real,
       metadata_completeness::real, is_refurbished::boolean,
       is_sponsored::boolean, offer_metadata::jsonb, effective_at::timestamptz
FROM offer_stage
ON CONFLICT (product_id) DO UPDATE SET
    price_cents = EXCLUDED.price_cents,
    list_price_cents = EXCLUDED.list_price_cents,
    currency = EXCLUDED.currency,
    availability = EXCLUDED.availability,
    inventory_count = EXCLUDED.inventory_count,
    seller_count = EXCLUDED.seller_count,
    shipping_days = EXCLUDED.shipping_days,
    warranty_months = EXCLUDED.warranty_months,
    rating = EXCLUDED.rating,
    review_count = EXCLUDED.review_count,
    return_rate = EXCLUDED.return_rate,
    popularity_score = EXCLUDED.popularity_score,
    quality_score = EXCLUDED.quality_score,
    freshness_score = EXCLUDED.freshness_score,
    metadata_completeness = EXCLUDED.metadata_completeness,
    is_refurbished = EXCLUDED.is_refurbished,
    is_sponsored = EXCLUDED.is_sponsored,
    offer_metadata = EXCLUDED.offer_metadata,
    effective_at = EXCLUDED.effective_at;

SELECT setval(pg_get_serial_sequence('mosaic.brand','brand_id'), coalesce((SELECT max(brand_id) FROM mosaic.brand), 1), true);
SELECT setval(pg_get_serial_sequence('mosaic.category','category_id'), coalesce((SELECT max(category_id) FROM mosaic.category), 1), true);
SELECT setval(pg_get_serial_sequence('mosaic.product','product_id'), coalesce((SELECT max(product_id) FROM mosaic.product), 1), true);

CALL mosaic_search.refresh_product_documents();
ANALYZE mosaic.product;
ANALYZE mosaic.product_offer;
ANALYZE mosaic_search.product_document;
