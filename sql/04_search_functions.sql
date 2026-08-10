\set ON_ERROR_STOP on

-- DEPRECATED: the `catalog.*` tree. The application does not read this schema;
-- `service/retrieval.py` queries `mosaic` and `mosaic_search` (see db/sql/).
-- Deleted by Phase 2 Unit E. See docs/rewrite-losses.md for what the rewrite
-- dropped and docs/superpowers/specs/ for the Phase 2 design.
-- Do not add features here. Do not point a lab at it.

CREATE OR REPLACE FUNCTION catalog.filter_match(p catalog.product, f jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
SELECT
    (NOT (f ? 'domain') OR (p).domain = f->>'domain') AND
    (NOT (f ? 'category') OR (p).category = f->>'category') AND
    (NOT (f ? 'subcategory') OR (p).subcategory = f->>'subcategory') AND
    (NOT (f ? 'brand') OR (p).brand = f->>'brand') AND
    (NOT (f ? 'availability') OR (p).availability = f->>'availability') AND
    (NOT (f ? 'max_price') OR (p).price_usd <= (f->>'max_price')::numeric) AND
    (NOT (f ? 'min_price') OR (p).price_usd >= (f->>'min_price')::numeric) AND
    (NOT (f ? 'min_rating') OR (p).rating >= (f->>'min_rating')::numeric) AND
    (NOT (f ? 'attributes') OR (p).attributes @> (f->'attributes'))
$$;

CREATE OR REPLACE FUNCTION catalog.search_lexical(
    q text,
    f jsonb DEFAULT '{}'::jsonb,
    candidate_limit integer DEFAULT 100
)
RETURNS TABLE(product_id bigint, lexical_score real, lexical_rank bigint)
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
WITH query AS (
    SELECT
        websearch_to_tsquery('english', q) AS strict_tsq,
        to_tsquery(
            'english',
            array_to_string(
                tsvector_to_array(to_tsvector('english', q)),
                ' | '
            )
        ) AS broad_tsq
), scored AS (
    SELECT
        p.product_id,
        (
            ts_rank_cd(p.search_document, query.broad_tsq, 32) +
            CASE
                WHEN p.search_document @@ query.strict_tsq THEN 1.0
                ELSE 0.0
            END
        )::real AS score
    FROM catalog.product p
    CROSS JOIN query
    WHERE p.search_document @@ query.broad_tsq
      AND catalog.filter_match(p, f)
    ORDER BY score DESC, p.product_id
    LIMIT candidate_limit
)
SELECT product_id, score, row_number() OVER (ORDER BY score DESC, product_id)
FROM scored
$$;

CREATE OR REPLACE FUNCTION catalog.search_trigram(
    q text,
    f jsonb DEFAULT '{}'::jsonb,
    candidate_limit integer DEFAULT 75,
    minimum_similarity real DEFAULT 0.24
)
RETURNS TABLE(product_id bigint, trigram_score real, trigram_rank bigint)
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
WITH tokens AS MATERIALIZED (
    SELECT DISTINCT token
    FROM regexp_split_to_table(lower(q), '[^a-z0-9]+') AS token
    WHERE length(token) >= 4
), token_stats AS (
    SELECT count(*)::integer AS token_count
    FROM tokens
), whole_query AS (
    SELECT
        p.product_id,
        greatest(
            similarity(p.trigram_text, lower(q)),
            word_similarity(lower(q), p.trigram_text)
        )::real AS score
    FROM catalog.product p
    WHERE catalog.filter_match(p, f)
      AND p.trigram_text % lower(q)
      AND greatest(
          similarity(p.trigram_text, lower(q)),
          word_similarity(lower(q), p.trigram_text)
      ) >= minimum_similarity
), token_query AS (
    SELECT
        p.product_id,
        least(
            1.0,
            max(word_similarity(tokens.token, p.trigram_text)) +
            0.04 * greatest(count(DISTINCT tokens.token) - 1, 0)
        )::real AS score
    FROM tokens
    JOIN catalog.product p
      ON tokens.token <% p.trigram_text
    CROSS JOIN token_stats
    WHERE catalog.filter_match(p, f)
    GROUP BY p.product_id, token_stats.token_count
    HAVING count(DISTINCT tokens.token) >=
        CASE WHEN token_stats.token_count >= 4 THEN 2 ELSE 1 END
       AND max(word_similarity(tokens.token, p.trigram_text)) >=
           minimum_similarity
), combined AS (
    SELECT product_id, score FROM whole_query
    UNION ALL
    SELECT product_id, score FROM token_query
), scored AS (
    SELECT product_id, max(score)::real AS score
    FROM combined
    GROUP BY product_id
    ORDER BY score DESC, product_id
    LIMIT candidate_limit
)
SELECT product_id, score, row_number() OVER (ORDER BY score DESC, product_id)
FROM scored
$$;

CREATE OR REPLACE FUNCTION catalog.search_semantic(
    query_embedding vector(1024),
    f jsonb DEFAULT '{}'::jsonb,
    candidate_limit integer DEFAULT 100
)
RETURNS TABLE(product_id bigint, semantic_score real, semantic_rank bigint)
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
WITH scored AS (
    SELECT
        p.product_id,
        (1 - (p.embedding <=> query_embedding))::real AS score
    FROM catalog.product p
    WHERE p.embedding IS NOT NULL
      AND catalog.filter_match(p, f)
    ORDER BY p.embedding <=> query_embedding
    LIMIT candidate_limit
)
SELECT product_id, score, row_number() OVER (ORDER BY score DESC, product_id)
FROM scored
$$;

CREATE OR REPLACE FUNCTION catalog.search_hybrid_rrf(
    q text,
    query_embedding vector(1024),
    f jsonb DEFAULT '{}'::jsonb,
    rrf_k integer DEFAULT 60,
    lexical_limit integer DEFAULT 100,
    trigram_limit integer DEFAULT 75,
    semantic_limit integer DEFAULT 100,
    result_limit integer DEFAULT 50,
    lexical_weight real DEFAULT 0.30,
    trigram_weight real DEFAULT 0.10,
    semantic_weight real DEFAULT 0.45
)
RETURNS TABLE(
    product_id bigint,
    sku text,
    title text,
    short_description text,
    domain text,
    category text,
    subcategory text,
    brand text,
    model text,
    price_usd numeric,
    list_price_usd numeric,
    rating numeric,
    review_count integer,
    availability text,
    inventory_count integer,
    attributes jsonb,
    tags jsonb,
    updated_at timestamptz,
    image_url text,
    image_source text,
    lexical_rank integer,
    lexical_score real,
    lexical_contribution double precision,
    trigram_rank integer,
    trigram_score real,
    trigram_contribution double precision,
    semantic_rank integer,
    semantic_score real,
    semantic_contribution double precision,
    rrf_score double precision,
    pre_rerank_rank integer,
    business_score real
)
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
WITH lexical AS MATERIALIZED (
    SELECT * FROM catalog.search_lexical(q, f, lexical_limit)
), typo AS MATERIALIZED (
    SELECT * FROM catalog.search_trigram(q, f, trigram_limit, 0.24)
), semantic AS MATERIALIZED (
    SELECT * FROM catalog.search_semantic(query_embedding, f, semantic_limit)
), candidate_ids AS (
    SELECT product_id FROM lexical
    UNION
    SELECT product_id FROM typo
    UNION
    SELECT product_id FROM semantic
), fused AS (
    SELECT
        candidate_ids.product_id,
        lexical.lexical_rank::integer,
        lexical.lexical_score,
        CASE WHEN lexical.lexical_rank IS NOT NULL
             THEN lexical_weight / (rrf_k + lexical.lexical_rank)
        END AS lexical_contribution,
        typo.trigram_rank::integer,
        typo.trigram_score,
        CASE WHEN typo.trigram_rank IS NOT NULL
             THEN trigram_weight / (rrf_k + typo.trigram_rank)
        END AS trigram_contribution,
        semantic.semantic_rank::integer,
        semantic.semantic_score,
        CASE WHEN semantic.semantic_rank IS NOT NULL
             THEN semantic_weight / (rrf_k + semantic.semantic_rank)
        END AS semantic_contribution
    FROM candidate_ids
    LEFT JOIN lexical USING (product_id)
    LEFT JOIN typo USING (product_id)
    LEFT JOIN semantic USING (product_id)
), enriched AS (
    SELECT
        p.*,
        fused.lexical_rank,
        fused.lexical_score,
        fused.lexical_contribution,
        fused.trigram_rank,
        fused.trigram_score,
        fused.trigram_contribution,
        fused.semantic_rank,
        fused.semantic_score,
        fused.semantic_contribution,
        (
            coalesce(fused.lexical_contribution, 0) +
            coalesce(fused.trigram_contribution, 0) +
            coalesce(fused.semantic_contribution, 0)
        )::double precision AS fused_rrf_score,
        (
            0.45 * p.quality_score +
            0.30 * p.popularity_score +
            0.15 * p.freshness_score +
            0.10 * CASE
                WHEN p.availability = 'In Stock' THEN 1
                WHEN p.availability = 'Low Stock' THEN 0.5
                ELSE 0
            END
        )::real AS computed_business_score
    FROM fused
    JOIN catalog.product p USING (product_id)
), ranked AS (
    SELECT
        enriched.*,
        row_number() OVER (
            ORDER BY fused_rrf_score DESC, computed_business_score DESC, product_id
        )::integer AS computed_pre_rerank_rank
    FROM enriched
)
SELECT
    r.product_id,
    r.sku,
    r.title,
    r.short_description,
    r.domain,
    r.category,
    r.subcategory,
    r.brand,
    r.model,
    r.price_usd,
    r.list_price_usd,
    r.rating,
    r.review_count,
    r.availability,
    r.inventory_count,
    r.attributes,
    r.tags,
    r.updated_at,
    media.image_url,
    media.image_source,
    r.lexical_rank,
    r.lexical_score,
    r.lexical_contribution,
    r.trigram_rank,
    r.trigram_score,
    r.trigram_contribution,
    r.semantic_rank,
    r.semantic_score,
    r.semantic_contribution,
    r.fused_rrf_score,
    r.computed_pre_rerank_rank,
    r.computed_business_score
FROM ranked r
LEFT JOIN catalog.product_media media
  ON media.product_id = r.product_id
 AND media.role = 'primary'
 AND media.sort_order = 0
ORDER BY r.computed_pre_rerank_rank
LIMIT result_limit
$$;

COMMENT ON FUNCTION catalog.search_hybrid_rrf IS
'Applies hard filters inside every arm, then performs weighted reciprocal-rank fusion. Raw scores and rank contributions remain separate diagnostics.';
