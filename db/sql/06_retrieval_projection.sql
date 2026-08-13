\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS mosaic_search.product_document (
    product_id              bigint PRIMARY KEY REFERENCES mosaic.product(product_id) ON DELETE CASCADE,
    product_uid             uuid NOT NULL,
    sku                     text NOT NULL,
    domain                  mosaic.product_domain NOT NULL,
    category_id             bigint NOT NULL,
    category_key            text NOT NULL,
    category_path           text NOT NULL,
    brand_id                bigint NOT NULL,
    brand_name              text NOT NULL,
    model_name              text NOT NULL,
    title                   text NOT NULL,
    short_description       text NOT NULL,
    canonical_group_id      text NOT NULL,

    price_cents             bigint NOT NULL,
    list_price_cents        bigint NOT NULL,
    currency                text NOT NULL,
    availability            mosaic.availability_status NOT NULL,
    inventory_count         integer NOT NULL,
    rating                  numeric(3,2),
    review_count            integer NOT NULL,
    quality_score           real NOT NULL,
    popularity_score        real NOT NULL,
    freshness_score         real NOT NULL,
    metadata_completeness   real NOT NULL,
    is_sponsored            boolean NOT NULL,
    is_refurbished          boolean NOT NULL,

    attributes              jsonb NOT NULL,
    tags                    text[] NOT NULL,
    aliases                 text[] NOT NULL,
    challenge_cohorts       text[] NOT NULL,

    media_tier              mosaic.media_tier,
    is_flagship             boolean NOT NULL DEFAULT false,
    is_retrieval_anchor     boolean NOT NULL DEFAULT false,
    catalog_asset_key       text,

    title_text              text NOT NULL,
    identity_text           text NOT NULL,
    feature_text            text NOT NULL,
    body_text               text NOT NULL,
    trigram_text            text NOT NULL,
    embedding_text          text NOT NULL,
    rerank_text             text NOT NULL,

    search_document         tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title_text, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(identity_text, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(feature_text, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(body_text, '')), 'C')
    ) STORED,

    embedding               vector(1024),
    embedding_model_key     text REFERENCES mosaic.embedding_model(model_key),
    embedding_updated_at    timestamptz,
    source_updated_at       timestamptz NOT NULL,
    updated_at              timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT search_attributes_object CHECK (jsonb_typeof(attributes) = 'object')
);

ALTER TABLE mosaic_search.product_document
    ADD COLUMN IF NOT EXISTS list_price_cents bigint NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS currency text NOT NULL DEFAULT 'USD';

ALTER TABLE mosaic_search.product_document
    ALTER COLUMN list_price_cents DROP DEFAULT,
    ALTER COLUMN currency DROP DEFAULT;

COMMENT ON TABLE mosaic_search.product_document IS
'Denormalized retrieval projection. Keep common filters on the same table as the HNSW vector so filtered ANN behavior is explicit and measurable.';

COMMENT ON COLUMN mosaic_search.product_document.embedding_text IS
'Stable semantic product document. Do not include volatile price, inventory, sale, or current-rating values.';

COMMENT ON COLUMN mosaic_search.product_document.rerank_text IS
'Rich candidate text for the external reranker; may include current commerce state and decisive eligibility facts.';

