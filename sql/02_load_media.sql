\set ON_ERROR_STOP on

TRUNCATE TABLE catalog_stage.product_media_raw;
\copy catalog_stage.product_media_raw (product_id, image_url, image_source, image_key) FROM PROGRAM 'gzip -dc data/full/product_image_urls.csv.gz' WITH (FORMAT csv, HEADER true)

INSERT INTO catalog.product_media (
    product_id,
    role,
    sort_order,
    image_url,
    image_source,
    image_key,
    alt_text,
    asset_sha256,
    publication_status
)
SELECT
    raw.product_id::bigint,
    'primary',
    0,
    '/' || split_part(raw.image_url, '?', 1),
    raw.image_source,
    nullif(raw.image_key, ''),
    product.title || ' product image',
    null,
    'approved'
FROM catalog_stage.product_media_raw raw
JOIN catalog.product product
  ON product.product_id = raw.product_id::bigint
ON CONFLICT (product_id, role, sort_order) DO UPDATE SET
    image_url = EXCLUDED.image_url,
    image_source = EXCLUDED.image_source,
    image_key = EXCLUDED.image_key,
    alt_text = EXCLUDED.alt_text,
    asset_sha256 = EXCLUDED.asset_sha256,
    publication_status = EXCLUDED.publication_status;

SELECT image_source, publication_status, count(*) AS products
FROM catalog.product_media
WHERE role = 'primary' AND sort_order = 0
GROUP BY image_source, publication_status
ORDER BY image_source, publication_status;
