CREATE OR REPLACE FUNCTION ops.precision_at_k(p_query_id text, p_run_id uuid, p_k int DEFAULT 10)
RETURNS numeric
LANGUAGE sql
STABLE
AS $$
WITH ranked AS (
  SELECT o.external_id, row_number() OVER (ORDER BY rc.final_score DESC) AS pos
  FROM ops.retrieval_candidates rc
  JOIN ops.source_objects o ON o.object_id = rc.object_id
  WHERE rc.run_id = p_run_id
), topk AS (
  SELECT * FROM ranked WHERE pos <= p_k
), rel AS (
  SELECT object_external_id
  FROM ops.relevance_judgments
  WHERE query_id = p_query_id AND relevance > 0
)
SELECT coalesce(sum(CASE WHEN rel.object_external_id IS NOT NULL THEN 1 ELSE 0 END)::numeric / nullif(p_k,0), 0)
FROM topk
LEFT JOIN rel ON rel.object_external_id = topk.external_id;
$$;
