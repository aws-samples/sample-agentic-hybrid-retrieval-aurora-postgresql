\set ON_ERROR_STOP on

CREATE OR REPLACE FUNCTION mosaic_search.matches_filters(
    d mosaic_search.product_document,
    f jsonb
)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
SELECT
    (NOT (f ? 'domain') OR (d).domain = (f->>'domain')::mosaic.product_domain) AND
    (NOT (f ? 'category_key') OR (d).category_key = f->>'category_key') AND
    (NOT (f ? 'brand') OR lower((d).brand_name) = lower(f->>'brand')) AND
    (NOT (f ? 'brands') OR jsonb_array_length(f->'brands') = 0 OR (d).brand_name = ANY (ARRAY(SELECT jsonb_array_elements_text(f->'brands')))) AND
    (NOT (f ? 'min_price_cents') OR (d).price_cents >= (f->>'min_price_cents')::bigint) AND
    (NOT (f ? 'max_price_cents') OR (d).price_cents <= (f->>'max_price_cents')::bigint) AND
    (NOT (f ? 'availability') OR (d).availability = (f->>'availability')::mosaic.availability_status) AND
    (NOT coalesce((f->>'in_stock_only')::boolean, false) OR (d).availability IN ('in_stock','low_stock')) AND
    (NOT (f ? 'min_rating') OR coalesce((d).rating, 0) >= (f->>'min_rating')::numeric) AND
    -- The right operand needs parentheses: `@>` and `->` share a precedence
    -- level and associate left, so `a @> f->'k'` parses as `(a @> f)->'k'`,
    -- which fails with "operator does not exist: boolean -> unknown".
    (NOT (f ? 'attributes') OR (d).attributes @> (f->'attributes')) AND
    (coalesce((f->>'include_refurbished')::boolean, false) OR NOT (d).is_refurbished) AND
    (coalesce((f->>'include_sponsored')::boolean, false) OR NOT (d).is_sponsored)
$$;

CREATE OR REPLACE FUNCTION mosaic_search.configure_hnsw(
    p_ef_search integer DEFAULT 100,
    p_iterative_scan text DEFAULT 'relaxed_order',
    p_max_scan_tuples integer DEFAULT 20000,
    p_scan_mem_multiplier real DEFAULT 1
)
RETURNS void
LANGUAGE plpgsql
VOLATILE
AS $$
BEGIN
    IF p_ef_search < 1 OR p_ef_search > 1000 THEN
        RAISE EXCEPTION 'ef_search must be between 1 and 1000';
    END IF;
    IF p_iterative_scan NOT IN ('off', 'strict_order', 'relaxed_order') THEN
        RAISE EXCEPTION 'iterative_scan must be off, strict_order, or relaxed_order';
    END IF;
    IF p_max_scan_tuples < 1 THEN
        RAISE EXCEPTION 'max_scan_tuples must be positive';
    END IF;
    IF p_scan_mem_multiplier < 1 THEN
        RAISE EXCEPTION 'scan_mem_multiplier must be at least 1';
    END IF;

    PERFORM set_config('hnsw.ef_search', p_ef_search::text, true);
    PERFORM set_config('hnsw.iterative_scan', p_iterative_scan, true);
    PERFORM set_config('hnsw.max_scan_tuples', p_max_scan_tuples::text, true);
    PERFORM set_config('hnsw.scan_mem_multiplier', p_scan_mem_multiplier::text, true);
END
$$;

