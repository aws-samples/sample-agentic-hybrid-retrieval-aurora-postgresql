\set ON_ERROR_STOP on

CREATE OR REPLACE VIEW mosaic.v_shop_product AS
SELECT
    p.product_id,
    p.product_uid,
    p.sku,
    c.domain,
    c.category_key,
    c.category_path,
    b.display_name AS brand_name,
    p.model_name,
    coalesce(ma.merchandising_title, p.title) AS display_title,
    p.short_description,
    p.attributes,
    o.price_cents,
    o.list_price_cents,
    o.currency,
    o.availability,
    o.inventory_count,
    o.rating,
    o.review_count,
    ma.media_tier,
    ma.shop_page,
    ma.shop_position,
    ma.is_flagship,
    ma.is_retrieval_anchor,
    ma.catalog_asset_key,
    catalog_media.runtime_uri AS catalog_image_uri,
    detail_media.runtime_uri AS detail_image_uri
FROM mosaic.product p
JOIN mosaic.brand b ON b.brand_id = p.brand_id
JOIN mosaic.category c ON c.category_id = p.category_id
JOIN mosaic.product_offer o ON o.product_id = p.product_id
LEFT JOIN mosaic.merchandising_assignment ma ON ma.product_id = p.product_id
LEFT JOIN LATERAL (
    SELECT a.runtime_uri
    FROM mosaic.product_media pm
    JOIN mosaic.media_asset a USING (asset_id)
    WHERE pm.product_id = p.product_id AND pm.role = 'catalog'
    ORDER BY pm.sort_order
    LIMIT 1
) catalog_media ON true
LEFT JOIN LATERAL (
    SELECT a.runtime_uri
    FROM mosaic.product_media pm
    JOIN mosaic.media_asset a USING (asset_id)
    WHERE pm.product_id = p.product_id AND pm.role = 'detail'
    ORDER BY pm.sort_order
    LIMIT 1
) detail_media ON true
WHERE p.is_active;

CREATE OR REPLACE VIEW mosaic.v_premium_shop AS
SELECT *
FROM mosaic.v_shop_product
WHERE media_tier IN ('flagship', 'premium')
  AND shop_page IS NOT NULL
ORDER BY shop_page, shop_position;

CREATE OR REPLACE VIEW mosaic.v_flagship_product AS
SELECT *
FROM mosaic.v_shop_product
WHERE is_flagship
ORDER BY shop_page, shop_position;

CREATE OR REPLACE VIEW mosaic_search.v_embedding_backlog AS
SELECT
    product_id,
    title,
    embedding_model_key,
    embedding_updated_at,
    source_updated_at,
    CASE
        WHEN embedding IS NULL THEN 'missing'
        WHEN embedding_updated_at IS NULL THEN 'unknown'
        WHEN embedding_updated_at < source_updated_at THEN 'stale'
        ELSE 'current'
    END AS embedding_status
FROM mosaic_search.product_document
WHERE embedding IS NULL
   OR embedding_updated_at IS NULL
   OR embedding_updated_at < source_updated_at;

CREATE OR REPLACE VIEW mosaic.v_media_coverage AS
SELECT
    ma.media_tier,
    count(*) AS products,
    count(*) FILTER (WHERE catalog_media.product_id IS NOT NULL) AS with_catalog_media,
    count(*) FILTER (WHERE detail_media.product_id IS NOT NULL) AS with_detail_media
FROM mosaic.merchandising_assignment ma
LEFT JOIN (
    SELECT DISTINCT product_id FROM mosaic.product_media WHERE role = 'catalog'
) catalog_media USING (product_id)
LEFT JOIN (
    SELECT DISTINCT product_id FROM mosaic.product_media WHERE role = 'detail'
) detail_media USING (product_id)
GROUP BY ma.media_tier
ORDER BY ma.media_tier;
