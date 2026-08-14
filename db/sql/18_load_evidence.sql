\set ON_ERROR_STOP on

\if :{?review_evidence_path}
\else
  \set review_evidence_path 'data/sample/reviews_15000.csv.gz'
\endif

\setenv MOSAIC_REVIEW_EVIDENCE_PATH :review_evidence_path

CREATE TEMP TABLE review_evidence_stage (
    review_id bigint,
    product_id bigint,
    rating numeric,
    title text,
    body text,
    verified_purchase boolean,
    helpful_votes integer,
    review_date date,
    sentiment_score numeric
);

\copy review_evidence_stage FROM PROGRAM 'gzip -cd "$MOSAIC_REVIEW_EVIDENCE_PATH"' WITH (FORMAT csv, HEADER true)

DELETE FROM mosaic.product_evidence
WHERE source_name = 'Mosaic catalog specification'
   OR source_reference LIKE 'mosaic://evidence/review/%';

INSERT INTO mosaic.product_evidence (
    product_id,
    evidence_type,
    source_name,
    source_reference,
    evidence_title,
    evidence_text,
    source_date,
    is_verified,
    metadata,
    trigram_text,
    embedding_text
)
SELECT
    d.product_id,
    'product_spec'::mosaic.evidence_type,
    'Mosaic catalog specification',
    format('mosaic://evidence/product-spec/%s', d.product_id),
    d.title || ' specifications',
    concat_ws(
        ' ',
        d.title || '.',
        d.short_description,
        'Availability: ' || d.availability::text || '.',
        'Price: ' || d.price_cents || ' cents.',
        'Attributes: ' || d.attributes::text
    ),
    d.updated_at::date,
    true,
    jsonb_build_object(
        'sku', d.sku,
        'domain', d.domain,
        'category_key', d.category_key,
        'attributes', d.attributes
    ),
    lower(concat_ws(' ', d.title, d.brand_name, d.model_name, d.sku)),
    concat_ws(' ', d.title, d.short_description, d.attributes::text)
FROM mosaic_search.product_document d
ORDER BY d.product_id;

INSERT INTO mosaic.product_evidence (
    product_id,
    evidence_type,
    source_name,
    source_reference,
    evidence_title,
    evidence_text,
    source_date,
    rating,
    is_verified,
    metadata,
    trigram_text,
    embedding_text
)
SELECT
    r.product_id,
    'customer_review'::mosaic.evidence_type,
    'Mosaic synthetic review corpus',
    format('mosaic://evidence/review/%s', r.review_id),
    r.title,
    r.body,
    r.review_date,
    r.rating,
    r.verified_purchase,
    jsonb_build_object(
        'review_id', r.review_id,
        'helpful_votes', r.helpful_votes,
        'sentiment_score', r.sentiment_score
    ),
    lower(concat_ws(' ', r.title, r.body)),
    concat_ws(' ', r.title, r.body)
FROM review_evidence_stage r
JOIN mosaic.product p USING (product_id)
ORDER BY r.review_id;

SELECT evidence_type, count(*)
FROM mosaic.product_evidence
WHERE source_name IN (
    'Mosaic catalog specification',
    'Mosaic synthetic review corpus'
)
GROUP BY evidence_type
ORDER BY evidence_type;