CREATE OR REPLACE FUNCTION mosaic_search.search_fts(
    q text,
    f jsonb DEFAULT '{}'::jsonb,
    candidate_limit integer DEFAULT 120
)
RETURNS TABLE (
    product_id bigint,
    fts_score real,
    fts_rank bigint
)
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
-- `websearch_to_tsquery` ANDs every term. A conversational query needs every
-- token present in one document, and a misspelled token exists in no document,
-- so the conjunction is unsatisfiable and this arm returns zero rows. Measured
-- on the live 500k-product corpus, four of the six workshop missions lost the
-- lexical arm entirely, including two that declare `fts`.
WITH query AS (
    SELECT
        websearch_to_tsquery('english', q) AS strict_tsq,
        -- OR-combined lexemes, for recall.
        to_tsquery(
            'english',
            array_to_string(
                tsvector_to_array(to_tsvector('english', q)),
                ' | '
            )
        ) AS broad_tsq
), guarded AS (
    SELECT
        strict_tsq,
        broad_tsq,
        -- `tsvector_to_array` discards the NOT operator, so a naive OR-combine
        -- inverts a user's exclusion: 'headphon' & !'wireless' would widen to
        -- 'headphon' | 'wireless' and admit the very rows they excluded. When
        -- the strict query negates, require the strict match as well.
        -- `websearch_to_tsquery` strips literal punctuation, so a `!` in the
        -- rendered tsquery is always negation, never user text.
        strict_tsq::text LIKE '%!%' AS has_negation
    FROM query
), scored AS (
    SELECT d.product_id,
           (
               ts_rank_cd(d.search_document, g.broad_tsq, 32)
               -- The strict match is kept as a scoring bonus so exact identity
               -- still dominates: the target holds rank 1 by 2.5x.
               + CASE WHEN d.search_document @@ g.strict_tsq THEN 1.0 ELSE 0.0 END
           )::real AS score
    FROM mosaic_search.product_document d
    CROSS JOIN guarded g
    WHERE d.search_document @@ g.broad_tsq
      AND (NOT g.has_negation OR d.search_document @@ g.strict_tsq)
      AND mosaic_search.matches_filters(d, f)
    ORDER BY score DESC, d.product_id
    LIMIT greatest(candidate_limit, 1)
)
SELECT product_id,
       score,
       row_number() OVER (ORDER BY score DESC, product_id)
FROM scored
$$;

CREATE OR REPLACE FUNCTION mosaic_search.search_trigram(
    q text,
    f jsonb DEFAULT '{}'::jsonb,
    candidate_limit integer DEFAULT 80,
    minimum_similarity real DEFAULT 0.20
)
RETURNS TABLE (
    product_id bigint,
    trigram_score real,
    trigram_rank bigint
)
LANGUAGE sql
STABLE
PARALLEL SAFE
SET pg_trgm.similarity_threshold = 0.18
-- `<%` reads word_similarity_threshold, not similarity_threshold. Without this
-- the OR'd gate below would inherit whatever the session left behind.
SET pg_trgm.word_similarity_threshold = 0.5
AS $$
WITH scored AS (
    SELECT d.product_id,
           greatest(
               similarity(d.trigram_text, lower(q)),
               word_similarity(lower(q), d.trigram_text),
               strict_word_similarity(lower(q), d.trigram_text)
           )::real AS score
    FROM mosaic_search.product_document d
    WHERE mosaic_search.matches_filters(d, f)
      -- Both index-backed gates, OR'd. `%` compares whole strings, so on a
      -- concatenated document it dilutes to near-zero: "auralux" against a
      -- 90-character trigram_text scores 0.11 and is rejected, even though
      -- word_similarity scores 0.875. Gating on `%` alone made the typo
      -- recovery arm unable to recover typos. `<%` is supported by the same
      -- GIN/GiST trgm index, so this stays indexable.
      AND (d.trigram_text % lower(q) OR lower(q) <% d.trigram_text)
      AND greatest(
          similarity(d.trigram_text, lower(q)),
          word_similarity(lower(q), d.trigram_text),
          strict_word_similarity(lower(q), d.trigram_text)
      ) >= minimum_similarity
    ORDER BY score DESC, d.product_id
    LIMIT greatest(candidate_limit, 1)
)
SELECT product_id,
       score,
       row_number() OVER (ORDER BY score DESC, product_id)
FROM scored
$$;

