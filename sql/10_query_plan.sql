-- ---------------------------------------------------------------------------
-- Query-plan and statistics surfaces for the Diagnostics view.
--
-- ops.query_plan       — EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) over the real
--                        retrieval arm query bodies, so a builder can watch which
--                        index the planner actually chooses (or rejects).
-- ops.v_index_usage    — live pg_stat_user_indexes for the ops schema: scan counts
--                        and on-disk size per index, with the access method (GIN /
--                        HNSW / btree) so "is my HNSW index even used?" is answerable.
-- ops.v_slow_queries   — pg_stat_statements ranked by mean execution time, scoped to
--                        the retrieval queries, with buffer cache-hit ratio.
--
-- Why EXPLAIN the arm BODIES and not the deployed functions: ops.hybrid_search,
-- ops.full_text_search, ops.vector_search, and ops.fuzzy_match are SQL set-returning
-- functions, and Postgres never inlines an SRF for EXPLAIN — every function call
-- plans to an opaque `Function Scan` node that hides the GIN / HNSW / Seq Scan
-- decision underneath. To expose the real scan the retrieval performs, this function
-- EXPLAINs the arm query bodies directly. Those bodies MIRROR the arm CTEs in
-- sql/03_search_functions.sql (text_hits / vector_hits / trgm_hits) and the
-- single-signal functions; sql/03 is the source of truth. Keep the FROM / JOIN /
-- WHERE / ORDER BY here in sync with sql/03 when the retrieval arms change, or the
-- plan will describe a query the app no longer runs. Only source_system and
-- project_key filters are wired here (the two common facets) — enough to show a
-- filtered plan without reproducing the full filter surface.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION ops.query_plan(
  p_arm text,
  p_query text,
  p_query_embedding vector(1024) DEFAULT NULL,
  p_limit int DEFAULT 10,
  p_source_systems text[] DEFAULT NULL,
  p_project_key text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
  v_plan jsonb;
  v_stmt text;
BEGIN
  IF p_arm = 'lexical' THEN
    -- Mirrors ops.full_text_search / hybrid_search text_hits: matches the chunk body
    -- GIN(tsv) OR the object-level GIN(search_tsv) (external_id + title at weight A),
    -- ranked by the summed ts_rank_cd — the exact-ID lexical fix.
    v_stmt :=
      'SELECT c.chunk_id, '
      '  (coalesce(ts_rank_cd(c.tsv, ops.to_or_tsquery($1)), 0) '
      '   + coalesce(ts_rank_cd(o.search_tsv, ops.to_or_tsquery($1)), 0))::numeric AS score '
      'FROM ops.object_chunks c '
      'JOIN ops.source_objects o ON o.object_id = c.object_id '
      'WHERE o.is_active '
      '  AND ops.to_or_tsquery($1) IS NOT NULL '
      '  AND (c.tsv @@ ops.to_or_tsquery($1) OR o.search_tsv @@ ops.to_or_tsquery($1)) '
      '  AND ($2::text[] IS NULL OR o.source_system = ANY($2)) '
      '  AND ($3::text IS NULL OR o.project_key = $3) '
      'ORDER BY score DESC LIMIT $4';
    EXECUTE 'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' || v_stmt
      INTO v_plan
      USING p_query, p_source_systems, p_project_key, p_limit;

  ELSIF p_arm = 'semantic' THEN
    -- Mirrors ops.vector_search / hybrid_search vector_hits: HNSW(embedding) candidate.
    IF p_query_embedding IS NULL THEN
      RAISE EXCEPTION 'semantic arm requires a query embedding';
    END IF;
    v_stmt :=
      'SELECT c.chunk_id, (1 - (c.embedding <=> $1))::numeric AS score '
      'FROM ops.object_chunks c '
      'JOIN ops.source_objects o ON o.object_id = c.object_id '
      'WHERE o.is_active '
      '  AND c.embedding IS NOT NULL '
      '  AND ($2::text[] IS NULL OR o.source_system = ANY($2)) '
      '  AND ($3::text IS NULL OR o.project_key = $3) '
      'ORDER BY c.embedding <=> $1 ASC LIMIT $4';
    EXECUTE 'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' || v_stmt
      INTO v_plan
      USING p_query_embedding, p_source_systems, p_project_key, p_limit;

  ELSIF p_arm = 'fuzzy' THEN
    -- Mirrors ops.fuzzy_match / hybrid_search trgm_hits: GIN(trgm) candidate.
    v_stmt :=
      'SELECT c.chunk_id, '
      '  greatest(similarity(o.title, $1), similarity(left(c.chunk_text, 500), $1))::numeric AS score '
      'FROM ops.object_chunks c '
      'JOIN ops.source_objects o ON o.object_id = c.object_id '
      'WHERE o.is_active '
      '  AND greatest(similarity(o.title, $1), similarity(left(c.chunk_text, 500), $1)) > 0.08 '
      '  AND ($2::text[] IS NULL OR o.source_system = ANY($2)) '
      '  AND ($3::text IS NULL OR o.project_key = $3) '
      'ORDER BY score DESC LIMIT $4';
    EXECUTE 'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' || v_stmt
      INTO v_plan
      USING p_query, p_source_systems, p_project_key, p_limit;

  ELSE
    RAISE EXCEPTION 'unknown arm %, expected one of lexical / semantic / fuzzy', p_arm;
  END IF;

  RETURN jsonb_build_object(
    'arm', p_arm,
    'statement', v_stmt,
    'plan', v_plan -> 0
  );
END;
$$;

-- Live index usage for the ops schema. idx_scan = 0 on the GIN / HNSW indexes at
-- small corpus size is expected and honest: the planner picks a Seq Scan until the
-- table is large enough for the index to win. The access method column makes the
-- GIN / HNSW / btree distinction explicit for the workshop.
CREATE OR REPLACE VIEW ops.v_index_usage AS
SELECT
  s.relname            AS table_name,
  s.indexrelname       AS index_name,
  am.amname            AS method,
  s.idx_scan           AS scans,
  s.idx_tup_read       AS tuples_read,
  s.idx_tup_fetch      AS tuples_fetched,
  pg_size_pretty(pg_relation_size(s.indexrelid)) AS index_size,
  pg_relation_size(s.indexrelid)                 AS index_bytes
FROM pg_stat_user_indexes s
JOIN pg_class c  ON c.oid = s.indexrelid
JOIN pg_am    am ON am.oid = c.relam
WHERE s.schemaname = 'ops'
ORDER BY s.idx_scan DESC, index_bytes DESC;

-- The retrieval queries ranked by mean execution time, from pg_stat_statements,
-- with the buffer cache-hit ratio. Scoped to statements that touch the corpus
-- tables / retrieval functions so the workshop sees the real hot path, not the
-- monitoring queries. Requires pg_stat_statements to be preloaded and readable.
CREATE OR REPLACE VIEW ops.v_slow_queries AS
SELECT
  s.queryid,
  left(regexp_replace(s.query, '\s+', ' ', 'g'), 240) AS query,
  s.calls,
  round(s.total_exec_time::numeric, 2) AS total_exec_ms,
  round(s.mean_exec_time::numeric, 2)  AS mean_exec_ms,
  round(s.stddev_exec_time::numeric, 2) AS stddev_exec_ms,
  s.rows,
  s.shared_blks_hit,
  s.shared_blks_read,
  CASE
    WHEN (s.shared_blks_hit + s.shared_blks_read) > 0
    THEN round(100.0 * s.shared_blks_hit / (s.shared_blks_hit + s.shared_blks_read), 1)
    ELSE NULL
  END AS cache_hit_pct
FROM pg_stat_statements s
WHERE s.query ILIKE ANY (ARRAY[
        '%ops.object_chunks%', '%ops.source_objects%',
        '%ops.hybrid_search%', '%ops.vector_search%',
        '%ops.full_text_search%', '%ops.fuzzy_match%'
      ])
  AND s.query NOT ILIKE '%pg_stat_statements%'
  AND s.query NOT ILIKE '%v_slow_queries%'
ORDER BY s.mean_exec_time DESC
LIMIT 25;
