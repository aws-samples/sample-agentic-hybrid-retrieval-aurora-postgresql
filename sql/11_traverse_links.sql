-- ---------------------------------------------------------------------------
-- Recursive object_links traversal — the cross-system evidence walk.
--
-- ops.traverse_links(seeds, max_depth, allowed_ids) walks ops.object_links from a
-- set of seed objects outward, breadth-first, to a bounded depth, returning every
-- reachable object with the depth it was first reached at and the external_id path
-- taken to get there. This is the real primitive the UI and agent already credit:
-- the Timeline is "assembled by traverse_links() over object_links" and the agent's
-- follow_evidence_links tool walks the same graph to pull in linked evidence a
-- single retrieval arm would miss (the PR that fixes the ticket, the case it
-- impacts) across Slack / Jira / Confluence / Salesforce / GitHub.
--
-- Cycle protection is mandatory: object_links carries mirror pairs (A references B
-- and B referenced_by A) and at least one true cycle (ORION-1473 caused ORION-1489,
-- ORION-1489 caused_by ORION-1473), so an unguarded walk would recurse forever. The
-- recursion carries the visited external_id path and refuses to re-enter a node
-- already on that path (NOT to_.external_id = ANY(w.path)).
--
-- p_allowed_ids optionally confines the walk to a working set (e.g. a run's cited
-- objects). When NULL the walk is unconfined and follows every link. When a run's
-- cited set is already a closed component (every link's endpoints are cited), the
-- confined and unconfined walks reach the SAME nodes — which is why deriving the
-- evidence graph through this function leaves the canonical Orion graph unchanged.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION ops.traverse_links(
  p_seed_ids uuid[],
  p_max_depth int DEFAULT 3,
  p_allowed_ids uuid[] DEFAULT NULL
)
RETURNS TABLE (
  object_id uuid,
  external_id text,
  source_system text,
  source_type text,
  title text,
  depth int,
  path text[],
  via_link_id uuid,
  via_link_type text,
  via_confidence numeric,
  parent_object_id uuid
)
LANGUAGE sql
STABLE
AS $$
  WITH RECURSIVE walk AS (
    -- Depth 0: the seed objects themselves, reached via no link.
    SELECT o.object_id,
           o.external_id,
           o.source_system,
           o.source_type,
           o.title,
           0                       AS depth,
           ARRAY[o.external_id]    AS path,
           NULL::uuid              AS via_link_id,
           NULL::text              AS via_link_type,
           NULL::numeric           AS via_confidence,
           NULL::uuid              AS parent_object_id
    FROM ops.source_objects o
    WHERE o.object_id = ANY(p_seed_ids)
      AND (p_allowed_ids IS NULL OR o.object_id = ANY(p_allowed_ids))

    UNION ALL

    -- Step outward one link at a time, staying under the depth bound, never
    -- re-entering a node already on this path, and (when confined) never leaving
    -- the allowed working set.
    SELECT to_.object_id,
           to_.external_id,
           to_.source_system,
           to_.source_type,
           to_.title,
           w.depth + 1                    AS depth,
           w.path || to_.external_id       AS path,
           l.link_id                       AS via_link_id,
           l.link_type                     AS via_link_type,
           l.confidence                    AS via_confidence,
           w.object_id                     AS parent_object_id
    FROM walk w
    JOIN ops.object_links l ON l.from_object_id = w.object_id
    JOIN ops.source_objects to_ ON to_.object_id = l.to_object_id
    WHERE w.depth < p_max_depth
      AND NOT to_.external_id = ANY(w.path)
      AND (p_allowed_ids IS NULL OR to_.object_id = ANY(p_allowed_ids))
  )
  -- One row per object at its SHALLOWEST reach (a node reachable by several paths
  -- is emitted once, via the lowest-depth / highest-confidence link).
  SELECT DISTINCT ON (object_id)
         object_id, external_id, source_system, source_type, title,
         depth, path, via_link_id, via_link_type, via_confidence, parent_object_id
  FROM walk
  ORDER BY object_id, depth, via_confidence DESC NULLS LAST;
$$;

COMMENT ON FUNCTION ops.traverse_links(uuid[], int, uuid[]) IS
  'Breadth-first, cycle-protected walk of ops.object_links from seed objects to a '
  'bounded depth. Returns each reachable object once at its shallowest depth with '
  'the external_id path taken. p_allowed_ids confines the walk to a working set '
  '(NULL = unconfined). Powers the evidence graph/timeline and the agent''s '
  'follow_evidence_links tool.';
