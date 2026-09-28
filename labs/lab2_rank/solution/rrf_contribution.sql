-- Lab 2: the reciprocal rank fusion contribution.
--
-- Lab 1's mosaic_search.search_hybrid_rrf adds this contribution once for each
-- channel that found a product, so it alone decides how channel ranks combine.
-- The marked block is Lab 2's edit; README.md beside this file has the task,
-- the commands and the reference answer.

CREATE OR REPLACE FUNCTION mosaic_search.reciprocal_rank_contribution(
    source_rank bigint,
    rrf_k integer
)
RETURNS double precision
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
-- Lab 2 edit: one channel's contribution. See README.md beside this file.
-- LAB2_RRF_FORMULA_START
SELECT
    1.0::double precision
    / (
        rrf_k::double precision
        + source_rank::double precision
    )
-- LAB2_RRF_FORMULA_END
$$;