CREATE OR REPLACE FUNCTION mosaic_search.search_vector(
    query_embedding vector(1024),
    f jsonb DEFAULT '{}'::jsonb,
    candidate_limit integer DEFAULT 150
)
RETURNS TABLE (
    product_id bigint,
    cosine_distance double precision,
    semantic_score real,
    semantic_rank bigint
)
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
WITH scored AS (
    SELECT d.product_id,
           d.embedding <=> query_embedding AS distance
    FROM mosaic_search.product_document d
    WHERE d.embedding IS NOT NULL
      AND mosaic_search.matches_filters(d, f)
    ORDER BY d.embedding <=> query_embedding
    LIMIT greatest(candidate_limit, 1)
)
SELECT product_id,
       distance,
       (1 - distance)::real,
       row_number() OVER (ORDER BY distance, product_id)
FROM scored
$$;

-- Unit D added the `trigram_threshold` parameter. `CREATE OR REPLACE` cannot
-- change a signature, so on an already-deployed cluster it creates an OVERLOAD
-- and leaves the 9-argument version live. A caller passing 9 positional
-- arguments then silently binds the old body. Dropping the previous signature
-- explicitly is the only way the replacement is a replacement.
DROP FUNCTION IF EXISTS mosaic_search.search_hybrid_rrf(
    text, vector, jsonb, integer, integer, integer, integer, integer, real
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
    business_weight real DEFAULT 0.003,
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
    business_score real,
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
    SELECT product_id, 'fts'::text AS channel, fts_rank AS source_rank,
           fts_score AS raw_score, 1.0 / (rrf_k + fts_rank) AS contribution
    FROM fts
    UNION ALL
    SELECT product_id, 'trigram', trigram_rank,
           trigram_score, 1.0 / (rrf_k + trigram_rank)
    FROM typo
    UNION ALL
    SELECT product_id, 'vector', semantic_rank,
           semantic_score, 1.0 / (rrf_k + semantic_rank)
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
    SELECT d.*,
           fused.rrf_score,
           fused.fts_score,
           fused.trigram_score,
           fused.semantic_score,
           fused.fts_rank,
           fused.trigram_rank,
           fused.semantic_rank,
           fused.channel_provenance,
           (
               0.40 * d.quality_score +
               0.25 * d.popularity_score +
               0.15 * d.freshness_score +
               0.10 * d.metadata_completeness +
               0.10 * CASE d.availability
                         WHEN 'in_stock' THEN 1.0
                         WHEN 'low_stock' THEN 0.5
                         ELSE 0.0
                      END
           )::real AS business_score
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
    e.business_score,
    e.rrf_score + business_weight * e.business_score AS pre_rerank_score,
    jsonb_build_object(
        'channels', e.channel_provenance,
        'business', jsonb_build_object(
            'quality', e.quality_score,
            'popularity', e.popularity_score,
            'freshness', e.freshness_score,
            'metadata_completeness', e.metadata_completeness,
            'availability', e.availability
        ),
        'challenge_cohorts', e.challenge_cohorts,
        'is_retrieval_anchor', e.is_retrieval_anchor
    ) AS provenance
FROM enriched e
ORDER BY pre_rerank_score DESC, e.product_id
LIMIT greatest(result_limit, 1)
$$;

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
CREATE OR REPLACE FUNCTION mosaic_search.search_hybrid_rrf_weighted(
    q text,
    query_embedding vector(1024),
    f jsonb DEFAULT '{}'::jsonb,
    rrf_k integer DEFAULT 60,
    fts_limit integer DEFAULT 120,
    trigram_limit integer DEFAULT 80,
    semantic_limit integer DEFAULT 150,
    result_limit integer DEFAULT 50,
    business_weight real DEFAULT 0.003,
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
    business_score real,
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
           weight_lexical * (1.0 / (rrf_k + fts_rank)) AS contribution,
           1.0 / (rrf_k + fts_rank) AS unweighted_contribution,
           weight_lexical AS weight
    FROM fts
    UNION ALL
    SELECT product_id, 'trigram', trigram_rank,
           trigram_score,
           weight_trigram * (1.0 / (rrf_k + trigram_rank)),
           1.0 / (rrf_k + trigram_rank),
           weight_trigram
    FROM typo
    UNION ALL
    SELECT product_id, 'vector', semantic_rank,
           semantic_score,
           weight_semantic * (1.0 / (rrf_k + semantic_rank)),
           1.0 / (rrf_k + semantic_rank),
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
    SELECT d.*,
           fused.rrf_score,
           fused.unweighted_rrf_score,
           fused.fts_score,
           fused.trigram_score,
           fused.semantic_score,
           fused.fts_rank,
           fused.trigram_rank,
           fused.semantic_rank,
           fused.channel_provenance,
           (
               0.40 * d.quality_score +
               0.25 * d.popularity_score +
               0.15 * d.freshness_score +
               0.10 * d.metadata_completeness +
               0.10 * CASE d.availability
                         WHEN 'in_stock' THEN 1.0
                         WHEN 'low_stock' THEN 0.5
                         ELSE 0.0
                      END
           )::real AS business_score
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
    e.business_score,
    e.rrf_score + business_weight * e.business_score AS pre_rerank_score,
    jsonb_build_object(
        'channels', e.channel_provenance,
        'business', jsonb_build_object(
            'quality', e.quality_score,
            'popularity', e.popularity_score,
            'freshness', e.freshness_score,
            'metadata_completeness', e.metadata_completeness,
            'availability', e.availability
        ),
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
ORDER BY pre_rerank_score DESC, e.product_id
LIMIT greatest(result_limit, 1)
$$;

CREATE OR REPLACE FUNCTION mosaic_search.search_product_evidence(
    p_product_id bigint,
    q text,
    query_embedding vector(1024),
    p_evidence_types mosaic.evidence_type[] DEFAULT NULL,
    result_limit integer DEFAULT 8
)
RETURNS TABLE (
    evidence_id bigint,
    evidence_type mosaic.evidence_type,
    source_name text,
    evidence_title text,
    evidence_text text,
    lexical_score real,
    semantic_score real,
    fused_score double precision,
    metadata jsonb
)
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
WITH lexical AS (
    SELECT e.evidence_id,
           ts_rank_cd(e.evidence_document, websearch_to_tsquery('english', q), 32)::real AS score,
           row_number() OVER (
               ORDER BY ts_rank_cd(e.evidence_document, websearch_to_tsquery('english', q), 32) DESC, e.evidence_id
           ) AS rank
    FROM mosaic.product_evidence e
    WHERE e.product_id = p_product_id
      AND (p_evidence_types IS NULL OR e.evidence_type = ANY (p_evidence_types))
      AND e.evidence_document @@ websearch_to_tsquery('english', q)
    ORDER BY score DESC, e.evidence_id
    LIMIT 50
), semantic AS (
    SELECT e.evidence_id,
           (1 - (e.embedding <=> query_embedding))::real AS score,
           row_number() OVER (ORDER BY e.embedding <=> query_embedding, e.evidence_id) AS rank
    FROM mosaic.product_evidence e
    WHERE e.product_id = p_product_id
      AND e.embedding IS NOT NULL
      AND (p_evidence_types IS NULL OR e.evidence_type = ANY (p_evidence_types))
    ORDER BY e.embedding <=> query_embedding
    LIMIT 50
), fused AS (
    SELECT coalesce(l.evidence_id, s.evidence_id) AS evidence_id,
           l.score AS lexical_score,
           s.score AS semantic_score,
           coalesce(1.0 / (60 + l.rank), 0) + coalesce(1.0 / (60 + s.rank), 0) AS fused_score
    FROM lexical l
    FULL OUTER JOIN semantic s USING (evidence_id)
)
SELECT e.evidence_id, e.evidence_type, e.source_name, e.evidence_title, e.evidence_text,
       fused.lexical_score, fused.semantic_score, fused.fused_score, e.metadata
FROM fused
JOIN mosaic.product_evidence e USING (evidence_id)
ORDER BY fused.fused_score DESC, e.evidence_id
LIMIT greatest(result_limit, 1)
$$;
