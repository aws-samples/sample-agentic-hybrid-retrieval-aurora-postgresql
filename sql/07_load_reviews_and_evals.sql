\set ON_ERROR_STOP on
CREATE TEMP TABLE review_raw (
    review_id text, product_id text, rating text, title text, body text,
    verified_purchase text, helpful_votes text, review_date text, sentiment_score text
);
\copy review_raw FROM PROGRAM 'gzip -dc data/sample/reviews_15000.csv.gz' WITH (FORMAT csv, HEADER true)

INSERT INTO catalog.product_review(
    review_id, product_id, rating, title, body, verified_purchase,
    helpful_votes, review_date, sentiment_score
)
OVERRIDING SYSTEM VALUE
SELECT
    review.review_id::bigint,
    review.product_id::bigint,
    review.rating::smallint,
    review.title,
    review.body,
    review.verified_purchase::boolean,
    review.helpful_votes::integer,
    review.review_date::date,
    review.sentiment_score::real
FROM review_raw AS review
JOIN catalog.product AS product
  ON product.product_id = review.product_id::bigint
ON CONFLICT (review_id) DO UPDATE SET
    product_id = EXCLUDED.product_id,
    rating = EXCLUDED.rating,
    title = EXCLUDED.title,
    body = EXCLUDED.body,
    verified_purchase = EXCLUDED.verified_purchase,
    helpful_votes = EXCLUDED.helpful_votes,
    review_date = EXCLUDED.review_date,
    sentiment_score = EXCLUDED.sentiment_score;

SELECT setval(
    pg_get_serial_sequence('catalog.product_review', 'review_id'),
    greatest(coalesce(max(review_id), 0), 1),
    max(review_id) IS NOT NULL
)
FROM catalog.product_review;

CREATE TEMP TABLE query_json(line text);
\copy query_json FROM 'data/evals/queries.jsonl'
INSERT INTO catalog_eval.query(query_id, query_text, domain, intent, filters, expected_techniques, target_product_id, notes)
SELECT line::jsonb->>'query_id', line::jsonb->>'query', line::jsonb->>'domain', line::jsonb->>'intent',
       coalesce(line::jsonb->'filters','{}'::jsonb), coalesce(line::jsonb->'expected_techniques','[]'::jsonb),
       nullif(line::jsonb->>'target_product_id','')::bigint, line::jsonb->>'notes'
FROM query_json
ON CONFLICT (query_id) DO UPDATE SET query_text=EXCLUDED.query_text, filters=EXCLUDED.filters;

CREATE TEMP TABLE judgment_raw(query_id text, product_id text, relevance_grade text, reason text);
\copy judgment_raw FROM PROGRAM 'gzip -dc data/evals/judgments.csv.gz' WITH (FORMAT csv, HEADER true)
INSERT INTO catalog_eval.judgment(query_id, product_id, relevance_grade, reason)
SELECT
    judgment.query_id,
    judgment.product_id::bigint,
    judgment.relevance_grade::smallint,
    judgment.reason
FROM judgment_raw AS judgment
JOIN catalog.product AS product
  ON product.product_id = judgment.product_id::bigint
ON CONFLICT (query_id, product_id) DO UPDATE SET relevance_grade=EXCLUDED.relevance_grade, reason=EXCLUDED.reason;

SELECT (SELECT count(*) FROM catalog.product_review) AS reviews,
       (SELECT count(*) FROM catalog_eval.query) AS eval_queries,
       (SELECT count(*) FROM catalog_eval.judgment) AS judgments;
