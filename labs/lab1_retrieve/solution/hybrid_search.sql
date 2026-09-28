-- Lab 1: hybrid search.
--
-- mosaic_search.search_hybrid_rrf asks three channels for candidates from the
-- same filtered catalog: full-text search, close spelling (pg_trgm) and meaning
-- search (pgvector HNSW). It fuses their ranks with the contribution Lab 2's
-- file defines, then returns the pool the service reranks. Reranking can only
-- reorder that pool, so a channel left out here is a product no later stage can
-- recover. The two marked blocks are Lab 1's edit; README.md beside this file
-- has the task, the commands and the reference answer.

-- Unit D added the `trigram_threshold` parameter. `CREATE OR REPLACE` cannot
-- change a signature, so on an already-deployed cluster it creates an OVERLOAD
-- and leaves the 9-argument version live. A caller passing 9 positional
-- arguments then silently binds the old body. Dropping the previous signature
-- explicitly is the only way the replacement is a replacement.
DROP FUNCTION IF EXISTS mosaic_search.search_hybrid_rrf(
    text, vector, jsonb, integer, integer, integer, integer, integer, real
);
DROP FUNCTION IF EXISTS mosaic_search.search_hybrid_rrf(
    text, vector, jsonb, integer, integer, integer, integer, integer, real, real
);

CREATE OR REPLACE FUNCTION mosaic_search.search_hybrid_rrf(
    q text,
    query_embedding vector(1024),
    f jsonb DEFAULT '{}'::jsonb,
    rrf_k integer DEFAULT 60,
    fts_limit integer DEFAULT 120,
    trigram_limit integer DEFAULT 80,
    semantic_limit integer DEFAULT 150,
    result_limit integer DEFAULT 50,
    -- Threaded through rather than hardcoded at the call site below. A
    -- positional literal there was invisible to scripts/config_tripwire.py,
    -- whose rule 1 only sees assignment-shaped declarations; as a named
    -- parameter it is an exempted default that the tripwire pins to
    -- candidate_generation.trigram_threshold and asserts equal.
    trigram_threshold real DEFAULT 0.20
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
)
-- Lab 1 edit, 1 of 2: close-spelling candidates. See README.md beside this file.
-- LAB1_TRIGRAM_CTE_START
, typo AS (
    SELECT * FROM mosaic_search.search_trigram(
        q, f, trigram_limit, trigram_threshold
    )
)
-- LAB1_TRIGRAM_CTE_END
, semantic AS (
    SELECT product_id, semantic_score, semantic_rank
    FROM mosaic_search.search_vector(query_embedding, f, semantic_limit)
), channels AS (
    SELECT product_id, 'fts'::text AS channel, fts_rank AS source_rank,
           fts_score AS raw_score,
           mosaic_search.reciprocal_rank_contribution(
               fts_rank, rrf_k
           ) AS contribution
    FROM fts
-- Lab 1 edit, 2 of 2: the close-spelling channel.
-- LAB1_TRIGRAM_CHANNEL_START
    UNION ALL
    SELECT product_id, 'trigram', trigram_rank,
           trigram_score,
           mosaic_search.reciprocal_rank_contribution(trigram_rank, rrf_k)
    FROM typo
-- LAB1_TRIGRAM_CHANNEL_END
    UNION ALL
    SELECT product_id, 'vector', semantic_rank,
           semantic_score,
           mosaic_search.reciprocal_rank_contribution(semantic_rank, rrf_k)
    FROM semantic
), fused AS (
    SELECT product_id,
           sum(contribution)::double precision AS rrf_score,
           max(raw_score) FILTER (WHERE channel = 'fts')::real AS fts_score,
           max(raw_score) FILTER (WHERE channel = 'trigram')::real AS trigram_score,
           max(raw_score) FILTER (WHERE channel = 'vector')::real AS semantic_score,
           min(source_rank) FILTER (WHERE channel = 'fts') AS fts_rank,
           min(source_rank) FILTER (WHERE channel = 'trigram') AS trigram_rank,
           min(source_rank) FILTER (WHERE channel = 'vector') AS semantic_rank,
           jsonb_object_agg(channel, jsonb_build_object(
               'rank', source_rank,
               'raw_score', raw_score,
               'rrf_contribution', contribution
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
        'is_retrieval_anchor', e.is_retrieval_anchor
    ) AS provenance
FROM enriched e
ORDER BY e.rrf_score DESC, e.product_id
LIMIT greatest(result_limit, 1)
$$;
