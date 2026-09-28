\set ON_ERROR_STOP on

-- Weighted RRF, shipped as a runnable comparison rather than a behavior change.
--
-- `search_hybrid_rrf` above is NOT modified and remains the served path. The
-- decision to make this the default is reserved for an explicit ruling, so it
-- cannot happen by drift; see db/config/retrieval.yaml beside `fusion.weights`.
--
-- The three arm CTEs, their caps, and their per-arm ranks are byte-identical to
-- the unweighted function. The ONLY difference is the fusion arithmetic:
-- each channel's `1 / (k + rank)` contribution is multiplied by that arm's
-- weight. Identical arms in, different order out — asserted per call by the
-- diagnostics endpoint rather than trusted.
--
-- Weights arrive as parameters from `fusion.weights` in the yaml via
-- scripts/retrieval_profile.py. Their DEFAULTs are the ported historical values
-- (LOSS-3) and are pinned by scripts/config_tripwire.py, so a coefficient
-- cannot be invented here or drift from the yaml.
--
-- Substrate: this is a `LANGUAGE sql` function over the same three `LANGUAGE
-- sql` arm functions, so it inherits LOSS-4's verdict from birth — each arm is
-- an optimization fence, its `ORDER BY ... LIMIT` is evaluated to completion,
-- and no `MATERIALIZED` hint is required for the per-arm caps to hold.
--
-- The RETURNS TABLE shape matches `search_hybrid_rrf` exactly, including the
-- `provenance` jsonb, so the diagnostics endpoint aligns rows from both
-- functions without translating either.
DROP FUNCTION IF EXISTS mosaic_search.search_hybrid_rrf_weighted(
    text, vector, jsonb, integer, integer, integer, integer, integer, real,
    real, real, real, real
);

CREATE OR REPLACE FUNCTION mosaic_search.search_hybrid_rrf_weighted(
    q text,
    query_embedding vector(1024),
    f jsonb DEFAULT '{}'::jsonb,
    rrf_k integer DEFAULT 60,
    fts_limit integer DEFAULT 120,
    trigram_limit integer DEFAULT 80,
    semantic_limit integer DEFAULT 150,
    result_limit integer DEFAULT 50,
    trigram_threshold real DEFAULT 0.20,
    weight_lexical real DEFAULT 0.30,
    weight_semantic real DEFAULT 0.45,
    weight_trigram real DEFAULT 0.10
)
RETURNS TABLE (
    product_id bigint,
    title text,
    brand_name text,
    category_path text,
    price_cents bigint,
    availability mosaic.availability_status,
    rating numeric,
    catalog_asset_key text,
    canonical_group_id text,
    fts_score real,
    trigram_score real,
    semantic_score real,
    fts_rank bigint,
    trigram_rank bigint,
    semantic_rank bigint,
    rrf_score double precision,
    pre_rerank_score double precision,
    provenance jsonb
)
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
WITH fts AS (
    SELECT * FROM mosaic_search.search_fts(q, f, fts_limit)
), typo AS (
    SELECT * FROM mosaic_search.search_trigram(
        q, f, trigram_limit, trigram_threshold
    )
), semantic AS (
    SELECT product_id, semantic_score, semantic_rank
    FROM mosaic_search.search_vector(query_embedding, f, semantic_limit)
), channels AS (
    -- `contribution` carries the weighted value so the fused sum and the
    -- per-channel provenance agree. `unweighted_contribution` is kept beside it
    -- so a participant can read what the weight did to each arm, which is the
    -- entire point of the comparison.
    SELECT product_id, 'fts'::text AS channel, fts_rank AS source_rank,
           fts_score AS raw_score,
           weight_lexical * mosaic_search.reciprocal_rank_contribution(
               fts_rank, rrf_k
           ) AS contribution,
           mosaic_search.reciprocal_rank_contribution(
               fts_rank, rrf_k
           ) AS unweighted_contribution,
           weight_lexical AS weight
    FROM fts
    UNION ALL
    SELECT product_id, 'trigram', trigram_rank,
           trigram_score,
           weight_trigram * mosaic_search.reciprocal_rank_contribution(
               trigram_rank, rrf_k
           ),
           mosaic_search.reciprocal_rank_contribution(trigram_rank, rrf_k),
           weight_trigram
    FROM typo
    UNION ALL
    SELECT product_id, 'vector', semantic_rank,
           semantic_score,
           weight_semantic * mosaic_search.reciprocal_rank_contribution(
               semantic_rank, rrf_k
           ),
           mosaic_search.reciprocal_rank_contribution(semantic_rank, rrf_k),
           weight_semantic
    FROM semantic
), fused AS (
    SELECT product_id,
           sum(contribution)::double precision AS rrf_score,
           sum(unweighted_contribution)::double precision AS unweighted_rrf_score,
           max(raw_score) FILTER (WHERE channel = 'fts')::real AS fts_score,
           max(raw_score) FILTER (WHERE channel = 'trigram')::real AS trigram_score,
           max(raw_score) FILTER (WHERE channel = 'vector')::real AS semantic_score,
           min(source_rank) FILTER (WHERE channel = 'fts') AS fts_rank,
           min(source_rank) FILTER (WHERE channel = 'trigram') AS trigram_rank,
           min(source_rank) FILTER (WHERE channel = 'vector') AS semantic_rank,
           jsonb_object_agg(channel, jsonb_build_object(
               'rank', source_rank,
               'raw_score', raw_score,
               'rrf_contribution', contribution,
               'unweighted_rrf_contribution', unweighted_contribution,
               'weight', weight
           )) AS channel_provenance
    FROM channels
    GROUP BY product_id
), enriched AS (
    SELECT d.product_id,
           d.title,
           d.brand_name,
           d.category_path,
           d.price_cents,
           d.availability,
           d.rating,
           d.catalog_asset_key,
           d.canonical_group_id,
           d.challenge_cohorts,
           d.is_retrieval_anchor,
           fused.rrf_score,
           fused.unweighted_rrf_score,
           fused.fts_score,
           fused.trigram_score,
           fused.semantic_score,
           fused.fts_rank,
           fused.trigram_rank,
           fused.semantic_rank,
           fused.channel_provenance
    FROM fused
    JOIN mosaic_search.product_document d USING (product_id)
)
SELECT
    e.product_id,
    e.title,
    e.brand_name,
    e.category_path,
    e.price_cents,
    e.availability,
    e.rating,
    e.catalog_asset_key,
    e.canonical_group_id,
    e.fts_score,
    e.trigram_score,
    e.semantic_score,
    e.fts_rank,
    e.trigram_rank,
    e.semantic_rank,
    e.rrf_score,
    e.rrf_score AS pre_rerank_score,
    jsonb_build_object(
        'channels', e.channel_provenance,
        'challenge_cohorts', e.challenge_cohorts,
        'is_retrieval_anchor', e.is_retrieval_anchor,
        -- Fusion identity and inputs travel with every row, so a persisted
        -- candidate can be re-scored later without joining anything.
        'fusion', jsonb_build_object(
            'method', 'weighted_reciprocal_rank_fusion',
            'rrf_k', rrf_k,
            'weights', jsonb_build_object(
                'lexical', weight_lexical,
                'semantic', weight_semantic,
                'trigram', weight_trigram
            ),
            'unweighted_rrf_score', e.unweighted_rrf_score
        )
    ) AS provenance
FROM enriched e
ORDER BY e.rrf_score DESC, e.product_id
LIMIT greatest(result_limit, 1)
$$;
