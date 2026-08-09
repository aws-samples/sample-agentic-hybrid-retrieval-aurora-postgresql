\set ON_ERROR_STOP on

\if :{?premium_cohort_path}
\else
  \set premium_cohort_path 'data/premium_cohort_120.csv'
\endif

CREATE TEMP TABLE premium_cohort_stage (
    product_id text,
    product_uid text,
    sku text,
    domain text,
    category text,
    subcategory text,
    source_title text,
    merchandising_title text,
    media_tier text,
    shop_page text,
    shop_position text,
    is_flagship text,
    is_retrieval_anchor text,
    catalog_asset_key text,
    detail_asset_key text,
    image_status text,
    challenge_cohorts text
);

\copy premium_cohort_stage FROM :'premium_cohort_path' WITH (FORMAT csv, HEADER true)

INSERT INTO mosaic.merchandising_assignment (
    product_id,
    media_tier,
    merchandising_title,
    shop_page,
    shop_position,
    is_flagship,
    is_retrieval_anchor,
    catalog_asset_key,
    detail_asset_key,
    metadata
)
SELECT
    s.product_id::bigint,
    s.media_tier::mosaic.media_tier,
    nullif(s.merchandising_title, ''),
    s.shop_page::smallint,
    s.shop_position::smallint,
    s.is_flagship::boolean,
    s.is_retrieval_anchor::boolean,
    nullif(s.catalog_asset_key, ''),
    nullif(s.detail_asset_key, ''),
    jsonb_build_object(
        'image_status', s.image_status,
        'source_title', s.source_title,
        'challenge_cohorts', string_to_array(s.challenge_cohorts, '|')
    )
FROM premium_cohort_stage s
JOIN mosaic.product p ON p.product_id = s.product_id::bigint
ON CONFLICT (product_id) DO UPDATE SET
    media_tier = EXCLUDED.media_tier,
    merchandising_title = EXCLUDED.merchandising_title,
    shop_page = EXCLUDED.shop_page,
    shop_position = EXCLUDED.shop_position,
    is_flagship = EXCLUDED.is_flagship,
    is_retrieval_anchor = EXCLUDED.is_retrieval_anchor,
    catalog_asset_key = EXCLUDED.catalog_asset_key,
    detail_asset_key = EXCLUDED.detail_asset_key,
    metadata = EXCLUDED.metadata;

CALL mosaic_search.refresh_product_documents(
    ARRAY(SELECT product_id::bigint FROM premium_cohort_stage)
);

SELECT media_tier, count(*)
FROM mosaic.merchandising_assignment
GROUP BY media_tier
ORDER BY media_tier;
