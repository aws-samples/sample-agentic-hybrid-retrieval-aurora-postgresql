CREATE OR REPLACE FUNCTION proof.recall_at_k(
  p_query_id text,
  p_run_id uuid,
  p_k integer
)
RETURNS numeric
LANGUAGE sql
STABLE
AS $$
WITH relevant AS (
  SELECT count(*)::numeric AS total
  FROM proof.relevance_judgments
  WHERE query_id = p_query_id
    AND relevance > 0
),
retrieved AS (
  SELECT count(*)::numeric AS hits
  FROM proof.retrieval_candidates candidate
  JOIN proof.relevance_judgments judgment
    ON judgment.query_id = p_query_id
   AND judgment.evidence_id = candidate.evidence_id
  WHERE candidate.run_id = p_run_id
    AND candidate.result_rank <= p_k
    AND judgment.relevance > 0
)
SELECT
  CASE
    WHEN relevant.total = 0 THEN 0
    ELSE retrieved.hits / relevant.total
  END
FROM relevant, retrieved
$$;

CREATE OR REPLACE FUNCTION proof.precision_at_k(
  p_query_id text,
  p_run_id uuid,
  p_k integer
)
RETURNS numeric
LANGUAGE sql
STABLE
AS $$
SELECT
  count(*) FILTER (WHERE coalesce(judgment.relevance, 0) > 0)::numeric
  / greatest(1, p_k)
FROM proof.retrieval_candidates candidate
LEFT JOIN proof.relevance_judgments judgment
  ON judgment.query_id = p_query_id
 AND judgment.evidence_id = candidate.evidence_id
WHERE candidate.run_id = p_run_id
  AND candidate.result_rank <= p_k
$$;

CREATE OR REPLACE FUNCTION proof.mrr(
  p_query_id text,
  p_run_id uuid
)
RETURNS numeric
LANGUAGE sql
STABLE
AS $$
SELECT coalesce(
  max(1.0 / candidate.result_rank) FILTER (WHERE judgment.relevance > 0),
  0
)::numeric
FROM proof.retrieval_candidates candidate
JOIN proof.relevance_judgments judgment
  ON judgment.query_id = p_query_id
 AND judgment.evidence_id = candidate.evidence_id
WHERE candidate.run_id = p_run_id
$$;

CREATE OR REPLACE FUNCTION proof.ndcg_at_k(
  p_query_id text,
  p_run_id uuid,
  p_k integer
)
RETURNS numeric
LANGUAGE sql
STABLE
AS $$
WITH actual AS (
  SELECT coalesce(
    sum(
      (power(2::numeric, coalesce(judgment.relevance, 0)) - 1)
      / (ln(candidate.result_rank + 1) / ln(2::numeric))
    ),
    0
  ) AS dcg
  FROM proof.retrieval_candidates candidate
  LEFT JOIN proof.relevance_judgments judgment
    ON judgment.query_id = p_query_id
   AND judgment.evidence_id = candidate.evidence_id
  WHERE candidate.run_id = p_run_id
    AND candidate.result_rank <= p_k
),
ideal_ranks AS (
  SELECT
    relevance,
    row_number() OVER (ORDER BY relevance DESC, evidence_id)::integer AS ideal_rank
  FROM proof.relevance_judgments
  WHERE query_id = p_query_id
    AND relevance > 0
),
ideal AS (
  SELECT coalesce(
    sum(
      (power(2::numeric, relevance) - 1)
      / (ln(ideal_rank + 1) / ln(2::numeric))
    ),
    0
  ) AS idcg
  FROM ideal_ranks
  WHERE ideal_rank <= p_k
)
SELECT
  CASE
    WHEN ideal.idcg = 0 THEN 0
    ELSE actual.dcg / ideal.idcg
  END
FROM actual, ideal
$$;

CREATE OR REPLACE VIEW proof.v_evaluation_results AS
SELECT
  run.filters ->> 'evaluation_query_id' AS query_id,
  run.run_id,
  run.retrieval_mode,
  proof.recall_at_k(run.filters ->> 'evaluation_query_id', run.run_id, 5) AS recall_at_5,
  proof.recall_at_k(run.filters ->> 'evaluation_query_id', run.run_id, 10) AS recall_at_10,
  proof.precision_at_k(run.filters ->> 'evaluation_query_id', run.run_id, 10) AS precision_at_10,
  proof.mrr(run.filters ->> 'evaluation_query_id', run.run_id) AS mrr,
  proof.ndcg_at_k(run.filters ->> 'evaluation_query_id', run.run_id, 10) AS ndcg_at_10,
  run.completed_at
FROM proof.retrieval_runs run
WHERE run.status = 'complete'
  AND run.filters ? 'evaluation_query_id';
