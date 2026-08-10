-- DEPRECATED: the `catalog.*` tree. The application does not read this schema;
-- `service/retrieval.py` queries `mosaic` and `mosaic_search` (see db/sql/).
-- Deleted by Phase 2 Unit E. See docs/rewrite-losses.md for what the rewrite
-- dropped and docs/superpowers/specs/ for the Phase 2 design.
-- Do not add features here. Do not point a lab at it.

INSERT INTO catalog.product AS current (
    product_id, product_uid, sku, domain, category, subcategory, brand, model, title,
    short_description, long_description, price_usd, list_price_usd, currency, rating,
    review_count, availability, inventory_count, seller_count, shipping_days,
    warranty_months, return_rate, popularity_score, quality_score, freshness_score,
    metadata_completeness, launch_date, updated_at, source_system, language,
    is_refurbished, is_sponsored, attributes, tags, aliases, challenge_cohorts,
    canonical_group_id, image_key, search_text, embedding_text, trigram_text
)
SELECT
    product_id::bigint,
    product_uid::uuid,
    sku,
    domain,
    category,
    subcategory,
    brand,
    model,
    title,
    short_description,
    long_description,
    price_usd::numeric,
    list_price_usd::numeric,
    currency,
    rating::numeric,
    review_count::integer,
    availability,
    inventory_count::integer,
    seller_count::smallint,
    shipping_days::smallint,
    warranty_months::smallint,
    return_rate::real,
    popularity_score::real,
    quality_score::real,
    freshness_score::real,
    metadata_completeness::real,
    launch_date::date,
    updated_at::timestamptz,
    source_system,
    language,
    is_refurbished::boolean,
    is_sponsored::boolean,
    attributes_json::jsonb,
    tags_json::jsonb,
    aliases_json::jsonb,
    challenge_cohorts_json::jsonb,
    canonical_group_id,
    nullif(image_key, ''),
    search_text,
    embedding_text,
    lower(concat_ws(' ', title, brand, model, subcategory, aliases_json))
FROM catalog_stage.product_raw
ON CONFLICT (product_id) DO UPDATE SET
    product_uid = EXCLUDED.product_uid,
    sku = EXCLUDED.sku,
    domain = EXCLUDED.domain,
    category = EXCLUDED.category,
    subcategory = EXCLUDED.subcategory,
    brand = EXCLUDED.brand,
    model = EXCLUDED.model,
    title = EXCLUDED.title,
    short_description = EXCLUDED.short_description,
    long_description = EXCLUDED.long_description,
    price_usd = EXCLUDED.price_usd,
    list_price_usd = EXCLUDED.list_price_usd,
    currency = EXCLUDED.currency,
    rating = EXCLUDED.rating,
    review_count = EXCLUDED.review_count,
    availability = EXCLUDED.availability,
    inventory_count = EXCLUDED.inventory_count,
    seller_count = EXCLUDED.seller_count,
    shipping_days = EXCLUDED.shipping_days,
    warranty_months = EXCLUDED.warranty_months,
    return_rate = EXCLUDED.return_rate,
    popularity_score = EXCLUDED.popularity_score,
    quality_score = EXCLUDED.quality_score,
    freshness_score = EXCLUDED.freshness_score,
    metadata_completeness = EXCLUDED.metadata_completeness,
    launch_date = EXCLUDED.launch_date,
    updated_at = EXCLUDED.updated_at,
    source_system = EXCLUDED.source_system,
    language = EXCLUDED.language,
    is_refurbished = EXCLUDED.is_refurbished,
    is_sponsored = EXCLUDED.is_sponsored,
    attributes = EXCLUDED.attributes,
    tags = EXCLUDED.tags,
    aliases = EXCLUDED.aliases,
    challenge_cohorts = EXCLUDED.challenge_cohorts,
    canonical_group_id = EXCLUDED.canonical_group_id,
    image_key = EXCLUDED.image_key,
    search_text = EXCLUDED.search_text,
    trigram_text = EXCLUDED.trigram_text,
    embedding = CASE
        WHEN current.embedding_content_hash = encode(
            digest(EXCLUDED.embedding_text, 'sha256'),
            'hex'
        )
        THEN current.embedding
        ELSE NULL
    END,
    embedding_model_id = CASE
        WHEN current.embedding_content_hash = encode(
            digest(EXCLUDED.embedding_text, 'sha256'),
            'hex'
        )
        THEN current.embedding_model_id
        ELSE NULL
    END,
    embedding_content_hash = CASE
        WHEN current.embedding_content_hash = encode(
            digest(EXCLUDED.embedding_text, 'sha256'),
            'hex'
        )
        THEN current.embedding_content_hash
        ELSE NULL
    END,
    embedded_at = CASE
        WHEN current.embedding_content_hash = encode(
            digest(EXCLUDED.embedding_text, 'sha256'),
            'hex'
        )
        THEN current.embedded_at
        ELSE NULL
    END,
    embedding_text = EXCLUDED.embedding_text;

ANALYZE catalog.product;