CREATE OR REPLACE PROCEDURE mosaic_search.refresh_product_documents(
    p_product_ids bigint[] DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO mosaic_search.product_document (
        product_id, product_uid, sku, domain, category_id, category_key, category_path,
        brand_id, brand_name, model_name, title, short_description, canonical_group_id,
        price_cents, list_price_cents, currency, availability, inventory_count,
        rating, review_count,
        quality_score, popularity_score, freshness_score, metadata_completeness,
        is_sponsored, is_refurbished, attributes, tags, aliases, challenge_cohorts,
        media_tier, is_flagship, is_retrieval_anchor, catalog_asset_key,
        title_text, identity_text, feature_text, body_text, trigram_text,
        embedding_text, rerank_text, source_updated_at, updated_at
    )
    SELECT
        p.product_id,
        p.product_uid,
        p.sku,
        c.domain,
        c.category_id,
        c.category_key,
        c.category_path,
        b.brand_id,
        b.display_name,
        p.model_name,
        p.title,
        p.short_description,
        p.canonical_group_id,
        o.price_cents,
        o.list_price_cents,
        o.currency,
        o.availability,
        o.inventory_count,
        o.rating,
        o.review_count,
        o.quality_score,
        o.popularity_score,
        o.freshness_score,
        o.metadata_completeness,
        o.is_sponsored,
        o.is_refurbished,
        p.attributes,
        p.tags,
        p.aliases,
        p.challenge_cohorts,
        ma.media_tier,
        coalesce(ma.is_flagship, false),
        coalesce(ma.is_retrieval_anchor, false),
        ma.catalog_asset_key,
        p.title,
        concat_ws(' ', b.display_name, p.model_name, p.sku, c.category_path),
        concat_ws(' ', p.short_description, array_to_string(p.tags, ' '), array_to_string(p.aliases, ' ')),
        concat_ws(' ', p.long_description, p.attributes::text),
        lower(concat_ws(' ', p.title, b.display_name, p.model_name, p.sku, c.category_path,
                        array_to_string(p.aliases, ' '), array_to_string(p.tags, ' '))),
        concat_ws(E'\n',
            'Product: ' || p.title,
            'Category: ' || c.category_path,
            'Brand and model: ' || b.display_name || ' ' || p.model_name,
            'Description: ' || p.short_description,
            'Details: ' || p.long_description,
            'Use cases and concepts: ' || array_to_string(p.tags, ', '),
            'Capabilities and attributes: ' || p.attributes::text
        ),
        concat_ws(E'\n',
            'Product: ' || p.title,
            'Catalog identity: SKU ' || p.sku || '; model ' || p.model_name,
            'Category: ' || c.category_path,
            'Description: ' || p.short_description,
            'Details: ' || p.long_description,
            'Search aliases: ' || array_to_string(p.aliases, ', '),
            'Attributes: ' || p.attributes::text,
            'Price: ' || to_char(o.price_cents / 100.0, 'FM999999990.00') || ' ' || o.currency,
            'Availability: ' || o.availability::text,
            'Rating: ' || coalesce(o.rating::text, 'unknown') || ' from ' || o.review_count || ' reviews'
        ),
        greatest(p.updated_at, o.updated_at, coalesce(ma.updated_at, '-infinity'::timestamptz)),
        clock_timestamp()
    FROM mosaic.product p
    JOIN mosaic.brand b ON b.brand_id = p.brand_id
    JOIN mosaic.category c ON c.category_id = p.category_id
    JOIN mosaic.product_offer o ON o.product_id = p.product_id
    LEFT JOIN mosaic.merchandising_assignment ma ON ma.product_id = p.product_id
    WHERE p.is_active
      AND (p_product_ids IS NULL OR p.product_id = ANY (p_product_ids))
    ON CONFLICT (product_id) DO UPDATE SET
        product_uid = EXCLUDED.product_uid,
        sku = EXCLUDED.sku,
        domain = EXCLUDED.domain,
        category_id = EXCLUDED.category_id,
        category_key = EXCLUDED.category_key,
        category_path = EXCLUDED.category_path,
        brand_id = EXCLUDED.brand_id,
        brand_name = EXCLUDED.brand_name,
        model_name = EXCLUDED.model_name,
        title = EXCLUDED.title,
        short_description = EXCLUDED.short_description,
        canonical_group_id = EXCLUDED.canonical_group_id,
        price_cents = EXCLUDED.price_cents,
        list_price_cents = EXCLUDED.list_price_cents,
        currency = EXCLUDED.currency,
        availability = EXCLUDED.availability,
        inventory_count = EXCLUDED.inventory_count,
        rating = EXCLUDED.rating,
        review_count = EXCLUDED.review_count,
        quality_score = EXCLUDED.quality_score,
        popularity_score = EXCLUDED.popularity_score,
        freshness_score = EXCLUDED.freshness_score,
        metadata_completeness = EXCLUDED.metadata_completeness,
        is_sponsored = EXCLUDED.is_sponsored,
        is_refurbished = EXCLUDED.is_refurbished,
        attributes = EXCLUDED.attributes,
        tags = EXCLUDED.tags,
        aliases = EXCLUDED.aliases,
        challenge_cohorts = EXCLUDED.challenge_cohorts,
        media_tier = EXCLUDED.media_tier,
        is_flagship = EXCLUDED.is_flagship,
        is_retrieval_anchor = EXCLUDED.is_retrieval_anchor,
        catalog_asset_key = EXCLUDED.catalog_asset_key,
        title_text = EXCLUDED.title_text,
        identity_text = EXCLUDED.identity_text,
        feature_text = EXCLUDED.feature_text,
        body_text = EXCLUDED.body_text,
        trigram_text = EXCLUDED.trigram_text,
        embedding_text = EXCLUDED.embedding_text,
        -- Invalidate the vector when the text it was computed from changes.
        -- Without this the projection carries an embedding of the OLD text: a
        -- silently stale vector, which is worse than a missing one because
        -- `scripts/embed_catalog.py` only selects rows where `embedding IS NULL`
        -- or the model key differs, so nothing would ever recompute it. The
        -- deleted `sql/02_upsert_from_stage.sql` did this and the port dropped
        -- it; restored in Phase 2 Unit E.
        embedding = CASE
            WHEN mosaic_search.product_document.embedding_text
                 IS DISTINCT FROM EXCLUDED.embedding_text
            THEN NULL
            ELSE mosaic_search.product_document.embedding
        END,
        embedding_model_key = CASE
            WHEN mosaic_search.product_document.embedding_text
                 IS DISTINCT FROM EXCLUDED.embedding_text
            THEN NULL
            ELSE mosaic_search.product_document.embedding_model_key
        END,
        rerank_text = EXCLUDED.rerank_text,
        source_updated_at = EXCLUDED.source_updated_at,
        updated_at = EXCLUDED.updated_at;

    DELETE FROM mosaic_search.product_document d
    USING mosaic.product p
    WHERE d.product_id = p.product_id
      AND NOT p.is_active
      AND (p_product_ids IS NULL OR p.product_id = ANY (p_product_ids));
END
$$;
