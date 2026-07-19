-- Retrieval quality metrics over judged relevance.
--
-- ops.precision_at_k (sql/05) answers "what fraction of the top-k is relevant."
-- These add the three metrics a retrieval eval actually reports:
--   recall@k  — of all judged-relevant objects, how many made the top-k
--   MRR       — 1 / rank of the first relevant object (0 if none retrieved)
--   nDCG@k    — graded ranking quality vs the ideal ordering, using the 0..3 grades
--
-- Every function ranks a run's candidates in the SAME order the app presents them
-- (rerank_score first when present, then final_score), so the metric scores the
-- ranking a workshop attendee actually sees. Relevance grades live in
-- ops.relevance_judgments (0 = not relevant, 1..3 = graded relevant).

-- Position of each cited object within a run, in presented order.
CREATE OR REPLACE FUNCTION ops.eval_ranked(p_run_id uuid)
RETURNS TABLE (external_id text, pos int)
LANGUAGE sql
STABLE
AS $$
  SELECT o.external_id,
         row_number() OVER (
           ORDER BY
             CASE WHEN rc.rerank_score IS NULL THEN 1 ELSE 0 END,
             rc.rerank_score DESC NULLS LAST,
             rc.final_score DESC NULLS LAST
         )::int AS pos
  FROM ops.retrieval_candidates rc
  JOIN ops.source_objects o ON o.object_id = rc.object_id
  WHERE rc.run_id = p_run_id;
$$;

-- recall@k = |relevant ∩ top-k| / |relevant|.
CREATE OR REPLACE FUNCTION ops.recall_at_k(p_query_id text, p_run_id uuid, p_k int DEFAULT 10)
RETURNS numeric
LANGUAGE sql
STABLE
AS $$
WITH rel AS (
  SELECT object_external_id
  FROM ops.relevance_judgments
  WHERE query_id = p_query_id AND relevance > 0
), topk AS (
  SELECT external_id FROM ops.eval_ranked(p_run_id) WHERE pos <= p_k
)
SELECT coalesce(
  count(*) FILTER (WHERE topk.external_id IS NOT NULL)::numeric
    / nullif((SELECT count(*) FROM rel), 0),
  0)
FROM rel
LEFT JOIN topk ON topk.external_id = rel.object_external_id;
$$;

-- Mean reciprocal rank of the first relevant object (single query -> reciprocal rank).
CREATE OR REPLACE FUNCTION ops.mrr(p_query_id text, p_run_id uuid)
RETURNS numeric
LANGUAGE sql
STABLE
AS $$
WITH rel AS (
  SELECT object_external_id
  FROM ops.relevance_judgments
  WHERE query_id = p_query_id AND relevance > 0
), hits AS (
  SELECT r.pos
  FROM ops.eval_ranked(p_run_id) r
  JOIN rel ON rel.object_external_id = r.external_id
)
SELECT coalesce(1.0 / min(pos), 0) FROM hits;
$$;

-- nDCG@k over graded relevance: DCG of the run's top-k vs the ideal DCG.
CREATE OR REPLACE FUNCTION ops.ndcg_at_k(p_query_id text, p_run_id uuid, p_k int DEFAULT 10)
RETURNS numeric
LANGUAGE sql
STABLE
AS $$
WITH graded AS (
  SELECT object_external_id, relevance
  FROM ops.relevance_judgments
  WHERE query_id = p_query_id
), dcg AS (
  -- Gain of each retrieved top-k object at its presented position.
  SELECT sum(
    (2 ^ coalesce(g.relevance, 0) - 1) / log(2, r.pos + 1)
  ) AS value
  FROM ops.eval_ranked(p_run_id) r
  LEFT JOIN graded g ON g.object_external_id = r.external_id
  WHERE r.pos <= p_k
), ideal AS (
  -- Ideal DCG: judged objects sorted by relevance desc, capped at k.
  SELECT sum(
    (2 ^ relevance - 1) / log(2, ideal_pos + 1)
  ) AS value
  FROM (
    SELECT relevance,
           row_number() OVER (ORDER BY relevance DESC) AS ideal_pos
    FROM graded
    WHERE relevance > 0
  ) ranked
  WHERE ideal_pos <= p_k
)
SELECT coalesce((SELECT value FROM dcg) / nullif((SELECT value FROM ideal), 0), 0);
$$;

-- One row per (eval query, retrieval run) with all four metrics, for the runs
-- whose query_text matches an evaluation query. The /v1/evaluation endpoint fires
-- one run per mode against each eval query; this view scores them side by side.
CREATE OR REPLACE VIEW ops.v_eval_comparison AS
SELECT
  eq.query_id,
  eq.query_text,
  rr.run_id,
  rr.retrieval_mode,
  rr.created_at,
  ops.recall_at_k(eq.query_id, rr.run_id, 5)   AS recall_at_5,
  ops.recall_at_k(eq.query_id, rr.run_id, 10)  AS recall_at_10,
  ops.precision_at_k(eq.query_id, rr.run_id, 10) AS precision_at_10,
  ops.mrr(eq.query_id, rr.run_id)              AS mrr,
  ops.ndcg_at_k(eq.query_id, rr.run_id, 10)    AS ndcg_at_10
FROM ops.evaluation_queries eq
JOIN ops.retrieval_runs rr ON rr.query_text = eq.query_text
ORDER BY eq.query_id, rr.created_at DESC;
