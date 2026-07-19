-- ---------------------------------------------------------------------------
-- ACL demonstration seed.
--
-- The corpus ships with every object at acl = {"visibility": "workshop_lab"},
-- which every workshop principal carries as a clearance, so retrieval is
-- unchanged for the default audience. To make row-level ACL enforcement
-- observable, this marks exactly ONE non-canonical object as restricted:
--
--   CASE-20919 (salesforce Case, "p95 latency regression after release")
--
-- After this runs, a principal WITHOUT the 'restricted' clearance can no longer
-- retrieve CASE-20919 through any arm of ops.hybrid_search / full_text_search /
-- vector_search / fuzzy_match (ops.acl_visible filters it out in the base scan),
-- while a principal carrying {"clearances": ["workshop_lab", "restricted"]} still
-- sees it. The default (p_principal IS NULL) context is unaffected.
--
-- CASE-20919 is deliberately outside the canonical Orion closed link component
-- (CASE-0012345, ORION-1473, ORION-1489, PAGE-2112, PR-1287, SLACK-000271), so
-- restricting it cannot perturb the byte-identical "Why did Orion slip?" answer,
-- which is served from ops.agent_answers and never recomputed via hybrid_search.
--
-- Idempotent: re-running sets the same value. Data-only, safe on a fresh schema
-- or a restored dump.
-- ---------------------------------------------------------------------------

UPDATE ops.source_objects
SET acl = jsonb_build_object('visibility', 'restricted')
WHERE external_id = 'CASE-20919';
