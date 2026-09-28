\set ON_ERROR_STOP on

-- Evidence search: the specification and review passages an answer may cite,
-- ranked within one product by the same fusion the product search uses.

DROP FUNCTION IF EXISTS mosaic_search.search_product_evidence(
    bigint, text, vector, mosaic.evidence_type[], integer
);

CREATE OR REPLACE FUNCTION mosaic_search.search_product_evidence(
    p_product_id bigint,
    q text,
    query_embedding vector(1024),
    p_evidence_types mosaic.evidence_type[],
    result_limit integer,
    p_rrf_k integer,
    lexical_limit integer,
    semantic_limit integer
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
      AND e.is_current
      AND (p_evidence_types IS NULL OR e.evidence_type = ANY (p_evidence_types))
      AND e.evidence_document @@ websearch_to_tsquery('english', q)
    ORDER BY score DESC, e.evidence_id
    LIMIT greatest(lexical_limit, 1)
), semantic AS (
    SELECT e.evidence_id,
           (
               1 - (
                   CASE
                       WHEN e.embedding IS NOT NULL THEN e.embedding
                       ELSE d.embedding
                   END <=> query_embedding
               )
           )::real AS score,
           row_number() OVER (
               ORDER BY
                   CASE
                       WHEN e.embedding IS NOT NULL THEN e.embedding
                       ELSE d.embedding
                   END <=> query_embedding,
                   e.evidence_id
           ) AS rank
    FROM mosaic.product_evidence e
    JOIN mosaic_search.product_document d USING (product_id)
    WHERE e.product_id = p_product_id
      AND e.is_current
      AND (
          e.embedding IS NOT NULL
          OR (
              e.evidence_type = 'product_spec'::mosaic.evidence_type
              AND d.embedding IS NOT NULL
          )
      )
      AND (p_evidence_types IS NULL OR e.evidence_type = ANY (p_evidence_types))
    ORDER BY
        CASE
            WHEN e.embedding IS NOT NULL THEN e.embedding
            ELSE d.embedding
        END <=> query_embedding,
        e.evidence_id
    LIMIT greatest(semantic_limit, 1)
), fused AS (
    SELECT coalesce(l.evidence_id, s.evidence_id) AS evidence_id,
           l.score AS lexical_score,
           s.score AS semantic_score,
           coalesce(
               mosaic_search.reciprocal_rank_contribution(
                   l.rank::integer, p_rrf_k
               ),
               0
           ) + coalesce(
               mosaic_search.reciprocal_rank_contribution(
                   s.rank::integer, p_rrf_k
               ),
               0
           ) AS fused_score
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
