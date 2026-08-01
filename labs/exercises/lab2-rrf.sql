\set ON_ERROR_STOP on

\if :{?run_id}
\else
  \echo 'REMEDY: pass -v run_id=<retrieval-run-uuid>'
  \quit 1
\endif

BEGIN;

CREATE TEMP TABLE lab2_rrf_checkpoint ON COMMIT DROP AS
WITH receipt AS (
  SELECT
    run.rrf_k,
    run.text_weight,
    run.vector_weight,
    run.fuzzy_weight,
    candidate.*
  FROM proof.retrieval_runs run
  JOIN proof.v_candidate_receipts candidate USING (run_id)
  WHERE run.run_id = :'run_id'::uuid
)
SELECT
  result_rank,
  external_key,
  rrf_score AS stored_rrf,
  (
    /*
     * TODO: add one weighted reciprocal-rank term for each arm.
     *
     * Inputs:
     *   text_weight,   text_position
     *   vector_weight, vector_position
     *   fuzzy_weight,  trigram_position
     *   rrf_k
     *
     * Rules:
     *   - combine rank positions, never raw arm scores;
     *   - a missing arm contributes zero;
     *   - keep the arithmetic numeric.
     */
    NULL::numeric
  ) AS recomputed_rrf
FROM receipt;

SELECT
  result_rank,
  external_key,
  round(stored_rrf, 6) AS stored_rrf,
  round(recomputed_rrf, 6) AS recomputed_rrf,
  recomputed_rrf IS NOT NULL
    AND abs(stored_rrf - recomputed_rrf) < 0.0000000001 AS matches
FROM lab2_rrf_checkpoint
ORDER BY result_rank;

DO $checkpoint$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM lab2_rrf_checkpoint
    WHERE recomputed_rrf IS NULL
       OR abs(stored_rrf - recomputed_rrf) >= 0.0000000001
  ) THEN
    RAISE EXCEPTION
      'REMEDY: complete the weighted-RRF expression; every row must match';
  END IF;
END
$checkpoint$;

\echo 'OK: participant SQL recomputed every persisted RRF score'
ROLLBACK;
