-- The stale two-arg DROP predates p_principal (A6) and has been a no-op since
-- p_principal was added: p_principal was never dropped, only shadowed by a new
-- overload. Extending rather than replacing so both dead overloads are gone.
DROP FUNCTION IF EXISTS retrieval.traverse_evidence(uuid[], integer);
DROP FUNCTION IF EXISTS retrieval.traverse_evidence(uuid[], integer, jsonb);

CREATE OR REPLACE FUNCTION retrieval.traverse_evidence(
  p_seed_evidence_ids uuid[],
  p_max_depth integer DEFAULT 3,
  p_role name DEFAULT current_user
)
RETURNS TABLE (
  evidence_id uuid,
  evidence_kind text,
  external_key text,
  title text,
  depth integer,
  path uuid[],
  via_edge_key text,
  via_relation text,
  via_origin text,
  via_confidence numeric
)
LANGUAGE sql
STABLE
AS $$
WITH RECURSIVE walk AS (
  SELECT
    seed.evidence_id,
    0 AS depth,
    ARRAY[seed.evidence_id]::uuid[] AS path,
    NULL::text AS via_edge_key,
    NULL::text AS via_relation,
    NULL::text AS via_origin,
    NULL::numeric AS via_confidence
  FROM unnest(p_seed_evidence_ids) AS seed(evidence_id)
  JOIN casework.evidence_items seed_item
    ON seed_item.evidence_id = seed.evidence_id
   AND NOT seed_item.is_deleted
   AND retrieval.acl_visible(seed_item.acl, p_role)

  UNION ALL

  SELECT
    neighbor.evidence_id,
    walk.depth + 1,
    walk.path || neighbor.evidence_id,
    edge.edge_key,
    edge.relation,
    edge.origin,
    edge.confidence
  FROM walk
  JOIN retrieval.evidence_edges edge
    ON edge.from_evidence_id = walk.evidence_id
    OR edge.to_evidence_id = walk.evidence_id
  CROSS JOIN LATERAL (
    SELECT CASE
      WHEN edge.from_evidence_id = walk.evidence_id THEN edge.to_evidence_id
      ELSE edge.from_evidence_id
    END AS evidence_id
  ) neighbor
  JOIN casework.evidence_items neighbor_item
    ON neighbor_item.evidence_id = neighbor.evidence_id
   AND NOT neighbor_item.is_deleted
   AND retrieval.acl_visible(neighbor_item.acl, p_role)
  WHERE walk.depth < greatest(0, least(p_max_depth, 8))
    AND NOT neighbor.evidence_id = ANY(walk.path)
),
best_path AS (
  SELECT DISTINCT ON (walk.evidence_id)
    walk.*
  FROM walk
  ORDER BY walk.evidence_id, walk.depth, walk.via_confidence DESC NULLS LAST
)
SELECT
  item.evidence_id,
  item.evidence_kind,
  item.external_key,
  item.title,
  best_path.depth,
  best_path.path,
  best_path.via_edge_key,
  best_path.via_relation,
  best_path.via_origin,
  best_path.via_confidence
FROM best_path
JOIN casework.evidence_items item ON item.evidence_id = best_path.evidence_id
ORDER BY best_path.depth, item.evidence_kind, item.external_key
$$;
